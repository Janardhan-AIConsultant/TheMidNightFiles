import json

import pytest

from backend.config import ConfigurationError, Settings, get_settings
from backend.services.context_budget_service import (BudgetPlan, ContextBudgetService, ContextOverflowError,
                                                     conservative_estimate)
from backend.services.model_registry import ModelRegistry, ModelSpec


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, cache_directory=str(tmp_path / "c"), log_dir=str(tmp_path / "l"),
                    data_dir=str(tmp_path))


@pytest.fixture
def registry(settings):
    r = ModelRegistry(settings)
    r.register(ModelSpec("test", "big", 100_000, 8_000, tools=True, structured=True))
    r.register(ModelSpec("openai", "gpt-4o", 128_000, 16_000, pricing=None))
    return r


@pytest.fixture
def svc(registry, settings):
    return ContextBudgetService(registry, settings)


def test_unknown_model_uses_documented_conservative_default(registry, settings):
    s = registry.get("never-heard-of-it")
    assert (s.context_limit, s.max_output) == (settings.default_context_limit, settings.default_max_output)
    assert not s.verified and not s.tools and not s.structured and s.pricing is None
    assert registry.known("big") and not registry.known("zzz")


def test_registry_rejects_invalid_and_loads_file(settings, tmp_path):
    r = ModelRegistry(settings)
    with pytest.raises(ValueError):
        r.register(ModelSpec("p", "m", 1000, 1000))
    f = tmp_path / "m.json"
    f.write_text(json.dumps([{"provider": "p", "model_id": "m1", "context_limit": 5000, "max_output": 500}]))
    s2 = settings.model_copy(update={"model_registry_file": str(f)})
    assert ModelRegistry(s2).get("m1").context_limit == 5000


def test_plan_formula(svc):
    p = svc.plan("writer", "big", system_tokens=1000, agent_tokens=2000, convo_tokens=3000, expected_output=4000,
                 tool_reserve=500)
    assert p.safety_margin == 5000  # 5% of 100k
    assert p.available_input == 100_000 - 6000 - 4000 - 500 - 5000
    assert p.reserved_output == 4000 and p.fits


def test_exact_boundary_fits_and_one_over_does_not(svc):
    p = svc.plan("a", "big", 0, 0, 0, 1)
    room = p.available_input
    assert svc.plan("a", "big", 0, 0, room + 1, 1).fits is False
    assert svc.plan("a", "big", 0, 0, room, 1).fits is True


def test_overflow_and_output_cap(svc):
    with pytest.raises(ContextOverflowError) as ei:
        svc.ensure_fits("editorial", "big", 50_000, 40_000, 20_000, 4000)
    assert isinstance(ei.value.plan, BudgetPlan) and not ei.value.plan.fits
    with pytest.raises(ContextOverflowError):
        svc.ensure_fits("writer", "big", 10, 10, 10, 9_000)  # > max_output 8000
    assert svc.ensure_fits("writer", "big", 10, 10, 10, 1000).fits


def test_never_exceeds_limit_for_unknown_model(svc):
    # default 8192 context: a 9000-token prompt must not fit
    assert svc.plan("x", "mystery", 9000, 0, 0, 100).fits is False


def test_stats_recorded(svc):
    svc.plan("writer", "big", 1000, 0, 0, 1000)
    svc.plan("writer", "big", 95_000, 0, 0, 1000)
    svc.plan("safety", "big", 10, 0, 0, 10)
    st = svc.stats()
    assert st["agents"]["writer"]["calls"] == 2 and st["agents"]["writer"]["overflows"] == 1
    assert st["agents"]["writer"]["max_utilisation"] > 0.9
    assert st["total_calls"] == 3 and st["total_overflows"] == 1


def test_estimate_is_conservative_and_not_a_single_ratio(svc):
    prose = "The lighthouse keeper heard the knocking again, softer this time. " * 50
    est = svc.estimate_tokens(prose, "big")
    assert est >= len(prose.split())             # never fewer tokens than words
    assert est >= len(prose) / 3 - 1
    assert svc.estimate_tokens("", "big") == 0
    assert conservative_estimate("a b c") == 5   # words*1.5 dominates short text
    long_word = "x" * 300
    assert conservative_estimate(long_word) == 100  # chars/3 dominates


def test_estimate_openai_uses_tokenizer_when_available_else_falls_back(svc):
    text = "Hello there, this is a short horror sentence."
    est = svc.estimate_tokens(text, "gpt-4o")
    assert 5 <= est <= conservative_estimate(text) + 10


def test_estimate_survives_missing_tokenizer(registry, settings, monkeypatch):
    s = ContextBudgetService(registry, settings)
    monkeypatch.setitem(__import__("sys").modules, "tiktoken", None)
    t = "some text here"
    assert s.estimate_tokens(t, "gpt-4o") == conservative_estimate(t)


# ---------------- config ----------------
def test_settings_defaults_match_spec(settings):
    assert settings.cache_default_ttl_seconds == 3600 and settings.cache_llm_ttl_seconds == 604800
    assert settings.cache_image_ttl_seconds == 2592000 and settings.cache_api_ttl_seconds == 300
    assert settings.cache_max_size_mb == 1024 and settings.cache_lock_stale_seconds == 300
    assert settings.max_revision_attempts == 3 and settings.publishing_max_retries == 3
    assert settings.app_timezone == "Asia/Kolkata" and settings.cache_fail_open is True


def test_env_override_and_cors_parsing(monkeypatch):
    monkeypatch.setenv("CACHE_MAX_SIZE_MB", "5")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret123456")
    s = Settings(_env_file=None)
    assert s.cache_max_size_mb == 5 and s.cors_origins == ["http://a.test", "http://b.test"]
    assert "sk-secret123456" not in repr(s)
    monkeypatch.setenv("CORS_ORIGINS", '["http://c.test"]')
    assert Settings(_env_file=None).cors_origins == ["http://c.test"]


def test_validate_startup_ok_creates_dirs(settings):
    assert settings.validate_startup() is settings
    assert settings.cache_path.is_dir() and settings.log_path.is_dir()


def test_validate_startup_reports_all_problems(tmp_path):
    s = Settings(_env_file=None, cache_directory=str(tmp_path / "c"), log_dir=str(tmp_path / "l"),
                 data_dir=str(tmp_path), cache_backend="memcached", cache_default_ttl_seconds=0,
                 cache_lock_timeout_seconds=100, cache_lock_stale_seconds=10, app_timezone="Mars/Base",
                 max_revision_attempts=0)
    with pytest.raises(ConfigurationError) as ei:
        s.validate_startup()
    msg = " ".join(ei.value.problems)
    for needle in ("CACHE_BACKEND", "CACHE_DEFAULT_TTL_SECONDS", "CACHE_LOCK_STALE", "APP_TIMEZONE",
                   "MAX_REVISION_ATTEMPTS"):
        assert needle in msg


def test_production_requires_secrets(tmp_path):
    s = Settings(_env_file=None, app_env="production", cache_directory=str(tmp_path / "c"),
                 log_dir=str(tmp_path / "l"), data_dir=str(tmp_path))
    with pytest.raises(ConfigurationError) as ei:
        s.validate_startup()
    assert any("OPENAI_API_KEY" in p for p in ei.value.problems)


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
