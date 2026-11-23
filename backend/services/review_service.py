"""Editorial / continuity / safety / humanisation review recording."""
from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (ContentSafetyReview, ContinuityReview, ContinuityStatus, EditorialReview,
                            EditorialStatus, HumanisationReview, SafetyStatus, StoryRevision)


class ReviewError(Exception):
    pass


class ReviewService:
    def __init__(self, session: Session):
        self.session = session

    def _revision(self, story_id: str, version: int) -> StoryRevision:
        rev = self.session.scalar(
            select(StoryRevision).where(StoryRevision.story_id == story_id, StoryRevision.version == version))
        if rev is None:
            raise ReviewError(f"no revision {story_id} v{version}")
        return rev

    def _record(self, model, story_id, version, status, findings, coverage, reviewer):
        rev = self._revision(story_id, version)
        row = model(story_id=story_id, version=version, content_hash=rev.content_hash, status=status,
                    findings=list(findings or []), coverage=coverage, reviewer=reviewer, is_valid=True)
        self.session.add(row)
        self.session.commit()
        return row

    @staticmethod
    def _status(enum_cls, status) -> str:
        value = status.value if hasattr(status, "value") else status
        try:
            return enum_cls(value).value
        except ValueError:
            raise ReviewError(f"invalid status {status!r} for {enum_cls.__name__}") from None

    @staticmethod
    def _check_findings(findings: Optional[Sequence[dict]]):
        for f in findings or []:
            if not isinstance(f, dict) or not f.get("severity") or not f.get("issue"):
                raise ReviewError("every finding needs at least severity and issue")

    def record_editorial(self, story_id: str, version: int, status, findings: Sequence[dict] = (),
                         coverage: Optional[float] = None, reviewer: str = "editorial_agent") -> EditorialReview:
        st = self._status(EditorialStatus, status)
        self._check_findings(findings)
        if st == EditorialStatus.APPROVED.value and (coverage is not None and coverage < 1.0):
            raise ReviewError("APPROVED requires the complete narrative to be reviewed (coverage 1.0)")
        return self._record(EditorialReview, story_id, version, st, findings, coverage, reviewer)

    def record_continuity(self, story_id: str, version: int, status, findings: Sequence[dict] = (),
                          coverage: Optional[float] = None, reviewer: str = "continuity_agent") -> ContinuityReview:
        st = self._status(ContinuityStatus, status)
        self._check_findings(findings)
        return self._record(ContinuityReview, story_id, version, st, findings, coverage, reviewer)

    def record_humanisation(self, story_id: str, version: int, status: str, findings: Sequence[dict] = (),
                            coverage: Optional[float] = None, reviewer: str = "humanisation_agent") -> HumanisationReview:
        return self._record(HumanisationReview, story_id, version, status, findings, coverage, reviewer)

    def record_safety(self, story_id: str, version: int, status, findings: Sequence[dict] = (),
                      coverage: Optional[float] = None, reviewer: str = "safety_agent") -> ContentSafetyReview:
        st = self._status(SafetyStatus, status)
        self._check_findings(findings)
        if st == SafetyStatus.PASSED.value:
            if coverage is None or coverage != 1.0:
                raise ReviewError("safety PASSED requires coverage == 1.0")
            if any(str(f.get("severity", "")).lower() == "critical" for f in findings or []):
                raise ReviewError("safety PASSED is incompatible with critical findings")
        return self._record(ContentSafetyReview, story_id, version, st, findings, coverage, reviewer)

    def latest_valid(self, model, story_id: str, version: int):
        return self.session.scalar(
            select(model).where(model.story_id == story_id, model.version == version, model.is_valid.is_(True))
            .order_by(model.id.desc()))

    def latest_editorial(self, story_id: str, version: int) -> Optional[EditorialReview]:
        return self.latest_valid(EditorialReview, story_id, version)

    def latest_safety(self, story_id: str, version: int) -> Optional[ContentSafetyReview]:
        return self.latest_valid(ContentSafetyReview, story_id, version)

    def list_reviews(self, story_id: str) -> list:
        out: list = []
        for model in (EditorialReview, ContentSafetyReview, ContinuityReview, HumanisationReview):
            out.extend(self.session.scalars(select(model).where(model.story_id == story_id)))
        return sorted(out, key=lambda r: r.created_at)
