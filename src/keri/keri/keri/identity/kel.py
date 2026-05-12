"""
Identity & KEL System
=====================
Implements:
  - InceptionEngine  : creates inception events from genesis policy
  - KELManager       : manages the Key Event Log for an AID
  - KELSelfValidator : validates KEL events locally
  - KELStoreCRUD     : append-only KEL store
  - IdentityStateDB  : resolved identity state store
  - IdentityAPI      : facade for AID, Seq, state management
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from ..core.models import (
    KELEvent, EventType, IdentityState, GenesisPolicy, KeyPair,
)
from ..core.crypto import (
    generate_key_pair, derive_next_key_digest, sign, hash_data, prefix_from_public_key,
)
from ..core.exceptions import ValidationError, IdentityError


# ---------------------------------------------------------------------------
# KEL append-only store
# ---------------------------------------------------------------------------

class KELStore:
    """In-memory append-only Key Event Log store."""

    def __init__(self) -> None:
        self._events: Dict[str, List[KELEvent]] = {}  # aid -> ordered events

    def append(self, event: KELEvent) -> None:
        aid = event.aid
        if aid not in self._events:
            self._events[aid] = []
        self._events[aid].append(event)

    def get_events(self, aid: str) -> List[KELEvent]:
        return list(self._events.get(aid, []))

    def get_latest(self, aid: str) -> Optional[KELEvent]:
        events = self._events.get(aid)
        return events[-1] if events else None

    def get_at_seq(self, aid: str, seq_no: int) -> Optional[KELEvent]:
        for evt in self._events.get(aid, []):
            if evt.seq_no == seq_no:
                return evt
        return None

    def list_aids(self) -> List[str]:
        return list(self._events.keys())


# ---------------------------------------------------------------------------
# KEL Self-Validator
# ---------------------------------------------------------------------------

class KELSelfValidator:
    """Validates an incoming KEL event against the existing log."""

    def __init__(self, store: KELStore) -> None:
        self._store = store

    def validate(self, event: KELEvent) -> None:
        existing = self._store.get_events(event.aid)

        if event.event_type in (EventType.INCEPTION, EventType.DELEGATED_INCEPTION):
            if existing:
                raise ValidationError(f"Inception event already exists for AID {event.aid}")
            if event.seq_no != 0:
                raise ValidationError("Inception event must have seq_no=0")
        else:
            if not existing:
                raise ValidationError(f"No inception event found for AID {event.aid}")
            last = existing[-1]
            if event.seq_no != last.seq_no + 1:
                raise ValidationError(
                    f"Seq_no mismatch: expected {last.seq_no + 1}, got {event.seq_no}"
                )
            if event.prior_event_digest != last.digest():
                raise ValidationError("Prior event digest mismatch")

        if not event.keys:
            raise ValidationError("Event must contain at least one key")


# ---------------------------------------------------------------------------
# Identity State DB
# ---------------------------------------------------------------------------

class IdentityStateDB:
    """Stores resolved IdentityState per AID."""

    def __init__(self) -> None:
        self._states: Dict[str, IdentityState] = {}

    def save(self, state: IdentityState) -> None:
        self._states[state.aid] = state

    def get(self, aid: str) -> Optional[IdentityState]:
        return self._states.get(aid)

    def list_aids(self) -> List[str]:
        return list(self._states.keys())


# ---------------------------------------------------------------------------
# KEL Manager
# ---------------------------------------------------------------------------

class KELManager:
    """Orchestrates KEL event processing: validate → store → update state."""

    def __init__(
        self,
        store: KELStore,
        validator: KELSelfValidator,
        state_db: IdentityStateDB,
    ) -> None:
        self._store = store
        self._validator = validator
        self._state_db = state_db

    def process_event(self, event: KELEvent) -> IdentityState:
        self._validator.validate(event)
        self._store.append(event)
        state = self._derive_state(event)
        self._state_db.save(state)
        return state

    def _derive_state(self, event: KELEvent) -> IdentityState:
        existing_state = self._state_db.get(event.aid)
        return IdentityState(
            aid=event.aid,
            current_keys=list(event.keys),
            next_key_digests=[event.next_key_digest] if event.next_key_digest else [],
            seq_no=event.seq_no,
            witnesses=list(event.witnesses),
            delegator=event.delegator,
            last_event_digest=event.digest(),
            is_delegated=event.delegator is not None,
        )

    def get_state(self, aid: str) -> Optional[IdentityState]:
        return self._state_db.get(aid)

    def get_kel(self, aid: str) -> List[KELEvent]:
        return self._store.get_events(aid)


# ---------------------------------------------------------------------------
# Inception Engine
# ---------------------------------------------------------------------------

class InceptionEngine:
    """
    Creates inception events based on a genesis policy (role config).
    Wired to: role config → genesis policy loader → governance rules loader → InceptionEngine.
    """

    def __init__(self, kel_manager: KELManager) -> None:
        self._kel_manager = kel_manager

    def create_inception(
        self,
        policy: GenesisPolicy,
        hot_key_pair: KeyPair,
        pre_rotation_key_pair: KeyPair,
        delegator_aid: Optional[str] = None,
        private_key_for_signing: str = "",
    ) -> KELEvent:
        """
        Generate and process an inception event.
        Returns the KELEvent and persists it via KELManager.
        """
        aid = prefix_from_public_key(hot_key_pair.public_key)
        next_digest = derive_next_key_digest(pre_rotation_key_pair.public_key)

        event_type = EventType.DELEGATED_INCEPTION if delegator_aid else EventType.INCEPTION
        event = KELEvent(
            event_type=event_type,
            aid=aid,
            seq_no=0,
            keys=[hot_key_pair.public_key],
            next_key_digest=next_digest,
            witnesses=list(policy.witnesses),
            delegator=delegator_aid,
        )

        if private_key_for_signing:
            event.signature = sign(event.serialize(), private_key_for_signing)

        self._kel_manager.process_event(event)
        return event


# ---------------------------------------------------------------------------
# Identity API facade
# ---------------------------------------------------------------------------

class IdentityAPI:
    """
    Public API used by other subsystems to resolve AID, Seq, and state.
    Matches 'Identity API (used for AID, Seq, state management)' in the diagram.
    """

    def __init__(self, kel_manager: KELManager) -> None:
        self._kel_manager = kel_manager

    def resolve_aid(self, aid: str) -> Optional[IdentityState]:
        return self._kel_manager.get_state(aid)

    def get_sequence_number(self, aid: str) -> int:
        state = self._kel_manager.get_state(aid)
        return state.seq_no if state else -1

    def get_current_keys(self, aid: str) -> List[str]:
        state = self._kel_manager.get_state(aid)
        return state.current_keys if state else []

    def get_kel(self, aid: str) -> List[KELEvent]:
        return self._kel_manager.get_kel(aid)

    def is_connected(self, aid: str) -> bool:
        """Returns True if the AID has a resolved identity state."""
        return self._kel_manager.get_state(aid) is not None
