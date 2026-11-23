from __future__ import annotations

from backend.config import Settings

from .base import CacheBackend
from .cache_models import CacheBackendUnavailable
from .filesystem_backend import FilesystemBackend
from .redis_backend import RedisBackend


def create_backend(settings: Settings) -> CacheBackend:
    if settings.cache_backend == "filesystem":
        return FilesystemBackend(settings.cache_path)
    if settings.cache_backend == "redis":
        return RedisBackend(settings.redis_url)
    raise CacheBackendUnavailable(f"unknown cache backend {settings.cache_backend!r}")
