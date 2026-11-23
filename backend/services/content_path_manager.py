"""Central, safe path construction and atomic writes for story content."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Optional, Union

STORY_ID_RE = re.compile(r"^STORY-\d{4,}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ALLOWED_EXTENSIONS = {".md", ".json", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".mp4"}
ASSET_CATEGORIES = {"images", "images/thumbnails", "videos", "distribution"}


class PathSecurityError(ValueError):
    pass


class AssetProtectedError(Exception):
    pass


class ContentPathManager:
    def __init__(self, root: Union[str, Path], is_referenced: Optional[Callable[[Path], bool]] = None):
        self.root = Path(root).resolve()
        self.stories_root = self.root / "stories"
        self.is_referenced = is_referenced

    # -- validation ---------------------------------------------------------
    @staticmethod
    def validate_story_id(story_id: str) -> str:
        if not isinstance(story_id, str) or not STORY_ID_RE.match(story_id):
            raise PathSecurityError(f"invalid story id: {story_id!r}")
        return story_id

    @staticmethod
    def validate_name(name: str) -> str:
        if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
            raise PathSecurityError(f"invalid file name: {name!r}")
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise PathSecurityError(f"extension not allowed: {name!r}")
        return name

    def _check_inside(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.stories_root)
        except ValueError:
            raise PathSecurityError(f"path escapes content root: {path}") from None
        return resolved

    # -- path construction --------------------------------------------------
    def story_dir(self, story_id: str) -> Path:
        self.validate_story_id(story_id)
        return self._check_inside(self.stories_root / story_id)

    def revision_dir(self, story_id: str, version: int) -> Path:
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise PathSecurityError(f"invalid version: {version!r}")
        return self._check_inside(self.story_dir(story_id) / "revisions" / f"v{version:03d}")

    def revision_path(self, story_id: str, version: int, name: str) -> Path:
        self.validate_name(name)
        return self._check_inside(self.revision_dir(story_id, version) / name)

    def asset_path(self, story_id: str, category: str, name: str) -> Path:
        if category not in ASSET_CATEGORIES:
            raise PathSecurityError(f"invalid asset category: {category!r}")
        self.validate_name(name)
        return self._check_inside(self.story_dir(story_id) / Path(*category.split("/")) / name)

    # -- IO -------------------------------------------------------------------
    def write_atomic(self, path: Union[str, Path], data: Union[str, bytes], overwrite: bool = False) -> Path:
        """Write via temp file + atomic rename. Never overwrites unless allowed."""
        target = self._check_inside(Path(path))
        if target.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise PathSecurityError(f"extension not allowed: {target.name}")
        if "revisions" in target.parts:
            overwrite = False  # revisions are immutable
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        if target.exists() and self._referenced(target):
            raise AssetProtectedError(f"referenced asset cannot be overwritten: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            if overwrite:
                os.replace(tmp, target)
            else:
                os.link(tmp, target)  # atomic, fails if target appeared meanwhile
                os.unlink(tmp)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return target

    def exists(self, path: Union[str, Path]) -> bool:
        return self._check_inside(Path(path)).is_file()

    def read_text(self, path: Union[str, Path]) -> str:
        p = self._check_inside(Path(path))
        if not p.is_file():
            raise FileNotFoundError(str(p))
        return p.read_text(encoding="utf-8")

    def delete_asset(self, path: Union[str, Path]) -> None:
        p = self._check_inside(Path(path))
        if "revisions" in p.parts:
            raise AssetProtectedError("revision files are immutable and cannot be deleted")
        if self._referenced(p):
            raise AssetProtectedError(f"asset is referenced or published: {p}")
        p.unlink()

    def _referenced(self, path: Path) -> bool:
        return bool(self.is_referenced and self.is_referenced(path))
