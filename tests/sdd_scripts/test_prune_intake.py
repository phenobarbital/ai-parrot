"""Tests for scripts/sdd/prune_intake.py (FEAT-577, spec §4 Module 9)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.sdd.prune_intake import claim_daily_slot, find_stale, main, prune

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "sdd" / "state" / ".intake"
    r.mkdir(parents=True)
    return r


def _run(root: Path, name: str, age_days: float | None) -> Path:
    """Create a staged run whose intake.json updated_at is ``age_days`` old (None ⇒ no intake.json)."""
    d = root / name
    d.mkdir()
    if age_days is not None:
        ts = (_NOW - timedelta(days=age_days)).isoformat()
        (d / "intake.json").write_text(json.dumps({"updated_at": ts}), encoding="utf-8")
    return d


def test_find_stale_uses_updated_at(root: Path, tmp_path: Path) -> None:
    stale_run = _run(root, "feat-x-RUN1", 11)
    fresh_run = _run(root, "feat-y-RUN2", 3)
    stale = find_stale(root, now=_NOW, repo_root=tmp_path)
    assert [s.path for s in stale] == [stale_run]
    assert stale[0].age_source == "updated_at"
    assert stale[0].age_days == pytest.approx(11.0, abs=0.01)
    assert fresh_run.exists()


def test_find_stale_falls_back_to_mtime(root: Path, tmp_path: Path) -> None:
    d = _run(root, "feat-z-RUN3", None)
    old_time = (_NOW - timedelta(days=15)).timestamp()
    os.utime(d, (old_time, old_time))
    stale = find_stale(root, now=_NOW, repo_root=tmp_path)
    assert len(stale) == 1
    assert stale[0].path == d
    assert stale[0].age_source == "mtime"
    assert stale[0].age_days == pytest.approx(15.0, abs=0.01)


def test_prune_dry_run_deletes_nothing(root: Path, tmp_path: Path) -> None:
    stale_run = _run(root, "feat-a-RUN1", 20)
    result = prune(root, apply=False, now=_NOW, repo_root=tmp_path)
    assert len(result) == 1
    assert stale_run.exists()


def test_prune_apply_deletes_only_stale_children(root: Path, tmp_path: Path) -> None:
    stale_run = _run(root, "feat-a-RUN1", 20)
    fresh_run = _run(root, "feat-b-RUN2", 1)
    root_file = root / "not-a-dir.txt"
    root_file.write_text("keep me", encoding="utf-8")

    target = root / "outside-target"
    target.mkdir()
    symlinked = root / "feat-c-RUN3"
    symlinked.symlink_to(target, target_is_directory=True)

    result = prune(root, apply=True, now=_NOW, repo_root=tmp_path)

    assert [r.path for r in result] == [stale_run]
    assert not stale_run.exists()
    assert fresh_run.exists()
    assert root_file.exists()
    assert symlinked.is_symlink()
    assert target.exists()


def test_prune_rejects_unsafe_root(tmp_path: Path) -> None:
    unsafe_root = tmp_path / "not-intake"
    unsafe_root.mkdir()
    with pytest.raises(ValueError):
        prune(unsafe_root, apply=True)
    assert unsafe_root.exists()

    exit_code = main(["--root", str(unsafe_root), "--apply"])
    assert exit_code == 2
    assert unsafe_root.exists()


def test_prune_rejects_correctly_suffixed_root_outside_repo(tmp_path: Path) -> None:
    """A root with the right ``sdd/state/.intake`` suffix but outside the declared repo boundary
    must still be rejected — regression for the CRITICAL ``_check_root`` bypass (FEAT-577 review):
    a root that only checked the last 3 path components let ``--root /anywhere/sdd/state/.intake``
    pass and get pruned even when it resolved outside any repository.
    """
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    outside_root = tmp_path / "elsewhere" / "sdd" / "state" / ".intake"
    outside_root.mkdir(parents=True)
    stale_run = _run(outside_root, "feat-x-RUN1", 20)

    with pytest.raises(ValueError):
        find_stale(outside_root, now=_NOW, repo_root=fake_repo)
    with pytest.raises(ValueError):
        prune(outside_root, apply=True, now=_NOW, repo_root=fake_repo)
    assert stale_run.exists()


def test_prune_missing_root_is_noop(tmp_path: Path) -> None:
    missing_root = tmp_path / "sdd" / "state" / ".intake"
    assert find_stale(missing_root) == []
    assert prune(missing_root, apply=True) == []


def test_daily_gate_skips_within_24h(tmp_path: Path) -> None:
    stamp = tmp_path / "stamp" / "sdd-intake-prune.stamp"
    stamp.parent.mkdir(parents=True)
    stamp.touch()
    recent = (_NOW - timedelta(hours=1)).timestamp()
    os.utime(stamp, (recent, recent))
    assert claim_daily_slot(stamp, now=_NOW) is False


def test_daily_gate_first_run_creates_stamp(tmp_path: Path) -> None:
    stamp = tmp_path / "stamp" / "sdd-intake-prune.stamp"
    assert not stamp.exists()
    assert claim_daily_slot(stamp, now=_NOW) is True
    assert stamp.exists()
    mtime = datetime.fromtimestamp(stamp.stat().st_mtime, tz=timezone.utc)
    assert mtime == _NOW

    # A second claim right after should be denied (within 24h of the stamp we just wrote).
    assert claim_daily_slot(stamp, now=_NOW + timedelta(hours=1)) is False
    # But after 24h it should be claimable again.
    assert claim_daily_slot(stamp, now=_NOW + timedelta(hours=25)) is True


def test_gitignore_ignores_intake_staging() -> None:
    gitignore = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "sdd/state/.intake/" in gitignore.splitlines()


def test_sdd_status_stays_read_only() -> None:
    command_doc = (_REPO_ROOT / ".claude" / "commands" / "sdd-status.md").read_text(encoding="utf-8")
    workflow_doc = (_REPO_ROOT / ".agent" / "workflows" / "sdd-status.md").read_text(encoding="utf-8")
    assert "prune_intake" not in command_doc
    assert "prune_intake" not in workflow_doc
