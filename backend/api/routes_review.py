"""Reviews, approvals, safety, distribution."""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.common import Page, page_envelope, paginate, row
from backend.api.deps import get_approval_service, get_db, get_review_service
from backend.api.errors import ApiError, NotFound
from backend.models import (ContentApproval, ContentSafetyReview, ContinuityReview, DistributionContent,
                            EditorialReview, HumanisationReview, Story)
from backend.services.approval_service import ApprovalService
from backend.services.review_service import ReviewService

router = APIRouter()

REVIEW_MODELS = {"editorial": EditorialReview, "safety": ContentSafetyReview, "continuity": ContinuityReview,
                 "humanisation": HumanisationReview}
PLATFORM_RE = re.compile(r"^[a-z0-9_]{2,30}$")


class ApprovalRequest(BaseModel):
    story_id: str
    version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    notes: str = ""
    approver: str = Field(default="operator", min_length=1, max_length=100)


class DistributionPut(BaseModel):
    payload: dict
    version: Optional[int] = Field(default=None, ge=1)
    status: Optional[str] = None


def review_dict(r, kind: str) -> dict:
    d = row(r)
    d["review_type"] = kind
    return d


# ---------------------------------------------------------------- reviews
@router.get("/reviews")
def list_reviews(p: Page = Depends(), db: Session = Depends(get_db), story_id: Optional[str] = None,
                 review_type: Optional[Literal["editorial", "safety", "continuity", "humanisation"]] = None,
                 status: Optional[str] = None, valid_only: bool = False):
    kinds = [review_type] if review_type else list(REVIEW_MODELS)
    items: list[dict] = []
    for k in kinds:
        m = REVIEW_MODELS[k]
        stmt = select(m)
        if story_id:
            stmt = stmt.where(m.story_id == story_id)
        if status:
            stmt = stmt.where(m.status == status)
        if valid_only:
            stmt = stmt.where(m.is_valid.is_(True))
        items.extend(review_dict(r, k) for r in db.scalars(stmt))
    items.sort(key=lambda d: (d["created_at"], d["id"]), reverse=True)
    return page_envelope(items[p.offset:p.offset + p.page_size], len(items), p)


@router.get("/safety/reviews")
def safety_reviews(p: Page = Depends(), db: Session = Depends(get_db), story_id: Optional[str] = None,
                   status: Optional[str] = None, valid_only: bool = False):
    stmt = select(ContentSafetyReview)
    if story_id:
        stmt = stmt.where(ContentSafetyReview.story_id == story_id)
    if status:
        stmt = stmt.where(ContentSafetyReview.status == status)
    if valid_only:
        stmt = stmt.where(ContentSafetyReview.is_valid.is_(True))
    return paginate(db, stmt.order_by(ContentSafetyReview.id.desc()), p, lambda r: review_dict(r, "safety"))


# ---------------------------------------------------------------- approvals
@router.get("/approvals/pending")
def pending_approvals(p: Page = Depends(), db: Session = Depends(get_db),
                      reviews: ReviewService = Depends(get_review_service),
                      approvals: ApprovalService = Depends(get_approval_service)):
    """Stories whose current version has no valid human approval. Statuses are informational only:
    whether approval is allowed is decided solely by ApprovalService.approve (409 if blocked)."""
    stories = db.scalars(select(Story).where(Story.current_version > 0).order_by(Story.updated_at.desc())).all()
    items = []
    for s in stories:
        if approvals.valid_approval(s.id, s.current_version) is not None:
            continue
        ed, sf = reviews.latest_editorial(s.id, s.current_version), reviews.latest_safety(s.id, s.current_version)
        items.append({"story_id": s.id, "title": s.title, "version": s.current_version, "story_status": s.status,
                      "editorial_status": ed.status if ed else None, "editorial_review_id": ed.id if ed else None,
                      "safety_status": sf.status if sf else None, "safety_review_id": sf.id if sf else None,
                      "safety_coverage": sf.coverage if sf else None})
    return page_envelope(items[p.offset:p.offset + p.page_size], len(items), p)


@router.get("/approvals")
def list_approvals(p: Page = Depends(), db: Session = Depends(get_db), story_id: Optional[str] = None,
                   valid_only: bool = False):
    stmt = select(ContentApproval)
    if story_id:
        stmt = stmt.where(ContentApproval.story_id == story_id)
    if valid_only:
        stmt = stmt.where(ContentApproval.is_valid.is_(True))
    return paginate(db, stmt.order_by(ContentApproval.id.desc()), p, row)


@router.post("/approvals")
def decide_approval(body: ApprovalRequest, db: Session = Depends(get_db),
                    approvals: ApprovalService = Depends(get_approval_service)):
    if db.get(Story, body.story_id) is None:
        raise NotFound(f"Story {body.story_id}")
    if body.decision == "approve":
        # No eligibility logic here: ApprovalService is the single gate (ApprovalError -> 409).
        return {"decision": "approve", "approval": row(approvals.approve(body.story_id, body.version,
                                                                         body.approver, body.notes))}
    revoked = approvals.revoke(body.story_id, body.version, f"rejected by {body.approver}: {body.notes}"[:200])
    return {"decision": "reject", "revoked_approvals": revoked, "approval": None}


# ---------------------------------------------------------------- distribution
def _check_platform(platform: str) -> str:
    if not PLATFORM_RE.match(platform):
        raise ApiError(422, "validation_error", "invalid platform identifier")
    return platform


@router.get("/distribution/{story_id}/{platform}")
def get_distribution(story_id: str, platform: str, version: Optional[int] = None, db: Session = Depends(get_db)):
    _check_platform(platform)
    s = db.get(Story, story_id)
    if s is None:
        raise NotFound(f"Story {story_id}")
    v = version or s.current_version
    d = db.scalar(select(DistributionContent).where(
        DistributionContent.story_id == story_id, DistributionContent.platform == platform,
        DistributionContent.version == v))
    if d is None:
        raise NotFound(f"Distribution content for {story_id} v{v} on {platform}")
    return row(d)


@router.put("/distribution/{story_id}/{platform}")
def put_distribution(story_id: str, platform: str, body: DistributionPut, db: Session = Depends(get_db)):
    _check_platform(platform)
    s = db.get(Story, story_id)
    if s is None:
        raise NotFound(f"Story {story_id}")
    v = body.version or s.current_version
    if v < 1:
        raise ApiError(409, "no_content", "Story has no revision to attach distribution content to")
    d = db.scalar(select(DistributionContent).where(
        DistributionContent.story_id == story_id, DistributionContent.platform == platform,
        DistributionContent.version == v))
    if d is None:
        d = DistributionContent(story_id=story_id, platform=platform, version=v, payload=body.payload,
                                status=body.status or "DRAFT")
        db.add(d)
    else:
        d.payload = body.payload
        if body.status:
            d.status = body.status
    db.commit()
    return row(d)
