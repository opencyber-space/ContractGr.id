use std::sync::Arc;
use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};
use std::time::Instant;

use tokio::sync::mpsc;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::core::types::{KeyEvent, ProcessingResult, Receipt};
use crate::core::validator::EventValidator;
use crate::crypto::{self, KeyPair};
use crate::db::repository::WitnessRepository;
use crate::utils::errors::{WitnessError, WitnessResult};
use crate::utils::metrics;

pub struct EventProcessor {
    repo: Arc<dyn WitnessRepository>,
    validator: Arc<EventValidator>,
    key_pair: Arc<KeyPair>,
    witness_aid: String,
    tx: mpsc::Sender<KeyEvent>,
    stats: Arc<ProcessorStats>,
}

struct ProcessorStats {
    processed: AtomicU64,
    rejected: AtomicU64,
    duplicity: AtomicU64,
    escrowed: AtomicU64,
    receipts_issued: AtomicU64,
    queue_depth: AtomicI64,
}

impl ProcessorStats {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            processed: AtomicU64::new(0),
            rejected: AtomicU64::new(0),
            duplicity: AtomicU64::new(0),
            escrowed: AtomicU64::new(0),
            receipts_issued: AtomicU64::new(0),
            queue_depth: AtomicI64::new(0),
        })
    }
}

impl EventProcessor {
    pub fn new(
        repo: Arc<dyn WitnessRepository>,
        key_pair: Arc<KeyPair>,
        queue_size: usize,
        num_workers: usize,
    ) -> Self {
        let validator = Arc::new(EventValidator::new(Arc::clone(&repo)));
        let witness_aid = key_pair.aid();
        let stats = ProcessorStats::new();
        let (tx, rx) = mpsc::channel::<KeyEvent>(queue_size);

        let rx = Arc::new(tokio::sync::Mutex::new(rx));
        for i in 0..num_workers {
            let rx_clone = Arc::clone(&rx);
            let repo_clone = Arc::clone(&repo);
            let validator_clone = Arc::clone(&validator);
            let key_pair_clone = Arc::clone(&key_pair);
            let stats_clone = Arc::clone(&stats);
            let witness_aid_clone = witness_aid.clone();

            tokio::spawn(async move {
                Self::worker_loop(
                    i,
                    rx_clone,
                    repo_clone,
                    validator_clone,
                    key_pair_clone,
                    stats_clone,
                    witness_aid_clone,
                )
                .await;
            });
        }

        Self { repo, validator, key_pair, witness_aid, tx, stats }
    }

    async fn worker_loop(
        id: usize,
        rx: Arc<tokio::sync::Mutex<mpsc::Receiver<KeyEvent>>>,
        repo: Arc<dyn WitnessRepository>,
        validator: Arc<EventValidator>,
        key_pair: Arc<KeyPair>,
        stats: Arc<ProcessorStats>,
        witness_aid: String,
    ) {
        debug!(worker = id, "Event processor worker started");
        loop {
            let event = {
                let mut guard = rx.lock().await;
                guard.recv().await
            };
            match event {
                Some(ev) => {
                    stats.queue_depth.fetch_sub(1, Ordering::Relaxed);
                    metrics::QUEUE_SIZE.set(stats.queue_depth.load(Ordering::Relaxed) as f64);
                    let _ = Self::process_one(
                        &ev,
                        &repo,
                        &validator,
                        &key_pair,
                        &stats,
                        &witness_aid,
                    )
                    .await;
                }
                None => {
                    info!(worker = id, "Worker channel closed, exiting");
                    break;
                }
            }
        }
    }

    pub async fn submit(&self, event: KeyEvent) -> WitnessResult<()> {
        let depth = self.stats.queue_depth.load(Ordering::Relaxed);
        metrics::QUEUE_SIZE.set(depth as f64);
        metrics::EVENTS_RECEIVED
            .with_label_values(&[event.ilk.as_str(), "api"])
            .inc();

        self.tx.try_send(event).map_err(|_| {
            metrics::EVENTS_REJECTED.with_label_values(&["queue_full"]).inc();
            self.stats.rejected.fetch_add(1, Ordering::Relaxed);
            WitnessError::QueueFull
        })?;
        self.stats.queue_depth.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    pub async fn process_immediate(&self, event: KeyEvent) -> ProcessingResult {
        Self::process_one(
            &event,
            &self.repo,
            &self.validator,
            &self.key_pair,
            &self.stats,
            &self.witness_aid,
        )
        .await
    }

    async fn process_one(
        event: &KeyEvent,
        repo: &Arc<dyn WitnessRepository>,
        validator: &Arc<EventValidator>,
        key_pair: &Arc<KeyPair>,
        stats: &Arc<ProcessorStats>,
        witness_aid: &str,
    ) -> ProcessingResult {
        let start = Instant::now();

        let existing_said = match repo.get_first_seen_said(&event.aid, event.sn).await {
            Ok(s) => s,
            Err(e) => {
                error!(aid = %event.aid, sn = event.sn, error = %e, "DB error checking first-seen");
                stats.rejected.fetch_add(1, Ordering::Relaxed);
                metrics::EVENTS_REJECTED.with_label_values(&["db_error"]).inc();
                return ProcessingResult::rejected(e.to_string());
            }
        };

        if let Some(ref existing) = existing_said {
            if existing != &event.said {
                warn!(
                    aid = %event.aid,
                    sn = event.sn,
                    first = %existing,
                    conflict = %event.said,
                    "DUPLICITY DETECTED"
                );
                stats.duplicity.fetch_add(1, Ordering::Relaxed);
                metrics::DUPLICITY_DETECTED.inc();

                if let Err(e) = repo
                    .record_duplicity(
                        &event.aid,
                        event.sn,
                        existing,
                        &event.said,
                        None,
                        Some(&event.raw),
                        Some(witness_aid),
                    )
                    .await
                {
                    error!(error = %e, "Failed to persist duplicity record");
                }
                return ProcessingResult::duplicate();
            }

            if let Ok(Some(receipt)) = repo.get_receipt(&event.aid, event.sn).await {
                return ProcessingResult::accepted(receipt);
            }
        }

        match validator.validate(event, &event.raw).await {
            Err(WitnessError::Escrowed { aid, sn, reason }) => {
                stats.escrowed.fetch_add(1, Ordering::Relaxed);
                metrics::ESCROW_SIZE.inc();
                if let Err(e) = repo
                    .escrow_event(&aid, &event.raw, &reason, Some(sn), event.said.as_str().into())
                    .await
                {
                    error!(error = %e, "Failed to persist escrowed event");
                }
                return ProcessingResult::escrowed();
            }
            Err(e) => {
                warn!(aid = %event.aid, sn = event.sn, error = %e, "Event validation failed");
                stats.rejected.fetch_add(1, Ordering::Relaxed);
                metrics::EVENTS_REJECTED.with_label_values(&[e.error_code()]).inc();
                return ProcessingResult::rejected(e.to_string());
            }
            Ok(_) => {}
        }

        let coupling = crypto::issue_receipt(key_pair, &event.raw);
        let receipt = Receipt {
            id: Uuid::new_v4(),
            aid: event.aid.clone(),
            sn: event.sn,
            said: event.said.clone(),
            witness_aid: witness_aid.to_string(),
            signature_b64: coupling.signature_b64.clone(),
            issued_at: chrono::Utc::now(),
            ilk: event.ilk.to_string(),
        };

        match repo
            .store_event_and_receipt(event, &receipt)
            .await
        {
            Ok(_) => {
                stats.processed.fetch_add(1, Ordering::Relaxed);
                stats.receipts_issued.fetch_add(1, Ordering::Relaxed);
                metrics::EVENTS_PROCESSED.with_label_values(&[event.ilk.as_str()]).inc();
                metrics::RECEIPTS_ISSUED.with_label_values(&[event.ilk.as_str()]).inc();

                let elapsed_ms = start.elapsed().as_millis();
                debug!(
                    aid = %event.aid,
                    sn = event.sn,
                    ilk = %event.ilk,
                    elapsed_ms = elapsed_ms,
                    "Event processed and receipt issued"
                );

                let _ = Self::retry_escrow_for_aid(
                    &event.aid,
                    event.sn,
                    repo,
                    validator,
                    key_pair,
                    stats,
                    witness_aid,
                )
                .await;

                ProcessingResult::accepted(receipt)
            }
            Err(e) => {
                error!(aid = %event.aid, sn = event.sn, error = %e, "Failed to store event");
                stats.rejected.fetch_add(1, Ordering::Relaxed);
                metrics::EVENTS_REJECTED.with_label_values(&["store_failed"]).inc();
                ProcessingResult::rejected(e.to_string())
            }
        }
    }

    async fn retry_escrow_for_aid(
        aid: &str,
        just_seen_sn: i64,
        repo: &Arc<dyn WitnessRepository>,
        validator: &Arc<EventValidator>,
        key_pair: &Arc<KeyPair>,
        stats: &Arc<ProcessorStats>,
        witness_aid: &str,
    ) {
        let pending = match repo.get_pending_escrow(Some(aid), 20).await {
            Ok(p) => p,
            Err(e) => {
                error!(aid = %aid, error = %e, "Failed to fetch pending escrow");
                return;
            }
        };

        for record in pending {
            let escrowed_sn = match record.sn {
                Some(s) => s,
                None => continue,
            };
            if escrowed_sn > just_seen_sn + 1 {
                continue;
            }

            debug!(aid = %aid, sn = escrowed_sn, "Re-processing escrowed event");

            let parsed: Result<crate::core::types::IncomingEvent, _> =
                serde_json::from_slice(&record.raw_event);

            if let Ok(incoming) = parsed {
                if let Ok(event) = crate::core::validator::parse_incoming_event(
                    &incoming,
                    record.raw_event.clone(),
                ) {
                    let result = Self::process_one(
                        &event, repo, validator, key_pair, stats, witness_aid,
                    )
                    .await;

                    if result.accepted {
                        let _ = repo.resolve_escrow(&record.id).await;
                        metrics::ESCROW_SIZE.dec();
                    } else {
                        let _ = repo.increment_escrow_retry(&record.id).await;
                    }
                }
            }
        }
    }

    pub fn get_stats(&self) -> serde_json::Value {
        serde_json::json!({
            "processed": self.stats.processed.load(Ordering::Relaxed),
            "rejected": self.stats.rejected.load(Ordering::Relaxed),
            "duplicity": self.stats.duplicity.load(Ordering::Relaxed),
            "escrowed": self.stats.escrowed.load(Ordering::Relaxed),
            "receipts_issued": self.stats.receipts_issued.load(Ordering::Relaxed),
            "queue_depth": self.stats.queue_depth.load(Ordering::Relaxed),
        })
    }

    pub fn witness_aid(&self) -> &str {
        &self.witness_aid
    }
}

trait ErrorCode {
    fn error_code(&self) -> &'static str;
}

impl ErrorCode for WitnessError {
    fn error_code(&self) -> &'static str {
        match self {
            WitnessError::Validation { .. } => "validation_error",
            WitnessError::SignatureVerification { .. } => "sig_verify_failed",
            WitnessError::Duplicity { .. } => "duplicity",
            WitnessError::Escrowed { .. } => "escrowed",
            WitnessError::Database(_) | WitnessError::DatabaseMsg(_) => "db_error",
            WitnessError::QueueFull => "queue_full",
            _ => "unknown",
        }
    }
}