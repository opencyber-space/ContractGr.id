"""
Output Subsystem
=================
Implements:
  - OutputQueue      : FIFO queue for outbound messages
  - OutputSigner     : signs outbound messages/events
  - OutputManager    : orchestrates output queuing and signing
  - OutputCollector  : collects and dispatches finalized output
"""
from __future__ import annotations

import json
import queue
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.models import Message
from ..core.crypto import sign, hash_data
from ..core.exceptions import KERIError


# ---------------------------------------------------------------------------
# Output Envelope
# ---------------------------------------------------------------------------

@dataclass
class OutputEnvelope:
    """Signed outbound message ready for delivery."""
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message: Optional[Message] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    sender_aid: str = ""
    signature: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "sender_aid": self.sender_aid,
            "payload": self.payload,
            "signature": self.signature,
            "timestamp": self.timestamp,
        }

    def serialize(self) -> str:
        d = self.to_dict()
        d.pop("signature", None)
        return json.dumps(d, sort_keys=True)


# ---------------------------------------------------------------------------
# Output Queue
# ---------------------------------------------------------------------------

class OutputQueue:
    """
    Thread-safe FIFO queue for outbound messages.
    Corresponds to the output queue boxes in the diagram.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._q: queue.Queue[OutputEnvelope] = queue.Queue(maxsize=maxsize)

    def put(self, envelope: OutputEnvelope, timeout: Optional[float] = None) -> None:
        self._q.put(envelope, timeout=timeout)

    def get(self, timeout: Optional[float] = None) -> OutputEnvelope:
        return self._q.get(timeout=timeout)

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()

    def empty(self) -> bool:
        return self._q.empty()

    def drain(self) -> List[OutputEnvelope]:
        results = []
        while not self._q.empty():
            try:
                results.append(self._q.get_nowait())
            except queue.Empty:
                break
        return results


# ---------------------------------------------------------------------------
# Output Signer
# ---------------------------------------------------------------------------

class OutputSigner:
    """
    Signs outgoing output envelopes.
    Corresponds to 'Output signer' in the diagram.
    """

    def __init__(self, private_key: str = "") -> None:
        self._private_key = private_key

    def set_private_key(self, private_key: str) -> None:
        self._private_key = private_key

    def sign(self, envelope: OutputEnvelope) -> OutputEnvelope:
        if self._private_key:
            envelope.signature = sign(envelope.serialize(), self._private_key)
        else:
            envelope.signature = "unsigned"
        return envelope


# ---------------------------------------------------------------------------
# Output Manager
# ---------------------------------------------------------------------------

class OutputManager:
    """
    Assembles outbound envelopes from processed messages, queues them,
    and forwards to the Output Signer.
    Corresponds to 'Output Manager' in the diagram.
    """

    def __init__(
        self,
        output_queue: OutputQueue,
        output_signer: OutputSigner,
    ) -> None:
        self._queue = output_queue
        self._signer = output_signer

    def submit(
        self,
        message: Message,
        payload: Optional[Dict[str, Any]] = None,
        sender_aid: str = "",
    ) -> OutputEnvelope:
        """Create a signed envelope and enqueue it."""
        envelope = OutputEnvelope(
            message=message,
            payload=payload or message.payload,
            sender_aid=sender_aid or message.sender_aid,
        )
        self._signer.sign(envelope)
        self._queue.put(envelope)
        return envelope

    def pending_count(self) -> int:
        return self._queue.qsize()


# ---------------------------------------------------------------------------
# Output Collector
# ---------------------------------------------------------------------------

class OutputCollector:
    """
    Collects signed envelopes from the output queue and dispatches them
    to registered handlers (e.g. network transport, storage, logging).
    Corresponds to 'Output collector' in the diagram.
    """

    def __init__(self, output_queue: OutputQueue) -> None:
        self._queue = output_queue
        self._handlers: List[Callable[[OutputEnvelope], None]] = []
        self._collected: List[OutputEnvelope] = []

    def register_handler(self, handler: Callable[[OutputEnvelope], None]) -> None:
        self._handlers.append(handler)

    def collect_all(self) -> List[OutputEnvelope]:
        """Drain the queue and dispatch to all handlers."""
        envelopes = self._queue.drain()
        for envelope in envelopes:
            self._collected.append(envelope)
            for handler in self._handlers:
                handler(envelope)
        return envelopes

    def collect_next(self, timeout: float = 1.0) -> Optional[OutputEnvelope]:
        """Collect and dispatch next envelope."""
        try:
            envelope = self._queue.get(timeout=timeout)
            self._collected.append(envelope)
            for handler in self._handlers:
                handler(envelope)
            self._queue.task_done()
            return envelope
        except Exception:
            return None

    def collected(self) -> List[OutputEnvelope]:
        return list(self._collected)
