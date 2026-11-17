#!/usr/bin/env python3
"""Clean-install smoke harness for ai-parrot (FEAT-633 spike S1; reused by TASK-4094).

Stdlib only: runs under a bare uv-managed interpreter before ai-parrot exists.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCRIPTS: tuple[str, ...] = ("parrot", "wikitoolkit", "bookstore")
DEFAULT_SPEC = "ai-parrot ai-parrot-tools"  # rev 0.5 C20: wikitoolkit mcp's wiki tools live in parrot_tools.wiki
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "parrot-smoke", "version": "0"}},
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
REQUIRED_TOOL = "wiki_query"


class SmokeError(RuntimeError):
    """Raised when a smoke step fails; the message is recorded in ``SmokeReport.errors``."""


@dataclass
class SmokeReport:
    """JSON-serialisable outcome of one smoke run."""

    platform: str
    python: str
    install_ok: bool = False
    sdist_failures: list[str] = field(default_factory=list)
    scripts_ok: dict[str, bool] = field(default_factory=dict)
    mcp_ok: bool = False
    errors: list[str] = field(default_factory=list)


def venv_script(venv: Path, name: str, *, os_name: str | None = None) -> Path:
    """Return ``venv/bin/<name>`` on POSIX, ``venv/Scripts/<name>.exe`` on Windows."""
    if (os_name or os.name) == "nt":
        return venv / "Scripts" / f"{name}.exe"  # build via `/` — never Path(...) (WindowsPath fails on POSIX)
    return venv / "bin" / name


def _read_line(proc: subprocess.Popen, timeout: float, what: str) -> str:
    """Read one stdout line of ``proc`` on a helper thread (select() fails on Windows pipes)."""
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
    try:
        return lines.get(timeout=timeout)
    except queue.Empty as exc:
        raise SmokeError(f"no {what} response within {timeout}s") from exc


def _parse_response(line: str, expected_id: int, what: str) -> dict:
    if not line.strip():
        raise SmokeError(f"{what}: server closed stdout without a response")
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{what}: non-JSON bytes on stdout (pollution): {line.strip()[:200]!r}") from exc
    if not isinstance(message, dict) or message.get("id") != expected_id:
        raise SmokeError(f"{what}: unexpected response id: {line.strip()[:200]!r}")
    return message


def mcp_initialize(cmd: list[str], cwd: Path, timeout: float = 30.0) -> dict:
    """Spawn ``cmd`` as a stdio MCP server, send ``initialize``, return the parsed response.

    After the handshake it sends ``notifications/initialized`` and ``tools/list`` and requires
    ``wiki_query`` among the listed tools — but only when the server answers ``tools/list``
    with a tool list at all; a server that lists tools without any wiki tool fails.

    Raises:
        SmokeError: on timeout, a non-JSON first stdout line (stdout pollution), a
            response without ``result.protocolVersion``, a mismatched ``id`` or a
            ``tools/list`` without the wiki tools.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        proc.stdin.write(json.dumps(INITIALIZE) + "\n")
        proc.stdin.flush()
        response = _parse_response(_read_line(proc, timeout, "initialize"), 1, "initialize")
        if "protocolVersion" not in (response.get("result") or {}):
            raise SmokeError(f"initialize: result lacks protocolVersion: {response!r}")
        proc.stdin.write(json.dumps(INITIALIZED) + "\n" + json.dumps(TOOLS_LIST) + "\n")
        proc.stdin.flush()
        listing = _parse_response(_read_line(proc, timeout, "tools/list"), 2, "tools/list")
        names = {t.get("name") for t in (listing.get("result") or {}).get("tools", [])}
        if REQUIRED_TOOL not in names:
            raise SmokeError(f"tools/list lacks {REQUIRED_TOOL}: {sorted(n for n in names if n)}")
        return response
    except SmokeError as exc:
        tail = _stderr_tail(proc)
        if tail:
            raise SmokeError(f"{exc}\n--- stderr tail ---\n{tail}") from exc
        raise
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()


def _stderr_tail(proc: subprocess.Popen, limit: int = 2000) -> str:
    """Return the tail of the child's stderr, killing it first so the read cannot block."""
    if proc.poll() is None:
        proc.kill()
    try:
        return (proc.stderr.read() or "")[-limit:]
    except (OSError, ValueError):
        return ""


def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 1800.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)


#: uv's resolver form under ``--no-build``: "Wheels are required for `pkg` because building from source is disabled".
_WHEELS_REQUIRED_RE = re.compile(r"Wheels are required for `([A-Za-z0-9_.\-]+)`", re.IGNORECASE)
_SDIST_RE = re.compile(
    r"(?:Failed to build|building)(?! from source)[`'\s]+([A-Za-z0-9_.\-]+)", re.IGNORECASE
)
_NO_BUILD_RE = re.compile(r"`?([A-Za-z0-9_.\-]+)[=<>!~@ ][^\n]*?(?:no source distribution|--no-build|sdist)", re.IGNORECASE)


def parse_sdist_failures(stderr: str) -> list[str]:
    """Extract the package names uv refused (or failed) to build from source."""
    found: list[str] = []
    for line in stderr.splitlines():
        lowered = line.lower()
        if "no-build" not in lowered and "build" not in lowered and "sdist" not in lowered:
            continue
        for regex in (_WHEELS_REQUIRED_RE, _SDIST_RE, _NO_BUILD_RE):
            match = regex.search(line)
            if match and match.group(1) not in found:
                found.append(match.group(1))
                break
    return found


def run_smoke(spec: str | None, wheels: list[Path], python: str, no_build: bool) -> SmokeReport:
    """Create a temp uv venv, install, run the three scripts' ``--help`` and the MCP handshake.

    ``spec`` is a whitespace-separated requirement list (``DEFAULT_SPEC``); ``wheels`` are local
    wheels installed together instead (core + ai-parrot-tools, rev 0.5 C20).
    """
    report = SmokeReport(platform=f"{platform.system()}-{platform.machine()}", python=python)
    uv = shutil.which("uv")
    if uv is None:
        report.errors.append("uv not found on PATH")
        return report
    with tempfile.TemporaryDirectory(prefix="parrot-smoke-") as tmp:
        venv, repo = Path(tmp) / "venv", Path(tmp) / "repo"
        # navconfig derives its project root from the venv's parent and refuses to start without env/<env>/.env
        (Path(tmp) / "env" / "dev").mkdir(parents=True)
        (Path(tmp) / "env" / "dev" / ".env").write_text("", encoding="utf-8")
        created = _run([uv, "venv", str(venv), "--python", python])
        if created.returncode != 0:
            report.errors.append(f"uv venv failed: {created.stderr.strip()[-500:]}")
            return report
        targets = [str(w) for w in wheels] if wheels else (spec or DEFAULT_SPEC).split()
        interpreter = venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"
        install = [uv, "pip", "install", "--python", str(interpreter)]
        if no_build:
            install.append("--no-build")
        installed = _run(install + targets)
        if installed.returncode != 0:
            report.sdist_failures = parse_sdist_failures(installed.stderr)
            report.errors.append(f"install failed: {installed.stderr.strip()[-1500:]}")
            return report
        report.install_ok = True
        for name in SCRIPTS:
            try:
                report.scripts_ok[name] = _run([str(venv_script(venv, name)), "--help"], timeout=300).returncode == 0
            except (OSError, subprocess.TimeoutExpired) as exc:
                report.scripts_ok[name] = False
                report.errors.append(f"{name} --help: {exc}")
        wikitoolkit = str(venv_script(venv, "wikitoolkit"))
        try:
            repo.mkdir()
            env_git = ["git", "-c", "user.email=smoke@example.com", "-c", "user.name=smoke"]
            _run(["git", "init", "-q"], cwd=repo)
            (repo / "README.md").write_text("# smoke\n", encoding="utf-8")
            _run(["git", "add", "README.md"], cwd=repo)
            _run(env_git + ["commit", "-q", "-m", "init"], cwd=repo)
            built = _run([wikitoolkit, "build", "--quiet", "--no-export", "--no-graph"], cwd=repo, timeout=600)
            if built.returncode != 0:
                report.errors.append(f"wikitoolkit build failed: {built.stderr.strip()[-800:]}")
                return report
            mcp_initialize([wikitoolkit, "mcp"], repo)
            report.mcp_ok = True
        except SmokeError as exc:
            message = str(exc)
            if "parrot_tools" in message:
                message = f"missing-dependency (parrot_tools import error; ai-parrot-tools absent?): {message}"
            report.errors.append(message)
        except (OSError, subprocess.TimeoutExpired) as exc:
            report.errors.append(f"mcp smoke: {exc}")
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry: exit 0 iff install, all scripts and the MCP handshake succeeded."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--spec", default=None, help=f"whitespace-separated pip requirements (default: {DEFAULT_SPEC})")
    source.add_argument("--wheel", type=Path, action="append", default=None,
                        help="local wheel to install instead; repeat for core + ai-parrot-tools")
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--no-build", dest="no_build", action="store_true", default=True)
    parser.add_argument("--allow-build", dest="no_build", action="store_false")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_smoke(args.spec or (None if args.wheel else DEFAULT_SPEC), args.wheel or [], args.python, args.no_build)
    payload = json.dumps(asdict(report), indent=2)
    if args.json_out:
        args.json_out.write_text(payload, encoding="utf-8")
    sys.stderr.write(payload + "\n")
    return 0 if report.install_ok and all(report.scripts_ok.values()) and report.mcp_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
