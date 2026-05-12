use std::sync::Arc;
use std::time::Duration;

use tokio::time::sleep;
use tracing::{debug, error, info};

use crate::db::repository::WitnessRepository;
use crate::utils::metrics;

pub struct EscrowRetryTask {
    repo: Arc<dyn WitnessRepository>,
    interval: Duration,
}

impl EscrowRetryTask {
    pub fn new(repo: Arc<dyn WitnessRepository>, interval_secs: u64) -> Self {
        Self {
            repo,
            interval: Duration::from_secs(interval_secs),
        }
    }

    pub fn spawn(self) {
        tokio::spawn(async move {
            info!("Escrow retry task started");
            loop {
                sleep(self.interval).await;
                if let Err(e) = self.tick().await {
                    error!(error = %e, "Escrow retry task error");
                }
            }
        });
    }

    async fn tick(&self) -> anyhow::Result<()> {
        let expired = self.repo.expire_old_escrow_events().await?;
        if expired > 0 {
            info!(count = expired, "Expired old escrow events");
            metrics::ESCROW_SIZE.sub(expired as f64);
        }

        let pending_count = self.repo.count_pending_escrow().await?;
        metrics::ESCROW_SIZE.set(pending_count as f64);
        debug!(pending = pending_count, "Escrow retry tick complete");

        Ok(())
    }
}