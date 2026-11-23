"""Redis backend: optional future implementation (not required for single-host deployment).

Intentionally a stub; selecting it fails loudly at startup rather than silently
degrading. Distributed locking (e.g. SET NX PX) would live here.
"""
from __future__ import annotations

from .base import CacheBackend
from .cache_models import CacheBackendUnavailable


class RedisBackend(CacheBackend):
    def __init__(self, url: str = "", client=None):
        raise CacheBackendUnavailable("Redis cache backend is not implemented yet; use CACHE_BACKEND=filesystem")

    def get(self, namespace, key): raise NotImplementedError
    def put(self, entry): raise NotImplementedError
    def delete(self, namespace, key): raise NotImplementedError
    def iter_entries(self): raise NotImplementedError
    def size_bytes(self): raise NotImplementedError
    def lock(self, namespace, key, timeout, stale_after): raise NotImplementedError
