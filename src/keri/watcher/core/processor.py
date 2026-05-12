from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from keri_watcher.config import WatcherConfig
from keri_watcher.db.lmdb import WatcherLMDB
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.utils.errors import (
    DuplicityError,
    EscrowError,
    NotWatchedError,
    ValidationError,
)
from keri_watcher.utils.logging import get_logger, set_aid_context
from keri_watcher.utils import metrics as m

log = get_logger(__name__)


@dataclass
class RawEvent:
    aid: str
    sn: int
    said: str
    ilk: str
    raw: bytes
    prior_said: Optional[str] = None
    source_witness: Optional[str] = None
    sigers: List[Any] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessingResult:
    accepted: bool
    duplicate: bool = False
    escrowed: bool = False
    error: Optional[str] = None


class EventProcessor:
    def __init__(
        self,
        config: WatcherConfig,
        repo: TimescaleRepository,
        lmdb: WatcherLMDB,
    ) -> None:
        self._config = config
        self._repo = repo
        self._lmdb = lmdb
        self._queue: asyncio.Queue[RawEvent] = asyncio.Queue(
            maxsize=config.max_event_queue_size
        )
        self._running = False
        self._workers: List[asyncio.Task] = []
        self._stats = _ProcessorStats()

    async def start(self, num_workers: int = 4) -> None:
        self._running = True
        for i in range(num_workers):
            task = asyncio.create_task(
                self._worker(f"worker-{i}"),
                name=f"event-processor-{i}",
            )
            self._workers.append(task)
        log.info_kw("Event processor started", workers=num_workers)

    async def stop(self) -> None:
        self._running = False
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        log.info_kw("Event processor stopped")

    async def submit(self, event: RawEvent) -> None:
        if not self._running:
            raise RuntimeError("Processor is not running")
        m.EVENTS_RECEIVED.labels(ilk=event.ilk, source=event.source_witness or "unknown").inc()
        m.QUEUE_SIZE.set(self._queue.qsize())
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            m.EVENTS_REJECTED.labels(reason="queue_full").inc()
            self._stats.rejected += 1
            log.warning_kw("Event queue full, dropping event", aid=event.aid, sn=event.sn)
            raise

    async def submit_batch(self, events: List[RawEvent]) -> int:
        accepted = 0
        for event in events:
            try:
                await self.submit(event)
                accepted += 1
            except asyncio.QueueFull:
                break
        return accepted

    async def process_immediate(self, event: RawEvent) -> ProcessingResult:
        return await self._process_event(event)

    async def _worker(self, name: str) -> None:
        log.debug_kw("Worker started", worker=name)
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if event is None:
                    break
                m.QUEUE_SIZE.set(self._queue.qsize())
                await self._process_event(event)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                log.error_kw("Worker unhandled error", worker=name, error=str(exc))
        log.debug_kw("Worker stopped", worker=name)

    async def _process_event(self, event: RawEvent) -> ProcessingResult:
        set_aid_context(event.aid)
        start = time.monotonic()

        try:
            is_watched = await self._repo.get_watched_aid(event.aid)
            if not is_watched:
                m.EVENTS_REJECTED.labels(reason="not_watched").inc()
                self._stats.rejected += 1
                return ProcessingResult(accepted=False, error="not_watched")

            existing_said = self._lmdb.get_first_seen_said(event.aid, event.sn)

            if existing_said is not None and existing_said != event.said:
                await self._handle_duplicity(event, existing_said)
                self._stats.duplicity += 1
                return ProcessingResult(accepted=False, duplicate=True)

            if existing_said == event.said:
                return ProcessingResult(accepted=True)

            valid, reason = await self._validate_event(event)
            if not valid:
                if reason == "missing_prior":
                    await self._escrow_event(event, reason)
                    self._stats.escrowed += 1
                    return ProcessingResult(accepted=False, escrowed=True)
                m.EVENTS_REJECTED.labels(reason=reason).inc()
                self._stats.rejected += 1
                return ProcessingResult(accepted=False, error=reason)

            stored = self._lmdb.put_first_seen_said(event.aid, event.sn, event.said)

            if stored:
                await self._repo.record_first_seen(
                    aid=event.aid,
                    sn=event.sn,
                    said=event.said,
                    ilk=event.ilk,
                    raw_event=event.raw,
                    source_witness=event.source_witness,
                    prior_said=event.prior_said,
                )
                m.EVENTS_PROCESSED.labels(ilk=event.ilk).inc()
                self._stats.processed += 1

                await self._process_escrow_for_aid(event.aid, event.sn)

            duration = time.monotonic() - start
            log.debug_kw(
                "Event processed",
                aid=event.aid,
                sn=event.sn,
                ilk=event.ilk,
                duration_ms=round(duration * 1000, 1),
            )
            return ProcessingResult(accepted=True)

        except DuplicityError:
            raise
        except Exception as exc:
            log.error_kw("Event processing error", aid=event.aid, sn=event.sn, error=str(exc))
            m.EVENTS_REJECTED.labels(reason="internal_error").inc()
            self._stats.rejected += 1
            return ProcessingResult(accepted=False, error=str(exc))

    async def _validate_event(self, event: RawEvent) -> Tuple[bool, str]:
        if not event.aid or not event.said or not event.raw:
            return False, "missing_required_fields"

        if event.sn < 0:
            return False, "invalid_sequence_number"

        if event.ilk not in ("icp", "rot", "ixn", "dip", "drt"):
            return False, "unknown_ilk"

        if event.sn == 0:
            if event.ilk not in ("icp", "dip"):
                return False, "invalid_inception_ilk"
            return True, ""

        prior_in_db = await self._repo.get_first_seen_said(event.aid, event.sn - 1)
        if prior_in_db is None:
            lmdb_prior = self._lmdb.get_first_seen_said(event.aid, event.sn - 1)
            if lmdb_prior is None:
                return False, "missing_prior"

        if event.ilk == "rot" and not event.sigers:
            return False, "rotation_missing_signatures"

        return True, ""

    async def _handle_duplicity(self, event: RawEvent, first_said: str) -> None:
        log.warning_kw(
            "DUPLICITY DETECTED",
            aid=event.aid,
            sn=event.sn,
            first_said=first_said,
            conflict_said=event.said,
            source_witness=event.source_witness,
        )
        m.DUPLICITY_DETECTED.inc()

        first_raw_row = None
        kel = await self._repo.get_kel(event.aid, from_sn=event.sn, limit=1)
        if kel:
            first_raw_row = kel[0]["raw_event"]

        await self._repo.record_duplicity(
            aid=event.aid,
            sn=event.sn,
            first_said=first_said,
            conflict_said=event.said,
            first_raw=first_raw_row,
            conflict_raw=event.raw,
            source_witness=event.source_witness,
        )

    async def _escrow_event(self, event: RawEvent, reason: str) -> None:
        log.debug_kw("Escrowing event", aid=event.aid, sn=event.sn, reason=reason)
        self._lmdb.set_escrowed(event.aid, event.sn, event.said)
        await self._repo.escrow_event(
            aid=event.aid,
            raw_event=event.raw,
            reason=reason,
            sn=event.sn,
            said=event.said,
        )

    async def _process_escrow_for_aid(self, aid: str, just_seen_sn: int) -> None:
        pending = await self._repo.get_pending_escrow(aid=aid, limit=20)
        for row in pending:
            escrowed_sn = row["sn"]
            if escrowed_sn is None:
                continue
            if escrowed_sn <= just_seen_sn + 1:
                log.debug_kw("Re-processing escrowed event", aid=aid, sn=escrowed_sn)
                try:
                    raw = row["raw_event"]
                    escrowed_event = _parse_raw_event(raw, aid)
                    if escrowed_event:
                        result = await self._process_event(escrowed_event)
                        if result.accepted:
                            await self._repo.resolve_escrow(row["id"])
                            self._lmdb.clear_escrowed(aid, escrowed_sn, row["said"] or "")
                        else:
                            await self._repo.increment_escrow_retry(row["id"])
                except Exception as exc:
                    log.error_kw("Escrow re-process error", aid=aid, sn=escrowed_sn, error=str(exc))
                    await self._repo.increment_escrow_retry(row["id"])

    def get_stats(self) -> Dict[str, int]:
        return {
            "processed": self._stats.processed,
            "rejected": self._stats.rejected,
            "duplicity": self._stats.duplicity,
            "escrowed": self._stats.escrowed,
            "queue_size": self._queue.qsize(),
        }


class _ProcessorStats:
    def __init__(self) -> None:
        self.processed = 0
        self.rejected = 0
        self.duplicity = 0
        self.escrowed = 0


def _parse_raw_event(raw: bytes, aid: str) -> Optional[RawEvent]:
    try:
        import json
        data = json.loads(raw)
        return RawEvent(
            aid=data.get("i", aid),
            sn=int(data.get("s", 0), 16) if isinstance(data.get("s"), str) else data.get("s", 0),
            said=data.get("d", ""),
            ilk=data.get("t", ""),
            raw=raw,
            prior_said=data.get("p"),
        )
    except Exception:
        return None