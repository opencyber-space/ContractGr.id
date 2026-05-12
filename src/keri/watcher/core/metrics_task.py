from __future__ import annotations

import asyncio
from typing import Optional

from keri_watcher.core.processor import EventProcessor
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.polling.witness_poller import WitnessPoller
from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


class MetricsSnapshotTask:
    def __init__(
        self,
        repo: TimescaleRepository,
        processor: EventProcessor,
        poller: WitnessPoller,
        manager: WatchManager,
        interval_seconds: int = 60,
    ) -> None:
        self._repo = repo
        self._processor = processor
        self._poller = poller
        self._manager = manager
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="metrics-snapshot")
        log.info_kw("Metrics snapshot task started", interval=self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                await self._snapshot()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error_kw("Metrics snapshot error", error=str(exc))

    async def _snapshot(self) -> None:
        proc_stats = self._processor.get_stats()
        poll_stats = self._poller.get_stats()

        await self._repo.write_metrics_snapshot(
            events_received=proc_stats.get("processed", 0) + proc_stats.get("rejected", 0),
            events_processed=proc_stats.get("processed", 0),
            events_rejected=proc_stats.get("rejected", 0),
            duplicity_count=proc_stats.get("duplicity", 0),
            escrow_count=proc_stats.get("escrowed", 0),
            watched_aid_count=self._manager.count(),
            poll_success_count=poll_stats.get("poll_success", 0),
            poll_error_count=poll_stats.get("poll_error", 0),
        )
        log.debug_kw("Metrics snapshot written")