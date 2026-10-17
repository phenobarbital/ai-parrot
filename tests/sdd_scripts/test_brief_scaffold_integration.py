"""End-to-end brief scaffold in a real worktree — FEAT-698 / TASK-4438."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.sdd.brief_meta import BriefMeta, emit_brief_frontmatter, parse_brief, write_brief_index
from scripts.sdd.ensure_worktree import main

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A clone with an ``origin`` remote and a pushed ``dev`` branch."""
    origin_dir = tmp_path / "origin.git"
    work_dir = tmp_path / "work"

    subprocess.run(["git", "init", "--bare", str(origin_dir)], check=True)
    subprocess.run(["git", "init", str(work_dir)], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=work_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=work_dir, check=True)

    (work_dir / "README.md").write_text("demo", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=work_dir, check=True)
    subprocess.run(["git", "branch", "-M", "dev"], cwd=work_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin_dir)], cwd=work_dir, check=True)
    subprocess.run(["git", "push", "-u", "origin", "dev"], cwd=work_dir, check=True)
    return work_dir


def test_brief_scaffold_round_trip(tmp_git_repo: Path, capsys, monkeypatch) -> None:
    """ensure_worktree --brief-key → brief + task + index → check_task_graph clean."""
    monkeypatch.chdir(tmp_git_repo)

    rc = main(["--slug", "fix-null-deref", "--brief-key", "abc123", "--base-branch", "dev", "--json"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    wt = Path(plan["path"])
    assert wt.is_dir()
    assert plan["name"] == "fix-abc123-fix-null-deref"

    # No upstream on the fresh worktree branch.
    upstream = subprocess.run(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=wt, capture_output=True, text=True)
    assert upstream.returncode != 0

    meta = BriefMeta.model_validate(
        {
            "kind": "brief",
            "slug": "fix-null-deref",
            "key": "abc123",
            "base_branch": "dev",
            "source": {"type": "text", "ref": "null deref in foo"},
            "created": "2026-10-17",
        }
    )
    brief = wt / meta.brief_path
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text(emit_brief_frontmatter(meta) + "\n# Brief\n", encoding="utf-8")
    assert parse_brief(brief) == meta

    task_rel = f"{meta.tasks_dir}/HOTFIX-abc123-1-fix.md"
    task_file = wt / task_rel
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text("# HOTFIX-abc123-1\n", encoding="utf-8")
    index = write_brief_index(
        meta,
        [{"id": "HOTFIX-abc123-1", "slug": "fix", "title": "Fix null deref", "file": task_rel}],
        wt,
    )

    result = subprocess.run(
        [sys.executable, "-m", "scripts.sdd.check_task_graph", str(index)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
