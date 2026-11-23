"""Application configuration (spec section 19). Single source: ``get_settings()``."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised by Settings.validate_startup() with every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid configuration: " + "; ".join(problems))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_debug: bool = True
    app_timezone: str = "Asia/Kolkata"

    llm_provider: str = "openai"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""

    langsmith_tracing: bool = True
    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_project: str = "the-midnight-files"

    database_url: str = "sqlite:///./data/substack_automation.db"
    data_dir: str = "./data"
    log_dir: str = "./logs"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    cache_enabled: bool = True
    cache_backend: str = "filesystem"
    cache_directory: str = "./data/cache"
    cache_default_ttl_seconds: int = 3600
    cache_llm_ttl_seconds: int = 604800
    cache_image_ttl_seconds: int = 2592000
    cache_api_ttl_seconds: int = 300
    cache_max_size_mb: int = 1024
    cache_cleanup_interval_hours: int = 24
    cache_lock_timeout_seconds: int = 120
    cache_lock_stale_seconds: int = 300
    cache_fail_open: bool = True
    redis_url: str = ""

    # Model registry fallbacks (conservative, unverified assumptions; see model_registry.py)
    default_context_limit: int = 8192
    default_max_output: int = 2048
    model_registry_file: str = ""

    vite_api_base_url: str = "http://localhost:8000/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    image_generator: str = ""  # optional 'package.module:callable' image tool hook (no backend bundled)
    max_revision_attempts: int = 3
    publishing_max_retries: int = 3

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [p.strip() for p in s.split(",") if p.strip()]
        return v

    # -- derived paths -------------------------------------------------
    @property
    def cache_path(self) -> Path:
        return Path(self.cache_directory)

    @property
    def log_path(self) -> Path:
        return Path(self.log_dir)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    def validate_startup(self, create_dirs: bool = True) -> "Settings":
        problems: list[str] = []
        if self.app_env.lower() not in {"development", "test", "testing", "staging", "production"}:
            problems.append(f"APP_ENV '{self.app_env}' not recognised")
        if self.cache_backend not in {"filesystem", "redis"}:
            problems.append("CACHE_BACKEND must be 'filesystem' or 'redis'")
        if self.cache_backend == "redis" and not self.redis_url:
            problems.append("REDIS_URL required when CACHE_BACKEND=redis")
        for name in ("cache_default_ttl_seconds", "cache_llm_ttl_seconds", "cache_image_ttl_seconds",
                     "cache_api_ttl_seconds", "cache_max_size_mb", "cache_cleanup_interval_hours",
                     "cache_lock_timeout_seconds", "cache_lock_stale_seconds", "default_context_limit",
                     "default_max_output"):
            if getattr(self, name) <= 0:
                problems.append(f"{name.upper()} must be > 0")
        if self.cache_lock_stale_seconds < self.cache_lock_timeout_seconds:
            problems.append("CACHE_LOCK_STALE_SECONDS must be >= CACHE_LOCK_TIMEOUT_SECONDS")
        if self.default_max_output >= self.default_context_limit:
            problems.append("DEFAULT_MAX_OUTPUT must be < DEFAULT_CONTEXT_LIMIT")
        if self.max_revision_attempts < 1:
            problems.append("MAX_REVISION_ATTEMPTS must be >= 1")
        if self.publishing_max_retries < 0:
            problems.append("PUBLISHING_MAX_RETRIES must be >= 0")
        prod = self.app_env.lower() == "production"
        if self.llm_provider == "openai" and prod:
            if not self.openai_api_key.get_secret_value():
                problems.append("OPENAI_API_KEY required in production")
            if not self.openai_model:
                problems.append("OPENAI_MODEL required in production")
        if self.langsmith_tracing and prod and not self.langsmith_api_key.get_secret_value():
            problems.append("LANGSMITH_API_KEY required when LANGSMITH_TRACING=true in production")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(self.app_timezone)
        except Exception:
            problems.append(f"APP_TIMEZONE '{self.app_timezone}' is not a valid IANA zone")
        if create_dirs:
            for p in (self.data_path, self.cache_path, self.log_path):
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    if not os.access(p, os.W_OK):
                        problems.append(f"{p} is not writable")
                except OSError as exc:
                    problems.append(f"cannot create {p}: {exc}")
        if problems:
            raise ConfigurationError(problems)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
