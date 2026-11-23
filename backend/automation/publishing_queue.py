"""Publishing queue: safe claim, idempotency, duplicate prevention, retry with exponential backoff."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import func, select, update

from backend.automation import publishing_worker as pw
from backend.automation.browser_manager import BrowserManager
from backend.automation.publishing_validator import (PLATFORMS, SUCCESS_OUTCOMES, PublishingValidator,
                                                     idempotency_key)
from backend.automation.publishing_verifier import PublishingVerifier
from backend.models import PublishingHistory, PublishingQueue
from backend.models.base import utcnow
from backend.services.approval_service import ApprovalService

ACTIVE = ("PENDING", "CLAIMED")
RETRYABLE_STATES = ("FAILED", "BLOCKED", "BLOCKED_AUTOMATION", "UNCERTAIN", "CLAIMED")


class PublishingQueueError(Exception):
    pass


class PublishingQueueService:
    def __init__(self, session_factory: Optional[Callable] = None, browser: Optional[BrowserManager] = None,
                 publishers: Optional[dict] = None, max_retries: Optional[int] = None,
                 backoff_base_seconds: float = 60.0, data_dir: Optional[Path] = None,
                 now: Callable[[], datetime] = utcnow):
        if session_factory is None:
            from backend import database
            session_factory = database.get_session
        self._sf = session_factory
        if max_retries is None:
            from backend.config import get_settings
            max_retries = get_settings().publishing_max_retries
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self.now = now
        if data_dir is None:
            from backend.config import get_settings
            data_dir = Path(get_settings().data_dir)
        self.records_dir = Path(data_dir) / "publishing"
        self.browser = browser or BrowserManager()
        self.publishers = publishers

    # ---- sidecar record (url / screenshot / idempotency key / error detail) ------
    def _rec_path(self, job_id: int) -> Path:
        return self.records_dir / "records" / f"{job_id}.json"

    def _rec_read(self, job_id: int) -> dict:
        try:
            return json.loads(self._rec_path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _rec_update(self, job_id: int, **kw) -> None:
        rec = self._rec_read(job_id)
        rec.update({k: v for k, v in kw.items() if v is not None})
        p = self._rec_path(job_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        tmp.replace(p)

    def _to_dict(self, j: PublishingQueue) -> dict:
        rec = self._rec_read(j.id)
        return {
            "id": j.id, "story_id": j.story_id, "version": j.version, "platform": j.platform,
            "status": j.status, "scheduled_at": j.scheduled_for.isoformat() if j.scheduled_for else None,
            "attempts": j.attempts, "last_error": j.last_error, "approval_id": j.approval_id,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "idempotency_key": idempotency_key(j.story_id, j.version, j.platform),
            "external_url": rec.get("external_url"), "screenshot_ref": rec.get("screenshot_ref"),
            "manual_fallback": rec.get("manual_fallback"),
        }

    def _history(self, s, j: PublishingQueue, outcome: str, url: Optional[str] = None) -> None:
        s.add(PublishingHistory(queue_id=j.id, story_id=j.story_id, version=j.version, platform=j.platform,
                                outcome=outcome, external_url=url, published_at=self.now()))

    # ---- public API ---------------------------------------------------------------
    def enqueue(self, story_id: str, version: int, platform: str, scheduled_at: Optional[datetime] = None) -> dict:
        if platform not in PLATFORMS:
            raise PublishingQueueError(f"unsupported platform {platform!r}")
        with self._sf() as s:
            ok, reasons = ApprovalService(s).is_publishable(story_id, int(version))
            if not ok:
                raise PublishingQueueError("not publishable: " + "; ".join(reasons))
            if PublishingValidator(s).already_published(story_id, version, platform):
                raise PublishingQueueError("duplicate: already published for this story/version/platform")
            existing = s.scalars(select(PublishingQueue).where(
                PublishingQueue.story_id == story_id, PublishingQueue.version == version,
                PublishingQueue.platform == platform,
                PublishingQueue.status.in_(ACTIVE + ("UNCERTAIN",)))).first()
            if existing is not None:  # idempotent enqueue: return the active job
                return self._to_dict(existing)
            ap = ApprovalService(s).valid_approval(story_id, version)
            job = PublishingQueue(story_id=story_id, version=version, platform=platform,
                                  approval_id=ap.id if ap else None, status="PENDING",
                                  scheduled_for=scheduled_at, attempts=0)
            s.add(job)
            s.flush()
            self._rec_update(job.id, idempotency_key=idempotency_key(story_id, version, platform))
            return self._to_dict(job)

    def cancel(self, job_id: int) -> dict:
        with self._sf() as s:
            j = s.get(PublishingQueue, job_id)
            if j is None:
                raise PublishingQueueError(f"unknown job {job_id}")
            if j.status in ("PUBLISHED", "SCHEDULED"):
                raise PublishingQueueError("cannot cancel a published job")
            if j.status == "CLAIMED":
                raise PublishingQueueError("job is currently being processed")
            j.status = "CANCELLED"
            self._history(s, j, "CANCELLED")
            return self._to_dict(j)

    def retry(self, job_id: int) -> dict:
        """Manual retry: re-queues; every gate is re-validated at execution (and destination is checked)."""
        with self._sf() as s:
            j = s.get(PublishingQueue, job_id)
            if j is None:
                raise PublishingQueueError(f"unknown job {job_id}")
            if j.status not in RETRYABLE_STATES:
                raise PublishingQueueError(f"job in status {j.status} cannot be retried")
            ap = ApprovalService(s).valid_approval(j.story_id, j.version)
            j.approval_id = ap.id if ap else j.approval_id
            j.status, j.attempts, j.scheduled_for, j.last_error = "PENDING", 0, None, None
            return self._to_dict(j)

    def list_jobs(self, page: int = 1, page_size: int = 20, status: Optional[str] = None,
                  platform: Optional[str] = None, story_id: Optional[str] = None) -> dict:
        page, page_size = max(1, int(page)), max(1, min(int(page_size), 200))
        with self._sf() as s:
            q = select(PublishingQueue)
            cq = select(func.count()).select_from(PublishingQueue)
            for col, val in ((PublishingQueue.status, status), (PublishingQueue.platform, platform),
                         (PublishingQueue.story_id, story_id)):
                if val:
                    q, cq = q.where(col == val), cq.where(col == val)
            total = s.scalar(cq) or 0
            rows = s.scalars(q.order_by(PublishingQueue.id.desc()).offset((page - 1) * page_size)
                             .limit(page_size)).all()
            return {"items": [self._to_dict(r) for r in rows], "total": total, "page": page,
                    "page_size": page_size}

    # ---- processing ---------------------------------------------------------------
    def _claim(self, s) -> Optional[PublishingQueue]:
        now = self.now()
        ids = s.scalars(select(PublishingQueue.id).where(
            PublishingQueue.status == "PENDING",
            (PublishingQueue.scheduled_for.is_(None)) | (PublishingQueue.scheduled_for <= now))
            .order_by(PublishingQueue.id)).all()
        for jid in ids:  # atomic compare-and-set: only one worker wins
            res = s.execute(update(PublishingQueue).where(PublishingQueue.id == jid,
                                                          PublishingQueue.status == "PENDING")
                            .values(status="CLAIMED"))
            if res.rowcount == 1:
                s.commit()
                s.expire_all()
                return s.get(PublishingQueue, jid)
        return None

    def process_next(self) -> Optional[dict]:
        with self._sf() as s:
            job = self._claim(s)
            if job is None:
                return None
            job.attempts += 1
            s.commit()
            worker = pw.PublishingWorker(
                s, self.browser, PublishingVerifier(self.records_dir / "screenshots"),
                PublishingValidator(s, self.now), self.publishers)
            try:
                out = worker.execute(job)
            except Exception as exc:  # never leave a job stuck in CLAIMED
                out = pw.WorkerOutcome(pw.RETRY, error=f"{type(exc).__name__}: {exc}")
            self._apply(s, job, out)
            s.commit()
            return self._to_dict(job)

    def _apply(self, s, job: PublishingQueue, out: "pw.WorkerOutcome") -> None:
        job.last_error = out.error
        if out.kind in (pw.PUBLISHED, pw.SCHEDULED):
            job.status, job.last_error = out.kind, None
            self._history(s, job, out.kind, out.url)
            self._rec_update(job.id, external_url=out.url, screenshot_ref=out.screenshot_ref)
        elif out.kind == pw.GATE_BLOCKED:  # gates failed: no submission, no auto-retry
            job.status = "BLOCKED"
            self._history(s, job, "BLOCKED")
        elif out.kind == pw.AUTOMATION_BLOCKED:  # stop safely; human must act
            job.status = "BLOCKED_AUTOMATION"
            self._history(s, job, "BLOCKED_AUTOMATION")
            self._rec_update(job.id, manual_fallback=out.manual_fallback)
        else:  # RETRY / UNCERTAIN
            self._history(s, job, "UNCERTAIN" if out.kind == pw.UNCERTAIN else "FAILED_ATTEMPT")
            if job.attempts >= self.max_retries:
                job.status = "UNCERTAIN" if out.kind == pw.UNCERTAIN else "FAILED"
                self._rec_update(job.id, manual_fallback="Max retries reached. Check the destination "
                                                         "manually before re-queuing.")
            else:
                delay = self.backoff_base * (2 ** (job.attempts - 1))
                job.scheduled_for = self.now() + timedelta(seconds=delay)
                job.status = "PENDING"
