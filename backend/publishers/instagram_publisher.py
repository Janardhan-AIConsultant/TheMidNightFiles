from __future__ import annotations

from typing import Any

from backend.publishers.base_publisher import BasePublisher, SubmissionResult


class InstagramPublisher(BasePublisher):
    platform = "instagram"
    compose_url = "https://www.instagram.com/"
    list_url = "https://www.instagram.com/accounts/activity/"
    login_url = "https://www.instagram.com/accounts/login/"
    required_fields = ("caption", "video_path")
    needs_video = True

    def title_of(self, payload: dict) -> str:
        return str(payload.get("caption") or "")[:60]

    def fill(self, page: Any, payload: dict) -> None:
        page.click("svg[aria-label='New post']")
        page.set_input_files("input[type='file']", payload["video_path"])
        page.click("text=Next")
        if payload.get("cover_path"):
            page.set_input_files("input[type='file'][accept*='image']", payload["cover_path"])
        page.click("text=Next")
        tags = " ".join(payload.get("hashtags") or [])
        page.fill("div[aria-label='Write a caption...']", (payload["caption"] + ("\n" + tags if tags else "")).strip())

    def submit(self, page: Any, payload: dict, scheduled_at=None) -> SubmissionResult:
        page.click("text=Share")
        return SubmissionResult(url=getattr(page, "url", None), status="published")
