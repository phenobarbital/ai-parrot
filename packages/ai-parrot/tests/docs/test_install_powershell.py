"""Parse-check for scripts/install/install-parrot.ps1 (FEAT-586, TASK-3587)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "install" / "install-parrot.ps1"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _flat(text: str) -> str:
    """Normalise pwsh console output for substring checks.

    pwsh renders errors with ANSI colours and wraps long messages onto continuation lines prefixed
    with a ``|`` gutter, so a phrase like "not writable" can arrive as ``not\\n     | writable``.
    Strip the escapes and the gutter, then collapse all whitespace to single spaces.
    """
    text = _ANSI.sub("", text)
    text = re.sub(r"(?m)^\s*\|\s?", " ", text)
    return " ".join(text.split())


def _pwsh_env(**overrides: str) -> dict[str, str]:
    """The current environment with plain (uncoloured) pwsh output and the given overrides."""
    env = {k: v for k, v in os.environ.items() if k not in overrides}
    env.update(NO_COLOR="1", **overrides)
    return env


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


_TEXT = SCRIPT.read_text(encoding="utf-8")


def test_global_params_declared() -> None:
    """-Global / -Version / -With are script parameters."""
    assert "[Alias('Global')][switch]$GlobalMode" in _TEXT
    assert "[string]$Version" in _TEXT
    assert "[string]$With" in _TEXT


def test_global_branch_precedes_python_guard() -> None:
    """The -Global dispatch appears before the system-Python guard (codex S10)."""
    assert _TEXT.index("if ($GlobalMode)") < _TEXT.index("# Python guard (AC10)")


def test_global_pins_and_verifies_uv() -> None:
    """Pinned uv 0.11.28 is verified with Get-FileHash; PATH edits are User-scope only."""
    assert "0.11.28" in _TEXT
    assert "Get-FileHash" in _TEXT
    assert "'User'" in _TEXT
    assert "'Machine'" not in _TEXT


def test_preflight_gate_precedes_first_write() -> None:
    """C14b: Write-Plan and Test-Preflight are called before $Created exists / the first New-Item in Install-Global."""
    body = _TEXT[_TEXT.index("function Install-Global") :]
    assert body.index("Write-Plan ") < body.index("Test-Preflight ") < body.index("$script:Created =") < body.index("New-Item")
    for needle in ("preflight: unsupported platform", "git not found", "$MinFreeKB", "network checks skipped (-DryRun)"):
        assert needle in _TEXT, needle


def test_post_install_doctor_precedes_components() -> None:
    """C14b: `self doctor --runtime-only` runs after Add-UserPath and before any `self add`, pinned via PARROT_VENV."""
    body = _TEXT[_TEXT.index("function Install-Global") :]
    assert body.index("Add-UserPath $bin") < body.index("self doctor --runtime-only") < body.index("self add $c")
    assert "if ($LASTEXITCODE) { throw" in body
    assert "$env:PARROT_VENV = $venv" in body
    assert "self doctor\n" not in body and "self doctor;" not in body, "plain-scope doctor must never gate the install"


def _run_offline_install(tmp_path: Path, *, fake_parrot: str) -> subprocess.CompletedProcess[str]:
    """C14b harness (pwsh-gated): a real -Global run with fakes — no network, no real HOME, no real PATH edit."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    uv_stub = (
        "#!/bin/sh\n"
        'if [ "$1" = "venv" ]; then\n'
        '  mkdir -p "$2/Scripts"\n'
        '  for n in python wikitoolkit bookstore; do printf "#!/bin/sh\\n" > "$2/Scripts/$n.exe"; done\n'
        '  printf "#!/usr/bin/env pwsh\\n%s\\n" "$FAKE_PARROT_BODY" > "$2/Scripts/parrot.exe"\n'
        '  chmod +x "$2"/Scripts/*.exe\n'
        "fi\n"
        "exit 0\n"
    )
    zip_path = fixtures / "uv.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo("uv.exe")
        info.external_attr = 0o755 << 16
        zf.writestr(info, uv_stub)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (fixtures / "uv.zip.sha256").write_text(f"{digest}  uv.zip\n", encoding="utf-8")
    # Stub Invoke-WebRequest as a function: functions shadow the cmdlet for the dot-less script call.
    stub = (
        "function Invoke-WebRequest { param($Uri, $OutFile, $Method, [switch]$UseBasicParsing) "
        "if ($Method -eq 'Head') { return }; "
        f"if ($Uri -like '*.sha256') {{ Copy-Item '{fixtures / 'uv.zip.sha256'}' $OutFile }} "
        f"else {{ Copy-Item '{zip_path}' $OutFile }} }}; "
        f"& '{SCRIPT}' -Global"
    )
    env = {
        **{k: v for k, v in os.environ.items() if k != "PARROT_HOME"},
        "HOME": str(home),
        "PARROT_HOME": str(home / ".parrot"),
        "FAKE_PARROT_BODY": fake_parrot,
    }
    return subprocess.run(
        ["pwsh", "-NoProfile", "-Command", stub], capture_output=True, text=True, check=False, env=env
    )


_OFFLINE_XFAIL = pytest.mark.xfail(
    strict=False,
    reason="offline harness relies on pwsh honouring unix exec bits for an Expand-Archive'd fake uv.exe; unverified on CI",
)
_PARROT_RUNTIME_BROKEN = "echo 'uv: missing — fix: rerun the bootstrap'; exit 1"
_PARROT_REPO_NOT_READY = (
    "if ($args -contains '--runtime-only') { 'runtime: ok'; exit 0 }; "
    "'gh: not authenticated — fix: gh auth login'; 'ledger: uncommitted'; exit 1"
)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
@_OFFLINE_XFAIL
def test_post_install_runtime_failure_rolls_back(tmp_path: Path) -> None:
    """C14b: a failing `self doctor --runtime-only` removes what the run created and restores the user PATH."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_RUNTIME_BROKEN)
    assert result.returncode != 0
    assert "self doctor --runtime-only" in result.stdout and "suggested fixes above" in (result.stderr + result.stdout)
    assert not (tmp_path / "home" / ".parrot").exists()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
@_OFFLINE_XFAIL
def test_post_install_repo_readiness_failures_keep_runtime(tmp_path: Path) -> None:
    """C14b: unauthenticated gh / uncommitted ledger / outdated SDD assets never roll back a healthy runtime."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY)
    assert result.returncode == 0, result.stderr
    assert "gh: not authenticated" not in result.stdout
    home = tmp_path / "home" / ".parrot"
    assert (home / "bin" / "parrot.exe").exists() and (home / "venv").exists()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_global_dry_run(tmp_path: Path) -> None:
    """-Global -DryRun with a bogus -Python exits 0 and writes nothing under PARROT_HOME."""
    home = tmp_path / "parrot-home"
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT), "-Global", "-DryRun", "-Python", "C:/nonexistent",
         "-Version", "9.9.9", "-With", "sdd"],
        capture_output=True,
        text=True,
        check=False,
        env=_pwsh_env(PARROT_HOME=str(home)),
    )
    assert result.returncode == 0, result.stderr
    assert "unsupported Python" not in result.stderr
    assert "==9.9.9" in result.stdout and "self add sdd" in result.stdout
    assert "ai-parrot-tools==9.9.9" in result.stdout      # rev 0.5 C20: same version pin as ai-parrot
    assert not home.exists()
    # C14a/C14b: plan paragraph and gate summary precede the first "->" announcement
    assert "never used or modified" in _flat(result.stdout) and "SHA256SUMS" in result.stdout
    assert result.stdout.index("preflight: network checks skipped") < result.stdout.index("->")


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
def test_global_gate_unwritable_home_exits_before_write(tmp_path: Path) -> None:
    """C14b: PARROT_HOME under a read-only parent fails the writability gate with nothing written."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores read-only directory permissions")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT), "-Global"],
        capture_output=True, text=True, check=False,
        env=_pwsh_env(PARROT_HOME=str(ro / ".parrot")),
    )
    out = _flat(result.stderr + result.stdout)
    # On a non-x64 host the platform gate fires first; either refusal must happen before any write.
    assert result.returncode == 1 and ("not writable" in out or "unsupported platform" in out)
    assert not (ro / ".parrot").exists()


def test_run_turns_native_failures_into_errors() -> None:
    """Run resets then checks $LASTEXITCODE so uv/pip/self add/npm failures cannot report success."""
    run_body = _TEXT.split("function Run {", 1)[1].split("function Resolve-Extras", 1)[0]
    assert "$global:LASTEXITCODE = 0" in run_body
    assert "if ($LASTEXITCODE) { throw" in run_body
    assert run_body.index("$global:LASTEXITCODE = 0") < run_body.index("& $Cmd") < run_body.index("if ($LASTEXITCODE)")


def test_component_failure_warns_and_exits_nonzero_without_rollback() -> None:
    """A failing `parrot self add` warns, keeps the base runtime and exits 1 (parity with install-parrot.sh)."""
    assert "$script:ComponentFailed = $true" in _TEXT
    assert "if ($script:ComponentFailed) { exit 1 }" in _TEXT
