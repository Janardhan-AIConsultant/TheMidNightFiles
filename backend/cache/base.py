"""Backend abstraction. A Redis-compatible implementation only needs these methods."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Iterator

from .cache_models import CacheEntry


class CacheBackend(ABC):
    @abstractmethod
    def get(self, namespace: str, key: str) -> CacheEntry | None:
        """Return entry or None. Raise CacheCorruptError for unreadable/tampered entries
        (the backend must already have removed it)."""

    @abstractmethod
    def put(self, entry: CacheEntry) -> None: ...

    @abstractmethod
    def delete(self, namespace: str, key: str) -> bool: ...

    @abstractmethod
    def iter_entries(self) -> Iterator[tuple[str, str, CacheEntry | None]]:
        """Yield (namespace, key, entry); entry None means the stored data is corrupt."""

    @abstractmethod
    def size_bytes(self) -> int: ...

    @abstractmethod
    def lock(self, namespace: str, key: str, timeout: float, stale_after: float) -> AbstractContextManager:
        """Same-host mutual exclusion. Raise CacheLockTimeout on timeout."""

    def cleanup_locks(self, stale_after: float) -> int:
        return 0

    def cleanup_temp(self, older_than: float) -> int:
        return 0

    def entry_sort_key(self, namespace: str, key: str) -> float:
        """Age ordering used for size-limit eviction (smaller = older)."""
        return 0.0
