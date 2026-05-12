use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use thiserror::Error;

pub type WitnessResult<T> = Result<T, WitnessError>;

#[derive(Debug, Error)]
pub enum WitnessError {
    #[error("Validation failed for {aid} sn={sn}: {reason}")]
    Validation {
        aid: String,
        sn: i64,
        reason: String,
    },

    #[error("Duplicity detected for {aid} at sn={sn}: first={first_said} conflict={conflict_said}")]
    Duplicity {
        aid: String,
        sn: i64,
        first_said: String,
        conflict_said: String,
    },

    #[error("Event escrowed for {aid} at sn={sn}: {reason}")]
    Escrowed {
        aid: String,
        sn: i64,
        reason: String,
    },

    #[error("Event queue is full")]
    QueueFull,

    #[error("Database error: {0}")]
    Database(#[from] sqlx::Error),

    #[error("Database error: {0}")]
    DatabaseMsg(String),

    #[error("Cryptographic error: {reason}")]
    Crypto { reason: String },

    #[error("Signature verification failed for {aid}: {reason}")]
    SignatureVerification { aid: String, reason: String },

    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("HTTP client error: {0}")]
    HttpClient(#[from] reqwest::Error),

    #[error("Configuration error: {0}")]
    Config(String),

    #[error("Not found: {0}")]
    NotFound(String),

    #[error("Already exists: {0}")]
    AlreadyExists(String),

    #[error("Rate limit exceeded")]
    RateLimited,

    #[error("Internal error: {0}")]
    Internal(String),
}

impl WitnessError {
    pub fn validation(aid: impl Into<String>, sn: i64, reason: impl Into<String>) -> Self {
        Self::Validation { aid: aid.into(), sn, reason: reason.into() }
    }

    pub fn duplicity(
        aid: impl Into<String>,
        sn: i64,
        first_said: impl Into<String>,
        conflict_said: impl Into<String>,
    ) -> Self {
        Self::Duplicity {
            aid: aid.into(),
            sn,
            first_said: first_said.into(),
            conflict_said: conflict_said.into(),
        }
    }

    pub fn crypto(reason: impl Into<String>) -> Self {
        Self::Crypto { reason: reason.into() }
    }

    pub fn sig_verify(aid: impl Into<String>, reason: impl Into<String>) -> Self {
        Self::SignatureVerification { aid: aid.into(), reason: reason.into() }
    }

    pub fn internal(reason: impl Into<String>) -> Self {
        Self::Internal(reason.into())
    }

    pub fn not_found(msg: impl Into<String>) -> Self {
        Self::NotFound(msg.into())
    }

    fn status_code(&self) -> StatusCode {
        match self {
            Self::Validation { .. } => StatusCode::UNPROCESSABLE_ENTITY,
            Self::Duplicity { .. } => StatusCode::CONFLICT,
            Self::Escrowed { .. } => StatusCode::ACCEPTED,
            Self::QueueFull => StatusCode::TOO_MANY_REQUESTS,
            Self::Database(_) | Self::DatabaseMsg(_) => StatusCode::INTERNAL_SERVER_ERROR,
            Self::Crypto { .. } => StatusCode::INTERNAL_SERVER_ERROR,
            Self::SignatureVerification { .. } => StatusCode::UNPROCESSABLE_ENTITY,
            Self::Serialization(_) => StatusCode::BAD_REQUEST,
            Self::HttpClient(_) => StatusCode::BAD_GATEWAY,
            Self::Config(_) => StatusCode::INTERNAL_SERVER_ERROR,
            Self::NotFound(_) => StatusCode::NOT_FOUND,
            Self::AlreadyExists(_) => StatusCode::CONFLICT,
            Self::RateLimited => StatusCode::TOO_MANY_REQUESTS,
            Self::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    fn error_code(&self) -> &'static str {
        match self {
            Self::Validation { .. } => "validation_error",
            Self::Duplicity { .. } => "duplicity_detected",
            Self::Escrowed { .. } => "escrowed",
            Self::QueueFull => "queue_full",
            Self::Database(_) | Self::DatabaseMsg(_) => "database_error",
            Self::Crypto { .. } => "crypto_error",
            Self::SignatureVerification { .. } => "signature_verification_failed",
            Self::Serialization(_) => "serialization_error",
            Self::HttpClient(_) => "upstream_error",
            Self::Config(_) => "config_error",
            Self::NotFound(_) => "not_found",
            Self::AlreadyExists(_) => "already_exists",
            Self::RateLimited => "rate_limited",
            Self::Internal(_) => "internal_error",
        }
    }
}

impl IntoResponse for WitnessError {
    fn into_response(self) -> Response {
        let status = self.status_code();
        let body = json!({
            "status": "error",
            "error": {
                "code": self.error_code(),
                "message": self.to_string(),
            }
        });
        (status, Json(body)).into_response()
    }
}

impl From<anyhow::Error> for WitnessError {
    fn from(e: anyhow::Error) -> Self {
        Self::Internal(e.to_string())
    }
}