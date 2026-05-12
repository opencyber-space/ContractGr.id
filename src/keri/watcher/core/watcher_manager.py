from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from keri_watcher.config import WatcherConfig
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.utils.errors import AlreadyWatchedError, NotWatchedError
from keri_watcher.utils.logging import get_logger
from keri_watcher.utils import metrics as m

log = get_logger(__name__)


class WatchManager:
    def __init__(self, config: WatcherConfig, repo: TimescaleRepository) -> None:
        self._config = config
        self._repo = repo
        self._watched_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
        self._cache_loaded = False

    async def load_cache(self) -> None:
        async with self._cache_lock:
            records = await self._repo.list_watched_aids(limit=10000)
            self._watched_cache = {r["aid"]: dict(r) for r in records}
            self._cache_loaded = True
            m.WATCHED_AIDS.set(len(self._watched_cache))
            log.info_kw("Watch cache loaded", count=len(self._watched_cache))

    def is_watched(self, aid: str) -> bool:
        return aid in self._watched_cache

    async def watch(
        self,
        aid: str,
        witnesses: List[str],
        witness_oobis: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> None:
        if not force and self.is_watched(aid):
            raise AlreadyWatchedError(aid)

        await self._repo.add_watched_aid(
            aid=aid,
            witnesses=witnesses,
            witness_oobis=witness_oobis,
            metadata=metadata,
        )

        async with self._cache_lock:
            self._watched_cache[aid] = {
                "aid": aid,
                "witnesses": witnesses,
                "witness_oobis": witness_oobis,
                "last_sn": -1,
                "metadata": metadata or {},
            }
            m.WATCHED_AIDS.set(len(self._watched_cache))

        log.info_kw("AID registered for watching", aid=aid, witnesses=witnesses)

    async def unwatch(self, aid: str) -> None:
        if not self.is_watched(aid):
            raise NotWatchedError(aid)

        await self._repo.remove_watched_aid(aid)

        async with self._cache_lock:
            self._watched_cache.pop(aid, None)
            m.WATCHED_AIDS.set(len(self._watched_cache))

        log.info_kw("AID removed from watch", aid=aid)

    async def update_witnesses(
        self,
        aid: str,
        witnesses: List[str],
        witness_oobis: Dict[str, str],
    ) -> None:
        if not self.is_watched(aid):
            raise NotWatchedError(aid)

        await self._repo.update_witnesses(aid, witnesses, witness_oobis)

        async with self._cache_lock:
            if aid in self._watched_cache:
                self._watched_cache[aid]["witnesses"] = witnesses
                self._watched_cache[aid]["witness_oobis"] = witness_oobis

        log.info_kw("Witnesses updated for AID", aid=aid, witnesses=witnesses)

    def get_witnesses(self, aid: str) -> List[str]:
        entry = self._watched_cache.get(aid)
        if not entry:
            raise NotWatchedError(aid)
        return entry.get("witnesses", [])

    def get_witness_oobis(self, aid: str) -> Dict[str, str]:
        entry = self._watched_cache.get(aid)
        if not entry:
            raise NotWatchedError(aid)
        oobis = entry.get("witness_oobis", {})
        if isinstance(oobis, str):
            import json
            return json.loads(oobis)
        return oobis

    def get_all_watched(self) -> List[str]:
        return list(self._watched_cache.keys())

    async def get_detail(self, aid: str) -> Dict[str, Any]:
        row = await self._repo.get_watched_aid(aid)
        if not row:
            raise NotWatchedError(aid)
        return dict(row)

    async def list_details(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        rows = await self._repo.list_watched_aids(limit=limit, offset=offset)
        return [dict(r) for r in rows]

    def count(self) -> int:
        return len(self._watched_cache)