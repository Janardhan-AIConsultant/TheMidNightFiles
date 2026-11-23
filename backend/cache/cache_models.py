from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CacheError(Exception):
    pass


class CacheCorruptError(CacheError):
    pass


class CacheBackendUnavailable(CacheError):
    pass


class CacheLockTimeout(CacheError):
    pass


@dataclass
class CacheEntry:
    namespace: str
    key: str
    value: Any
    created_at: float
    expires_at: float | None
    story_id: str | None = None
    version: int | None = None
    meta: dict = field(default_factory=dict)

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at
