use axum::{
    extract::{Path, Query, State},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::api::state::AppState;
use crate::utils::errors::{WitnessError, WitnessResult};

#[derive(Debug, Deserialize)]
pub struct DuplicityQuery {
    pub aid: Option<String>,
    pub resolved: Option<bool>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct ResolveBody {
    pub action: String,
    pub notes: Option<String>,
}

pub async fn list_duplicity(
    State(state): State<AppState>,
    Query(params): Query<DuplicityQuery>,
) -> WitnessResult<Json<Value>> {
    let limit = params.limit.unwrap_or(100).min(1000);
    let offset = params.offset.unwrap_or(0).max(0);

    let records = state
        .repo
        .list_duplicity(params.aid.as_deref(), params.resolved, limit, offset)
        .await?;

    let data: Vec<Value> = records
        .iter()
        .map(|r| json!({
            "id": r.id,
            "aid": r.aid,
            "sn": r.sn,
            "first_said": r.first_said,
            "conflict_said": r.conflict_said,
            "detected_at": r.detected_at.to_rfc3339(),
            "resolved": r.resolved,
            "resolved_at": r.resolved_at.map(|t| t.to_rfc3339()),
            "notes": r.notes,
        }))
        .collect();

    Ok(Json(json!({
        "status": "ok",
        "data": {
            "duplicity": data,
            "count": data.len(),
            "limit": limit,
            "offset": offset,
        }
    })))
}

pub async fn list_duplicity_by_aid(
    State(state): State<AppState>,
    Path(aid): Path<String>,
    Query(params): Query<DuplicityQuery>,
) -> WitnessResult<Json<Value>> {
    let limit = params.limit.unwrap_or(100).min(1000);
    let offset = params.offset.unwrap_or(0).max(0);

    let records = state
        .repo
        .list_duplicity(Some(&aid), params.resolved, limit, offset)
        .await?;

    let data: Vec<Value> = records
        .iter()
        .map(|r| json!({
            "id": r.id,
            "aid": r.aid,
            "sn": r.sn,
            "first_said": r.first_said,
            "conflict_said": r.conflict_said,
            "detected_at": r.detected_at.to_rfc3339(),
            "resolved": r.resolved,
            "resolved_at": r.resolved_at.map(|t| t.to_rfc3339()),
        }))
        .collect();

    Ok(Json(json!({
        "status": "ok",
        "data": {
            "aid": aid,
            "duplicity": data,
            "count": data.len(),
        }
    })))
}

pub async fn resolve_duplicity(
    State(state): State<AppState>,
    Path(id_str): Path<String>,
    Json(body): Json<ResolveBody>,
) -> WitnessResult<Json<Value>> {
    if body.action != "resolve" {
        return Err(WitnessError::validation(
            "",
            0,
            format!("unknown action '{}', expected 'resolve'", body.action),
        ));
    }

    let id = Uuid::parse_str(&id_str)
        .map_err(|_| WitnessError::validation("", 0, format!("invalid UUID: {id_str}")))?;

    let resolved = state
        .repo
        .resolve_duplicity(&id, body.notes.as_deref())
        .await?;

    if !resolved {
        return Err(WitnessError::not_found(format!(
            "Duplicity {id} not found or already resolved"
        )));
    }

    Ok(Json(json!({
        "status": "ok",
        "data": {
            "id": id_str,
            "message": "Duplicity event resolved",
        }
    })))
}