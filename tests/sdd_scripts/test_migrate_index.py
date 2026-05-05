"""Unit tests for ``scripts.sdd.migrate_index`` — FEAT-145 / TASK-995."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.sdd.migrate_index import migrate


@pytest.fixture
def monolith(tmp_path: Path) -> Path:
    """Synthetic monolith: current feature, two prior, FEAT-142 collision, one orphan."""
    src = tmp_path / "src.json"
    src.write_text(
        json.dumps(
            {
                "feature": "current-feature",
                "feature_id": "FEAT-100",
                "spec": "sdd/specs/current-feature.spec.md",
                "created_at": "2026-05-01T00:00:00+00:00",
                "previous_features": [
                    {
                        "feature": "prior-a",
                        "feature_id": "FEAT-099",
                        "spec": "sdd/specs/prior-a.spec.md",
                        "created_at": "2026-04-01T00:00:00+00:00",
                    },
                    {
                        "feature": "prior-b",
                        "feature_id": "FEAT-098",
                        "spec": "sdd/specs/prior-b.spec.md",
                        "created_at": "2026-03-01T00:00:00+00:00",
                    },
                    # Two distinct specs sharing FEAT-142 — must NOT collide on file name.
                    {
                        "feature": "feat142-alpha",
                        "feature_id": "FEAT-142",
                        "spec": "sdd/specs/feat142-alpha.spec.md",
                        "created_at": "2026-02-01T00:00:00+00:00",
                    },
                    {
                        "feature": "feat142-beta",
                        "feature_id": "FEAT-142",
                        "spec": "sdd/specs/feat142-beta.spec.md",
                        "created_at": "2026-02-15T00:00:00+00:00",
                    },
                ],
                "tasks": [
                    {"id": "TASK-001", "feature": "current-feature", "feature_id": "FEAT-100", "status": "pending"},
                    {"id": "TASK-002", "feature": "prior-a", "feature_id": "FEAT-099", "status": "done", "completed_at": "2026-04-15T00:00:00+00:00"},
                    {"id": "TASK-003", "feature": "prior-a", "feature_id": "FEAT-099", "status": "done", "completed_at": "2026-04-20T00:00:00+00:00"},
                    {"id": "TASK-004", "feature": "prior-b", "feature_id": "FEAT-098", "status": "done", "completed_at": "2026-03-15T00:00:00+00:00"},
                    {"id": "TASK-010", "feature": "feat142-alpha", "feature_id": "FEAT-142", "status": "done", "completed_at": "2026-02-10T00:00:00+00:00"},
                    {"id": "TASK-011", "feature": "feat142-beta", "feature_id": "FEAT-142", "status": "done", "completed_at": "2026-02-20T00:00:00+00:00"},
                    {"id": "TASK-099", "status": "pending"},  # orphan — no feature
                ],
            },
            indent=2,
        )
    )
    return src


def test_groups_by_feature_slug(monolith: Path, tmp_path: Path) -> None:
    """Each unique ``feature`` slug becomes its own per-spec file."""
    dest = tmp_path / "out"
    migrate(monolith, dest)
    assert (dest / "current-feature.json").exists()
    assert (dest / "prior-a.json").exists()
    assert (dest / "prior-b.json").exists()


def test_feat142_collision_split_by_slug(monolith: Path, tmp_path: Path) -> None:
    """Two specs sharing ``feature_id`` but with different slugs must NOT overwrite."""
    dest = tmp_path / "out"
    migrate(monolith, dest)
    assert (dest / "feat142-alpha.json").exists()
    assert (dest / "feat142-beta.json").exists()
    alpha = json.loads((dest / "feat142-alpha.json").read_text())
    beta = json.loads((dest / "feat142-beta.json").read_text())
    assert alpha["feature_id"] == "FEAT-142"
    assert beta["feature_id"] == "FEAT-142"
    assert alpha["spec"] != beta["spec"]


def test_orphans_routed_with_warning(monolith: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Tasks with no feature land in ``_orphans.json`` and emit stderr warnings."""
    dest = tmp_path / "out"
    migrate(monolith, dest)
    orph = json.loads((dest / "_orphans.json").read_text())
    assert orph["feature"] == "_orphans"
    assert orph["feature_id"] is None
    assert len(orph["tasks"]) == 1
    assert orph["tasks"][0]["id"] == "TASK-099"
    captured = capsys.readouterr()
    assert "TASK-099" in captured.err
    assert "_orphans.json" in captured.err


def test_idempotent(monolith: Path, tmp_path: Path) -> None:
    """Re-running on the same input must produce byte-identical output."""
    dest = tmp_path / "out"
    migrate(monolith, dest)
    first = {p.name: p.read_bytes() for p in dest.iterdir()}
    migrate(monolith, dest)
    second = {p.name: p.read_bytes() for p in dest.iterdir()}
    assert first == second


def test_does_not_modify_source(monolith: Path, tmp_path: Path) -> None:
    """Source monolith must be preserved byte-for-byte."""
    original = monolith.read_bytes()
    migrate(monolith, tmp_path / "out")
    assert monolith.read_bytes() == original


def test_completed_at_set_when_all_done(monolith: Path, tmp_path: Path) -> None:
    """``completed_at`` is the max of task timestamps when every task is done; else None."""
    dest = tmp_path / "out"
    migrate(monolith, dest)

    prior_a = json.loads((dest / "prior-a.json").read_text())
    # All prior-a tasks done; max completed_at is TASK-003's 2026-04-20
    assert prior_a["completed_at"] == "2026-04-20T00:00:00+00:00"

    current = json.loads((dest / "current-feature.json").read_text())
    # current-feature has a pending task — completed_at must be None
    assert current["completed_at"] is None


def test_dry_run_writes_nothing(monolith: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--dry-run`` keeps stderr warnings but writes no files."""
    dest = tmp_path / "out"
    migrate(monolith, dest, dry_run=True)
    assert not dest.exists()
    captured = capsys.readouterr()
    assert "TASK-099" in captured.err  # orphan warning still emitted
