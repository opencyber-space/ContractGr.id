from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, Optional, Tuple, Type

from keri_watcher.utils.logging import get_logger

log = get_logger(__name__)


async def retry_async(
    fn: Callable,
    *args: Any,
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    jitter: bool = True,
    retryable: Tuple[Type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = min(backoff_base ** (attempt - 1), backoff_max)
            if jitter:
                delay *= (0.5 + random.random() * 0.5)
            log.warning_kw(
                "Retrying after error",
                attempt=attempt,
                max_attempts=max_attempts,
                delay=round(delay, 2),
                error=str(exc),
            )
            await asyncio.sleep(delay)
    raise last_exc


def retry_sync(
    fn: Callable,
    *args: Any,
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    retryable: Tuple[Type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    import time
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except retryable as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = backoff_base ** (attempt - 1)
            time.sleep(delay)
    raise last_exc