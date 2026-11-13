"""Tests for the procedure check inside the SDD pre-tool guards (FEAT-891)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from parrot.sdd.scripts import native_claude_sandbox, worktree_environment

BYPASS = "git mv sdd/tasks/active/TASK-1-demo.md sdd/tasks/completed/TASK-1-demo.md"
PUSH = "git push origin HEAD"


def _plane_repo(tmp_path: Path) -> Path:
    """A repo (.git/HEAD on feat-FEAT-1-demo) with sdd/procedures/x.yaml, a per-spec index (TASK-1 pending)
    and a hand-written .parrot/procedure/procedures.json: `sdd:task-close` mandatory with a `git mv` bypass
    guard on sdd/tasks/active/*, and `sdd:push` advisory with an entry guard on `git push` whose
    precondition is env.not_worker_sandbox."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/feat-FEAT-1-demo\n", encoding="utf-8")
    source = root / "sdd" / "procedures" / "x.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("id: sdd:task-close\n", encoding="utf-8")
    index_dir = root / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "demo.json").write_text(
        json.dumps(
            {
                "feature": "demo",
                "feature_id": "FEAT-1",
                "tasks": [{"id": "TASK-1", "status": "pending", "depends_on": []}],
            }
        ),
        encoding="utf-8",
    )
    compiled = {
        "schema_version": 1,
        "sources": [{"path": "sdd/procedures/x.yaml", "sha1": hashlib.sha1(source.read_bytes()).hexdigest()}],
        "procedures": {
            "sdd:task-close": {
                "mode": "mandatory",
                "use_instead": "parrot sdd task close",
                "preconditions": [],
            },
            "sdd:push": {
                "mode": "advisory",
                "advice": "Push from the host.",
                "preconditions": [{"probe": "env.not_worker_sandbox", "cost": "local", "expect": True}],
            },
        },
        "guards": [
            {
                "procedure": "sdd:task-close",
                "kind": "bypass",
                "executable": "git",
                "argv_prefix": ["mv"],
                "path_globs": ["sdd/tasks/active/*"],
            },
            {
                "procedure": "sdd:push",
                "kind": "entry",
                "executable": "git",
                "argv_prefix": ["push"],
                "path_globs": [],
            },
        ],
    }
    plane = root / ".parrot" / "procedure"
    plane.mkdir(parents=True)
    (plane / "procedures.json").write_text(json.dumps(compiled), encoding="utf-8")
    return root


def _payload(root: Path, command: str) -> dict:
    return {"cwd": str(root), "tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No launcher markers or escape hatches leak in from the host; wrapping is deterministic."""
    for name in (
        "PARROT_SDD_SANDBOX_ROOTS",
        "PARROT_SDD_CACHE_DIR",
        "PARROT_ALLOW_PROCEDURE",
        "PARROT_ALLOW_DANGEROUS",
    ):
        monkeypatch.delenv(name, raising=False)

    def fake_wrap(command: str, *args: Any, **kwargs: Any) -> str:
        return f"WRAPPED {command}"

    monkeypatch.setattr(worktree_environment, "_wrap_bash", fake_wrap)


def test_worktree_guard_deny_and_advise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A deny drops `updatedInput`; an advise keeps the wrapper and adds `additionalContext`."""
    root = _plane_repo(tmp_path)

    denied = worktree_environment.hook_response(_payload(root, BYPASS))["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny"
    assert "sdd:task-close" in denied["permissionDecisionReason"]
    assert "updatedInput" not in denied

    monkeypatch.setenv("PARROT_SDD_SANDBOX_ROOTS", "/x")
    advised = worktree_environment.hook_response(_payload(root, PUSH))["hookSpecificOutput"]
    assert "permissionDecision" not in advised
    assert "sdd:push" in advised["additionalContext"]
    assert advised["updatedInput"]["command"] == f"WRAPPED {PUSH}"


def test_worktree_guard_unchanged_without_plane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no index the response equals the response computed before this feature (no extra keys)."""
    root = tmp_path / "plain"
    (root / ".git").mkdir(parents=True)
    payload = _payload(root, BYPASS)
    with_advice = worktree_environment.hook_response(payload)
    monkeypatch.setattr(worktree_environment, "_apply_procedure_advice", lambda output, payload: None)
    without_advice = worktree_environment.hook_response(payload)
    assert with_advice == without_advice
    assert "additionalContext" not in with_advice["hookSpecificOutput"]


def test_worktree_guard_existing_deny_wins(tmp_path: Path) -> None:
    """A payload the guard already denies keeps its own reason and gets no procedure text."""
    root = _plane_repo(tmp_path)
    output = worktree_environment.hook_response(_payload(root, BYPASS), backend="nope")["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "Unknown SDD sandbox backend" in output["permissionDecisionReason"]
    assert "sdd:task-close" not in output["permissionDecisionReason"]
    assert "additionalContext" not in output


def test_worktree_guard_swallows_advice_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception inside the procedure check never becomes a denial."""
    root = _plane_repo(tmp_path)

    def boom() -> Any:
        raise RuntimeError("advice module exploded")

    monkeypatch.setattr(worktree_environment, "_load_procedure_advice", boom)
    output = worktree_environment.hook_response(_payload(root, BYPASS))["hookSpecificOutput"]
    assert "permissionDecision" not in output
    assert "additionalContext" not in output
    assert output["updatedInput"]["command"] == f"WRAPPED {BYPASS}"


def test_control_files_include_advice(tmp_path: Path) -> None:
    """procedure_advice.py is protected next to the guard files."""
    names = {path.name for path in native_claude_sandbox._control_files(tmp_path)}
    assert {"native_claude_sandbox.py", "worktree_environment.py", "procedure_advice.py"} <= names
