use std::time::Instant;

use axum::{
    body::Body,
    extract::Request,
    http::{HeaderValue, Response, StatusCode},
    middleware::Next,
};
use tracing::{info, warn};
use uuid::Uuid;

use crate::utils::metrics;

pub async fn request_tracing(
    mut req: Request,
    next: Next,
) -> Response<Body> {
    let start = Instant::now();
    let method = req.method().to_string();
    let path = req.uri().path().to_string();
    let request_id = Uuid::new_v4().to_string();

    req.headers_mut().insert(
        "x-request-id",
        HeaderValue::from_str(&request_id).unwrap_or(HeaderValue::from_static("")),
    );

    let mut response = next.run(req).await;

    let elapsed = start.elapsed();
    let status = response.status().as_u16();

    response.headers_mut().insert(
        "x-request-id",
        HeaderValue::from_str(&request_id).unwrap_or(HeaderValue::from_static("")),
    );
    response.headers_mut().insert(
        "x-response-time-ms",
        HeaderValue::from_str(&format!("{:.1}", elapsed.as_secs_f64() * 1000.0))
            .unwrap_or(HeaderValue::from_static("0")),
    );

    metrics::HTTP_REQUESTS
        .with_label_values(&[&method, &path, &status.to_string()])
        .inc();
    metrics::HTTP_LATENCY
        .with_label_values(&[&method, &path])
        .observe(elapsed.as_secs_f64());

    info!(
        method = %method,
        path = %path,
        status = status,
        elapsed_ms = format!("{:.1}", elapsed.as_secs_f64() * 1000.0),
        request_id = %request_id,
    );

    response
}

pub async fn security_headers(
    req: Request,
    next: Next,
) -> Response<Body> {
    let mut response = next.run(req).await;
    let headers = response.headers_mut();
    headers.insert("x-content-type-options", HeaderValue::from_static("nosniff"));
    headers.insert("x-frame-options", HeaderValue::from_static("DENY"));
    headers.insert("x-xss-protection", HeaderValue::from_static("1; mode=block"));
    headers.insert(
        "strict-transport-security",
        HeaderValue::from_static("max-age=31536000; includeSubDomains"),
    );
    response
}