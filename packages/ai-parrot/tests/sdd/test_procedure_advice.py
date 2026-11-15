"""Tests for the hook-side procedure advice module (FEAT-891)."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import pytest

from parrot.sdd.scripts import procedure_advice as advice

GUARDS = [
    {
        "procedure": "sdd:task-close",
        "kind": "entry",
        "executable": "parrot",
        "argv_prefix": ["sdd", "task", "close"],
        "path_globs": [],
        "scope": {"task": {"argv": 0}, "feature": {"argv": 1}},
    },
    {
        "procedure": "sdd:task-close",
        "kind": "bypass",
        "executable": "git",
        "argv_prefix": ["mv"],
        "path_globs": ["sdd/tasks/active/*"],
        "scope": {},
    },
]


def test_advice_stdlib_only() -> None:
    """Importing the module in a fresh interpreter loads no pydantic, yaml or sqlite3."""
    code = (
        "import sys\n"
        "from parrot.sdd.scripts import procedure_advice\n"
        "print(sorted(m for m in ('pydantic', 'yaml', 'sqlite3') if m in sys.modules))\n"
    )
    env = os.environ.copy()
    source_root = Path(__file__).parents[2] / "src"
    env["PYTHONPATH"] = os.pathsep.join((str(source_root), env.get("PYTHONPATH", "")))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, env=env)
    assert proc.stdout.strip() == "[]", proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("cd x && rtk git mv a b", ("git", ["mv", "a", "b"])),
        ("FOO=1 BAR=2 /usr/bin/git push", ("git", ["push"])),
        ("uv run pytest -q", ("pytest", ["-q"])),
        ("timeout 30 gh pr create --base dev", ("gh", ["pr", "create", "--base", "dev"])),
        ("echo 'unbalanced", ("", [])),
    ],
)
def test_leading_command_wrappers(command: str, expected: tuple[str, list[str]]) -> None:
    """Assignments, ``cd … &&`` and known wrappers are skipped."""
    assert advice.leading_command(command) == expected


def test_match_guards_every_segment() -> None:
    """A guarded command is found in any segment of a compound command."""
    index = {"schema_version": advice.INDEX_SCHEMA_VERSION, "guards": GUARDS}
    matched = advice.match_guards(index, "mkdir -p x && git mv sdd/tasks/active/TASK-1-a.md sdd/tasks/completed/")
    assert matched[0]["argv"] == ["sdd/tasks/active/TASK-1-a.md", "sdd/tasks/completed/"]
    assert advice.match_guards(index, "git mv README.md docs/") == []

    matched = advice.match_guards(index, "parrot sdd task close TASK-1 demo verified")
    assert matched[0]["argv"] == ["TASK-1", "demo", "verified"]


def test_shared_root_plain_and_worktree(tmp_path: Path) -> None:
    """A plain checkout and linked worktree resolve to the primary checkout."""
    main = tmp_path / "main"
    main_git = main / ".git"
    main_git.mkdir(parents=True)
    assert advice.checkout_root(main / "src") == main
    assert advice.shared_root(main / "src") == main

    worktree = tmp_path / "worktree"
    admin = main_git / "worktrees" / "linked"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    assert advice.checkout_root(worktree / "src") == worktree
    assert advice.shared_root(worktree / "src") == main


def test_load_index_rejects_bad_files(tmp_path: Path) -> None:
    """Absent, unparsable, oversized and wrong-version files all return None."""
    root = tmp_path / "repo"
    index_path = root / advice.PLANE_DIR / advice.INDEX_FILE
    index_path.parent.mkdir(parents=True)

    assert advice.load_index(root) is None

    index_path.write_text("not json", encoding="utf-8")
    assert advice.load_index(root) is None

    index_path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    assert advice.load_index(root) is None

    index_path.write_text("x" * (advice.MAX_INDEX_BYTES + 1), encoding="utf-8")
    assert advice.load_index(root) is None

    index_path.write_text(json.dumps({"schema_version": advice.INDEX_SCHEMA_VERSION}), encoding="utf-8")
    assert advice.load_index(root) == {"schema_version": advice.INDEX_SCHEMA_VERSION}


def _repo(tmp_path: Path, *, status: str = "in-progress", config: dict | None = None) -> Path:
    """Create a small plain checkout with a fresh compiled procedure plane."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/feat-FEAT-1-demo\n", encoding="utf-8")
    (root / "sdd" / "specs").mkdir(parents=True)
    (root / "sdd" / "specs" / "demo.spec.md").write_text("# demo\n", encoding="utf-8")
    (root / "sdd" / "procedures").mkdir(parents=True)
    source = root / "sdd" / "procedures" / "sdd-workflow.yaml"
    source.write_text("graph: sdd\n", encoding="utf-8")
    (root / "sdd" / "tasks" / "index").mkdir(parents=True)
    index = {
        "schema_version": advice.INDEX_SCHEMA_VERSION,
        "feature": "demo",
        "feature_id": "FEAT-1",
        "tasks": [
            {"id": "TASK-1", "status": status, "depends_on": []},
            {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
        ],
        "guards": [
            {
                "procedure": "sdd:task-close",
                "kind": "entry",
                "executable": "parrot",
                "argv_prefix": ["sdd", "task", "close"],
                "path_globs": [],
                "scope": {"task": {"argv": 0}, "feature": {"argv": 1}},
            },
            {
                "procedure": "sdd:task-close",
                "kind": "bypass",
                "executable": "git",
                "argv_prefix": ["mv"],
                "path_globs": ["sdd/tasks/active/*"],
                "scope": {},
            },
            {
                "procedure": "sdd:pr-create",
                "kind": "entry",
                "executable": "gh",
                "argv_prefix": ["pr", "create"],
                "path_globs": [],
                "scope": {"base": {"flag": "--base|-B"}},
            },
            {
                "procedure": "sdd:push",
                "kind": "entry",
                "executable": "git",
                "argv_prefix": ["push"],
                "path_globs": [],
                "scope": {},
            },
        ],
        "procedures": {
            "sdd:task-close": {
                "mode": "mandatory",
                "command": "parrot sdd task close <TASK> <slug> verified",
                "use_instead": "parrot sdd task close <TASK> <slug> verified",
                "advice": "Close tasks through the SDD command.",
                "preconditions": [
                    {"probe": "task.status", "expect": "in-progress", "cost": "local"},
                    {"probe": "task.depends_done", "expect": True, "cost": "local"},
                ],
            },
            "sdd:pr-create": {
                "mode": "mandatory",
                "command": "gh pr create --base <base>",
                "advice": "Pass the intended base branch.",
                "preconditions": [{"probe": "flow.base_allowed", "expect": True, "cost": "local"}],
            },
            "sdd:push": {
                "mode": "advisory",
                "command": "git push",
                "advice": "Push through the normal SDD workflow.",
                "preconditions": [{"probe": "env.not_worker_sandbox", "expect": True, "cost": "local"}],
            },
        },
        "sources": [
            {"path": "sdd/procedures/sdd-workflow.yaml", "sha1": hashlib.sha1(source.read_bytes()).hexdigest()}
        ],
    }
    index_path = root / "sdd" / "tasks" / "index" / "demo.json"
    index_path.write_text(json.dumps({"feature": "demo", "tasks": index["tasks"]}), encoding="utf-8")
    config_payload = {"hotfix_base": "main"}
    if config:
        config_payload.update(config)
    (root / "sdd" / "config.json").write_text(json.dumps(config_payload), encoding="utf-8")
    plane = root / advice.PLANE_DIR
    plane.mkdir(parents=True)
    (plane / advice.INDEX_FILE).write_text(json.dumps(index), encoding="utf-8")
    return root


def test_guard_decision_table(tmp_path: Path) -> None:
    """Exercise every local row of the guard decision table."""
    root = _repo(tmp_path)
    assert (
        advice.evaluate_command("git mv sdd/tasks/active/TASK-1.md sdd/tasks/completed/", root, env={}).decision
        == "deny"
    )
    assert (
        "parrot sdd task close"
        in advice.evaluate_command("git mv sdd/tasks/active/TASK-1.md sdd/tasks/completed/", root, env={}).text
    )
    assert advice.evaluate_command("parrot sdd task close TASK-2 demo verified", root, env={}).decision == "deny"
    assert advice.evaluate_command("parrot sdd task close TASK-1 demo verified", root, env={}).decision == "none"
    assert advice.evaluate_command("parrot sdd task close TASK-9 demo verified", root, env={}).decision == "advise"
    assert advice.evaluate_command("gh pr create --base main", root, env={}).decision == "deny"
    assert advice.evaluate_command("gh pr create -B main", root, env={}).decision == "deny"
    assert advice.evaluate_command("gh pr create", root, env={}).decision != "deny"
    assert advice.evaluate_command("git push", root, env={"PARROT_SDD_CACHE_DIR": "1"}).decision == "advise"


@pytest.mark.parametrize("switch", ["PARROT_ALLOW_PROCEDURE", "PARROT_ALLOW_DANGEROUS", "enforce-false"])
def test_escape_downgrades_deny(tmp_path: Path, switch: str) -> None:
    """Each supported escape switch changes a denial into an advisory."""
    config = {"procedure": {"enforce": False}} if switch == "enforce-false" else None
    env = {} if config else {switch: "1"}
    assert (
        advice.evaluate_command(
            "git mv sdd/tasks/active/TASK-1.md sdd/tasks/completed/", _repo(tmp_path, config=config), env=env
        ).decision
        == "advise"
    )


def test_stale_index_is_silent(tmp_path: Path) -> None:
    """A changed or missing listed source makes the plane silent."""
    root = _repo(tmp_path)
    source = root / "sdd" / "procedures" / "sdd-workflow.yaml"
    source.write_text("changed\n", encoding="utf-8")
    assert (
        advice.evaluate_command("git mv sdd/tasks/active/TASK-1.md sdd/tasks/completed/", root, env={}).decision
        == "none"
    )
    source.unlink()
    assert (
        advice.evaluate_command("git mv sdd/tasks/active/TASK-1.md sdd/tasks/completed/", root, env={}).decision
        == "none"
    )


def test_disabled_and_absent_plane_are_silent(tmp_path: Path) -> None:
    """A disabled or absent procedure plane never emits advice."""
    disabled = _repo(tmp_path / "disabled", config={"procedure": {"enabled": False}})
    assert (
        advice.evaluate_command("git mv sdd/tasks/active/TASK-1.md sdd/tasks/completed/", disabled, env={}).decision
        == "none"
    )
    absent = tmp_path / "absent"
    (absent / ".git").mkdir(parents=True)
    (absent / ".git" / "HEAD").write_text("ref: refs/heads/feat-demo\n", encoding="utf-8")
    assert advice.evaluate_command("git push", absent, env={}).decision == "none"


def test_apply_check_semantics(tmp_path: Path) -> None:
    """String expectations are probe arguments; boolean expectations compare values."""
    seen: dict[str, str] = {}

    def probe(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
        seen["expect"] = args["expect"]
        return args["expect"] == "in-progress|done"

    assert (
        advice.apply_check({"probe": "custom", "expect": "in-progress|done"}, tmp_path, {}, probes={"custom": probe})
        is True
    )
    assert seen["expect"] == "in-progress|done"
    assert (
        advice.apply_check({"probe": "custom", "expect": True}, tmp_path, {}, probes={"custom": lambda *_: True})
        is True
    )
    assert (
        advice.apply_check({"probe": "custom", "expect": True}, tmp_path, {}, probes={"custom": lambda *_: None})
        is None
    )
