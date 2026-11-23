import json
import logging

import pytest

from backend.config import Settings
from backend.utils.logging_setup import redact_text, setup_logging, teardown_logging


@pytest.fixture
def handlers(tmp_path):
    s = Settings(_env_file=None, log_dir=str(tmp_path / "logs"), data_dir=str(tmp_path), log_max_bytes=2000,
                 log_backup_count=2)
    h = setup_logging(s)
    yield tmp_path / "logs", h
    teardown_logging()


def read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def flush(h):
    for x in h.values():
        x.flush()


def test_channels_write_json_lines(handlers):
    d, h = handlers
    logging.getLogger("midnight.agent").info("agent ran", extra={"workflow_id": "W1", "story_id": "S1",
                                                                 "story_version": 2, "agent": "writer",
                                                                 "operation": "generate"})
    logging.getLogger("midnight.publishing").info("pub")
    logging.getLogger("midnight.scheduler").info("sched")
    logging.getLogger("midnight.app").info("app")
    flush(h)
    rec = read(d / "agent.log")[0]
    assert rec["workflow_id"] == "W1" and rec["story_version"] == 2 and rec["agent"] == "writer"
    assert rec["severity"] == "INFO" and rec["timestamp"] and rec["operation"] == "generate"
    for f in ("publishing", "scheduler", "app"):
        assert len(read(d / f"{f}.log")) == 1
    assert not (d / "error.log").exists() or read(d / "error.log") == []


def test_errors_go_to_error_log_once_and_not_to_other_channels_twice(handlers):
    d, h = handlers
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        logging.getLogger("midnight.agent").exception("failed")
    flush(h)
    assert len(read(d / "error.log")) == 1 and len(read(d / "agent.log")) == 1
    assert "kaboom" in read(d / "error.log")[0]["exception"]
    assert not (d / "app.log").exists() or read(d / "app.log") == []


def test_secrets_redacted_everywhere(handlers):
    d, h = handlers
    lg = logging.getLogger("midnight.app")
    lg.info("calling with api_key=sk-abcdef1234567890 and Bearer abcdefghijklmnop")
    lg.info("args %s", "password: hunter2hunter2")
    lg.info("extra", extra={"openai_api_key": "sk-zzzzzzzzzzzz", "headers": {"Authorization": "Bearer abc123456789"},
                            "note": "token=abc123"})
    try:
        raise ValueError("bad key sk-exceptionsecret99")
    except ValueError:
        lg.error("err", exc_info=True)
    flush(h)
    blob = (d / "app.log").read_text(encoding="utf-8") + (d / "error.log").read_text(encoding="utf-8")
    for secret in ("sk-abcdef1234567890", "abcdefghijklmnop", "hunter2hunter2", "sk-zzzzzzzzzzzz", "abc123456789",
                   "sk-exceptionsecret99", "token=abc123"):
        assert secret not in blob, secret
    assert "[REDACTED]" in blob


def test_root_logger_captures_third_party(handlers):
    d, h = handlers
    logging.getLogger("uvicorn.error").warning("third party")
    flush(h)
    assert any(r["message"] == "third party" for r in read(d / "app.log"))


def test_idempotent_no_duplicate_lines(handlers, tmp_path):
    d, h = handlers
    s = Settings(_env_file=None, log_dir=str(d), data_dir=str(tmp_path))
    h2 = setup_logging(s)
    logging.getLogger("midnight.agent").info("once")
    flush(h2)
    assert len([r for r in read(d / "agent.log") if r["message"] == "once"]) == 1


def test_rotation(handlers):
    d, h = handlers
    for i in range(200):
        logging.getLogger("midnight.scheduler").info("x" * 100)
    flush(h)
    assert (d / "scheduler.log.1").exists()


def test_redact_text_unit():
    assert "secret" not in redact_text("password=secret")
    assert redact_text("plain text") == "plain text"
