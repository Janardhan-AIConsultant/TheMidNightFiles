"""Builds real agents against OpenRouter for eval runs. NEVER imported by the normal test suite.
Env: OPENROUTER_API_KEY (required), EVAL_MODEL (default: the app's free pilot model), OPENROUTER_ALLOW_PAID."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents import AgentConfig, SafetyAgent, WriterAgent  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.services.context_budget_service import ContextBudgetService  # noqa: E402
from backend.services.llm_client import OpenRouterLLMClient, build_model_registry  # noqa: E402
from backend.services.story_profile_service import select_story_profile  # noqa: E402

MODEL = os.getenv("EVAL_MODEL") or "google/gemma-4-31b-it:free"


def settings() -> Settings:
    return Settings(_env_file=None, llm_provider="openrouter", openrouter_model=MODEL, langsmith_tracing=False,
                    openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
                    openrouter_allow_paid=os.getenv("OPENROUTER_ALLOW_PAID", "").lower() == "true")


def _common():
    s = settings()
    # max_retries covers free-tier 429s; the agent's own backoff applies.
    return (OpenRouterLLMClient(s, temperature=0.7), ContextBudgetService(build_model_registry(s), s),
            AgentConfig(model_id=MODEL, use_cache=False, max_retries=3, backoff_base_s=2.0, timeout_s=180))


def write_story(brief: dict, words: int = 300) -> dict:
    llm, budget, cfg = _common()
    profile = select_story_profile(None, words).to_dict()
    agent = WriterAgent(llm=llm, budget=budget, cache=None, config=cfg, tracing=False)
    res = agent.run({"brief": brief, "profile": profile})
    return {"ok": res.ok, "text": res.output.text if res.ok else "", "title": res.output.title if res.ok else "",
            "error": res.error.message if res.error else "",
            "error_kind": res.error.kind.value if res.error else ""}


def review_safety(text: str) -> str:
    llm, budget, cfg = _common()
    agent = SafetyAgent(llm=llm, budget=budget, cache=None, config=cfg, tracing=False)
    agg, _ = agent.review_story(text, select_story_profile(None, 300).to_dict(), {}, "EVAL", 1)
    return agg.status
