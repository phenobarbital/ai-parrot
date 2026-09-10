"""Opt-in host read guards for Claude Code and Codex (FEAT-543).

A ``PreToolUse`` hook that denies *unbounded* reads of large files and
replies with the exact bounded-reader call to make instead. It uses the same
thresholds as the MCP reader, and it is a convenience, not an enforcement
boundary: the reader's own limits hold regardless of whether this hook is
installed.

Scope is deliberately narrow and honestly documented (see
:func:`coverage_matrix`). v1 understands Claude's structured ``Read`` tool
and a small literal shell subset (``cat``, ``head``, ``tail``, ``less``,
``more``). Anything else — command substitution, redirection, globs,
compound statements, other interpreters — produces **no decision**, and the
host behaves normally. A pipe never makes a large read safe: the reading
segment decides.

Two invariants:

* **This module never breaks a host session.** Any exception, malformed
  payload, or unreadable file results in exit 0 with no output.
* **This module is stdlib-only at import.** No pydantic, no ``parrot.*``.
  A hook runs on every tool call, so its import cost must stay negligible.

Run as::

    python -m parrot_tools.tool_optimizations.hooks --host claude
    python -m parrot_tools.tool_optimizations.hooks --host codex
"""

import argparse
import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

__all__ = (
    "GuardDecision",
    "GuardPolicy",
    "DENY_VALUE",
    "build_reason",
    "count_lines_bounded",
    "coverage_matrix",
    "evaluate_read",
    "evaluate_shell",
    "is_large",
    "main",
    "parse_shell_subset",
    "render_output",
)

#: Programs whose default behaviour is to emit a whole file.
_READERS = frozenset({"cat", "less", "more"})

#: Programs that read a *bounded* prefix/suffix by default (10 lines).
_BOUNDED_READERS = frozenset({"head", "tail"})

#: Shell metacharacters that put a command outside the documented subset.
#: A match means "no decision" — never a denial, and never an approval.
_UNSAFE = re.compile(r"[;&<>`$*?\[\]{}~\n()!]")

_CHUNK = 1 << 16


@dataclass(frozen=True)
class GuardPolicy:
    """Thresholds and reader identity used by the guard.

    Attributes:
        max_lines: Line threshold above which a read must be bounded.
        large_file_bytes: Byte threshold above which a read must be bounded.
        reader_server: MCP server name to recommend in a denial.
        tool: Bounded-reader tool name to recommend in a denial.
    """

    max_lines: int = 350
    large_file_bytes: int = 64_000
    reader_server: str = "parrot-bounded-source"
    tool: str = "source_read"

    @classmethod
    def load(cls, root: Path) -> "GuardPolicy":
        """Load thresholds from ``<root>/.parrot/tool-guards.json``.

        Any problem — missing file, bad JSON, wrong types — falls back to
        the defaults rather than failing the host's tool call.

        Args:
            root: The repository root reported by the host.

        Returns:
            The effective policy.
        """
        try:
            raw = json.loads((root / ".parrot" / "tool-guards.json").read_text(encoding="utf-8"))
            return cls(
                max_lines=int(raw.get("max_lines", cls.max_lines)),
                large_file_bytes=int(raw.get("large_file_bytes", cls.large_file_bytes)),
                reader_server=str(raw.get("reader_server", cls.reader_server)),
                tool=str(raw.get("tool", cls.tool)),
            )
        except Exception:  # noqa: BLE001 — defaults are always acceptable
            return cls()


@dataclass
class GuardDecision:
    """The guard's verdict for one tool call.

    Attributes:
        deny: True when the call should be blocked.
        reason: The message shown to the assistant.
        path: The file the decision is about, if any.
        lines: The file's line count, when it was counted.
        size: The file's size in bytes.
        coverage: Which rule produced the verdict — ``structured``,
            ``shell``, ``unrecognized`` or ``not_applicable``.
    """

    deny: bool = False
    reason: str = ""
    path: Optional[str] = None
    lines: Optional[int] = None
    size: Optional[int] = None
    coverage: str = "not_applicable"


def count_lines_bounded(path: Path, stop_after: int) -> tuple[int, bool]:
    """Count logical lines, stopping early once the bound is exceeded.

    This intentionally duplicates
    :func:`parrot_tools.tool_optimizations.reader.count_lines_bounded`.
    Importing the reader would pull pydantic into a hook that runs on every
    tool call; twenty stdlib lines are cheaper than that. A test asserts the
    two implementations agree.

    Args:
        path: The file to count.
        stop_after: The threshold to compare against.

    Returns:
        A ``(count, exceeded)`` tuple; when ``exceeded`` the exact count is
        unknown and ``count`` is ``stop_after + 1``.
    """
    count = 0
    ended_with_newline = True
    saw_any = False
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            saw_any = True
            count += chunk.count(b"\n")
            ended_with_newline = chunk.endswith(b"\n")
            if count > stop_after:
                return stop_after + 1, True
    if saw_any and not ended_with_newline:
        count += 1
        if count > stop_after:
            return stop_after + 1, True
    return count, False


def is_large(path: Path, policy: GuardPolicy) -> tuple[bool, Optional[int], int]:
    """Decide whether a file exceeds either configured threshold.

    Only file metadata and newline counts are inspected; contents are never
    loaded.

    Args:
        path: The file to inspect.
        policy: The active policy.

    Returns:
        A ``(large, line_count_or_None, size_bytes)`` tuple. ``line_count``
        is None when counting stopped early.

    Raises:
        OSError: The path is unreadable.
        ValueError: The path is not a regular file.
    """
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{path} is not a regular file")
    if info.st_size > policy.large_file_bytes:
        return True, None, info.st_size
    count, exceeded = count_lines_bounded(path, policy.max_lines)
    return exceeded, (None if exceeded else count), info.st_size


def _resolve(candidate: str, cwd: Path) -> Path:
    """Resolve a caller path against the host's working directory."""
    path = Path(candidate).expanduser()
    return path if path.is_absolute() else (cwd / path)


def _decide_for_path(candidate: str, cwd: Path, policy: GuardPolicy, coverage: str) -> GuardDecision:
    """Build a decision for one file operand.

    Args:
        candidate: The path as written by the caller.
        cwd: The host's working directory.
        policy: The active policy.
        coverage: The rule that produced this decision.

    Returns:
        A denial when the file is large, otherwise a non-applicable verdict.
    """
    target = _resolve(candidate, cwd)
    try:
        large, lines, size = is_large(target, policy)
    except (OSError, ValueError):
        return GuardDecision(coverage="not_applicable")
    if not large:
        return GuardDecision(coverage=coverage, path=str(target), lines=lines, size=size)

    decision = GuardDecision(deny=True, coverage=coverage, path=str(target), lines=lines, size=size)
    decision.reason = build_reason(decision, policy, cwd)
    return decision


def evaluate_read(tool_input: dict[str, Any], cwd: Path, policy: GuardPolicy) -> GuardDecision:
    """Evaluate Claude Code's structured ``Read`` tool.

    Args:
        tool_input: The host's ``tool_input`` mapping.
        cwd: The host's working directory.
        policy: The active policy.

    Returns:
        The guard's verdict.
    """
    candidate = tool_input.get("file_path")
    if not isinstance(candidate, str) or not candidate:
        return GuardDecision(coverage="not_applicable")

    limit = tool_input.get("limit")
    if isinstance(limit, int) and 0 < limit <= policy.max_lines:
        # Already an explicitly bounded read.
        return GuardDecision(coverage="structured", path=candidate)

    return _decide_for_path(candidate, cwd, policy, "structured")


def parse_shell_subset(command: str) -> Optional[list[list[str]]]:
    """Parse a command if — and only if — it is in the documented subset.

    Args:
        command: The raw shell command.

    Returns:
        Pipeline segments as argv lists, or None when the command uses any
        construct outside the subset (in which case the guard makes no
        decision at all).
    """
    if not command or not command.strip():
        return None
    if _UNSAFE.search(command):
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None

    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token == "|":
            segments.append(current)
            current = []
            continue
        if "|" in token:
            # `||` (and any other pipe-bearing token) survives shlex as a
            # single token rather than a separator. Treating it as a plain
            # operand would silently swallow a compound statement.
            return None
        current.append(token)
    segments.append(current)
    return segments if all(segments) else None


def _is_bounded_invocation(argv: list[str], policy: GuardPolicy) -> bool:
    """Decide whether a head/tail invocation is explicitly bounded.

    Conservative by construction: anything this function cannot fully
    reason about is reported as **not** bounded, so the caller falls
    through to the size check instead of waving the command past.

    Three ways a naive reading fails open, all rejected here:

    * A **signed** count changes the meaning from "N lines" to "from/until
      line N" — ``tail -n +1 f`` and ``head -n -1 f`` both read essentially
      the whole file.
    * The ``--lines=N`` / ``-n=N`` *equals* form is a single token and is
      missed by a two-token-only parser.
    * ``tail -f`` (and any other unrecognized flag) is not a bounded read
      at all.

    A bare ``head file`` / ``tail file`` really does default to 10 lines
    and is the only case that is bounded without an explicit count.

    Args:
        argv: The segment's argv.
        policy: The active policy.

    Returns:
        True only when the invocation provably cannot exceed the thresholds.
    """
    if os.path.basename(argv[0]) not in _BOUNDED_READERS:
        return False

    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break  # everything after this is a file operand
        if not token.startswith("-") or token == "-":
            index += 1
            continue

        plain_count = re.fullmatch(r"-(\d+)", token)
        if plain_count:
            if int(plain_count.group(1)) > policy.max_lines:
                return False
            index += 1
            continue

        name, separator, inline = token.partition("=")
        if name in ("-n", "--lines", "-c", "--bytes"):
            if separator:
                value, step = inline, 1
            elif index + 1 < len(argv):
                value, step = argv[index + 1], 2
            else:
                return False
            # `isdigit()` rejects '+1' and '-1' — a signed count is not a bound.
            if not value.isdigit():
                return False
            limit = policy.max_lines if name in ("-n", "--lines") else policy.large_file_bytes
            if int(value) > limit:
                return False
            index += step
            continue

        if name in ("-q", "--quiet", "--silent", "-v", "--verbose", "-z", "--zero-terminated"):
            index += 1
            continue

        # Unrecognized flag (-f/--follow, --retry, ...): not reasoned about,
        # therefore not bounded.
        return False

    return True  # bare head/tail: 10 lines by default


def _file_operands(argv: list[str], program: str) -> Optional[list[str]]:
    """Extract literal file operands from a reader invocation.

    Only ``head`` and ``tail`` take a *value* after ``-n``/``-c``. For
    ``cat``, ``less`` and ``more``, ``-n`` is a valueless flag (``cat -n``
    numbers output lines), so treating it as value-consuming would swallow
    the filename and leave no operand to size-check — a silent fail-open.

    Args:
        argv: The segment's argv.
        program: The basename of ``argv[0]``.

    Returns:
        The operands, or None when stdin is used (nothing to check).
    """
    consumes_value = program in _BOUNDED_READERS
    operands: list[str] = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--":
            operands.extend(argv[index + 1 :])
            break
        if token == "-":
            return None  # explicit stdin
        if token.startswith("-"):
            name, separator, _inline = token.partition("=")
            if consumes_value and not separator and name in ("-n", "--lines", "-c", "--bytes"):
                index += 2
                continue
            index += 1
            continue
        operands.append(token)
        index += 1
    return operands


def evaluate_shell(command: str, cwd: Path, policy: GuardPolicy) -> GuardDecision:
    """Evaluate a shell command against the documented reader subset.

    Args:
        command: The raw shell command.
        cwd: The host's working directory.
        policy: The active policy.

    Returns:
        The guard's verdict. Unrecognised commands yield ``unrecognized``,
        which renders no output.
    """
    segments = parse_shell_subset(command)
    if segments is None:
        return GuardDecision(coverage="unrecognized")

    for argv in segments:
        program = os.path.basename(argv[0])
        if program not in _READERS and program not in _BOUNDED_READERS:
            continue
        if program in _BOUNDED_READERS and _is_bounded_invocation(argv, policy):
            continue
        operands = _file_operands(argv, program)
        if operands is None:
            return GuardDecision(coverage="not_applicable")
        for operand in operands:
            decision = _decide_for_path(operand, cwd, policy, "shell")
            if decision.deny:
                return decision
    return GuardDecision(coverage="shell")


def build_reason(decision: GuardDecision, policy: GuardPolicy, cwd: Optional[Path] = None) -> str:
    """Build the denial message, naming the exact call to make instead.

    Args:
        decision: The denial being explained.
        policy: The active policy.
        cwd: The host's working directory, used to relativize the path.

    Returns:
        A concise, actionable reason.
    """
    path = Path(decision.path or "")
    display = str(path)
    if cwd is not None:
        try:
            display = str(path.relative_to(cwd))
        except ValueError:
            display = str(path)

    measured = f"{decision.lines} lines" if decision.lines is not None else f"more than {policy.max_lines} lines"
    arguments = json.dumps({"path": display, "start_line": 1, "end_line": policy.max_lines}, ensure_ascii=False)
    return (
        f"{display} is {measured} / {decision.size} bytes "
        f"(> {policy.max_lines} lines or {policy.large_file_bytes:,} bytes). "
        f"Use the bounded reader instead: MCP server '{policy.reader_server}' tool '{policy.tool}' "
        f"with {arguments}; continue with the returned next_line and expected_sha256."
    )


#: The refusal value each host's PreToolUse decision enum accepts.
#:
#: Both hosts accept ``deny`` inside ``hookSpecificOutput.permissionDecision``.
#: Codex's legacy *top-level* ``decision`` uses ``block`` instead; putting
#: that legacy value inside the structured envelope fails open.
DENY_VALUE = {"claude": "deny", "codex": "deny"}


def render_output(decision: Optional[GuardDecision], host: str) -> Optional[str]:
    """Render a host-appropriate hook response.

    Both hosts use ``deny`` within the ``hookSpecificOutput`` envelope.

    Args:
        decision: The guard's verdict, if any.
        host: ``claude`` or ``codex``.

    Returns:
        The JSON to print, or None when there is no decision to report.
    """
    if decision is None or not decision.deny:
        return None
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": DENY_VALUE.get(host, "deny"),
            "permissionDecisionReason": decision.reason,
        }
    }
    return json.dumps(payload, ensure_ascii=False)


def coverage_matrix() -> list[dict[str, Any]]:
    """Return the honest, machine-readable coverage table.

    Publishing what the guard does **not** intercept is deliberate: a guard
    that appears total but is not creates a false sense of enforcement.

    Returns:
        Rows of ``{"form", "covered", "note"}``.
    """
    return [
        {
            "form": "Claude Read (file_path)",
            "covered": True,
            "note": "Structured tool input; honours a limit <= max_lines.",
        },
        {"form": "cat FILE", "covered": True, "note": "Literal operand; denied when the file is large."},
        {"form": "head -n N FILE / head -N FILE", "covered": True, "note": "Allowed when N <= max_lines."},
        {"form": "tail -c N FILE", "covered": True, "note": "Allowed when N <= large_file_bytes."},
        {"form": "bare head FILE / tail FILE", "covered": True, "note": "Defaults to 10 lines, so bounded."},
        {"form": "less FILE / more FILE", "covered": True, "note": "Treated as a whole-file read."},
        {"form": "cat FILE | head -20", "covered": True, "note": "The reading segment decides; a pipe is not safe."},
        {"form": "cat FILE; other", "covered": False, "note": "Compound statement — outside the parsed subset."},
        {"form": "cat $(echo FILE)", "covered": False, "note": "Command substitution is never evaluated."},
        {"form": "cat *.py", "covered": False, "note": "Glob expansion is the shell's, not ours."},
        {"form": "cat < FILE", "covered": False, "note": "Redirection is outside the subset."},
        {"form": "sed -n '1,500p' FILE", "covered": False, "note": "sed is not an intercepted program."},
        {"form": "awk 'NR<500' FILE", "covered": False, "note": "awk is not an intercepted program."},
        {
            "form": "python -c \"open('FILE').read()\"",
            "covered": False,
            "note": "Arbitrary interpreters are not parsed.",
        },
        {"form": "xargs cat", "covered": False, "note": "Operands arrive on stdin, not in the argv we can see."},
        {"form": "heredoc (<<EOF)", "covered": False, "note": "Outside the subset."},
        {"form": "Codex write_stdin", "covered": False, "note": "Documented host gap: it does not re-run PreToolUse."},
        {"form": "Codex hosted tools", "covered": False, "note": "Not hookable by the host."},
        {"form": "Grep / Glob", "covered": False, "note": "Out of scope; the guard matcher is Read|Bash."},
        {"form": "WebFetch", "covered": False, "note": "Not a local file read."},
        {"form": "Interactive shell session input", "covered": False, "note": "Not mediated by PreToolUse."},
    ]


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse the hook's command line.

    Args:
        argv: Argument list, or None for ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(prog="parrot-tool-guard", description="PreToolUse read guard.")
    parser.add_argument("--host", choices=("claude", "codex"), default="claude")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None, stdin: Any = None, stdout: Any = None) -> int:
    """Run the guard over one hook payload.

    Always returns 0. A denial is communicated by the printed JSON, never by
    the exit code, and any internal failure results in silence — a broken
    guard must not break the host session.

    Args:
        argv: Command-line arguments.
        stdin: Input stream carrying the hook JSON.
        stdout: Output stream for the decision.

    Returns:
        Always 0.
    """
    stream_in = stdin if stdin is not None else sys.stdin
    stream_out = stdout if stdout is not None else sys.stdout
    try:
        args = _parse_args(argv)
        payload = json.load(stream_in)
        cwd = Path(payload.get("cwd") or os.getcwd())
        policy = GuardPolicy.load(cwd)
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input") or {}

        decision: Optional[GuardDecision]
        if tool_name == "Read":
            decision = evaluate_read(tool_input, cwd, policy)
        elif tool_name == "Bash":
            decision = evaluate_shell(str(tool_input.get("command", "")), cwd, policy)
        else:
            decision = None

        rendered = render_output(decision, args.host)
        if rendered:
            stream_out.write(rendered)
            stream_out.flush()
    except Exception:  # noqa: BLE001 — never break the host session
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover — process entry point
    sys.exit(main())
