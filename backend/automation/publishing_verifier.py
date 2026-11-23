"""Success is only recorded after the destination confirms the post."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from backend.publishers.base_publisher import BasePublisher, SubmissionResult


@dataclass
class VerificationResult:
    verified: bool
    url: Optional[str] = None
    screenshot_ref: Optional[str] = None
    status: str = "published"


class PublishingVerifier:
    def __init__(self, screenshot_dir: Path):
        self.screenshot_dir = Path(screenshot_dir)

    def verify(self, page: Any, publisher: BasePublisher, result: SubmissionResult, payload: dict,
               job_id: int) -> VerificationResult:
        try:
            ok = publisher.verify_published(page, result, payload)
        except Exception:
            ok = False
        if not ok:
            return VerificationResult(False, result.url, None, result.status)
        return VerificationResult(True, result.url, self._screenshot(page, job_id), result.status)

    def _screenshot(self, page: Any, job_id: int) -> Optional[str]:
        try:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = self.screenshot_dir / f"job-{job_id}.png"
            page.screenshot(path=str(path))
            return str(path)
        except Exception:
            return None  # screenshot is best-effort; verification itself already passed
