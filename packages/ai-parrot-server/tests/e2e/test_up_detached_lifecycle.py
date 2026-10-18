"""Real-subprocess launcher-exit survival scenarios for ``parrot e2e up`` (FEAT-581 AC5).

The unit tests for ``up`` monkeypatch subprocess creation and fake the
supervisor, so they cannot prove that the detached daemon and its target
actually outlive the launcher. These scenarios spawn the real CLI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil
import pytest

from parrot.e2e import state as e2e_state
from parrot.e2e.cli import _ticket_path
from parrot.e2e.models import ProcessIdentity, RunState

_CLI = [sys.executable, "-m", "parrot.e2e.cli"]
_UP_TIMEOUT_S = 90
_TICKET_DEADLINE_S = 60
_DEATH_DEADLINE_S = 30
_POLL_S = 0.2


def _is_alive(identity: ProcessIdentity) -> bool:
    """Return True if ``identity`` is a live process with a matching create_time (PID-reuse safe)."""
    try:
        proc = psutil.Process(identity.pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        observed = datetime.fromtimestamp(proc.create_time(), tz=timezone.utc)
    except psutil.NoSuchProcess:
        return False
    return abs((observed - identity.create_time).total_seconds()) < 1.0


async def _spawn_up(worktree: Path, owner_id: str, ticket_id: str, *, capture: bool) -> asyncio.subprocess.Process:
    """Spawn the real ``up mcp-stdio`` launcher subprocess."""
    return await asyncio.create_subprocess_exec(
        *_CLI,
        "up",
        "mcp-stdio",
        "--owner-id",
        owner_id,
        "--run-id",
        ticket_id,
        cwd=str(worktree),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
    )


def _killpg(identity: ProcessIdentity) -> None:
    """SIGKILL an identity's process group, ignoring already-dead groups."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(identity.pgid, signal.SIGKILL)


async def _teardown(worktree: Path, owner_id: str, state: RunState | None) -> None:
    """Stop a run via the real ``down`` CLI; fall back to killpg + state deletion.

    Asserts ``cleanup_complete`` on the clean path.
    """
    if state is None:
        return
    clean = False
    try:
        down = await asyncio.create_subprocess_exec(
            *_CLI,
            "down",
            state.run_id,
            "--owner-id",
            owner_id,
            cwd=str(worktree),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(down.wait(), timeout=_DEATH_DEADLINE_S)
        deadline = time.monotonic() + _DEATH_DEADLINE_S
        while _is_alive(state.supervisor_identity) and time.monotonic() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(_POLL_S)
        final = e2e_state.read_state(state.run_id, worktree=worktree)
        clean = (
            final is not None
            and final.cleanup_complete is True
            and not _is_alive(state.supervisor_identity)
            and not _is_alive(state.process_identity)
        )
    finally:
        if not clean:
            _killpg(state.process_identity)
            _killpg(state.supervisor_identity)
        with contextlib.suppress(Exception):
            e2e_state.delete_state(state.run_id, worktree=worktree)
    assert clean, "down did not cleanly stop the daemon and target (killpg fallback was used)"


@pytest.mark.e2e
async def test_up_daemon_and_target_survive_launcher_exit(e2e_worktree: Path) -> None:
    """The daemon and target stay alive after the launcher exits 0 with a ready RunState."""
    owner_id = f"pytest-up-{uuid.uuid4().hex}"
    ticket_id = f"up-{uuid.uuid4().hex[:12]}"
    state: RunState | None = None
    launcher = await _spawn_up(e2e_worktree, owner_id, ticket_id, capture=True)
    try:
        try:
            stdout, stderr = await asyncio.wait_for(launcher.communicate(), timeout=_UP_TIMEOUT_S)
        except asyncio.TimeoutError:
            launcher.kill()
            await launcher.wait()
            raise
        assert launcher.returncode == 0, f"launcher failed: {stderr.decode(errors='replace')}"
        last_line = stdout.decode().strip().splitlines()[-1]
        state = RunState.model_validate(json.loads(last_line))
        assert state.status == "ready"
        # The launcher has exited by construction: verify survival by identity.
        assert _is_alive(state.supervisor_identity), "daemon died with the launcher"
        assert _is_alive(state.process_identity), "target died with the launcher"
    finally:
        if launcher.returncode is None:
            launcher.kill()
            await launcher.wait()
        await _teardown(e2e_worktree, owner_id, state)


@pytest.mark.e2e
async def test_up_daemon_survives_launcher_sigkill_mid_wait(e2e_worktree: Path) -> None:
    """SIGKILLing the launcher while it polls for the ticket does not kill the daemon."""
    owner_id = f"pytest-up-{uuid.uuid4().hex}"
    ticket_id = f"up-{uuid.uuid4().hex[:12]}"
    ticket = _ticket_path(e2e_worktree, ticket_id)
    with contextlib.suppress(OSError):
        ticket.unlink()
    state: RunState | None = None
    launcher = await _spawn_up(e2e_worktree, owner_id, ticket_id, capture=False)
    try:
        await asyncio.sleep(0.5)
        launcher.kill()
        await launcher.wait()

        deadline = time.monotonic() + _TICKET_DEADLINE_S
        while not ticket.is_file() and time.monotonic() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(_POLL_S)
        log = e2e_worktree / "artifacts" / "logs" / "e2e" / "_up_daemons" / f"{ticket_id}.log"
        assert ticket.is_file(), f"daemon never wrote its ticket after launcher SIGKILL (log: {log})"
        payload = json.loads(ticket.read_text(encoding="utf-8"))
        assert "error" not in payload, f"daemon failed to start: {payload['error']} (log: {log})"
        state = RunState.model_validate(payload)
        assert state.status == "ready"
        assert _is_alive(state.supervisor_identity), "daemon died with the launcher"
        assert _is_alive(state.process_identity), "target died with the launcher"
    finally:
        if launcher.returncode is None:
            launcher.kill()
            await launcher.wait()
        try:
            await _teardown(e2e_worktree, owner_id, state)
        finally:
            with contextlib.suppress(OSError):
                ticket.unlink()
