# packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
"""FEAT-633 move A: ledger/worktree helpers live in parrot.sdd.scripts; scripts/sdd shims alias them."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree")
MOVED_HOOK = SRC / "parrot" / "sdd" / "scripts" / "worktree_environment.py"  # rev 0.3 C16
OLD_HOOK = SRC / "parrot" / "flows" / "dev_loop" / "worktree_environment.py"  # rev 0.5 C19 shim
MOVED_LIBS = ("brief_meta",)  # rev 0.4 C17: library module, no main() until TASK-4299 adds the CLI
SDD_META_NAMES = (
    "KNOWN_BRANCHES", "KNOWN_PROJECTS", "PROJECT_ALIASES", "WORK_KIND_FLOW", "WORKTREE_ROOT", "DocTaxonomy",
    "FlowMeta", "WorktreePlan", "emit", "normalize_project", "normalize_tag", "parse", "parse_taxonomy",
    "plan_worktree", "resolve_flow",
)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


def _run(module: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, env=_env(), capture_output=True, text=True)


@pytest.mark.parametrize("name", (*MOVED, *MOVED_LIBS, "sdd_meta"))
def test_importable_from_package(name: str) -> None:
    assert importlib.import_module(f"parrot.sdd.scripts.{name}") is not None


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    assert _run(f"parrot.sdd.scripts.{name}", "--help", cwd=tmp_path).returncode == 0


@pytest.mark.parametrize("name", (*MOVED, *MOVED_LIBS))
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


@pytest.mark.parametrize("name", ("reserve_ids", "ensure_worktree"))
def test_live_cli_help_and_usage_error_unchanged(name: str) -> None:
    shim, pkg = _run(f"scripts.sdd.{name}", "--help", cwd=REPO_ROOT), _run(f"parrot.sdd.scripts.{name}", "--help", cwd=REPO_ROOT)
    assert (shim.returncode, shim.stdout) == (pkg.returncode, pkg.stdout)
    assert _run(f"scripts.sdd.{name}", cwd=REPO_ROOT).returncode == _run(f"parrot.sdd.scripts.{name}", cwd=REPO_ROOT).returncode == 2


def test_sdd_meta_reexport_identity() -> None:
    pkg = importlib.import_module("parrot.sdd.scripts.sdd_meta")
    src = importlib.import_module("parrot.knowledge.wiki.ledger.sdd_meta")
    for name in SDD_META_NAMES:
        assert getattr(pkg, name) is getattr(src, name), name


def test_worktree_environment_shim_reexports_moved_module() -> None:  # rev 0.3 C16 / AC-8
    old = importlib.import_module("parrot.flows.dev_loop.worktree_environment")
    moved = importlib.import_module("parrot.sdd.scripts.worktree_environment")
    for name in ("command_policy_error", "protected_argv", "validate_write_path"):
        assert getattr(old, name) is getattr(moved, name), name


def test_guard_loader_module_mode_never_imports_dev_loop() -> None:  # rev 0.5 C19 (1) / AC-9
    code = (
        "import sys; from parrot.sdd.scripts import worktree_environment as we; "
        "print(we._load_guard_bash().__module__); "
        "print(any(m == 'parrot.flows.dev_loop' or m.startswith('parrot.flows.dev_loop.') for m in sys.modules))"
    )
    proc = subprocess.run([sys.executable, "-c", code], env=_env(), capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["test_scope.guard", "False"]


@pytest.mark.parametrize("hook", (MOVED_HOOK, OLD_HOOK))
def test_hook_answers_with_bare_interpreter(hook: Path, tmp_path: Path) -> None:  # rev 0.5 C19 (2) / AC-10
    # -I -S: stdlib only (no site-packages, no PYTHONPATH, no script dir on sys.path).
    proc = subprocess.run(
        [sys.executable, "-I", "-S", str(hook), "--hook"],
        input="{}", cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_scope_guard_blocks_after_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-11
    from parrot.sdd.scripts import worktree_environment as we

    we._load_guard_bash()
    guard_mod = sys.modules["test_scope.guard"]
    from test_scope.datatypes import ScopePlan

    empty = ScopePlan(tier="task", invocations=(), escalated=(), core_hits=(), skipped_escalations=(), notes=())
    monkeypatch.setattr(guard_mod, "_task_plan", lambda worktree: empty)
    monkeypatch.setattr(we, "repository_paths", lambda cwd: (tmp_path, tmp_path))
    action, message = we._scope_guard("python -m pytest", tmp_path)
    assert action == "block", (action, message)


def test_kernel_lookup_from_wheel_layout(tmp_path: Path) -> None:  # AC-12
    pkg = tmp_path / "parrot"
    (pkg / "sdd" / "scripts").mkdir(parents=True)
    shutil.copy(MOVED_HOOK, pkg / "sdd" / "scripts" / "worktree_environment.py")
    shutil.copytree(
        SRC / "parrot" / "flows" / "dev_loop" / "test_scope",
        pkg / "flows" / "dev_loop" / "test_scope",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    copy = pkg / "sdd" / "scripts" / "worktree_environment.py"
    code = (
        "import importlib.util as u, sys; "
        f"s = u.spec_from_file_location('we', {str(copy)!r}); "
        "m = u.module_from_spec(s); s.loader.exec_module(m); "
        "g = m._load_guard_bash(); "
        "print(g.__module__, sys.modules['test_scope.guard'].__file__)"
    )
    proc = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    mod, path = proc.stdout.split()
    assert mod == "test_scope.guard"
    assert path.startswith(str(pkg))
