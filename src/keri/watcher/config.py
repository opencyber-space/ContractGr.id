from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, str(default)).lower()
    return val in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LMDBConfig:
    path: str = field(default_factory=lambda: _env("LMDB_PATH", "/var/lib/keri-watcher/lmdb"))
    map_size_gb: int = field(default_factory=lambda: _env_int("LMDB_MAP_SIZE_GB", 10))

    @property
    def map_size(self) -> int:
        return self.map_size_gb * 1024 ** 3


@dataclass(frozen=True)
class TimescaleConfig:
    dsn: str = field(default_factory=lambda: _env("TIMESCALE_DSN", "postgresql://keri:keri@localhost:5432/keri_watcher"))
    min_pool: int = field(default_factory=lambda: _env_int("TIMESCALE_MIN_POOL", 5))
    max_pool: int = field(default_factory=lambda: _env_int("TIMESCALE_MAX_POOL", 20))
    command_timeout: int = field(default_factory=lambda: _env_int("TIMESCALE_COMMAND_TIMEOUT", 30))


@dataclass(frozen=True)
class PollingConfig:
    interval_seconds: int = field(default_factory=lambda: _env_int("POLL_INTERVAL_SECONDS", 30))
    concurrency: int = field(default_factory=lambda: _env_int("POLL_CONCURRENCY", 10))
    timeout_seconds: int = field(default_factory=lambda: _env_int("POLL_TIMEOUT_SECONDS", 10))
    max_retries: int = field(default_factory=lambda: _env_int("POLL_MAX_RETRIES", 3))
    retry_backoff_base: float = field(default_factory=lambda: _env_float("POLL_RETRY_BACKOFF_BASE", 2.0))


@dataclass(frozen=True)
class MetricsConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("METRICS_ENABLED", True))
    port: int = field(default_factory=lambda: _env_int("METRICS_PORT", 9090))


@dataclass(frozen=True)
class OtelConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("OTEL_ENABLED", False))
    endpoint: str = field(default_factory=lambda: _env("OTEL_ENDPOINT", "http://localhost:4317"))


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("RATE_LIMIT_ENABLED", True))
    per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 600))


@dataclass(frozen=True)
class WatcherConfig:
    name: str = field(default_factory=lambda: _env("WATCHER_NAME", "watcher0"))
    http_port: int = field(default_factory=lambda: _env_int("WATCHER_HTTP_PORT", 5632))
    admin_port: int = field(default_factory=lambda: _env_int("WATCHER_ADMIN_PORT", 5633))
    log_level: str = field(default_factory=lambda: _env("WATCHER_LOG_LEVEL", "INFO"))
    log_format: str = field(default_factory=lambda: _env("WATCHER_LOG_FORMAT", "json"))
    salt: Optional[str] = field(default_factory=lambda: _env("WATCHER_SALT") or None)
    passcode: Optional[str] = field(default_factory=lambda: _env("WATCHER_PASSCODE") or None)
    max_event_queue_size: int = field(default_factory=lambda: _env_int("MAX_EVENT_QUEUE_SIZE", 10000))
    event_batch_size: int = field(default_factory=lambda: _env_int("EVENT_BATCH_SIZE", 100))
    allowed_origins: str = field(default_factory=lambda: _env("ALLOWED_ORIGINS", "*"))

    lmdb: LMDBConfig = field(default_factory=LMDBConfig)
    timescale: TimescaleConfig = field(default_factory=TimescaleConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    otel: OtelConfig = field(default_factory=OtelConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)


_config: Optional[WatcherConfig] = None


def get_config() -> WatcherConfig:
    global _config
    if _config is None:
        _config = WatcherConfig()
    return _config


def override_config(config: WatcherConfig) -> None:
    global _config
    _config = config