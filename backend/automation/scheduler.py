"""APScheduler wiring (spec section 17). APScheduler only *triggers*; LangGraph/services do the work.

Jobs (stable ids, coalesce, max_instances=1, replace_existing => no duplicate scheduling/execution):
  calendar_workflow  daily cron      -> start a workflow for each due PLANNED calendar item
  publishing_queue   interval        -> PublishingQueueService processes due jobs (never publishes in tests)
  cache_cleanup      interval (hrs)  -> CacheCleanupService.run()
Job status is tracked in memory and logged to the ``midnight.scheduler`` channel (no DB log tables).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from backend.config import Settings
from backend.database import get_session
from backend.models import ContentCalendar, Setting
from backend.models.base import utcnow

log = logging.getLogger("midnight.scheduler")

JOB_CALENDAR = "calendar_workflow"
JOB_PUBLISHING = "publishing_queue"
JOB_CACHE = "cache_cleanup"
MAX_CALENDAR_FAILURES = 3
CALENDAR_BATCH = 10


def _run_maybe_async(fn: Callable, *args, **kwargs):
    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):
        res = asyncio.run(_await(res))
    return res


async def _await(aw):
    return await aw


class SchedulerService:
    def __init__(self, settings: Settings, cache=None, scheduler: Optional[BackgroundScheduler] = None,
                 queue=None):
        self.settings = settings
        self.cache = cache
        self.queue = queue  # shared PublishingQueueService (created lazily if None)
        self.tz = ZoneInfo(settings.app_timezone or "Asia/Kolkata")
        self._sched = scheduler or BackgroundScheduler(timezone=self.tz, job_defaults={
            "coalesce": True, "max_instances": 1, "misfire_grace_time": 300})
        self._lock = threading.Lock()
        self._status: dict[str, dict] = {}
        self._sched.add_listener(self._on_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)

    # ------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return bool(self._sched.running)

    def start(self) -> None:
        self.reconfigure()
        if not self._sched.running:
            self._sched.start()
            log.info("scheduler started", extra={"operation": "scheduler_start"})

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)
            log.info("scheduler stopped", extra={"operation": "scheduler_stop"})

    def _operator_settings(self) -> dict:
        try:
            with get_session() as s:
                return {r.key: (r.value or {}).get("value") for r in s.scalars(
                    select(Setting).where(Setting.key.like("scheduler.%")))}
        except Exception:
            log.warning("could not read scheduler settings; using defaults", extra={"operation": "scheduler_config"})
            return {}

    def reconfigure(self) -> None:
        """(Re)register all jobs idempotently: same ids + replace_existing => never duplicates."""
        cfg = self._operator_settings()
        enabled = cfg.get("scheduler.enabled", True)
        hour = int(cfg.get("scheduler.calendar_hour", 0))
        minute = int(cfg.get("scheduler.calendar_minute", 5))
        every = int(cfg.get("scheduler.publishing_interval_seconds", 60))
        jobs = {
            JOB_CALENDAR: (self.run_calendar_workflows, CronTrigger(hour=hour, minute=minute, timezone=self.tz)),
            JOB_PUBLISHING: (self.process_publishing_queue, IntervalTrigger(seconds=every, timezone=self.tz)),
            JOB_CACHE: (self.cleanup_cache, IntervalTrigger(
                hours=max(1, self.settings.cache_cleanup_interval_hours), timezone=self.tz)),
        }
        for job_id, (fn, trigger) in jobs.items():
            with self._lock:
                self._status.setdefault(job_id, {"runs": 0, "failures": 0, "last_run": None, "last_status": None,
                                                 "last_error": None, "last_result": None, "last_duration_s": None})
            self._sched.add_job(self._tracked(job_id, fn), trigger=trigger, id=job_id, name=job_id,
                                replace_existing=True, coalesce=True, max_instances=1, misfire_grace_time=300)
            if not enabled:
                self._sched.pause_job(job_id)

    # ------------------------------------------------------------ tracking
    def _tracked(self, job_id: str, fn: Callable[[], Any]) -> Callable[[], Any]:
        def wrapper():
            return self.run_job(job_id, fn)
        wrapper.__name__ = f"tracked_{job_id}"
        return wrapper

    def run_job(self, job_id: str, fn: Optional[Callable[[], Any]] = None) -> dict:
        """Run a job body with status tracking; never raises (failures are recorded and logged)."""
        fn = fn or {JOB_CALENDAR: self.run_calendar_workflows, JOB_PUBLISHING: self.process_publishing_queue,
                    JOB_CACHE: self.cleanup_cache}[job_id]
        t0 = time.monotonic()
        with self._lock:
            st = self._status.setdefault(job_id, {"runs": 0, "failures": 0})
            st.update(last_run=datetime.now(timezone.utc).isoformat(), last_status="running")
        try:
            result = fn()
            with self._lock:
                st.update(last_status="ok", last_error=None, last_result=result, runs=st["runs"] + 1)
            log.info("job finished", extra={"operation": job_id, "result": result})
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                st.update(last_status="failed", last_error=f"{type(exc).__name__}: {exc}"[:300],
                          runs=st["runs"] + 1, failures=st["failures"] + 1)
            log.error("job failed", extra={"operation": job_id}, exc_info=exc)
        with self._lock:
            st["last_duration_s"] = round(time.monotonic() - t0, 4)
            return dict(st)

    def _on_event(self, event) -> None:
        with self._lock:
            st = self._status.setdefault(event.job_id, {"runs": 0, "failures": 0})
            if event.code == EVENT_JOB_MISSED:
                st["last_status"] = "missed"
        log.warning("job event", extra={"operation": event.job_id, "code": event.code})

    def status(self) -> dict:
        jobs = []
        for job_id in (JOB_CALENDAR, JOB_PUBLISHING, JOB_CACHE):
            job = self._sched.get_job(job_id) if self._sched.running else None
            nxt = getattr(job, "next_run_time", None) if job else None
            with self._lock:
                st = dict(self._status.get(job_id, {}))
            jobs.append({"id": job_id, "scheduled": job is not None, "next_run_time":
                         nxt.isoformat() if nxt else None, **st})
        return {"running": self.running, "timezone": str(self.tz), "jobs": jobs}

    # ------------------------------------------------------------ job bodies
    def run_calendar_workflows(self, now: Optional[datetime] = None) -> dict:
        """Start a workflow for each due PLANNED item. Items are claimed (status TRIGGERED) before the
        call so an overlapping/duplicate run cannot start the same item twice."""
        try:
            from backend.orchestration.workflow_service import get_workflow_service
            wf = get_workflow_service()
        except ImportError:
            return {"skipped": "workflow service unavailable", "started": 0}
        now = now or utcnow()
        started, failed = 0, 0
        with get_session() as s:
            due = list(s.scalars(select(ContentCalendar).where(
                ContentCalendar.status == "PLANNED", ContentCalendar.planned_date <= now)
                .order_by(ContentCalendar.planned_date).limit(CALENDAR_BATCH)))
            for item in due:
                claimed = s.execute(ContentCalendar.__table__.update().where(
                    ContentCalendar.id == item.id, ContentCalendar.status == "PLANNED").values(status="TRIGGERED"))
                s.commit()
                if claimed.rowcount != 1:
                    continue  # another runner took it
                try:
                    # WorkflowService.start(request: dict). story_type on a calendar row is a free label, not
                    # necessarily a story *profile* name, so it is not forwarded (the planner selects the profile).
                    _run_maybe_async(wf.start, {"workflow_type": "story_generation", "calendar_id": item.id,
                                                "topic": item.topic, "genre": item.genre or "horror",
                                                "planned_date": item.planned_date.isoformat()})
                    started += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    s.refresh(item)
                    d = dict(item.details or {})
                    d["failures"] = d.get("failures", 0) + 1
                    d["last_error"] = type(exc).__name__
                    item.details = d
                    item.status = "FAILED" if d["failures"] >= MAX_CALENDAR_FAILURES else "PLANNED"  # retry next run
                    s.commit()
                    log.error("calendar workflow start failed", extra={"operation": JOB_CALENDAR,
                                                                      "calendar_id": item.id}, exc_info=exc)
        return {"started": started, "failed": failed, "due": len(due)}

    def process_publishing_queue(self, max_jobs: int = 20) -> dict:
        """Drain due jobs one at a time via PublishingQueueService.process_next (it claims atomically and
        re-validates every approval/safety gate itself)."""
        try:
            from backend.automation.publishing_queue import PublishingQueueService
        except ImportError:
            return {"skipped": "publishing queue unavailable"}
        svc = self.queue or PublishingQueueService()
        step = getattr(svc, "process_next", None)
        if not callable(step):
            return {"skipped": "publishing queue has no processing entry point"}
        processed = 0
        for _ in range(max_jobs):
            if _run_maybe_async(step) is None:
                break
            processed += 1
        return {"processed": processed}

    def cleanup_cache(self) -> dict:
        backend = getattr(self.cache, "backend", None)
        if self.cache is None or backend is None or not getattr(self.cache, "enabled", False):
            return {"skipped": "cache disabled"}
        from backend.services.cache_cleanup_service import CacheCleanupService
        return CacheCleanupService(backend, self.settings).run()
