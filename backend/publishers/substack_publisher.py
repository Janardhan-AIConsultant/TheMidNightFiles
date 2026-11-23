from __future__ import annotations

from typing import Any

from backend.publishers.base_publisher import BasePublisher, SubmissionResult


class SubstackPublisher(BasePublisher):
    platform = "substack"
    compose_url = "https://substack.com/publish/post"
    list_url = "https://substack.com/publish/posts"
    login_url = "https://substack.com/sign-in"
    required_fields = ("title", "body")

    def fill(self, page: Any, payload: dict) -> None:
        page.fill("[data-testid='post-title'], textarea[placeholder='Title']", payload["title"])
        if payload.get("subtitle"):
            page.fill("[data-testid='post-subtitle']", payload["subtitle"])
        page.fill(".editor-content, [contenteditable='true']", payload["body"])
        if payload.get("cover_image_path"):
            page.set_input_files("input[type='file']", payload["cover_image_path"])

    def configure(self, page: Any, payload: dict, scheduled_at=None) -> None:
        page.click("button:has-text('Continue')")
        if payload.get("tags"):
            page.fill("input[placeholder*='tag' i]", ", ".join(payload["tags"]))
        if payload.get("seo_description"):
            page.fill("textarea[name='search_engine_description']", payload["seo_description"])
        page.click("text=Paid subscribers only" if payload.get("audience") == "paid" else "text=Everyone")
        if scheduled_at:
            page.click("text=Schedule for later")
            page.fill("input[name='schedule_datetime']", scheduled_at.strftime("%Y-%m-%d %H:%M"))

    def submit(self, page: Any, payload: dict, scheduled_at=None) -> SubmissionResult:
        page.click("button:has-text('Schedule')" if scheduled_at else "button:has-text('Publish now')")
        return SubmissionResult(url=getattr(page, "url", None), status="scheduled" if scheduled_at else "published")
