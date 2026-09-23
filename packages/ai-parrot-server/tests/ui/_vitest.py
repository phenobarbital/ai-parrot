"""Run a vitest file from pytest (FEAT-593 validation contract accepts pytest commands only)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[2] / "ui"


def run_vitest(*files: str) -> None:
    """Run ``pnpm exec vitest run <files>`` in the admin UI; skip when node tooling is absent."""
    if shutil.which("pnpm") is None or not (UI_DIR / "node_modules").is_dir():
        pytest.skip("pnpm / ui node_modules not available")
    proc = subprocess.run(
        ["pnpm", "exec", "vitest", "run", *files],
        cwd=UI_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
