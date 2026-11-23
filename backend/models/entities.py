"""Business entities (spec section 11). No log/trace tables by design."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, event)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, utcnow


class ImmutableError(Exception):
    pass


class StorySeries(Base):
    __tablename__ = "story_series"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    current_bible_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SeriesContinuity(Base):
    """Immutable, versioned series bible."""
    __tablename__ = "series_continuity"
    __table_args__ = (UniqueConstraint("series_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("story_series.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    bible: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Story(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    genre: Mapped[str] = mapped_column(String(100), default="horror")
    story_type: Mapped[str] = mapped_column(String(50), default="standalone")
    target_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    series_id: Mapped[Optional[int]] = mapped_column(ForeignKey("story_series.id"), nullable=True)
    episode_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    story_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StoryRevision(Base):
    """Immutable: updates and deletes are rejected at ORM level."""
    __tablename__ = "story_revisions"
    __table_args__ = (UniqueConstraint("story_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    author: Mapped[str] = mapped_column(String(100), default="system")
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


@event.listens_for(StoryRevision, "before_update")
def _no_update(mapper, connection, target):
    raise ImmutableError("story revisions are immutable")


@event.listens_for(StoryRevision, "before_delete")
def _no_delete(mapper, connection, target):
    raise ImmutableError("story revisions cannot be deleted")


class _ReviewMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))
    findings: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(100), default="agent")
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    invalidated_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EditorialReview(_ReviewMixin, Base):
    __tablename__ = "editorial_reviews"


class ContentSafetyReview(_ReviewMixin, Base):
    __tablename__ = "content_safety_reviews"


class ContinuityReview(_ReviewMixin, Base):
    __tablename__ = "continuity_reviews"


class HumanisationReview(_ReviewMixin, Base):
    __tablename__ = "humanisation_reviews"


class ContentApproval(Base):
    __tablename__ = "content_approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    editorial_review_id: Mapped[int] = mapped_column(ForeignKey("editorial_reviews.id"))
    safety_review_id: Mapped[int] = mapped_column(ForeignKey("content_safety_reviews.id"))
    editorial_status: Mapped[str] = mapped_column(String(40))
    safety_status: Mapped[str] = mapped_column(String(40))
    approver: Mapped[str] = mapped_column(String(100))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    invalidated_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    source_version: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(50))
    path: Mapped[str] = mapped_column(String(500))
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    referenced: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DistributionContent(Base):
    __tablename__ = "distribution_content"
    __table_args__ = (UniqueConstraint("story_id", "version", "platform"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PublishingQueue(Base):
    __tablename__ = "publishing_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(30))
    approval_id: Mapped[Optional[int]] = mapped_column(ForeignKey("content_approvals.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PublishingHistory(Base):
    __tablename__ = "publishing_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("publishing_queue.id"), nullable=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(30))
    external_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlatformAccount(Base):
    """Never stores raw secrets; only a reference to env/secret store."""
    __tablename__ = "platform_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(30))
    handle: Mapped[str] = mapped_column(String(200))
    credential_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Analytics(Base):
    __tablename__ = "analytics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    metric: Mapped[str] = mapped_column(String(50))
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # None = unavailable
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContentCalendar(Base):
    __tablename__ = "content_calendar"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    planned_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    story_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stories.id"), nullable=True)
    topic: Mapped[str] = mapped_column(String(300))
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    story_type: Mapped[str] = mapped_column(String(50), default="standalone")
    status: Mapped[str] = mapped_column(String(30), default="PLANNED")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class TopicHistory(Base):
    __tablename__ = "topic_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(300), index=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    story_id: Mapped[Optional[str]] = mapped_column(ForeignKey("stories.id"), nullable=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Summary(Base):
    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True)
    source_version: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    dependencies: Mapped[dict] = mapped_column(JSON, default=dict)  # dep key -> hash
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    invalidated_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
