"""Contract checks for newer Claude SDD behavior migrated to Codex surfaces."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    """Read a repository-relative workflow definition."""
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_spec_and_task_preserve_edit_site_anchor_contract() -> None:
    """Codex planning surfaces carry the Claude edit-site anchor workflow."""
    spec = _read(".agents/skills/sdd-spec/SKILL.md")
    task = _read(".agents/skills/sdd-task/SKILL.md")

    assert "Edit Sites" in spec
    assert "occurrence count" in spec
    assert "Edit Sites" in task
    assert "re-run `grep -c`" in task
    assert "stop and report drift" in task


def test_worker_uses_deterministic_finalization_and_scoped_force_add() -> None:
    """Codex worker does not lose declared ignored files or hand-roll closure."""
    worker = _read(".codex/agents/sdd-worker.toml")

    assert "git add -f <file>" in worker
    assert "TaskCompletionEvidence" in worker
    assert "scripts.sdd.finalize_task" in worker
    assert "hand-edit the Completion Note" in worker


def test_existing_codex_workflow_skills_retain_shared_lifecycle_contracts() -> None:
    """Already-migrated lifecycle behavior remains present on all requested skills."""
    start = _read(".agents/skills/sdd-start/SKILL.md")
    done = _read(".agents/skills/sdd-done/SKILL.md")
    fix = _read(".agents/skills/sdd-fix/SKILL.md")

    assert "Deterministic task inspection and closure" in start
    assert "Durable review boundary" in done
    assert "wikitoolkit ledger plan-fix --json" in fix
