"""Tests for scripts/install/install-parrot.sh (FEAT-586, TASK-3586)."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.sh"


def test_posix_script_syntax() -> None:
    """`bash -n` parses the script."""
    assert SCRIPT.is_file()
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_posix_script_dry_run() -> None:
    """--dry-run prints a plan and creates no venv."""
    with tempfile.TemporaryDirectory() as tmp:
        venv_dir = Path(tmp) / ".venv"
        result = subprocess.run(
            ["bash", str(SCRIPT), "--dry-run", "--provider", "anthropic", "--venv", str(venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "→" in result.stdout  # the announced-purpose arrow ("->")
        assert not venv_dir.exists(), "--dry-run must not create the virtualenv"


def test_script_rejects_unsupported_python() -> None:
    """A 3.10/3.14 interpreter is refused before install."""
    with tempfile.TemporaryDirectory() as tmp:
        stub_python = Path(tmp) / "fake-python"
        stub_python.write_text(
            "#!/usr/bin/env bash\n" 'if [ "$1" = "-c" ]; then\n' '  echo "3.10"\n' "fi\n",
            encoding="utf-8",
        )
        stub_python.chmod(stub_python.stat().st_mode | stat.S_IEXEC)

        result = subprocess.run(
            ["bash", str(SCRIPT), "--dry-run", "--python", str(stub_python), "--provider", "anthropic"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ},
        )

        assert result.returncode != 0
        assert "unsupported Python" in result.stderr
