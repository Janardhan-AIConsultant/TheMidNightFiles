import pytest
from sqlalchemy import inspect, text

from backend.models import ImmutableError, StoryRevision
from backend.services.approval_service import ApprovalError, ApprovalService
from backend.services.content_path_manager import ContentPathManager
from backend.services.review_service import ReviewError, ReviewService
from backend.services.series_service import SeriesError, SeriesService
from backend.services.story_service import StoryError, StoryService, hash_text
from backend.services.summary_service import SummaryService


def full_pass(session, sid, v):
    r = ReviewService(session)
    e = r.record_editorial(sid, v, "APPROVED", coverage=1.0)
    s = r.record_safety(sid, v, "PASSED", coverage=1.0)
    return e, s


def test_no_log_tables(engine):
    names = set(inspect(engine).get_table_names())
    assert not names & {"agent_execution_logs", "application_logs"}
    for t in ["stories", "story_revisions", "story_series", "series_continuity", "images",
              "distribution_content", "publishing_queue", "publishing_history", "scheduled_tasks",
              "platform_accounts", "analytics", "content_approvals", "content_safety_reviews",
              "editorial_reviews", "humanisation_reviews", "content_calendar", "topic_history",
              "settings", "summaries"]:
        assert t in names


def test_revisions_versioning_hash_and_immutability(session, tmp_path):
    calls = []
    pm = ContentPathManager(tmp_path / "c")
    svc = StoryService(session, pm, on_new_version=lambda s, v: calls.append((s, v)))
    st = svc.create_story("Hollow")
    assert st.id == "STORY-0001" and svc.create_story("Two").id == "STORY-0002"
    r1 = svc.add_revision(st.id, "hello world", "original", "ai")
    r2 = svc.add_revision(st.id, "hello again", "humanised")
    assert (r1.version, r2.version) == (1, 2) and calls == [(st.id, 1), (st.id, 2)]
    assert r1.content_hash == hash_text("hello world") != r2.content_hash
    assert svc.get_revision(st.id).version == 2 and svc.get_revision(st.id, 1).text == "hello world"
    assert [r.version for r in svc.list_revisions(st.id)] == [1, 2]
    assert pm.read_text(r1.file_path) == "hello world"
    r1.text = "tampered"
    with pytest.raises(ImmutableError):
        session.commit()
    session.rollback()
    session.delete(session.get(StoryRevision, r1.id))
    with pytest.raises(ImmutableError):
        session.commit()
    session.rollback()
    with pytest.raises(StoryError):
        svc.add_revision(st.id, "  ")
    with pytest.raises(StoryError):
        svc.add_revision(st.id, "x", "bogus")


def test_safety_requires_full_coverage(session):
    st = StoryService(session).create_story("A")
    StoryService(session).add_revision(st.id, "body")
    r = ReviewService(session)
    for cov in (None, 0.99, 0.0):
        with pytest.raises(ReviewError):
            r.record_safety(st.id, 1, "PASSED", coverage=cov)
    with pytest.raises(ReviewError):
        r.record_safety(st.id, 1, "PASSED", [{"severity": "critical", "issue": "x"}], 1.0)
    with pytest.raises(ReviewError):
        r.record_safety(st.id, 1, "MAYBE", coverage=1.0)
    with pytest.raises(ReviewError):
        r.record_editorial(st.id, 1, "PASSED")
    with pytest.raises(ReviewError):
        r.record_safety(st.id, 9, "BLOCKED")
    assert r.record_safety(st.id, 1, "NEEDS_REVISION", coverage=0.5).status == "NEEDS_REVISION"
    assert r.record_continuity(st.id, 1, "CONSISTENT").status == "CONSISTENT"


def test_approval_gates(session):
    ss = StoryService(session)
    st = ss.create_story("A")
    ss.add_revision(st.id, "body")
    r, a = ReviewService(session), ApprovalService(session)
    with pytest.raises(ApprovalError):
        a.approve(st.id, 1, "me")
    r.record_editorial(st.id, 1, "APPROVED", coverage=1.0)
    with pytest.raises(ApprovalError):
        a.approve(st.id, 1, "me")  # no safety
    r.record_safety(st.id, 1, "BLOCKED", coverage=1.0)
    ok, reasons = a.is_publishable(st.id, 1)
    assert not ok and any("BLOCKED" in x for x in reasons)
    with pytest.raises(ApprovalError):
        a.approve(st.id, 1, "me")
    e, s = full_pass(session, st.id, 1)
    with pytest.raises(ApprovalError):
        a.approve(st.id, 1, " ")
    ok, _ = a.is_publishable(st.id, 1)
    assert not ok  # reviews pass but no human approval yet
    ap = a.approve(st.id, 1, "editor")
    assert (ap.editorial_review_id, ap.safety_review_id) == (e.id, s.id) and ap.version == 1
    assert a.is_publishable(st.id, 1) == (True, [])
    assert a.approve(st.id, 1, "editor").id == ap.id


def test_editorial_non_approved_blocks(session):
    ss = StoryService(session)
    st = ss.create_story("A")
    ss.add_revision(st.id, "body")
    r = ReviewService(session)
    r.record_editorial(st.id, 1, "NEEDS_REVISION")
    r.record_safety(st.id, 1, "PASSED", coverage=1.0)
    with pytest.raises(ApprovalError, match="NEEDS_REVISION"):
        ApprovalService(session).approve(st.id, 1, "me")


def test_new_version_invalidates_everything(session):
    ss = StoryService(session)
    st = ss.create_story("A")
    ss.add_revision(st.id, "v1")
    full_pass(session, st.id, 1)
    a = ApprovalService(session)
    ap = a.approve(st.id, 1, "me")
    ss.add_revision(st.id, "v2 edited")
    session.refresh(ap)
    assert ap.is_valid is False
    ok, reasons = a.is_publishable(st.id, 1)
    assert not ok and any("not the current" in x or "no valid" in x for x in reasons)
    with pytest.raises(ApprovalError):
        a.approve(st.id, 1, "me")  # old version can't be approved
    with pytest.raises(ApprovalError):
        a.approve(st.id, 2, "me")  # new version has no reviews
    assert ReviewService(session).latest_editorial(st.id, 1) is None
    assert a.is_publishable(st.id, 2)[0] is False
    full_pass(session, st.id, 2)
    a.approve(st.id, 2, "me")
    assert a.is_publishable(st.id, 2)[0] is True


def test_approval_bound_to_latest_reviews(session):
    ss = StoryService(session)
    st = ss.create_story("A")
    ss.add_revision(st.id, "v1")
    full_pass(session, st.id, 1)
    a = ApprovalService(session)
    a.approve(st.id, 1, "me")
    ReviewService(session).record_safety(st.id, 1, "HUMAN_REVIEW_REQUIRED", coverage=1.0)
    ok, reasons = a.is_publishable(st.id, 1)
    assert not ok and any("HUMAN_REVIEW_REQUIRED" in x for x in reasons)


def test_series_bible_versions(session):
    sv = SeriesService(session)
    s = sv.create_series("Hollow House")
    with pytest.raises(SeriesError):
        sv.create_series("Hollow House")
    b1 = sv.save_bible(s.id, {"characters": [{"name": "Ana", "age": 30}], "locations": ["attic"]})
    b2 = sv.save_bible(s.id, {"characters": [{"name": "Ana", "age": 31}]})
    assert (b1.version, b2.version) == (1, 2) and b1.content_hash != b2.content_hash
    assert sv.get_bible(s.id).version == 2 and sv.get_bible(s.id, 1).bible["characters"][0]["age"] == 30
    assert sv.relevant_context(s.id, ["characters", "nope"]) == {"characters": [{"name": "Ana", "age": 31}]}
    with pytest.raises(SeriesError):
        sv.save_bible(s.id, {"bogus": 1})
    st = StoryService(session).create_story("Ep1")
    assert sv.attach_story(st.id, s.id, 1).series_id == s.id


def test_summary_staleness(session):
    sm = SummaryService(session)
    s = sm.record("story", "STORY-0001", 1, "h1", "synopsis", "sum", "p1", "m", {"bible": "b1"})
    assert sm.get_current("story", "STORY-0001", "synopsis", "h1", {"bible": "b1"}, "p1").id == s.id
    assert sm.get_current("story", "STORY-0001", "synopsis", "h2") is None
    assert sm.get_current("story", "STORY-0001", "synopsis", "h1", {"bible": "b2"}) is None
    assert sm.get_current("story", "STORY-0001", "synopsis", "h1", prompt_version="p2") is None
    assert sm.invalidate_for_dependency("bible", "b1") == 0
    assert sm.invalidate_for_dependency("bible", "b2") == 1
    assert sm.get_current("story", "STORY-0001", "synopsis", "h1") is None
    s2 = sm.record("story", "STORY-0001", 1, "h1", "synopsis", "new", "p1", "m")
    assert sm.get_current("story", "STORY-0001", "synopsis", "h1").id == s2.id
    assert sm.invalidate_for_source("story", "STORY-0001") == 1
