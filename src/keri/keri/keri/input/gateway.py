"""
Input Subsystem
================
Implements:
  - InputParser           : parses raw input into Message objects
  - InputQueue            : FIFO task queue for parsed messages
  - SenderCredentialVerifier : resolves sender AID from a message
  - InputGatewayModule    : orchestrates parsing → queuing → credential lookup
"""
from __future__ import annotations

import json
import queue
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.models import Message
from ..core.exceptions import ParseError
from ..identity.kel import IdentityAPI


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class InputParser:
    """
    Parses raw bytes/string/dict input into a Message object.
    Corresponds to 'Parser' in the Input Gateway Module.
    """

    def parse(self, raw: Any) -> Message:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode()
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, dict):
                data = raw
            else:
                raise ParseError(f"Unsupported input type: {type(raw)}")

            return Message(
                message_id=data.get("id", str(uuid.uuid4())),
                sender_aid=data.get("sender", ""),
                payload=data.get("payload", data),
                timestamp=data.get("timestamp", time.time()),
                signature=data.get("signature"),
                credentials=data.get("credentials", []),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            raise ParseError(f"Failed to parse input: {exc}") from exc


# ---------------------------------------------------------------------------
# Input Queue (FIFO)
# ---------------------------------------------------------------------------

class InputQueue:
    """
    Thread-safe FIFO queue for parsed input tasks.
    Corresponds to the queue box between Parser and processing steps.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._q: queue.Queue[Message] = queue.Queue(maxsize=maxsize)

    def put(self, message: Message, timeout: Optional[float] = None) -> None:
        self._q.put(message, timeout=timeout)

    def get(self, timeout: Optional[float] = None) -> Message:
        return self._q.get(timeout=timeout)

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()

    def empty(self) -> bool:
        return self._q.empty()

    def drain(self) -> List[Message]:
        """Drain all queued messages (useful for batch processing)."""
        results = []
        while not self._q.empty():
            try:
                results.append(self._q.get_nowait())
            except queue.Empty:
                break
        return results


# ---------------------------------------------------------------------------
# Sender Credential Verifier
# ---------------------------------------------------------------------------

class SenderCredentialVerifier:
    """
    Obtains and verifies sender credential reference from a message.
    Corresponds to 'Sender Credential verifier' + 'Obtain sender credential reference'.
    Uses IdentityAPI to look up the sender AID's current state.
    """

    def __init__(self, identity_api: IdentityAPI) -> None:
        self._identity_api = identity_api

    def verify(self, message: Message) -> bool:
        """
        Returns True if the sender's AID is known and has an active KEL.
        """
        if not message.sender_aid:
            return False
        state = self._identity_api.resolve_aid(message.sender_aid)
        return state is not None

    def get_sender_keys(self, message: Message) -> List[str]:
        return self._identity_api.get_current_keys(message.sender_aid)


# ---------------------------------------------------------------------------
# Input Gateway Module
# ---------------------------------------------------------------------------

class InputGatewayModule:
    """
    Orchestrates the full input pipeline:
      raw input → parse → queue → verify sender → forward for processing.
    Corresponds to 'Input Gateway module' in the diagram.
    """

    def __init__(
        self,
        parser: InputParser,
        queue: InputQueue,
        sender_verifier: SenderCredentialVerifier,
    ) -> None:
        self._parser = parser
        self._queue = queue
        self._sender_verifier = sender_verifier

    def ingest(self, raw: Any) -> Message:
        """Parse raw input and enqueue for processing."""
        message = self._parser.parse(raw)
        self._queue.put(message)
        return message

    def process_next(
        self,
        handler: Callable[[Message, bool], Any],
        timeout: Optional[float] = 1.0,
    ) -> Any:
        """
        Dequeue next message, verify sender, and call handler(message, sender_ok).
        """
        try:
            message = self._queue.get(timeout=timeout)
            sender_ok = self._sender_verifier.verify(message)
            result = handler(message, sender_ok)
            self._queue.task_done()
            return result
        except Exception:
            raise

    def pending_count(self) -> int:
        return self._queue.qsize()
