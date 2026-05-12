use async_trait::async_trait;
use uuid::Uuid;

use crate::core::types::{
    DuplicityRecord, EscrowRecord, KeyEvent, Receipt, StoredEvent, WatcherRecord,
};
use crate::utils::errors::WitnessResult;

#[async_trait]
pub trait WitnessRepository: Send + Sync + 'static {
    async fn store_event_and_receipt(
        &self,
        event: &KeyEvent,
        receipt: &Receipt,
    ) -> WitnessResult<()>;

    async fn get_event(&self, aid: &str, sn: i64) -> WitnessResult<Option<StoredEvent>>;

    async fn get_kel(
        &self,
        aid: &str,
        from_sn: i64,
        limit: i64,
    ) -> WitnessResult<Vec<StoredEvent>>;

    async fn get_latest_event(&self, aid: &str) -> WitnessResult<Option<StoredEvent>>;

    async fn get_first_seen_said(&self, aid: &str, sn: i64) -> WitnessResult<Option<String>>;

    async fn get_receipt(&self, aid: &str, sn: i64) -> WitnessResult<Option<Receipt>>;

    async fn get_receipts_for_aid(&self, aid: &str) -> WitnessResult<Vec<Receipt>>;

    async fn record_duplicity(
        &self,
        aid: &str,
        sn: i64,
        first_said: &str,
        conflict_said: &str,
        first_raw: Option<&[u8]>,
        conflict_raw: Option<&[u8]>,
        source: Option<&str>,
    ) -> WitnessResult<Uuid>;

    async fn list_duplicity(
        &self,
        aid: Option<&str>,
        resolved: Option<bool>,
        limit: i64,
        offset: i64,
    ) -> WitnessResult<Vec<DuplicityRecord>>;

    async fn resolve_duplicity(
        &self,
        id: &Uuid,
        notes: Option<&str>,
    ) -> WitnessResult<bool>;

    async fn escrow_event(
        &self,
        aid: &str,
        raw: &[u8],
        reason: &str,
        sn: Option<i64>,
        said: Option<&str>,
    ) -> WitnessResult<()>;

    async fn get_pending_escrow(
        &self,
        aid: Option<&str>,
        limit: i64,
    ) -> WitnessResult<Vec<EscrowRecord>>;

    async fn resolve_escrow(&self, id: &Uuid) -> WitnessResult<()>;

    async fn increment_escrow_retry(&self, id: &Uuid) -> WitnessResult<()>;

    async fn expire_old_escrow_events(&self) -> WitnessResult<u64>;

    async fn count_pending_escrow(&self) -> WitnessResult<i64>;

    async fn record_watcher_push_error(&self, watcher_url: &str) -> WitnessResult<()>;

    async fn record_watcher_push_success(&self, watcher_url: &str) -> WitnessResult<()>;

    async fn write_metrics_snapshot(&self, snapshot: MetricsSnapshot) -> WitnessResult<()>;

    async fn health_check(&self) -> WitnessResult<DbHealthStatus>;
}

#[derive(Debug, Clone)]
pub struct MetricsSnapshot {
    pub events_received: i64,
    pub events_processed: i64,
    pub events_rejected: i64,
    pub receipts_issued: i64,
    pub duplicity_count: i64,
    pub escrow_count: i64,
    pub watcher_push_success: i64,
    pub watcher_push_errors: i64,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct DbHealthStatus {
    pub status: String,
    pub latency_ms: f64,
    pub version: Option<String>,
    pub error: Option<String>,
}