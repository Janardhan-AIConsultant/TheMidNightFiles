"""Dashboard, analytics, settings, logs, health, cache/context stats."""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import exists, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.api.common import Page, page_envelope, row
from backend.api.deps import (get_cache_dep, get_context_dep, get_db, get_scheduler_dep, get_settings_dep)
from backend.api.errors import ApiError
from backend.config import Settings
from backend.models import (Analytics, ContentApproval, ContentCalendar, PublishingHistory, PublishingQueue,
                            Setting, Story)
from backend.models.base import utcnow
from backend.services.cache_service import CacheService
from backend.services.context_budget_service import ContextBudgetService
from backend.utils.logging_setup import CHANNELS, redact_text

router = APIRouter()
LOG_CHANNELS = tuple(CHANNELS) + ("error",)  # whitelist; maps to <log_dir>/<channel>.log only
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
SECRET_RE = re.compile(r"(api[_-]?key|secret|token|password|passwd|credential|cookie|profile|url_with)", re.I)
EDITABLE = {  # DB-stored operator settings (never secrets)
    "scheduler.calendar_hour": (int, 0, 23), "scheduler.calendar_minute": (int, 0, 59),
    "scheduler.publishing_interval_seconds": (int, 10, 86400), "scheduler.enabled": (bool, None, None),
    "ui.theme": (str, None, None), "publishing.default_platform": (str, None, None),
}


# ---------------------------------------------------------------- health / stats
@router.get("/health")
def health(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep),
           cache: CacheService = Depends(get_cache_dep), sched=Depends(get_scheduler_dep)):
    checks: dict[str, Any] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    checks["cache"] = "ok" if cache.enabled else "disabled"
    checks["logs_dir"] = "ok" if settings.log_path.is_dir() else "missing"
    checks["scheduler"] = ("running" if sched is not None and sched.running else "stopped") if sched else "disabled"
    for mod in ("backend.orchestration.workflow_service", "backend.automation.publishing_queue"):
        import importlib.util
        try:
            checks[mod.rsplit(".", 1)[-1]] = "available" if importlib.util.find_spec(mod) else "unavailable"
        except Exception:
            checks[mod.rsplit(".", 1)[-1]] = "unavailable"
    status = "ok" if checks["database"] == "ok" else "degraded"
    return {"status": status, "environment": settings.app_env, "timezone": settings.app_timezone, "checks": checks}


@router.get("/cache/stats")
def cache_stats(cache: CacheService = Depends(get_cache_dep)):
    return cache.stats()


@router.get("/context/stats")
def context_stats(ctx: ContextBudgetService = Depends(get_context_dep)):
    return ctx.stats()


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard/summary")
def dashboard(db: Session = Depends(get_db), cache: CacheService = Depends(get_cache_dep),
              ctx: ContextBudgetService = Depends(get_context_dep), sched=Depends(get_scheduler_dep)):
    by_status = {s: n for s, n in db.execute(select(Story.status, func.count()).group_by(Story.status))}
    queue = {s: n for s, n in db.execute(select(PublishingQueue.status, func.count()).group_by(PublishingQueue.status))}
    awaiting = db.scalar(select(func.count()).select_from(Story).where(
        Story.current_version > 0,
        ~exists().where(ContentApproval.story_id == Story.id, ContentApproval.version == Story.current_version,
                        ContentApproval.is_valid.is_(True)))) or 0
    now = utcnow()
    upcoming = [row(c) for c in db.scalars(select(ContentCalendar).where(
        ContentCalendar.planned_date >= now, ContentCalendar.status == "PLANNED")
        .order_by(ContentCalendar.planned_date).limit(5))]
    recent = [row(h) for h in db.scalars(select(PublishingHistory).order_by(PublishingHistory.id.desc()).limit(5))]
    recent_stories = [{"id": s.id, "title": s.title, "status": s.status, "current_version": s.current_version,
                       "updated_at": s.updated_at}
                      for s in db.scalars(select(Story).order_by(Story.updated_at.desc()).limit(5))]
    return {"generated_at": now,
            "stories": {"total": sum(by_status.values()), "by_status": by_status, "recent": recent_stories},
            "approvals": {"awaiting_approval": awaiting},
            "publishing": {"queue_by_status": queue, "recent_history": recent},
            "calendar": {"planned_total": db.scalar(select(func.count()).select_from(ContentCalendar).where(
                ContentCalendar.status == "PLANNED")) or 0, "upcoming": upcoming},
            "cache": cache.stats(), "context": ctx.stats(),
            "scheduler": sched.status() if sched is not None and hasattr(sched, "status") else None}


# ---------------------------------------------------------------- analytics (never fabricated)
@router.get("/analytics/summary")
def analytics_summary(db: Session = Depends(get_db)):
    metrics: dict[str, Any] = {}
    for metric, total, n, avail in db.execute(select(
            Analytics.metric, func.sum(Analytics.value), func.count(),
            func.count(Analytics.value)).group_by(Analytics.metric)):
        metrics[metric] = {"total": total if avail else None, "samples": n, "available_samples": avail}
    published = db.scalar(select(func.count()).select_from(PublishingHistory).where(
        PublishingHistory.outcome.in_(("PUBLISHED", "SUCCESS", "published", "success")))) or 0
    attempts = db.scalar(select(func.count()).select_from(PublishingHistory)) or 0
    return {"status": "available" if metrics else "unavailable",
            "message": None if metrics else "No analytics metrics have been captured yet.",
            "metrics": metrics, "publishing": {"attempts": attempts, "published": published}}


@router.get("/analytics/stories")
def analytics_stories(p: Page = Depends(), db: Session = Depends(get_db), story_id: Optional[str] = None):
    stmt = select(Story).order_by(Story.updated_at.desc())
    if story_id:
        stmt = stmt.where(Story.id == story_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = []
    for s in db.scalars(stmt.limit(p.page_size).offset(p.offset)):
        m: dict[str, Any] = {}
        for metric, platform, value in db.execute(select(Analytics.metric, Analytics.platform, Analytics.value)
                                                  .where(Analytics.story_id == s.id)
                                                  .order_by(Analytics.captured_at, Analytics.id)):
            m.setdefault(metric, {})[platform] = value  # latest wins; value None => unavailable
        items.append({"story_id": s.id, "title": s.title, "status": s.status,
                      "metrics": m or None, "status_detail": "available" if m else "unavailable"})
    return page_envelope(items, total, p)


# ---------------------------------------------------------------- settings
def _mask(v: str) -> str:
    return "********" if v else ""


def _public_config(s: Settings) -> dict:
    db_url = make_url(s.database_url)
    return {
        "app_env": s.app_env, "app_timezone": s.app_timezone, "llm_provider": s.llm_provider,
        "openai_model": s.openai_model, "langsmith_tracing": s.langsmith_tracing,
        "langsmith_project": s.langsmith_project, "cache_enabled": s.cache_enabled,
        "cache_backend": s.cache_backend, "cache_default_ttl_seconds": s.cache_default_ttl_seconds,
        "cache_llm_ttl_seconds": s.cache_llm_ttl_seconds, "cache_max_size_mb": s.cache_max_size_mb,
        "cache_cleanup_interval_hours": s.cache_cleanup_interval_hours,
        "max_revision_attempts": s.max_revision_attempts, "publishing_max_retries": s.publishing_max_retries,
        "cors_origins": list(s.cors_origins), "database": {"dialect": db_url.get_backend_name()},
        "secrets": {"openai_api_key": {"configured": bool(s.openai_api_key.get_secret_value()),
                                       "value": _mask(s.openai_api_key.get_secret_value())},
                    "langsmith_api_key": {"configured": bool(s.langsmith_api_key.get_secret_value()),
                                          "value": _mask(s.langsmith_api_key.get_secret_value())},
                    "redis_url": {"configured": bool(s.redis_url), "value": _mask(s.redis_url)}},
    }


def _stored(db: Session) -> dict:
    out = {}
    for r in db.scalars(select(Setting)):
        if r.key in EDITABLE and not SECRET_RE.search(r.key):
            out[r.key] = r.value.get("value") if isinstance(r.value, dict) else r.value
    return out


@router.get("/settings")
def get_settings_view(db: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)):
    return {"config": _public_config(settings), "operator": _stored(db),
            "editable_keys": sorted(EDITABLE), "read_only_note": "Secrets and infrastructure settings come from the "
                                                                   "environment and cannot be changed here."}


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


@router.put("/settings")
def put_settings(body: SettingsUpdate, request: Request, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings_dep), sched=Depends(get_scheduler_dep)):
    problems = []
    clean: dict[str, Any] = {}
    for k, v in body.values.items():
        spec = EDITABLE.get(k)
        if spec is None or SECRET_RE.search(k):
            problems.append({"key": k, "message": "not an editable setting"})
            continue
        typ, lo, hi = spec
        if typ is bool and not isinstance(v, bool):
            problems.append({"key": k, "message": "must be a boolean"})
        elif typ is int and (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi):
            problems.append({"key": k, "message": f"must be an integer {lo}-{hi}"})
        elif typ is str and (not isinstance(v, str) or len(v) > 100):
            problems.append({"key": k, "message": "must be a short string"})
        else:
            clean[k] = v
    if problems:
        raise ApiError(422, "validation_error", "Invalid settings", problems)
    for k, v in clean.items():
        r = db.get(Setting, k)
        if r is None:
            db.add(Setting(key=k, value={"value": v}))
        else:
            r.value = {"value": v}
    db.commit()
    if sched is not None and any(k.startswith("scheduler.") for k in clean) and hasattr(sched, "reconfigure"):
        sched.reconfigure()
    return {"config": _public_config(settings), "operator": _stored(db)}


# ---------------------------------------------------------------- logs
def _tail(path: Path, max_lines: int) -> list[str]:
    if not path.is_file():
        return []
    with path.open("rb") as f:
        return [ln.decode("utf-8", "replace") for ln in deque(f, maxlen=max_lines)]


@router.get("/logs")
def logs(settings: Settings = Depends(get_settings_dep),
         channel: Literal["app", "agent", "publishing", "scheduler", "error"] = "app",
         level: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = None,
         limit: int = Query(100, ge=1, le=1000)):
    path = settings.log_path / f"{channel}.log"  # channel is a Literal => no arbitrary paths
    floor = LEVELS.get(level or "DEBUG", 0)
    entries: list[dict] = []
    for line in reversed(_tail(path, max(limit * 5, 500))):
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            doc = {"severity": "INFO", "message": line, "malformed": True}
        if not isinstance(doc, dict):
            continue
        if LEVELS.get(str(doc.get("severity", "INFO")).upper(), 20) < floor:
            continue
        try:
            doc = json.loads(redact_text(json.dumps(doc, default=str)))
        except ValueError:
            doc = {"severity": doc.get("severity"), "message": redact_text(str(doc.get("message", "")))}
        entries.append(doc)
        if len(entries) >= limit:
            break
    return {"channel": channel, "level": level, "items": entries, "total": len(entries)}
