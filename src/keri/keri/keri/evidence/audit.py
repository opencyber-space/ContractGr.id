"""
Audit and Evidence Subsystem
==============================
Implements:
  - EvidenceBuilder    : constructs evidence from a message
  - EvidenceHasher     : hashes the evidence data
  - EvidenceHashSigner : signs the evidence hash
  - EvidenceStoreAPI   : persists evidence records
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from ..core.models import Evidence, Message
from ..core.crypto import hash_data, sign
from ..core.exceptions import EvidenceError


# ---------------------------------------------------------------------------
# Evidence Builder
# ---------------------------------------------------------------------------

class EvidenceBuilder:
    """
    Constructs an Evidence record from a processed Message.
    Corresponds to 'Evidence Builder' in the Audit and Evidence section.
    """

    def build(self, message: Message, extra: Optional[Dict[str, Any]] = None) -> Evidence:
        raw_data: Dict[str, Any] = {
            "message_id": message.message_id,
            "sender_aid": message.sender_aid,
            "payload": message.payload,
            "timestamp": message.timestamp,
            "credentials": message.credentials,
        }
        if extra:
            raw_data.update(extra)
        return Evidence(
            evidence_id=str(uuid.uuid4()),
            message_id=message.message_id,
            raw_data=raw_data,
            timestamp=time.time(),
        )


# ---------------------------------------------------------------------------
# Evidence Hasher
# ---------------------------------------------------------------------------

class EvidenceHasher:
    """
    Hashes an Evidence record's raw data.
    Corresponds to 'Evidence Hasher'.
    """

    def hash(self, evidence: Evidence) -> str:
        digest = evidence.compute_hash()
        evidence.hash_value = digest
        return digest


# ---------------------------------------------------------------------------
# Evidence Hash Signer
# ---------------------------------------------------------------------------

class EvidenceHashSigner:
    """
    Signs the evidence hash using the node's private key.
    Corresponds to 'Evidence hash signer'.
    """

    def __init__(self, private_key: str = "") -> None:
        self._private_key = private_key

    def set_private_key(self, private_key: str) -> None:
        self._private_key = private_key

    def sign(self, evidence: Evidence) -> str:
        if not evidence.hash_value:
            raise EvidenceError("Evidence must be hashed before signing")
        if not self._private_key:
            # Allow unsigned evidence in dev mode
            evidence.signature = "unsigned"
            return "unsigned"
        sig = sign(evidence.hash_value, self._private_key)
        evidence.signature = sig
        return sig


# ---------------------------------------------------------------------------
# Evidence Store API
# ---------------------------------------------------------------------------

class EvidenceStoreAPI:
    """
    Persists and retrieves evidence records.
    Corresponds to 'Evidence store API'.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Evidence] = {}
        self._by_message: Dict[str, List[str]] = {}  # message_id -> [evidence_ids]

    def save(self, evidence: Evidence) -> None:
        if not evidence.hash_value:
            raise EvidenceError("Only hashed evidence may be stored")
        self._store[evidence.evidence_id] = evidence
        self._by_message.setdefault(evidence.message_id, []).append(evidence.evidence_id)

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self._store.get(evidence_id)

    def get_for_message(self, message_id: str) -> List[Evidence]:
        ids = self._by_message.get(message_id, [])
        return [self._store[eid] for eid in ids if eid in self._store]

    def list_all(self) -> List[Evidence]:
        return list(self._store.values())


# ---------------------------------------------------------------------------
# Evidence Pipeline (convenience wrapper)
# ---------------------------------------------------------------------------

class EvidencePipeline:
    """
    Runs the full evidence pipeline: build → hash → sign → store.
    """

    def __init__(
        self,
        builder: EvidenceBuilder,
        hasher: EvidenceHasher,
        signer: EvidenceHashSigner,
        store: EvidenceStoreAPI,
    ) -> None:
        self._builder = builder
        self._hasher = hasher
        self._signer = signer
        self._store = store

    def process(
        self,
        message: Message,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Evidence:
        evidence = self._builder.build(message, extra)
        self._hasher.hash(evidence)
        self._signer.sign(evidence)
        self._store.save(evidence)
        return evidence
