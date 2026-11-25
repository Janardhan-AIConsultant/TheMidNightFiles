"""Runtime safety wired into the workflow: inbound PII redaction and the fail-closed pre-publish gate."""
from __future__ import annotations

from backend.services.llm_client import FakeLLMClient
from tests.workflows.support import DIST, default_responses, story_text


def llm_with(**over) -> FakeLLMClient:
    r = default_responses()
    r.update(over)
    return FakeLLMClient(r)


def test_gate_blocks_story_containing_pii_before_approval(tmp_path):
    from tests.workflows.support import Env
    leaky = lambda req: {"title": "t", "text": story_text(6) + "\n\nWrite to the keeper at keeper.real@gmail.com."}  # noqa: E731
    env = Env(tmp_path, llm_with(writer=leaky, humanisation=lambda r: {"text": leaky(None)["text"], "changes": []}))
    try:
        g = env.service.get(env.run())
        assert g["status"] == "failed" and g["approval_status"] != "APPROVED"
        err = g["errors"][-1]
        assert err["kind"] == "guardrail" and "pii" in err["message"]
        assert g["publishing_status"] in (None, "", "NOT_STARTED") or g["publishing_status"] != "queued"
    finally:
        from backend.orchestration.checkpoint_manager import close_checkpointer
        close_checkpointer(env.ckpt)
        env.engine.dispose()


def test_gate_blocks_pii_in_distribution_payload(tmp_path):
    from tests.workflows.support import Env
    dist = {"platforms": {**DIST["platforms"], "reddit": {**DIST["platforms"]["reddit"],
                                                           "body": "dm me at spam.victim@example.com"}}}
    env = Env(tmp_path, llm_with(distribution=dist))
    try:
        g = env.service.get(env.run())
        assert g["status"] == "failed" and g["errors"][-1]["kind"] == "guardrail"
        assert "reddit.body" in g["errors"][-1]["message"]
    finally:
        from backend.orchestration.checkpoint_manager import close_checkpointer
        close_checkpointer(env.ckpt)
        env.engine.dispose()


def test_clean_story_still_reaches_human_approval(env):
    g = env.service.get(env.run())
    assert g["status"] == "awaiting_human" and g["awaiting"]["type"] == "human_approval"


def test_topic_pii_is_redacted_before_reaching_the_model(env):
    env.run({"topic": "A ghost story about the caretaker, contact jane.doe@example.com for details"})
    sent = env.llm.calls_for("planner")[0].user
    assert "jane.doe@example.com" not in sent and "EMAIL_ADDRESS" in sent
