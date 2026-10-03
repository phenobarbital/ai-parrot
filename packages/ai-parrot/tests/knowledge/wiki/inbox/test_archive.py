"""FEAT-626 archive regression and failure-path tests."""
from datetime import date
import errno
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from parrot.knowledge.wiki.inbox import archive as archive_mod
from parrot.knowledge.wiki.inbox.archive import archive_destination, archive_original, repoint_source
from parrot.knowledge.wiki.sources import SourceCollectionManager

TODAY = date(2026, 10, 3)
_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *_ID, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _dest(archive_dir: Path, source: Path, **kw) -> Path:
    params = dict(rejected=False, rejected_subdir="rejected", date_format="%Y-%m-%d", today=TODAY)
    params.update(kw)
    return archive_destination(archive_dir, source, **params)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    return root


def test_archive_destination_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Produce base, -1 and -2 paths; reject date-based directory traversal."""
    arch = tmp_path / "arch"
    arch.mkdir()
    src = Path("notes.tar.md")
    first = _dest(arch, src)
    assert first == arch / "notes.tar.2026-10-03.md"
    first.write_text("x")
    second = _dest(arch, src)
    assert second.name == "notes.tar.2026-10-03-1.md"
    second.write_text("x")
    assert _dest(arch, src).name == "notes.tar.2026-10-03-2.md"
    assert _dest(arch, src, rejected=True).parent == arch / "rejected"
    with pytest.raises(ValueError):
        _dest(arch, src, date_format="../%Y")
    with pytest.raises(ValueError):
        _dest(arch, src, date_format="%Y/%m")
    with pytest.raises(ValueError):
        _dest(arch, src, rejected=True, rejected_subdir="../x")


def test_archive_original_git_staging(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tracked files stage deletion; untracked and missing git do not."""
    tracked = repo / "t.md"
    tracked.write_text("t")
    _git(repo, "add", "t.md")
    _git(repo, "commit", "-q", "-m", "init")
    untracked = repo / "u.md"
    untracked.write_text("u")
    arch = repo / "arch"

    res = archive_original(repo, tracked, _dest(arch, tracked), stage_git=True)
    assert res.staged_git is True and res.destination.exists() and not tracked.exists()
    assert "D  t.md" in _git(repo, "status", "--porcelain")

    res = archive_original(repo, untracked, _dest(arch, untracked), stage_git=True)
    assert res.staged_git is False and res.destination.exists()

    other = repo / "o.md"
    other.write_text("o")
    res = archive_original(repo, other, _dest(arch, other), stage_git=False)
    assert res.staged_git is False

    def _no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(archive_mod.subprocess, "run", _no_git)
    gone = repo / "g.md"
    gone.write_text("g")
    res = archive_original(repo, gone, _dest(arch, gone), stage_git=True)
    assert res.staged_git is False and res.destination.read_text() == "g"


def test_archive_cross_filesystem_and_no_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover EXDEV fallback and destination collisions without data loss."""
    src = tmp_path / "a.md"
    src.write_text("new")
    dest = tmp_path / "arch" / "a.2026-10-03.md"

    def _exdev(*a, **k):
        raise OSError(errno.EXDEV, "cross-device")

    calls: list[tuple] = []
    real_move = shutil.move

    def _move(s, d):
        calls.append((s, d))
        return real_move(s, d)

    monkeypatch.setattr(archive_mod.os, "replace", _exdev)
    monkeypatch.setattr(archive_mod.shutil, "move", _move)
    res = archive_original(tmp_path, src, dest, stage_git=False)
    assert calls and res.destination.read_text() == "new" and not src.exists()

    src2 = tmp_path / "b.md"
    src2.write_text("keep")
    with pytest.raises(FileExistsError):
        archive_original(tmp_path, src2, dest, stage_git=False)
    assert dest.read_text() == "new" and src2.read_text() == "keep"

    def _eperm(*a, **k):
        raise OSError(errno.EPERM, "nope")

    monkeypatch.setattr(archive_mod.os, "replace", _eperm)
    calls.clear()
    with pytest.raises(OSError):
        archive_original(tmp_path, src2, tmp_path / "arch" / "c.md", stage_git=False)
    assert not calls and src2.exists()


def test_archive_repoints_source_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Keep source_id/external_id stable and make is_stale false for archived bytes."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    mgr = SourceCollectionManager(sources_dir, db_path=tmp_path / "wiki.db")
    doc = tmp_path / "doc.md"
    doc.write_text("hello")
    entry = mgr.add_source(doc, external_id="fireflies:abc")
    res = archive_original(tmp_path, doc, _dest(tmp_path / "arch", doc), stage_git=False)
    repoint_source(mgr, entry.source_id, res.destination)
    updated = mgr.get_source(entry.source_id)
    assert updated is not None
    assert updated.source_uri == str(res.destination.resolve())
    assert updated.external_id == "fireflies:abc"
    assert mgr.is_stale(entry.source_id) is False

    # Recoverable errors are logged, never raised, and never unarchive.
    repoint_source(mgr, entry.source_id, tmp_path / "missing.md")
    assert res.destination.exists()
    assert any("could not repoint" in r.message for r in caplog.records)


def test_archive_never_commits(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert exact git argv and unchanged git HEAD after a tracked move."""
    f = repo / "t.md"
    f.write_text("t")
    _git(repo, "add", "t.md")
    _git(repo, "commit", "-q", "-m", "init")
    head = _git(repo, "rev-parse", "HEAD")

    seen: list[list[str]] = []
    real_run = subprocess.run

    def _spy(cmd, *a, **k):
        seen.append(list(cmd))
        assert k.get("shell") is not True
        if cmd[3] == "rm":
            assert os.path.exists(repo / "arch" / "t.2026-10-03.md")  # move preceded staging
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(archive_mod.subprocess, "run", _spy)
    res = archive_original(repo, f, _dest(repo / "arch", f), stage_git=True)
    assert res.staged_git is True
    assert ["git", "-C", str(repo), "rm", "--cached", "--quiet", "--", "t.md"] in seen
    assert all("commit" not in c for c in seen)
    assert _git(repo, "rev-parse", "HEAD") == head
