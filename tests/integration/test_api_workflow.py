"""Workflow + publishing endpoints with fakes injected via dependency overrides."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.deps import get_publishing_service_dep, get_workflow_service_dep  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.main import create_app  # noqa: E402

API = "/api/v1"


class FakeWorkflows:
    def __init__(self):
        self.started = []
        self.items = {"wf1": {"id": "wf1", "status": "RUNNING", "story_id": "STORY-0001"}}

    def start(self, request):
        self.started.append(request)
        self.items["wf2"] = {"workflow_id": "wf2", "status": "running", "workflow_type": request["workflow_type"]}
        return "wf2"

    def get(self, workflow_id):
        return self.items.get(workflow_id)

    def list(self, **kw):
        return list(self.items.values())

    def events(self, workflow_id):
        if workflow_id not in self.items:
            raise KeyError(workflow_id)
        yield {"type": "node_started", "node": "writer"}
        yield {"type": "node_finished", "node": "writer"}

    def resume(self, workflow_id, decision):
        self.resumed = (workflow_id, decision)

    def agent_status(self):
        return [{"agent": "writer", "status": "idle"}]


class PublishingQueueError(Exception):
    pass


class FakeQueue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, story_id, version, platform, scheduled_at=None):
        if story_id == "STORY-0009":
            raise PublishingQueueError("not publishable: no valid human approval for this version")
        j = {"id": len(self.jobs) + 1, "story_id": story_id, "version": version, "platform": platform,
             "status": "PENDING"}
        self.jobs.append(j)
        return j

    def cancel(self, job_id):
        if job_id != 1:
            raise PublishingQueueError(f"unknown job {job_id}")
        return {"id": 1, "status": "CANCELLED"}

    def retry(self, job_id):
        raise PublishingQueueError("job in status PENDING cannot be retried")

    def list_jobs(self, page=1, page_size=20, status=None, platform=None):
        return {"items": self.jobs, "total": len(self.jobs), "page": page, "page_size": page_size}


@pytest.fixture()
def env(tmp_path):
    s = Settings(app_env="test", database_url=f"sqlite:///{(tmp_path / 'w.db').as_posix()}",
                 data_dir=str(tmp_path / "d"), log_dir=str(tmp_path / "l"), cache_directory=str(tmp_path / "c"),
                 langsmith_tracing=False, _env_file=None)
    app = create_app(s, enable_scheduler=False)
    wf, q = FakeWorkflows(), FakeQueue()
    app.dependency_overrides[get_workflow_service_dep] = lambda: wf
    app.dependency_overrides[get_publishing_service_dep] = lambda: q
    with TestClient(app) as c:
        yield c, wf, q


def test_workflow_lifecycle(env):
    c, wf, _ = env
    r = c.post(f"{API}/workflows", json={"workflow_type": "story_generation", "params": {"requested_word_count": 300}})
    assert r.status_code == 202 and r.json()["id"] == "wf2"
    lst = c.get(f"{API}/workflows").json()
    assert lst["total"] == 2 and lst["items"][0]["id"] == "wf1"
    assert c.get(f"{API}/workflows/wf1").json()["status"] == "RUNNING"
    assert c.get(f"{API}/workflows/nope").status_code == 404
    assert wf.started[0] == {"workflow_type": "story_generation", "requested_word_count": 300}
    assert c.post(f"{API}/workflows/wf1/resume", json={}).status_code == 422
    assert c.post(f"{API}/workflows/wf1/resume", json={"decision": "approve", "action": "rerun"}).status_code == 422
    assert c.post(f"{API}/workflows/wf1/resume", json={"decision": "approve", "approver": "Dana"}).status_code == 202
    assert wf.resumed == ("wf1", {"decision": "approve", "notes": "", "approver": "Dana"})
    assert c.post(f"{API}/workflows/wf1/resume", json={"action": "revise", "notes": "n"}).status_code == 202
    assert wf.resumed[1] == {"action": "revise", "notes": "n"}
    assert c.get(f"{API}/agents/status").json()["items"][0]["agent"] == "writer"


def test_story_actions_start_workflows(env):
    c, wf, _ = env
    sid = c.post(f"{API}/stories", json={"title": "T", "text": "body text"}).json()["id"]
    for kind in ("humanise", "continuity", "editorial", "safety"):
        assert c.post(f"{API}/stories/{sid}/{kind}").status_code == 202
    assert [r["stages"] for r in wf.started] == [["humanise"], ["continuity"], ["editorial"], ["safety"]]
    assert all(r["workflow_type"] == "story_review" and r["story_id"] == sid for r in wf.started)
    assert wf.started[0]["version"] == 1
    empty = c.post(f"{API}/stories", json={"title": "No text"}).json()["id"]
    assert c.post(f"{API}/stories/{empty}/safety").status_code == 409
    assert c.post(f"{API}/stories/STORY-8888/safety").status_code == 404


def test_sse_events(env):
    c, _, _ = env
    with c.stream("GET", f"{API}/workflows/wf1/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: node_started" in body and "event: node_finished" in body and "event: end" in body
    assert c.get(f"{API}/workflows/nope/events").status_code == 404


def test_publishing_queue_and_error_mapping(env):
    c, _, q = env
    r = c.post(f"{API}/publishing/queue", json={"story_id": "STORY-0001", "version": 1, "platform": "substack",
                                                 "scheduled_for": "2030-01-01T10:00:00+05:30"})
    assert r.status_code == 201 and r.json()["status"] == "PENDING"
    assert c.get(f"{API}/publishing/queue").json()["total"] == 1
    blocked = c.post(f"{API}/publishing/queue", json={"story_id": "STORY-0009", "version": 1, "platform": "substack"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "approval_blocked"
    assert c.post(f"{API}/publishing/queue/1/cancel").json()["status"] == "CANCELLED"
    assert c.post(f"{API}/publishing/queue/5/cancel").status_code == 404
    assert c.post(f"{API}/publishing/queue/1/retry").status_code == 409
    assert c.post(f"{API}/publishing/queue", json={"story_id": "S", "version": 1, "platform": "BAD!"}).status_code == 422
    assert c.post(f"{API}/publishing/queue", json={"story_id": "S", "version": 1, "platform": "substack",
                                                    "scheduled_for": "garbage"}).status_code == 422
