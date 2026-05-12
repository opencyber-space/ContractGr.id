use anyhow::{Context, Result};
use serde::Deserialize;
use std::time::Duration;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub witness: WitnessConfig,
    pub database: DatabaseConfig,
    pub receipt: ReceiptConfig,
    pub escrow: EscrowConfig,
    pub metrics: MetricsConfig,
    pub rate_limit: RateLimitConfig,
    pub watcher: WatcherPushConfig,
    pub server: ServerConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct WitnessConfig {
    #[serde(default = "default_witness_name")]
    pub name: String,
    #[serde(default)]
    pub aid: String,
    #[serde(default = "default_http_port")]
    pub http_port: u16,
    #[serde(default = "default_admin_port")]
    pub admin_port: u16,
    #[serde(default = "default_log_level")]
    pub log_level: String,
    #[serde(default = "default_log_format")]
    pub log_format: String,
    #[serde(default = "default_origins")]
    pub allowed_origins: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct DatabaseConfig {
    pub url: String,
    #[serde(default = "default_db_min")]
    pub min_connections: u32,
    #[serde(default = "default_db_max")]
    pub max_connections: u32,
    #[serde(default = "default_acquire_timeout")]
    pub acquire_timeout_secs: u64,
    #[serde(default = "default_idle_timeout")]
    pub idle_timeout_secs: u64,
    #[serde(default = "default_max_lifetime")]
    pub max_lifetime_secs: u64,
}

impl DatabaseConfig {
    pub fn acquire_timeout(&self) -> Duration {
        Duration::from_secs(self.acquire_timeout_secs)
    }
    pub fn idle_timeout(&self) -> Duration {
        Duration::from_secs(self.idle_timeout_secs)
    }
    pub fn max_lifetime(&self) -> Duration {
        Duration::from_secs(self.max_lifetime_secs)
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ReceiptConfig {
    #[serde(default = "default_queue_size")]
    pub queue_size: usize,
    #[serde(default = "default_workers")]
    pub workers: usize,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EscrowConfig {
    #[serde(default = "default_escrow_retry_secs")]
    pub retry_interval_secs: u64,
    #[serde(default = "default_escrow_max_days")]
    pub max_age_days: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MetricsConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_metrics_port")]
    pub port: u16,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RateLimitConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_rps")]
    pub per_second: u32,
    #[serde(default = "default_burst")]
    pub burst: u32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct WatcherPushConfig {
    #[serde(default = "default_true")]
    pub push_enabled: bool,
    #[serde(default)]
    pub urls: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ServerConfig {
    #[serde(default = "default_request_timeout")]
    pub request_timeout_secs: u64,
    #[serde(default = "default_max_body")]
    pub max_body_size_bytes: usize,
}

fn default_witness_name() -> String { "witness0".into() }
fn default_http_port() -> u16 { 5631 }
fn default_admin_port() -> u16 { 5634 }
fn default_log_level() -> String { "info".into() }
fn default_log_format() -> String { "json".into() }
fn default_origins() -> String { "*".into() }
fn default_db_min() -> u32 { 5 }
fn default_db_max() -> u32 { 20 }
fn default_acquire_timeout() -> u64 { 30 }
fn default_idle_timeout() -> u64 { 600 }
fn default_max_lifetime() -> u64 { 1800 }
fn default_queue_size() -> usize { 10_000 }
fn default_workers() -> usize { 8 }
fn default_escrow_retry_secs() -> u64 { 60 }
fn default_escrow_max_days() -> i64 { 7 }
fn default_true() -> bool { true }
fn default_metrics_port() -> u16 { 9090 }
fn default_rps() -> u32 { 200 }
fn default_burst() -> u32 { 500 }
fn default_request_timeout() -> u64 { 30 }
fn default_max_body() -> usize { 1_048_576 }

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenvy::dotenv().ok();

        let db_url = std::env::var("DATABASE_URL")
            .context("DATABASE_URL environment variable is required")?;

        Ok(Config {
            witness: WitnessConfig {
                name: env_str("WITNESS_NAME", "witness0"),
                aid: env_str("WITNESS_AID", ""),
                http_port: env_u16("WITNESS_HTTP_PORT", 5631),
                admin_port: env_u16("WITNESS_ADMIN_PORT", 5634),
                log_level: env_str("WITNESS_LOG_LEVEL", "info"),
                log_format: env_str("WITNESS_LOG_FORMAT", "json"),
                allowed_origins: env_str("ALLOWED_ORIGINS", "*"),
            },
            database: DatabaseConfig {
                url: db_url,
                min_connections: env_u32("DB_MIN_CONNECTIONS", 5),
                max_connections: env_u32("DB_MAX_CONNECTIONS", 20),
                acquire_timeout_secs: env_u64("DB_ACQUIRE_TIMEOUT_SECS", 30),
                idle_timeout_secs: env_u64("DB_IDLE_TIMEOUT_SECS", 600),
                max_lifetime_secs: env_u64("DB_MAX_LIFETIME_SECS", 1800),
            },
            receipt: ReceiptConfig {
                queue_size: env_usize("RECEIPT_QUEUE_SIZE", 10_000),
                workers: env_usize("RECEIPT_WORKERS", 8),
            },
            escrow: EscrowConfig {
                retry_interval_secs: env_u64("ESCROW_RETRY_INTERVAL_SECS", 60),
                max_age_days: env_i64("ESCROW_MAX_AGE_DAYS", 7),
            },
            metrics: MetricsConfig {
                enabled: env_bool("METRICS_ENABLED", true),
                port: env_u16("METRICS_PORT", 9090),
            },
            rate_limit: RateLimitConfig {
                enabled: env_bool("RATE_LIMIT_ENABLED", true),
                per_second: env_u32("RATE_LIMIT_PER_SECOND", 200),
                burst: env_u32("RATE_LIMIT_BURST", 500),
            },
            watcher: WatcherPushConfig {
                push_enabled: env_bool("WATCHER_PUSH_ENABLED", true),
                urls: env_str("WATCHER_URLS", "")
                    .split(',')
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .map(String::from)
                    .collect(),
            },
            server: ServerConfig {
                request_timeout_secs: env_u64("REQUEST_TIMEOUT_SECS", 30),
                max_body_size_bytes: env_usize("MAX_BODY_SIZE_BYTES", 1_048_576),
            },
        })
    }
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_bool(key: &str, default: bool) -> bool {
    std::env::var(key)
        .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
        .unwrap_or(default)
}

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn env_u32(key: &str, default: u32) -> u32 {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn env_u64(key: &str, default: u64) -> u64 {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn env_i64(key: &str, default: i64) -> i64 {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}