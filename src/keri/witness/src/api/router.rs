use std::time::Duration;

use axum::{
    middleware,
    routing::{get, post, put},
    Router,
};
use tower::ServiceBuilder;
use tower_http::{
    cors::{Any, CorsLayer},
    timeout::TimeoutLayer,
    trace::TraceLayer,
};

use crate::api::{
    duplicity, events, middleware as mw, state::AppState, status,
};

pub fn build_router(state: AppState, request_timeout_secs: u64) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        .route("/health", get(status::health))
        .route("/ready", get(status::ready))
        .route("/status", get(status::status))
        .route("/metrics", get(status::prometheus_metrics))
        .route("/oobi", get(status::oobi))
        .route("/events", post(events::submit_event))
        .route("/kel/:aid", get(events::get_kel))
        .route("/kel/:aid/latest", get(events::get_kel_latest))
        .route("/receipts/:aid", get(events::get_all_receipts))
        .route("/receipts/:aid/sn", get(events::get_receipt))
        .route("/duplicity", get(duplicity::list_duplicity))
        .route("/duplicity/:aid", get(duplicity::list_duplicity_by_aid))
        .route("/duplicity/event/:id", put(duplicity::resolve_duplicity))
        .layer(
            ServiceBuilder::new()
                .layer(TraceLayer::new_for_http())
                .layer(TimeoutLayer::new(Duration::from_secs(request_timeout_secs)))
                .layer(cors)
                .layer(middleware::from_fn(mw::request_tracing))
                .layer(middleware::from_fn(mw::security_headers)),
        )
        .with_state(state)
}