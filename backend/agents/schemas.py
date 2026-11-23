"""Pydantic input/output schemas for all agents."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_id: Optional[str] = None
    version: Optional[int] = None
    workflow_id: Optional[str] = Field(default=None, description="tracing only; excluded from cache keys")


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    severity: Severity
    issue: str = Field(min_length=1)
    location: str = Field(min_length=1, description="quoted passage, section or paragraph")
    explanation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    category: str = "other"

    @field_validator("severity", mode="before")
    @classmethod
    def _lower(cls, v):
        return v.lower() if isinstance(v, str) else v


# ---- planner -----------------------------------------------------------------------------------------------------
class CalendarEntry(BaseModel):
    date: str
    topic: str
    genre: str = "horror"
    story_type: str = "standalone"


class PlannerInput(AgentInput):
    topic: Optional[str] = None
    genre: str = "horror"
    story_type: Optional[str] = None
    target_word_count: Optional[int] = None
    platform: Optional[str] = None
    series_mode: bool = False
    planned_date: Optional[str] = None
    calendar_days: int = Field(default=0, ge=0, le=365)
    topic_history: list[str] = []


class PlannerOutput(AgentOutput):
    working_title: str = Field(min_length=1)
    genre: str
    subgenre: str = ""
    story_type: str = "standalone"
    target_word_count: int = Field(gt=0)
    audience: str = ""
    hook: str
    synopsis: str = Field(min_length=1)
    characters: list[str] = []
    setting: str = ""
    planned_date: Optional[str] = None
    series_association: Optional[str] = None
    platform_opportunities: list[str] = []
    calendar: list[CalendarEntry] = []


# ---- writer / humanisation ---------------------------------------------------------------------------------------
class WriterInput(AgentInput):
    brief: dict
    profile: dict
    series_context: dict = {}
    revision_findings: list[dict] = []
    previous_text: Optional[str] = None


class WriterOutput(AgentOutput):
    title: str = ""
    text: str = Field(min_length=1)


class HumanisationInput(AgentInput):
    story_text: str = Field(min_length=1)
    profile: dict = {}
    revision_findings: list[dict] = []


class HumanisationOutput(AgentOutput):
    text: str = Field(min_length=1)
    changes: list[str] = []


# ---- reviewers ---------------------------------------------------------------------------------------------------
class ReviewInput(AgentInput):
    story_text: str = Field(min_length=1)
    profile: dict = {}
    series_context: dict = {}
    section: int = 0
    total_sections: int = 1


class ContinuityOutput(AgentOutput):
    status: Literal["CONSISTENT", "ISSUES_FOUND", "HUMAN_REVIEW_REQUIRED"]
    findings: list[Finding] = []
    bible_updates: dict = {}


class EditorialOutput(AgentOutput):
    status: Literal["APPROVED", "NEEDS_REVISION", "HUMAN_REVIEW_REQUIRED", "REJECTED"]
    findings: list[Finding] = []
    scores: dict[str, Any] = {}
    reviewed_complete: bool = False


class SafetyOutput(AgentOutput):
    status: Literal["PASSED", "NEEDS_REVISION", "HUMAN_REVIEW_REQUIRED", "BLOCKED"]
    findings: list[Finding] = []
    reviewed_complete: bool = False


class AggregatedReview(BaseModel):
    """Result of reviewing a complete story (possibly in several sections)."""
    status: str
    findings: list[dict]
    coverage: float
    sections: int
    failed_sections: int = 0
    scores: dict = {}


# ---- images / distribution ---------------------------------------------------------------------------------------
class ImageInput(AgentInput):
    synopsis: str
    title: str = ""
    visual_direction: str = ""
    characters: list[str] = []


class ImageAsset(BaseModel):
    kind: Literal["cover", "article", "youtube_thumbnail", "instagram"]
    aspect_ratio: str
    prompt: str = Field(min_length=1)
    alt_text: str = ""
    reference: Optional[str] = None


class ImageOutput(AgentOutput):
    assets: list[ImageAsset] = Field(min_length=1)


PLATFORMS = ("substack", "youtube_shorts", "instagram_reels", "reddit")


class DistributionInput(AgentInput):
    story_text: str = Field(min_length=1)
    title: str = ""
    platforms: list[str] = list(PLATFORMS)
    image_refs: dict[str, str] = {}

    @field_validator("platforms")
    @classmethod
    def _known(cls, v):
        bad = [p for p in v if p not in PLATFORMS]
        if bad:
            raise ValueError(f"unknown platforms {bad}")
        return v


REQUIRED_FIELDS = {
    "substack": ["title", "body", "seo_title", "seo_description", "tags"],
    "youtube_shorts": ["hook", "narration", "script", "title", "description", "hashtags"],
    "instagram_reels": ["hook", "script", "narration", "description", "hashtags"],
    "reddit": ["title", "body", "discussion_question", "subreddits"],
}


class DistributionOutput(AgentOutput):
    platforms: dict[str, dict]


# ---- publishing / analytics --------------------------------------------------------------------------------------
class PublishingInput(AgentInput):
    story_id: str
    version: int
    distribution: dict[str, dict] = {}
    asset_refs: list[str] = []
    scheduled_for: Optional[str] = None
    platform_config: dict[str, bool] = {}
    require_approval: bool = False
    enqueue: bool = False


class PublishingOutput(AgentOutput):
    ready: bool
    reasons: list[str] = []
    jobs: list[dict] = []


class AnalyticsInput(AgentInput):
    metrics: dict[str, dict[str, Optional[float]]] = {}
    expected: list[str] = ["views", "reads", "likes", "comments", "shares", "subscribers"]


class AnalyticsOutput(AgentOutput):
    available: dict[str, dict[str, float]]
    missing: dict[str, list[str]]
    engagement_rate: dict[str, Optional[float]] = {}
