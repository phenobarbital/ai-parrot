"""Tests for the pre-auto-mode SDD shell-prefix runtime."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import shlex

import pytest

from parrot.sdd.scripts import shell_prefix


def _write_policy(tmp_path: Path, **overrides: object) -> tuple[Path, dict[str, object]]:
    """Write a secure test policy and return it with its JSON document."""
    document: dict[str, object] = {
        "schema_version": 1,
        "mode": "legacy",
        "worktree": str(tmp_path),
        "hook_commands": ["echo hook-ran >&2; exit 0"],
        "mcp_argv": [["/bin/sleep", "2"]],
        "rtk": False,
    }
    document.update(overrides)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path, document


def _capture_exec(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Capture shell-prefix exec calls without replacing this test process."""
    captured: dict[str, object] = {}

    def capture(executable: str, argv: list[str], environment: dict[str, str]) -> None:
        captured.update(executable=executable, argv=argv, environment=environment)

    monkeypatch.setattr(shell_prefix.os, "execvpe", capture)
    return captured


def test_hook_and_mcp_commands_pass_through_token_is_hook_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact hook strings and MCP argv commands pass through; only the hook receives the policy token."""
    policy_path, _document = _write_policy(tmp_path)
    monkeypatch.setenv(shell_prefix.POLICY_ENV, str(policy_path))
    expected_token = hashlib.sha256(policy_path.read_bytes()).hexdigest()

    monkeypatch.setenv(shell_prefix.TOKEN_ENV, "inherited")
    for command, token in (("echo hook-ran >&2; exit 0", expected_token), ("/bin/sleep 2", None)):
        captured = _capture_exec(monkeypatch)
        shell_prefix.main([command])
        assert captured["argv"] == ["/bin/bash", "-c", command]
        assert captured["environment"].get(shell_prefix.TOKEN_ENV) == token


def test_bash_preamble_is_wrapped_in_legacy_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Claude Bash preamble stays unchanged inside the legacy wrapper."""
    policy_path, _document = _write_policy(tmp_path)
    monkeypatch.setenv(shell_prefix.POLICY_ENV, str(policy_path))
    monkeypatch.setenv(shell_prefix.TOKEN_ENV, "stale-token")
    preamble = "source /tmp/snapshot && eval 'pwd' < /dev/null && pwd -P >| /tmp/cwd"
    wrapped = ["bwrap", "--", "/bin/bash", "-c", preamble]
    monkeypatch.setattr(shell_prefix, "protected_argv", lambda cwd, argv: wrapped)
    captured = _capture_exec(monkeypatch)

    shell_prefix.main([preamble])

    assert captured["argv"] == wrapped
    assert shell_prefix.TOKEN_ENV not in captured["environment"]


def test_bash_preamble_runs_unchanged_in_native_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native mode leaves a Bash preamble directly executable without a marker."""
    policy_path, _document = _write_policy(tmp_path, mode="native")
    monkeypatch.setenv(shell_prefix.POLICY_ENV, str(policy_path))
    monkeypatch.setenv(shell_prefix.TOKEN_ENV, "stale-token")
    preamble = "source /tmp/snapshot && eval 'pwd' < /dev/null && pwd -P >| /tmp/cwd"
    captured = _capture_exec(monkeypatch)

    shell_prefix.main([preamble])

    assert captured["argv"] == ["/bin/bash", "-c", preamble]
    assert shell_prefix.TOKEN_ENV not in captured["environment"]


def test_preamble_never_matches_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An allowlisted hook embedded in a preamble is still sandboxed."""
    policy_path, _document = _write_policy(tmp_path)
    monkeypatch.setenv(shell_prefix.POLICY_ENV, str(policy_path))
    preamble = "source /tmp/snapshot && echo hook-ran >&2; exit 0"
    wrapped = ["bwrap", "--", "/bin/bash", "-c", preamble]
    monkeypatch.setattr(shell_prefix, "protected_argv", lambda cwd, argv: wrapped)
    captured = _capture_exec(monkeypatch)

    shell_prefix.main([preamble])

    assert captured["argv"] == wrapped
    assert shell_prefix.TOKEN_ENV not in captured["environment"]


@pytest.mark.parametrize(
    "command",
    [
        "printf '%s' \"dollar:$HOME\"",
        "printf '%s\\n' 'it'\"'\"'s done' && printf second",
        "printf '%s' 'first line\nsecond line'",
    ],
)
def test_rtk_payload_round_trip(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rewritten eval word remains a shell-equivalent single command argument."""
    preamble = f"true && eval {shlex.quote(command)} < /dev/null && true"
    monkeypatch.setattr(shell_prefix, "rtk_rewrite", lambda value: f":; {value}")

    rewritten = shell_prefix.rtk_payload(preamble)

    expected = subprocess.run(["/bin/bash", "-c", preamble], capture_output=True, text=True, check=False)
    actual = subprocess.run(["/bin/bash", "-c", rewritten], capture_output=True, text=True, check=False)
    assert actual.returncode == expected.returncode
    assert actual.stdout == expected.stdout
    assert actual.stderr == expected.stderr


def test_rtk_payload_leaves_unrecognised_input_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed and ambiguous preambles do not invoke RTK or change bytes."""
    monkeypatch.setattr(shell_prefix, "rtk_rewrite", lambda value: pytest.fail(f"unexpected RTK call: {value}"))
    inputs = (
        "true && eval 'one' < /dev/null && eval 'two' < /dev/null",
        "true && eval 'missing stdin redirect' && true",
        "true && eval 'unterminated < /dev/null",
    )
    for value in inputs:
        assert shell_prefix.rtk_payload(value) == value


def test_rtk_payload_respects_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The global RTK switch leaves a recognised payload byte-identical."""
    value = "true && eval 'git status --short' < /dev/null && true"
    monkeypatch.setenv("PARROT_SANDBOX_RTK", "0")
    assert shell_prefix.rtk_payload(value) == value


def test_passthrough_is_never_rtk_rewritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allowlisted hook commands never enter the payload optimiser."""
    policy_path, _document = _write_policy(tmp_path, rtk=True)
    monkeypatch.setenv(shell_prefix.POLICY_ENV, str(policy_path))
    monkeypatch.setattr(shell_prefix, "rtk_payload", lambda value: pytest.fail(f"unexpected payload: {value}"))
    captured = _capture_exec(monkeypatch)

    shell_prefix.main(["echo hook-ran >&2; exit 0"])

    assert captured["argv"] == ["/bin/bash", "-c", "echo hook-ran >&2; exit 0"]


@pytest.mark.parametrize(
    ("arguments", "policy", "mode", "bwrap_missing"),
    [
        ([], None, 0o600, False),
        (["one", "two"], None, 0o600, False),
        (["echo safe"], None, 0o600, False),
        (["echo safe"], {"schema_version": 2}, 0o600, False),
        (["echo safe"], {}, 0o620, False),
        (["echo safe"], {}, 0o600, True),
    ],
)
def test_errors_exit_2_and_exec_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    policy: dict[str, object] | None,
    mode: int,
    bwrap_missing: bool,
) -> None:
    """Malformed invocations and policy files block execution with exit 2."""
    policy_path, document = _write_policy(tmp_path)
    if policy is not None:
        document.update(policy)
        policy_path.write_text(json.dumps(document), encoding="utf-8")
        policy_path.chmod(mode)
        monkeypatch.setenv(shell_prefix.POLICY_ENV, str(policy_path))
    if bwrap_missing:
        monkeypatch.setattr(
            shell_prefix, "protected_argv", lambda cwd, argv: (_ for _ in ()).throw(RuntimeError("bwrap missing"))
        )
    captured = _capture_exec(monkeypatch)

    with pytest.raises(SystemExit) as raised:
        shell_prefix.main(arguments)

    assert raised.value.code == 2
    assert captured == {}
    assert "sdd shell prefix:" in capsys.readouterr().err


def test_script_mode_does_not_import_parrot() -> None:
    """Direct script-mode import needs only stdlib sibling modules."""
    scripts = Path(shell_prefix.__file__).parent
    result = subprocess.run(
        [
            sys.executable,
            "-E",
            "-s",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import shell_prefix; "
            "assert not any(name == 'parrot' or name.startswith('parrot.') for name in sys.modules)",
            str(scripts),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
