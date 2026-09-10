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

    expected = {"claude": "deny", "codex": "block"}
    for host, raw in outputs.items():
        decision = json.loads(raw)["hookSpecificOutput"]
        # Each host has its own refusal keyword; see DENY_VALUE in hooks.py.
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

    # Evidence read directly from the installed codex binary (see the
    # TASK-3091 Completion Note). The refusal keyword is fixed; the on-disk
    # hooks.json field names are observed but NOT verified end to end.
    report["codex"]["observed_decision_enum"] = ["approve", "block", "allow"]
    report["codex"]["observed_hook_config_fields"] = ["eventName", "matcher", "timeoutSec", "command"]
    report["codex"]["hooks_file_format_verified"] = False
    report["codex"]["open_item"] = (
        "installed hooks.json uses Claude-style {hooks:{PreToolUse:[{matcher,hooks:[{type,command,timeout}]}]}}; "
        "codex 0.154.0 strings show eventName/timeoutSec fields. Verify end to end before release."
    )

    record_json("host-smoke.json", report)
    assert (ARTIFACT_LOGS / "host-smoke.json").is_file()


def _maybe_run_codex_smoke(root):
    """Optionally drive a real `codex exec` to observe a guard denial.

    Gated on PARROT_TOOL_OPT_HOST_SMOKE=1 because it starts a real agent
    session; absent that, the result is reported as not exercised.
    """
    if os.environ.get("PARROT_TOOL_OPT_HOST_SMOKE") != "1":
        return None
    binary = shutil.which("codex")
    if not binary:
        return {"note": "codex binary not installed"}

    (root / "big.py").write_text("".join(f"line{i}\n" for i in range(1, 401)))
    try:
        result = subprocess.run(
            [binary, "exec", "--sandbox", "read-only", "-C", str(root), "cat big.py"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exercised_end_to_end": False, "note": f"codex exec failed to start: {exc}"}

    transcript = (result.stdout or "") + (result.stderr or "")
    denied = "source_read" in transcript or "bounded reader" in transcript
    return {
        "exercised_end_to_end": denied,
        "note": "denial observed in transcript" if denied else "hooks not honoured by this codex configuration",
        "exit_code": result.returncode,
    }


def test_coverage_matrix_is_published_as_evidence():
    """The honest coverage table ships alongside the smoke report."""
    from parrot_tools.tool_optimizations.hooks import coverage_matrix

    matrix = coverage_matrix()
    record_json("TASK-3091-guard-coverage.json", {"rows": matrix})

    covered = [row for row in matrix if row["covered"]]
    gaps = [row for row in matrix if not row["covered"]]
    assert covered and gaps, "the matrix must state both what is and is not intercepted"
