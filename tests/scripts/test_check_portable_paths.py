"""Tests for scripts/check_portable_paths.py (issue:7e03742cc29b)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_portable_paths.py"
_spec = importlib.util.spec_from_file_location("check_portable_paths", SCRIPT)
check_portable_paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_portable_paths)


@pytest.mark.parametrize(
    "path",
    [
        "sdd/state/FEAT-774/findings/.audit/FC-001-cli-identity-bootstrap-has-one-caller:-standalon.md",
        "sdd/state/x/FC-002-no-broker-or-_cred_*-seam.md",
        "docs/what?.md",
        'docs/say-"hi".md',
        "docs/a<b>.md",
        "docs/pipe|name.md",
        "docs/back\\slash.md",
        "docs/tab\there.md",
        "src/aux.py",
        "src/CON",
        "src/com1.txt",
        "docs/trailing.",
        "docs/trailing /x.md",
    ],
)
def test_non_portable_paths_are_reported(path: str) -> None:
    assert check_portable_paths.path_problems(path), path


@pytest.mark.parametrize(
    "path",
    [
        "sdd/state/FEAT-774/findings/.audit/FC-001-cli-identity-bootstrap-has-one-caller-standalon.md",
        "packages/ai-parrot/src/parrot/__init__.py",
        ".github/workflows/ci.yml",
        "docs/console.md",
        "src/auxiliary.py",
        "src/com10.txt",
        "a/b,c;d(e)'f+g=h.md",
    ],
)
def test_portable_paths_pass(path: str) -> None:
    assert check_portable_paths.path_problems(path) == []


def test_cli_exits_1_and_names_the_offender(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_portable_paths.main(["ok/file.md", "bad/na:me.md"]) == 1
    out = capsys.readouterr().out
    assert "bad/na:me.md: 'na:me.md' contains ':'" in out
    assert "1 path(s) cannot be checked out on Windows" in out


def test_repository_paths_are_portable() -> None:
    """The gate CI runs: every tracked path in this repository can be checked out on Windows."""
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout
