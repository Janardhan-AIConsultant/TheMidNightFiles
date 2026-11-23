"""Reviewer aggregation, coverage gating, chunked humanisation, distribution validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents import AgentConfig, DistributionAgent, HumanisationAgent
from backend.agents.base import AgentFailure
from backend.agents.reviewers import ContinuityAgent, EditorialAgent, SafetyAgent
from backend.services.context_budget_service import ContextBudgetService
from backend.services.llm_client import FakeLLMClient, LLMModelError, build_model_registry
from tests.workflows.support import (DIST, MID, MODEL, OK_CONTINUITY, OK_EDITORIAL, OK_SAFETY, finding,
                                     make_settings, story_text)


@pytest.fixture()
def budget(tmp_path):
    s = make_settings(tmp_path)
    return ContextBudgetService(build_model_registry(s), s)


def mk(cls, llm, budget, model=MODEL):
    return cls(llm=llm, budget=budget, tracing=False, config=AgentConfig(model_id=model, backoff_base_s=0,
                                                                         max_retries=0, timeout_s=5))


def review(a, text, **kw):
    return a.review_story(text, {}, {}, "STORY-1", 1, **kw)


def test_safety_single_section_passed_requires_complete_flag(budget):
    agg, _ = review(mk(SafetyAgent, FakeLLMClient({"safety": OK_SAFETY}), budget), story_text(3))
    assert agg.status == "PASSED" and agg.coverage == 1.0 and agg.sections == 1
    agg, _ = review(mk(SafetyAgent, FakeLLMClient({"safety": {**OK_SAFETY, "reviewed_complete": False}}), budget),
                    story_text(3))
    assert agg.status == "HUMAN_REVIEW_REQUIRED" and agg.coverage == 0.0


def test_safety_critical_always_blocks_and_uncertainty_escalates(budget):
    crit = {"status": "PASSED", "findings": [finding("critical", "safety")], "reviewed_complete": True}
    assert review(mk(SafetyAgent, FakeLLMClient({"safety": crit}), budget), story_text(2))[0].status == "BLOCKED"
    hr = {"status": "HUMAN_REVIEW_REQUIRED", "findings": [], "reviewed_complete": True}
    assert review(mk(SafetyAgent, FakeLLMClient({"safety": hr}), budget), story_text(2))[0].status == \
        "HUMAN_REVIEW_REQUIRED"


def test_multi_section_coverage_partial_failure(budget):
    llm = FakeLLMClient({"safety": [OK_SAFETY, LLMModelError("x")]})
    agg, _ = review(mk(SafetyAgent, llm, budget, MID), story_text(90))
    assert agg.sections >= 3 and agg.failed_sections >= 1 and 0 < agg.coverage < 1.0
    assert agg.status == "HUMAN_REVIEW_REQUIRED"
    assert any(f["category"] == "coverage" for f in agg.findings)


def test_total_failure_raises_instead_of_producing_a_status(budget):
    with pytest.raises(AgentFailure):
        review(mk(SafetyAgent, FakeLLMClient({"safety": LLMModelError("down")}), budget), story_text(2))


def test_editorial_needs_complete_narrative_and_severity_order(budget):
    inc = {**OK_EDITORIAL, "reviewed_complete": False}
    assert review(mk(EditorialAgent, FakeLLMClient({"editorial": inc}), budget), story_text(2))[0].status == \
        "HUMAN_REVIEW_REQUIRED"
    mixed = FakeLLMClient({"editorial": [OK_EDITORIAL, {"status": "NEEDS_REVISION", "findings": [finding()],
                                                        "reviewed_complete": True},
                                         {"status": "REJECTED", "findings": [], "reviewed_complete": True}]})
    agg, _ = review(mk(EditorialAgent, mixed, budget, MID), story_text(90))
    assert agg.status == "REJECTED"


def test_findings_require_evidence(budget):
    bad = {"status": "NEEDS_REVISION", "findings": [{"severity": "high", "issue": "meh"}], "reviewed_complete": True}
    r = mk(EditorialAgent, FakeLLMClient({"editorial": bad}), budget).run({"story_text": story_text(2)})
    assert not r.ok  # vague finding without location/explanation/recommendation is rejected


def test_continuity_statuses(budget):
    assert review(mk(ContinuityAgent, FakeLLMClient({"continuity": OK_CONTINUITY}), budget), story_text(2),
                  )[0].status == "CONSISTENT"
    issues = {"status": "ISSUES_FOUND", "findings": [finding("high", "plot")]}
    assert review(mk(ContinuityAgent, FakeLLMClient({"continuity": issues}), budget), story_text(2))[0].status == \
        "ISSUES_FOUND"


def test_humanisation_chunks_long_story_in_order_and_preserves_length(budget):
    text = story_text(90)
    llm = FakeLLMClient({"humanisation": lambda r: {"text": json.loads(r.user)["story_text"], "changes": []}})
    out, usage, results = mk(HumanisationAgent, llm, budget, MID).humanise_story(text, {}, "S", 1)
    assert len(results) >= 2 and out.count("Part ") == 90
    assert [int(p.split("Part ")[1].rstrip(".")) for p in out.split("\n\n")] == list(range(90))
    shrink = FakeLLMClient({"humanisation": {"text": "tiny", "changes": []}})
    with pytest.raises(AgentFailure):
        mk(HumanisationAgent, shrink, budget).humanise_story(text, {}, "S", 1)


def test_distribution_requires_all_platform_fields_and_drops_extras(budget):
    ok = FakeLLMClient({"distribution": {"platforms": {**DIST["platforms"], "tiktok": {"x": 1}}}})
    r = mk(DistributionAgent, ok, budget).run({"story_text": story_text(2)})
    assert r.ok and "tiktok" not in r.output.platforms
    broken = {"platforms": {**DIST["platforms"], "reddit": {"title": "t"}}}
    r = mk(DistributionAgent, FakeLLMClient({"distribution": broken}), budget).run({"story_text": story_text(2)})
    assert not r.ok and "reddit" in r.error.message
    assert not mk(DistributionAgent, ok, budget).run({"story_text": "x", "platforms": ["myspace"]}).ok
