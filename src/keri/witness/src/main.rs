use std::net::SocketAddr;
use std::sync::Arc;

use keri_witness::{
    api::{router::build_router, state::AppState},
    core::{
        escrow_retry::EscrowRetryTask,
        processor::EventProcessor,
        watcher_push::WatcherPushService,
    },
    crypto::KeyPair,
    db::TimescaleRepository,
    utils::{config::Config, metrics, tracing},
};
use tokio::signal;
use tracing::{error, info};

#[tokio::main]
async fn main() {
    let config = match Config::from_env() {
        Ok(c) => Arc::new(c),
        Err(e) => {
            eprintln!("Configuration error: {e}");
            std::process::exit(1);
        }
    };

    if let Err(e) = tracing::init(&config.witness.log_level, &config.witness.log_format) {
        eprintln!("Failed to initialize logging: {e}");
        std::process::exit(1);
    }

    info!(
        name = %config.witness.name,
        http_port = config.witness.http_port,
        "Starting KERI Witness"
    );

    if config.metrics.enabled {
        metrics::init_all();
    }

    let repo = match TimescaleRepository::connect(&config.database).await {
        Ok(r) => {
            let r = Arc::new(r) as Arc<dyn keri_witness::db::repository::WitnessRepository>;
            r
        }
        Err(e) => {
            error!(error = %e, "Failed to connect to TimescaleDB");
            std::process::exit(1);
        }
    };

    let concrete_repo = match TimescaleRepository::connect(&config.database).await {
        Ok(r) => Arc::new(r),
        Err(e) => {
            error!(error = %e, "Failed to connect to TimescaleDB for migrations");
            std::process::exit(1);
        }
    };

    if let Err(e) = concrete_repo.run_migrations().await {
        error!(error = %e, "Database migration failed");
        std::process::exit(1);
    }

    let repo: Arc<dyn keri_witness::db::repository::WitnessRepository> =
        Arc::new(TimescaleRepository::connect(&config.database).await.unwrap());

    let key_pair = match load_or_generate_key_pair(&config) {
        Ok(kp) => Arc::new(kp),
        Err(e) => {
            error!(error = %e, "Failed to load or generate witness key pair");
            std::process::exit(1);
        }
    };

    info!(witness_aid = %key_pair.aid(), "Witness identity initialized");

    let processor = Arc::new(EventProcessor::new(
        Arc::clone(&repo),
        Arc::clone(&key_pair),
        config.receipt.queue_size,
        config.receipt.workers,
    ));

    let watcher_push = Arc::new(WatcherPushService::new(
        config.watcher.clone(),
        Arc::clone(&repo),
    ));

    EscrowRetryTask::new(Arc::clone(&repo), config.escrow.retry_interval_secs).spawn();

    let state = AppState::new(
        Arc::clone(&config),
        Arc::clone(&repo),
        Arc::clone(&processor),
        Arc::clone(&watcher_push),
    );

    let app = build_router(state, config.server.request_timeout_secs);

    let addr = SocketAddr::from(([0, 0, 0, 0], config.witness.http_port));
    info!(addr = %addr, "Witness HTTP server listening");

    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(l) => l,
        Err(e) => {
            error!(addr = %addr, error = %e, "Failed to bind listener");
            std::process::exit(1);
        }
    };

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap_or_else(|e| error!(error = %e, "Server error"));

    info!("KERI Witness shut down gracefully");
}

fn load_or_generate_key_pair(config: &Config) -> anyhow::Result<KeyPair> {
    if !config.witness.aid.is_empty() {
        anyhow::bail!(
            "Pre-existing AID configured but key loading from keystore not yet implemented; \
             start with empty WITNESS_AID to auto-generate"
        );
    }
    Ok(KeyPair::generate())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("Failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("Failed to install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => info!("Received Ctrl+C"),
        _ = terminate => info!("Received SIGTERM"),
    }
}