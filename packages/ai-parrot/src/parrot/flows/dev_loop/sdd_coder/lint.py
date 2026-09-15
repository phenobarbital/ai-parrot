"""Engine-owned per-task lint pass for coder branches.

Formatting and auto-fixable lint are mechanical, so the engine runs them at the merge
boundary instead of spending coder-LLM turns on them: ``ruff check --fix`` plus the repo's
declared formatter over the task's changed ``.py`` files, committed on the attempt branch.
What remains is reported, never blocking — correctness findings (``LintConfig.error_select``)
go to the orchestrator to fix, style residue is left for the single full pass in ``/sdd-done``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import List, Optional, Tuple

from parrot.flows.dev_loop.sdd_coder.models import LintConfig, LintReport

_RESIDUAL_LIMIT = 50


async def _run(argv: List[str], cwd: str) -> Tuple[int, str, str]:
    """Run a subprocess and return ``(returncode, stdout, stderr)``; OS errors surface as rc 127."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
    except (FileNotFoundError, OSError) as exc:
        return 127, "", str(exc)
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def resolve_bin(name: str) -> Optional[str]:
    """Locate ``name`` on ``PATH``, falling back to the interpreter's own bin dir.

    The MCP server is launched by absolute path (``.venv/bin/parrot``), so its ``PATH`` may
    not include the venv that ships ruff/black.

    Args:
        name: Executable name, e.g. ``"ruff"``.

    Returns:
        The absolute executable path, or ``None`` when not found.
    """
    found = shutil.which(name)
    if found:
        return found
    sibling = Path(sys.executable).parent / name
    return str(sibling) if sibling.is_file() and os.access(sibling, os.X_OK) else None


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def detect_formatter(cwd: str, configured: str) -> str:
    """Resolve the formatter for the repo checked out at ``cwd``.

    Args:
        cwd: Repository (sub-worktree) root.
        configured: ``LintConfig.formatter``; anything but ``"auto"`` is returned as-is.

    Returns:
        ``"black"``, ``"ruff"`` or ``"none"``.
    """
    if configured != "auto":
        return configured
    root = Path(cwd)
    tool = _load_toml(root / "pyproject.toml").get("tool", {})
    if "black" in tool:
        return "black"
    if "format" in tool.get("ruff", {}):
        return "ruff"
    for name in ("ruff.toml", ".ruff.toml"):
        if "format" in _load_toml(root / name):
            return "ruff"
    return "none"


async def _ruff_findings(ruff: str, cwd: str, files: List[str], select: Optional[List[str]]) -> Tuple[List[str], str]:
    """Run ``ruff check --no-fix`` and format findings as ``path:row: CODE message``."""
    argv = [ruff, "check", "--no-fix", "--output-format", "json"]
    if select:
        argv += ["--select", ",".join(select)]
    rc, out, err = await _run([*argv, *files], cwd)
    if rc not in (0, 1):
        return [], f"ruff exit {rc}: {err.strip()}"
    try:
        items = json.loads(out or "[]")
    except json.JSONDecodeError:
        return [], "ruff: unparseable output"
    return _format_findings(items, cwd), ""


def _format_findings(items: List[dict], cwd: str) -> List[str]:
    """Render ruff JSON findings as ``path:row: CODE message`` relative to ``cwd``."""
    findings = []
    for item in items:
        rel = os.path.relpath(item.get("filename", ""), cwd)
        row = (item.get("location") or {}).get("row", 0)
        code = item.get("code") or "syntax-error"
        findings.append(f"{rel}:{row}: {code} {item.get('message', '')}")
    return findings


def _existing_python_files(cwd: str, changed: List[str]) -> List[str]:
    """The changed paths that are ``.py`` files still present in ``cwd`` (deletions excluded)."""
    return [p for p in changed if p.endswith(".py") and Path(cwd, p).is_file()]


async def run_lint_pass(cwd: str, changed: List[str], *, config: LintConfig, commit_message: str) -> LintReport:
    """Auto-fix, format, commit and report lint for the changed ``.py`` files of one task branch.

    Never raises and never blocks: a missing tool or failed commit is recorded in
    ``LintReport.tool_error`` and the working tree is restored to the committed state.

    Args:
        cwd: The attempt sub-worktree (its branch is checked out there, tree clean).
        changed: Repo-relative paths the branch changed against the feature branch.
        config: Engine lint settings.
        commit_message: Message for the autofix commit.

    Returns:
        The lint report attached to the task result.
    """
    py_files = await asyncio.to_thread(_existing_python_files, cwd, changed)
    if not py_files:
        return LintReport()
    ruff = resolve_bin("ruff")
    if ruff is None:
        return LintReport(tool_error="ruff not found")
    formatter = await asyncio.to_thread(detect_formatter, cwd, config.formatter)
    report = LintReport(formatter=formatter)
    tool_errors: List[str] = []

    if config.autofix:
        await _run([ruff, "check", "--fix", "--exit-zero", "--quiet", *py_files], cwd)
        if formatter == "black":
            black = resolve_bin("black")
            if black is None:
                tool_errors.append("black not found")
            else:
                await _run([black, "--quiet", *py_files], cwd)
        elif formatter == "ruff":
            await _run([ruff, "format", "--quiet", *py_files], cwd)

        _rc, status, _err = await _run(["git", "status", "--porcelain", "--", *py_files], cwd)
        fixed = [line[3:] for line in status.splitlines() if line.strip()]
        if fixed:
            await _run(["git", "add", "--", *fixed], cwd)
            rc, _out, err = await _run(["git", "commit", "--no-verify", "-m", commit_message], cwd)
            if rc == 0:
                _rc, sha, _err = await _run(["git", "rev-parse", "--short", "HEAD"], cwd)
                report.fixed_files, report.commit = fixed, sha.strip()
            else:
                await _run(["git", "reset", "--quiet", "--", *fixed], cwd)
                await _run(["git", "checkout", "--", *fixed], cwd)
                tool_errors.append(f"autofix commit failed: {err.strip()}")

    errors, err_msg = await _ruff_findings(ruff, cwd, py_files, config.error_select)
    residual, res_msg = await _ruff_findings(ruff, cwd, py_files, None)
    tool_errors += [m for m in (err_msg, res_msg) if m]
    error_set = set(errors)
    residual = [f for f in residual if f not in error_set]
    report.errors = errors
    report.residual_count = len(residual)
    report.residual = residual[:_RESIDUAL_LIMIT]
    report.tool_error = "; ".join(tool_errors)
    return report
