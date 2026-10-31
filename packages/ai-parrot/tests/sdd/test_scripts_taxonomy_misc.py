# packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py
"""FEAT-633 move C: taxonomy/select_tests/insight/install_hooks live in parrot.sdd.scripts; shims alias them."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = (
    "doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "insight", "install_hooks",
    "prune_intake", "spec_tools",
)


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
    # select_tests.main() swallows argparse's SystemExit and returns 2 (pre-existing); --help still prints usage.
    ok = (0, 2) if name == "select_tests" else (0,)
    assert proc.returncode in ok, proc.stderr
    assert "usage" in proc.stdout.lower()


@pytest.mark.parametrize("name", MOVED)
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


def test_select_tests_kernel_is_package_relative() -> None:
    import parrot
    from parrot.sdd.scripts import select_tests

    assert select_tests._KERNEL_PARENT == Path(parrot.__file__).resolve().parent / "flows" / "dev_loop"
    assert hasattr(select_tests._load_kernel(), "plan_tests")


def test_insight_runs_by_path_with_bare_interpreter() -> None:
    # -I -S: isolated + no site-packages (no venv, no editable .pth) — a truly bare interpreter; only the shim's
    # own-checkout fallback can find parrot.sdd.scripts.insight (stdlib-only), so this exercises the fallback.
    proc = subprocess.run(
        [sys.executable, "-I", "-S", str(REPO_ROOT / "scripts" / "sdd" / "insight.py"), "--help"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
