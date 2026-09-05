"""Tests for bookstore library-location resolution and precedence."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.bookstore.config import (
    ENV_LIBRARY_DIR,
    LibraryLocation,
    resolve_locations,
)


def _init_catalog(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "library.db").touch()


def _project(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_env_var_beats_project(tmp_path, monkeypatch):
    repo = _project(tmp_path)
    env_dir = tmp_path / "custom-lib"
    monkeypatch.setenv(ENV_LIBRARY_DIR, str(env_dir))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    locs = resolve_locations(cwd=repo)
    assert locs[0].scope == "project"
    assert locs[0].root == env_dir
    assert locs[-1].scope == "global"


def test_project_scope_from_git_root(tmp_path, monkeypatch):
    repo = _project(tmp_path)
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.delenv(ENV_LIBRARY_DIR, raising=False)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    locs = resolve_locations(cwd=nested)
    assert locs[0].root == repo / ".parrot" / "library"
    assert locs[1].root == tmp_path / "home" / "library"


def test_no_git_root_yields_global_only(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_LIBRARY_DIR, raising=False)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    lone = tmp_path / "nowhere"
    lone.mkdir()
    locs = resolve_locations(cwd=lone)
    assert [loc.scope for loc in locs] == ["global"]


def test_dedupe_env_pointing_at_global(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.setenv(ENV_LIBRARY_DIR, str(home / "library"))
    locs = resolve_locations(cwd=tmp_path)
    assert len(locs) == 1
    assert locs[0].scope == "project"


def test_require_exists_filters_uninitialized(tmp_path, monkeypatch):
    repo = _project(tmp_path)
    home = tmp_path / "home"
    monkeypatch.delenv(ENV_LIBRARY_DIR, raising=False)
    monkeypatch.setenv("PARROT_HOME", str(home))
    _init_catalog(home / "library")
    locs = resolve_locations(cwd=repo, require_exists=True)
    assert [loc.scope for loc in locs] == ["global"]


def test_location_paths():
    loc = LibraryLocation(scope="project", root=Path("/x/.parrot/library"))
    assert loc.db_path == Path("/x/.parrot/library/library.db")
    assert loc.trees_dir == Path("/x/.parrot/library/trees")
