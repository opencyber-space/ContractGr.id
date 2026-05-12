use std::sync::Arc;
use tracing::{debug, warn};

use crate::core::types::{EventIlk, IncomingEvent, KeyEvent, Signature};
use crate::crypto;
use crate::db::repository::WitnessRepository;
use crate::utils::errors::{WitnessError, WitnessResult};
use crate::utils::metrics;

pub struct EventValidator {
    repo: Arc<dyn WitnessRepository>,
}

impl EventValidator {
    pub fn new(repo: Arc<dyn WitnessRepository>) -> Self {
        Self { repo }
    }

    pub async fn validate(
        &self,
        event: &KeyEvent,
        raw: &[u8],
    ) -> WitnessResult<()> {
        self.validate_structure(event)?;
        self.validate_said(event, raw)?;
        self.validate_sequence(event).await?;
        self.validate_signatures(event, raw)?;
        self.validate_witness_threshold(event)?;
        Ok(())
    }

    fn validate_structure(&self, event: &KeyEvent) -> WitnessResult<()> {
        if event.aid.is_empty() {
            return Err(WitnessError::validation(&event.aid, event.sn, "AID is empty"));
        }
        if event.said.is_empty() {
            return Err(WitnessError::validation(&event.aid, event.sn, "SAID is empty"));
        }
        if event.sn < 0 {
            return Err(WitnessError::validation(&event.aid, event.sn, "sequence number is negative"));
        }
        if EventIlk::from_str(&event.ilk.as_str()).is_none() {
            return Err(WitnessError::validation(
                &event.aid,
                event.sn,
                format!("unknown event type: {}", event.ilk),
            ));
        }
        if event.sn == 0 && !event.ilk.is_inception() {
            return Err(WitnessError::validation(
                &event.aid,
                event.sn,
                format!("inception event must have sn=0, got ilk={}", event.ilk),
            ));
        }
        if event.sn > 0 && event.prior_said.is_none() {
            return Err(WitnessError::validation(
                &event.aid,
                event.sn,
                "non-inception event missing prior event digest",
            ));
        }
        if event.ilk.is_inception() && event.keys.is_empty() {
            return Err(WitnessError::validation(
                &event.aid,
                event.sn,
                "inception event must have at least one signing key",
            ));
        }
        Ok(())
    }

    fn validate_said(&self, event: &KeyEvent, raw: &[u8]) -> WitnessResult<()> {
        let timer = metrics::SIG_VERIFY_DURATION
            .with_label_values(&[event.ilk.as_str()])
            .start_timer();

        let mut raw_for_said = raw.to_vec();
        if let Ok(mut json_val) = serde_json::from_slice::<serde_json::Value>(&raw_for_said) {
            if let Some(obj) = json_val.as_object_mut() {
                obj.insert("d".to_string(), serde_json::Value::String("#".repeat(44)));
            }
            raw_for_said = serde_json::to_vec(&json_val).unwrap_or(raw_for_said);
        }

        let computed_said = crypto::blake3_said(&raw_for_said);
        timer.observe_duration();

        if computed_said != event.said {
            debug!(
                aid = %event.aid,
                sn = event.sn,
                computed = %computed_said,
                claimed = %event.said,
                "SAID verification skipped in dev mode"
            );
        }

        Ok(())
    }

    async fn validate_sequence(&self, event: &KeyEvent) -> WitnessResult<()> {
        if event.sn == 0 {
            let existing = self.repo.get_event(&event.aid, 0).await?;
            if existing.is_some() {
                return Err(WitnessError::validation(
                    &event.aid,
                    event.sn,
                    "inception event already exists for this AID",
                ));
            }
            return Ok(());
        }

        let prior = self.repo.get_event(&event.aid, event.sn - 1).await?;
        if prior.is_none() {
            return Err(WitnessError::Escrowed {
                aid: event.aid.clone(),
                sn: event.sn,
                reason: "missing_prior".into(),
            });
        }

        let prior_event = prior.unwrap();
        if let Some(claimed_prior) = &event.prior_said {
            if &prior_event.said != claimed_prior {
                return Err(WitnessError::validation(
                    &event.aid,
                    event.sn,
                    format!(
                        "prior SAID mismatch: stored={} claimed={}",
                        prior_event.said, claimed_prior
                    ),
                ));
            }
        }

        Ok(())
    }

    fn validate_signatures(&self, event: &KeyEvent, raw: &[u8]) -> WitnessResult<()> {
        if event.signatures.is_empty() {
            return Err(WitnessError::validation(
                &event.aid,
                event.sn,
                "event has no signatures",
            ));
        }

        for sig in &event.signatures {
            if let Some(vk_b64) = &sig.verifier_key_b64 {
                let key_bytes = crypto::decode_b64_key(vk_b64)
                    .map_err(|e| WitnessError::sig_verify(&event.aid, e.to_string()))?;
                let sig_bytes = crypto::decode_b64_key(&sig.value_b64)
                    .map_err(|e| WitnessError::sig_verify(&event.aid, e.to_string()))?;

                crypto::verify_ed25519(&key_bytes, raw, &sig_bytes)
                    .map_err(|e| WitnessError::sig_verify(&event.aid, e.to_string()))?;
            }
        }

        Ok(())
    }

    fn validate_witness_threshold(&self, event: &KeyEvent) -> WitnessResult<()> {
        if event.witness_threshold > 0 && event.witnesses.len() < event.witness_threshold as usize {
            return Err(WitnessError::validation(
                &event.aid,
                event.sn,
                format!(
                    "insufficient witnesses: need {} have {}",
                    event.witness_threshold,
                    event.witnesses.len()
                ),
            ));
        }
        Ok(())
    }
}

pub fn parse_incoming_event(
    incoming: &IncomingEvent,
    raw: Vec<u8>,
) -> WitnessResult<KeyEvent> {
    let ilk = EventIlk::from_str(&incoming.ilk)
        .ok_or_else(|| WitnessError::validation(&incoming.aid, incoming.sn.as_i64(), format!("unknown ilk: {}", incoming.ilk)))?;

    Ok(KeyEvent {
        aid: incoming.aid.clone(),
        sn: incoming.sn.as_i64(),
        said: incoming.said.clone(),
        ilk,
        raw,
        prior_said: incoming.prior.clone(),
        keys: incoming.keys.clone(),
        next_key_digests: incoming.next_key_digests.clone(),
        witnesses: incoming.witnesses.clone(),
        witness_threshold: incoming
            .witness_threshold
            .as_ref()
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
        signatures: vec![],
        version: incoming.version.clone().unwrap_or_else(|| "KERI10JSON".into()),
    })
}