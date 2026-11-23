from __future__ import annotations

from typing import Any

from backend.publishers.base_publisher import BasePublisher, PublisherError, SubmissionResult


class RedditPublisher(BasePublisher):
    platform = "reddit"
    compose_url = "https://www.reddit.com/submit"
    list_url = "https://www.reddit.com/user/me/submitted/"
    login_url = "https://www.reddit.com/login"
    required_fields = ("subreddit", "title", "body")

    def check_fields(self, page: Any, payload: dict) -> None:
        super().check_fields(page, payload)
        if not payload.get("rules_acknowledged"):
            raise PublisherError("subreddit rules not acknowledged in payload")

    def fill(self, page: Any, payload: dict) -> None:
        page.goto(f"https://www.reddit.com/r/{payload['subreddit']}/submit")
        page.fill("textarea[name='title']", payload["title"])
        body = payload["body"]
        if payload.get("discussion_prompt"):
            body = f"{body}\n\n{payload['discussion_prompt']}"
        page.fill("div[contenteditable='true']", body)

    def submit(self, page: Any, payload: dict, scheduled_at=None) -> SubmissionResult:
        page.click("button:has-text('Post')")
        return SubmissionResult(url=getattr(page, "url", None), status="published")
