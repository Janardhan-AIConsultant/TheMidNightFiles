"""Planner, Horror Writer, Humanisation Editor."""
from __future__ import annotations

import math

from backend.agents.base import AgentFailure, AgentError, AgentResult, BaseAgent, ErrorKind, Usage
from backend.agents.schemas import (HumanisationInput, HumanisationOutput, PlannerInput, PlannerOutput,
                                    WriterInput, WriterOutput)
from backend.services.chunking_service import ChunkingService

TOKENS_PER_WORD = 1.6


def section_token_limit(agent: BaseAgent, expected_output: int, overhead: int = 600) -> int:
    """Largest story section (input tokens) that still fits this agent's model context with output reserved."""
    model = agent.config.model_id
    spec = agent.budget.registry.get(model)
    system, _ = agent.prompts.load(agent.agent_id, agent.prompt_version)
    margin = max(256, math.ceil(spec.context_limit * 0.05))
    avail = spec.context_limit - margin - expected_output - agent.budget.estimate_tokens(system, model) - overhead
    return max(avail, 200)


class PlannerAgent(BaseAgent):
    agent_id = "planner"
    input_model = PlannerInput
    output_model = PlannerOutput
    cache_namespace = "planner"
    allowed_tools = frozenset({"topic_history", "calendar"})
    context_policy = "request + recent topic history + calendar slice only; no story text"

    def prepare(self, inp):
        if not inp.topic_history and self.tools.has("topic_history"):
            hist = self.tools.call("topic_history")
            inp = inp.model_copy(update={"topic_history": [str(h) for h in hist][:200]})
        return inp

    def expected_output_tokens(self, inp):
        return 1200 + 60 * inp.calendar_days

    def validate_output(self, inp, out):
        if inp.topic_history and out.working_title.strip().lower() in {t.strip().lower() for t in inp.topic_history}:
            raise ValueError("planner repeated a previous topic")
        if inp.calendar_days and len(out.calendar) < inp.calendar_days:
            raise ValueError(f"calendar has {len(out.calendar)} entries, expected {inp.calendar_days}")


class WriterAgent(BaseAgent):
    agent_id = "writer"
    input_model = WriterInput
    output_model = WriterOutput
    cache_namespace = "writer"
    allowed_tools = frozenset()
    context_policy = "approved creative brief, story profile, relevant series context, revision findings"

    def expected_output_tokens(self, inp):
        return int(inp.profile.get("writer_output_budget") or 4000)

    def validate_output(self, inp, out):
        mn = inp.profile.get("min_words")
        if mn and len(out.text.split()) < int(mn):
            raise ValueError(f"story has {len(out.text.split())} words; minimum is {mn} (do not shorten)")
        if inp.previous_text and out.text.strip() == inp.previous_text.strip():
            raise ValueError("revision returned unchanged text")


class HumanisationAgent(BaseAgent):
    agent_id = "humanisation"
    input_model = HumanisationInput
    output_model = HumanisationOutput
    cache_namespace = "humanisation"
    allowed_tools = frozenset()
    context_policy = "story section only; long stories processed in ordered coherent chunks"

    def expected_output_tokens(self, inp):
        return max(300, int(self.budget.estimate_tokens(inp.story_text, self.config.model_id) * 1.15))

    def validate_output(self, inp, out):
        a, b = len(inp.story_text.split()), len(out.text.split())
        if b < 0.8 * a:
            raise ValueError(f"humanised text shrank from {a} to {b} words; length must be preserved")

    def humanise_story(self, text: str, profile: dict, story_id: str, version: int, workflow_id: str | None = None,
                       revision_findings: list | None = None) -> tuple[str, Usage, list[AgentResult]]:
        """Chunk when the story does not fit one call, process in order and reassemble."""
        expected_full = self.budget.estimate_tokens(text, self.config.model_id)
        limit = section_token_limit(self, int(expected_full * 1.15) + 100)
        if expected_full <= limit:
            sections = [text]
        else:
            per = max(200, int(limit / 2.4))  # input + ~1.15x output must both fit
            sections = [c.text for c in ChunkingService().chunk(text, story_id, version, per)]
        usage, results, out = Usage(), [], []
        for part in sections:
            r = self.run(HumanisationInput(story_text=part, profile=profile, story_id=story_id, version=version,
                                           workflow_id=workflow_id, revision_findings=revision_findings or []))
            usage.add(r.usage)
            results.append(r)
            if not r.ok:
                raise AgentFailure(r.error)
            out.append(r.output.text.strip())
        return "\n\n".join(out), usage, results
