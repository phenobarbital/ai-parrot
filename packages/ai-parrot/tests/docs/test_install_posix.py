"""Tests for scripts/install/install-parrot.sh (FEAT-586, TASK-3586)."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest

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


def _run_global(tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the installer in --global --dry-run with HOME and PARROT_HOME sandboxed under tmp."""
    env = {**os.environ, "HOME": str(tmp / "home"), "PARROT_HOME": str(tmp / "home" / ".parrot"), "SHELL": "/bin/bash"}
    return subprocess.run(
        ["bash", str(SCRIPT), "--global", "--dry-run", *extra],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_global_dry_run_bypasses_python_guard(tmp_path: Path) -> None:
    """--global runs before the system-Python guard: a nonexistent --python is never executed."""
    result = _run_global(tmp_path, "--python", "/nonexistent")
    assert result.returncode == 0, result.stderr
    assert "unsupported Python" not in result.stderr
    assert "0.11.28" in result.stdout
    assert "uv venv" in result.stdout or "venv" in result.stdout


def test_global_dry_run_writes_nothing(tmp_path: Path) -> None:
    """--global --dry-run creates no file under HOME / PARROT_HOME."""
    result = _run_global(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home").exists()


def test_global_flags_parse(tmp_path: Path) -> None:
    """--version pins the spec (ai-parrot and ai-parrot-tools alike, rev 0.5 C20); --with announces one `parrot self add` per component."""
    result = _run_global(tmp_path, "--version", "9.9.9", "--with", "sdd,scraping")
    assert result.returncode == 0, result.stderr
    assert "==9.9.9" in result.stdout
    assert "ai-parrot-tools==9.9.9" in result.stdout
    assert "self add sdd" in result.stdout
    assert "self add scraping" in result.stdout


def test_global_rejects_project_only_flags(tmp_path: Path) -> None:
    """--venv is meaningless with --global and is refused."""
    result = _run_global(tmp_path, "--venv", str(tmp_path / "v"))
    assert result.returncode != 0
    assert "--global cannot be combined with --venv" in result.stderr


def test_global_dry_run_prints_plan_and_gate(tmp_path: Path) -> None:
    """C14a/C14b: the plan paragraph and the gate summary precede any `→` announcement."""
    result = _run_global(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "0.11.28" in result.stdout and ".sha256" in result.stdout and "SHA256SUMS" in result.stdout
    assert "never used or modified" in result.stdout
    assert result.stdout.index("preflight: network checks skipped") < result.stdout.index("→")


_TOOLS = (
    "bash", "uname", "df", "awk", "dirname", "tar", "gzip", "mkdir", "rm", "ln", "mv", "grep", "cat", "cp",
    "chmod", "env", "sed", "sha256sum", "git", "curl", "wget",
)


def _fake_bin(tmp: Path, *, drop: tuple[str, ...] = (), scripts: dict[str, str] | None = None) -> str:
    """Build a PATH dir of symlinks to the real tools minus `drop`, plus fake `scripts` (name → body)."""
    bindir = tmp / "fakebin"
    bindir.mkdir(exist_ok=True)
    scripts = scripts or {}
    for name in _TOOLS:
        real = shutil.which(name)
        if real and name not in drop and name not in scripts:
            (bindir / name).symlink_to(real)
    for name, body in scripts.items():
        target = bindir / name
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)
    return str(bindir)


def test_gate_unsupported_platform_exits_before_write(tmp_path: Path) -> None:
    """C14b: a fake `uname` reporting Linux-mips fails the platform gate; nothing is written."""
    path = _fake_bin(tmp_path, scripts={"uname": '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo mips;; esac\n'})
    env = {"HOME": str(tmp_path / "home"), "PARROT_HOME": str(tmp_path / "home" / ".parrot"), "PATH": path}
    result = subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1
    assert "preflight: unsupported platform" in result.stderr and "fix:" in result.stderr
    assert not (tmp_path / "home").exists()


def test_gate_missing_download_tool_exits_before_write(tmp_path: Path) -> None:
    """C14b: a PATH without curl/wget fails the tool gate before any write (and before network)."""
    path = _fake_bin(tmp_path, drop=("curl", "wget"))
    env = {"HOME": str(tmp_path / "home"), "PARROT_HOME": str(tmp_path / "home" / ".parrot"), "PATH": path}
    result = subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1 and "no download tool" in result.stderr
    assert not (tmp_path / "home").exists()


def test_gate_unwritable_home_exits_before_write(tmp_path: Path) -> None:
    """C14b: PARROT_HOME under a read-only parent fails the writability gate."""
    if os.geteuid() == 0:
        pytest.skip("root ignores a 0o555 directory")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        env = {**os.environ, "HOME": str(tmp_path / "home"), "PARROT_HOME": str(ro / ".parrot")}
        result = subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)
        assert result.returncode == 1 and "not writable" in result.stderr
        assert not (ro / ".parrot").exists()
    finally:
        ro.chmod(0o755)


_FAKE_UNAME = '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n'
_FAKE_CURL = """#!/bin/sh
case "$1" in -fsI) exit 0;; esac
dest=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) dest="$2"; shift 2;; -*) shift;; *) url="$1"; shift;; esac
done
case "$url" in
  *.sha256) cp "$FIXTURES/uv.tar.gz.sha256" "$dest" ;;
  *) cp "$FIXTURES/uv.tar.gz" "$dest" ;;
esac
"""
_FAKE_UV = """#!/bin/sh
case "$1" in
  venv)
    mkdir -p "$2/bin"
    for n in python wikitoolkit bookstore; do printf '#!/bin/sh\\n' > "$2/bin/$n"; chmod 755 "$2/bin/$n"; done
    cp "$FIXTURES/parrot" "$2/bin/parrot"; chmod 755 "$2/bin/parrot" ;;
  pip) exit 0 ;;
esac
"""


def _run_offline_install(tmp_path: Path, *, fake_parrot: str) -> subprocess.CompletedProcess[str]:
    """C14b harness: a real non-dry-run `--global` with fakes — never touches the network or the real HOME."""
    fixtures = tmp_path / "fixtures"
    stage = fixtures / "uv-x86_64-unknown-linux-gnu"
    stage.mkdir(parents=True)
    (stage / "uv").write_text(_FAKE_UV.replace("$FIXTURES", str(fixtures)), encoding="utf-8")
    (stage / "uv").chmod(0o755)
    (fixtures / "parrot").write_text(fake_parrot, encoding="utf-8")
    tarball = fixtures / "uv.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(stage, arcname="uv-x86_64-unknown-linux-gnu")
    digest = hashlib.sha256(tarball.read_bytes()).hexdigest()
    (fixtures / "uv.tar.gz.sha256").write_text(f"{digest}  uv-x86_64-unknown-linux-gnu.tar.gz\n", encoding="utf-8")
    path = _fake_bin(
        tmp_path,
        scripts={"uname": _FAKE_UNAME, "curl": _FAKE_CURL.replace("$FIXTURES", str(fixtures))},
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {
        "HOME": str(tmp_path / "home"),
        "PARROT_HOME": str(tmp_path / "home" / ".parrot"),
        "SHELL": "/bin/bash",
        "TMPDIR": str(scratch),
        "PATH": path,
    }
    return subprocess.run(["bash", str(SCRIPT), "--global"], capture_output=True, text=True, check=False, env=env)


_PARROT_RUNTIME_BROKEN = "#!/bin/sh\necho 'uv: missing — fix: rerun the bootstrap'; exit 1\n"
_PARROT_REPO_NOT_READY = (
    "#!/bin/sh\n"
    'case "$*" in *--runtime-only*) echo "runtime: ok"; exit 0;; esac\n'
    "echo 'gh: not authenticated — fix: gh auth login'; echo 'ledger: uncommitted'; exit 1\n"
)


def test_post_install_runtime_failure_rolls_back(tmp_path: Path) -> None:
    """C14b: a failing `parrot self doctor --runtime-only` removes what the run created."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_RUNTIME_BROKEN)
    assert result.returncode != 0
    assert "self doctor --runtime-only" in result.stdout and "suggested fixes are printed above" in result.stderr
    assert not (tmp_path / "home" / ".parrot").exists()
    rc_file = tmp_path / "home" / ".bashrc"
    assert not rc_file.exists() or "# >>> parrot >>>" not in rc_file.read_text(encoding="utf-8")


def test_post_install_repo_readiness_failures_keep_runtime(tmp_path: Path) -> None:
    """C14b: unauthenticated gh / uncommitted ledger / outdated SDD assets never roll back a healthy runtime."""
    result = _run_offline_install(tmp_path, fake_parrot=_PARROT_REPO_NOT_READY)
    assert result.returncode == 0, result.stderr
    assert "--runtime-only" in result.stdout and "gh: not authenticated" not in result.stdout
    home = tmp_path / "home" / ".parrot"
    assert (home / "bin" / "parrot").exists() and (home / "venv").exists()
    assert (home / "bin" / "uv").exists()
    assert "# >>> parrot >>>" in (tmp_path / "home" / ".bashrc").read_text(encoding="utf-8")
