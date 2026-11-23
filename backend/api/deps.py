"""FastAPI dependencies. External services (workflow, publishing) are imported lazily -> 503 if absent.

Tests inject fakes with ``app.dependency_overrides[get_workflow_service_dep] = lambda: fake``.
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.api.errors import ServiceUnavailable
from backend.config import Settings
from backend.database import get_db
from backend.services.approval_service import ApprovalService
from backend.services.cache_invalidation_service import CacheInvalidationService
from backend.services.cache_service import CacheService
from backend.services.content_path_manager import ContentPathManager
from backend.services.context_budget_service import ContextBudgetService
from backend.services.review_service import ReviewService
from backend.services.story_service import StoryService

__all__ = ["get_db", "get_settings_dep", "get_cache_dep", "get_context_dep", "get_story_service",
           "get_approval_service", "get_review_service", "get_workflow_service_dep",
           "get_publishing_service_dep", "get_scheduler_dep"]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_cache_dep(request: Request) -> CacheService:
    st = request.app.state
    if getattr(st, "cache", None) is None:
        st.cache = CacheService(st.settings)
    return st.cache


def get_context_dep(request: Request) -> ContextBudgetService:
    st = request.app.state
    if getattr(st, "context_budget", None) is None:
        st.context_budget = ContextBudgetService(settings=st.settings)
    return st.context_budget


def get_story_service(db: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep),
                      cache: CacheService = Depends(get_cache_dep)) -> StoryService:
    """Every edit goes through StoryService: immutable versioning + review/approval/cache invalidation."""
    return StoryService(db, ContentPathManager(settings.data_path / "content"),
                        on_new_version=CacheInvalidationService(cache).on_new_version)


def get_approval_service(db: Session = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)


def get_review_service(db: Session = Depends(get_db)) -> ReviewService:
    return ReviewService(db)


def get_workflow_service_dep(request: Request):
    shared = getattr(request.app.state, "workflow", None)
    if shared is not None:
        return shared
    try:
        from backend.orchestration.workflow_service import get_workflow_service
    except ImportError as exc:
        raise ServiceUnavailable("Workflow service is not available (backend.orchestration not installed)") from exc
    try:
        return get_workflow_service()
    except Exception as exc:
        raise ServiceUnavailable(f"Workflow service failed to initialise: {type(exc).__name__}") from exc


def get_publishing_service_dep(request: Request):
    shared = getattr(request.app.state, "publishing_queue", None)
    if shared is not None:
        return shared
    try:
        from backend.automation.publishing_queue import PublishingQueueService
    except ImportError as exc:
        raise ServiceUnavailable("Publishing queue service is not available") from exc
    try:
        return PublishingQueueService()
    except Exception as exc:
        raise ServiceUnavailable(f"Publishing queue failed to initialise: {type(exc).__name__}") from exc


def get_scheduler_dep(request: Request):
    return getattr(request.app.state, "scheduler", None)
