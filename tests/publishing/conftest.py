import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.automation.browser_manager import BrowserManager  # noqa: E402
from backend.automation.publishing_queue import PublishingQueueService  # noqa: E402
from backend.database import init_db, make_engine  # noqa: E402
from backend.services.approval_service import ApprovalService  # noqa: E402
from backend.services.review_service import ReviewService  # noqa: E402
from backend.services.story_service import StoryService  # noqa: E402


class FakeSite:
    """Simulated destination shared across browser sessions. No network, no real publishing."""

    def __init__(self):
        self.posts = []          # titles that exist at the destination
        self.captcha = False
        self.submit_mode = "ok"  # ok | error_posted | error_not_posted | silent_not_posted
        self.submits = 0
        self.last_title = ""
        self.opened = 0


class FakeLocator:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n


class FakePage:
    def __init__(self, site):
        self.site = site
        self.url = ""
        self.screens = []

    def goto(self, url):
        self.url = url

    def locator(self, sel):
        return FakeLocator(1 if self.site.captcha and "captcha" in sel else 0)

    def fill(self, sel, text):
        if "title" in sel.lower() or "Title" in sel:
            self.site.last_title = text

    def set_input_files(self, sel, path):
        pass

    def click(self, sel):
        if "Publish now" in sel or "Post" in sel and "button" in sel:
            self.site.submits += 1
            mode = self.site.submit_mode
            if mode in ("ok", "error_posted"):
                self.site.posts.append(self.site.last_title)
            self.url = "https://example.test/p/%d" % len(self.site.posts)
            if mode.startswith("error"):
                raise RuntimeError("connection dropped after click")

    def inner_text(self, sel):
        if self.url.endswith("/posts") or "/posts" in self.url:
            return "\n".join(self.site.posts)
        if "/p/" in self.url:
            return "\n".join(self.site.posts)
        return ""

    def screenshot(self, path):
        Path(path).write_bytes(b"png")
        self.screens.append(path)


class FakeContext:
    def __init__(self, site):
        self.site = site

    def new_page(self):
        self.site.opened += 1
        return FakePage(self.site)

    def close(self):
        pass


@pytest.fixture()
def site():
    return FakeSite()


@pytest.fixture()
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def factory(engine):
    sm = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def _sf():
        s = sm()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return _sf


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, 12, 0, 0)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def svc(factory, site, tmp_path, clock):
    browser = BrowserManager(profile_root=tmp_path / "profiles", launcher=lambda d, h: FakeContext(site))
    return PublishingQueueService(session_factory=factory, browser=browser, max_retries=3,
                                  backoff_base_seconds=60, data_dir=tmp_path / "data", now=clock)


def make_publishable(factory, title="Midnight Door", approve=True):
    """Create story v1 with passing reviews and a human approval. Returns story_id."""
    with factory() as s:
        ss = StoryService(s)
        story = ss.create_story(title)
        ss.add_revision(story.id, "It was the longest night of the year.")
        rs = ReviewService(s)
        rs.record_editorial(story.id, 1, "APPROVED", coverage=1.0)
        rs.record_safety(story.id, 1, "PASSED", coverage=1.0)
        if approve:
            ApprovalService(s).approve(story.id, 1, "editor")
        return story.id


@pytest.fixture()
def story_id(factory):
    return make_publishable(factory)
