"""Workflow tests: routing, bounded loops, interrupt/resume, checkpoint recovery, stale versions, safety gating."""
from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.checkpoint_manager import close_checkpointer
from backend.orchestration.workflow_service import StaleVersionError, WorkflowStateError, WorkflowNotFound
from backend.services.approval_service import ApprovalService
from backend.services.llm_client import FakeLLMClient
from backend.services.llm_client import LLMModelError
from tests.workflows.support import (Env, MID, OK_EDITORIAL, OK_SAFETY, TINY, default_responses, finding, story_text)

APPROVE = {"decision": "approve", "approver": "editor.jane"}


def llm_with(**over) -> FakeLLMClient:
    r = default_responses()
    r.update(over)
    return FakeLLMClient(r)


def stage(g, name):
    return next(s["status"] for s in g["stages"] if s["name"] == name)


def test_happy_path_interrupts_for_approval_then_completes(env):
    wid = env.run()
    g = env.service.get(wid)
    assert g["status"] == "awaiting_human" and g["awaiting"]["type"] == "human_approval"
    assert stage(g, "approval") == "awaiting_human" and stage(g, "queue") == "pending"
    sid, ver = g["story_id"], g["version"]
    assert [k for _, k in env.versions(sid)] == ["original", "humanised"] and ver == 2
    with env.session_factory() as s:
        assert ApprovalService(s).is_publishable(sid, ver)[0] is False  # nothing is approved before a human acts
    env.service.resume(wid, APPROVE)
    g = env.service.get(wid)
    assert g["status"] == "completed" and g["approval_status"] == "APPROVED"
    assert g["publishing_status"] == "ready_for_queue"
    with env.session_factory() as s:
        assert ApprovalService(s).is_publishable(sid, ver)[0] is True
    assert g["token_usage"]["calls"] >= 8 and set(g["token_usage"]["by_agent"]) >= {"planner", "writer", "safety"}
    assert g["errors"] == [] and g["thread_id"].startswith("thread-")
    # state holds references/hashes, never story text
    snap = env.service._graph("story_generation").get_state(env.service._cfg(env.service._row(wid)))
    assert "text" not in snap.values and all(len(str(v)) < 5000 for v in snap.values.values())


def test_agent_cannot_approve_itself(env):
    wid = env.run()
    env.service.resume(wid, {"decision": "approve", "approver": "safety"})
    g = env.service.get(wid)
    assert g["status"] == "failed" and g["approval_status"] != "APPROVED"
    with env.session_factory() as s:
        assert ApprovalService(s).valid_approval(g["story_id"], g["version"]) is None


def test_human_rejects_at_approval(env):
    wid = env.run()
    env.service.resume(wid, {"decision": "reject", "notes": "no"})
    g = env.service.get(wid)
    assert g["status"] == "terminated" and g["approval_status"] == "REJECTED"


def test_resume_when_not_waiting_is_an_error(env):
    wid = env.run()
    env.service.resume(wid, APPROVE)
    with pytest.raises(WorkflowStateError):
        env.service.resume(wid, APPROVE)
    with pytest.raises(WorkflowNotFound):
        env.service.get("WF-nope")


def test_editorial_needs_revision_routes_to_writer_then_fresh_review(tmp_path):
    llm = llm_with(editorial=[{"status": "NEEDS_REVISION", "findings": [finding(category="plot")],
                               "reviewed_complete": True}, OK_EDITORIAL])
    env = Env(tmp_path, llm)
    wid = env.run()
    g = env.service.get(wid)
    assert g["status"] == "awaiting_human" and g["revision_attempts"] == 1
    assert [k for _, k in env.versions(g["story_id"])] == ["original", "humanised", "original"]
    assert len(llm.calls_for("writer")) == 2 and len(llm.calls_for("humanisation")) == 1
    assert len(llm.calls_for("continuity")) == 2 and len(llm.calls_for("editorial")) == 2  # full fresh review
    assert g["version"] == 3
    close_checkpointer(env.ckpt)


def test_prose_findings_route_to_humanisation_revision(tmp_path):
    llm = llm_with(editorial=[{"status": "NEEDS_REVISION", "findings": [finding(category="dialogue")],
                               "reviewed_complete": True}, OK_EDITORIAL])
    env = Env(tmp_path, llm)
    g = env.service.get(env.run())
    assert len(llm.calls_for("humanisation")) == 2 and len(llm.calls_for("writer")) == 1
    assert [k for _, k in env.versions(g["story_id"])][-1] == "humanised"
    close_checkpointer(env.ckpt)


def test_revision_loop_is_bounded_then_human_review(tmp_path):
    llm = llm_with(editorial={"status": "NEEDS_REVISION", "findings": [finding(category="plot")],
                              "reviewed_complete": True})
    env = Env(tmp_path, llm, max_revisions=3)
    wid = env.run()
    g = env.service.get(wid)
    assert g["status"] == "awaiting_human" and g["awaiting"]["type"] == "human_review"
    assert "max automated revisions" in g["awaiting"]["reason"]
    assert g["revision_attempts"] == 3 and len(llm.calls_for("writer")) == 4  # initial + exactly 3 revisions
    assert len(llm.calls_for("safety")) == 0  # never reaches safety / publication
    env.service.resume(wid, {"action": "reject", "notes": "give up"})
    assert env.service.get(wid)["status"] == "terminated"
    close_checkpointer(env.ckpt)


def test_editorial_rejected_and_safety_blocked_terminate(tmp_path):
    env = Env(tmp_path, llm_with(editorial={"status": "REJECTED", "findings": [], "reviewed_complete": True}))
    g = env.service.get(env.run())
    assert g["status"] == "terminated" and stage(g, "safety") == "pending" and stage(g, "images") == "pending"
    close_checkpointer(env.ckpt)
    (tmp_path / "b").mkdir()
    env2 = Env(tmp_path / "b", llm_with(safety={"status": "BLOCKED", "findings": [finding("critical", "safety")],
                                                  "reviewed_complete": True}))
    g = env2.service.get(env2.run())
    assert g["status"] == "terminated" and g["safety_status"] == "BLOCKED" and stage(g, "images") == "pending"
    close_checkpointer(env2.ckpt)


def test_safety_incomplete_coverage_never_passes(tmp_path):
    env = Env(tmp_path, llm_with(safety={"status": "PASSED", "findings": [], "reviewed_complete": False}))
    wid = env.run()
    g = env.service.get(wid)
    assert g["safety_status"] == "HUMAN_REVIEW_REQUIRED" and g["status"] == "awaiting_human"
    assert g["awaiting"]["type"] == "human_review" and stage(g, "images") == "pending"
    with env.session_factory() as s:
        assert env.ctx.story_service(s) and ApprovalService(s).is_publishable(g["story_id"], g["version"])[0] is False
    close_checkpointer(env.ckpt)


def test_safety_critical_finding_overrides_model_passed(tmp_path):
    env = Env(tmp_path, llm_with(safety={"status": "PASSED", "findings": [finding("critical", "safety")],
                                         "reviewed_complete": True}))
    g = env.service.get(env.run())
    assert g["safety_status"] == "BLOCKED" and g["status"] == "terminated"
    close_checkpointer(env.ckpt)


def _seed_long_story(env, paragraphs=90):
    with env.session_factory() as s:
        st = env.story_service(s).create_story("Long one")
        env.story_service(s).add_revision(st.id, story_text(paragraphs, "long"), "original", "x")
    return st.id


def test_safety_reviews_every_section_of_a_long_story(tmp_path):
    import json
    env = Env(tmp_path, model=MID)  # small context forces multi-section review
    sid = _seed_long_story(env)
    g = env.service.get(env.service.start({"workflow_type": "story_review", "story_id": sid, "stages": ["safety"]}))
    calls = env.llm.calls_for("safety")
    assert len(calls) >= 3
    covered = " ".join(json.loads(c.user)["story_text"] for c in calls)
    assert covered.count("Part ") == 90  # every paragraph reached the safety reviewer exactly once
    assert g["status"] == "completed" and g["safety_status"] == "PASSED"
    with env.session_factory() as s:
        from backend.services.review_service import ReviewService
        assert ReviewService(s).latest_safety(sid, 1).coverage == 1.0
    close_checkpointer(env.ckpt)


def test_safety_failed_section_blocks_passed_and_escalates(tmp_path):
    llm = llm_with(safety=[OK_SAFETY, LLMModelError("boom")])
    env = Env(tmp_path, llm, model=MID)
    sid = _seed_long_story(env)
    g = env.service.get(env.service.start({"workflow_type": "story_review", "story_id": sid, "stages": ["safety"]}))
    assert g["safety_status"] == "HUMAN_REVIEW_REQUIRED" and g["status"] == "awaiting_human"
    with env.session_factory() as s:
        from backend.services.review_service import ReviewService
        rec = ReviewService(s).latest_safety(sid, 1)
        assert rec.status == "HUMAN_REVIEW_REQUIRED" and rec.coverage < 1.0
        assert ApprovalService(s).is_publishable(sid, 1)[0] is False
    close_checkpointer(env.ckpt)


def test_context_overflow_fails_workflow_without_approval(tmp_path):
    env = Env(tmp_path, llm_with(), model=TINY)
    env.llm.set("planner", None)  # would raise if called
    wid = env.run({"topic": "x " * 6000})
    g = env.service.get(wid)
    assert g["status"] == "failed" and g["errors"][0]["kind"] == "context_overflow"
    assert env.llm.calls_for("planner") == []  # blocked before any model call
    assert g["approval_status"] != "APPROVED"
    close_checkpointer(env.ckpt)


def test_stale_version_cannot_resume_into_publishing(env):
    wid = env.run()
    g = env.service.get(wid)
    with env.session_factory() as s:
        env.story_service(s).add_revision(g["story_id"], story_text(3, "edited"), "final", "human")
    with pytest.raises(StaleVersionError):
        env.service.resume(wid, APPROVE)
    g2 = env.service.get(wid)
    assert g2["status"] == "stale"
    with env.session_factory() as s:
        assert ApprovalService(s).valid_approval(g["story_id"], g["version"]) is None


def test_node_level_stale_guard_when_version_changes_after_interrupt(env, monkeypatch):
    wid = env.run()
    g = env.service.get(wid)
    import backend.orchestration.workflow_service as ws
    monkeypatch.setattr(ws, "latest_version", lambda ctx, sid: (g["version"], g["awaiting"]["content_hash"]))
    with env.session_factory() as s:  # change lands after the service-level check passed
        env.story_service(s).add_revision(g["story_id"], story_text(3, "late"), "final", "human")
    env.service.resume(wid, APPROVE)
    g2 = env.service.get(wid)
    assert g2["status"] == "stale" and g2["approval_status"] != "APPROVED"


def test_human_review_rerun_after_human_edit(tmp_path):
    llm = llm_with(editorial=[{"status": "HUMAN_REVIEW_REQUIRED", "findings": [], "reviewed_complete": True},
                              OK_EDITORIAL])
    env = Env(tmp_path, llm)
    wid = env.run()
    g = env.service.get(wid)
    assert g["awaiting"]["type"] == "human_review"
    with env.session_factory() as s:
        env.story_service(s).add_revision(g["story_id"], story_text(5, "human"), "final", "editor.jane")
    env.service.resume(wid, {"action": "rerun"})
    g = env.service.get(wid)
    assert g["awaiting"]["type"] == "human_approval" and g["version"] == 3
    close_checkpointer(env.ckpt)


def test_checkpoint_survives_application_restart(tmp_path):
    env = Env(tmp_path)
    wid = env.run()
    sid = env.service.get(wid)["story_id"]
    close_checkpointer(env.ckpt)                # simulate process exit
    llm2 = llm_with()
    svc2 = env.new_service(llm2)                # brand-new service, context, graphs; same checkpoints.db
    assert svc2.get(wid)["status"] == "awaiting_human"
    svc2.resume(wid, APPROVE)
    g = svc2.get(wid)
    assert g["status"] == "completed" and g["story_id"] == sid
    assert llm2.calls == []  # nothing was regenerated after restart
    close_checkpointer(env.ckpt)


def test_crash_mid_run_resumes_from_last_checkpoint(tmp_path):
    crash = {"on": True}

    def dist(req):
        if crash["on"]:
            raise KeyboardInterrupt("simulated crash")
        return __import__("tests.workflows.support", fromlist=["DIST"]).DIST

    llm = llm_with(distribution=dist)
    env = Env(tmp_path, llm)
    wid = env.run()
    assert env.service.get(wid)["status"] == "interrupted"
    before = {k: len(llm.calls_for(k)) for k in ("planner", "writer", "safety")}
    crash["on"] = False
    assert env.service.recover_interrupted() == [wid]
    assert env.service.get(wid)["status"] == "awaiting_human"
    assert {k: len(llm.calls_for(k)) for k in before} == before  # earlier stages not re-run
    close_checkpointer(env.ckpt)


def test_cache_hit_on_repeated_workflow_and_invalidation_on_new_version(tmp_path):
    llm = llm_with()
    env = Env(tmp_path, llm)
    wid1 = env.run({"topic": "same"})
    n1 = len(llm.calls)
    wid2 = env.run({"topic": "same"})
    assert env.service.get(wid2)["status"] == "awaiting_human"
    assert len(llm.calls) < 2 * n1  # planner (story-independent) served from cache
    assert env.cache.stats()["hits"] >= 1
    close_checkpointer(env.ckpt)


def test_review_workflow_runs_selected_stages_only(env):
    wid = env.run()
    sid = env.service.get(wid)["story_id"]
    before = len(env.llm.calls_for("safety"))
    w2 = env.service.start({"workflow_type": "story_review", "story_id": sid, "stages": ["safety"]})
    g = env.service.get(w2)
    assert g["status"] == "completed" and g["safety_status"] == "PASSED"
    assert stage(g, "continuity") == "pending" and len(env.llm.calls_for("safety")) >= before


def test_distribution_requires_reviewed_story(env):
    with env.session_factory() as s:
        st = env.story_service(s).create_story("t")
        env.story_service(s).add_revision(st.id, story_text(2), "original", "x")
    w = env.service.start({"workflow_type": "distribution", "story_id": st.id})
    g = env.service.get(w)
    assert g["status"] == "failed" and "APPROVED" in g["errors"][0]["message"]


def test_invalid_story_profile_fails_validation(env):
    g = env.service.get(env.run({"requested_word_count": 999999}))
    assert g["status"] == "failed" and g["errors"][0]["kind"] == "validation"


def test_api_surface_shapes_pagination_events_and_agent_status(env):
    wid = env.run()
    g = env.service.get(wid)
    for k in ("workflow_id", "thread_id", "story_id", "version", "status", "current_agent", "stages", "token_usage",
              "errors", "retries"):
        assert k in g
    assert all(set(s) == {"name", "status"} for s in g["stages"])
    env.run()
    lst = env.service.list(1, 1)
    assert lst["total"] == 2 and lst["page_size"] == 1 and len(lst["items"]) == 1 and lst["page"] == 1
    assert len(env.service.list(2, 1)["items"]) == 1

    async def collect():
        return [e async for e in env.service.events(wid, poll_interval=0.01, stop_when_idle=True)]

    evs = asyncio.run(collect())
    types = [e["type"] for e in evs]
    assert types[0] == "workflow_started" and "stage_completed" in types and types[-1] == "workflow_status"
    assert evs[-1]["status"] == "awaiting_human" and [e["seq"] for e in evs] == sorted(e["seq"] for e in evs)
    assert all("story_text" not in e and "text" not in e for e in evs)
    ag = env.service.agent_status()
    assert len(ag) == 10 and {a["agent_id"] for a in ag} >= {"planner", "writer", "safety", "publishing"}
    assert next(a for a in ag if a["agent_id"] == "writer")["runs"] >= 1


def test_background_thread_mode(tmp_path):
    env = Env(tmp_path, inline=False)
    wid = env.run()
    g = env.service.wait(wid, timeout=30)
    assert g["status"] == "awaiting_human"
    env.service.resume(wid, APPROVE)
    assert env.service.wait(wid, timeout=30)["status"] == "completed"
    close_checkpointer(env.ckpt)
