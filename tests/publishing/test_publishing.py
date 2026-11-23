import pytest

from backend.automation.browser_manager import BrowserManager, BrowserManagerError
from backend.automation.publishing_queue import PublishingQueueError
from backend.automation.publishing_validator import PublishingValidator, idempotency_key
from backend.models import PublishingHistory, PublishingQueue
from backend.services.review_service import ReviewService
from backend.services.story_service import StoryService
from tests.publishing.conftest import make_publishable


def history(factory):
    with factory() as s:
        return [(h.outcome, h.external_url) for h in s.query(PublishingHistory).order_by(PublishingHistory.id)]


def test_happy_path_publishes_and_verifies(svc, site, story_id, factory):
    job = svc.enqueue(story_id, 1, "substack")
    assert job["status"] == "PENDING"
    out = svc.process_next()
    assert out["status"] == "PUBLISHED"
    assert out["external_url"].startswith("https://example.test/p/")
    assert out["screenshot_ref"]
    assert site.submits == 1 and site.posts == ["Midnight Door"]
    assert history(factory)[-1][0] == "PUBLISHED"
    assert svc.process_next() is None


def test_enqueue_refuses_unapproved(svc, factory):
    sid = make_publishable(factory, approve=False)
    with pytest.raises(PublishingQueueError):
        svc.enqueue(sid, 1, "substack")


def test_stale_version_blocks_and_never_submits(svc, site, story_id, factory):
    svc.enqueue(story_id, 1, "substack")
    with factory() as s:  # story edited after enqueue -> v2 is current
        StoryService(s).add_revision(story_id, "Edited text.")
    out = svc.process_next()
    assert out["status"] == "BLOCKED"
    assert site.submits == 0 and site.opened == 0
    assert "version" in out["last_error"] or "approval" in out["last_error"]


def test_each_gate_blocks(svc, site, story_id, factory):
    svc.enqueue(story_id, 1, "substack")
    with factory() as s:
        ReviewService(s).record_safety(story_id, 1, "BLOCKED", findings=[{"severity": "critical", "issue": "x"}])
    out = svc.process_next()
    assert out["status"] == "BLOCKED" and "safety" in out["last_error"]
    assert site.submits == 0


def test_revoked_approval_blocks(svc, site, story_id, factory):
    from backend.services.approval_service import ApprovalService
    svc.enqueue(story_id, 1, "substack")
    with factory() as s:
        ApprovalService(s).revoke(story_id, 1)
    assert svc.process_next()["status"] == "BLOCKED"
    assert site.submits == 0


def test_series_requires_continuity(svc, site, factory):
    from backend.models import StorySeries
    with factory() as s:
        ser = StorySeries(name="S")
        s.add(ser)
        s.flush()
        sid_series = ser.id
    sid = make_publishable(factory, title="Ep1")
    with factory() as s:
        s.get(__import__("backend.models", fromlist=["Story"]).Story, sid).series_id = sid_series
    svc.enqueue(sid, 1, "substack")
    out = svc.process_next()
    assert out["status"] == "BLOCKED" and "continuity" in out["last_error"]


def test_missing_payload_and_asset_block(svc, site, factory, story_id):
    # youtube needs video etc.
    svc.enqueue(story_id, 1, "youtube")
    out = svc.process_next()
    assert out["status"] == "BLOCKED" and "payload" in out["last_error"]
    assert site.submits == 0


def test_missing_asset_file_blocks(factory):
    from backend.models import DistributionContent
    sid = make_publishable(factory)
    with factory() as s:
        s.add(DistributionContent(story_id=sid, version=1, platform="youtube",
                                  payload={"title": "t", "description": "d", "video_path": "Z:/nope.mp4"}))
        s.flush()
        job = PublishingQueue(story_id=sid, version=1, platform="youtube")
        s.add(job)
        s.flush()
        res = PublishingValidator(s).validate(job)
        assert not res.ok and any("asset" in r for r in res.reasons)


def test_idempotency_and_duplicate_prevention(svc, site, story_id):
    a = svc.enqueue(story_id, 1, "substack")
    b = svc.enqueue(story_id, 1, "substack")  # same active job
    assert a["id"] == b["id"]
    assert a["idempotency_key"] == idempotency_key(story_id, 1, "substack")
    svc.process_next()
    with pytest.raises(PublishingQueueError):
        svc.enqueue(story_id, 1, "substack")  # already published
    assert site.submits == 1


def test_duplicate_blocked_at_execution(svc, site, story_id, factory):
    a = svc.enqueue(story_id, 1, "substack")
    with factory() as s:  # simulate a published record created by another path
        s.add(PublishingHistory(story_id=story_id, version=1, platform="substack", outcome="PUBLISHED",
                                external_url="https://x"))
    out = svc.process_next()
    assert out["id"] == a["id"] and out["status"] == "BLOCKED" and "duplicate" in out["last_error"]
    assert site.submits == 0


def test_claim_is_exclusive(svc, story_id, factory):
    svc.enqueue(story_id, 1, "substack")
    with factory() as s1, factory() as s2:
        c1 = svc._claim(s1)
        c2 = svc._claim(s2)
        assert c1 is not None and c2 is None


def test_retry_backoff_and_max_retries(svc, site, story_id, clock, monkeypatch):
    svc.enqueue(story_id, 1, "substack")

    def boom():
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(svc.browser, "session", lambda p: (_ for _ in ()).throw(RuntimeError("launch failed")))
    o1 = svc.process_next()
    assert o1["status"] == "PENDING" and o1["attempts"] == 1
    assert svc.process_next() is None  # backoff: not due yet
    clock.advance(59)
    assert svc.process_next() is None
    clock.advance(2)  # 60s
    o2 = svc.process_next()
    assert o2["attempts"] == 2 and o2["status"] == "PENDING"
    clock.advance(119)
    assert svc.process_next() is None  # second backoff is 120s
    clock.advance(2)
    o3 = svc.process_next()
    assert o3["attempts"] == 3 and o3["status"] == "FAILED"
    assert site.submits == 0


def test_retry_revalidates_gates(svc, site, story_id, clock, factory, monkeypatch):
    svc.enqueue(story_id, 1, "substack")
    real = svc.browser.session
    monkeypatch.setattr(svc.browser, "session", lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    assert svc.process_next()["status"] == "PENDING"
    monkeypatch.setattr(svc.browser, "session", real)
    with factory() as s:
        ReviewService(s).record_safety(story_id, 1, "HUMAN_REVIEW_REQUIRED")
    clock.advance(61)
    out = svc.process_next()
    assert out["status"] == "BLOCKED" and site.submits == 0


def test_uncertain_submission_found_at_destination_not_resubmitted(svc, site, story_id, clock):
    site.submit_mode = "error_posted"  # click errored but post really went out
    svc.enqueue(story_id, 1, "substack")
    o1 = svc.process_next()
    assert o1["status"] == "PENDING" and site.submits == 1
    clock.advance(61)
    o2 = svc.process_next()
    assert o2["status"] == "PUBLISHED"
    assert site.submits == 1 and site.posts == ["Midnight Door"]  # no duplicate post


def test_uncertain_submission_not_found_resubmits(svc, site, story_id, clock):
    site.submit_mode = "error_not_posted"
    svc.enqueue(story_id, 1, "substack")
    assert svc.process_next()["status"] == "PENDING"
    site.submit_mode = "ok"
    clock.advance(61)
    out = svc.process_next()
    assert out["status"] == "PUBLISHED" and site.submits == 2 and site.posts == ["Midnight Door"]


def test_unverified_submission_is_never_success(svc, site, story_id, factory):
    site.submit_mode = "silent_not_posted"  # click "works" but nothing appears at destination
    svc.enqueue(story_id, 1, "substack")
    out = svc.process_next()
    assert out["status"] != "PUBLISHED"
    assert all(o != "PUBLISHED" for o, _ in history(factory))


def test_uncertain_ends_as_uncertain_after_max(svc, site, story_id, clock):
    site.submit_mode = "silent_not_posted"
    svc.enqueue(story_id, 1, "substack")
    status = None
    for _ in range(5):
        r = svc.process_next()
        if r:
            status = r["status"]
        clock.advance(10000)
    assert status == "UNCERTAIN"


def test_blocked_automation_stops_safely_no_retry(svc, site, story_id, clock):
    site.captcha = True
    svc.enqueue(story_id, 1, "substack")
    out = svc.process_next()
    assert out["status"] == "BLOCKED_AUTOMATION" and "CAPTCHA" in out["last_error"]
    assert out["manual_fallback"]
    assert site.submits == 0
    clock.advance(100000)
    assert svc.process_next() is None  # not auto-retried


def test_manual_retry_after_block(svc, site, story_id):
    site.captcha = True
    j = svc.enqueue(story_id, 1, "substack")
    svc.process_next()
    site.captcha = False
    assert svc.retry(j["id"])["status"] == "PENDING"
    assert svc.process_next()["status"] == "PUBLISHED"


def test_cancel_and_list(svc, story_id):
    j = svc.enqueue(story_id, 1, "substack")
    assert svc.cancel(j["id"])["status"] == "CANCELLED"
    assert svc.process_next() is None
    with pytest.raises(PublishingQueueError):
        svc.retry(j["id"])
    res = svc.list_jobs(1, 10, status="CANCELLED", platform="substack")
    assert res["total"] == 1 and res["items"][0]["id"] == j["id"] and res["page"] == 1
    assert svc.list_jobs(1, 10, status="PENDING")["total"] == 0


def test_scheduled_job_not_claimed_until_due(svc, story_id, clock):
    from datetime import timedelta
    svc.enqueue(story_id, 1, "substack", scheduled_at=clock() + timedelta(hours=1))
    assert svc.process_next() is None
    clock.advance(3601)
    assert svc.process_next()["status"] == "PUBLISHED"


def test_profile_dir_must_be_outside_repo():
    from backend.automation.browser_manager import PROJECT_ROOT
    with pytest.raises(BrowserManagerError):
        BrowserManager(profile_root=PROJECT_ROOT / "data" / "profiles")
