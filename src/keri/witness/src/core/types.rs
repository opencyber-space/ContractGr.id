use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EventIlk {
    Icp,
    Rot,
    Ixn,
    Dip,
    Drt,
    Rct,
}

impl EventIlk {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "icp" => Some(Self::Icp),
            "rot" => Some(Self::Rot),
            "ixn" => Some(Self::Ixn),
            "dip" => Some(Self::Dip),
            "drt" => Some(Self::Drt),
            "rct" => Some(Self::Rct),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Icp => "icp",
            Self::Rot => "rot",
            Self::Ixn => "ixn",
            Self::Dip => "dip",
            Self::Drt => "drt",
            Self::Rct => "rct",
        }
    }

    pub fn is_inception(&self) -> bool {
        matches!(self, Self::Icp | Self::Dip)
    }

    pub fn is_rotation(&self) -> bool {
        matches!(self, Self::Rot | Self::Drt)
    }
}

impl std::fmt::Display for EventIlk {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyEvent {
    pub aid: String,
    pub sn: i64,
    pub said: String,
    pub ilk: EventIlk,
    pub raw: Vec<u8>,
    pub prior_said: Option<String>,
    pub keys: Vec<String>,
    pub next_key_digests: Vec<String>,
    pub witnesses: Vec<String>,
    pub witness_threshold: u64,
    pub signatures: Vec<Signature>,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Signature {
    pub index: usize,
    pub value_b64: String,
    pub verifier_key_b64: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Receipt {
    pub id: Uuid,
    pub aid: String,
    pub sn: i64,
    pub said: String,
    pub witness_aid: String,
    pub signature_b64: String,
    pub issued_at: DateTime<Utc>,
    pub ilk: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredEvent {
    pub aid: String,
    pub sn: i64,
    pub said: String,
    pub ilk: String,
    pub raw_event: Vec<u8>,
    pub prior_said: Option<String>,
    pub first_seen_at: DateTime<Utc>,
    pub receipted: bool,
    pub receipt_sig: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DuplicityRecord {
    pub id: Uuid,
    pub aid: String,
    pub sn: i64,
    pub first_said: String,
    pub conflict_said: String,
    pub detected_at: DateTime<Utc>,
    pub resolved: bool,
    pub resolved_at: Option<DateTime<Utc>>,
    pub notes: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EscrowRecord {
    pub id: Uuid,
    pub aid: String,
    pub sn: Option<i64>,
    pub said: Option<String>,
    pub raw_event: Vec<u8>,
    pub reason: String,
    pub retry_count: i32,
    pub received_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WatcherRecord {
    pub url: String,
    pub last_push_at: Option<DateTime<Utc>>,
    pub consecutive_errors: i32,
    pub enabled: bool,
}

#[derive(Debug, Clone)]
pub struct ProcessingResult {
    pub accepted: bool,
    pub receipt: Option<Receipt>,
    pub duplicate: bool,
    pub escrowed: bool,
    pub error: Option<String>,
}

impl ProcessingResult {
    pub fn accepted(receipt: Receipt) -> Self {
        Self { accepted: true, receipt: Some(receipt), duplicate: false, escrowed: false, error: None }
    }

    pub fn rejected(reason: impl Into<String>) -> Self {
        Self { accepted: false, receipt: None, duplicate: false, escrowed: false, error: Some(reason.into()) }
    }

    pub fn duplicate() -> Self {
        Self { accepted: false, receipt: None, duplicate: true, escrowed: false, error: None }
    }

    pub fn escrowed() -> Self {
        Self { accepted: false, receipt: None, duplicate: false, escrowed: true, error: None }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IncomingEvent {
    #[serde(rename = "v")]
    pub version: Option<String>,
    #[serde(rename = "t")]
    pub ilk: String,
    #[serde(rename = "d")]
    pub said: String,
    #[serde(rename = "i")]
    pub aid: String,
    #[serde(rename = "s")]
    pub sn: SnField,
    #[serde(rename = "p")]
    pub prior: Option<String>,
    #[serde(rename = "k", default)]
    pub keys: Vec<String>,
    #[serde(rename = "n", default)]
    pub next_key_digests: Vec<String>,
    #[serde(rename = "b", default)]
    pub witnesses: Vec<String>,
    #[serde(rename = "bt")]
    pub witness_threshold: Option<serde_json::Value>,
    #[serde(rename = "a", default)]
    pub data: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum SnField {
    Hex(String),
    Int(i64),
}

impl SnField {
    pub fn as_i64(&self) -> i64 {
        match self {
            Self::Hex(s) => i64::from_str_radix(s.trim_start_matches("0x"), 16).unwrap_or(0),
            Self::Int(n) => *n,
        }
    }
}