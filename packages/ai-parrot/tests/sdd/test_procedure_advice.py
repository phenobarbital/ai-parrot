"""Tests for the hook-side procedure advice module (FEAT-891)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
