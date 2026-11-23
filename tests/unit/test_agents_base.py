"""BaseAgent behaviour with FakeLLMClient: retries, timeout, cache, budget, tools, tracing fail-open, prompts."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents import (AGENT_CLASSES, AgentConfig, ErrorKind, PlannerAgent, PublishingAgent, WriterAgent,
                            AnalyticsAgent, ImageAgent, ToolPermissionError)
from backend.agents.base import PromptStore
from backend.agents.reviewers import EditorialAgent, SafetyAgent
from backend.agents.tracing import safe_metadata, trace_span
from backend.services.cache_invalidation_service import CacheInvalidationService
from backend.services.cache_service import CacheService
from backend.services.context_budget_service import ContextBudgetService
from backend.services.llm_client import (FakeLLMClient, LLMModelError, LLMRateLimitError, LLMRequest, LLMResponse,
                                         build_model_registry)
from tests.workflows.support import (MODEL, OK_EDITORIAL, PLANNER, TINY, make_settings, story_text)


@pytest.fixture()
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture()
def budget(settings):
    return ContextBudgetService(build_model_registry(settings), settings)


def agent(cls, llm, budget, cache=None, model=MODEL, **cfg):
    return cls(llm=llm, budget=budget, cache=cache, tracing=False,
               config=AgentConfig(model_id=model, backoff_base_s=0, timeout_s=cfg.pop("timeout_s", 5), **cfg))


def test_every_agent_has_a_versioned_prompt_and_schemas():
    ids = [c.agent_id for c in AGENT_CLASSES]
    assert len(ids) == 10 and len(set(ids)) == 10
    store = PromptStore()
    for c in AGENT_CLASSES:
        text, h = store.load(c.agent_id, c.prompt_version)
        assert text.strip() and len(h) == 16
        assert c.input_model and c.output_model and c.context_policy != "none"


def test_valid_output_and_usage(budget):
    llm = FakeLLMClient({"planner": PLANNER})
    r = agent(PlannerAgent, llm, budget).run({"topic": "lighthouse"})
    assert r.ok and r.output.working_title == "The Knocking Below" and r.attempts == 1
    assert r.usage.calls == 1 and r.usage.input_tokens > 0 and r.context_utilisation > 0
    assert r.prompt_version == "v1" and r.model_id == MODEL


def test_invalid_input_is_a_structured_validation_error(budget):
    llm = FakeLLMClient({"planner": PLANNER})
    r = agent(PlannerAgent, llm, budget).run({"calendar_days": -5})
    assert not r.ok and r.error.kind == ErrorKind.VALIDATION and llm.calls == []


def test_bounded_retries_on_invalid_output_then_failure_is_not_approval(budget):
    llm = FakeLLMClient({"editorial": {"status": "MAYBE"}})
    r = agent(EditorialAgent, llm, budget, max_retries=2).run({"story_text": story_text(2)})
    assert not r.ok and r.output is None and r.error.kind == ErrorKind.VALIDATION
    assert len(llm.calls) == 3 and r.attempts == 3  # 1 + 2 retries, never more
    assert "rejected" in llm.calls[-1].user  # corrective feedback supplied on retry


def test_rate_limit_retried_then_succeeds(budget):
    llm = FakeLLMClient({"editorial": [LLMRateLimitError("429"), OK_EDITORIAL]})
    r = agent(EditorialAgent, llm, budget).run({"story_text": story_text(2)})
    assert r.ok and r.attempts == 2 and r.usage.retries == 1


def test_model_error_exhausts_retries(budget):
    llm = FakeLLMClient({"editorial": LLMModelError("500")})
    r = agent(EditorialAgent, llm, budget, max_retries=1).run({"story_text": story_text(2)})
    assert not r.ok and r.error.kind == ErrorKind.MODEL and r.error.retryable and len(llm.calls) == 2


def test_timeout_is_enforced(budget):
    def slow(req):
        time.sleep(1.0)
        return OK_EDITORIAL

    r = agent(EditorialAgent, FakeLLMClient({"editorial": slow}), budget, max_retries=0, timeout_s=0.1).run(
        {"story_text": story_text(2)})
    assert not r.ok and r.error.kind == ErrorKind.TIMEOUT


def test_context_overflow_blocks_call_and_is_not_retried(budget):
    llm = FakeLLMClient({"planner": PLANNER})
    r = agent(PlannerAgent, llm, budget, model=TINY).run({"topic": "x " * 5000})
    assert not r.ok and r.error.kind == ErrorKind.CONTEXT_OVERFLOW and llm.calls == []
    assert budget.stats()["total_overflows"] >= 1


def test_budget_checked_before_every_call_even_for_retries(budget):
    llm = FakeLLMClient({"editorial": {"status": "bad"}})
    before = budget.stats()["total_calls"]
    agent(EditorialAgent, llm, budget, max_retries=2).run({"story_text": story_text(2)})
    assert budget.stats()["total_calls"] == before + 1  # planned once up-front for the (identical-size) prompt


def test_cache_hit_miss_and_invalidation(settings, budget):
    cache = CacheService(settings)
    llm = FakeLLMClient({"editorial": OK_EDITORIAL})
    a = agent(EditorialAgent, llm, budget, cache)
    inp = {"story_text": story_text(2), "story_id": "STORY-0001", "version": 1}
    r1, r2 = a.run(inp), a.run(inp)
    assert r1.ok and not r1.cache_hit and r2.ok and r2.cache_hit and len(llm.calls) == 1
    assert r2.usage.calls == 0
    CacheInvalidationService(cache).on_new_version("STORY-0001", 2)  # new version drops entries >= 2 only
    assert a.run(inp).cache_hit
    CacheInvalidationService(cache).on_new_version("STORY-0001", 1)
    assert not a.run(inp).cache_hit and len(llm.calls) == 2
    # different prompt content -> different key
    assert not a.run({**inp, "story_text": story_text(3)}).cache_hit


def test_failed_runs_are_never_cached(settings, budget):
    cache = CacheService(settings)
    llm = FakeLLMClient({"editorial": [{"status": "x"}] * 3 + [OK_EDITORIAL]})
    a = agent(EditorialAgent, llm, budget, cache)
    inp = {"story_text": story_text(2)}
    assert not a.run(inp).ok
    assert a.run(inp).ok  # recomputed, not served from a cached failure


def test_writer_may_not_silently_shorten(budget):
    short = {"title": "t", "text": "too short"}
    llm = FakeLLMClient({"writer": short})
    r = agent(WriterAgent, llm, budget, max_retries=1).run(
        {"brief": {}, "profile": {"min_words": 200, "writer_output_budget": 500}})
    assert not r.ok and "minimum" in r.error.message


def test_restricted_tools(budget):
    img = agent(ImageAgent, FakeLLMClient(), budget)
    with pytest.raises(ToolPermissionError):
        img.tools.call("delete_everything")
    planner = PlannerAgent(llm=FakeLLMClient({"planner": PLANNER}), budget=budget, tracing=False,
                           config=AgentConfig(model_id=MODEL),
                           tools={"topic_history": lambda: ["a", "b"], "shell": lambda: "pwned"})
    r = planner.run({})
    assert r.ok
    with pytest.raises(ToolPermissionError):
        planner.tools.call("shell")


def test_tool_call_budget_is_bounded(budget):
    p = PlannerAgent(llm=None, budget=budget, config=AgentConfig(model_id=MODEL, max_tool_calls=2),
                     tools={"topic_history": lambda: []})
    p.tools.call("topic_history")
    p.tools.call("topic_history")
    from backend.agents import AgentFailure
    with pytest.raises(AgentFailure):
        p.tools.call("topic_history")


def test_planner_repeating_previous_topic_rejected(budget):
    llm = FakeLLMClient({"planner": PLANNER})
    r = agent(PlannerAgent, llm, budget, max_retries=0).run({"topic_history": ["the knocking below"]})
    assert not r.ok and "repeated" in r.error.message


def test_tracing_fails_open_and_metadata_is_safe(budget, monkeypatch):
    import langsmith

    def boom(*a, **k):
        raise RuntimeError("langsmith down")

    monkeypatch.setattr(langsmith, "trace", boom)
    llm = FakeLLMClient({"planner": PLANNER})
    a = PlannerAgent(llm=llm, budget=budget, config=AgentConfig(model_id=MODEL), tracing=True)
    assert a.run({}).ok  # tracing outage must not fail generation
    with trace_span("x", {"story_text": "SECRET STORY", "api_key": "k", "story_id": "S"}, enabled=False) as sp:
        assert "story_text" not in sp.meta and "api_key" not in sp.meta and sp.meta["story_id"] == "S"
    assert "text" not in safe_metadata({"text": "x"}) and len(safe_metadata({"a": "z" * 999})["a"]) == 200


def test_unexpected_crash_is_structured_not_success(budget):
    class Boom(FakeLLMClient):
        def invoke(self, request: LLMRequest) -> LLMResponse:
            raise ValueError("kaboom")

    r = agent(EditorialAgent, Boom(), budget, max_retries=0).run({"story_text": story_text(2)})
    assert not r.ok and r.error.kind == ErrorKind.WORKFLOW


def test_publishing_agent_validates_without_llm():
    cfg = AgentConfig(model_id=MODEL)
    good = {"substack": {"title": "t", "body": "b", "seo_title": "s", "seo_description": "d", "tags": ["x"]}}
    tools = {"current_version": lambda sid: 2, "is_publishable": lambda sid, v: (False, ["no valid human approval"]),
             "queue_job": lambda job: 7}
    a = PublishingAgent(config=cfg, tools=tools, tracing=False)
    base = dict(story_id="S", version=2, distribution=good, asset_refs=["a.png"])
    assert a.run(base).output.ready
    stale = a.run({**base, "version": 1}).output
    assert not stale.ready and "stale" in stale.reasons[0]
    unapproved = a.run({**base, "require_approval": True, "enqueue": True}).output
    assert not unapproved.ready and unapproved.jobs == []  # no jobs without approval
    tools["is_publishable"] = lambda sid, v: (True, [])
    ok = PublishingAgent(config=cfg, tools=tools, tracing=False).run({**base, "require_approval": True,
                                                                      "enqueue": True}).output
    assert ok.ready and ok.jobs[0]["queue_id"] == 7
    missing = a.run({**base, "distribution": {"substack": {"title": "t"}}}).output
    assert not missing.ready


def test_analytics_never_fabricates():
    r = AnalyticsAgent(config=AgentConfig(model_id=MODEL), tracing=False).run(
        {"metrics": {"substack": {"views": 100, "likes": 5, "comments": None}}})
    o = r.output
    assert o.available["substack"] == {"views": 100.0, "likes": 5.0}
    assert "comments" in o.missing["substack"] and "subscribers" in o.missing["substack"]
    assert o.engagement_rate["substack"] == 0.05
    assert AnalyticsAgent(config=AgentConfig(model_id=MODEL), tracing=False).run({"metrics": {"x": {}}}
                                                                                 ).output.engagement_rate["x"] is None
