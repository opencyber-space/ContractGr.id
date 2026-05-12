from __future__ import annotations

import json
from typing import Any

import falcon
import falcon.asgi

from keri_watcher.api.duplicity import (
    DuplicityByAIDResource,
    DuplicityDetailResource,
    DuplicityListResource,
)
from keri_watcher.api.kel import KELLatestResource, KELResource
from keri_watcher.api.middleware import build_middleware
from keri_watcher.api.status import HealthResource, OOBIResource, ReadyResource, StatusResource, StatsResource
from keri_watcher.api.watch import WatchDetailResource, WatchListResource
from keri_watcher.config import WatcherConfig
from keri_watcher.core.processor import EventProcessor
from keri_watcher.core.watch_manager import WatchManager
from keri_watcher.db.lmdb import WatcherLMDB
from keri_watcher.db.timescale import TimescaleRepository
from keri_watcher.polling.witness_poller import WitnessPoller
from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


class _JSONHandler(falcon.media.BaseHandler):
    def serialize(self, media: Any, content_type: str) -> bytes:
        return json.dumps(media, default=str).encode()

    def deserialize(self, stream, content_type: str, content_length: int) -> Any:
        return json.loads(stream.read())

    async def deserialize_async(self, stream, content_type: str, content_length: int) -> Any:
        return json.loads(await stream.read())


def create_app(
    config: WatcherConfig,
    repo: TimescaleRepository,
    lmdb: WatcherLMDB,
    processor: EventProcessor,
    poller: WitnessPoller,
    manager: WatchManager,
    watcher_aid: str = "",
) -> falcon.asgi.App:
    middleware = build_middleware(config)

    app = falcon.asgi.App(
        middleware=middleware,
        cors_enable=False,
    )

    json_handler = _JSONHandler()
    app.req_options.media_handlers.update({"application/json": json_handler})
    app.resp_options.media_handlers.update({"application/json": json_handler})

    def handle_not_found(req, resp, ex, params):
        resp.status = falcon.HTTP_404
        resp.media = {"status": "error", "error": {"code": "not_found", "message": str(ex)}}

    def handle_bad_request(req, resp, ex, params):
        resp.status = falcon.HTTP_400
        resp.media = {"status": "error", "error": {"code": "bad_request", "message": str(ex)}}

    def handle_generic(req, resp, ex, params):
        log.error_kw("Unhandled exception", error=str(ex), path=req.path)
        resp.status = falcon.HTTP_500
        resp.media = {"status": "error", "error": {"code": "internal_error", "message": "An internal error occurred"}}

    app.add_error_handler(falcon.HTTPNotFound, handle_not_found)
    app.add_error_handler(falcon.HTTPBadRequest, handle_bad_request)
    app.add_error_handler(Exception, handle_generic)

    app.add_route("/health", HealthResource(repo=repo, lmdb=lmdb))
    app.add_route("/ready", ReadyResource(repo=repo))
    app.add_route("/status", StatusResource(processor=processor, poller=poller, manager=manager))
    app.add_route("/stats", StatsResource(repo=repo))
    app.add_route("/oobi", OOBIResource(watcher_aid=watcher_aid, http_port=config.http_port))

    app.add_route("/watch", WatchListResource(manager=manager))
    app.add_route("/watch/{aid}", WatchDetailResource(manager=manager, poller=poller))

    app.add_route("/kel/{aid}", KELResource(repo=repo, manager=manager, processor=processor))
    app.add_route("/kel/{aid}/latest", KELLatestResource(repo=repo, manager=manager))

    app.add_route("/duplicity", DuplicityListResource(repo=repo))
    app.add_route("/duplicity/{aid}", DuplicityByAIDResource(repo=repo))
    app.add_route("/duplicity/event/{duplicity_id}", DuplicityDetailResource(repo=repo))

    log.info_kw("Falcon ASGI app created", routes=9)
    return app