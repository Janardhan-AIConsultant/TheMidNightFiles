"""DeepEval judge model served through OpenRouter's OpenAI-compatible API (DeepEval defaults to OpenAI)."""
from __future__ import annotations

import json

from deepeval.models import DeepEvalBaseLLM

from backend.agents.base import extract_json
from evals.runner import MODEL, settings


class OpenRouterJudge(DeepEvalBaseLLM):
    def __init__(self, model: str | None = None):
        self._model = model or MODEL
        super().__init__(self._model)

    def load_model(self):
        from openai import OpenAI
        s = settings()
        return OpenAI(api_key=s.openrouter_api_key.get_secret_value(), base_url=s.openrouter_base_url,
                      default_headers={"X-Title": s.openrouter_app_name})

    def generate(self, prompt: str, schema=None):
        suffix = "\n\nRespond with ONE valid JSON object only." if schema is not None else ""
        r = self.load_model().chat.completions.create(
            model=self._model, temperature=0, messages=[{"role": "user", "content": prompt + suffix}])
        text = r.choices[0].message.content or ""
        return schema(**extract_json(text)) if schema is not None else text

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return f"openrouter/{self._model}"
