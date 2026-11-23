import pytest

from backend.cache import FilesystemBackend
from backend.config import Settings
from backend.services.cache_service import CacheService


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, cache_directory=str(tmp_path / "cache"), log_dir=str(tmp_path / "logs"),
                    data_dir=str(tmp_path), cache_lock_timeout_seconds=2, cache_lock_stale_seconds=5)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def backend(settings):
    return FilesystemBackend(settings.cache_path)


@pytest.fixture
def cache(settings, backend, clock):
    return CacheService(settings, backend, clock=clock)
