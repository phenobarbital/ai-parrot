"""Parse-check for scripts/install/install-parrot.ps1 (FEAT-586, TASK-3587)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.ps1"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_powershell_script_syntax() -> None:
    """PowerShell parses the script with zero errors."""
    assert SCRIPT.is_file()
    command = (
        "$errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 } else { exit 0 }"
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
