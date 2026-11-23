import pytest

from backend.services.content_path_manager import (AssetProtectedError, ContentPathManager,
                                                   PathSecurityError)


@pytest.fixture()
def pm(tmp_path):
    return ContentPathManager(tmp_path / "content")


@pytest.mark.parametrize("sid", ["../x", "STORY-1", "story-0001", "STORY-0001/..", "", "STORY-0001\\x"])
def test_bad_story_ids(pm, sid):
    with pytest.raises(PathSecurityError):
        pm.story_dir(sid)


@pytest.mark.parametrize("name", ["../a.md", "a/b.md", "..\\a.md", "a.exe", "noext", ".hidden.md", "a..b.md"])
def test_bad_names(pm, name):
    with pytest.raises(PathSecurityError):
        pm.revision_path("STORY-0001", 1, name)


def test_bad_version_and_category(pm):
    for v in (0, -1, "1", True):
        with pytest.raises(PathSecurityError):
            pm.revision_dir("STORY-0001", v)
    with pytest.raises(PathSecurityError):
        pm.asset_path("STORY-0001", "../..", "a.png")


def test_paths_inside_root(pm):
    p = pm.revision_path("STORY-0001", 2, "final.md")
    assert p.parts[-3:] == ("v002", "final.md") or p.name == "final.md"
    assert pm.stories_root in p.parents
    assert pm.asset_path("STORY-0001", "images/thumbnails", "t.png").parent.name == "thumbnails"


def test_atomic_write_no_overwrite_and_no_temp_left(pm):
    p = pm.asset_path("STORY-0001", "images", "cover.png")
    pm.write_atomic(p, b"one")
    with pytest.raises(FileExistsError):
        pm.write_atomic(p, b"two")
    assert p.read_bytes() == b"one"
    assert [x.name for x in p.parent.iterdir()] == ["cover.png"]
    pm.write_atomic(p, b"three", overwrite=True)
    assert p.read_bytes() == b"three"


def test_revision_files_immutable(pm):
    p = pm.revision_path("STORY-0001", 1, "original.md")
    pm.write_atomic(p, "x")
    with pytest.raises(FileExistsError):
        pm.write_atomic(p, "y", overwrite=True)
    with pytest.raises(AssetProtectedError):
        pm.delete_asset(p)


def test_referenced_assets_protected(tmp_path):
    protected = set()
    pm = ContentPathManager(tmp_path / "c", is_referenced=lambda p: p in protected)
    p = pm.asset_path("STORY-0001", "images", "a.png")
    pm.write_atomic(p, b"1")
    protected.add(p)
    with pytest.raises(AssetProtectedError):
        pm.delete_asset(p)
    with pytest.raises(AssetProtectedError):
        pm.write_atomic(p, b"2", overwrite=True)
    protected.clear()
    pm.delete_asset(p)
    assert not p.exists()


def test_write_outside_root_rejected(pm, tmp_path):
    with pytest.raises(PathSecurityError):
        pm.write_atomic(tmp_path / "evil.md", "x")
    with pytest.raises(PathSecurityError):
        pm.write_atomic(pm.story_dir("STORY-0001") / ".." / ".." / "evil.md", "x")
