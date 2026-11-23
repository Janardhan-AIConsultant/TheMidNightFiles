import os
import threading
import time
from pathlib import Path

import pytest

from backend.cache import CacheBackendUnavailable, CacheEntry, CacheLockTimeout, FilesystemBackend, create_backend
from backend.cache.redis_backend import RedisBackend
from backend.config import Settings
from backend.services.cache_cleanup_service import CacheCleanupService
from backend.services.cache_invalidation_service import CacheInvalidationService
from backend.services.cache_key_service import CacheKeyService, build_key
from backend.services.cache_service import CacheService


def K(**p):
    return build_key(**{"x": 1, **p})


# ---------------- keys ----------------
def test_key_deterministic_and_order_independent():
    assert build_key(a=1, b={"x": [1, 2], "y": 2}) == build_key(b={"y": 2, "x": [1, 2]}, a=1)
    assert len(build_key(a=1)) == 64
    assert build_key(a=1) != build_key(a=2)
    assert build_key(a={1, 2}) == build_key(a={2, 1})


def test_key_rejects_unknown_types_and_empty():
    with pytest.raises(TypeError):
        build_key(a=object())
    with pytest.raises(ValueError):
        build_key()


def test_agent_key_varies_with_each_dependency():
    base = dict(agent_id="writer", agent_version="1", prompt_hash="p", input_hash="i", model_provider="openai",
                model_id="m", model_params={"t": 0.7})
    k = CacheKeyService.agent_key(**base)
    for field, val in [("agent_version", "2"), ("prompt_hash", "q"), ("input_hash", "j"), ("model_id", "m2"),
                       ("model_params", {"t": 0.2}), ("story_version", 2), ("safety_policy_version", "9")]:
        assert CacheKeyService.agent_key(**{**base, field: val}) != k, field


# ---------------- hit / miss / ttl ----------------
def test_miss_then_hit(cache):
    k = K()
    assert cache.get("writer", k) is None
    assert cache.set("writer", k, {"text": "hello"})
    assert cache.get("writer", k) == {"text": "hello"}
    s = cache.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["by_namespace"]["writer"]["writes"] == 1
    assert s["size_mb"] > 0


def test_ttl_expiry_and_namespace_defaults(cache, clock, settings):
    k = K()
    cache.set("api", k, [1])           # api ttl 300
    cache.set("writer", k, [2])        # llm ttl 604800
    assert cache.ttl_for("images") == settings.cache_image_ttl_seconds
    assert cache.ttl_for("misc") == settings.cache_default_ttl_seconds
    clock.advance(301)
    assert cache.get("api", k) is None
    assert cache.get("writer", k) == [2]
    clock.advance(604800)
    assert cache.get("writer", k) is None


def test_explicit_ttl_and_zero_ttl(cache, clock):
    cache.set("api", K(a=1), 1, ttl=10)
    assert cache.set("api", K(a=2), 1, ttl=0) is False
    clock.advance(11)
    assert cache.get("api", K(a=1)) is None


def test_never_cache_namespaces(cache):
    for ns in ("approvals", "publishing", "auth"):
        assert cache.set(ns, K(), {"approved": True}) is False
        assert cache.get(ns, K()) is None
    calls = []
    for _ in range(2):
        cache.get_or_compute("approvals", K(), lambda: calls.append(1) or {"a": 1})
    assert len(calls) == 2


def test_none_not_cached_and_unserialisable_fail_open(cache):
    assert cache.set("writer", K(), None) is False
    assert cache.set("writer", K(b=1), {"x": object()}) is False  # error logged, no raise
    assert cache.stats()["errors"] >= 1
    assert cache.get_or_compute("writer", K(c=1), lambda: {"x": object()})["x"] is not None


def test_disabled_cache_always_computes(settings, backend):
    s = settings.model_copy(update={"cache_enabled": False})
    c = CacheService(s, backend)
    n = []
    for _ in range(3):
        c.get_or_compute("writer", K(), lambda: n.append(1) or "v")
    assert len(n) == 3 and c.get("writer", K()) is None


# ---------------- get_or_compute ----------------
def test_get_or_compute_caches(cache):
    n = []
    f = lambda: n.append(1) or {"v": len(n)}
    assert cache.get_or_compute("writer", K(), f) == {"v": 1}
    assert cache.get_or_compute("writer", K(), f) == {"v": 1}
    assert len(n) == 1


def test_validate_rejects_unvalidated_output_not_cached(cache):
    n = []
    f = lambda: n.append(1) or {"ok": False}
    for _ in range(2):
        assert cache.get_or_compute("writer", K(), f, validate=lambda v: v["ok"]) == {"ok": False}
    assert len(n) == 2 and cache.get("writer", K()) is None


def test_validate_raising_is_not_cached(cache):
    def bad(v):
        raise RuntimeError("x")

    assert cache.get_or_compute("writer", K(), lambda: {"a": 1}, validate=bad) == {"a": 1}
    assert cache.get("writer", K()) is None


def test_stored_value_failing_validation_is_dropped_and_recomputed(cache):
    cache.set("writer", K(), {"ok": False})
    out = cache.get_or_compute("writer", K(), lambda: {"ok": True}, validate=lambda v: v["ok"])
    assert out == {"ok": True}
    assert cache.get("writer", K()) == {"ok": True}


def test_exception_not_cached_and_lock_released(cache):
    def boom():
        raise ValueError("llm failed")

    with pytest.raises(ValueError):
        cache.get_or_compute("writer", K(), boom)
    assert cache.get("writer", K()) is None
    assert cache.get_or_compute("writer", K(), lambda: "ok") == "ok"  # would time out if lock leaked


def test_single_flight_threads(cache):
    n = []
    gate = threading.Barrier(8)

    def slow():
        n.append(1)
        time.sleep(0.3)
        return {"r": 1}

    out = []

    def worker():
        gate.wait()
        out.append(cache.get_or_compute("writer", K(), slow))

    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(n) == 1 and out == [{"r": 1}] * 8


def test_single_flight_two_service_instances_share_file_lock(settings, clock):
    """Separate CacheService instances (no shared in-process locks) still compute once via the file lock."""
    n = []
    caches = [CacheService(settings, FilesystemBackend(settings.cache_path), clock=clock) for _ in range(4)]
    gate = threading.Barrier(4)

    def slow():
        n.append(1)
        time.sleep(0.3)
        return {"r": 1}

    def worker(c):
        gate.wait()
        assert c.get_or_compute("writer", K(), slow) == {"r": 1}

    ts = [threading.Thread(target=worker, args=(c,)) for c in caches]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(n) == 1


def test_different_keys_not_serialised(cache):
    t0 = time.monotonic()

    def slow(i):
        time.sleep(0.3)
        return i

    ts = [threading.Thread(target=lambda i=i: cache.get_or_compute("writer", K(i=i), lambda: slow(i))) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert time.monotonic() - t0 < 0.9


# ---------------- locks ----------------
def test_lock_timeout_fails_open_and_computes(settings, backend, clock):
    s = settings.model_copy(update={"cache_lock_timeout_seconds": 1, "cache_lock_stale_seconds": 100})
    c = CacheService(s, backend, clock=clock)
    key = K()
    with backend.lock("writer", key, 1, 100):
        t0 = time.monotonic()
        assert c.get_or_compute("writer", key, lambda: "computed") == "computed"
        assert 0.9 < time.monotonic() - t0 < 5
    assert c.stats()["errors"] >= 1


def test_lock_timeout_raises_when_not_fail_open(settings, backend):
    s = settings.model_copy(update={"cache_lock_timeout_seconds": 1, "cache_lock_stale_seconds": 100,
                                    "cache_fail_open": False})
    c = CacheService(s, backend)
    with backend.lock("writer", K(), 1, 100):
        with pytest.raises(CacheLockTimeout):
            c.get_or_compute("writer", K(), lambda: "x")


def test_stale_lock_is_broken(backend):
    key = K()
    lp = backend._lock_path("writer", key)
    lp.write_text('{"pid": 1, "token": "dead"}')
    old = time.time() - 1000
    os.utime(lp, (old, old))
    t0 = time.monotonic()
    with backend.lock("writer", key, 2, 5):
        assert time.monotonic() - t0 < 1
    assert not lp.exists()


def test_fresh_lock_not_broken_times_out(backend):
    key = K()
    with backend.lock("writer", key, 1, 100):
        with pytest.raises(CacheLockTimeout):
            with backend.lock("writer", key, 0.3, 100):
                pass


def test_lock_released_on_exception_in_body(backend):
    key = K()
    with pytest.raises(RuntimeError):
        with backend.lock("writer", key, 1, 100):
            raise RuntimeError
    with backend.lock("writer", key, 0.5, 100):
        pass


def test_lock_not_removed_if_taken_over_after_stale_break(backend):
    key = K()
    with backend.lock("writer", key, 1, 100):
        lp = backend._lock_path("writer", key)
        lp.write_text('{"pid": 2, "token": "someone-else"}')
    assert lp.exists()  # we must not delete a lock we no longer own


# ---------------- corruption / failures ----------------
def _entry_path(backend, ns, key):
    return backend._path(ns, key)


@pytest.mark.parametrize("garbage", [b"", b"{not json", b'{"namespace": "writer"}', b"\xff\xfe\x00bad"])
def test_corrupt_entry_rejected_and_recomputed(cache, backend, garbage):
    key = K()
    cache.set("writer", key, {"v": 1})
    _entry_path(backend, "writer", key).write_bytes(garbage)
    assert cache.get("writer", key) is None
    assert not _entry_path(backend, "writer", key).exists()
    assert cache.get_or_compute("writer", key, lambda: {"v": 2}) == {"v": 2}
    assert cache.stats()["errors"] >= 1


def test_tampered_value_detected_by_checksum(cache, backend):
    key = K()
    cache.set("writer", key, {"v": 1})
    p = _entry_path(backend, "writer", key)
    p.write_text(p.read_text().replace('"v": 1', '"v": 999'))
    assert cache.get("writer", key) is None


def test_entry_for_other_key_rejected(cache, backend):
    k1, k2 = K(a=1), K(a=2)
    cache.set("writer", k1, {"v": 1})
    _entry_path(backend, "writer", k2).parent.mkdir(parents=True, exist_ok=True)
    _entry_path(backend, "writer", k2).write_bytes(_entry_path(backend, "writer", k1).read_bytes())
    assert cache.get("writer", k2) is None


class ExplodingBackend(FilesystemBackend):
    def get(self, *a):
        raise OSError("disk gone")

    def put(self, *a):
        raise OSError("disk full")

    def lock(self, *a):
        raise OSError("no locks")

    def size_bytes(self):
        raise OSError("x")


def test_backend_failures_fail_open(settings):
    c = CacheService(settings, ExplodingBackend(settings.cache_path))
    assert c.get("writer", K()) is None
    assert c.set("writer", K(), {"a": 1}) is False
    assert c.stats()["errors"] >= 2


def test_backend_failure_raises_when_not_fail_open(settings):
    s = settings.model_copy(update={"cache_fail_open": False})
    c = CacheService(s, ExplodingBackend(s.cache_path))
    with pytest.raises(OSError):
        c.get("writer", K())


def test_get_or_compute_survives_lock_error(settings):
    c = CacheService(settings, ExplodingBackend(settings.cache_path))
    # every backend operation (get, lock, put) raises, yet the computation result is returned
    assert c.get_or_compute("writer", K(), lambda: {"v": 1}) == {"v": 1}
    assert c.stats()["errors"] >= 3


def test_unavailable_redis_backend_disables_cache_when_fail_open(tmp_path):
    s = Settings(_env_file=None, cache_backend="redis", cache_directory=str(tmp_path))
    with pytest.raises(CacheBackendUnavailable):
        create_backend(s)
    with pytest.raises(CacheBackendUnavailable):
        RedisBackend("redis://x")
    c = CacheService(s)
    assert c.enabled is False
    assert c.get_or_compute("writer", K(), lambda: 5) == 5
    with pytest.raises(CacheBackendUnavailable):
        CacheService(s.model_copy(update={"cache_fail_open": False}))


def test_unsafe_names_rejected(backend):
    for ns, key in [("../x", "a"), ("writer", "../../etc"), ("_locks", "a"), ("w/x", "a")]:
        with pytest.raises(ValueError):
            backend.get(ns, key)


def test_concurrent_writes_same_key_never_corrupt(cache, backend):
    key = K()

    def w(i):
        for j in range(20):
            cache.set("writer", key, {"i": i, "j": j, "pad": "x" * 2000})

    ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    v = cache.get("writer", key)
    assert v is not None and v["pad"] == "x" * 2000
    assert not list(backend.root.glob("*/*/*.tmp"))


# ---------------- invalidation ----------------
def test_invalidate_story_all_and_from_version(cache):
    cache.set("editorial", K(a=1), "r1", story_id="S1", version=1)
    cache.set("editorial", K(a=2), "r2", story_id="S1", version=2)
    cache.set("safety", K(a=3), "r3", story_id="S1", version=3)
    cache.set("series", K(a=4), "ctx", story_id="S1")  # story-level, version None
    cache.set("editorial", K(a=5), "other", story_id="S2", version=2)
    cache.set("planner", K(a=6), "untagged")
    assert cache.invalidate_story("S1", from_version=2) == 3
    assert cache.get("editorial", K(a=1)) == "r1"       # older immutable version stays valid
    assert cache.get("editorial", K(a=2)) is None
    assert cache.get("series", K(a=4)) is None
    assert cache.get("editorial", K(a=5)) == "other"
    assert cache.invalidate_story("S1") == 1
    assert cache.get("editorial", K(a=1)) is None
    assert cache.get("planner", K(a=6)) == "untagged"


def test_invalidation_service_hooks(cache):
    inv = CacheInvalidationService(cache)
    cache.set("editorial", K(a=1), "r", story_id="S1", version=2)
    cache.set("safety", K(a=2), "r", story_id="S9", version=1)
    assert inv.on_new_version("S1", 2) == 1
    assert inv.on_policy_change() == 1
    cache.set("images", K(a=3), "i")
    assert inv.invalidate_namespace("images") == 1


def test_invalidation_survives_corrupt_files(cache, backend):
    cache.set("editorial", K(a=1), "r", story_id="S1", version=1)
    cache.set("editorial", K(a=2), "r", story_id="S1", version=1)
    _entry_path(backend, "editorial", K(a=2)).write_bytes(b"junk")
    assert cache.invalidate_story("S1") == 1


# ---------------- cleanup ----------------
def test_cleanup_removes_expired_corrupt_stale_locks_and_temp(settings, backend, cache, clock):
    cache.set("api", K(a=1), "exp", ttl=10)
    cache.set("writer", K(a=2), "live")
    cache.set("writer", K(a=3), "corrupt")
    _entry_path(backend, "writer", K(a=3)).write_bytes(b"{bad")
    lockd = backend.root / "_locks"
    lockd.mkdir(exist_ok=True)
    stale = lockd / "x.lock"
    stale.write_text("{}")
    old = time.time() - 10_000
    os.utime(stale, (old, old))
    tmp = _entry_path(backend, "writer", K(a=2)).with_name("orphan.json.abc.tmp")
    tmp.write_text("partial")
    os.utime(tmp, (old, old))
    clock.advance(11)
    res = CacheCleanupService(backend, settings, clock=clock).run()
    assert res["expired"] == 1 and res["corrupt"] == 1 and res["stale_locks"] == 1 and res["temp_files"] == 1
    assert cache.get("writer", K(a=2)) == "live"


def test_cleanup_enforces_size_cap_oldest_first(settings, backend, clock):
    s = settings.model_copy(update={"cache_max_size_mb": 1})
    c = CacheService(s, backend, clock=clock)
    pad = "x" * 300_000
    keys = [K(i=i) for i in range(5)]
    base = time.time() - 100
    for i, k in enumerate(keys):
        c.set("writer", k, {"p": pad})
        os.utime(_entry_path(backend, "writer", k), (base + i, base + i))
    res = CacheCleanupService(backend, s, clock=clock).run()
    assert res["evicted"] >= 1
    assert backend.size_bytes() <= 1024 * 1024
    assert c.get("writer", keys[-1]) is not None      # newest survives
    assert c.get("writer", keys[0]) is None           # oldest evicted


def test_cleanup_never_deletes_referenced_assets(settings, backend, clock, tmp_path):
    asset = tmp_path / "content" / "cover.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"png")
    c = CacheService(settings, backend, clock=clock)
    c.set("images", K(), {"asset_path": str(asset)}, ttl=1)
    clock.advance(5)
    res = CacheCleanupService(backend, settings, clock=clock).run()
    assert res["expired"] == 1 and asset.exists()


def test_cleanup_never_raises(settings):
    class Bad(FilesystemBackend):
        def iter_entries(self):
            raise OSError("boom")

    res = CacheCleanupService(Bad(settings.cache_path), settings).run()
    assert res["errors"] == 1
    assert CacheCleanupService(Bad(settings.cache_path), settings).interval_seconds == 24 * 3600


def test_stats_by_namespace(cache):
    cache.get("planner", K(a=1))
    cache.set("writer", K(a=2), 1)
    cache.get("writer", K(a=2))
    s = cache.stats()
    assert s["by_namespace"]["planner"]["misses"] == 1
    assert s["by_namespace"]["writer"]["hits"] == 1
    assert set(["hits", "misses", "errors", "size_mb", "by_namespace"]) <= set(s)
