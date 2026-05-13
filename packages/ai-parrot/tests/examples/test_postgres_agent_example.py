"""Tests for the Postgres DatabaseAgent example script (FEAT-164)."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

# packages/ai-parrot/ — needed so the subprocess can import ``examples.*``.
_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])


def test_postgres_agent_example_module_imports() -> None:
    """Module imports without side effects."""
    mod = importlib.import_module("examples.database.postgres_agent")
    assert hasattr(mod, "main")


@pytest.mark.integration
def test_example_postgres_script_runs_to_completion() -> None:
    """Smoke: script exits 0 (with DB it prints four sections; without it
    prints the 'no URL configured' message and exits cleanly)."""
    env = {**os.environ, "PYTHONPATH": _PACKAGE_ROOT}
    result = subprocess.run(
        [sys.executable, "-m", "examples.database.postgres_agent"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
