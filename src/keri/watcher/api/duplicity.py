from __future__ import annotations

from typing import Any, Dict

import falcon

from keri_watcher.api.helpers import handle_watcher_errors, ok, paginate_params, require_json_body
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


class DuplicityListResource:
    def __init__(self, repo: TimescaleRepository) -> None:
        self._repo = repo

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        limit, offset = paginate_params(req)
        resolved_param = req.get_param("resolved")
        resolved = None
        if resolved_param is not None:
            resolved = resolved_param.lower() in ("true", "1", "yes")

        records = await self._repo.list_duplicity(
            resolved=resolved,
            limit=limit,
            offset=offset,
        )
        resp.media = ok({
            "duplicity": [_serialize_dup(r) for r in records],
            "limit": limit,
            "offset": offset,
        })


class DuplicityByAIDResource:
    def __init__(self, repo: TimescaleRepository) -> None:
        self._repo = repo

    @handle_watcher_errors
    async def on_get(self, req: falcon.Request, resp: falcon.Response, aid: str) -> None:
        limit, offset = paginate_params(req)
        resolved_param = req.get_param("resolved")
        resolved = None
        if resolved_param is not None:
            resolved = resolved_param.lower() in ("true", "1", "yes")

        records = await self._repo.list_duplicity(
            aid=aid,
            resolved=resolved,
            limit=limit,
            offset=offset,
        )
        resp.media = ok({
            "aid": aid,
            "duplicity": [_serialize_dup(r) for r in records],
            "count": len(records),
        })


class DuplicityDetailResource:
    def __init__(self, repo: TimescaleRepository) -> None:
        self._repo = repo

    @handle_watcher_errors
    async def on_put(self, req: falcon.Request, resp: falcon.Response, duplicity_id: str) -> None:
        body = require_json_body(req)
        action = body.get("action", "")
        notes = body.get("notes")

        if action == "resolve":
            resolved = await self._repo.resolve_duplicity(duplicity_id, notes=notes)
            if not resolved:
                raise falcon.HTTPNotFound(description=f"Duplicity event {duplicity_id} not found or already resolved")
            resp.media = ok({"id": duplicity_id, "message": "Resolved"})
        else:
            raise falcon.HTTPBadRequest(description=f"Unknown action: {action}. Use 'resolve'.")


def _serialize_dup(row: Any) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "detected_at": row["detected_at"].isoformat(),
        "aid": row["aid"],
        "sn": row["sn"],
        "first_said": row["first_said"],
        "conflict_said": row["conflict_said"],
        "source_witness": row["source_witness"],
        "resolved": row["resolved"],
        "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
    }