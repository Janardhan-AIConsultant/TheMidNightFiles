"""Publishing (validation + queue preparation) and Analytics agents. Both are deterministic: no LLM, no browser."""
from __future__ import annotations

from datetime import datetime

from backend.agents.base import AgentError, AgentFailure, BaseAgent, ErrorKind
from backend.agents.schemas import (REQUIRED_FIELDS, AnalyticsInput, AnalyticsOutput, PublishingInput,
                                    PublishingOutput)


class PublishingAgent(BaseAgent):
    """Validates and prepares jobs. A separate Playwright worker performs browser interaction."""
    agent_id = "publishing"
    input_model = PublishingInput
    output_model = PublishingOutput
    cache_namespace = None  # publishing state is never cached
    uses_llm = False
    allowed_tools = frozenset({"is_publishable", "current_version", "queue_job"})
    context_policy = "validated queue services only"

    def execute(self, inp: PublishingInput) -> PublishingOutput:
        reasons: list[str] = []
        if not self.tools.has("current_version"):
            raise AgentFailure(AgentError(kind=ErrorKind.TOOL, message="current_version tool required",
                                          agent_id=self.agent_id))
        cur = self.tools.call("current_version", inp.story_id)
        if cur != inp.version:
            reasons.append(f"stale story version: workflow has v{inp.version}, current is v{cur}")
        if not inp.distribution:
            reasons.append("no distribution payloads")
        for plat, payload in inp.distribution.items():
            if plat not in REQUIRED_FIELDS:
                reasons.append(f"unknown platform {plat}")
                continue
            missing = [f for f in REQUIRED_FIELDS[plat] if payload.get(f) in (None, "", [], {})]
            if missing:
                reasons.append(f"{plat}: missing {missing}")
            if inp.platform_config and not inp.platform_config.get(plat, False):
                reasons.append(f"{plat}: publishing not configured/enabled")
        if not inp.asset_refs:
            reasons.append("no validated image assets")
        if inp.scheduled_for:
            try:
                datetime.fromisoformat(inp.scheduled_for)
            except ValueError:
                reasons.append("invalid schedule timestamp")
        if inp.require_approval:
            if not self.tools.has("is_publishable"):
                raise AgentFailure(AgentError(kind=ErrorKind.TOOL, message="is_publishable tool required",
                                              agent_id=self.agent_id))
            ok, why = self.tools.call("is_publishable", inp.story_id, inp.version)
            if not ok:
                reasons += list(why)
        ready = not reasons
        jobs: list[dict] = []
        if ready and inp.enqueue:
            for plat in inp.distribution:
                job = {"story_id": inp.story_id, "version": inp.version, "platform": plat,
                       "scheduled_for": inp.scheduled_for}
                if self.tools.has("queue_job"):
                    job["queue_id"] = self.tools.call("queue_job", job)
                jobs.append(job)
        return PublishingOutput(ready=ready, reasons=reasons, jobs=jobs)


class AnalyticsAgent(BaseAgent):
    agent_id = "analytics"
    input_model = AnalyticsInput
    output_model = AnalyticsOutput
    cache_namespace = None
    uses_llm = False
    allowed_tools = frozenset({"metrics"})
    context_policy = "permitted metrics only; unavailable metrics are reported, never fabricated"

    def execute(self, inp: AnalyticsInput) -> AnalyticsOutput:
        available, missing, eng = {}, {}, {}
        for plat, m in inp.metrics.items():
            have = {k: float(v) for k, v in m.items() if v is not None}
            available[plat] = have
            missing[plat] = [k for k in inp.expected if k not in have]
            views = have.get("views") or have.get("reads")
            inter = [have.get(k) for k in ("likes", "comments", "shares")]
            eng[plat] = (round(sum(x for x in inter if x) / views, 4)
                         if views and any(x is not None for x in inter) else None)
        return AnalyticsOutput(available=available, missing=missing, engagement_rate=eng)
