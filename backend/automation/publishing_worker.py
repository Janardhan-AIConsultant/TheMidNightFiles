"""Executes ONE claimed job: gates -> browser -> (destination check on re-attempt) -> submit -> verify."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.automation.browser_manager import BrowserManager
from backend.automation.publishing_validator import PublishingValidator
from backend.automation.publishing_verifier import PublishingVerifier
from backend.models import PublishingHistory, PublishingQueue
from backend.publishers import PUBLISHERS
from backend.publishers.base_publisher import (AutomationBlocked, PublisherError, SubmissionResult,
                                               UncertainSubmission)

# outcome kinds
PUBLISHED, SCHEDULED, GATE_BLOCKED, AUTOMATION_BLOCKED, RETRY, UNCERTAIN = (
    "PUBLISHED", "SCHEDULED", "GATE_BLOCKED", "AUTOMATION_BLOCKED", "RETRY", "UNCERTAIN")


@dataclass
class WorkerOutcome:
    kind: str
    url: Optional[str] = None
    screenshot_ref: Optional[str] = None
    error: Optional[str] = None
    reasons: list = field(default_factory=list)
    manual_fallback: Optional[str] = None


class PublishingWorker:
    def __init__(self, session: Session, browser: BrowserManager, verifier: PublishingVerifier,
                 validator: Optional[PublishingValidator] = None, publishers: Optional[dict] = None):
        self.session = session
        self.browser = browser
        self.verifier = verifier
        self.validator = validator or PublishingValidator(session)
        self.publishers = publishers or PUBLISHERS

    def _prior_attempts(self, job: PublishingQueue) -> bool:
        return self.session.scalars(select(PublishingHistory.id).where(
            PublishingHistory.story_id == job.story_id, PublishingHistory.version == job.version,
            PublishingHistory.platform == job.platform)).first() is not None

    def execute(self, job: PublishingQueue) -> WorkerOutcome:
        v = self.validator.validate(job)
        if not v.ok:
            return WorkerOutcome(GATE_BLOCKED, error="; ".join(v.reasons), reasons=v.reasons)
        publisher = self.publishers[job.platform]()
        prior = self._prior_attempts(job)

        def pre_submit():  # independent gate re-check immediately before the submit click
            again = self.validator.validate(job)
            if not again.ok:
                raise _GateFailure(again.reasons)

        try:
            with self.browser.session(job.platform) as page:
                result = None
                if prior:  # destination verification before any retry of a possibly-submitted post
                    found = publisher.find_existing(page, v.payload)
                    if found:
                        result = SubmissionResult(url=found, status="published")
                if result is None:
                    result = publisher.publish(page, v.payload, None,
                                               pre_submit=pre_submit)
                ver = self.verifier.verify(page, publisher, result, v.payload, job.id)
        except _GateFailure as g:
            return WorkerOutcome(GATE_BLOCKED, error="; ".join(g.reasons), reasons=g.reasons)
        except AutomationBlocked as b:
            return WorkerOutcome(AUTOMATION_BLOCKED, error=b.reason, manual_fallback=b.manual_fallback)
        except UncertainSubmission as u:
            return WorkerOutcome(UNCERTAIN, error=str(u))
        except PublisherError as e:
            return WorkerOutcome(RETRY, error=str(e))
        except Exception as e:  # browser launch failure etc. (nothing submitted)
            return WorkerOutcome(RETRY, error=f"{type(e).__name__}: {e}")
        if not ver.verified:
            return WorkerOutcome(UNCERTAIN, url=result.url, error="submission could not be verified at destination")
        kind = SCHEDULED if ver.status == "scheduled" else PUBLISHED
        return WorkerOutcome(kind, url=ver.url, screenshot_ref=ver.screenshot_ref)


class _GateFailure(PublisherError):
    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons
