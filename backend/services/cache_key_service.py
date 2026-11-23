"""Cache key construction: SHA-256 over canonical JSON of the *specific* relevant inputs.

Never pass an entire LangGraph state; pass only the parts the computation depends on
(agent id/version, prompt hash, content hash, story id/version, model, params, schema/policy version...).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any


def _default(o: Any):
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return dataclasses.asdict(o)
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=repr)
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"cannot canonicalise {type(o).__name__} for cache key")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def build_key(**parts: Any) -> str:
    if not parts:
        raise ValueError("build_key requires at least one part")
    return hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()


def content_hash(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


class CacheKeyService:
    build_key = staticmethod(build_key)
    content_hash = staticmethod(content_hash)

    @staticmethod
    def agent_key(*, agent_id: str, agent_version: str, prompt_hash: str, input_hash: str,
                  model_provider: str, model_id: str, model_params: dict | None = None,
                  output_schema_version: str = "1", story_id: str | None = None,
                  story_version: int | None = None, series_context_hash: str | None = None,
                  safety_policy_version: str | None = None, config: dict | None = None) -> str:
        return build_key(agent_id=agent_id, agent_version=agent_version, prompt_hash=prompt_hash,
                         input_hash=input_hash, model_provider=model_provider, model_id=model_id,
                         model_params=model_params or {}, output_schema_version=output_schema_version,
                         story_id=story_id, story_version=story_version,
                         series_context_hash=series_context_hash,
                         safety_policy_version=safety_policy_version, config=config or {})
