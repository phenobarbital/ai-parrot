"""Brief-aware index discovery — FEAT-698 / TASK-4431."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.background import ValidationSupervisor
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.task_scheduler import TaskScheduler, iter_index_files, resolve_index_path


def _write(path: Path, header: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(header), encoding="utf-8")
    return path


def _brief_header(slug: str = "demo-fix", key: str = "cs-224") -> dict:
    return {
        "feature": slug,
        "feature_id": f"BRIEF-{key}",
        "spec": f"sdd/briefs/{slug}.brief.md",
        "type": "brief",
        "base_branch": "main",
        "parallel_semantics": "exclusive",
        "tasks": [
            {
                "id": f"HOTFIX-{key}-1",
                "status": "pending",
                "depends_on": [],
                "file": f"sdd/briefs/{slug}/tasks/HOTFIX-{key}-1-x.md",
            }
        ],
    }


def _feature_header(slug: str, fid: str = "FEAT-001") -> dict:
    return {
        "feature": slug,
        "feature_id": fid,
        "spec": f"sdd/specs/{slug}.spec.md",
        "type": "feature",
        "base_branch": "dev",
        "tasks": [{"id": "TASK-0001", "status": "pending", "depends_on": []}],
    }


def _brief(wt: Path) -> Path:
    return _write(wt / "sdd" / "briefs" / "demo-fix.index.json", _brief_header())


def test_resolves_brief_index_when_no_feature_index(tmp_path: Path) -> None:
    brief = _brief(tmp_path)
    assert resolve_index_path(tmp_path, "demo-fix") == brief
    assert resolve_index_path(tmp_path, "missing") == tmp_path / "sdd" / "tasks" / "index" / "missing.json"


def test_feature_index_wins_over_brief_index(tmp_path: Path) -> None:
    _brief(tmp_path)
    feat = _write(tmp_path / "sdd" / "tasks" / "index" / "demo-fix.json", _feature_header("demo-fix"))
    assert resolve_index_path(str(tmp_path), "demo-fix") == feat


def test_iter_index_files_order_and_orphans_skipped(tmp_path: Path) -> None:
    idx = tmp_path / "sdd" / "tasks" / "index"
    b = _write(idx / "b.json", _feature_header("b"))
    a = _write(idx / "a.json", _feature_header("a"))
    _write(idx / "_orphans.json", {"tasks": []})
    briefs = tmp_path / "sdd" / "briefs"
    z = _write(briefs / "z.index.json", _brief_header("z"))
    y = _write(briefs / "y.index.json", _brief_header("y"))
    _write(briefs / "y.brief.json", {})
    assert iter_index_files(tmp_path) == [a, b, y, z]


def test_iter_tolerates_missing_dirs(tmp_path: Path) -> None:
    assert iter_index_files(tmp_path) == []


def test_from_worktree_loads_brief_scheduler(tmp_path: Path) -> None:
    _brief(tmp_path)
    sched = TaskScheduler.from_worktree(str(tmp_path), "demo-fix")
    assert sched is not None
    assert [t.id for t in sched.all_tasks()] == ["HOTFIX-cs-224-1"]


@pytest.mark.parametrize("feature", ["BRIEF-cs-224", "demo-fix"])
async def test_engine_resolve_feature_matches_brief_by_feature_id(tmp_path: Path, noop_probe, feature: str) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    await asyncio.to_thread(subprocess.run, ["git", "init", "-q", "-b", "hotfix-x", str(wt)], check=True)
    await asyncio.to_thread(
        subprocess.run,
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    _brief(wt)
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(tmp_path),
    )
    ctx = await engine._resolve_feature(feature, str(wt))
    assert ctx.index_path.endswith("sdd/briefs/demo-fix.index.json")
    assert ctx.feature_id == "BRIEF-cs-224"


def test_background_resolve_feature_id_returns_brief_id(tmp_path: Path) -> None:
    _brief(tmp_path)
    assert ValidationSupervisor._resolve_feature_id(tmp_path, "demo-fix") == "BRIEF-cs-224"
    assert ValidationSupervisor._resolve_feature_id(tmp_path, "BRIEF-cs-224") == "BRIEF-cs-224"
