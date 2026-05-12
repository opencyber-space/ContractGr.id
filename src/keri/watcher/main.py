from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Optional

import uvicorn

from keri_watcher.api.app import create_app
from keri_watcher.config import get_config
from keri_watcher.core.metrics_task import MetricsSnapshotTask
from keri_watcher.core.processor import EventProcessor
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db import TimescaleRepository, WatcherLMDB, run_migrations
from keri_watcher.polling.witness_poller import WitnessPoller
from keri_watcher.utils.logging import get_logger, setup_logging
from keri_watcher.utils import metrics as m

log = get_logger(__name__)


class WatcherApplication:
    def __init__(self) -> None:
        self._config = get_config()
        self._repo: Optional[TimescaleRepository] = None
        self._lmdb: Optional[WatcherLMDB] = None
        self._processor: Optional[EventProcessor] = None
        self._manager: Optional[WatchManager] = None
        self._poller: Optional[WitnessPoller] = None
        self._metrics_task: Optional[MetricsSnapshotTask] = None
        self._server: Optional[asyncio.Task] = None

    async def startup(self) -> None:
        log.info_kw("Starting KERI Watcher", name=self._config.name)

        self._repo = TimescaleRepository(self._config.timescale)
        await self._repo.connect()

        log.info_kw("Running database migrations")
        await run_migrations(self._repo)

        os.makedirs(self._config.lmdb.path, exist_ok=True)
        self._lmdb = WatcherLMDB(
            path=self._config.lmdb.path,
            map_size=self._config.lmdb.map_size,
        )
        self._lmdb.open()

        self._processor = EventProcessor(
            config=self._config,
            repo=self._repo,
            lmdb=self._lmdb,
        )
        await self._processor.start(num_workers=4)

        self._manager = WatchManager(config=self._config, repo=self._repo)
        await self._manager.load_cache()

        self._poller = WitnessPoller(
            config=self._config,
            repo=self._repo,
            processor=self._processor,
            watch_manager=self._manager,
        )
        await self._poller.start()

        self._metrics_task = MetricsSnapshotTask(
            repo=self._repo,
            processor=self._processor,
            poller=self._poller,
            manager=self._manager,
        )
        await self._metrics_task.start()

        if self._config.metrics.enabled:
            m.start_metrics_server(self._config.metrics.port)
            log.info_kw("Prometheus metrics server started", port=self._config.metrics.port)

        log.info_kw(
            "KERI Watcher started",
            http_port=self._config.http_port,
            watched_aids=self._manager.count(),
        )

    async def shutdown(self) -> None:
        log.info_kw("Shutting down KERI Watcher")

        if self._metrics_task:
            await self._metrics_task.stop()

        if self._poller:
            await self._poller.stop()

        if self._processor:
            await self._processor.stop()

        if self._lmdb:
            self._lmdb.close()

        if self._repo:
            await self._repo.close()

        log.info_kw("KERI Watcher shutdown complete")

    def build_asgi_app(self):
        assert self._repo and self._lmdb and self._processor and self._manager and self._poller
        return create_app(
            config=self._config,
            repo=self._repo,
            lmdb=self._lmdb,
            processor=self._processor,
            poller=self._poller,
            manager=self._manager,
            watcher_aid=self._config.name,
        )


_app_instance: Optional[WatcherApplication] = None


def get_app_instance() -> WatcherApplication:
    global _app_instance
    if _app_instance is None:
        _app_instance = WatcherApplication()
    return _app_instance


async def _serve() -> None:
    config = get_config()
    setup_logging(level=config.log_level, fmt=config.log_format)

    watcher = get_app_instance()
    await watcher.startup()

    asgi_app = watcher.build_asgi_app()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal():
        log.info_kw("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_signal)

    server_config = uvicorn.Config(
        app=asgi_app,
        host="0.0.0.0",
        port=config.http_port,
        loop="none",
        log_config=None,
        access_log=False,
        lifespan="off",
    )
    server = uvicorn.Server(config=server_config)

    serve_task = asyncio.create_task(server.serve(), name="uvicorn")

    await stop_event.wait()

    server.should_exit = True
    await serve_task
    await watcher.shutdown()


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    config = get_config()
    setup_logging(level=config.log_level, fmt=config.log_format)

    asyncio.run(_serve())


if __name__ == "__main__":
    main()