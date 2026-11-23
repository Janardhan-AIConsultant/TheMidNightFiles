from backend.publishers.base_publisher import (AutomationBlocked, BasePublisher, PublisherError,  # noqa: F401
                                               SubmissionResult, UncertainSubmission)
from backend.publishers.instagram_publisher import InstagramPublisher
from backend.publishers.reddit_publisher import RedditPublisher
from backend.publishers.substack_publisher import SubstackPublisher
from backend.publishers.youtube_publisher import YouTubePublisher

PUBLISHERS = {"substack": SubstackPublisher, "youtube": YouTubePublisher,
              "instagram": InstagramPublisher, "reddit": RedditPublisher}


def get_publisher(platform: str) -> BasePublisher:
    try:
        return PUBLISHERS[platform]()
    except KeyError:
        raise ValueError(f"unsupported platform {platform!r}") from None
