"""
Core data models for the KERI architecture.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    INCEPTION = "icp"
    ROTATION = "rot"
    INTERACTION = "ixn"
    DELEGATED_INCEPTION = "dip"
    DELEGATED_ROTATION = "drt"


class CredentialStatus(str, Enum):
    ISSUED = "issued"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class KeyPair:
    public_key: str
    private_key: str
    key_type: str = "Ed25519"

    def to_dict(self) -> Dict[str, Any]:
        return {"public_key": self.public_key, "key_type": self.key_type}


@dataclass
class Prefix:
    """Autonomic Identifier (AID)"""
    aid: str
    inception_key: str
    seq_no: int = 0

    def __str__(self) -> str:
        return self.aid


@dataclass
class KELEvent:
    """Key Event Log entry"""
    event_type: EventType
    aid: str
    seq_no: int
    keys: List[str]
    next_key_digest: Optional[str] = None
    witnesses: List[str] = field(default_factory=list)
    anchors: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signature: Optional[str] = None
    prior_event_digest: Optional[str] = None
    delegator: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t": self.event_type.value,
            "i": self.aid,
            "s": self.seq_no,
            "kt": "1",
            "k": self.keys,
            "n": self.next_key_digest or "",
            "b": self.witnesses,
            "a": self.anchors,
            "ts": self.timestamp,
            "d": self.event_id,
            "p": self.prior_event_digest or "",
            "di": self.delegator or "",
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def digest(self) -> str:
        return hashlib.sha256(self.serialize().encode()).hexdigest()


@dataclass
class Credential:
    """ACDC (Authentic Chained Data Container) credential"""
    credential_id: str
    issuer_aid: str
    subject_aid: str
    schema_id: str
    claims: Dict[str, Any]
    status: CredentialStatus = CredentialStatus.ISSUED
    issued_at: float = field(default_factory=time.time)
    expiry: Optional[float] = None
    chain: List[str] = field(default_factory=list)  # chained credential IDs
    signature: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.credential_id,
            "issuer": self.issuer_aid,
            "subject": self.subject_aid,
            "schema": self.schema_id,
            "claims": self.claims,
            "status": self.status.value,
            "issued_at": self.issued_at,
            "expiry": self.expiry,
            "chain": self.chain,
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def digest(self) -> str:
        return hashlib.sha256(self.serialize().encode()).hexdigest()


@dataclass
class Message:
    """A message flowing through the system"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender_aid: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    signature: Optional[str] = None
    credentials: List[str] = field(default_factory=list)  # credential IDs
    evidence_digest: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.message_id,
            "sender": self.sender_aid,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "credentials": self.credentials,
        }


@dataclass
class Evidence:
    """Audit evidence record"""
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_id: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
    hash_value: Optional[str] = None
    signature: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def compute_hash(self) -> str:
        raw = json.dumps(self.raw_data, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class GenesisPolicy:
    """Genesis policy loaded from role configuration"""
    policy_id: str
    org: str
    block: str
    instance: str
    thresholds: Dict[str, Any] = field(default_factory=dict)
    witnesses: List[str] = field(default_factory=list)
    rules: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "org": self.org,
            "block": self.block,
            "instance": self.instance,
            "thresholds": self.thresholds,
            "witnesses": self.witnesses,
            "rules": self.rules,
        }


@dataclass
class IdentityState:
    """Current resolved state of an AID"""
    aid: str
    current_keys: List[str] = field(default_factory=list)
    next_key_digests: List[str] = field(default_factory=list)
    seq_no: int = 0
    witnesses: List[str] = field(default_factory=list)
    delegator: Optional[str] = None
    last_event_digest: Optional[str] = None
    is_delegated: bool = False
