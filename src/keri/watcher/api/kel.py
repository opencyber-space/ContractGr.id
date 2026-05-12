from __future__ import annotations

import base64
from typing import Any, Dict, List

import falcon

from keri_watcher.api.helpers import handle_watcher_errors, ok, paginate_params
from keri_watcher.core.processor import EventProcessor, RawEvent
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


class KELResource:
    def __init__(
        self,
        repo: TimescaleRepository,
        manager: WatchManager,
        processor: EventProcessor,
    ) -> None:
        self._repo = repo
        self._manager = manager
        self._processor = processor

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        if not self._manager.is_watched(aid):
            raise falcon.HTTPNotFound(description=f"AID {aid} is not being watched")

        from_sn_str = req.get_param("from")
        try:
            from_sn = int(from_sn_str) if from_sn_str else 0
        except ValueError:
            raise falcon.HTTPBadRequest(description="from must be an integer")

        limit, offset = paginate_params(req)
        include_raw = req.get_param_as_bool("include_raw", default=False)

        events = await self._repo.get_kel(aid=aid, from_sn=from_sn, limit=limit)
        latest = await self._repo.get_latest_event(aid)

        serialized = []
        for row in events:
            event: Dict[str, Any] = {
                "sn": row["sn"],
                "said": row["said"],
                "ilk": row["ilk"],
                "first_seen_at": row["first_seen_at"].isoformat(),
                "source_witness": row["source_witness"],
                "prior_said": row["prior_said"],
            }
            if include_raw and row["raw_event"]:
                event["raw"] = base64.b64encode(bytes(row["raw_event"])).decode()
            serialized.append(event)

        resp.media = ok({
            "aid": aid,
            "events": serialized,
            "from_sn": from_sn,
            "count": len(serialized),
            "latest_sn": latest["sn"] if latest else -1,
        })

    @handle_watcher_errors
    async def on_post(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        if not self._manager.is_watched(aid):
            raise falcon.HTTPNotFound(description=f"AID {aid} is not being watched")

        if not req.content_type or "application/json" not in req.content_type:
            raise falcon.HTTPUnsupportedMediaType()

        import json
        raw_body = req.bounded_stream.read()
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise falcon.HTTPBadRequest(description=f"Invalid JSON: {exc}")

        if isinstance(body, list):
            events_data = body
        elif isinstance(body, dict):
            events_data = [body]
        else:
            raise falcon.HTTPBadRequest(description="Body must be a JSON object or array")

        results = []
        for event_data in events_data:
            raw_event_bytes = json.dumps(event_data, separators=(",", ":")).encode()
            sn_raw = event_data.get("s", 0)
            if isinstance(sn_raw, str):
                sn = int(sn_raw, 16)
            else:
                sn = int(sn_raw)

            keri_event = RawEvent(
                aid=event_data.get("i", aid),
                sn=sn,
                said=event_data.get("d", ""),
                ilk=event_data.get("t", ""),
                raw=raw_event_bytes,
                prior_said=event_data.get("p"),
                source_witness=req.get_header("X-Source-Witness"),
            )

            result = await self._processor.process_immediate(keri_event)
            results.append({
                "sn": sn,
                "said": keri_event.said,
                "accepted": result.accepted,
                "duplicate": result.duplicate,
                "escrowed": result.escrowed,
                "error": result.error,
            })

        all_accepted = all(r["accepted"] for r in results)
        any_duplicate = any(r["duplicate"] for r in results)

        if len(results) == 1:
            r = results[0]
            if r["duplicate"]:
                resp.status = falcon.HTTP_409
            elif r["escrowed"]:
                resp.status = falcon.HTTP_202
            elif r["accepted"]:
                resp.status = falcon.HTTP_201
            else:
                resp.status = falcon.HTTP_422
        else:
            resp.status = falcon.HTTP_207

        resp.media = ok({
            "aid": aid,
            "results": results,
            "all_accepted": all_accepted,
            "any_duplicate": any_duplicate,
        })


class KELLatestResource:
    def __init__(self, repo: TimescaleRepository, manager: WatchManager) -> None:
        self._repo = repo
        self._manager = manager

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        if not self._manager.is_watched(aid):
            raise falcon.HTTPNotFound(description=f"AID {aid} is not being watched")

        latest = await self._repo.get_latest_event(aid)
        if not latest:
            resp.media = ok({"aid": aid, "latest": None})
            return

        resp.media = ok({
            "aid": aid,
            "latest": {
                "sn": latest["sn"],
                "said": latest["said"],
                "ilk": latest["ilk"],
                "first_seen_at": latest["first_seen_at"].isoformat(),
            },
        })