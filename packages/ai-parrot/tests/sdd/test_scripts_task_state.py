# packages/ai-parrot/tests/sdd/test_scripts_task_state.py
"""FEAT-633 move B1: task-state helpers live in parrot.sdd.scripts; scripts/sdd shims alias them."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("finalize_task", "check_task_state", "check_task_graph", "worktree_status", "review_checkpoint")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", f"parrot.sdd.scripts.{name}", "--help"],
        cwd=tmp_path, env=_env(), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", MOVED)
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


def test_check_task_graph_kernel_is_package_relative() -> None:
    import parrot
    from parrot.sdd.scripts import check_task_graph

    assert check_task_graph._KERNEL_DIR == Path(parrot.__file__).resolve().parent / "flows" / "dev_loop"
    assert (check_task_graph._KERNEL_DIR / "test_scope" / "contract.py").is_file()
    assert check_task_graph._load_contract() is not None


def test_worktree_status_main_takes_no_argv() -> None:
    import inspect

    from parrot.sdd.scripts import worktree_status

    assert list(inspect.signature(worktree_status.main).parameters) == []
