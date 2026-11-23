from __future__ import annotations

from typing import Any

from backend.publishers.base_publisher import BasePublisher, SubmissionResult


class YouTubePublisher(BasePublisher):
    platform = "youtube"
    compose_url = "https://studio.youtube.com"
    list_url = "https://studio.youtube.com/channel/UC/videos/short"
    login_url = "https://accounts.google.com"
    required_fields = ("title", "description", "video_path")
    needs_video = True

    def fill(self, page: Any, payload: dict) -> None:
        page.click("#create-icon")
        page.click("#text-item-0")
        page.set_input_files("input[type='file']", payload["video_path"])
        page.fill("#title-textarea", payload["title"])
        tags = " ".join(payload.get("hashtags") or [])
        page.fill("#description-textarea", (payload["description"] + ("\n" + tags if tags else "")).strip())
        if payload.get("thumbnail_path"):
            page.set_input_files("input#file-loader", payload["thumbnail_path"])

    def configure(self, page: Any, payload: dict, scheduled_at=None) -> None:
        kids = bool(payload.get("made_for_kids"))
        page.click("text=Yes, it is made for kids" if kids else "text=No, it is not made for kids")
        page.click("#next-button")
        visibility = "Schedule" if scheduled_at else str(payload.get("visibility", "public")).capitalize()
        page.click(f"text={visibility}")
        if scheduled_at:
            page.fill("input[aria-label='Date']", scheduled_at.strftime("%b %d, %Y"))

    def submit(self, page: Any, payload: dict, scheduled_at=None) -> SubmissionResult:
        page.click("#done-button")
        return SubmissionResult(url=getattr(page, "url", None), status="scheduled" if scheduled_at else "published")
