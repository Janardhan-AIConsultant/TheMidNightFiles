"""Filesystem cache backend.

Layout: <root>/<namespace>/<key[:2]>/<key>.json ; locks in <root>/_locks/.
Writes are atomic (temp file + os.replace, retried on Windows sharing violations).
Locks are exclusive-create lock files holding pid + token; a lock whose mtime is older
than ``stale_after`` is treated as abandoned and broken. This provides mutual exclusion on
ONE host only; it is NOT a distributed lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .base import CacheBackend
from .cache_models import CacheCorruptError, CacheEntry, CacheLockTimeout

_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
LOCK_DIR = "_locks"
TMP_SUFFIX = ".tmp"


def _checksum(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _replace_with_retry(src: Path, dst: Path, attempts: int = 8) -> None:
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:  # Windows: target briefly held open by another reader / AV scanner
            if i == attempts - 1:
                raise
            time.sleep(0.01 * (i + 1))


def _unlink(p: Path) -> bool:
    for i in range(5):
        try:
            p.unlink()
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            time.sleep(0.01 * (i + 1))
    return False


class FilesystemBackend(CacheBackend):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------
    def _path(self, namespace: str, key: str) -> Path:
        if not _SAFE.match(namespace) or not _SAFE.match(key) or namespace == LOCK_DIR or ".." in namespace + key:
            raise ValueError(f"unsafe cache namespace/key: {namespace!r}/{key!r}")
        return self.root / namespace / key[:2] / f"{key}.json"

    # -- crud ----------------------------------------------------------
    def get(self, namespace: str, key: str) -> CacheEntry | None:
        p = self._path(namespace, key)
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            return None
        try:
            return self._decode(raw, namespace, key)
        except CacheCorruptError:
            _unlink(p)
            raise

    @staticmethod
    def _decode(raw: bytes, namespace: str, key: str) -> CacheEntry:
        try:
            d = json.loads(raw.decode("utf-8"))
            if d["namespace"] != namespace or d["key"] != key or _checksum(d["value"]) != d["checksum"]:
                raise ValueError("identity/checksum mismatch")
            return CacheEntry(namespace, key, d["value"], float(d["created_at"]),
                              None if d["expires_at"] is None else float(d["expires_at"]),
                              d.get("story_id"), d.get("version"), d.get("meta") or {})
        except Exception as exc:
            raise CacheCorruptError(f"corrupt cache entry {namespace}/{key}: {exc}") from exc

    def put(self, entry: CacheEntry) -> None:
        p = self._path(entry.namespace, entry.key)
        doc = {"namespace": entry.namespace, "key": entry.key, "created_at": entry.created_at,
               "expires_at": entry.expires_at, "story_id": entry.story_id, "version": entry.version,
               "meta": entry.meta, "value": entry.value, "checksum": _checksum(entry.value)}
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")  # TypeError if not serialisable
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex}{TMP_SUFFIX}")
        try:
            tmp.write_bytes(data)
            _replace_with_retry(tmp, p)
        finally:
            if tmp.exists():
                _unlink(tmp)

    def delete(self, namespace: str, key: str) -> bool:
        return _unlink(self._path(namespace, key))

    def iter_entries(self) -> Iterator[tuple[str, str, CacheEntry | None]]:
        if not self.root.exists():
            return
        for ns_dir in sorted(self.root.iterdir()):
            if not ns_dir.is_dir() or ns_dir.name == LOCK_DIR:
                continue
            for f in list(ns_dir.glob("*/*.json")):
                key = f.stem
                try:
                    entry = self._decode(f.read_bytes(), ns_dir.name, key)
                except FileNotFoundError:
                    continue
                except CacheCorruptError:
                    entry = None
                except OSError:
                    continue
                yield ns_dir.name, key, entry

    def size_bytes(self) -> int:
        total = 0
        for dirpath, _dirs, files in os.walk(self.root):
            if Path(dirpath).name == LOCK_DIR:
                continue
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total

    def entry_sort_key(self, namespace: str, key: str) -> float:
        try:
            return self._path(namespace, key).stat().st_mtime
        except OSError:
            return 0.0

    # -- locking -------------------------------------------------------
    def _lock_path(self, namespace: str, key: str) -> Path:
        self._path(namespace, key)  # validates names
        d = self.root / LOCK_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{namespace}.{key}.lock"

    @contextmanager
    def lock(self, namespace: str, key: str, timeout: float, stale_after: float):
        lp = self._lock_path(namespace, key)
        deadline = time.monotonic() + timeout
        token = uuid.uuid4().hex
        delay = 0.005
        while True:
            try:
                fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, json.dumps({"pid": os.getpid(), "token": token, "ts": time.time()}).encode())
                finally:
                    os.close(fd)
                break
            except (FileExistsError, PermissionError):
                # PermissionError: Windows reports this while a file is pending delete.
                try:
                    if time.time() - lp.stat().st_mtime > stale_after:
                        _unlink(lp)  # abandoned lock (crashed / cancelled holder)
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise CacheLockTimeout(f"timed out acquiring lock {namespace}/{key}")
                time.sleep(delay)
                delay = min(delay * 2, 0.1)
        try:
            yield
        finally:
            try:  # only remove if still ours (it may have been broken as stale and re-taken)
                if json.loads(lp.read_text()).get("token") == token:
                    _unlink(lp)
            except Exception:
                pass

    def cleanup_locks(self, stale_after: float) -> int:
        n = 0
        d = self.root / LOCK_DIR
        if d.exists():
            for f in d.glob("*.lock"):
                try:
                    if time.time() - f.stat().st_mtime > stale_after and _unlink(f):
                        n += 1
                except OSError:
                    pass
        return n

    def cleanup_temp(self, older_than: float) -> int:
        n = 0
        for f in self.root.glob(f"*/*/*{TMP_SUFFIX}"):
            try:
                if time.time() - f.stat().st_mtime > older_than and _unlink(f):
                    n += 1
            except OSError:
                pass
        return n
