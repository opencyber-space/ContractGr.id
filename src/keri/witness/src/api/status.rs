use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::IntoResponse,
    Json,
};
use serde::Deserialize;
use serde_json::json;

use crate::api::state::AppState;
use crate::utils::errors::WitnessResult;
use crate::utils::metrics;

pub async fn health(State(state): State<AppState>) -> impl IntoResponse {
    let db = state.repo.health_check().await;
    match db {
        Ok(status) if status.status == "ok" => (
            StatusCode::OK,
            Json(json!({
                "status": "ok",
                "uptime_seconds": state.start_time.elapsed().as_secs(),
                "components": {
                    "timescaledb": status,
                }
            })),
        ),
        Ok(status) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({
                "status": "degraded",
                "components": { "timescaledb": status }
            })),
        ),
        Err(e) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({
                "status": "error",
                "error": e.to_string(),
            })),
        ),
    }
}

pub async fn ready(State(state): State<AppState>) -> impl IntoResponse {
    match state.repo.health_check().await {
        Ok(s) if s.status == "ok" => {
            (StatusCode::OK, Json(json!({ "ready": true })))
        }
        Ok(s) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({ "ready": false, "reason": s.error })),
        ),
        Err(e) => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({ "ready": false, "reason": e.to_string() })),
        ),
    }
}

pub async fn status(State(state): State<AppState>) -> Json<serde_json::Value> {
    let proc_stats = state.processor.get_stats();
    Json(json!({
        "status": "ok",
        "data": {
            "witness_aid": state.witness_aid,
            "uptime_seconds": state.start_time.elapsed().as_secs(),
            "processor": proc_stats,
            "watcher_urls": state.config.watcher.urls,
        }
    }))
}

pub async fn prometheus_metrics() -> impl IntoResponse {
    let body = metrics::render_metrics();
    (
        StatusCode::OK,
        [(axum::http::header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        body,
    )
}

pub async fn oobi(State(state): State<AppState>) -> Json<serde_json::Value> {
    let port = state.config.witness.http_port;
    let name = &state.config.witness.name;
    let aid = &state.witness_aid;

    Json(json!({
        "status": "ok",
        "data": {
            "aid": aid,
            "name": name,
            "role": "witness",
            "oobi": format!("http://localhost:{}/oobi/{}/witness", port, aid),
            "endpoints": {
                "events": format!("http://localhost:{}/events", port),
                "kel": format!("http://localhost:{}/kel/{{aid}}", port),
                "receipts": format!("http://localhost:{}/receipts/{{aid}}", port),
            }
        }
    }))
}

#[derive(Debug, Deserialize)]
pub struct StatsQuery {
    pub hours: Option<u32>,
}