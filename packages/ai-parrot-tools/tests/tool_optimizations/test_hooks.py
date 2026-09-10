"""Tests for the opt-in host read guards (TASK-3088, FEAT-543)."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from parrot_tools.tool_optimizations.hooks import (
    GuardPolicy,
    build_reason,
    count_lines_bounded,
    coverage_matrix,
    evaluate_shell,
    main,
    parse_shell_subset,
)
from parrot_tools.tool_optimizations.reader import count_lines_bounded as reader_count_lines


@pytest.fixture
def workspace(tmp_path):
    """A directory holding a large and a small source file."""
    (tmp_path / "big.py").write_text("".join(f"line{i}\n" for i in range(1, 401)))
    (tmp_path / "small.py").write_text("".join(f"line{i}\n" for i in range(1, 101)))
    (tmp_path / "sub").mkdir()
    return tmp_path


def _run(payload, *, host="claude", cwd=None):
    """Drive main() with a hook payload and return its stdout."""
    if cwd is not None:
        payload.setdefault("cwd", str(cwd))
    stdout = io.StringIO()
    code = main(["--host", host], stdin=io.StringIO(json.dumps(payload)), stdout=stdout)
    assert code == 0, "the guard must always exit 0"
    return stdout.getvalue()


def _read_payload(path, **tool_input):
    """Build a Claude Read payload."""
    return {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": str(path), **tool_input}}


def _bash_payload(command):
    """Build a Bash payload."""
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}


# --------------------------------------------------------------------------- #
# Structured Read
# --------------------------------------------------------------------------- #
def test_structured_read_of_large_file_is_denied(workspace):
    """A large unbounded Read is denied with an actionable reason."""
    out = _run(_read_payload(workspace / "big.py"), cwd=workspace)
    payload = json.loads(out)["hookSpecificOutput"]

    assert payload["hookEventName"] == "PreToolUse"
    assert payload["permissionDecision"] == "deny"
    reason = payload["permissionDecisionReason"]
    assert "parrot-bounded-source" in reason
    assert "source_read" in reason
    assert '"start_line": 1' in reason
    assert '"end_line": 350' in reason
    assert "next_line" in reason and "expected_sha256" in reason
    assert "big.py" in reason


def test_structured_read_bounded_or_small_is_allowed(workspace):
    """An explicit limit, or a small file, produces no decision at all."""
    assert _run(_read_payload(workspace / "big.py", limit=200), cwd=workspace) == ""
    assert _run(_read_payload(workspace / "small.py"), cwd=workspace) == ""


def test_structured_read_limit_above_threshold_is_denied(workspace):
    """A 'limit' larger than max_lines is not a bound."""
    assert _run(_read_payload(workspace / "big.py", limit=1000), cwd=workspace) != ""


def test_relative_path_is_resolved_against_cwd(workspace):
    """Hosts may send a repo-relative path."""
    assert _run(_read_payload("big.py"), cwd=workspace) != ""
    assert _run(_read_payload("small.py"), cwd=workspace) == ""


# --------------------------------------------------------------------------- #
# Shell subset
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "command,denied",
    [
        ("cat big.py", True),
        ("cat small.py", False),
        ("head -n 50 big.py", False),
        ("head -50 big.py", False),
        ("head -400 big.py", True),
        ("head -n 400 big.py", True),
        ("tail -c 1000 big.py", False),
        ("tail big.py", False),
        ("head big.py", False),
        ("less big.py", True),
        ("more big.py", True),
        ("cat big.py | head -20", True),
        ("head -20 small.py | cat", False),
        ("/bin/cat big.py", True),
    ],
)
def test_shell_subset_decisions(workspace, command, denied):
    """The documented subset is intercepted; a pipe never excuses a big read."""
    out = _run(_bash_payload(command), cwd=workspace)
    assert bool(out) is denied, f"{command!r} produced {out!r}"


@pytest.mark.parametrize(
    "command",
    [
        "cat big.py; rm x",
        "cat big.py && echo done",
        "cat big.py || true",
        "cat $(echo big.py)",
        "cat `echo big.py`",
        "cat *.py",
        "cat < big.py",
        "cat big.py > out.txt",
        "sed -n '1,500p' big.py",
        "awk 'NR<500' big.py",
        "python -c \"open('big.py').read()\"",
        "xargs cat",
        "cat ~/big.py",
        "cat $HOME/big.py",
    ],
)
def test_coverage_gaps_make_no_decision(workspace, command):
    """Unrecognised forms leave host behaviour untouched — never a denial."""
    assert _run(_bash_payload(command), cwd=workspace) == ""


def test_stdin_operand_is_not_applicable(workspace):
    """An explicit '-' reads stdin, not a file."""
    assert _run(_bash_payload("cat -"), cwd=workspace) == ""


def test_multiple_operands_deny_on_the_large_one(workspace):
    """Every literal operand is evaluated."""
    assert _run(_bash_payload("cat small.py big.py"), cwd=workspace) != ""
    assert _run(_bash_payload("cat small.py small.py"), cwd=workspace) == ""


def test_parse_shell_subset_rejects_metacharacters():
    """The parser refuses anything it cannot reason about, before splitting."""
    assert parse_shell_subset("cat a.py") == [["cat", "a.py"]]
    assert parse_shell_subset("cat a.py | head -5") == [["cat", "a.py"], ["head", "-5"]]
    for command in ("cat a; b", "cat `x`", "cat $(x)", "cat *.py", "cat > x", "cat\nb", ""):
        assert parse_shell_subset(command) is None
    assert parse_shell_subset('cat "unterminated') is None


# --------------------------------------------------------------------------- #
# Robustness — the guard must never break a session
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "Read", "tool_input": {"file_path": "/nonexistent/nope.py"}},
        {"tool_name": "Read", "tool_input": {}},
        {"tool_name": "Bash", "tool_input": {}},
        {"tool_name": "Grep", "tool_input": {"pattern": "x"}},
        {"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}},
        {},
    ],
)
def test_unactionable_payloads_exit_quietly(workspace, payload):
    """Missing files, unknown tools and empty payloads produce no output."""
    assert _run(payload, cwd=workspace) == ""


def test_directory_path_is_not_applicable(workspace):
    """A directory is not a file read."""
    assert _run(_read_payload(workspace / "sub"), cwd=workspace) == ""


def test_malformed_stdin_exits_zero(workspace):
    """Non-JSON input can never crash the host."""
    stdout = io.StringIO()
    assert main(["--host", "claude"], stdin=io.StringIO("not json at all"), stdout=stdout) == 0
    assert stdout.getvalue() == ""


# --------------------------------------------------------------------------- #
# Hosts and configuration
# --------------------------------------------------------------------------- #
def test_each_host_gets_its_own_refusal_keyword(workspace):
    """Regression: Codex rejects `deny`; its enum is approve|block|allow.

    Verified against codex-cli 0.154.0, whose `PreToolUseDecisionWire`
    serde variants are `approve`, `block`, `allow`, and which reports
    "PreToolUse hook returned unsupported decision" otherwise. Sending
    Claude's `deny` to Codex fails open — the large read would proceed.
    """
    claude_payload = json.loads(_run(_bash_payload("cat big.py"), host="claude", cwd=workspace))
    codex_payload = json.loads(_run(_bash_payload("cat big.py"), host="codex", cwd=workspace))

    assert claude_payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert codex_payload["hookSpecificOutput"]["permissionDecision"] == "block"

    # Everything else about the envelope is shared.
    assert claude_payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert codex_payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert (
        claude_payload["hookSpecificOutput"]["permissionDecisionReason"]
        == codex_payload["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_deny_value_table_matches_each_host_enum():
    """The refusal keyword table is explicit, not incidental."""
    from parrot_tools.tool_optimizations.hooks import DENY_VALUE

    assert DENY_VALUE == {"claude": "deny", "codex": "block"}


def test_configured_thresholds_change_the_verdict(workspace):
    """`.parrot/tool-guards.json` drives the policy."""
    medium = workspace / "medium.py"
    medium.write_text("".join(f"line{i}\n" for i in range(1, 201)))
    assert _run(_read_payload(medium), cwd=workspace) == ""

    guards = workspace / ".parrot"
    guards.mkdir()
    (guards / "tool-guards.json").write_text(
        json.dumps({"max_lines": 100, "large_file_bytes": 64000, "reader_server": "my-reader", "tool": "source_read"})
    )
    out = _run(_read_payload(medium), cwd=workspace)
    assert out != ""
    assert "my-reader" in json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


def test_broken_guard_config_falls_back_to_defaults(workspace):
    """A corrupt config must not disable the guard or crash it."""
    guards = workspace / ".parrot"
    guards.mkdir()
    (guards / "tool-guards.json").write_text("{ not json")
    assert GuardPolicy.load(workspace) == GuardPolicy()
    assert _run(_read_payload(workspace / "big.py"), cwd=workspace) != ""


# --------------------------------------------------------------------------- #
# Import weight and helper agreement
# --------------------------------------------------------------------------- #
def test_hook_import_is_dependency_light():
    """A hook runs on every tool call; it must not import pydantic or parrot."""
    code = (
        "import sys, parrot_tools.tool_optimizations.hooks as h;"
        "print('pydantic' in sys.modules,"
        " any(m == 'parrot' or m.startswith('parrot.') for m in sys.modules))"
    )
    env = dict(os.environ)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env)
    assert result.stdout.strip() == "False False"


@pytest.mark.parametrize("count", [0, 1, 349, 350, 351])
def test_line_counter_agrees_with_the_reader(tmp_path, count):
    """The documented duplicate must not drift from the reader's version."""
    target = tmp_path / "f.txt"
    target.write_text("".join(f"l{i}\n" for i in range(count)))
    assert count_lines_bounded(target, 350) == reader_count_lines(target, 350)

    no_final_newline = tmp_path / "g.txt"
    no_final_newline.write_bytes(b"a\nb\nc")
    assert count_lines_bounded(no_final_newline, 350) == reader_count_lines(no_final_newline, 350)


# --------------------------------------------------------------------------- #
# Coverage matrix
# --------------------------------------------------------------------------- #
def test_coverage_matrix_is_honest_and_complete():
    """The published matrix must match what the tests above actually prove."""
    rows = {row["form"]: row for row in coverage_matrix()}
    assert all(set(row) == {"form", "covered", "note"} for row in rows.values())
    assert all(row["note"] for row in rows.values())

    covered = {form for form, row in rows.items() if row["covered"]}
    assert "Claude Read (file_path)" in covered
    assert "cat FILE" in covered
    assert "cat FILE | head -20" in covered

    for form in (
        "cat FILE; other",
        "cat $(echo FILE)",
        "cat *.py",
        "sed -n '1,500p' FILE",
        "python -c \"open('FILE').read()\"",
        "xargs cat",
        "heredoc (<<EOF)",
        "Codex write_stdin",
        "Grep / Glob",
        "WebFetch",
    ):
        assert form in rows, f"{form} missing from the coverage matrix"
        assert rows[form]["covered"] is False, f"{form} is claimed as covered but is not"


def test_build_reason_relativises_paths(tmp_path):
    """The suggested call uses a repo-relative path the reader will accept."""
    from parrot_tools.tool_optimizations.hooks import GuardDecision

    decision = GuardDecision(
        deny=True, path=str(tmp_path / "pkg" / "mod.py"), lines=400, size=9000, coverage="structured"
    )
    reason = build_reason(decision, GuardPolicy(), tmp_path)
    assert '"path": "pkg/mod.py"' in reason
    assert "400 lines" in reason
