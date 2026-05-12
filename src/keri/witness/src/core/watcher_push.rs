use std::sync::Arc;
use std::time::Duration;

use reqwest::Client;
use serde_json::json;
use tokio::time::sleep;
use tracing::{error, info, warn};

use crate::core::types::Receipt;
use crate::db::repository::WitnessRepository;
use crate::utils::config::WatcherPushConfig;
use crate::utils::metrics;

pub struct WatcherPushService {
    config: WatcherPushConfig,
    client: Client,
    repo: Arc<dyn WitnessRepository>,
}

impl WatcherPushService {
    pub fn new(config: WatcherPushConfig, repo: Arc<dyn WitnessRepository>) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(10))
            .user_agent("keri-witness/1.0")
            .pool_max_idle_per_host(4)
            .build()
            .expect("Failed to build HTTP client");

        Self { config, client, repo }
    }

    pub async fn push_receipt(&self, receipt: &Receipt, raw_event: &[u8]) {
        if !self.config.push_enabled || self.config.urls.is_empty() {
            return;
        }

        let payload = json!({
            "aid": receipt.aid,
            "sn": receipt.sn,
            "said": receipt.said,
            "ilk": receipt.ilk,
            "witness_aid": receipt.witness_aid,
            "signature": receipt.signature_b64,
            "issued_at": receipt.issued_at,
            "raw_event": base64::Engine::encode(
                &base64::engine::general_purpose::URL_SAFE_NO_PAD,
                raw_event
            ),
        });

        for url in &self.config.urls {
            let watcher_url = format!("{}/kel/{}", url.trim_end_matches('/'), receipt.aid);
            let watcher_label = extract_host(url);

            match self
                .client
                .post(&watcher_url)
                .json(&payload)
                .send()
                .await
            {
                Ok(resp) if resp.status().is_success() => {
                    metrics::WATCHER_PUSH_SUCCESS
                        .with_label_values(&[&watcher_label])
                        .inc();
                    info!(
                        watcher = %watcher_label,
                        aid = %receipt.aid,
                        sn = receipt.sn,
                        "Receipt pushed to watcher"
                    );
                }
                Ok(resp) => {
                    let status = resp.status().as_u16();
                    warn!(
                        watcher = %watcher_label,
                        aid = %receipt.aid,
                        sn = receipt.sn,
                        status = status,
                        "Watcher push returned non-success status"
                    );
                    metrics::WATCHER_PUSH_ERRORS
                        .with_label_values(&[&watcher_label, &format!("http_{status}")])
                        .inc();
                    let _ = self.repo.record_watcher_push_error(url).await;
                }
                Err(e) => {
                    error!(
                        watcher = %watcher_label,
                        aid = %receipt.aid,
                        error = %e,
                        "Failed to push receipt to watcher"
                    );
                    metrics::WATCHER_PUSH_ERRORS
                        .with_label_values(&[&watcher_label, "connection_error"])
                        .inc();
                    let _ = self.repo.record_watcher_push_error(url).await;
                }
            }
        }
    }

    pub async fn start_retry_loop(self: Arc<Self>, interval_secs: u64) {
        tokio::spawn(async move {
            loop {
                sleep(Duration::from_secs(interval_secs)).await;
                if let Err(e) = self.retry_failed_pushes().await {
                    error!(error = %e, "Watcher push retry loop error");
                }
            }
        });
    }

    async fn retry_failed_pushes(&self) -> anyhow::Result<()> {
        Ok(())
    }
}

fn extract_host(url: &str) -> String {
    url::Url::parse(url)
        .map(|u| u.host_str().unwrap_or("unknown").to_string())
        .unwrap_or_else(|_| "unknown".to_string())
}