"""Graph nodes. Each node is a thin adapter: load references from the business DB, call exactly one agent through the
budgeted BaseAgent path, persist results through the Wave 1 services, and return a small state update."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from backend.agents import AGENT_CLASSES, AgentFailure, ErrorKind, Usage
from backend.agents.schemas import (DistributionInput, HumanisationInput, ImageInput, PlannerInput, PublishingInput,
                                    WriterInput)
from backend.models.entities import DistributionContent
from backend.orchestration.context import WorkflowContext
from backend.orchestration.graph_state import empty_usage
from backend.orchestration.workflow_config import REVIEW_STAGES
from backend.safety import PiiUnavailable
from backend.services.approval_service import ApprovalError, ApprovalService
from backend.services.review_service import ReviewError, ReviewService
from backend.services.series_service import SeriesService
from backend.services.story_profile_service import UnsupportedStoryProfile, select_story_profile
from backend.services.story_service import StoryError

log = logging.getLogger("midnight.agent.workflow")

AGENT_IDS = {c.agent_id for c in AGENT_CLASSES}
PROSE_CATEGORIES = {"prose", "dialogue", "pacing", "repetition", "grammar", "readability", "atmosphere"}
MAX_ISSUE_SEVERITIES = ("high", "critical")


class NodeFailure(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


class StaleVersion(Exception):
    pass


class Acc:
    """Collects usage/retries for one node run."""

    def __init__(self):
        self.usage = Usage()

    def add_result(self, r) -> None:
        self.usage.add(r.usage)

    def add_usage(self, u: Usage) -> None:
        self.usage.add(u)


# --- helpers ----------------------------------------------------------------------------------------------------
def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def load_revision(ctx: WorkflowContext, story_id: str, version: int | None = None):
    try:
        with ctx.session_factory() as s:
            rev = ctx.story_service(s).get_revision(story_id, version)
            return rev.text, rev.version, rev.content_hash
    except StoryError as exc:
        raise NodeFailure("workflow", str(exc)) from exc


def latest_version(ctx: WorkflowContext, story_id: str) -> tuple[int, str]:
    with ctx.session_factory() as s:
        rev = ctx.story_service(s).get_revision(story_id)
        return rev.version, rev.content_hash


def stale_guard(ctx: WorkflowContext, state: dict) -> None:
    """A workflow may never move toward approval/publishing with a version that is no longer current."""
    ver, h = latest_version(ctx, state["story_id"])
    if ver != state.get("version") or h != state.get("content_hash"):
        raise StaleVersion(f"workflow holds v{state.get('version')} but current version is v{ver}")


def series_context(ctx: WorkflowContext, state: dict) -> dict:
    sid = state.get("series_id")
    if not sid:
        return {}
    try:
        with ctx.session_factory() as s:
            return SeriesService(s).relevant_context(sid)
    except Exception:  # no bible yet is normal for a first episode
        return {}


def redact_inbound(ctx: WorkflowContext, text):
    """Presidio-redact user-supplied text before it reaches an LLM. Fail CLOSED: a broken engine blocks the run."""
    if not text or ctx.pii is None or not ctx.settings.pii_redaction_enabled:
        return text
    try:
        clean, hits = ctx.pii.redact(str(text))
    except PiiUnavailable as exc:
        raise NodeFailure("guardrail", f"PII engine unavailable, refusing to send user text to the model: {exc}")
    if hits:
        log.warning("redacted %d PII item(s) from user input (%s)", len(hits), sorted({h.entity for h in hits}))
    return clean


def guard_publish(state, ctx: WorkflowContext) -> None:
    """Pre-publish gate over the story text AND every distribution payload. Any violation (or gate error) blocks."""
    if ctx.guard is None:
        return
    text, _, _ = load_revision(ctx, state["story_id"], state["version"])
    problems = [f"story: {v.rule}: {v.message}" for v in ctx.guard.check(text).violations]
    from sqlalchemy import select
    with ctx.session_factory() as s:
        rows = s.scalars(select(DistributionContent).where(
            DistributionContent.story_id == state["story_id"],
            DistributionContent.version == state["version"])).all()
        payloads = {r.platform: dict(r.payload) for r in rows}
    for plat, payload in payloads.items():
        for key, val in payload.items():
            chunks = val if isinstance(val, list) else [val]
            for c in chunks:
                if isinstance(c, str) and c.strip():
                    rep = ctx.guard.check(c)
                    problems += [f"{plat}.{key}: {v.rule}: {v.message}" for v in rep.violations
                                 if v.rule != "length"]
    if problems:
        raise NodeFailure("guardrail", "blocked by pre-publish guardrails: " + " | ".join(problems[:8]))


def _run(ctx, acc, agent_id, payload):
    r = ctx.agents[agent_id].run(payload)
    acc.add_result(r)
    return r.unwrap()


def _new_version(ctx, state, text: str, kind: str, author: str) -> dict:
    with ctx.session_factory() as s:
        rev = ctx.story_service(s).add_revision(state["story_id"], text, kind, author)
        return {"version": rev.version, "content_hash": rev.content_hash,
                "continuity_status": "NOT_REVIEWED", "editorial_status": "NOT_REVIEWED",
                "safety_status": "NOT_REVIEWED", "approval_status": "NOT_REVIEWED"}


def _reset_reviews(state) -> dict:
    stages = dict(state.get("stages", {}))
    for st in ("continuity", "editorial", "safety"):
        if st in stages:
            stages[st] = "pending"
    return stages


# --- nodes -------------------------------------------------------------------------------------------------------
def validate(state, ctx, acc):
    req, wtype = state["request"], state["workflow_type"]
    enabled = [s for s in (req.get("stages") or REVIEW_STAGES) if s in REVIEW_STAGES]
    if not enabled and wtype == "story_review":
        raise NodeFailure("validation", f"no valid review stages requested; choose from {REVIEW_STAGES}")
    upd: dict = {"stages_enabled": enabled if wtype == "story_review" else list(REVIEW_STAGES)}
    if wtype == "story_generation":
        try:
            profile = select_story_profile(req.get("story_type"), req.get("requested_word_count"),
                                           req.get("platform"), bool(req.get("series_mode")))
        except (UnsupportedStoryProfile, ValueError) as exc:
            raise NodeFailure("validation", str(exc)) from exc
        upd.update(profile=profile.to_dict(), series_id=req.get("series_id"))
        return upd
    sid = req.get("story_id")
    if not sid:
        raise NodeFailure("validation", "story_id is required")
    with ctx.session_factory() as s:
        svc = ctx.story_service(s)
        try:
            story = svc.get_story(sid)
            rev = svc.get_revision(sid, req.get("version"))
        except StoryError as exc:
            raise NodeFailure("validation", str(exc)) from exc
        series_id, target = story.series_id, story.target_word_count
        version, chash = rev.version, rev.content_hash
        if wtype in ("distribution", "publishing"):
            rs = ReviewService(s)
            ed, sf = rs.latest_editorial(sid, version), rs.latest_safety(sid, version)
            if ed is None or ed.status != "APPROVED" or sf is None or sf.status != "PASSED":
                raise NodeFailure("workflow", f"{wtype} requires editorial APPROVED and safety PASSED for v{version}")
        if wtype == "publishing" and version != story.current_version:
            raise StaleVersion(f"v{version} is not the current version v{story.current_version}")
    try:
        profile = select_story_profile(None, target if target and 75 <= target <= 3000 else None)
    except (UnsupportedStoryProfile, ValueError):
        profile = select_story_profile()
    upd.update(story_id=sid, version=version, content_hash=chash, series_id=series_id, profile=profile.to_dict())
    return upd


def planner(state, ctx, acc):
    req, profile = state["request"], state["profile"]
    out = _run(ctx, acc, "planner", PlannerInput(
        topic=redact_inbound(ctx, req.get("topic")), genre=req.get("genre", "horror"), story_type=profile["profile_name"],
        target_word_count=profile["target_words"], platform=req.get("platform"),
        series_mode=bool(req.get("series_mode")), planned_date=req.get("planned_date"),
        calendar_days=int(req.get("calendar_days") or 0), workflow_id=state["workflow_id"]))
    with ctx.session_factory() as s:
        story = ctx.story_service(s).create_story(
            out.working_title, out.genre, out.story_type or "standalone", profile["target_words"],
            state.get("series_id"), req.get("episode_number"),
            {"workflow_id": state["workflow_id"], "profile": profile["profile_name"]})
        sid = story.id
    return {"story_id": sid, "brief": out.model_dump(mode="json"), "synopsis": out.synopsis}


def writer(state, ctx, acc):
    out = _run(ctx, acc, "writer", WriterInput(
        brief=state["brief"], profile=state["profile"], series_context=series_context(ctx, state),
        story_id=state["story_id"], workflow_id=state["workflow_id"]))
    return _new_version(ctx, state, out.text, "original", "writer_agent")


def _humanise(state, ctx, acc, findings=None, kind="humanised", author="humanisation_agent"):
    text, ver, _ = load_revision(ctx, state["story_id"], state["version"])
    new_text, usage, _results = ctx.agents["humanisation"].humanise_story(
        text, state["profile"], state["story_id"], ver, state["workflow_id"], findings)
    acc.add_usage(usage)
    upd = _new_version(ctx, state, new_text, kind, author)
    with ctx.session_factory() as s:
        ReviewService(s).record_humanisation(state["story_id"], upd["version"], "COMPLETED", [], 1.0)
    return upd


def humanise(state, ctx, acc):
    if "humanise" not in state["stages_enabled"]:
        return {"_stage_status": "skipped"}
    return _humanise(state, ctx, acc)


def _review(kind: str, state, ctx, acc):
    if kind not in state["stages_enabled"]:
        return {"_stage_status": "skipped"}
    text, ver, chash = load_revision(ctx, state["story_id"], state["version"])
    agg, usage = ctx.agents[kind].review_story(text, state["profile"], series_context(ctx, state),
                                               state["story_id"], ver, state["workflow_id"])
    acc.add_usage(usage)
    status = agg.status
    try:
        with ctx.session_factory() as s:
            rs = ReviewService(s)
            rec = {"continuity": rs.record_continuity, "editorial": rs.record_editorial,
                   "safety": rs.record_safety}[kind]
            rec(state["story_id"], ver, status, agg.findings, agg.coverage)
    except ReviewError as exc:
        raise NodeFailure("workflow", f"review could not be recorded: {exc}") from exc
    upd: dict = {f"{kind}_status": status, "pending_findings": agg.findings}
    if kind == "safety":
        upd["safety_coverage"] = agg.coverage
    cats = {f.get("category", "other") for f in agg.findings if f.get("severity") != "low"}
    upd["revision_target"] = "humanise" if kind == "editorial" and cats and cats <= PROSE_CATEGORIES else "writer"
    return upd


def continuity(state, ctx, acc):
    return _review("continuity", state, ctx, acc)


def editorial(state, ctx, acc):
    return _review("editorial", state, ctx, acc)


def safety(state, ctx, acc):
    return _review("safety", state, ctx, acc)


def revise(state, ctx, acc):
    """One bounded automated revision: creates a NEW version; every downstream review is invalidated."""
    findings = state.get("pending_findings") or [{
        "severity": "medium", "issue": "revision requested", "location": "story", "category": "other",
        "explanation": state.get("human_reason", ""), "recommendation": "address reviewer notes"}]
    text, ver, _ = load_revision(ctx, state["story_id"], state["version"])
    if state.get("revision_target") == "humanise":
        upd = _humanise(state, ctx, acc, findings, "humanised", "revision_agent")
    else:
        out = _run(ctx, acc, "writer", WriterInput(
            brief=state.get("brief", {}), profile=state["profile"], series_context=series_context(ctx, state),
            revision_findings=findings, previous_text=text, story_id=state["story_id"],
            workflow_id=state["workflow_id"]))
        upd = _new_version(ctx, state, out.text, "original", "revision_agent")
    upd.update(revision_attempts=state.get("revision_attempts", 0) + 1, pending_findings=[], human_action="",
               stages=_reset_reviews(state))
    return upd


def human_review(state, ctx, acc):
    editorial_s, safety_s = state.get("editorial_status"), state.get("safety_status")
    exhausted = state.get("revision_attempts", 0) >= ctx.config.max_revision_attempts
    reason = ("max automated revisions reached" if exhausted else
              f"continuity={state.get('continuity_status')} editorial={editorial_s} safety={safety_s}")
    decision = interrupt({"type": "human_review", "story_id": state["story_id"], "version": state["version"],
                          "content_hash": state["content_hash"], "reason": reason,
                          "findings": state.get("pending_findings", [])[:20]})
    action = (decision or {}).get("action") if isinstance(decision, dict) else None
    if action == "revise":
        notes = str(redact_inbound(ctx, decision.get("notes")) or "human reviewer requested revision")
        finding = {"severity": "high", "issue": notes[:300], "location": "story", "category": "other",
                   "explanation": "requested by human reviewer", "recommendation": notes[:300]}
        return {"human_action": "revise", "human_reason": notes[:300], "revision_target": "writer",
                "pending_findings": (state.get("pending_findings") or []) + [finding]}
    if action == "rerun":  # the human may have saved a new version; always re-review the current one
        ver, h = latest_version(ctx, state["story_id"])
        return {"human_action": "rerun", "version": ver, "content_hash": h, "continuity_status": "NOT_REVIEWED",
                "editorial_status": "NOT_REVIEWED", "safety_status": "NOT_REVIEWED", "pending_findings": [],
                "stages": _reset_reviews(state)}
    if action == "reject":
        return {"human_action": "reject", "human_reason": str(decision.get("notes", ""))[:300]}
    raise NodeFailure("validation", "human_review decision requires action in {revise, rerun, reject}")


def images(state, ctx, acc):
    title = (state.get("brief") or {}).get("working_title", "")
    brief = state.get("brief") or {}
    if not title:
        with ctx.session_factory() as s:
            title = ctx.story_service(s).get_story(state["story_id"]).title
    synopsis = state.get("synopsis") or brief.get("synopsis") or title
    out = _run(ctx, acc, "image", ImageInput(
        synopsis=synopsis, title=title, visual_direction=brief.get("hook", ""),
        characters=brief.get("characters", []), story_id=state["story_id"], version=state["version"],
        workflow_id=state["workflow_id"]))
    return {"images": [{"kind": a.kind, "aspect_ratio": a.aspect_ratio, "reference": a.reference,
                        "alt_text": a.alt_text} for a in out.assets]}


def distribution(state, ctx, acc):
    text, ver, _ = load_revision(ctx, state["story_id"], state["version"])
    req = state["request"]
    refs = {i["kind"]: i["reference"] for i in state.get("images", []) if i.get("reference")}
    inp = DistributionInput(story_text=text, title=(state.get("brief") or {}).get("working_title", ""),
                            platforms=req.get("platforms") or ["substack", "youtube_shorts", "instagram_reels",
                                                               "reddit"],
                            image_refs=refs, story_id=state["story_id"], version=ver,
                            workflow_id=state["workflow_id"])
    out = _run(ctx, acc, "distribution", inp)
    ref = {}
    with ctx.session_factory() as s:
        from sqlalchemy import select
        for plat, payload in out.platforms.items():
            row = s.scalar(select(DistributionContent).where(
                DistributionContent.story_id == state["story_id"], DistributionContent.version == ver,
                DistributionContent.platform == plat))
            if row is None:
                s.add(DistributionContent(story_id=state["story_id"], version=ver, platform=plat, payload=payload))
            else:
                row.payload = payload
            ref[plat] = _sha(payload)
    return {"distribution_ref": ref}


def _publishing_input(state, ctx, **extra) -> PublishingInput:
    from sqlalchemy import select
    with ctx.session_factory() as s:
        rows = s.scalars(select(DistributionContent).where(
            DistributionContent.story_id == state["story_id"],
            DistributionContent.version == state["version"])).all()
        dist = {r.platform: dict(r.payload) for r in rows}
    refs = [i["reference"] for i in state.get("images", []) if i.get("reference")]
    if state["workflow_type"] == "publishing" and not state.get("images"):
        refs = refs or list(state["request"].get("asset_refs") or [])
    req = state["request"]
    return PublishingInput(story_id=state["story_id"], version=state["version"], distribution=dist,
                           asset_refs=refs, scheduled_for=req.get("scheduled_for"),
                           platform_config=req.get("platform_config") or {}, workflow_id=state["workflow_id"],
                           **extra)


def readiness(state, ctx, acc):
    guard_publish(state, ctx)
    out = _run(ctx, acc, "publishing", _publishing_input(state, ctx))
    if not out.ready:
        raise NodeFailure("publishing", "not ready for publishing: " + "; ".join(out.reasons))
    return {"publishing_status": "validated"}


def approval(state, ctx, acc):
    stale_guard(ctx, state)
    decision = interrupt({"type": "human_approval", "story_id": state["story_id"], "version": state["version"],
                          "content_hash": state["content_hash"]})
    stale_guard(ctx, state)  # the story may have changed while the workflow waited
    d = decision if isinstance(decision, dict) else {}
    if d.get("decision") != "approve":
        return {"approval_status": "REJECTED", "status": "terminated", "human_reason": str(d.get("notes", ""))[:300]}
    approver = str(d.get("approver") or "").strip()
    if not approver or approver.lower() in AGENT_IDS or approver.lower().startswith(("agent", "system", "workflow")):
        raise NodeFailure("workflow", "approval requires a named human approver; agents cannot approve")
    try:
        with ctx.session_factory() as s:
            ApprovalService(s).approve(state["story_id"], state["version"], approver, str(d.get("notes", "")))
    except ApprovalError as exc:
        raise NodeFailure("workflow", f"approval refused: {exc}") from exc
    return {"approval_status": "APPROVED", "approval_version": state["version"]}


def queue(state, ctx, acc):
    stale_guard(ctx, state)
    guard_publish(state, ctx)  # re-check at hand-off: content may have changed while waiting for approval
    out = _run(ctx, acc, "publishing", _publishing_input(state, ctx, require_approval=True, enqueue=True))
    if not out.ready:
        raise NodeFailure("publishing", "; ".join(out.reasons))
    return {"publishing_status": "queued" if ctx.queue_port is not None else "ready_for_queue"}


def terminate(state, ctx, acc):
    why = (f"editorial={state.get('editorial_status')} safety={state.get('safety_status')} "
           f"human={state.get('human_action')}")
    return {"status": "terminated", "errors": state.get("errors", []) + [
        {"kind": "workflow", "message": f"workflow terminated: {why}", "agent_id": "", "retryable": False}]}


def finish(state, ctx, acc):
    return {} if state.get("status") != "running" else {"status": "completed"}


NODES: dict[str, Callable] = {
    "validate": validate, "planner": planner, "writer": writer, "humanise": humanise, "continuity": continuity,
    "editorial": editorial, "safety": safety, "revise": revise, "human_review": human_review, "images": images,
    "distribution": distribution, "readiness": readiness, "approval": approval, "queue": queue,
    "terminate": terminate, "finish": finish}


def make_node(name: str, agent_id: str | None, ctx: WorkflowContext):
    fn = NODES[name]

    def node(state):
        wid = state["workflow_id"]
        stages = dict(state.get("stages", {}))
        stages[name] = "running"
        ctx.events.publish(wid, {"type": "stage_started", "stage": name, "agent": agent_id or ""})
        if agent_id:
            ctx.touch_agent(agent_id, active=1)
        acc, errors, status, stage_status = Acc(), list(state.get("errors", [])), state.get("status", "running"), None
        upd: dict = {}
        try:
            upd = dict(fn(state, ctx, acc) or {})
            stage_status = upd.pop("_stage_status", "completed")
            stages.update(upd.pop("stages", {}) or {})
            status = upd.pop("status", status)
            errors = upd.pop("errors", errors)
        except GraphInterrupt:
            raise
        except StaleVersion as exc:
            status, stage_status = "stale", "failed"
            errors.append({"kind": "workflow", "message": f"stale story version: {exc}", "agent_id": agent_id or "",
                           "retryable": False})
        except NodeFailure as exc:
            status, stage_status = "failed", "failed"
            errors.append({"kind": exc.kind, "message": exc.message, "agent_id": agent_id or "", "retryable": False})
        except AgentFailure as exc:
            status, stage_status = "failed", "failed"
            errors.append({**exc.error.model_dump(mode="json")})
        except Exception as exc:
            log.exception("node %s crashed", name)
            status, stage_status = "failed", "failed"
            errors.append({"kind": ErrorKind.WORKFLOW.value, "message": f"{type(exc).__name__}: {exc}",
                           "agent_id": agent_id or "", "retryable": False})
        finally:
            if agent_id:
                ctx.touch_agent(agent_id, active=-1)
        stages[name] = stage_status or "failed"
        u = acc.usage
        usage = json.loads(json.dumps(state.get("token_usage") or empty_usage()))
        usage["input_tokens"] += u.input_tokens
        usage["output_tokens"] += u.output_tokens
        usage["calls"] += u.calls
        if agent_id and u.calls:
            b = usage["by_agent"].setdefault(agent_id, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
            b["input_tokens"] += u.input_tokens
            b["output_tokens"] += u.output_tokens
            b["calls"] += u.calls
        if agent_id:
            ctx.touch_agent(agent_id, runs=1, failures=1 if stage_status == "failed" else 0,
                            input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                            last_run=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
        upd.update(stages=stages, status=status, errors=errors, token_usage=usage,
                   current_agent=agent_id or state.get("current_agent", ""),
                   retries=state.get("retries", 0) + u.retries,
                   context_budget={a: s["max_utilisation"] for a, s in ctx.budget.stats().get("agents", {}).items()})
        ctx.events.publish(wid, {"type": "stage_failed" if stage_status == "failed" else "stage_completed",
                                 "stage": name, "agent": agent_id or "", "stage_status": stage_status,
                                 "status": status, "version": upd.get("version", state.get("version")),
                                 "error": errors[-1]["message"] if stage_status == "failed" and errors else None})
        return upd

    node.__name__ = name
    return node
