"""Image Generation and Distribution agents."""
from __future__ import annotations

from backend.agents.base import BaseAgent
from backend.agents.schemas import (REQUIRED_FIELDS, DistributionInput, DistributionOutput, ImageInput, ImageOutput)


class ImageAgent(BaseAgent):
    agent_id = "image"
    input_model = ImageInput
    output_model = ImageOutput
    cache_namespace = "images"
    allowed_tools = frozenset({"generate_image"})
    context_policy = "approved story synopsis, title, characters and visual direction only (no full text)"

    def expected_output_tokens(self, inp):
        return 1200

    def execute(self, inp):
        out = self._llm_execute(inp)
        if self.tools.has("generate_image"):  # the tool must refuse to overwrite referenced/published assets
            for a in out.assets:
                a.reference = self.tools.call("generate_image", a.model_dump(), inp.story_id, inp.version)
        return out


class DistributionAgent(BaseAgent):
    agent_id = "distribution"
    input_model = DistributionInput
    output_model = DistributionOutput
    cache_namespace = "distribution"
    allowed_tools = frozenset({"platform_specs"})
    context_policy = "approved story text + platform specifications; never auto-posts"

    def expected_output_tokens(self, inp):
        return 3500

    def validate_output(self, inp, out):
        for p in inp.platforms:
            payload = out.platforms.get(p)
            if not isinstance(payload, dict):
                raise ValueError(f"missing platform payload {p}")
            missing = [f for f in REQUIRED_FIELDS[p] if payload.get(f) in (None, "", [], {})]
            if missing:
                raise ValueError(f"{p} payload missing {missing}")
        extra = set(out.platforms) - set(inp.platforms)
        for p in extra:
            out.platforms.pop(p)
