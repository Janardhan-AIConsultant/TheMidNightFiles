"""Independent re-validation of every publishing gate (run at claim time, right before submit, and on retries)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (ContinuityReview, ContinuityStatus, DistributionContent, PublishingHistory,
                            PublishingQueue, Story, StoryRevision)
from backend.models.base import utcnow
from backend.services.approval_service import ApprovalService
from backend.services.review_service import ReviewService

SUCCESS_OUTCOMES = ("PUBLISHED", "SCHEDULED")
PLATFORMS = ("substack", "youtube", "instagram", "reddit")
REQUIRED = {
    "substack": ("title", "body"),
    "youtube": ("title", "description", "video_path"),
    "instagram": ("caption", "video_path"),
    "reddit": ("subreddit", "title", "body"),
}
DIST_KEYS = {"youtube": ("youtube", "youtube_shorts"), "instagram": ("instagram", "instagram_reels")}
ASSET_KEYS = ("video_path", "thumbnail_path", "cover_image_path", "cover_path")


def idempotency_key(story_id: str, version: int, platform: str) -> str:
    return hashlib.sha256(f"{story_id}:{version}:{platform}".encode()).hexdigest()


@dataclass
class ValidationResult:
    ok: bool
    reasons: list = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    idempotency_key: str = ""


class PublishingValidator:
    def __init__(self, session: Session, now: Callable[[], datetime] = utcnow):
        self.session = session
        self.now = now

    def already_published(self, story_id: str, version: int, platform: str,
                          exclude_queue_id: Optional[int] = None) -> Optional[PublishingHistory]:
        q = select(PublishingHistory).where(
            PublishingHistory.story_id == story_id, PublishingHistory.version == version,
            PublishingHistory.platform == platform, PublishingHistory.outcome.in_(SUCCESS_OUTCOMES))
        return self.session.scalars(q).first()

    def build_payload(self, story: Story, rev: StoryRevision, platform: str) -> dict:
        # The distribution agent stores youtube_shorts / instagram_reels; the queue names destinations.
        keys = DIST_KEYS.get(platform, (platform,))
        dist = self.session.scalar(select(DistributionContent).where(
            DistributionContent.story_id == story.id, DistributionContent.version == rev.version,
            DistributionContent.platform.in_(keys)))
        payload = dict((dist.payload if dist else None) or {})
        if platform in ("substack", "reddit"):
            payload.setdefault("title", story.title)
            payload.setdefault("body", rev.text)
        if platform == "instagram" and payload.get("description"):
            payload.setdefault("caption", payload["description"])
        if platform == "reddit" and payload.get("subreddits"):
            payload.setdefault("subreddit", str(payload["subreddits"][0]).removeprefix("r/"))
        return payload

    def validate(self, job: PublishingQueue, check_schedule: bool = True) -> ValidationResult:
        key = idempotency_key(job.story_id, job.version, job.platform)
        reasons: list = []
        if job.platform not in PLATFORMS:
            return ValidationResult(False, [f"unsupported platform {job.platform}"], {}, key)
        story = self.session.get(Story, job.story_id)
        if story is None:
            return ValidationResult(False, ["unknown story"], {}, key)
        rev = self.session.scalar(select(StoryRevision).where(
            StoryRevision.story_id == job.story_id, StoryRevision.version == job.version))
        if rev is None:
            return ValidationResult(False, [f"no revision v{job.version}"], {}, key)
        # story id, exact/current version, editorial, safety, approval (authoritative service)
        ok, why = ApprovalService(self.session).is_publishable(job.story_id, job.version)
        if not ok:
            reasons.extend(why)
        if job.version != story.current_version and not any("current version" in r for r in reasons):
            reasons.append(f"stale version v{job.version} (current v{story.current_version})")
        # continuity where applicable
        if story.series_id is not None:
            cont = ReviewService(self.session).latest_valid(ContinuityReview, job.story_id, job.version)
            if cont is None:
                reasons.append("no valid continuity review for series story")
            elif cont.status != ContinuityStatus.CONSISTENT.value:
                reasons.append(f"continuity status is {cont.status}")
            elif cont.content_hash != rev.content_hash:
                reasons.append("continuity review content hash mismatch")
        # approval bound to this job
        ap = ApprovalService(self.session).valid_approval(job.story_id, job.version)
        if job.approval_id is not None and (ap is None or ap.id != job.approval_id):
            reasons.append("approval changed or invalidated since enqueue")
        # payload + assets
        payload = self.build_payload(story, rev, job.platform)
        missing = [k for k in REQUIRED[job.platform] if not payload.get(k)]
        if missing:
            reasons.append(f"payload missing required fields: {missing}")
        for k in ASSET_KEYS:
            if payload.get(k) and not Path(str(payload[k])).is_file():
                reasons.append(f"asset not found: {k}")
        # schedule
        if check_schedule and job.scheduled_for is not None and job.scheduled_for > self.now():
            reasons.append("job is not due yet")
        # idempotency / duplicate prevention
        if self.already_published(job.story_id, job.version, job.platform):
            reasons.append("duplicate: already published for this story/version/platform")
        return ValidationResult(not reasons, reasons, payload, key)
