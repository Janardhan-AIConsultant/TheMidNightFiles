"""Zero-cost prompt checks that run on every PR (no LLM): every agent has a prompt, JSON agents say so, no leftovers."""
from __future__ import annotations

import re

import pytest

from backend.agents import AGENT_CLASSES
from backend.agents.base import PROMPT_DIR, PromptStore

LLM_AGENTS = [c for c in AGENT_CLASSES if c.uses_llm]


@pytest.mark.parametrize("cls", LLM_AGENTS, ids=lambda c: c.agent_id)
def test_prompt_exists_and_is_stable(cls):
    text, h1 = PromptStore().load(cls.agent_id, cls.prompt_version)
    assert len(text.strip()) > 80 and PromptStore().load(cls.agent_id, cls.prompt_version)[1] == h1


@pytest.mark.parametrize("cls", LLM_AGENTS, ids=lambda c: c.agent_id)
def test_prompt_demands_json_and_has_no_leftovers(cls):
    text, _ = PromptStore().load(cls.agent_id, cls.prompt_version)
    assert "json" in text.lower(), "agents parse JSON; the prompt must ask for it"
    assert not re.search(r"\{\{|TODO|FIXME|lorem ipsum", text, re.I)


def test_no_orphan_prompt_directories():
    ids = {c.agent_id for c in AGENT_CLASSES}
    assert {p.name for p in PROMPT_DIR.iterdir() if p.is_dir()} <= ids
