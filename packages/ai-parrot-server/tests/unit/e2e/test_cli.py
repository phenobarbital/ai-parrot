"""Focused CLI contract tests for ``parrot.e2e.cli`` (TASK-3534, M3).

Every collaborator (`run_plan`/`verify_evidence`/`E2ESupervisor`/
`parrot.e2e.state`/`parrot.e2e.watchdog`) is already covered by its own
task's unit suite; this file only asserts this task's own scope: Click
wiring/registration, JSON-on-stdout framing, exit-code mapping, owner
scoping and the ``up`` daemon's ticket-file handoff. Fakes replace
collaborators throughout — only the process-boundary polling logic in
``_spawn_detached_target`` gets a real (fake-``asyncio.create_subprocess_exec``)
child-process seam, per this task's own Test Specification.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from click.testing import CliRunner

from parrot.e2e import cli as cli_module
from parrot.e2e.cli import e2e
from parrot.e2e.errors import (
    EXIT_BLOCKED,
    EXIT_CONFIG,
    EXIT_EVIDENCE,
    EXIT_FAILURE,
    EXIT_SIGINT,
    EXIT_SIGTERM,
    EXIT_SUCCESS,
    E2EConfigError,
    E2EEvidenceError,
    E2ETargetError,
)
from parrot.e2e.models import ProcessIdentity, RunState, TargetConfig


def _sample_run_state(
    *,
    run_id: str = "target-a-abc123def456",
    status: str = "ready",
    cleanup_complete: bool = False,
    owner_id: str = "tester",
    feature_id: str = "feat-x",
    log_path: str = "/tmp/e2e-cli-test.log",
    worktree: Optional[Path] = None,
) -> RunState:
    """Build one real, schema-valid :class:`RunState` for CLI-layer tests."""
    now = datetime.now(timezone.utc)
    identity = ProcessIdentity(pid=1, pgid=1, create_time=now, boot_id="boot-1", owned=True)
    return RunState(
        feature_id=feature_id,
        run_id=run_id,
        worktree=str((worktree or Path("/tmp")).resolve()),
        owner_id=owner_id,
        controller_identity=identity,
        supervisor_identity=identity,
        process_identity=identity,
        target_id="mcp-toolkit",
        status=status,
        control_socket="/tmp/e2e-cli-test.sock",
        started_at=now,
        deadline=now,
        log_path=log_path,
        cleanup_complete=cleanup_complete,
    )


class _FakeResult:
    """A minimal duck-typed collaborator result (verdict/verification result)."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return dict(self.__dict__)


class _FakeSupervisor:
    """A minimal ``E2ESupervisor`` test double recording its own construction/calls."""

    instances: list["_FakeSupervisor"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.stop_calls: list[str] = []
        type(self).instances.append(self)

    async def stop(self, run_id: str) -> RunState:
        self.stop_calls.append(run_id)
        return _sample_run_state(
            run_id=run_id, status="stopped", cleanup_complete=True, owner_id=self.kwargs["owner_id"]
        )


# ---------------------------------------------------------------------------
# LazyGroup registration (core CLI)
# ---------------------------------------------------------------------------


def test_lazygroup_resolves_e2e() -> None:
    """Core's LazyGroup can resolve 'e2e' from _lazy_commands, with an install hint."""
    from unittest.mock import MagicMock

    from parrot.cli import cli

    assert cli._lazy_commands.get("e2e") == "parrot.e2e.cli"
    assert "ai-parrot-server" in cli._lazy_extras.get("e2e", "")
    cmd = cli.get_command(MagicMock(), "e2e")
    assert cmd is not None
    assert cmd.name == "e2e"


def test_e2e_group_lists_public_subcommands_and_hides_daemon() -> None:
    """The public run/verify/up/status/logs/down surface is documented; the daemon is not."""
    result = CliRunner().invoke(e2e, ["--help"])
    assert result.exit_code == 0
    for name in ("run", "verify", "up", "status", "logs", "down"):
        assert name in result.output
    assert "_run-daemon" not in result.output


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_success_prints_verdict_json_and_uses_verdict_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clean run echoes the verdict JSON and exits with its own exit_code."""
    captured: dict[str, Any] = {}

    async def _fake_run_plan(plan_path: Path, *, worktree: Path, owner_id: str) -> _FakeResult:
        captured.update(plan_path=plan_path, worktree=worktree, owner_id=owner_id)
        return _FakeResult(status="PASS", exit_code=EXIT_SUCCESS)

    monkeypatch.setattr(cli_module, "run_plan", _fake_run_plan)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    plan_path = tmp_path / "e2e-plan.md"
    result = CliRunner().invoke(e2e, ["run", "--plan", str(plan_path), "--owner-id", "tester"])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload == {"status": "PASS", "exit_code": EXIT_SUCCESS}
    assert captured["owner_id"] == "tester"
    assert captured["worktree"] == tmp_path


def test_run_propagates_typed_error_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An invalid plan fails before any target starts, mapped to exit code 2."""

    async def _fake_run_plan_raises(*_args: Any, **_kwargs: Any) -> Any:
        raise E2EConfigError("bad plan", reason_code="plan_invalid")

    monkeypatch.setattr(cli_module, "run_plan", _fake_run_plan_raises)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["run", "--plan", str(tmp_path / "e2e-plan.md")])

    assert result.exit_code == EXIT_CONFIG
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["status"] == "ERROR"
    assert payload["reason_code"] == "plan_invalid"


def test_run_rejects_unsafe_owner_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unsafe --owner-id is rejected before any run_plan collaborator call."""
    called = False

    async def _fake_run_plan(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal called
        called = True
        return _FakeResult(status="PASS", exit_code=EXIT_SUCCESS)

    monkeypatch.setattr(cli_module, "run_plan", _fake_run_plan)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["run", "--plan", str(tmp_path / "e2e-plan.md"), "--owner-id", "../bad"])

    assert result.exit_code == EXIT_CONFIG
    assert called is False


# ---------------------------------------------------------------------------
# _signal_exit_code (pure function backing run's interrupt handling)
# ---------------------------------------------------------------------------


def test_signal_exit_code_maps_sigint_and_sigterm() -> None:
    """SIGINT/SIGTERM map to spec §2's exact 130/143 exit codes, never fabricated as success."""
    import signal

    assert cli_module._signal_exit_code([signal.SIGINT], fallback=0) == EXIT_SIGINT
    assert cli_module._signal_exit_code([signal.SIGTERM], fallback=0) == EXIT_SIGTERM
    assert cli_module._signal_exit_code([], fallback=5) == 5


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [("PASS", EXIT_SUCCESS), ("FAIL", EXIT_FAILURE), ("BLOCKED", EXIT_BLOCKED), ("MISSING", EXIT_EVIDENCE)],
)
def test_verify_maps_status_to_documented_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str, expected_exit: int
) -> None:
    """Every VerificationResult.status maps to spec §2's exact exit code."""

    async def _fake_verify(*_args: Any, **_kwargs: Any) -> _FakeResult:
        return _FakeResult(status=status, gate_satisfied=status == "PASS", reason_codes=[])

    monkeypatch.setattr(cli_module, "verify_evidence", _fake_verify)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["verify", "--plan", str(tmp_path / "e2e-plan.md")])

    assert result.exit_code == expected_exit
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["status"] == status


def test_verify_stale_evidence_fails_closed_at_exit_4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tampered/stale evidence raises E2EEvidenceError, mapped to exit code 4 -- never PASS."""

    async def _fake_verify_raises(*_args: Any, **_kwargs: Any) -> Any:
        raise E2EEvidenceError("stale evidence", reason_code="source_identity_stale")

    monkeypatch.setattr(cli_module, "verify_evidence", _fake_verify_raises)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["verify", "--plan", str(tmp_path / "e2e-plan.md")])

    assert result.exit_code == EXIT_EVIDENCE
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["reason_code"] == "source_identity_stale"


# ---------------------------------------------------------------------------
# _load_target_config (fixed registry names only, never an arbitrary command)
# ---------------------------------------------------------------------------


def test_load_target_config_rejects_unknown_kind() -> None:
    """Only the six fixed registry names are accepted -- never an arbitrary target."""
    with pytest.raises(E2EConfigError) as excinfo:
        cli_module._load_target_config("arbitrary-shell-target", None)
    assert excinfo.value.reason_code == "unknown_target_kind"


def test_load_target_config_merges_overlay_file(tmp_path: Path) -> None:
    """A config overlay only ever supplies declared TargetConfig fields."""
    config_path = tmp_path / "target.yaml"
    config_path.write_text("profile: full\nstartup_timeout_s: 12\noptions:\n  base_path: /wm\n", encoding="utf-8")

    config = cli_module._load_target_config("mcp-toolkit", config_path)

    assert config.kind == "mcp-toolkit"
    assert config.profile == "full"
    assert config.startup_timeout_s == 12
    assert config.options == {"base_path": "/wm"}


def test_load_target_config_rejects_disagreeing_kind(tmp_path: Path) -> None:
    """An overlay file's own declared kind must agree with the requested target."""
    config_path = tmp_path / "target.yaml"
    config_path.write_text("kind: botmanager\n", encoding="utf-8")

    with pytest.raises(E2EConfigError) as excinfo:
        cli_module._load_target_config("mcp-toolkit", config_path)
    assert excinfo.value.reason_code == "target_kind_mismatch"


def test_load_target_config_rejects_non_mapping_overlay(tmp_path: Path) -> None:
    """A YAML list (or scalar) overlay is not a valid TargetConfig payload."""
    config_path = tmp_path / "target.yaml"
    config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(E2EConfigError) as excinfo:
        cli_module._load_target_config("mcp-toolkit", config_path)
    assert excinfo.value.reason_code == "target_config_invalid"


def test_load_target_config_rejects_unreadable_overlay(tmp_path: Path) -> None:
    """A missing overlay file fails closed with a clear reason code."""
    with pytest.raises(E2EConfigError) as excinfo:
        cli_module._load_target_config("mcp-toolkit", tmp_path / "does-not-exist.yaml")
    assert excinfo.value.reason_code == "target_config_unreadable"


# ---------------------------------------------------------------------------
# up (+ its detached daemon's ticket handoff)
# ---------------------------------------------------------------------------


def test_up_rejects_unknown_target_before_any_spawn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unknown target is rejected before the detached daemon is ever spawned."""
    spawned = False

    async def _fake_spawn(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal spawned
        spawned = True
        return _sample_run_state()

    monkeypatch.setattr(cli_module, "_spawn_detached_target", _fake_spawn)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["up", "arbitrary-shell-target"])

    assert result.exit_code == EXIT_CONFIG
    assert spawned is False


def test_up_success_prints_ready_state_and_exits_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A ready detached target is echoed and reported as success."""
    ready_state = _sample_run_state(status="ready", worktree=tmp_path)

    async def _fake_spawn(*_args: Any, **_kwargs: Any) -> RunState:
        return ready_state

    monkeypatch.setattr(cli_module, "_spawn_detached_target", _fake_spawn)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["up", "mcp-toolkit", "--owner-id", "tester"])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["status"] == "ready"
    assert payload["run_id"] == ready_state.run_id


def test_up_failed_target_never_reports_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A target that never became ready is reported as failure, never exit 0."""
    failed_state = _sample_run_state(status="failed", worktree=tmp_path)

    async def _fake_spawn(*_args: Any, **_kwargs: Any) -> RunState:
        return failed_state

    monkeypatch.setattr(cli_module, "_spawn_detached_target", _fake_spawn)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["up", "mcp-toolkit"])

    assert result.exit_code == EXIT_FAILURE


def test_up_propagates_typed_readiness_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A daemon readiness timeout is a typed target failure, not a silent hang."""

    async def _fake_spawn_raises(*_args: Any, **_kwargs: Any) -> Any:
        raise E2ETargetError("no ticket", reason_code="up_readiness_timeout")

    monkeypatch.setattr(cli_module, "_spawn_detached_target", _fake_spawn_raises)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["up", "mcp-toolkit"])

    assert result.exit_code == EXIT_FAILURE
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["reason_code"] == "up_readiness_timeout"


@pytest.mark.asyncio
async def test_spawn_detached_target_returns_state_from_success_ticket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Once the daemon writes its readiness ticket, the real minted RunState is returned."""
    real_state = _sample_run_state(run_id="mcp-toolkit-abc123def456", status="ready", worktree=tmp_path)

    class _FakeProcess:
        returncode: Optional[int] = None

    async def _fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> _FakeProcess:
        ticket = cli_module._ticket_path(tmp_path, "ticket-1")
        ticket.parent.mkdir(parents=True, exist_ok=True)
        ticket.write_text(json.dumps(real_state.model_dump(mode="json")), encoding="utf-8")
        return _FakeProcess()

    monkeypatch.setattr(cli_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=1)
    result = await cli_module._spawn_detached_target(
        "mcp-toolkit", config, invocation_id="ticket-1", owner_id="tester", worktree=tmp_path, feature_id="feat-x"
    )

    assert result.run_id == real_state.run_id
    assert result.status == "ready"


@pytest.mark.asyncio
async def test_spawn_detached_target_raises_on_daemon_exit_before_ticket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A daemon that exits before writing any ticket is a target failure, never a silent success."""

    class _FakeExitedProcess:
        returncode = 9

    async def _fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> _FakeExitedProcess:
        return _FakeExitedProcess()

    monkeypatch.setattr(cli_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=1)
    with pytest.raises(E2ETargetError) as excinfo:
        await cli_module._spawn_detached_target(
            "mcp-toolkit", config, invocation_id="ticket-2", owner_id="tester", worktree=tmp_path, feature_id="feat-x"
        )
    assert excinfo.value.reason_code == "daemon_exited_early"


@pytest.mark.asyncio
async def test_spawn_detached_target_times_out_without_a_ticket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A daemon that never writes a ticket within the bounded deadline fails, not hangs forever."""

    class _FakeAliveProcess:
        returncode = None

    async def _fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> _FakeAliveProcess:
        return _FakeAliveProcess()

    monkeypatch.setattr(cli_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(cli_module, "_UP_DAEMON_SPAWN_GRACE_S", 0.05)
    monkeypatch.setattr(cli_module, "_DEFAULT_UP_READY_POLL_S", 0.01)

    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=0.05)
    with pytest.raises(E2ETargetError) as excinfo:
        await cli_module._spawn_detached_target(
            "mcp-toolkit", config, invocation_id="ticket-3", owner_id="tester", worktree=tmp_path, feature_id="feat-x"
        )
    assert excinfo.value.reason_code == "up_readiness_timeout"


@pytest.mark.asyncio
async def test_run_daemon_writes_error_ticket_on_start_failure(tmp_path: Path) -> None:
    """A start() failure is captured as an error ticket, never left for `up` to hang polling."""

    class _FailingSupervisor:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def start(self, *_args: Any, **_kwargs: Any) -> RunState:
            raise E2ETargetError("boom", reason_code="target_readiness_timeout")

    import parrot.e2e.cli as real_cli_module

    original_supervisor = real_cli_module.E2ESupervisor
    real_cli_module.E2ESupervisor = _FailingSupervisor
    try:
        ticket_path = tmp_path / "ticket.json"
        exit_code = await real_cli_module._run_daemon(
            "mcp-toolkit",
            TargetConfig(kind="mcp-toolkit"),
            owner_id="tester",
            worktree=tmp_path,
            feature_id="feat-x",
            ticket_path=ticket_path,
        )
    finally:
        real_cli_module.E2ESupervisor = original_supervisor

    assert exit_code == EXIT_FAILURE
    payload = json.loads(ticket_path.read_text(encoding="utf-8"))
    assert payload["reason_code"] == "target_readiness_timeout"


@pytest.mark.asyncio
async def test_run_daemon_self_exits_once_externally_cleaned_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run stopped by a *separate* `down` invocation makes the daemon observe cleanup and exit."""
    started_state = _sample_run_state(status="ready", worktree=tmp_path)
    stopped_state = _sample_run_state(status="stopped", cleanup_complete=True, worktree=tmp_path)

    class _FakeSupervisor:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def start(self, *_args: Any, **_kwargs: Any) -> RunState:
            return started_state

    monkeypatch.setattr(cli_module, "E2ESupervisor", _FakeSupervisor)
    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda *_a, **_k: stopped_state)

    ticket_path = tmp_path / "ticket.json"
    exit_code = await cli_module._run_daemon(
        "mcp-toolkit",
        TargetConfig(kind="mcp-toolkit"),
        owner_id="tester",
        worktree=tmp_path,
        feature_id="feat-x",
        ticket_path=ticket_path,
    )

    assert exit_code == EXIT_SUCCESS
    payload = json.loads(ticket_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"  # the ticket reflects the started state, not the terminal one


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_single_run_prints_its_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`status RUN_ID` prints exactly that run's persisted state."""
    state = _sample_run_state(run_id="mcp-toolkit-abc123def456", worktree=tmp_path)
    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda run_id, **_k: state)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["status", state.run_id])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["run_id"] == state.run_id


def test_status_missing_run_fails_with_config_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A RUN_ID with no persisted state is a clear, typed failure, not a crash."""

    def _raise_missing(run_id: str, **_kwargs: Any) -> RunState:
        raise E2EConfigError(f"no persisted run state for run_id={run_id!r}", reason_code="state_missing")

    monkeypatch.setattr(cli_module.e2e_state, "read_state", _raise_missing)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["status", "no-such-run"])

    assert result.exit_code == EXIT_CONFIG


def test_status_without_run_id_lists_every_known_run_and_skips_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`status` with no RUN_ID lists every run in this worktree, skipping a corrupt one."""
    good_state = _sample_run_state(run_id="mcp-toolkit-abc123def456", worktree=tmp_path)

    def _fake_read_state(run_id: str, **_kwargs: Any) -> RunState:
        if run_id == "corrupt-run":
            raise E2EConfigError("bad state", reason_code="state_invalid")
        return good_state

    monkeypatch.setattr(cli_module.e2e_state, "list_run_ids", lambda **_k: [good_state.run_id, "corrupt-run"])
    monkeypatch.setattr(cli_module.e2e_state, "read_state", _fake_read_state)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["status"])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["run_id"] == good_state.run_id


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


def test_logs_tail_prints_only_the_last_n_lines(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`--tail N` bounds the printed log to its last N lines."""
    log_path = tmp_path / "target.log"
    log_path.write_text("\n".join(f"line-{i}" for i in range(10)) + "\n", encoding="utf-8")
    state = _sample_run_state(log_path=str(log_path), worktree=tmp_path)

    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda *_a, **_k: state)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["logs", state.run_id, "--tail", "3"])

    assert result.exit_code == EXIT_SUCCESS
    assert result.output.splitlines() == ["line-7", "line-8", "line-9"]


def test_logs_missing_log_file_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A run whose log file vanished from disk is a clear, typed failure."""
    state = _sample_run_state(log_path=str(tmp_path / "does-not-exist.log"), worktree=tmp_path)
    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda *_a, **_k: state)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["logs", state.run_id])

    assert result.exit_code == EXIT_CONFIG
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["reason_code"] == "log_unavailable"


# ---------------------------------------------------------------------------
# down
# ---------------------------------------------------------------------------


def test_down_requires_exactly_one_selector(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Neither RUN_ID, --all nor --stale (or more than one) is rejected before any teardown."""
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["down"])
    assert result.exit_code == EXIT_CONFIG

    result = CliRunner().invoke(e2e, ["down", "some-run", "--all"])
    assert result.exit_code == EXIT_CONFIG


def test_down_run_id_stops_owned_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`down RUN_ID` stops exactly the owner's own run via the fixed E2ESupervisor.stop() contract."""
    _FakeSupervisor.instances.clear()
    state = _sample_run_state(owner_id="tester", worktree=tmp_path)
    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda *_a, **_k: state)
    monkeypatch.setattr(cli_module, "E2ESupervisor", _FakeSupervisor)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["down", state.run_id, "--owner-id", "tester"])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["runs"][0]["cleanup_complete"] is True
    assert _FakeSupervisor.instances[0].stop_calls == [state.run_id]


def test_down_refuses_cross_owner_teardown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`down RUN_ID` never signals a run owned by a different identity (spec §2 owner scoping)."""
    _FakeSupervisor.instances.clear()
    state = _sample_run_state(owner_id="someone-else", worktree=tmp_path)
    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda *_a, **_k: state)
    monkeypatch.setattr(cli_module, "E2ESupervisor", _FakeSupervisor)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["down", state.run_id, "--owner-id", "tester"])

    assert result.exit_code == EXIT_CONFIG
    assert _FakeSupervisor.instances == []


def test_down_all_stops_only_owned_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`down --all` scopes strictly to runs owned by the (defaulted) invoking identity."""
    _FakeSupervisor.instances.clear()
    mine = _sample_run_state(run_id="mcp-toolkit-mine000001", owner_id="tester", worktree=tmp_path)
    theirs = _sample_run_state(run_id="mcp-toolkit-theirs0001", owner_id="someone-else", worktree=tmp_path)

    def _fake_read_state(run_id: str, **_kwargs: Any) -> RunState:
        return mine if run_id == mine.run_id else theirs

    monkeypatch.setattr(cli_module.e2e_state, "list_run_ids", lambda **_k: [mine.run_id, theirs.run_id])
    monkeypatch.setattr(cli_module.e2e_state, "read_state", _fake_read_state)
    monkeypatch.setattr(cli_module, "E2ESupervisor", _FakeSupervisor)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["down", "--all", "--owner-id", "tester"])

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert [entry["run_id"] for entry in payload["runs"]] == [mine.run_id]
    assert _FakeSupervisor.instances[0].stop_calls == [mine.run_id]


def test_down_reports_failure_when_any_cleanup_incomplete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unresolved cleanup is never silently reported as an overall success."""

    class _FlakySupervisor(_FakeSupervisor):
        async def stop(self, run_id: str) -> RunState:
            self.stop_calls.append(run_id)
            return _sample_run_state(run_id=run_id, status="failed", cleanup_complete=False, owner_id="tester")

    state = _sample_run_state(owner_id="tester", worktree=tmp_path)
    monkeypatch.setattr(cli_module.e2e_state, "read_state", lambda *_a, **_k: state)
    monkeypatch.setattr(cli_module, "E2ESupervisor", _FlakySupervisor)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["down", state.run_id, "--owner-id", "tester"])

    assert result.exit_code == EXIT_FAILURE


def test_down_stale_reconciles_only_stale_owned_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`down --stale` is spec §2's own documented next-invocation recovery path."""
    fresh = _sample_run_state(run_id="mcp-toolkit-fresh00001", owner_id="tester", worktree=tmp_path)
    stale = _sample_run_state(run_id="mcp-toolkit-stale00001", owner_id="tester", worktree=tmp_path)
    reconciled_calls: list[str] = []

    async def _fake_reconcile(run_id: str, *, worktree: Path) -> RunState:
        reconciled_calls.append(run_id)
        return _sample_run_state(run_id=run_id, status="stopped", cleanup_complete=True, owner_id="tester")

    def _fake_read_state(run_id: str, **_kwargs: Any) -> RunState:
        return fresh if run_id == fresh.run_id else stale

    def _fake_is_stale(state: RunState, **_kwargs: Any) -> bool:
        return state.run_id == stale.run_id

    monkeypatch.setattr(cli_module.e2e_state, "list_run_ids", lambda **_k: [fresh.run_id, stale.run_id])
    monkeypatch.setattr(cli_module.e2e_state, "read_state", _fake_read_state)
    monkeypatch.setattr(cli_module.e2e_state, "is_stale", _fake_is_stale)
    monkeypatch.setattr(cli_module.e2e_watchdog, "reconcile_stale_run", _fake_reconcile)
    monkeypatch.setattr(cli_module, "_resolve_worktree", lambda *_a, **_k: tmp_path)

    result = CliRunner().invoke(e2e, ["down", "--stale", "--owner-id", "tester"])

    assert result.exit_code == EXIT_SUCCESS
    assert reconciled_calls == [stale.run_id]


# ---------------------------------------------------------------------------
# owner-id / worktree resolution helpers
# ---------------------------------------------------------------------------


def test_default_owner_id_prefers_env_var_and_sanitizes(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit owner override wins, and unsafe characters are sanitized, never rejected outright."""
    monkeypatch.setenv("PARROT_E2E_OWNER_ID", "weird user!!name")
    owner = cli_module._default_owner_id()
    assert owner
    assert cli_module._SAFE_ID_RE.match(owner)


def test_default_owner_id_falls_back_when_nothing_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty environment still yields a safe, nonempty default identity."""
    monkeypatch.delenv("PARROT_E2E_OWNER_ID", raising=False)
    monkeypatch.setattr(cli_module.getpass, "getuser", lambda: (_ for _ in ()).throw(OSError("no user")))
    owner = cli_module._default_owner_id()
    assert owner == "cli"


def test_resolve_worktree_finds_nearest_git_ancestor(tmp_path: Path) -> None:
    """Worktree discovery walks up to the nearest `.git`, never trusting an arbitrary path."""
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "packages" / "ai-parrot-server" / "src"
    nested.mkdir(parents=True)

    assert cli_module._resolve_worktree(nested) == tmp_path.resolve()


def test_resolve_worktree_falls_back_to_start_without_a_git_ancestor(tmp_path: Path) -> None:
    """With no `.git` anywhere in the ancestry, the starting directory itself is used."""
    isolated = tmp_path / "no-git-here"
    isolated.mkdir()

    assert cli_module._resolve_worktree(isolated) == isolated.resolve()
