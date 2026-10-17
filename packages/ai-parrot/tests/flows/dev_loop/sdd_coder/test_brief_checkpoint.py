"""sdd-coder checkpoint + scheduler accept a BRIEF-<KEY> index — FEAT-698 / TASK-4438."""

from __future__ import annotations

import json
from pathlib import Path

from parrot.flows.dev_loop.sdd_coder import checkpoint
from parrot.flows.dev_loop.task_scheduler import TaskScheduler

_SLUG = "fix-null-deref"


def _write_brief_index(wt: Path) -> None:
    index = wt / "sdd" / "briefs" / f"{_SLUG}.index.json"
    index.parent.mkdir(parents=True)
    task = {
        "id": "HOTFIX-abc123-1",
        "slug": "fix",
        "title": "Fix",
        "feature_id": "BRIEF-abc123",
        "feature": _SLUG,
        "status": "pending",
        "depends_on": [],
        "parallel": True,
        "file": f"sdd/briefs/{_SLUG}/tasks/HOTFIX-abc123-1-fix.md",
    }
    index.write_text(
        json.dumps(
            {
                "feature": _SLUG,
                "feature_id": "BRIEF-abc123",
                "spec": f"sdd/briefs/{_SLUG}.brief.md",
                "type": "brief",
                "base_branch": "dev",
                "tasks": [task],
            }
        ),
        encoding="utf-8",
    )


def test_checkpoint_reads_brief_index_header(tmp_path: Path) -> None:
    _write_brief_index(tmp_path)

    path, _raw, data = checkpoint._load_index_sync(tmp_path, _SLUG)

    assert path.name == f"{_SLUG}.index.json"
    assert data["feature_id"].startswith("BRIEF-")
    assert data["base_branch"]
    assert data["spec"]


def test_scheduler_from_worktree_sees_hotfix_tasks(tmp_path: Path) -> None:
    _write_brief_index(tmp_path)

    scheduler = TaskScheduler.from_worktree(tmp_path, _SLUG)

    assert scheduler is not None
    assert [t.id for t in scheduler.next_wave()] == ["HOTFIX-abc123-1"]
