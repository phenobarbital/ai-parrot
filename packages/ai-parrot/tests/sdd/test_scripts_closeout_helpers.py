"""FEAT-633 move D: closeout/Validation Contract helpers live in parrot.sdd.scripts."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

MOVED = ("cache_test_contract", "test_report", "check_e2e_closeout", "close_resolved_issues")


@pytest.mark.parametrize("name", MOVED)
def test_importable_from_package(name: str) -> None:
    """Each helper imports from parrot.sdd.scripts and exposes main()."""
    mod = importlib.import_module(f"parrot.sdd.scripts.{name}")
    assert callable(mod.main)


@pytest.mark.parametrize("name", MOVED)
def test_module_help_runs(name: str) -> None:
    """``python -m parrot.sdd.scripts.<name> --help`` exits 0."""
    proc = subprocess.run(
        [sys.executable, "-m", f"parrot.sdd.scripts.{name}", "--help"], capture_output=True, text=True
    )
    if name in ("cache_test_contract", "test_report"):
        # Their main() swallows argparse's SystemExit(0) and returns 2 (pre-existing behaviour, unchanged by the move).
        assert "usage" in proc.stdout.lower(), proc.stderr
    else:
        assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", MOVED)
def test_shim_is_same_module(name: str) -> None:
    """The scripts.sdd shim aliases the package module object."""
    try:
        shim = importlib.import_module(f"scripts.sdd.{name}")
    except ImportError:
        pytest.skip("repo root is not importable")
    assert shim is importlib.import_module(f"parrot.sdd.scripts.{name}")


@pytest.mark.parametrize(
    ("name", "loader", "kernel"),
    (
        ("cache_test_contract", "_load_contract", "test_scope.contract"),
        ("test_report", "_load_report", "test_scope.report"),
    ),
)
def test_kernel_parent_is_package_relative(name: str, loader: str, kernel: str) -> None:
    """_KERNEL_PARENT points inside the installed parrot package, not at a monorepo path."""
    mod = importlib.import_module(f"parrot.sdd.scripts.{name}")
    import parrot

    assert Path(mod._KERNEL_PARENT) == Path(parrot.__file__).resolve().parent / "flows" / "dev_loop"
    assert (Path(mod._KERNEL_PARENT) / "test_scope").is_dir()
    assert getattr(mod, loader)().__name__ == kernel
