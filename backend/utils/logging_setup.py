"""Structured JSON-lines rotating file logging with secret redaction (spec section 18).

Channels (logger names -> files): midnight.app -> app.log, midnight.agent -> agent.log,
midnight.publishing -> publishing.log, midnight.scheduler -> scheduler.log; every ERROR+ record from
any ``midnight.*`` logger also goes to error.log. The root logger gets the app handler so
third-party libraries are captured. Nothing is written to SQLite.
Do not log full story content; log ids and hashes.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from backend.config import Settings

CHANNELS = {"app": "midnight.app", "agent": "midnight.agent", "publishing": "midnight.publishing",
            "scheduler": "midnight.scheduler"}
CONTEXT_FIELDS = ("workflow_id", "story_id", "story_version", "agent", "operation")
_SENSITIVE_KEY = re.compile(r"(api[_-]?key|secret|token|password|passwd|authorization|cookie|credential)", re.I)
_PATTERNS = [
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|secret|token|password|passwd|authorization)[\"']?\s*[=:]\s*[\"']?)[^\s\"',;&}]+"),
]
REDACTED = "[REDACTED]"
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


def redact_text(s: str) -> str:
    s = _PATTERNS[0].sub(lambda m: f"{m.group(1)} {REDACTED}", s)
    s = _PATTERNS[1].sub(REDACTED, s)
    s = _PATTERNS[2].sub(REDACTED, s)
    return _PATTERNS[3].sub(lambda m: m.group(1) + REDACTED, s)


def redact_value(key: str, v):
    if _SENSITIVE_KEY.search(key or ""):
        return REDACTED
    if isinstance(v, str):
        return redact_text(v)
    if isinstance(v, dict):
        return {k: redact_value(str(k), x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [redact_value(key, x) for x in v]
    return v


class RedactionFilter(logging.Filter):
    """Redacts secrets from message, args, exception text and extra fields (in place)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg, record.args = redact_text(msg), ()
        if record.exc_info:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        for k in list(record.__dict__):
            if k not in _STANDARD:
                record.__dict__[k] = redact_value(k, record.__dict__[k])
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        doc = {"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
               "severity": record.levelname, "logger": record.name, "message": record.getMessage()}
        for f in CONTEXT_FIELDS:
            doc[f] = getattr(record, f, None)
        for k, v in record.__dict__.items():
            if k not in _STANDARD and k not in doc and not k.startswith("_"):
                doc[k] = v
        if record.exc_text:
            doc["exception"] = record.exc_text
        elif record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str, ensure_ascii=False)


_MARK = "_midnight_handler"


def _handler(path, settings: Settings, level=logging.DEBUG) -> RotatingFileHandler:
    h = RotatingFileHandler(path, maxBytes=settings.log_max_bytes, backupCount=settings.log_backup_count,
                            encoding="utf-8", delay=True)
    h.setLevel(level)
    h.setFormatter(JsonFormatter())
    h.addFilter(RedactionFilter())
    setattr(h, _MARK, True)
    return h


def _clear(logger: logging.Logger) -> None:
    for h in list(logger.handlers):
        if getattr(h, _MARK, False):
            logger.removeHandler(h)
            h.close()


def setup_logging(settings: Settings) -> dict[str, RotatingFileHandler]:
    """Idempotent. Returns {channel: handler} including 'error'."""
    d = settings.log_path
    d.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if settings.app_debug else logging.INFO
    handlers: dict[str, RotatingFileHandler] = {}
    for name, logger_name in CHANNELS.items():
        lg = logging.getLogger(logger_name)
        _clear(lg)
        h = _handler(d / f"{name}.log", settings)
        lg.addHandler(h)
        lg.setLevel(level)
        lg.propagate = True  # to "midnight" for error.log
        handlers[name] = h
    base = logging.getLogger("midnight")
    _clear(base)
    err = _handler(d / "error.log", settings, logging.ERROR)
    base.addHandler(err)
    base.setLevel(level)
    base.propagate = False  # keep midnight.* out of the root/app handler (no duplicate lines)
    handlers["error"] = err
    root = logging.getLogger()
    _clear(root)
    root.addHandler(handlers["app"])  # same handler object: one writer per file (Windows rotation safety)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return handlers


def teardown_logging() -> None:
    for name in ("midnight", *CHANNELS.values(), ""):
        _clear(logging.getLogger(name))
