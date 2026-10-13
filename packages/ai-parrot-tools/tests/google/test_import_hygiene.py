"""Regression tests for cross-module import hygiene (issue:265b7797ae9b).

Both defects guarded here are invisible to single-file runs: they only
appear when one module's import-time side effects leak into the next
module's imports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DRIVE_TEST = Path(__file__).with_name("test_drive_toolkit.py")
_JIRA_TEST = _REPO_ROOT / "packages" / "ai-parrot-tools" / "tests" / "test_jira_config.py"
_FAKES_DIR = _REPO_ROOT / "packages" / "ai-parrot" / "tests" / "interfaces"
_JIRA_SYMPTOM = "cannot import name 'JIRA'"


def test_drive_toolkit_does_not_shadow_pypi_jira():
    """Collecting the Drive toolkit tests must not break `from jira import JIRA`."""
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "--collect-only", "-q",
            "-p", "no:randomly", str(_DRIVE_TEST), str(_JIRA_TEST),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert _JIRA_SYMPTOM not in output, (
        "test_drive_toolkit.py shadowed the PyPI `jira` package for a "
        f"later-collected module ({_JIRA_SYMPTOM!r} found):\n{output[-2000:]}"
    )
    assert result.returncode == 0, (
        f"collecting the Drive and Jira test modules together failed "
        f"(exit {result.returncode}):\n{output[-2000:]}"
    )


def test_drive_toolkit_leaves_sys_path_clean():
    """Importing the Drive toolkit tests adds no directory to sys.path."""
    # This module is collected after test_drive_toolkit.py within the same
    # directory, so its import side effects have already run.
    entries = {os.path.normcase(os.path.realpath(p)) for p in sys.path if p}
    assert os.path.normcase(os.path.realpath(_FAKES_DIR)) not in entries, (
        f"{_FAKES_DIR} is on sys.path; its `jira/` test package would shadow "
        "the PyPI `jira` distribution"
    )


def test_parrot_interfaces_file_is_the_real_package():
    """The root conftest must not shadow parrot.interfaces.file with a stub."""
    import parrot.interfaces.file as pif

    assert hasattr(pif, "__path__"), (
        "parrot.interfaces.file is not a package — the root conftest stub "
        "is shadowing the real one"
    )
    from parrot.interfaces.file.gdrive import GoogleDriveFileManager

    assert GoogleDriveFileManager is not None
