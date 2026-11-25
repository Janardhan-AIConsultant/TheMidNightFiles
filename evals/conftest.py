"""Eval suite: calls a REAL LLM, so it is skipped unless OPENROUTER_API_KEY is set and never runs in `pytest tests`."""
import os

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")  # no data to third parties
os.environ.setdefault("GUARDRAILS_METRICS_OPT_OUT", "true")


def pytest_collection_modifyitems(config, items):
    if os.getenv("OPENROUTER_API_KEY"):
        return
    skip = pytest.mark.skip(reason="OPENROUTER_API_KEY not set - LLM evals skipped")
    for item in items:
        item.add_marker(skip)
