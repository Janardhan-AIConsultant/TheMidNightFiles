"""End-to-end through the HTTP API with a FakeLLMClient and a mocked browser. Never publishes for real."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import database  # noqa: E402
from backend.automation.browser_manager import BrowserManager  # noqa: E402
from backend.automation.publishing_queue import PublishingQueueService  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.services.llm_client import FakeLLMClient  # noqa: E402
from tests.publishing.conftest import FakeContext, FakeSite  # noqa: E402
from tests.workflows.support import default_responses, make_settings  # noqa: E402

API = "/api/v1"


@pytest.fixture()
def stack(tmp_path):
    settings = make_settings(tmp_path, app_env="test",
                             database_url=f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}",
                             image_generator="tests.workflows.support:gen_image")
    site = FakeSite()
    browser = BrowserManager(profile_root=tmp_path / "profiles", launcher=lambda d, h: FakeContext(site))
    queue = PublishingQueueService(browser=browser, data_dir=tmp_path / "pub", max_retries=3,
                                   session_factory=database.get_session)
    app = create_app(settings, enable_scheduler=False, llm=FakeLLMClient(default_responses()), queue=queue)
    with TestClient(app) as c:
        yield c, app, site, queue, settings
    from backend.orchestration.checkpoint_manager import close_checkpointer
    close_checkpointer(str(settings.data_path / "checkpoints.db"))


def wait(app, wid):
    return app.state.workflow.wait(wid, timeout=60)


def generate(c, app, **body):
    r = c.post(f"{API}/workflows", json={"workflow_type": "story_generation",
                                         "params": {"requested_word_count": 300}, **body})
    assert r.status_code == 202, r.text
    wid = r.json()["workflow_id"]
    return wid, wait(app, wid)


def test_full_flow_create_generate_review_approve_edit_enqueue(stack):
    c, app, site, queue, settings = stack
    draft = c.post(f"{API}/stories", json={"title": "Draft", "text": "A short draft."})
    assert draft.status_code == 201 and draft.json()["current_version"] == 1

    # story_generation through the API runs on the shared WorkflowService until the human approval interrupt
    wid, g = generate(c, app)
    assert g["status"] == "awaiting_human" and g["awaiting"]["type"] == "human_approval"
    view = c.get(f"{API}/workflows/{wid}").json()
    assert view["id"] == wid and view["kind"] == "story_generation" and view["current_stage"] == "approval"
    sid, ver = g["story_id"], g["version"]

    reviews = c.get(f"{API}/reviews", params={"story_id": sid, "valid_only": True}).json()["items"]
    assert {"editorial", "safety", "continuity"} <= {x["review_type"] for x in reviews}

    # agents used the SAME budget/cache objects the API reports on
    assert app.state.workflow.ctx.budget is app.state.context_budget
    assert app.state.workflow.ctx.cache is app.state.cache
    ctx_stats = c.get(f"{API}/context/stats").json()
    assert sum(a["calls"] for a in ctx_stats["agents"].values()) >= 5
    assert c.get(f"{API}/cache/stats").status_code == 200
    assert c.get(f"{API}/dashboard/summary").status_code == 200

    # approval of an ineligible version is refused by the single gate (409); bad resume shapes are 422
    assert c.post(f"{API}/approvals", json={"story_id": sid, "version": ver + 1, "decision": "approve"}
                  ).status_code == 409
    assert c.post(f"{API}/workflows/{wid}/resume", json={}).status_code == 422

    # edit while the workflow waits: the stale workflow must refuse to resume toward publishing (409)
    edit = c.patch(f"{API}/stories/{sid}", json={"text": "Edited text. " * 40, "revision_kind": "manual_edit"})
    assert edit.status_code == 200 and edit.json()["current_version"] == ver + 1
    assert edit.json()["review_state"]["approved"] is False
    assert c.post(f"{API}/workflows/{wid}/resume",
                  json={"decision": "approve", "approver": "Dana"}).status_code == 409
    assert c.post(f"{API}/approvals", json={"story_id": sid, "version": ver + 1, "decision": "approve",
                                            "approver": "Dana"}).status_code == 409  # no passing reviews

    # a fresh generation, approved through the resume endpoint, hands jobs to the real queue service
    wid2, g2 = generate(c, app)
    assert g2["status"] == "awaiting_human"
    sid2, ver2 = g2["story_id"], g2["version"]
    ok = c.post(f"{API}/workflows/{wid2}/resume", json={"decision": "approve", "approver": "Dana",
                                                        "notes": "ship it"})
    assert ok.status_code == 202, ok.text
    g2 = wait(app, wid2)
    assert g2["status"] == "completed" and g2["approval_status"] == "APPROVED"
    assert g2["publishing_status"] == "queued"
    story = c.get(f"{API}/stories/{sid2}").json()
    assert story["review_state"]["approved"] is True and story["review_state"]["publishable"] is True

    jobs = c.get(f"{API}/publishing/queue", params={"story_id": sid2}).json()
    assert {j["platform"] for j in jobs["items"]} == {"substack", "youtube", "instagram", "reddit"}
    assert jobs["total"] == 4 and all(j["status"] == "PENDING" and j["version"] == ver2 for j in jobs["items"])
    assert c.get(f"{API}/publishing/queue", params={"story_id": "STORY-9999"}).json()["total"] == 0
    assert site.submits == 0  # enqueueing never submits

    # editing the approved story creates a NEW immutable version and invalidates the approval
    e2 = c.patch(f"{API}/stories/{sid2}", json={"text": "A rewritten ending. " * 30, "revision_kind": "manual_edit"})
    assert e2.status_code == 200 and e2.json()["current_version"] == ver2 + 1
    assert e2.json()["review_state"]["approved"] is False
    revs = c.get(f"{API}/stories/{sid2}/revisions").json()["items"]
    assert [x["version"] for x in revs][:2] == [ver2 + 1, ver2]
    assert c.post(f"{API}/publishing/queue", json={"story_id": sid2, "version": ver2 + 1, "platform": "substack"}
                  ).status_code == 409
    assert all(a["is_valid"] is False for a in c.get(f"{API}/approvals", params={"story_id": sid2}).json()["items"])

    # the queued job for the OLD version is re-validated at execution time and blocked: nothing submitted
    for _ in range(4):
        assert queue.process_next()["status"] == "BLOCKED"
    assert site.submits == 0


def test_enqueue_via_api_and_process_with_mocked_browser(stack):
    c, app, site, queue, settings = stack
    wid, g = generate(c, app)
    assert c.post(f"{API}/workflows/WF-nope/resume", json={"decision": "approve"}).status_code == 404
    unapproved = c.post(f"{API}/publishing/queue", json={"story_id": g["story_id"], "version": g["version"],
                                                          "platform": "substack"})
    assert unapproved.status_code == 409 and unapproved.json()["error"]["code"] == "approval_blocked"
    wait(app, wid)
    assert c.post(f"{API}/workflows/{wid}/resume", json={"decision": "approve", "approver": "Dana"}
                  ).status_code in (202, 409)
    wait(app, wid)
    again = c.post(f"{API}/publishing/queue", json={"story_id": g["story_id"], "version": g["version"],
                                                    "platform": "substack"})
    assert again.status_code == 201 and again.json()["status"] == "PENDING"
    done = {}
    for _ in range(4):  # mocked browser only: FakeSite records everything, no network
        out = queue.process_next()
        done[out["platform"]] = out
    # substack needs only title/body and publishes to the FakeSite. youtube/instagram need a rendered video_path
    # (no video renderer is bundled) so they are BLOCKED; reddit refuses until subreddit rules are acknowledged.
    assert done["substack"]["status"] == "PUBLISHED" and site.submits == 1
    assert done["youtube"]["status"] == done["instagram"]["status"] == "BLOCKED"
    assert "video_path" in done["instagram"]["last_error"] and "video_path" in done["youtube"]["last_error"]
    assert done["reddit"]["status"] != "PUBLISHED"


def test_no_log_or_trace_tables_in_schema(stack):
    names = {n.lower() for n in inspect(database.get_engine()).get_table_names()}
    assert names, "schema is empty"
    banned = ("log", "trace", "span", "audit_event", "agent_run")
    assert not [n for n in names if any(b in n for b in banned)], names


def test_settings_endpoint_exposes_no_secret_values(stack):
    c, app, site, queue, settings = stack
    from pydantic import SecretStr
    app.state.settings = settings.model_copy(update={"openai_api_key": SecretStr("sk-supersecretvalue123"),
                                                     "langsmith_api_key": SecretStr("lsv2_supersecretvalue123")})
    got = c.get(f"{API}/settings")
    for secret in ("sk-supersecretvalue123", "lsv2_supersecretvalue123"):
        assert secret not in got.text
    assert got.json()["config"]["secrets"]["openai_api_key"]["configured"] is True
    put = c.put(f"{API}/settings", json={"values": {"openai_api_key": "sk-leak"}})
    assert put.status_code in (400, 403, 422) and "sk-leak" not in put.text
    assert "sk-leak" not in c.get(f"{API}/settings").text
