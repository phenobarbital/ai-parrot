"""Host smoke tests: pin versions, exercise the guard, report gaps (TASK-3091).

A host being absent is never a failure — it is recorded as an explicitly
unsupported configuration, per the spec's requirement to "report unsupported
configurations explicitly" rather than imply coverage that does not exist.
"""

import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from parrot_tools.tool_optimizations.hooks import main as hook_main
from parrot_tools.tool_optimizations.installation import HOOK_MODULE, guard_status, install_guards

from .conftest import ARTIFACT_LOGS, record_json


def _version(binary: str):
    """Read a host binary's version, or None when it is absent/silent."""
    path = shutil.which(binary)
    if not path:
        return None
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0] if output else None


@pytest.fixture(scope="module")
def host_versions():
    """Record the installed host versions as evidence."""
    versions = {host: _version(host) for host in ("claude", "codex")}
    ARTIFACT_LOGS.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_LOGS / "host-versions.txt").write_text(
        "\n".join(f"{host}: {version or 'NOT INSTALLED'}" for host, version in versions.items()) + "\n",
        encoding="utf-8",
    )
    return versions


def test_host_versions_are_recorded(host_versions):
    """The suite always records what it was run against."""
    assert (ARTIFACT_LOGS / "host-versions.txt").is_file()
    assert set(host_versions) == {"claude", "codex"}


def test_guard_denies_a_large_read_through_the_hook_runtime(tmp_path):
    """The guard runtime is exercised directly for both hosts.

    Claude Code's hook runner cannot be driven headlessly, so the hook
    module itself is invoked with a synthetic payload — the same payload
    shape the host documents.
    """
    (tmp_path / "big.py").write_text("".join(f"line{i}\n" for i in range(1, 401)))
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "big.py"},
        "cwd": str(tmp_path),
    }

    outputs = {}
    for host in ("claude", "codex"):
        stdout = io.StringIO()
        assert hook_main(["--host", host], stdin=io.StringIO(json.dumps(payload)), stdout=stdout) == 0
        outputs[host] = stdout.getvalue()

    expected = {"claude": "deny", "codex": "deny"}
    for host, raw in outputs.items():
        decision = json.loads(raw)["hookSpecificOutput"]
        # Structured permission decisions use deny on both hosts.
        assert decision["permissionDecision"] == expected[host], host
        assert "source_read" in decision["permissionDecisionReason"]


def test_installed_claude_settings_match_the_documented_schema(tmp_path):
    """`install_guards` writes an entry with the documented hook shape."""
    install_guards(tmp_path, "claude")
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())

    entries = settings["hooks"]["PreToolUse"]
    ours = [entry for entry in entries if HOOK_MODULE in json.dumps(entry)]
    assert len(ours) == 1

    entry = ours[0]
    assert entry["matcher"] == "Read|Bash"
    hook = entry["hooks"][0]
    assert hook["type"] == "command"
    assert hook["timeout"] == 10
    assert "--host claude" in hook["command"]
    assert hook["command"].split()[0].startswith("/"), "the interpreter path must be absolute"


def test_codex_hooks_file_matches_the_documented_schema(tmp_path):
    """`install_guards` writes a project-scoped Codex hooks file."""
    install_guards(tmp_path, "codex")
    hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    entry = hooks["hooks"]["PreToolUse"][0]

    assert entry["matcher"] == "Bash"
    assert "--host codex" in entry["hooks"][0]["command"]


def test_host_support_report_is_written(tmp_path, host_versions):
    """Produce an explicit supported/unsupported report for both hosts."""
    install_guards(tmp_path, "claude")
    install_guards(tmp_path, "codex")

    report = {}
    for host in ("claude", "codex"):
        status = guard_status(tmp_path, host)
        report[host] = {
            "version": host_versions[host],
            "installed": status["installed"],
            "supported": status["supported"],
            "exercised_end_to_end": False,
            "note": (
                "binary not installed — guard policy unit-tested only"
                if host_versions[host] is None
                else "guard runtime exercised directly; the host's own hook runner was not driven headlessly"
            ),
        }
        assert status["installed"] is True

    codex_smoke = _maybe_run_codex_smoke(tmp_path)
    if codex_smoke is not None:
        report["codex"].update(codex_smoke)

    report["codex"]["structured_denial"] = "deny"
    report["codex"]["hooks_file_format_verified"] = report["codex"]["exercised_end_to_end"]
    report["codex"]["activation"] = (
        "Project trust and per-hook trust are required. Live smoke acknowledges hook trust "
        "only for its reviewed temporary fixture; normal sessions require /hooks review."
    )

    record_json("host-smoke.json", report)
    assert (ARTIFACT_LOGS / "host-smoke.json").is_file()
    if codex_smoke is not None and host_versions["codex"] is not None:
        assert codex_smoke["exercised_end_to_end"], codex_smoke


def _maybe_run_codex_smoke(root: Path) -> dict[str, Any] | None:
    """Optionally drive a real `codex exec` to observe a guard denial.

    Gated on PARROT_TOOL_OPT_HOST_SMOKE=1 because it starts a real agent
    session; absent that, the result is reported as not exercised.
    """
    if os.environ.get("PARROT_TOOL_OPT_HOST_SMOKE") != "1":
        return None
    binary = shutil.which("codex")
    if not binary:
        return {"note": "codex binary not installed"}

    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".codex" / "config.toml").touch()
    (root / "big.py").write_text("".join(f"line{i}\n" for i in range(1, 401)))
    (root / "small.py").write_text("SMALL_READ_OK\n")
    prompt = (
        "This is a hook integration test. Run exactly these three shell tool calls separately, "
        "in order, even if the first is blocked: cat big.py; head -n 20 big.py; cat small.py. "
        "Do not combine commands, inspect other files, or use alternatives. "
        "Report each result and include the exact error if a call is blocked."
    )
    try:
        result = subprocess.run(
            [
                binary,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--dangerously-bypass-hook-trust",
                "-c",
                f'projects={{{json.dumps(str(root))}={{trust_level="trusted"}}}}',
                "-C",
                str(root),
                "--json",
                prompt,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exercised_end_to_end": False, "note": f"codex exec failed to start: {exc}"}

    (ARTIFACT_LOGS / "codex-host-smoke.jsonl").write_text(result.stdout)
    (ARTIFACT_LOGS / "codex-host-smoke.stderr").write_text(result.stderr)
    observation = _codex_smoke_observation(result.stdout)
    return {
        **observation,
        "exercised_end_to_end": result.returncode == 0 and all(observation.values()),
        "note": "Checks require a blocked large read, successful bounded and small reads, and no large-file execution.",
        "exit_code": result.returncode,
    }


def _codex_smoke_observation(transcript: str) -> dict[str, bool]:
    """Reject failed-open runs even if the assistant mentions source_read."""
    events = [json.loads(line) for line in transcript.splitlines() if line.strip()]
    items = [event.get("item", {}) for event in events if event.get("type") == "item.completed"]
    commands = [item for item in items if item.get("type") == "command_execution"]
    messages = "\n".join(item.get("text", "") for item in items if item.get("type") == "agent_message")
    return {
        "denial_observed": "Command blocked by PreToolUse hook" in messages and "source_read" in messages,
        "large_read_not_executed": not any("cat big.py" in item.get("command", "") for item in commands),
        "bounded_read_succeeded": any(
            "head -n 20 big.py" in item.get("command", "")
            and item.get("exit_code") == 0
            and item.get("aggregated_output", "").splitlines() == [f"line{i}" for i in range(1, 21)]
            for item in commands
        ),
        "small_read_succeeded": any(
            "cat small.py" in item.get("command", "")
            and item.get("exit_code") == 0
            and item.get("aggregated_output", "").strip() == "SMALL_READ_OK"
            for item in commands
        ),
    }


def test_codex_smoke_rejects_a_failed_open_transcript() -> None:
    """A model mentioning the reader cannot disguise a successful large read."""
    items = [
        {"type": "command_execution", "command": "cat big.py", "exit_code": 0, "aggregated_output": "line1\n"},
        {"type": "agent_message", "text": "Command blocked by PreToolUse hook: use source_read"},
    ]
    transcript = "\n".join(json.dumps({"type": "item.completed", "item": item}) for item in items)
    observation = _codex_smoke_observation(transcript)
    assert not observation["large_read_not_executed"]
    assert not all(observation.values())


def test_coverage_matrix_is_published_as_evidence():
    """The honest coverage table ships alongside the smoke report."""
    from parrot_tools.tool_optimizations.hooks import coverage_matrix

    matrix = coverage_matrix()
    record_json("TASK-3091-guard-coverage.json", {"rows": matrix})

    covered = [row for row in matrix if row["covered"]]
    gaps = [row for row in matrix if not row["covered"]]
    assert covered and gaps, "the matrix must state both what is and is not intercepted"
