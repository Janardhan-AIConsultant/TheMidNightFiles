"""Base class for browser publishers. Works against a Playwright-like ``page``.

Safety rules: never bypass CAPTCHA/MFA/anti-bot; stop and raise AutomationBlocked instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class PublisherError(Exception):
    """Failure BEFORE anything was submitted (safe to retry)."""


class AutomationBlocked(PublisherError):
    """Login/MFA/CAPTCHA/anti-bot wall hit. Never retried automatically; manual action needed."""

    def __init__(self, reason: str, manual_fallback: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.manual_fallback = manual_fallback


class UncertainSubmission(Exception):
    """Submit was clicked but the outcome is unknown. Destination must be verified before any retry."""


@dataclass
class SubmissionResult:
    url: Optional[str] = None
    status: str = "published"  # published | scheduled | draft
    details: dict = field(default_factory=dict)


class BasePublisher:
    platform = ""
    compose_url = ""
    list_url = ""
    login_url = ""
    required_fields: tuple = ()
    needs_video = False
    block_markers: tuple = (
        "iframe[src*='captcha']", "iframe[src*='recaptcha']", "#captcha", "[data-testid='captcha']",
        "input[name='otp']", "input[autocomplete='one-time-code']", "text=Unusual activity",
        "text=Confirm you are not a robot",
    )
    login_markers: tuple = ("input[type='password']",)

    # ---- helpers -----------------------------------------------------------------
    @staticmethod
    def _present(page: Any, selector: str) -> bool:
        try:
            return page.locator(selector).count() > 0
        except Exception:
            return False

    def check_blocked(self, page: Any) -> None:
        for sel in self.block_markers:
            if self._present(page, sel):
                raise AutomationBlocked(f"{self.platform}: CAPTCHA/MFA/anti-bot challenge detected",
                                        self.manual_fallback_text())
        for sel in self.login_markers:
            if self._present(page, sel):
                raise AutomationBlocked(f"{self.platform}: not logged in (manual login required)",
                                        self.manual_fallback_text())

    def manual_fallback_text(self) -> str:
        return (f"Log in to {self.platform} manually in the dedicated browser profile, "
                f"then publish from {self.compose_url or self.list_url} or re-queue the job.")

    @staticmethod
    def _text(page: Any) -> str:
        try:
            return page.inner_text("body") or ""
        except Exception:
            return ""

    # ---- platform hooks ----------------------------------------------------------
    def fill(self, page: Any, payload: dict) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def configure(self, page: Any, payload: dict, scheduled_at=None) -> None:
        return None

    def submit(self, page: Any, payload: dict, scheduled_at=None) -> SubmissionResult:  # pragma: no cover
        raise NotImplementedError

    def check_fields(self, page: Any, payload: dict) -> None:
        missing = [f for f in self.required_fields if not payload.get(f)]
        if missing:
            raise PublisherError(f"missing fields before submit: {missing}")

    def title_of(self, payload: dict) -> str:
        return str(payload.get("title") or "")

    # ---- template ----------------------------------------------------------------
    def publish(self, page: Any, payload: dict, scheduled_at=None, pre_submit=None) -> SubmissionResult:
        page.goto(self.compose_url)
        self.check_blocked(page)
        try:
            self.fill(page, payload)
            self.configure(page, payload, scheduled_at)
            self.check_fields(page, payload)
        except PublisherError:
            raise
        except Exception as exc:
            raise PublisherError(f"{self.platform}: {exc}") from exc
        self.check_blocked(page)  # last look before submitting
        if pre_submit is not None:
            pre_submit()  # worker re-validates every gate; raises PublisherError to abort
        try:
            result = self.submit(page, payload, scheduled_at)
        except Exception as exc:  # outcome unknown after click
            raise UncertainSubmission(f"{self.platform}: submit outcome unknown: {exc}") from exc
        try:
            self.check_blocked(page)
        except AutomationBlocked as exc:
            raise UncertainSubmission(f"blocked after submit: {exc.reason}") from exc
        return result

    def find_existing(self, page: Any, payload: dict) -> Optional[str]:
        """Look at the destination for an already-created post with this title."""
        page.goto(self.list_url)
        self.check_blocked(page)
        title = self.title_of(payload)
        if title and title in self._text(page):
            return getattr(page, "url", None) or self.list_url
        return None

    def verify_published(self, page: Any, result: SubmissionResult, payload: dict) -> bool:
        if not result.url:
            return False
        page.goto(result.url)
        self.check_blocked(page)
        title = self.title_of(payload)
        return bool(title) and title in self._text(page)
