"""Human approval bound to exact version + review IDs."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ContentApproval, EditorialStatus, SafetyStatus, Story, StoryRevision
from backend.services.review_service import ReviewService


class ApprovalError(Exception):
    pass


class ApprovalService:
    def __init__(self, session: Session):
        self.session = session
        self.reviews = ReviewService(session)

    def _gate_check(self, story_id: str, version: int):
        """Return (reasons, editorial, safety, revision)."""
        reasons: list[str] = []
        story = self.session.get(Story, story_id)
        if story is None:
            return ["unknown story"], None, None, None
        rev = self.session.scalar(select(StoryRevision).where(
            StoryRevision.story_id == story_id, StoryRevision.version == version))
        if rev is None:
            return [f"no revision v{version}"], None, None, None
        if version != story.current_version:
            reasons.append(f"v{version} is not the current version (v{story.current_version})")
        ed = self.reviews.latest_editorial(story_id, version)
        sf = self.reviews.latest_safety(story_id, version)
        if ed is None:
            reasons.append("no valid editorial review for this version")
        elif ed.status != EditorialStatus.APPROVED.value:
            reasons.append(f"editorial status is {ed.status}")
        elif ed.content_hash != rev.content_hash:
            reasons.append("editorial review content hash mismatch")
        if sf is None:
            reasons.append("no valid safety review for this version")
        else:
            if sf.status != SafetyStatus.PASSED.value:
                reasons.append(f"safety status is {sf.status}")
            elif sf.coverage != 1.0:
                reasons.append("safety review coverage incomplete")
            if sf.content_hash != rev.content_hash:
                reasons.append("safety review content hash mismatch")
        return reasons, ed, sf, rev

    def approve(self, story_id: str, version: int, approver: str, notes: str = "") -> ContentApproval:
        if not approver or not approver.strip():
            raise ApprovalError("approver required")
        reasons, ed, sf, rev = self._gate_check(story_id, version)
        if reasons:
            raise ApprovalError("; ".join(reasons))
        existing = self.valid_approval(story_id, version)
        if existing is not None and existing.editorial_review_id == ed.id and existing.safety_review_id == sf.id:
            return existing
        if existing is not None:
            existing.is_valid = False
            existing.invalidated_reason = "re-approved against newer reviews"
        approval = ContentApproval(story_id=story_id, version=version, content_hash=rev.content_hash,
                                   editorial_review_id=ed.id, safety_review_id=sf.id,
                                   editorial_status=ed.status, safety_status=sf.status,
                                   approver=approver.strip(), notes=notes, is_valid=True)
        self.session.add(approval)
        self.session.get(Story, story_id).status = "APPROVED"
        self.session.commit()
        return approval

    def valid_approval(self, story_id: str, version: int) -> Optional[ContentApproval]:
        return self.session.scalar(select(ContentApproval).where(
            ContentApproval.story_id == story_id, ContentApproval.version == version,
            ContentApproval.is_valid.is_(True)).order_by(ContentApproval.id.desc()))

    def revoke(self, story_id: str, version: int, reason: str = "revoked") -> int:
        n = 0
        for a in self.session.scalars(select(ContentApproval).where(
                ContentApproval.story_id == story_id, ContentApproval.version == version,
                ContentApproval.is_valid.is_(True))):
            a.is_valid, a.invalidated_reason = False, reason
            n += 1
        self.session.commit()
        return n

    def is_publishable(self, story_id: str, version: int) -> tuple[bool, list[str]]:
        """Independent re-validation of every gate (used by the publishing worker)."""
        reasons, ed, sf, rev = self._gate_check(story_id, version)
        if not reasons:
            ap = self.valid_approval(story_id, version)
            if ap is None:
                reasons.append("no valid human approval for this version")
            else:
                if ap.editorial_review_id != ed.id or ap.safety_review_id != sf.id:
                    reasons.append("approval is bound to superseded reviews")
                if ap.content_hash != rev.content_hash:
                    reasons.append("approval content hash mismatch")
        return (not reasons), reasons
