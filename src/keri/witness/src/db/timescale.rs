use std::time::Instant;

use async_trait::async_trait;
use chrono::Utc;
use sqlx::{PgPool, Row};
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::core::types::{DuplicityRecord, EscrowRecord, KeyEvent, Receipt, StoredEvent};
use crate::db::repository::{DbHealthStatus, MetricsSnapshot, WitnessRepository};
use crate::utils::errors::{WitnessError, WitnessResult};
use crate::utils::metrics;

pub struct TimescaleRepository {
    pool: PgPool,
}

impl TimescaleRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn connect(config: &crate::utils::config::DatabaseConfig) -> WitnessResult<Self> {
        let pool = Self::build_pool(config).await?;
        info!("TimescaleDB connection pool established");
        Ok(Self { pool })
    }

    async fn build_pool(
        config: &crate::utils::config::DatabaseConfig,
    ) -> WitnessResult<PgPool> {
        let mut last_err: Option<WitnessError> = None;
        for attempt in 1..=5u32 {
            match sqlx::postgres::PgPoolOptions::new()
                .min_connections(config.min_connections)
                .max_connections(config.max_connections)
                .acquire_timeout(config.acquire_timeout())
                .idle_timeout(config.idle_timeout())
                .max_lifetime(config.max_lifetime())
                .connect(&config.url)
                .await
            {
                Ok(pool) => return Ok(pool),
                Err(e) => {
                    let delay = 2u64.pow(attempt - 1);
                    warn!(attempt = attempt, delay_secs = delay, error = %e, "DB connect failed, retrying");
                    last_err = Some(WitnessError::Database(e));
                    tokio::time::sleep(std::time::Duration::from_secs(delay)).await;
                }
            }
        }
        Err(last_err.unwrap_or_else(|| WitnessError::DatabaseMsg("connection failed".into())))
    }

    pub async fn run_migrations(&self) -> WitnessResult<()> {
        sqlx::migrate!("./migrations")
            .run(&self.pool)
            .await
            .map_err(|e| WitnessError::DatabaseMsg(format!("Migration failed: {e}")))?;
        info!("Database migrations applied successfully");
        Ok(())
    }

    fn timed<F, T>(&self, op: &'static str, f: F) -> impl std::future::Future<Output = WitnessResult<T>>
    where
        F: std::future::Future<Output = Result<T, sqlx::Error>>,
    {
        let timer = metrics::DB_QUERY_DURATION.with_label_values(&[op]).start_timer();
        async move {
            let result = f.await.map_err(|e| {
                metrics::DB_ERRORS.with_label_values(&[op]).inc();
                WitnessError::Database(e)
            });
            timer.observe_duration();
            result
        }
    }
}

#[async_trait]
impl WitnessRepository for TimescaleRepository {
    async fn store_event_and_receipt(
        &self,
        event: &KeyEvent,
        receipt: &Receipt,
    ) -> WitnessResult<()> {
        let timer = metrics::DB_QUERY_DURATION
            .with_label_values(&["store_event_and_receipt"])
            .start_timer();

        let mut tx = self.pool.begin().await.map_err(WitnessError::Database)?;

        sqlx::query(
            r#"
            INSERT INTO key_events
                (first_seen_at, aid, sn, said, ilk, raw_event, prior_said, receipted, receipt_sig)
            VALUES (NOW(), $1, $2, $3, $4, $5, $6, TRUE, $7)
            ON CONFLICT (aid, sn, said) DO UPDATE
                SET receipted = TRUE, receipt_sig = EXCLUDED.receipt_sig
            "#,
        )
        .bind(&event.aid)
        .bind(event.sn)
        .bind(&event.said)
        .bind(event.ilk.as_str())
        .bind(&event.raw)
        .bind(&event.prior_said)
        .bind(&receipt.signature_b64)
        .execute(&mut *tx)
        .await
        .map_err(|e| {
            metrics::DB_ERRORS.with_label_values(&["store_event"]).inc();
            WitnessError::Database(e)
        })?;

        sqlx::query(
            r#"
            INSERT INTO receipts
                (id, issued_at, aid, sn, said, witness_aid, signature_b64, ilk)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7)
            ON CONFLICT (aid, sn) DO UPDATE
                SET signature_b64 = EXCLUDED.signature_b64,
                    issued_at = NOW()
            "#,
        )
        .bind(receipt.id)
        .bind(&receipt.aid)
        .bind(receipt.sn)
        .bind(&receipt.said)
        .bind(&receipt.witness_aid)
        .bind(&receipt.signature_b64)
        .bind(&receipt.ilk)
        .execute(&mut *tx)
        .await
        .map_err(|e| {
            metrics::DB_ERRORS.with_label_values(&["store_receipt"]).inc();
            WitnessError::Database(e)
        })?;

        tx.commit().await.map_err(WitnessError::Database)?;
        timer.observe_duration();
        Ok(())
    }

    async fn get_event(&self, aid: &str, sn: i64) -> WitnessResult<Option<StoredEvent>> {
        let row = sqlx::query(
            r#"
            SELECT aid, sn, said, ilk, raw_event, prior_said, first_seen_at, receipted, receipt_sig
            FROM key_events
            WHERE aid = $1 AND sn = $2
            ORDER BY first_seen_at ASC
            LIMIT 1
            "#,
        )
        .bind(aid)
        .bind(sn)
        .fetch_optional(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(row.map(|r| StoredEvent {
            aid: r.get("aid"),
            sn: r.get("sn"),
            said: r.get("said"),
            ilk: r.get("ilk"),
            raw_event: r.get::<Vec<u8>, _>("raw_event"),
            prior_said: r.get("prior_said"),
            first_seen_at: r.get("first_seen_at"),
            receipted: r.get("receipted"),
            receipt_sig: r.get("receipt_sig"),
        }))
    }

    async fn get_kel(
        &self,
        aid: &str,
        from_sn: i64,
        limit: i64,
    ) -> WitnessResult<Vec<StoredEvent>> {
        let rows = sqlx::query(
            r#"
            SELECT aid, sn, said, ilk, raw_event, prior_said, first_seen_at, receipted, receipt_sig
            FROM key_events
            WHERE aid = $1 AND sn >= $2
            ORDER BY sn ASC
            LIMIT $3
            "#,
        )
        .bind(aid)
        .bind(from_sn)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(rows
            .into_iter()
            .map(|r| StoredEvent {
                aid: r.get("aid"),
                sn: r.get("sn"),
                said: r.get("said"),
                ilk: r.get("ilk"),
                raw_event: r.get::<Vec<u8>, _>("raw_event"),
                prior_said: r.get("prior_said"),
                first_seen_at: r.get("first_seen_at"),
                receipted: r.get("receipted"),
                receipt_sig: r.get("receipt_sig"),
            })
            .collect())
    }

    async fn get_latest_event(&self, aid: &str) -> WitnessResult<Option<StoredEvent>> {
        let row = sqlx::query(
            r#"
            SELECT aid, sn, said, ilk, raw_event, prior_said, first_seen_at, receipted, receipt_sig
            FROM key_events
            WHERE aid = $1
            ORDER BY sn DESC
            LIMIT 1
            "#,
        )
        .bind(aid)
        .fetch_optional(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(row.map(|r| StoredEvent {
            aid: r.get("aid"),
            sn: r.get("sn"),
            said: r.get("said"),
            ilk: r.get("ilk"),
            raw_event: r.get::<Vec<u8>, _>("raw_event"),
            prior_said: r.get("prior_said"),
            first_seen_at: r.get("first_seen_at"),
            receipted: r.get("receipted"),
            receipt_sig: r.get("receipt_sig"),
        }))
    }

    async fn get_first_seen_said(&self, aid: &str, sn: i64) -> WitnessResult<Option<String>> {
        let row = sqlx::query_scalar::<_, String>(
            r#"
            SELECT said FROM key_events
            WHERE aid = $1 AND sn = $2
            ORDER BY first_seen_at ASC
            LIMIT 1
            "#,
        )
        .bind(aid)
        .bind(sn)
        .fetch_optional(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(row)
    }

    async fn get_receipt(&self, aid: &str, sn: i64) -> WitnessResult<Option<Receipt>> {
        let row = sqlx::query(
            r#"
            SELECT id, aid, sn, said, witness_aid, signature_b64, issued_at, ilk
            FROM receipts
            WHERE aid = $1 AND sn = $2
            LIMIT 1
            "#,
        )
        .bind(aid)
        .bind(sn)
        .fetch_optional(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(row.map(|r| Receipt {
            id: r.get("id"),
            aid: r.get("aid"),
            sn: r.get("sn"),
            said: r.get("said"),
            witness_aid: r.get("witness_aid"),
            signature_b64: r.get("signature_b64"),
            issued_at: r.get("issued_at"),
            ilk: r.get("ilk"),
        }))
    }

    async fn get_receipts_for_aid(&self, aid: &str) -> WitnessResult<Vec<Receipt>> {
        let rows = sqlx::query(
            r#"
            SELECT id, aid, sn, said, witness_aid, signature_b64, issued_at, ilk
            FROM receipts
            WHERE aid = $1
            ORDER BY sn ASC
            "#,
        )
        .bind(aid)
        .fetch_all(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(rows
            .into_iter()
            .map(|r| Receipt {
                id: r.get("id"),
                aid: r.get("aid"),
                sn: r.get("sn"),
                said: r.get("said"),
                witness_aid: r.get("witness_aid"),
                signature_b64: r.get("signature_b64"),
                issued_at: r.get("issued_at"),
                ilk: r.get("ilk"),
            })
            .collect())
    }

    async fn record_duplicity(
        &self,
        aid: &str,
        sn: i64,
        first_said: &str,
        conflict_said: &str,
        first_raw: Option<&[u8]>,
        conflict_raw: Option<&[u8]>,
        source: Option<&str>,
    ) -> WitnessResult<Uuid> {
        let id = Uuid::new_v4();
        sqlx::query(
            r#"
            INSERT INTO duplicity_log
                (id, detected_at, aid, sn, first_said, conflict_said, first_raw, conflict_raw, source_witness)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT DO NOTHING
            "#,
        )
        .bind(id)
        .bind(aid)
        .bind(sn)
        .bind(first_said)
        .bind(conflict_said)
        .bind(first_raw)
        .bind(conflict_raw)
        .bind(source)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(id)
    }

    async fn list_duplicity(
        &self,
        aid: Option<&str>,
        resolved: Option<bool>,
        limit: i64,
        offset: i64,
    ) -> WitnessResult<Vec<DuplicityRecord>> {
        let rows = match (aid, resolved) {
            (Some(a), Some(r)) => sqlx::query(
                "SELECT id, aid, sn, first_said, conflict_said, detected_at, resolved, resolved_at, notes FROM duplicity_log WHERE aid = $1 AND resolved = $2 ORDER BY detected_at DESC LIMIT $3 OFFSET $4"
            ).bind(a).bind(r).bind(limit).bind(offset).fetch_all(&self.pool).await,
            (Some(a), None) => sqlx::query(
                "SELECT id, aid, sn, first_said, conflict_said, detected_at, resolved, resolved_at, notes FROM duplicity_log WHERE aid = $1 ORDER BY detected_at DESC LIMIT $2 OFFSET $3"
            ).bind(a).bind(limit).bind(offset).fetch_all(&self.pool).await,
            (None, Some(r)) => sqlx::query(
                "SELECT id, aid, sn, first_said, conflict_said, detected_at, resolved, resolved_at, notes FROM duplicity_log WHERE resolved = $1 ORDER BY detected_at DESC LIMIT $2 OFFSET $3"
            ).bind(r).bind(limit).bind(offset).fetch_all(&self.pool).await,
            (None, None) => sqlx::query(
                "SELECT id, aid, sn, first_said, conflict_said, detected_at, resolved, resolved_at, notes FROM duplicity_log ORDER BY detected_at DESC LIMIT $1 OFFSET $2"
            ).bind(limit).bind(offset).fetch_all(&self.pool).await,
        }.map_err(WitnessError::Database)?;

        Ok(rows
            .into_iter()
            .map(|r| DuplicityRecord {
                id: r.get("id"),
                aid: r.get("aid"),
                sn: r.get("sn"),
                first_said: r.get("first_said"),
                conflict_said: r.get("conflict_said"),
                detected_at: r.get("detected_at"),
                resolved: r.get("resolved"),
                resolved_at: r.get("resolved_at"),
                notes: r.get("notes"),
            })
            .collect())
    }

    async fn resolve_duplicity(&self, id: &Uuid, notes: Option<&str>) -> WitnessResult<bool> {
        let result = sqlx::query(
            "UPDATE duplicity_log SET resolved = TRUE, resolved_at = NOW(), notes = $2 WHERE id = $1 AND resolved = FALSE"
        )
        .bind(id)
        .bind(notes)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;

        Ok(result.rows_affected() > 0)
    }

    async fn escrow_event(
        &self,
        aid: &str,
        raw: &[u8],
        reason: &str,
        sn: Option<i64>,
        said: Option<&str>,
    ) -> WitnessResult<()> {
        sqlx::query(
            r#"
            INSERT INTO escrow_events
                (aid, sn, said, raw_event, reason, expires_at)
            VALUES ($1, $2, $3, $4, $5, NOW() + INTERVAL '7 days')
            ON CONFLICT DO NOTHING
            "#,
        )
        .bind(aid)
        .bind(sn)
        .bind(said)
        .bind(raw)
        .bind(reason)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(())
    }

    async fn get_pending_escrow(
        &self,
        aid: Option<&str>,
        limit: i64,
    ) -> WitnessResult<Vec<EscrowRecord>> {
        let rows = match aid {
            Some(a) => sqlx::query(
                "SELECT id, aid, sn, said, raw_event, reason, retry_count, received_at, expires_at FROM escrow_events WHERE resolved = FALSE AND expires_at > NOW() AND aid = $1 ORDER BY received_at ASC LIMIT $2"
            ).bind(a).bind(limit).fetch_all(&self.pool).await,
            None => sqlx::query(
                "SELECT id, aid, sn, said, raw_event, reason, retry_count, received_at, expires_at FROM escrow_events WHERE resolved = FALSE AND expires_at > NOW() ORDER BY received_at ASC LIMIT $1"
            ).bind(limit).fetch_all(&self.pool).await,
        }.map_err(WitnessError::Database)?;

        Ok(rows
            .into_iter()
            .map(|r| EscrowRecord {
                id: r.get("id"),
                aid: r.get("aid"),
                sn: r.get("sn"),
                said: r.get("said"),
                raw_event: r.get::<Vec<u8>, _>("raw_event"),
                reason: r.get("reason"),
                retry_count: r.get("retry_count"),
                received_at: r.get("received_at"),
                expires_at: r.get("expires_at"),
            })
            .collect())
    }

    async fn resolve_escrow(&self, id: &Uuid) -> WitnessResult<()> {
        sqlx::query(
            "UPDATE escrow_events SET resolved = TRUE, resolved_at = NOW() WHERE id = $1",
        )
        .bind(id)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(())
    }

    async fn increment_escrow_retry(&self, id: &Uuid) -> WitnessResult<()> {
        sqlx::query(
            "UPDATE escrow_events SET retry_count = retry_count + 1, last_retry_at = NOW() WHERE id = $1",
        )
        .bind(id)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(())
    }

    async fn expire_old_escrow_events(&self) -> WitnessResult<u64> {
        let result = sqlx::query(
            "UPDATE escrow_events SET resolved = TRUE, resolved_at = NOW() WHERE resolved = FALSE AND expires_at <= NOW()"
        )
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(result.rows_affected())
    }

    async fn count_pending_escrow(&self) -> WitnessResult<i64> {
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM escrow_events WHERE resolved = FALSE AND expires_at > NOW()",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(count)
    }

    async fn record_watcher_push_error(&self, watcher_url: &str) -> WitnessResult<()> {
        sqlx::query(
            r#"
            INSERT INTO watcher_registry (url, consecutive_errors, last_error_at)
            VALUES ($1, 1, NOW())
            ON CONFLICT (url) DO UPDATE
                SET consecutive_errors = watcher_registry.consecutive_errors + 1,
                    last_error_at = NOW()
            "#,
        )
        .bind(watcher_url)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(())
    }

    async fn record_watcher_push_success(&self, watcher_url: &str) -> WitnessResult<()> {
        sqlx::query(
            r#"
            INSERT INTO watcher_registry (url, consecutive_errors, last_push_at)
            VALUES ($1, 0, NOW())
            ON CONFLICT (url) DO UPDATE
                SET consecutive_errors = 0,
                    last_push_at = NOW()
            "#,
        )
        .bind(watcher_url)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(())
    }

    async fn write_metrics_snapshot(&self, snapshot: MetricsSnapshot) -> WitnessResult<()> {
        sqlx::query(
            r#"
            INSERT INTO witness_metrics
                (events_received, events_processed, events_rejected, receipts_issued,
                 duplicity_count, escrow_count, watcher_push_success, watcher_push_errors)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            "#,
        )
        .bind(snapshot.events_received)
        .bind(snapshot.events_processed)
        .bind(snapshot.events_rejected)
        .bind(snapshot.receipts_issued)
        .bind(snapshot.duplicity_count)
        .bind(snapshot.escrow_count)
        .bind(snapshot.watcher_push_success)
        .bind(snapshot.watcher_push_errors)
        .execute(&self.pool)
        .await
        .map_err(WitnessError::Database)?;
        Ok(())
    }

    async fn health_check(&self) -> WitnessResult<DbHealthStatus> {
        let start = Instant::now();
        match sqlx::query_scalar::<_, String>("SELECT version()")
            .fetch_one(&self.pool)
            .await
        {
            Ok(version) => Ok(DbHealthStatus {
                status: "ok".into(),
                latency_ms: start.elapsed().as_secs_f64() * 1000.0,
                version: Some(version),
                error: None,
            }),
            Err(e) => Ok(DbHealthStatus {
                status: "error".into(),
                latency_ms: start.elapsed().as_secs_f64() * 1000.0,
                version: None,
                error: Some(e.to_string()),
            }),
        }
    }
}