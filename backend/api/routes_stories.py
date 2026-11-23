"""Stories, revisions, story profiles, workflow-start actions, calendar."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.common import Page, call, naive_utc, paginate, plain, row
from backend.api.deps import (get_approval_service, get_db, get_review_service, get_story_service,
                              get_workflow_service_dep)
from backend.api.errors import ApiError, NotFound
from backend.api.routes_workflow import build_start_request, guarded, workflow_view
from backend.models import ContentCalendar, Story, StoryRevision
from backend.services.approval_service import ApprovalService
from backend.services.review_service import ReviewService
from backend.services.story_profile_service import list_profiles, select_story_profile
from backend.services.story_service import StoryService

router = APIRouter()


# ---------------------------------------------------------------- models
class StoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    genre: str = "horror"
    story_type: str = "standalone"
    target_word_count: Optional[int] = Field(default=None, ge=1)
    series_id: Optional[int] = None
    episode_number: Optional[int] = None
    metadata: dict = Field(default_factory=dict)
    text: Optional[str] = None
    author: str = "operator"


class StoryPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    genre: Optional[str] = None
    story_type: Optional[str] = None
    target_word_count: Optional[int] = Field(default=None, ge=1)
    metadata: Optional[dict] = None
    text: Optional[str] = None  # a text edit creates a NEW immutable revision via StoryService
    revision_kind: str = "original"
    author: str = "operator"


class RevisionCreate(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "original"
    author: str = "operator"


class WorkflowAction(BaseModel):
    version: Optional[int] = None
    params: dict = Field(default_factory=dict)


class CalendarCreate(BaseModel):
    planned_date: datetime
    topic: str = Field(min_length=1, max_length=300)
    genre: Optional[str] = None
    story_type: str = "standalone"
    story_id: Optional[str] = None
    details: dict = Field(default_factory=dict)


class CalendarPatch(BaseModel):
    planned_date: Optional[datetime] = None
    topic: Optional[str] = Field(default=None, min_length=1, max_length=300)
    genre: Optional[str] = None
    story_type: Optional[str] = None
    details: Optional[dict] = None


# ---------------------------------------------------------------- helpers
# The UI labels edits "manual_edit" / "restore"; the stored RevisionKind enum only has original/humanised/final.
# A human edit or restore is stored as a new "original" revision (immutable history keeps every version).
_KIND_ALIASES = {"manual_edit": "original", "edit": "original", "manual": "original", "restore": "original"}


def _kind(k: str) -> str:
    return _KIND_ALIASES.get(k, k)


def rev_dict(r: StoryRevision, include_text: bool) -> dict:
    return row(r, exclude=() if include_text else ("text",))


def story_dict(s: Story) -> dict:
    return row(s)


def _detail(s: Story, db: Session, approvals: ApprovalService, reviews: ReviewService, svc: StoryService) -> dict:
    out = story_dict(s)
    out["current_revision"] = None
    out["review_state"] = None
    if s.current_version > 0:
        out["current_revision"] = rev_dict(svc.get_revision(s.id, s.current_version), True)
        ed, sf = reviews.latest_editorial(s.id, s.current_version), reviews.latest_safety(s.id, s.current_version)
        ok, reasons = approvals.is_publishable(s.id, s.current_version)
        ap = approvals.valid_approval(s.id, s.current_version)
        out["review_state"] = {"editorial_status": ed.status if ed else None,
                               "safety_status": sf.status if sf else None,
                               "approved": ap is not None, "publishable": ok, "blockers": reasons}
    return out


def _get_story(db: Session, story_id: str) -> Story:
    s = db.get(Story, story_id)
    if s is None:
        raise NotFound(f"Story {story_id}")
    return s


# ---------------------------------------------------------------- stories
@router.get("/stories")
def list_stories(p: Page = Depends(), db: Session = Depends(get_db), status: Optional[str] = None,
                 genre: Optional[str] = None, story_type: Optional[str] = None, series_id: Optional[int] = None,
                 q: Optional[str] = Query(None, max_length=200),
                 sort: str = Query("updated_desc", pattern="^(updated_desc|updated_asc|created_desc|created_asc|title)$")):
    stmt = select(Story)
    if status:
        stmt = stmt.where(Story.status == status)
    if genre:
        stmt = stmt.where(Story.genre == genre)
    if story_type:
        stmt = stmt.where(Story.story_type == story_type)
    if series_id is not None:
        stmt = stmt.where(Story.series_id == series_id)
    if q:
        stmt = stmt.where(Story.title.ilike(f"%{q}%"))
    order = {"updated_desc": Story.updated_at.desc(), "updated_asc": Story.updated_at.asc(),
             "created_desc": Story.created_at.desc(), "created_asc": Story.created_at.asc(),
             "title": Story.title.asc()}[sort]
    return paginate(db, stmt.order_by(order, Story.id), p, story_dict)


@router.post("/stories", status_code=201)
def create_story(body: StoryCreate, svc: StoryService = Depends(get_story_service),
                 approvals: ApprovalService = Depends(get_approval_service),
                 reviews: ReviewService = Depends(get_review_service), db: Session = Depends(get_db)):
    story = svc.create_story(body.title, body.genre, body.story_type, body.target_word_count, body.series_id,
                             body.episode_number, body.metadata)
    if body.text:
        svc.add_revision(story.id, body.text, "original", body.author)
    return _detail(db.get(Story, story.id), db, approvals, reviews, svc)


@router.get("/stories/{story_id}")
def get_story(story_id: str, db: Session = Depends(get_db), svc: StoryService = Depends(get_story_service),
              approvals: ApprovalService = Depends(get_approval_service),
              reviews: ReviewService = Depends(get_review_service)):
    return _detail(_get_story(db, story_id), db, approvals, reviews, svc)


@router.patch("/stories/{story_id}")
def patch_story(story_id: str, body: StoryPatch, db: Session = Depends(get_db),
                svc: StoryService = Depends(get_story_service),
                approvals: ApprovalService = Depends(get_approval_service),
                reviews: ReviewService = Depends(get_review_service)):
    story = _get_story(db, story_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data and not data["title"].strip():
        raise ApiError(422, "validation_error", "title must not be blank")
    for k, attr in (("title", "title"), ("genre", "genre"), ("story_type", "story_type"),
                    ("target_word_count", "target_word_count"), ("metadata", "story_metadata")):
        if k in data and data[k] is not None:
            setattr(story, attr, data[k])
    db.commit()
    if body.text is not None:  # content edits ONLY via StoryService => new version + invalidation
        svc.add_revision(story_id, body.text, _kind(body.revision_kind), body.author)
    return _detail(db.get(Story, story_id), db, approvals, reviews, svc)


@router.get("/stories/{story_id}/revisions")
def list_revisions(story_id: str, p: Page = Depends(), include_text: bool = False, db: Session = Depends(get_db)):
    _get_story(db, story_id)
    stmt = select(StoryRevision).where(StoryRevision.story_id == story_id).order_by(StoryRevision.version.desc())
    return paginate(db, stmt, p, lambda r: rev_dict(r, include_text))


@router.get("/stories/{story_id}/revisions/{version}")
def get_revision(story_id: str, version: int, svc: StoryService = Depends(get_story_service),
                 db: Session = Depends(get_db)):
    _get_story(db, story_id)
    return rev_dict(svc.get_revision(story_id, version), True)


@router.post("/stories/{story_id}/revisions", status_code=201)
def create_revision(story_id: str, body: RevisionCreate, svc: StoryService = Depends(get_story_service),
                    db: Session = Depends(get_db)):
    _get_story(db, story_id)
    return rev_dict(svc.add_revision(story_id, body.text, _kind(body.kind), body.author), True)


# ---------------------------------------------------------------- story profiles
@router.get("/story-profiles")
def story_profiles(story_type: Optional[str] = None, word_count: Optional[int] = None,
                   platform: Optional[str] = None, series_mode: bool = False):
    out: dict[str, Any] = {"items": list_profiles(), "selected": None}
    out["total"] = len(out["items"])
    if story_type or word_count or platform or series_mode:
        out["selected"] = select_story_profile(story_type, word_count, platform, series_mode).to_dict()
    return out


# ---------------------------------------------------------------- workflow-start actions
async def _start(kind: str, story_id: str, body: WorkflowAction, db: Session, wf) -> dict:
    s = _get_story(db, story_id)
    if s.current_version < 1:
        raise ApiError(409, "no_content", "Story has no revision to process")
    version = body.version or s.current_version
    # humanise / continuity / editorial / safety all run as a one-stage story_review workflow
    req = build_start_request("story_review", story_id, {**body.params, "version": version, "stages": [kind]})
    wid = await guarded(wf.start, req)
    doc = await guarded(wf.get, wid) if isinstance(wid, str) and callable(getattr(wf, "get", None)) else None
    return workflow_view(doc) if isinstance(doc, dict) else (
        {"workflow_id": wid, "id": wid, "status": "running"} if isinstance(wid, str) else workflow_view(wid))


def _action(kind: str):
    async def handler(story_id: str, body: Optional[WorkflowAction] = None, db: Session = Depends(get_db),
                      wf=Depends(get_workflow_service_dep)):
        from fastapi.responses import JSONResponse
        from fastapi.encoders import jsonable_encoder
        res = await _start(kind, story_id, body or WorkflowAction(), db, wf)
        return JSONResponse(status_code=202, content=jsonable_encoder(res))
    handler.__name__ = f"start_{kind}"
    return handler


for _k in ("humanise", "continuity", "editorial", "safety"):
    router.add_api_route(f"/stories/{{story_id}}/{_k}", _action(_k), methods=["POST"], status_code=202)


# ---------------------------------------------------------------- calendar
def cal_dict(c: ContentCalendar) -> dict:
    return row(c)


@router.get("/calendar")
def list_calendar(p: Page = Depends(), db: Session = Depends(get_db), start: Optional[datetime] = None,
                  end: Optional[datetime] = None, status: Optional[str] = None, story_id: Optional[str] = None):
    stmt = select(ContentCalendar)
    if start:
        stmt = stmt.where(ContentCalendar.planned_date >= naive_utc(start))
    if end:
        stmt = stmt.where(ContentCalendar.planned_date <= naive_utc(end))
    if status:
        stmt = stmt.where(ContentCalendar.status == status)
    if story_id:
        stmt = stmt.where(ContentCalendar.story_id == story_id)
    return paginate(db, stmt.order_by(ContentCalendar.planned_date, ContentCalendar.id), p, cal_dict)


@router.post("/calendar", status_code=201)
def create_calendar(body: CalendarCreate, db: Session = Depends(get_db)):
    if body.story_id and db.get(Story, body.story_id) is None:
        raise NotFound(f"Story {body.story_id}")
    item = ContentCalendar(planned_date=naive_utc(body.planned_date), topic=body.topic.strip(),
                           genre=body.genre, story_type=body.story_type, story_id=body.story_id,
                           details=body.details, status="PLANNED")
    db.add(item)
    db.commit()
    return cal_dict(item)


@router.patch("/calendar/{item_id}")
def reschedule_calendar(item_id: int, body: CalendarPatch, db: Session = Depends(get_db)):
    item = db.get(ContentCalendar, item_id)
    if item is None:
        raise NotFound(f"Calendar item {item_id}")
    if item.status != "PLANNED":
        raise ApiError(409, "not_reschedulable", f"Calendar item is {item.status}; only PLANNED items can change")
    data = body.model_dump(exclude_unset=True)
    if data.get("planned_date"):
        item.planned_date = naive_utc(data["planned_date"])
    for k in ("topic", "genre", "story_type", "details"):
        if data.get(k) is not None:
            setattr(item, k, data[k])
    db.commit()
    return cal_dict(item)
