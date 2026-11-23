"""Pydantic schemas for persistence entities (API list pages: {items,total,page,page_size})."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


class Finding(BaseModel):
    severity: str
    issue: str
    location: Optional[str] = None
    explanation: Optional[str] = None
    recommendation: Optional[str] = None


class StoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    genre: str = "horror"
    story_type: str = "standalone"
    target_word_count: Optional[int] = None
    series_id: Optional[int] = None
    episode_number: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoryOut(ORMModel):
    id: str
    title: str
    genre: str
    story_type: str
    status: str
    current_version: int
    target_word_count: Optional[int] = None
    series_id: Optional[int] = None
    episode_number: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class RevisionCreate(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "original"
    author: str = "system"


class RevisionOut(ORMModel):
    story_id: str
    version: int
    kind: str
    content_hash: str
    word_count: int
    author: str
    created_at: datetime
    text: Optional[str] = None


class ReviewCreate(BaseModel):
    version: int
    status: str
    findings: list[Finding] = Field(default_factory=list)
    coverage: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ReviewOut(ORMModel):
    id: int
    story_id: str
    version: int
    content_hash: str
    status: str
    findings: list[dict[str, Any]]
    coverage: Optional[float] = None
    is_valid: bool
    invalidated_reason: Optional[str] = None
    created_at: datetime


class ApprovalCreate(BaseModel):
    story_id: str
    version: int
    approver: str = Field(min_length=1)
    notes: str = ""


class ApprovalOut(ORMModel):
    id: int
    story_id: str
    version: int
    content_hash: str
    editorial_review_id: int
    safety_review_id: int
    editorial_status: str
    safety_status: str
    approver: str
    approved_at: datetime
    is_valid: bool
    invalidated_reason: Optional[str] = None


class PublishableOut(BaseModel):
    publishable: bool
    reasons: list[str]


class SeriesCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


class SeriesOut(ORMModel):
    id: int
    name: str
    description: str
    current_bible_version: int


class BibleOut(ORMModel):
    series_id: int
    version: int
    bible: dict[str, Any]
    content_hash: str
    author: str
    created_at: datetime


class SummaryOut(ORMModel):
    id: int
    source_type: str
    source_id: str
    source_version: int
    source_hash: str
    kind: str
    text: str
    prompt_version: str
    model: str
    dependencies: dict[str, Any]
    is_valid: bool
