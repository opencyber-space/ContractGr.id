use once_cell::sync::Lazy;
use prometheus::{
    register_counter_vec, register_gauge, register_histogram_vec,
    CounterVec, Gauge, HistogramVec, TextEncoder, Encoder,
};
use std::net::SocketAddr;

pub static EVENTS_RECEIVED: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_events_received_total",
        "Total key events received",
        &["ilk", "source"]
    ).unwrap()
});

pub static EVENTS_PROCESSED: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_events_processed_total",
        "Total key events successfully processed",
        &["ilk"]
    ).unwrap()
});

pub static EVENTS_REJECTED: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_events_rejected_total",
        "Total key events rejected",
        &["reason"]
    ).unwrap()
});

pub static RECEIPTS_ISSUED: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_receipts_issued_total",
        "Total receipts issued",
        &["ilk"]
    ).unwrap()
});

pub static DUPLICITY_DETECTED: Lazy<prometheus::Counter> = Lazy::new(|| {
    prometheus::register_counter!(
        "keri_witness_duplicity_detected_total",
        "Total duplicity events detected"
    ).unwrap()
});

pub static ESCROW_SIZE: Lazy<Gauge> = Lazy::new(|| {
    register_gauge!(
        "keri_witness_escrow_size",
        "Current number of events in escrow"
    ).unwrap()
});

pub static QUEUE_SIZE: Lazy<Gauge> = Lazy::new(|| {
    register_gauge!(
        "keri_witness_queue_size",
        "Current event processing queue depth"
    ).unwrap()
});

pub static DB_QUERY_DURATION: Lazy<HistogramVec> = Lazy::new(|| {
    register_histogram_vec!(
        "keri_witness_db_query_duration_seconds",
        "TimescaleDB query latency",
        &["operation"],
        vec![0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
    ).unwrap()
});

pub static DB_ERRORS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_db_errors_total",
        "TimescaleDB errors",
        &["operation"]
    ).unwrap()
});

pub static HTTP_REQUESTS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_http_requests_total",
        "Total HTTP requests",
        &["method", "path", "status"]
    ).unwrap()
});

pub static HTTP_LATENCY: Lazy<HistogramVec> = Lazy::new(|| {
    register_histogram_vec!(
        "keri_witness_http_latency_seconds",
        "HTTP request latency",
        &["method", "path"],
        vec![0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
    ).unwrap()
});

pub static WATCHER_PUSH_SUCCESS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_watcher_push_success_total",
        "Successful pushes to watchers",
        &["watcher"]
    ).unwrap()
});

pub static WATCHER_PUSH_ERRORS: Lazy<CounterVec> = Lazy::new(|| {
    register_counter_vec!(
        "keri_witness_watcher_push_errors_total",
        "Failed pushes to watchers",
        &["watcher", "reason"]
    ).unwrap()
});

pub static SIG_VERIFY_DURATION: Lazy<HistogramVec> = Lazy::new(|| {
    register_histogram_vec!(
        "keri_witness_sig_verify_duration_seconds",
        "Signature verification latency",
        &["ilk"],
        vec![0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05]
    ).unwrap()
});

pub fn init_all() {
    Lazy::force(&EVENTS_RECEIVED);
    Lazy::force(&EVENTS_PROCESSED);
    Lazy::force(&EVENTS_REJECTED);
    Lazy::force(&RECEIPTS_ISSUED);
    Lazy::force(&DUPLICITY_DETECTED);
    Lazy::force(&ESCROW_SIZE);
    Lazy::force(&QUEUE_SIZE);
    Lazy::force(&DB_QUERY_DURATION);
    Lazy::force(&DB_ERRORS);
    Lazy::force(&HTTP_REQUESTS);
    Lazy::force(&HTTP_LATENCY);
    Lazy::force(&WATCHER_PUSH_SUCCESS);
    Lazy::force(&WATCHER_PUSH_ERRORS);
    Lazy::force(&SIG_VERIFY_DURATION);
}

pub fn render_metrics() -> String {
    let encoder = TextEncoder::new();
    let metric_families = prometheus::gather();
    let mut buffer = Vec::new();
    encoder.encode(&metric_families, &mut buffer).unwrap_or_default();
    String::from_utf8(buffer).unwrap_or_default()
}