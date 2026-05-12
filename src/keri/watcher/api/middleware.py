from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Any, Deque, Dict

import falcon

from keri_watcher.config import WatcherConfig
from keri_watcher.utils.logging import get_logger, set_request_id
from keri_watcher.utils import metrics as m

log = get_logger(__name__)


class RequestLoggingMiddleware:
    def process_request(self, req: falcon.Request, resp: falcon.Response) -> None:
        req.context.start_time = time.monotonic()
        req.context.request_id = str(uuid.uuid4())
        set_request_id(req.context.request_id)
        resp.set_header("X-Request-ID", req.context.request_id)

    def process_response(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        resource: Any,
        req_succeeded: bool,
    ) -> None:
        duration = time.monotonic() - req.context.start_time
        status_code = int(resp.status.split()[0])

        m.HTTP_REQUESTS.labels(
            method=req.method,
            path=req.path,
            status=str(status_code),
        ).inc()
        m.HTTP_LATENCY.labels(method=req.method, path=req.path).observe(duration)

        log.info_kw(
            "HTTP request",
            method=req.method,
            path=req.path,
            status=status_code,
            duration_ms=round(duration * 1000, 1),
            request_id=req.context.request_id,
            remote=req.remote_addr,
        )


class CORSMiddleware:
    def __init__(self, allowed_origins: str = "*") -> None:
        self._origins = allowed_origins

    def process_response(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        resource: Any,
        req_succeeded: bool,
    ) -> None:
        resp.set_header("Access-Control-Allow-Origin", self._origins)
        resp.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        resp.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
        resp.set_header("Access-Control-Expose-Headers", "X-Request-ID")


class RateLimitMiddleware:
    def __init__(self, per_minute: int = 600) -> None:
        self._per_minute = per_minute
        self._window = 60
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def process_request(self, req: falcon.Request, resp: falcon.Response) -> None:
        client = req.remote_addr or "unknown"
        now = time.monotonic()
        bucket = self._buckets[client]

        while bucket and bucket[0] < now - self._window:
            bucket.popleft()

        if len(bucket) >= self._per_minute:
            resp.set_header("X-RateLimit-Limit", str(self._per_minute))
            resp.set_header("X-RateLimit-Remaining", "0")
            resp.set_header("Retry-After", "60")
            raise falcon.HTTPTooManyRequests(
                title="Rate limit exceeded",
                description=f"Maximum {self._per_minute} requests per minute",
            )

        bucket.append(now)
        resp.set_header("X-RateLimit-Limit", str(self._per_minute))
        resp.set_header("X-RateLimit-Remaining", str(self._per_minute - len(bucket)))


class ErrorHandlerMiddleware:
    def process_response(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        resource: Any,
        req_succeeded: bool,
    ) -> None:
        pass


def build_middleware(config: WatcherConfig) -> list:
    middleware = [
        RequestLoggingMiddleware(),
        CORSMiddleware(allowed_origins=config.allowed_origins),
        ErrorHandlerMiddleware(),
    ]
    if config.rate_limit.enabled:
        middleware.insert(1, RateLimitMiddleware(per_minute=config.rate_limit.per_minute))
    return middleware