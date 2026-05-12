from __future__ import annotations

import json
from typing import Any, Dict, List

import falcon

from keri_watcher.api.helpers import (
    handle_watcher_errors,
    ok,
    paginate_params,
    require_json_body,
)
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.polling.witness_poller import WitnessPoller
from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


class WatchListResource:
    def __init__(self, manager: WatchManager) -> None:
        self._manager = manager

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        limit, offset = paginate_params(req)
        details = await self._manager.list_details(limit=limit, offset=offset)
        for d in details:
            _sanitize_record(d)
        resp.media = ok({
            "watched": details,
            "total": self._manager.count(),
            "limit": limit,
            "offset": offset,
        })

    @handle_watcher_errors
    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        body = require_json_body(req)
        aid = body.get("aid", "").strip()
        if not aid:
            raise falcon.HTTPBadRequest(description="aid is required")

        witnesses = body.get("witnesses", [])
        if not isinstance(witnesses, list):
            raise falcon.HTTPBadRequest(description="witnesses must be a list")

        witness_oobis = body.get("witness_oobis", {})
        if not isinstance(witness_oobis, dict):
            raise falcon.HTTPBadRequest(description="witness_oobis must be an object")

        metadata = body.get("metadata")
        force = body.get("force", False)

        await self._manager.watch(
            aid=aid,
            witnesses=witnesses,
            witness_oobis=witness_oobis,
            metadata=metadata,
            force=force,
        )

        resp.status = falcon.HTTP_201
        resp.media = ok({"aid": aid, "message": "AID registered for watching"})


class WatchDetailResource:
    def __init__(self, manager: WatchManager, poller: WitnessPoller) -> None:
        self._manager = manager
        self._poller = poller

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        detail = await self._manager.get_detail(aid)
        _sanitize_record(detail)
        resp.media = ok(detail)

    @handle_watcher_errors
    async def on_put(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        body = require_json_body(req)
        witnesses = body.get("witnesses")
        witness_oobis = body.get("witness_oobis", {})

        if witnesses is not None:
            await self._manager.update_witnesses(
                aid=aid,
                witnesses=witnesses,
                witness_oobis=witness_oobis,
            )

        resp.media = ok({"aid": aid, "message": "Updated"})

    @handle_watcher_errors
    async def on_delete(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        await self._manager.unwatch(aid)
        resp.media = ok({"aid": aid, "message": "AID removed from watch"})

    @handle_watcher_errors
    async def on_post(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        action = req.get_param("action", "")
        if action == "poll":
            last_sn = await self._poller.poll_aid_now(aid)
            resp.media = ok({"aid": aid, "last_sn": last_sn, "message": "Poll triggered"})
        else:
            raise falcon.HTTPBadRequest(description=f"Unknown action: {action}")


def _sanitize_record(d: Dict[str, Any]) -> None:
    for key in list(d.keys()):
        val = d[key]
        if hasattr(val, "isoformat"):
            d[key] = val.isoformat()
        elif isinstance(val, memoryview):
            d[key] = None