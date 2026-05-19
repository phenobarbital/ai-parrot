"""Regression tests for FEAT-187 — Git Parrot Flow."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sdd_command_files() -> list[Path]:
    """Return the SDD command files and agent updated by FEAT-187.

    These are the files that TASK-1256 explicitly edited to add `staging`
    mentions and the feature-main refusal block. The regression guard ensures
    that future edits to these files do not silently remove the three-branch
    model awareness introduced by FEAT-187.

    Other sdd-*.md files (sdd-codereview.md, sdd-fromjira.md, sdd-next.md,
    sdd-start.md, sdd-status.md, sdd-tojira.md) are read-only utilities that
    do not handle base_branch selection and are intentionally excluded.
    """
    commands_dir = REPO_ROOT / ".claude" / "commands"
    return [
        commands_dir / "sdd-brainstorm.md",
        commands_dir / "sdd-done.md",
        commands_dir / "sdd-proposal.md",
        commands_dir / "sdd-spec.md",
        commands_dir / "sdd-task.md",
        REPO_ROOT / ".claude" / "agents" / "sdd-worker.md",
    ]


@pytest.mark.parametrize("path", _sdd_command_files(), ids=lambda p: p.name)
def test_sdd_commands_mention_staging(path: Path) -> None:
    """Every SDD command file and the worker agent must mention 'staging'.

    Regression guard for FEAT-187: prevents a refactor from silently
    reverting the Git Parrot Flow three-branch model in the command docs.
    """
    assert path.exists(), f"missing expected file: {path}"
    assert "staging" in path.read_text(encoding="utf-8"), (
        f"{path.relative_to(REPO_ROOT)} does not mention 'staging' "
        f"(FEAT-187 regression guard)"
    )


def test_sync_down_workflow_is_valid_yaml() -> None:
    """The sync-down GitHub Action must parse as valid YAML with expected keys."""
    workflow = REPO_ROOT / ".github" / "workflows" / "sync-down.yml"
    assert workflow.exists(), f"missing: {workflow}"
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # PyYAML deserializes the literal 'on' key to boolean True in some versions.
    # Accept either form to be robust across PyYAML versions.
    on_key = "on" if "on" in data else True
    assert on_key in data, "workflow missing 'on:' trigger"
    for key in ("name", "permissions", "jobs"):
        assert key in data, f"workflow missing top-level '{key}'"


def test_sync_down_workflow_targets_staging_and_dev() -> None:
    """The matrix target list must be exactly [staging, dev]."""
    workflow = REPO_ROOT / ".github" / "workflows" / "sync-down.yml"
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    matrix = data["jobs"]["sync"]["strategy"]["matrix"]["target"]
    assert matrix == ["staging", "dev"], (
        f"unexpected sync-down matrix targets: {matrix!r}"
    )
