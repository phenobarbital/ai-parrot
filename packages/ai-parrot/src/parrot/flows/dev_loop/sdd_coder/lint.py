"""Engine-owned per-task lint pass for coder branches.

Formatting and auto-fixable lint are mechanical, so the engine runs them at the merge
boundary instead of spending coder-LLM turns on them: ``ruff check --fix`` plus the repo's
declared formatter over the task's changed ``.py`` files, committed on the attempt branch.
What remains is reported, never blocking — correctness findings (``LintConfig.error_select``)
go to the orchestrator to fix, style residue is left for the single full pass in ``/sdd-done``.

The formatter is scoped to the lines the task actually changed (FEAT-702,
``LintConfig.format_scope``): a pre-existing file that is not formatter-clean at its base is
never reformatted wholesale under the task's name, so the autofix commit stays a minimal diff.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tomllib
from pathlib import Path
from typing import List, Optional, Tuple

from parrot.flows.dev_loop.procs import run_bounded
from parrot.flows.dev_loop.sdd_coder.models import LintConfig, LintReport

#: Wall-clock cap for one ruff/black child over a task's changed files.
LINT_TIMEOUT_S: float = 300.0

_RESIDUAL_LIMIT = 50


async def _run(argv: List[str], cwd: str) -> Tuple[int, str, str]:
    """Run a subprocess and return ``(returncode, stdout, stderr)``.

    OS errors surface as rc 127 and a `LINT_TIMEOUT_S` expiry as rc 124 (`run_bounded`).
    """
    return await run_bounded(argv, cwd=cwd, timeout_s=LINT_TIMEOUT_S)


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


#: ``@@ -<old>[,<n>] +<new>[,<n>] @@`` hunk headers of a ``git diff -U0`` stream.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def parse_unified_hunks(diff_text: str) -> List[Tuple[int, int]]:
    """Post-image ``(start, end)`` line ranges (1-based, inclusive) of every hunk in a ``-U0`` diff.

    Pure deletions (``+N,0``) are skipped: there is nothing left to format at that position.

    Args:
        diff_text: Output of ``git diff -U0`` for one file.

    Returns:
        The ranges in diff order, possibly empty.
    """
    ranges: List[Tuple[int, int]] = []
    for match in _HUNK_RE.finditer(diff_text):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count == 0:
            continue
        ranges.append((start, start + count - 1))
    return ranges


async def changed_line_ranges(cwd: str, diff_base: str, path: str) -> Tuple[Optional[List[Tuple[int, int]]], str]:
    """Line ranges of ``path`` in the working tree that differ from ``diff_base``.

    Args:
        cwd: The attempt sub-worktree.
        diff_base: The merge-base commit the task branch is compared against.
        path: Repo-relative path of one changed ``.py`` file.

    Returns:
        ``(ranges, error)``. ``ranges`` is ``None`` when the whole file must be formatted: the
        file has no base version (added by the task) or git failed, in which case ``error``
        names the failure (empty otherwise).
    """
    rc, out, err = await _run(["git", "diff", "-U0", "--no-color", diff_base, "--", path], cwd)
    if rc != 0:
        return None, f"line ranges unavailable for {path}: {err.strip() or f'git exit {rc}'}"
    if re.search(r"^--- /dev/null", out, re.MULTILINE):
        return None, ""
    return parse_unified_hunks(out), ""


async def _format_files(
    formatter: str, tool: str, cwd: str, py_files: List[str], *, diff_base: Optional[str], scope: str
) -> List[str]:
    """Run ``black`` or ``ruff format`` over ``py_files``, whole-file or changed-lines per ``scope``.

    Args:
        formatter: ``"black"`` or ``"ruff"``.
        tool: Resolved executable for that formatter.
        cwd: The attempt sub-worktree.
        py_files: The task's changed ``.py`` files.
        diff_base: Merge-base commit for changed-line detection; ``None`` means whole-file.
        scope: ``LintConfig.format_scope``.

    Returns:
        Tool-error notes (range computation fallbacks); empty when everything was scoped.
    """
    if scope == "file" or diff_base is None:
        if formatter == "black":
            await _run([tool, "--quiet", *py_files], cwd)
        else:
            await _run([tool, "format", "--quiet", *py_files], cwd)
        return []
    notes: List[str] = []
    for path in py_files:
        ranges, error = await changed_line_ranges(cwd, diff_base, path)
        if error:
            notes.append(error)
        if ranges is None:
            argv = [tool, "--quiet", path] if formatter == "black" else [tool, "format", "--quiet", path]
            await _run(argv, cwd)
            continue
        if not ranges:
            continue
        if formatter == "black":
            flags = [flag for start, end in ranges for flag in ("--line-ranges", f"{start}-{end}")]
            await _run([tool, "--quiet", *flags, path], cwd)
        else:
            # Bottom-up so a reformatted hunk cannot shift the line numbers of the hunks above it.
            # ruff's `--range A-B` means `A:1-B:1` (end exclusive at column 1), so the inclusive
            # post-image range [start, end] is `start-(end + 1)`; an end past EOF is accepted.
            for start, end in reversed(ranges):
                await _run([tool, "format", "--quiet", "--range", f"{start}-{end + 1}", path], cwd)
    return notes


async def run_lint_pass(
    cwd: str, changed: List[str], *, config: LintConfig, commit_message: str, diff_base: Optional[str] = None
) -> LintReport:
    """Auto-fix, format, commit and report lint for the changed ``.py`` files of one task branch.

    Never raises and never blocks: a missing tool or failed commit is recorded in
    ``LintReport.tool_error`` and the working tree is restored to the committed state.

    Args:
        cwd: The attempt sub-worktree (its branch is checked out there, tree clean).
        changed: Repo-relative paths the branch changed against the feature branch.
        config: Engine lint settings.
        commit_message: Message for the autofix commit.
        diff_base: Merge-base commit the branch is compared against; enables
            ``LintConfig.format_scope == "changed-lines"``. ``None`` formats whole files.

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
        # Ranges are computed AFTER `ruff --fix` so ruff's own edits are inside what gets formatted.
        if formatter == "black":
            black = resolve_bin("black")
            if black is None:
                tool_errors.append("black not found")
            else:
                tool_errors += await _format_files(
                    "black", black, cwd, py_files, diff_base=diff_base, scope=config.format_scope
                )
        elif formatter == "ruff":
            tool_errors += await _format_files(
                "ruff", ruff, cwd, py_files, diff_base=diff_base, scope=config.format_scope
            )

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
