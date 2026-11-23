"""Cache invalidation hooks. Wire ``on_new_version`` into StoryService's injected callback."""
from __future__ import annotations

import logging

from backend.services.cache_service import CacheService

log = logging.getLogger("midnight.app.cache")


class CacheInvalidationService:
    def __init__(self, cache: CacheService):
        self.cache = cache

    def on_new_version(self, story_id: str, version: int) -> int:
        """A new immutable revision exists: drop story-level entries and entries for >= version.
        Entries for older immutable versions are keyed by version and remain correct for those versions.
        Approvals/reviews are never cached, so nothing stale can be reused for the new version."""
        n = self.cache.invalidate_story(story_id, from_version=version)
        log.info("cache invalidated for new story version", extra={"story_id": story_id, "story_version": version,
                                                                   "operation": "cache_invalidate", "removed": n})
        return n

    def invalidate_story(self, story_id: str) -> int:
        return self.cache.invalidate_story(story_id)

    def invalidate_namespace(self, namespace: str) -> int:
        return self.cache.invalidate_namespace(namespace)

    def on_policy_change(self, namespaces=("safety", "editorial")) -> int:
        """Safety-policy / criteria change: previous reviews must not be reused."""
        return sum(self.cache.invalidate_namespace(ns) for ns in namespaces)
