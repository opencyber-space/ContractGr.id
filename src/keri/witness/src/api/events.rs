use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::api::state::AppState;
use crate::core::types::IncomingEvent;
use crate::core::validator::parse_incoming_event;
use crate::utils::errors::{WitnessError, WitnessResult};

#[derive(Debug, Deserialize)]
pub struct KelQuery {
    pub from: Option<i64>,
    pub limit: Option<i64>,
    pub include_raw: Option<bool>,
}

#[derive(Debug, Serialize)]
pub struct EventResponse {
    pub status: &'static str,
    pub aid: String,
    pub sn: i64,
    pub said: String,
    pub accepted: bool,
    pub duplicate: bool,
    pub escrowed: bool,
    pub receipt: Option<ReceiptResponse>,
    pub error: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ReceiptResponse {
    pub id: String,
    pub witness_aid: String,
    pub signature_b64: String,
    pub issued_at: String,
    pub cesr_encoded: Option<String>,
}

pub async fn submit_event(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> WitnessResult<(StatusCode, Json<Value>)> {
    let events: Vec<Value> = if body.is_array() {
        serde_json::from_value(body)?
    } else {
        vec![body]
    };

    let mut results = Vec::with_capacity(events.len());

    for event_val in events {
        let raw = serde_json::to_vec(&event_val)?;
        let incoming: IncomingEvent = serde_json::from_value(event_val)?;
        let key_event = parse_incoming_event(&incoming, raw.clone())?;

        let result = state.processor.process_immediate(key_event.clone()).await;

        if result.accepted {
            if let Some(ref receipt) = result.receipt {
                let raw_clone = raw.clone();
                let push = state.watcher_push.clone();
                let receipt_clone = receipt.clone();
                tokio::spawn(async move {
                    push.push_receipt(&receipt_clone, &raw_clone).await;
                });
            }
        }

        let receipt_resp = result.receipt.as_ref().map(|r| {
            let cesr = crate::crypto::cesr_encode_receipt(
                &r.witness_aid,
                &r.said,
                &r.signature_b64,
            );
            ReceiptResponse {
                id: r.id.to_string(),
                witness_aid: r.witness_aid.clone(),
                signature_b64: r.signature_b64.clone(),
                issued_at: r.issued_at.to_rfc3339(),
                cesr_encoded: Some(URL_SAFE_NO_PAD.encode(&cesr)),
            }
        });

        results.push(EventResponse {
            status: if result.accepted { "ok" } else { "error" },
            aid: incoming.aid.clone(),
            sn: incoming.sn.as_i64(),
            said: incoming.said.clone(),
            accepted: result.accepted,
            duplicate: result.duplicate,
            escrowed: result.escrowed,
            receipt: receipt_resp,
            error: result.error,
        });
    }

    let status = if results.len() == 1 {
        let r = &results[0];
        if r.accepted { StatusCode::CREATED }
        else if r.duplicate { StatusCode::CONFLICT }
        else if r.escrowed { StatusCode::ACCEPTED }
        else { StatusCode::UNPROCESSABLE_ENTITY }
    } else {
        StatusCode::MULTI_STATUS
    };

    Ok((status, Json(json!({
        "status": "ok",
        "data": {
            "results": results,
            "count": results.len(),
        }
    }))))
}

pub async fn get_kel(
    State(state): State<AppState>,
    Path(aid): Path<String>,
    Query(params): Query<KelQuery>,
) -> WitnessResult<Json<Value>> {
    let from_sn = params.from.unwrap_or(0);
    let limit = params.limit.unwrap_or(1000).min(10_000);
    let include_raw = params.include_raw.unwrap_or(false);

    let events = state.repo.get_kel(&aid, from_sn, limit).await?;
    let latest = state.repo.get_latest_event(&aid).await?;

    let event_list: Vec<Value> = events
        .iter()
        .map(|e| {
            let mut v = json!({
                "sn": e.sn,
                "said": e.said,
                "ilk": e.ilk,
                "first_seen_at": e.first_seen_at.to_rfc3339(),
                "prior_said": e.prior_said,
                "receipted": e.receipted,
            });
            if include_raw {
                v["raw"] = json!(URL_SAFE_NO_PAD.encode(&e.raw_event));
            }
            v
        })
        .collect();

    Ok(Json(json!({
        "status": "ok",
        "data": {
            "aid": aid,
            "events": event_list,
            "count": event_list.len(),
            "from_sn": from_sn,
            "latest_sn": latest.map(|e| e.sn).unwrap_or(-1),
        }
    })))
}

pub async fn get_kel_latest(
    State(state): State<AppState>,
    Path(aid): Path<String>,
) -> WitnessResult<Json<Value>> {
    let latest = state.repo.get_latest_event(&aid).await?;

    Ok(Json(json!({
        "status": "ok",
        "data": {
            "aid": aid,
            "latest": latest.map(|e| json!({
                "sn": e.sn,
                "said": e.said,
                "ilk": e.ilk,
                "first_seen_at": e.first_seen_at.to_rfc3339(),
            })),
        }
    })))
}

pub async fn get_receipt(
    State(state): State<AppState>,
    Path(aid): Path<String>,
    Query(params): Query<KelQuery>,
) -> WitnessResult<Json<Value>> {
    let sn = params.from.ok_or_else(|| {
        WitnessError::validation(&aid, 0, "sn query parameter is required")
    })?;

    let receipt = state.repo.get_receipt(&aid, sn).await?;

    match receipt {
        Some(r) => {
            let cesr = crate::crypto::cesr_encode_receipt(
                &r.witness_aid, &r.said, &r.signature_b64,
            );
            Ok(Json(json!({
                "status": "ok",
                "data": {
                    "id": r.id,
                    "aid": r.aid,
                    "sn": r.sn,
                    "said": r.said,
                    "witness_aid": r.witness_aid,
                    "signature_b64": r.signature_b64,
                    "issued_at": r.issued_at.to_rfc3339(),
                    "cesr_encoded": URL_SAFE_NO_PAD.encode(&cesr),
                }
            })))
        }
        None => Err(WitnessError::not_found(format!("No receipt for {aid} sn={sn}"))),
    }
}

pub async fn get_all_receipts(
    State(state): State<AppState>,
    Path(aid): Path<String>,
) -> WitnessResult<Json<Value>> {
    let receipts = state.repo.get_receipts_for_aid(&aid).await?;
    let data: Vec<Value> = receipts
        .iter()
        .map(|r| json!({
            "sn": r.sn,
            "said": r.said,
            "witness_aid": r.witness_aid,
            "signature_b64": r.signature_b64,
            "issued_at": r.issued_at.to_rfc3339(),
        }))
        .collect();

    Ok(Json(json!({
        "status": "ok",
        "data": {
            "aid": aid,
            "receipts": data,
            "count": data.len(),
        }
    })))
}