"""Shared CacheService: TTL, namespaces, single-flight, fail-open, corruption rejection."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import ExitStack
from collections import defaultdict
from typing import Any, Callable

from backend.cache import (CacheBackend, CacheCorruptError, CacheEntry, CacheLockTimeout, create_backend)
from backend.config import Settings, get_settings
from backend.services.cache_key_service import build_key

log = logging.getLogger("midnight.app.cache")

LLM_NAMESPACES = {"planner", "writer", "humanisation", "continuity", "editorial", "safety", "distribution",
                  "embeddings", "analytics_llm"}
IMAGE_NAMESPACES = {"images"}
API_NAMESPACES = {"api", "analytics"}
# Must never be stored as reusable success (spec section 9).
NEVER_CACHE = {"approvals", "approval", "publishing", "auth", "credentials"}
_MISS = object()


class CacheService:
    def __init__(self, settings: Settings | None = None, backend: CacheBackend | None = None,
                 clock: Callable[[], float] = time.time):
        self.settings = settings or get_settings()
        self.clock = clock
        self.enabled = self.settings.cache_enabled
        self.backend = backend
        if self.backend is None and self.enabled:
            try:
                self.backend = create_backend(self.settings)
            except Exception as exc:
                if not self.settings.cache_fail_open:
                    raise
                log.error("cache backend unavailable, cache disabled: %s", exc)
                self.enabled = False
        self._stat_lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0, "errors": 0, "writes": 0})
        self._key_locks: dict[str, threading.Lock] = {}
        self._key_locks_guard = threading.Lock()

    # -- helpers -------------------------------------------------------
    build_key = staticmethod(build_key)

    def ttl_for(self, namespace: str) -> int:
        s = self.settings
        if namespace in LLM_NAMESPACES:
            return s.cache_llm_ttl_seconds
        if namespace in IMAGE_NAMESPACES:
            return s.cache_image_ttl_seconds
        if namespace in API_NAMESPACES:
            return s.cache_api_ttl_seconds
        return s.cache_default_ttl_seconds

    def _bump(self, ns: str, what: str) -> None:
        with self._stat_lock:
            self._counts[ns][what] += 1

    def _error(self, ns: str, op: str, exc: BaseException) -> None:
        self._bump(ns, "errors")
        log.error("cache %s failed (ns=%s): %s", op, ns, exc)
        if not self.settings.cache_fail_open:
            raise exc

    def _key_lock(self, ns: str, key: str) -> threading.Lock:
        with self._key_locks_guard:
            return self._key_locks.setdefault(f"{ns}/{key}", threading.Lock())

    # -- primitive ops -------------------------------------------------
    def _lookup(self, namespace: str, key: str, validate: Callable[[Any], bool] | None = None, count: bool = True):
        if not self.enabled or self.backend is None or namespace in NEVER_CACHE:
            return _MISS
        try:
            entry = self.backend.get(namespace, key)
            if entry is not None and entry.is_expired(self.clock()):
                self.backend.delete(namespace, key)
                entry = None
            if entry is not None and validate is not None and not validate(entry.value):
                self.backend.delete(namespace, key)  # reject stored value that fails validation
                self._bump(namespace, "errors")
                entry = None
        except CacheCorruptError as exc:  # backend already removed the file
            # Corrupt entries are always rejected and recomputed, even when fail-open is off.
            self._bump(namespace, "errors")
            log.warning("corrupt cache entry rejected: %s", exc)
            entry = None
        except Exception as exc:
            self._error(namespace, "read", exc)
            entry = None
        if entry is None:
            if count:
                self._bump(namespace, "misses")
            return _MISS
        if count:
            self._bump(namespace, "hits")
        return entry.value

    def get(self, namespace: str, key: str) -> Any | None:
        v = self._lookup(namespace, key)
        return None if v is _MISS else v

    def set(self, namespace: str, key: str, value: Any, ttl: int | None = None, *,
            story_id: str | None = None, version: int | None = None, meta: dict | None = None) -> bool:
        if not self.enabled or self.backend is None:
            return False
        if namespace in NEVER_CACHE:
            log.warning("refusing to cache in protected namespace %s", namespace)
            return False
        if value is None:
            return False
        now = self.clock()
        t = self.ttl_for(namespace) if ttl is None else ttl
        if t <= 0:
            return False  # zero/negative TTL means "do not cache"
        entry = CacheEntry(namespace, key, value, now, now + t, story_id, version, meta or {})
        try:
            self.backend.put(entry)
            self._bump(namespace, "writes")
            return True
        except Exception as exc:  # includes non-JSON-serialisable values
            self._error(namespace, "write", exc)
            return False

    def delete(self, namespace: str, key: str) -> bool:
        if not self.enabled or self.backend is None:
            return False
        try:
            return self.backend.delete(namespace, key)
        except Exception as exc:
            self._error(namespace, "delete", exc)
            return False

    def get_or_compute(self, namespace: str, key: str, fn: Callable[[], Any],
                       validate: Callable[[Any], bool] | None = None, ttl: int | None = None, *,
                       story_id: str | None = None, version: int | None = None) -> Any:
        """Single-flight: check, lock, recheck, compute once, validate, store, unlock.

        Exceptions from ``fn`` propagate and nothing is cached. Results failing ``validate`` are returned
        to the caller but never stored. Cache faults never fail the computation (when fail-open).
        """
        v = self._lookup(namespace, key, validate)
        if v is not _MISS:
            return v
        if not self.enabled or self.backend is None or namespace in NEVER_CACHE:
            return fn()
        s = self.settings
        tlock = self._key_lock(namespace, key)
        got_thread = tlock.acquire(timeout=s.cache_lock_timeout_seconds)
        try:
            if not got_thread:
                self._error(namespace, "lock(thread-timeout)", CacheLockTimeout(f"{namespace}/{key}"))
                return self._compute_and_store(namespace, key, fn, validate, ttl, story_id, version)
            stack = ExitStack()
            try:
                stack.enter_context(self.backend.lock(namespace, key, s.cache_lock_timeout_seconds,
                                                      s.cache_lock_stale_seconds))
            except Exception as exc:  # timeout or lock-infrastructure failure: fail open, compute unlocked
                self._error(namespace, "lock", exc)
            with stack:
                v = self._lookup(namespace, key, validate, count=False)
                if v is not _MISS:
                    self._bump(namespace, "hits")
                    return v
                return self._compute_and_store(namespace, key, fn, validate, ttl, story_id, version)
        finally:
            if got_thread:
                tlock.release()

    def _compute_and_store(self, ns, key, fn, validate, ttl, story_id, version):
        value = fn()
        if value is not None and (validate is None or self._safe_validate(ns, validate, value)):
            self.set(ns, key, value, ttl, story_id=story_id, version=version)
        return value

    def _safe_validate(self, ns, validate, value) -> bool:
        try:
            return bool(validate(value))
        except Exception as exc:
            self._bump(ns, "errors")
            log.warning("cache validate raised (not caching): %s", exc)
            return False

    # -- invalidation / stats -----------------------------------------
    def invalidate_story(self, story_id: str, from_version: int | None = None) -> int:
        """Remove entries tagged with story_id. With from_version, only entries for versions >= from_version
        and story-level entries (version None) are removed; older immutable versions stay valid."""
        if not self.enabled or self.backend is None:
            return 0
        n = 0
        try:
            for ns, key, entry in list(self.backend.iter_entries()):
                if entry is None or entry.story_id != story_id:
                    continue
                if from_version is not None and entry.version is not None and entry.version < from_version:
                    continue
                if self.backend.delete(ns, key):
                    n += 1
        except Exception as exc:
            self._error("*", "invalidate_story", exc)
        return n

    def invalidate_namespace(self, namespace: str) -> int:
        if not self.enabled or self.backend is None:
            return 0
        n = 0
        try:
            for ns, key, _e in list(self.backend.iter_entries()):
                if ns == namespace and self.backend.delete(ns, key):
                    n += 1
        except Exception as exc:
            self._error(namespace, "invalidate_namespace", exc)
        return n

    def stats(self) -> dict:
        with self._stat_lock:
            by_ns = {k: dict(v) for k, v in self._counts.items()}
        total = {"hits": 0, "misses": 0, "errors": 0}
        for v in by_ns.values():
            for k in total:
                total[k] += v[k]
        size_mb = 0.0
        if self.backend is not None and self.enabled:
            try:
                size_mb = round(self.backend.size_bytes() / (1024 * 1024), 4)
            except Exception:
                total["errors"] += 1
        return {**total, "size_mb": size_mb, "by_namespace": by_ns, "enabled": self.enabled}
