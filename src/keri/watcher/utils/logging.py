from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar
from typing import Any, Optional
import json

_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_aid_var: ContextVar[Optional[str]] = ContextVar("aid", default=None)


def set_request_id(rid: str) -> None:
    _request_id_var.set(rid)


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def set_aid_context(aid: str) -> None:
    _aid_var.set(aid)


def get_aid_context() -> Optional[str]:
    return _aid_var.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        rid = _request_id_var.get()
        if rid:
            log["request_id"] = rid

        aid = _aid_var.get()
        if aid:
            log["aid"] = aid

        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)

        for key, val in record.__dict__.items():
            if key.startswith("kw_"):
                log[key[3:]] = val

        return json.dumps(log)


class StructuredLogger(logging.Logger):
    def _log_kw(self, level: int, msg: str, **kwargs: Any) -> None:
        extra = {f"kw_{k}": v for k, v in kwargs.items()}
        self.log(level, msg, extra=extra)

    def info_kw(self, msg: str, **kwargs: Any) -> None:
        self._log_kw(logging.INFO, msg, **kwargs)

    def warning_kw(self, msg: str, **kwargs: Any) -> None:
        self._log_kw(logging.WARNING, msg, **kwargs)

    def error_kw(self, msg: str, **kwargs: Any) -> None:
        self._log_kw(logging.ERROR, msg, **kwargs)

    def debug_kw(self, msg: str, **kwargs: Any) -> None:
        self._log_kw(logging.DEBUG, msg, **kwargs)


logging.setLoggerClass(StructuredLogger)


def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ))

    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> StructuredLogger:
    return logging.getLogger(name)  # type: ignore[return-value]