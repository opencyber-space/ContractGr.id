from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from keri_watcher.config import WatcherConfig
from keri_watcher.core.processor import EventProcessor, RawEvent
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.utils.errors import PollError
from keri_watcher.utils.logging import get_logger
from keri_watcher.utils import metrics as m
from keri_watcher.utils.retry import retry_async

log = get_logger(__name__)

_POLL_STATS = {
    "poll_success": 0,
    "poll_error": 0,
}


class WitnessPoller:
    def __init__(
        self,
        config: WatcherConfig,
        repo: TimescaleRepository,
        processor: EventProcessor,
        watch_manager: WatchManager,
    ) -> None:
        self._config = config
        self._repo = repo
        self._processor = processor
        self._watch_manager = watch_manager
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(config.polling.concurrency)
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self._config.polling.timeout_seconds)
        connector = aiohttp.TCPConnector(
            limit=self._config.polling.concurrency * 2,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={
                "Accept": "application/json",
                "User-Agent": f"keri-watcher/{self._config.name}",
            },
        )
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(), name="witness-poller")
        log.info_kw(
            "Witness poller started",
            interval=self._config.polling.interval_seconds,
            concurrency=self._config.polling.concurrency,
        )

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        log.info_kw("Witness poller stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error_kw("Poll loop error", error=str(exc))
            await asyncio.sleep(self._config.polling.interval_seconds)

    async def _poll_cycle(self) -> None:
        due = await self._repo.get_aids_due_for_polling(
            poll_interval_seconds=self._config.polling.interval_seconds,
            limit=200,
        )
        if not due:
            return

        log.debug_kw("Poll cycle starting", aid_count=len(due))
        tasks = [
            asyncio.create_task(self._poll_aid(row), name=f"poll-{row['aid'][:8]}")
            for row in due
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_aid(self, row: Any) -> None:
        aid = row["aid"]
        last_sn = row["last_sn"]
        witnesses = row["witnesses"] or []
        witness_oobis = row["witness_oobis"] or {}
        if isinstance(witness_oobis, str):
            import json
            witness_oobis = json.loads(witness_oobis)

        if not witnesses:
            log.debug_kw("No witnesses for AID, skipping poll", aid=aid)
            return

        async with self._semaphore:
            results = await asyncio.gather(
                *[
                    self._fetch_from_witness(aid, witness, witness_oobis.get(witness, ""), last_sn)
                    for witness in witnesses
                ],
                return_exceptions=True,
            )

        max_sn = last_sn
        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, int) and result > max_sn:
                max_sn = result

        await self._repo.update_poll_timestamp(aid, max_sn)

    async def _fetch_from_witness(
        self,
        aid: str,
        witness_aid: str,
        oobi: str,
        from_sn: int,
    ) -> int:
        if not oobi:
            log.debug_kw("No OOBI for witness, skipping", aid=aid, witness=witness_aid)
            return from_sn

        start = time.monotonic()
        try:
            events = await retry_async(
                self._fetch_kel,
                oobi, aid, from_sn,
                max_attempts=self._config.polling.max_retries,
                backoff_base=self._config.polling.retry_backoff_base,
                retryable=(aiohttp.ClientError, asyncio.TimeoutError),
            )
            duration = time.monotonic() - start
            m.POLL_DURATION.labels(witness=witness_aid[:16]).observe(duration)
            await self._repo.record_witness_success(witness_aid)
            _POLL_STATS["poll_success"] += 1

            max_sn = from_sn
            for event in events:
                sn = event.get("sn", from_sn)
                if isinstance(sn, str):
                    sn = int(sn, 16)
                raw_event = _serialize_event(event)
                keri_event = RawEvent(
                    aid=event.get("i", aid),
                    sn=sn,
                    said=event.get("d", ""),
                    ilk=event.get("t", ""),
                    raw=raw_event,
                    prior_said=event.get("p"),
                    source_witness=witness_aid,
                )
                try:
                    await self._processor.submit(keri_event)
                    if sn > max_sn:
                        max_sn = sn
                except asyncio.QueueFull:
                    log.warning_kw("Queue full during poll, stopping batch", aid=aid, sn=sn)
                    break

            log.debug_kw(
                "Poll complete",
                aid=aid,
                witness=witness_aid[:16],
                events=len(events),
                duration_ms=round(duration * 1000, 1),
            )
            return max_sn

        except Exception as exc:
            duration = time.monotonic() - start
            m.POLL_ERRORS.labels(witness=witness_aid[:16], reason=type(exc).__name__).inc()
            await self._repo.record_witness_error(witness_aid)
            _POLL_STATS["poll_error"] += 1
            log.warning_kw(
                "Witness poll failed",
                aid=aid,
                witness=witness_aid[:16],
                error=str(exc),
                duration_ms=round(duration * 1000, 1),
            )
            return from_sn

    async def _fetch_kel(
        self,
        oobi: str,
        aid: str,
        from_sn: int,
    ) -> List[Dict[str, Any]]:
        base_url = _oobi_to_base_url(oobi)
        if not base_url:
            raise PollError("unknown", f"Cannot parse OOBI: {oobi}")

        url = f"{base_url}/kel/{aid}"
        params = {"from": from_sn} if from_sn >= 0 else {}

        async with self._session.get(url, params=params) as resp:
            if resp.status == 404:
                return []
            if resp.status != 200:
                raise PollError(base_url, f"HTTP {resp.status}")
            data = await resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("events", [])
            return []

    async def poll_aid_now(self, aid: str) -> int:
        row = await self._repo.get_watched_aid(aid)
        if not row:
            from keri_watcher.utils.errors import NotWatchedError
            raise NotWatchedError(aid)
        await self._poll_aid(row)
        updated = await self._repo.get_watched_aid(aid)
        return updated["last_sn"] if updated else -1

    def get_stats(self) -> Dict[str, int]:
        return dict(_POLL_STATS)


def _oobi_to_base_url(oobi: str) -> Optional[str]:
    if oobi.startswith("http"):
        parts = oobi.split("/oobi/")
        if parts:
            return parts[0]
        return oobi.rstrip("/")
    return None


def _serialize_event(event: Dict[str, Any]) -> bytes:
    import json
    return json.dumps(event, separators=(",", ":")).encode()