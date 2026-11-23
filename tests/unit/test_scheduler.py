import sys
import types
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import database  # noqa: E402
from backend.automation.scheduler import (JOB_CACHE, JOB_CALENDAR, JOB_PUBLISHING, MAX_CALENDAR_FAILURES,  # noqa: E402
                                          SchedulerService)
from backend.config import Settings  # noqa: E402
from backend.models import ContentCalendar, Setting  # noqa: E402
from backend.models.base import utcnow  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(app_env="test", database_url=f"sqlite:///{(tmp_path / 's.db').as_posix()}",
                    data_dir=str(tmp_path / "d"), log_dir=str(tmp_path / "l"),
                    cache_directory=str(tmp_path / "c"), langsmith_tracing=False, _env_file=None)


@pytest.fixture()
def sched(settings):
    database.configure(settings.database_url)
    database.init_db()
    s = SchedulerService(settings)
    yield s
    s.shutdown()


def fake_workflow_module(monkeypatch, start):
    mod = types.ModuleType("backend.orchestration.workflow_service")
    mod.get_workflow_service = lambda: types.SimpleNamespace(start=start)
    monkeypatch.setitem(sys.modules, "backend.orchestration.workflow_service", mod)


def add_items(n=2, past=True):
    with database.get_session() as s:
        for i in range(n):
            s.add(ContentCalendar(planned_date=utcnow() + timedelta(hours=-1 if past else 5), topic=f"t{i}"))


def statuses():
    with database.get_session() as s:
        return sorted(c.status for c in s.query(ContentCalendar))


def test_jobs_registered_once_with_safe_options(sched):
    sched.start()
    sched.reconfigure()
    sched.reconfigure()  # idempotent: replace_existing + stable ids
    jobs = {j.id: j for j in sched._sched.get_jobs()}
    assert set(jobs) == {JOB_CALENDAR, JOB_PUBLISHING, JOB_CACHE} and len(sched._sched.get_jobs()) == 3
    for j in jobs.values():
        assert j.coalesce is True and j.max_instances == 1
    assert str(sched.tz) == "Asia/Kolkata" and str(jobs[JOB_CALENDAR].trigger.timezone) == "Asia/Kolkata"
    st = sched.status()
    assert st["running"] and all(j["scheduled"] and j["next_run_time"] for j in st["jobs"])


def test_operator_settings_drive_schedule_and_pause(sched):
    with database.get_session() as s:
        s.add(Setting(key="scheduler.calendar_hour", value={"value": 7}))
        s.add(Setting(key="scheduler.publishing_interval_seconds", value={"value": 120}))
    sched.start()
    j = {j.id: j for j in sched._sched.get_jobs()}
    assert "hour='7'" in str(j[JOB_CALENDAR].trigger)
    assert j[JOB_PUBLISHING].trigger.interval.total_seconds() == 120
    with database.get_session() as s:
        s.add(Setting(key="scheduler.enabled", value={"value": False}))
    sched.reconfigure()
    assert all(x["next_run_time"] is None for x in sched.status()["jobs"])


def test_calendar_starts_due_items_exactly_once(sched, monkeypatch):
    calls = []
    fake_workflow_module(monkeypatch, lambda req: calls.append(req) or "WF-1")
    add_items(2)
    add_items(1, past=False)
    assert sched.run_calendar_workflows()["started"] == 2
    assert sched.run_calendar_workflows()["started"] == 0  # no duplicate execution
    assert len(calls) == 2 and calls[0]["workflow_type"] == "story_generation"
    assert statuses() == ["PLANNED", "TRIGGERED", "TRIGGERED"]


def test_calendar_failure_retries_then_fails(sched, monkeypatch):
    def boom(req):
        raise RuntimeError("down")
    fake_workflow_module(monkeypatch, boom)
    add_items(1)
    for i in range(MAX_CALENDAR_FAILURES):
        r = sched.run_calendar_workflows()
        assert r["failed"] == 1
        assert statuses() == (["PLANNED"] if i < MAX_CALENDAR_FAILURES - 1 else ["FAILED"])
    assert sched.run_calendar_workflows()["due"] == 0


def test_calendar_skipped_when_workflow_module_missing(sched, monkeypatch):
    monkeypatch.setitem(sys.modules, "backend.orchestration.workflow_service", None)
    add_items(1)
    assert "skipped" in sched.run_calendar_workflows()
    assert statuses() == ["PLANNED"]  # not claimed


def test_run_job_tracks_status_and_never_raises(sched):
    def bad():
        raise ValueError("kaboom")
    st = sched.run_job(JOB_CACHE, bad)
    assert st["last_status"] == "failed" and st["failures"] == 1 and "kaboom" in st["last_error"]
    st = sched.run_job(JOB_CACHE, lambda: {"expired": 0})
    assert st["last_status"] == "ok" and st["runs"] == 2 and st["last_result"] == {"expired": 0}


def test_publishing_processes_until_empty(sched, monkeypatch):
    jobs = [{"id": 1}, {"id": 2}]
    mod = types.ModuleType("backend.automation.publishing_queue")

    class Svc:
        def process_next(self):
            return jobs.pop(0) if jobs else None
    mod.PublishingQueueService = Svc
    monkeypatch.setitem(sys.modules, "backend.automation.publishing_queue", mod)
    assert sched.process_publishing_queue() == {"processed": 2}


def test_cache_cleanup_runs_real_service(settings):
    from backend.services.cache_service import CacheService
    cache = CacheService(settings)
    cache.set("api", "k", {"v": 1})
    res = SchedulerService(settings, cache=cache).cleanup_cache()
    assert {"expired", "corrupt", "evicted"} <= set(res)
    assert "skipped" in SchedulerService(settings, cache=None).cleanup_cache()
