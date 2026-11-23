"""LangSmith tracing wrapper. Every operation fails open: tracing problems never affect content generation."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("midnight.agent.trace")

_SAFE_TYPES = (str, int, float, bool, type(None))
_FORBIDDEN = {"text", "story_text", "body", "api_key", "secret", "password", "token"}


def safe_metadata(meta: dict) -> dict:
    """Drop secrets / story bodies; truncate long values."""
    out = {}
    for k, v in meta.items():
        if k.lower() in _FORBIDDEN:
            continue
        out[k] = (v[:200] if isinstance(v, str) else v) if isinstance(v, _SAFE_TYPES) else str(v)[:200]
    return out


class Span:
    def __init__(self, run: Any = None):
        self._run = run
        self.meta: dict = {}

    def set(self, **meta: Any) -> None:
        self.meta.update(safe_metadata(meta))
        try:
            if self._run is not None:
                self._run.add_metadata(safe_metadata(meta))
        except Exception as exc:  # fail open
            log.debug("trace metadata failed: %s", exc)


@contextmanager
def trace_span(name: str, metadata: dict | None = None, enabled: bool | None = None,
               run_type: str = "chain") -> Iterator[Span]:
    cm = None
    run = None
    if enabled is None:
        try:
            from backend.config import get_settings
            s = get_settings()
            enabled = bool(s.langsmith_tracing and s.langsmith_api_key.get_secret_value())
        except Exception:
            enabled = False
    if enabled:
        try:
            from langsmith import trace
            cm = trace(name=name, run_type=run_type, metadata=safe_metadata(metadata or {}))
            run = cm.__enter__()
        except Exception as exc:
            log.warning("LangSmith unavailable, continuing untraced: %s", exc)
            cm = run = None
    span = Span(run)
    span.meta.update(safe_metadata(metadata or {}))
    try:
        yield span
    finally:
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception as exc:
                log.debug("trace close failed: %s", exc)
