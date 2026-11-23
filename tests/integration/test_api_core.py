"""API integration tests against a real temp SQLite DB, real services, real cache."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import database  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.models import Analytics  # noqa: E402
from backend.services.review_service import ReviewService  # noqa: E402

API = "/api/v1"


@pytest.fixture()
def settings(tmp_path):
    return Settings(app_env="test", database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
                    data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "logs"),
                    cache_directory=str(tmp_path / "cache"), openai_api_key="sk-supersecretvalue123",
                    langsmith_api_key="lsv2_supersecretvalue123", langsmith_tracing=False,
                    cors_origins=["http://localhost:5173"], _env_file=None)


@pytest.fixture()
def client(settings):
    app = create_app(settings, enable_scheduler=False)
    with TestClient(app) as c:
        yield c


def mk_story(client, text="Once upon a midnight dreary, the house breathed.", **kw):
    r = client.post(f"{API}/stories", json={"title": "The Hollow", "text": text, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def review_pass(story_id, version, safety="PASSED", coverage=1.0):
    with database.get_session() as s:
        rs = ReviewService(s)
        rs.record_editorial(story_id, version, "APPROVED", coverage=1.0)
        rs.record_safety(story_id, version, safety, coverage=coverage)


# ------------------------------------------------------------------ envelope / cors / health
def test_error_envelope_and_404(client):
    r = client.get(f"{API}/stories/STORY-9999")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found" and "message" in err and "details" in err


def test_validation_error_envelope(client):
    r = client.post(f"{API}/stories", json={"title": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert isinstance(r.json()["error"]["details"], list)


def test_cors_from_settings(client):
    ok = client.options(f"{API}/health", headers={"Origin": "http://localhost:5173",
                                                  "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(f"{API}/health", headers={"Origin": "http://evil.example",
                                                   "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_health_and_stats(client):
    h = client.get(f"{API}/health").json()
    assert h["status"] == "ok" and h["checks"]["database"] == "ok"
    c = client.get(f"{API}/cache/stats").json()
    assert {"hits", "misses", "errors", "size_mb"} <= set(c)
    assert "agents" in client.get(f"{API}/context/stats").json()


# ------------------------------------------------------------------ stories / revisions
def test_story_crud_pagination_filter(client):
    for i in range(3):
        mk_story(client, genre="gothic" if i else "horror")
    r = client.get(f"{API}/stories", params={"page": 1, "page_size": 2}).json()
    assert r["total"] == 3 and len(r["items"]) == 2 and r["page_size"] == 2
    assert client.get(f"{API}/stories", params={"genre": "gothic"}).json()["total"] == 2
    assert client.get(f"{API}/stories", params={"q": "hollow"}).json()["total"] == 3
    assert client.get(f"{API}/stories", params={"page_size": 500}).status_code == 422
    d = client.get(f"{API}/stories/STORY-0001").json()
    assert d["current_version"] == 1 and d["current_revision"]["text"].startswith("Once")
    assert d["review_state"]["publishable"] is False


def test_edit_creates_new_version_and_invalidates(client):
    s = mk_story(client)
    sid = s["id"]
    review_pass(sid, 1)
    assert client.post(f"{API}/approvals", json={"story_id": sid, "version": 1, "decision": "approve",
                                                  "approver": "ed"}).status_code == 200
    r = client.patch(f"{API}/stories/{sid}", json={"text": "A different, longer midnight tale."})
    assert r.status_code == 200
    assert r.json()["current_version"] == 2
    revs = client.get(f"{API}/stories/{sid}/revisions").json()
    assert revs["total"] == 2 and "text" not in revs["items"][0]
    # v1 still immutable and intact
    assert client.get(f"{API}/stories/{sid}/revisions/1").json()["text"].startswith("Once")
    # approval for v1 invalidated by new version
    assert client.get(f"{API}/approvals", params={"story_id": sid, "valid_only": True}).json()["total"] == 0
    # approving stale v1 is blocked by the service
    r = client.post(f"{API}/approvals", json={"story_id": sid, "version": 1, "decision": "approve"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_blocked"


def test_metadata_patch_does_not_version(client):
    sid = mk_story(client)["id"]
    r = client.patch(f"{API}/stories/{sid}", json={"title": "Renamed", "metadata": {"k": 1}}).json()
    assert r["title"] == "Renamed" and r["current_version"] == 1 and r["metadata"] == {"k": 1}


def test_new_revision_endpoint_and_invalid_kind(client):
    sid = mk_story(client)["id"]
    assert client.post(f"{API}/stories/{sid}/revisions", json={"text": "v2", "kind": "humanised"}).json()["version"] == 2
    assert client.post(f"{API}/stories/{sid}/revisions", json={"text": "v3", "kind": "bogus"}).status_code == 422
    assert client.post(f"{API}/stories/STORY-4040/revisions", json={"text": "x"}).status_code == 404


def test_story_profiles(client):
    r = client.get(f"{API}/story-profiles").json()
    assert r["total"] >= 1 and r["selected"] is None
    sel = client.get(f"{API}/story-profiles", params={"word_count": 1500}).json()["selected"]
    assert sel["target_words"] == 1500
    assert client.get(f"{API}/story-profiles", params={"story_type": "nonsense"}).status_code == 422


# ------------------------------------------------------------------ approvals / reviews / safety
def test_approval_gate_enforced_only_by_service(client):
    sid = mk_story(client)["id"]
    r = client.post(f"{API}/approvals", json={"story_id": sid, "version": 1, "decision": "approve"})
    assert r.status_code == 409 and r.json()["error"]["details"]["reasons"]
    pend = client.get(f"{API}/approvals/pending").json()
    assert pend["total"] == 1 and pend["items"][0]["safety_status"] is None
    review_pass(sid, 1, safety="NEEDS_REVISION", coverage=0.5)
    assert client.post(f"{API}/approvals", json={"story_id": sid, "version": 1,
                                                  "decision": "approve"}).status_code == 409
    review_pass(sid, 1)
    ok = client.post(f"{API}/approvals", json={"story_id": sid, "version": 1, "decision": "approve", "notes": "n"})
    assert ok.status_code == 200 and ok.json()["approval"]["is_valid"] is True
    assert client.get(f"{API}/approvals/pending").json()["total"] == 0
    assert client.get(f"{API}/stories/{sid}").json()["review_state"]["publishable"] is True
    rej = client.post(f"{API}/approvals", json={"story_id": sid, "version": 1, "decision": "reject"}).json()
    assert rej["revoked_approvals"] == 1
    assert client.get(f"{API}/stories/{sid}").json()["review_state"]["publishable"] is False
    assert client.post(f"{API}/approvals", json={"story_id": "STORY-7777", "version": 1,
                                                  "decision": "approve"}).status_code == 404
    assert client.post(f"{API}/approvals", json={"story_id": sid, "version": 1,
                                                  "decision": "maybe"}).status_code == 422


def test_reviews_and_safety_listing(client):
    sid = mk_story(client)["id"]
    review_pass(sid, 1)
    assert client.get(f"{API}/reviews", params={"story_id": sid}).json()["total"] == 2
    assert client.get(f"{API}/reviews", params={"story_id": sid, "review_type": "safety"}).json()["total"] == 1
    sf = client.get(f"{API}/safety/reviews", params={"status": "PASSED"}).json()
    assert sf["total"] == 1 and sf["items"][0]["coverage"] == 1.0
    assert client.get(f"{API}/reviews", params={"review_type": "bad"}).status_code == 422


# ------------------------------------------------------------------ calendar / distribution
def test_calendar_create_list_reschedule(client):
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    c = client.post(f"{API}/calendar", json={"planned_date": when, "topic": "Lighthouse"})
    assert c.status_code == 201
    cid = c.json()["id"]
    new = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    p = client.patch(f"{API}/calendar/{cid}", json={"planned_date": new})
    assert p.status_code == 200 and p.json()["planned_date"].startswith(new[:10])
    assert client.get(f"{API}/calendar", params={"status": "PLANNED"}).json()["total"] == 1
    assert client.patch(f"{API}/calendar/999", json={"topic": "x"}).status_code == 404
    assert client.post(f"{API}/calendar", json={"planned_date": when, "topic": "x",
                                                 "story_id": "STORY-1234"}).status_code == 404


def test_distribution_put_get(client):
    sid = mk_story(client)["id"]
    assert client.get(f"{API}/distribution/{sid}/substack").status_code == 404
    r = client.put(f"{API}/distribution/{sid}/substack", json={"payload": {"title": "T"}})
    assert r.status_code == 200 and r.json()["version"] == 1
    client.put(f"{API}/distribution/{sid}/substack", json={"payload": {"title": "T2"}})
    assert client.get(f"{API}/distribution/{sid}/substack").json()["payload"] == {"title": "T2"}
    assert client.put(f"{API}/distribution/{sid}/BAD..", json={"payload": {}}).status_code in (404, 422)


# ------------------------------------------------------------------ dashboard / analytics
def test_dashboard_reflects_real_data(client):
    empty = client.get(f"{API}/dashboard/summary").json()
    assert empty["stories"]["total"] == 0 and empty["approvals"]["awaiting_approval"] == 0
    mk_story(client)
    d = client.get(f"{API}/dashboard/summary").json()
    assert d["stories"]["total"] == 1 and d["stories"]["by_status"] == {"DRAFT": 1}
    assert d["approvals"]["awaiting_approval"] == 1
    assert "hits" in d["cache"] and "agents" in d["context"]


def test_analytics_never_fabricates(client):
    sid = mk_story(client)["id"]
    s = client.get(f"{API}/analytics/summary").json()
    assert s["status"] == "unavailable" and s["metrics"] == {}
    st = client.get(f"{API}/analytics/stories").json()
    assert st["items"][0]["metrics"] is None and st["items"][0]["status_detail"] == "unavailable"
    with database.get_session() as db:
        db.add(Analytics(story_id=sid, platform="substack", metric="views", value=None))
    s = client.get(f"{API}/analytics/summary").json()
    assert s["metrics"]["views"]["total"] is None
    with database.get_session() as db:
        db.add(Analytics(story_id=sid, platform="substack", metric="views", value=12.0))
    assert client.get(f"{API}/analytics/summary").json()["metrics"]["views"]["total"] == 12.0


# ------------------------------------------------------------------ settings / logs
def test_settings_masked_and_editable(client):
    raw = client.get(f"{API}/settings").text
    assert "supersecretvalue" not in raw and "sk-" not in raw and "lsv2_" not in raw
    cfg = json.loads(raw)
    assert cfg["config"]["secrets"]["openai_api_key"] == {"configured": True, "value": "********"}
    r = client.put(f"{API}/settings", json={"values": {"scheduler.calendar_hour": 3}})
    assert r.status_code == 200 and r.json()["operator"]["scheduler.calendar_hour"] == 3
    for bad in ({"openai_api_key": "x"}, {"scheduler.calendar_hour": 99}, {"scheduler.enabled": "yes"}):
        assert client.put(f"{API}/settings", json={"values": bad}).status_code == 422
    assert "x" not in client.get(f"{API}/settings").json()["config"]["secrets"]["openai_api_key"]["value"]


def test_logs_whitelist_and_filter(client, settings):
    import logging
    logging.getLogger("midnight.app").info("hello info")
    logging.getLogger("midnight.app").error("boom token=abc12345secret")
    for h in logging.getLogger("midnight.app").handlers + logging.getLogger("midnight").handlers:
        h.flush()
    r = client.get(f"{API}/logs", params={"channel": "app", "level": "ERROR"}).json()
    assert r["channel"] == "app"
    assert all(i["severity"] in ("ERROR", "CRITICAL") for i in r["items"])
    assert "abc12345secret" not in json.dumps(r)
    for ch in ("../../etc/passwd", "config", "..%2f..%2fsettings"):
        assert client.get(f"{API}/logs", params={"channel": ch}).status_code == 422
    assert client.get(f"{API}/logs", params={"channel": "agent", "limit": 5000}).status_code == 422
    assert client.get(f"{API}/logs", params={"channel": "scheduler"}).json()["items"] == []


def test_workflow_and_publishing_503_when_modules_missing(client, monkeypatch):
    # Hide the optional modules so the lazy imports fail -> clear 503 envelope.
    client.app.state.workflow = client.app.state.publishing_queue = None  # no shared runtime instances
    for mod in ("backend.orchestration.workflow_service", "backend.automation.publishing_queue"):
        monkeypatch.setitem(sys.modules, mod, None)
    for url in ("/workflows", "/agents/status", "/publishing/queue"):
        r = client.get(API + url)
        assert r.status_code == 503 and r.json()["error"]["code"] == "service_unavailable", url
    sid = mk_story(client)["id"]
    assert client.post(f"{API}/stories/{sid}/safety").status_code == 503
