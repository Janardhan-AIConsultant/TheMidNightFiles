import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend import database
from backend.services.approval_service import ApprovalError, ApprovalService
from backend.services.content_path_manager import ContentPathManager
from backend.services.review_service import ReviewService
from backend.services.story_service import StoryService


def test_alembic_upgrade_creates_schema(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "..", "alembic"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")
    names = set(inspect(create_engine(url)).get_table_names())
    assert {"stories", "story_revisions", "content_approvals", "alembic_version"} <= names
    assert not names & {"agent_execution_logs", "application_logs"}
    command.downgrade(cfg, "base")


def test_database_env_url_and_session_scope(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'sub' / 'e.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    database.configure()
    database.init_db()
    with database.get_session() as s:
        StoryService(s).create_story("X")
    with pytest.raises(RuntimeError):
        with database.get_session() as s:
            StoryService(s).create_story("Y")
            raise RuntimeError
    with database.get_session() as s:
        assert StoryService(s).get_story("STORY-0001").title == "X"
        assert StoryService(s).create_story("Z").id == "STORY-0003"  # services commit themselves, so Y persisted (0002)
    monkeypatch.delenv("DATABASE_URL")
    assert database.get_database_url().endswith("data/substack_automation.db")
    database._engine.dispose()
    database._engine = None


def test_full_lifecycle_with_files_and_cache_hook(session, tmp_path):
    invalidated = []
    pm = ContentPathManager(tmp_path / "content")
    ss = StoryService(session, pm, on_new_version=lambda s, v: invalidated.append((s, v)))
    st = ss.create_story("Night Shift")
    ss.add_revision(st.id, "draft one")
    rv, ap = ReviewService(session), ApprovalService(session)
    rv.record_editorial(st.id, 1, "APPROVED", coverage=1.0)
    rv.record_safety(st.id, 1, "PASSED", coverage=1.0)
    approval = ap.approve(st.id, 1, "alice")
    assert ap.is_publishable(st.id, 1)[0]
    ss.add_revision(st.id, "draft two", "humanised")
    assert invalidated == [(st.id, 1), (st.id, 2)]
    assert not ap.is_publishable(st.id, 1)[0] and not ap.is_publishable(st.id, 2)[0]
    session.refresh(approval)
    assert not approval.is_valid and "superseded" in approval.invalidated_reason
    # only a fresh review pair + fresh approval unlocks v2
    rv.record_editorial(st.id, 2, "APPROVED", coverage=1.0)
    with pytest.raises(ApprovalError):
        ap.approve(st.id, 2, "alice")
    rv.record_safety(st.id, 2, "PASSED", coverage=1.0)
    a2 = ap.approve(st.id, 2, "alice")
    assert a2.id != approval.id and ap.is_publishable(st.id, 2) == (True, [])
    assert pm.read_text(pm.revision_path(st.id, 1, "original.md")) == "draft one"
    assert pm.read_text(pm.revision_path(st.id, 2, "humanised.md")) == "draft two"
