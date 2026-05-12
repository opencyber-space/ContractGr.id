from __future__ import annotations

import platform
import time
from typing import Any, Dict

import falcon

from keri_watcher.api.helpers import handle_watcher_errors, ok
from keri_watcher.core.processor import EventProcessor
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db.lmdb import WatcherLMDB
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.polling.witness_poller import WitnessPoller
from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)

_START_TIME = time.time()


class HealthResource:
    def __init__(self, repo: TimescaleRepository, lmdb: WatcherLMDB) -> None:
        self._repo = repo
        self._lmdb = lmdb

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        db_health = await self._repo.health_check()
        lmdb_stat = self._lmdb.stat()
        overall = "ok" if db_health["status"] == "ok" else "degraded"

        if overall != "ok":
            resp.status = falcon.HTTP_503

        resp.media = {
            "status": overall,
            "uptime_seconds": round(time.time() - _START_TIME, 1),
            "components": {
                "timescaledb": db_health,
                "lmdb": {"status": "ok" if lmdb_stat else "disabled"},
            },
        }


class ReadyResource:
    def __init__(self, repo: TimescaleRepository) -> None:
        self._repo = repo

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        health = await self._repo.health_check()
        if health["status"] != "ok":
            resp.status = falcon.HTTP_503
            resp.media = {"ready": False, "reason": health.get("error")}
        else:
            resp.media = {"ready": True}


class StatusResource:
    def __init__(
        self,
        processor: EventProcessor,
        poller: WitnessPoller,
        manager: WatchManager,
    ) -> None:
        self._processor = processor
        self._poller = poller
        self._manager = manager

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.media = ok({
            "uptime_seconds": round(time.time() - _START_TIME, 1),
            "watched_aids": self._manager.count(),
            "processor": self._processor.get_stats(),
            "poller": self._poller.get_stats(),
            "system": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        })


class StatsResource:
    def __init__(self, repo: TimescaleRepository) -> None:
        self._repo = repo

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        hours_str = req.get_param("hours") or "24"
        try:
            hours = min(int(hours_str), 168)
        except ValueError:
            hours = 24

        throughput = await self._repo.get_throughput_stats(hours=hours)
        dup_stats = await self._repo.get_duplicity_stats(hours=hours)

        resp.media = ok({
            "period_hours": hours,
            "throughput": [
                {
                    "bucket": r["bucket"].isoformat(),
                    "ilk": r["ilk"],
                    "event_count": r["event_count"],
                }
                for r in throughput
            ],
            "duplicity": [
                {
                    "bucket": r["bucket"].isoformat(),
                    "total": r["total_duplicity"],
                    "affected_aids": r["affected_aids"],
                }
                for r in dup_stats
            ],
        })


class OOBIResource:
    def __init__(self, watcher_aid: str, http_port: int) -> None:
        self._aid = watcher_aid
        self._port = http_port

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        host = req.host or f"localhost:{self._port}"
        oobi_url = f"http://{host}/oobi/{self._aid}/witness"
        resp.media = ok({
            "aid": self._aid,
            "oobi": oobi_url,
            "role": "watcher",
        })