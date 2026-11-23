"""Cache cleanup: expired/corrupt entries, stale locks, orphan temp files, size cap.

Only touches files inside the cache directory that the backend owns. Cache entries merely
reference generated assets by path; cleanup never deletes those assets (referenced or published).
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from backend.cache import CacheBackend
from backend.config import Settings, get_settings

log = logging.getLogger("midnight.app.cache")


class CacheCleanupService:
    def __init__(self, backend: CacheBackend, settings: Settings | None = None,
                 clock: Callable[[], float] = time.time):
        self.backend = backend
        self.settings = settings or get_settings()
        self.clock = clock

    @property
    def interval_seconds(self) -> int:
        return self.settings.cache_cleanup_interval_hours * 3600

    def run(self) -> dict:
        result = {"expired": 0, "corrupt": 0, "evicted": 0, "stale_locks": 0, "temp_files": 0, "errors": 0}
        now = self.clock()
        live: list[tuple[float, str, str]] = []
        try:
            for ns, key, entry in list(self.backend.iter_entries()):
                try:
                    if entry is None:
                        self.backend.delete(ns, key)
                        result["corrupt"] += 1
                    elif entry.is_expired(now):
                        self.backend.delete(ns, key)
                        result["expired"] += 1
                    else:
                        live.append((self.backend.entry_sort_key(ns, key), ns, key))
                except Exception as exc:
                    result["errors"] += 1
                    log.error("cache cleanup entry failed: %s", exc)
            limit = self.settings.cache_max_size_mb * 1024 * 1024
            size = self.backend.size_bytes()
            for _mtime, ns, key in sorted(live):  # oldest first
                if size <= limit:
                    break
                try:
                    self.backend.delete(ns, key)
                    result["evicted"] += 1
                    size = self.backend.size_bytes()
                except Exception as exc:
                    result["errors"] += 1
                    log.error("cache eviction failed: %s", exc)
            result["stale_locks"] = self.backend.cleanup_locks(self.settings.cache_lock_stale_seconds)
            result["temp_files"] = self.backend.cleanup_temp(self.settings.cache_lock_stale_seconds)
        except Exception as exc:  # cleanup must never break the app
            result["errors"] += 1
            log.error("cache cleanup failed: %s", exc)
        return result
