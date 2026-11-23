"""Story and immutable revision management."""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.models import (ContentApproval, ContentSafetyReview, ContinuityReview, EditorialReview,
                            HumanisationReview, RevisionKind, Story, StoryRevision)
from backend.services.content_path_manager import ContentPathManager


class StoryError(Exception):
    pass


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StoryService:
    def __init__(self, session: Session, path_manager: Optional[ContentPathManager] = None,
                 on_new_version: Optional[Callable[[str, int], None]] = None):
        self.session = session
        self.paths = path_manager
        self.on_new_version = on_new_version

    def create_story(self, title: str, genre: str = "horror", story_type: str = "standalone",
                     target_word_count: Optional[int] = None, series_id: Optional[int] = None,
                     episode_number: Optional[int] = None, metadata: Optional[dict] = None) -> Story:
        if not title or not title.strip():
            raise StoryError("title required")
        nums = [int(i.split("-")[1]) for i in self.session.scalars(select(Story.id)) if i.startswith("STORY-")]
        story = Story(id=f"STORY-{(max(nums) if nums else 0) + 1:04d}", title=title.strip(), genre=genre,
                      story_type=story_type, target_word_count=target_word_count, series_id=series_id,
                      episode_number=episode_number, story_metadata=metadata or {})
        self.session.add(story)
        self.session.commit()
        return story

    def get_story(self, story_id: str) -> Story:
        story = self.session.get(Story, story_id)
        if story is None:
            raise StoryError(f"unknown story {story_id}")
        return story

    def add_revision(self, story_id: str, text: str, kind: str = "original", author: str = "system") -> StoryRevision:
        story = self.get_story(story_id)
        kind_v = kind.value if isinstance(kind, RevisionKind) else kind
        try:
            RevisionKind(kind_v)
        except ValueError:
            raise StoryError(f"invalid revision kind {kind!r}") from None
        if not text or not text.strip():
            raise StoryError("revision text required")
        version = (self.session.scalar(
            select(func.max(StoryRevision.version)).where(StoryRevision.story_id == story_id)) or 0) + 1
        file_path = None
        if self.paths is not None:  # write file first; never overwrites (raises if exists)
            file_path = str(self.paths.write_atomic(
                self.paths.revision_path(story_id, version, f"{kind_v}.md"), text))
        rev = StoryRevision(story_id=story_id, version=version, kind=kind_v, text=text,
                            content_hash=hash_text(text), word_count=len(text.split()), author=author,
                            file_path=file_path)
        self.session.add(rev)
        story.current_version = version
        story.status = "DRAFT"
        self._invalidate_older(story_id, version)
        self.session.commit()
        if self.on_new_version is not None:
            self.on_new_version(story_id, version)
        return rev

    def _invalidate_older(self, story_id: str, new_version: int) -> None:
        reason = f"superseded by v{new_version}"
        for model in (EditorialReview, ContentSafetyReview, ContinuityReview, HumanisationReview, ContentApproval):
            self.session.execute(
                update(model).where(model.story_id == story_id, model.version < new_version,
                                    model.is_valid.is_(True))
                .values(is_valid=False, invalidated_reason=reason))

    def get_revision(self, story_id: str, version: Optional[int] = None) -> StoryRevision:
        q = select(StoryRevision).where(StoryRevision.story_id == story_id)
        q = q.where(StoryRevision.version == version) if version is not None else q.order_by(
            StoryRevision.version.desc())
        rev = self.session.scalars(q).first()
        if rev is None:
            raise StoryError(f"no revision for {story_id} version={version}")
        return rev

    def list_revisions(self, story_id: str) -> list[StoryRevision]:
        return list(self.session.scalars(
            select(StoryRevision).where(StoryRevision.story_id == story_id).order_by(StoryRevision.version)))
