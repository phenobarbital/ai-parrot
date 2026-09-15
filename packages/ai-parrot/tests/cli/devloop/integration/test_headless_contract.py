"""FEAT-555 TASK-3210 — real headless child over a Unix socket."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, UnixConnector

from parrot.cli.devloop.headless import HeadlessHandshake

STUB_DIR = str(Path(__file__).parent)
pytestmark = pytest.mark.integration

# Child-spawning tests only make sense when this interpreter can actually
# import the workspace (same PYTHONPATH the test runner itself uses) — skip
# cleanly rather than fail CI environments that cannot launch the CLI.
_CAN_SPAWN = shutil.which(sys.executable) is not None


def _skip_if_cannot_spawn():
    if not _CAN_SPAWN:
        pytest.skip("cannot locate a Python interpreter to spawn the headless child")


async def _spawn(tmp_path, run_id="run-e2e1", token="tok"):
    brief = tmp_path / "b.json"
    brief.write_text(json.dumps({"kind": "new_feature", "title": "t", "description": "d"}))
    sock = str(tmp_path / "c.sock")
    gate_file = tmp_path / "gate_id.txt"
    env = {
        **os.environ,
        "PARROT_DEVLOOP_COMMAND_TOKEN": token,
        "PARROT_DEVLOOP_STUB_RUNNER": "1",
        "PARROT_DEVLOOP_STUB_GATE_FILE": str(gate_file),
        "PYTHONPATH": STUB_DIR + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import _stub_runner; from parrot.cli import cli; cli()",
        "devloop",
        "run",
        "--brief",
        str(brief),
        "--yes",
        "--headless",
        "--command-socket",
        sock,
        "--run-id",
        run_id,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    # The child's own startup logging (e.g. the Navigator banner) may land on
    # stdout before `run_headless` reconfigures logging to stderr — read
    # lines until one actually validates as the handshake, exactly like
    # HeadlessRunProcess._drain does in production.
    deadline = asyncio.get_event_loop().time() + 60
    handshake = None
    while asyncio.get_event_loop().time() < deadline:
        line = await asyncio.wait_for(proc.stdout.readline(), max(1.0, deadline - asyncio.get_event_loop().time()))
        if not line:
            stderr = (await proc.stderr.read()).decode("utf-8", "replace")
            raise AssertionError(f"child exited before a handshake; stderr tail:\n{stderr[-4000:]}")
        try:
            handshake = HeadlessHandshake.model_validate_json(line)
            break
        except Exception:  # noqa: BLE001 - pre-handshake noise, keep reading
            continue
    if handshake is None:
        raise AssertionError("child never printed a valid handshake within 60s")
    return proc, handshake, sock, gate_file


async def _read_gate_id(gate_file: Path, timeout: float = 10.0) -> str:
    """Poll the stub's file side-channel for the real (uuid4) gate id."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if gate_file.exists():
            content = gate_file.read_text(encoding="utf-8").strip()
            if content:
                return content
        await asyncio.sleep(0.05)
    raise AssertionError("stub never wrote a gate id within the timeout")


@pytest.mark.asyncio
async def test_cross_process_command_contract(tmp_path):
    _skip_if_cannot_spawn()
    proc, hs, sock, gate_file = await _spawn(tmp_path)
    try:
        assert hs.command_endpoint == f"unix://{sock}"
        gate_id = await _read_gate_id(gate_file)
        async with ClientSession(connector=UnixConnector(path=sock)) as s:
            # (1) no bearer ⇒ 401
            r = await s.post(
                f"http://x/runs/{hs.run_id}/gates/{gate_id}/resolve",
                json={"resolution": "approved", "resolved_by": "u", "answers": {"What store?": "pgvector"}},
            )
            assert r.status == 401

            # (2) resolve the stub's open_questions gate with answers ⇒ 200
            r = await s.post(
                f"http://x/runs/{hs.run_id}/gates/{gate_id}/resolve",
                json={"resolution": "approved", "resolved_by": "u", "answers": {"What store?": "pgvector"}},
                headers={"Authorization": "Bearer tok"},
            )
            assert r.status == 200

            # (3) second resolve ⇒ 409 (first-writer wins)
            r = await s.post(
                f"http://x/runs/{hs.run_id}/gates/{gate_id}/resolve",
                json={"resolution": "approved", "resolved_by": "u", "answers": {"What store?": "pgvector"}},
                headers={"Authorization": "Bearer tok"},
            )
            assert r.status == 409

        # (4) child exits 0 within 60 s and the socket file is gone
        code = await asyncio.wait_for(proc.wait(), timeout=60)
        assert code == 0
        assert not os.path.exists(sock)
    finally:
        if proc.returncode is None:
            proc.kill()


@pytest.mark.asyncio
async def test_headless_child_end_to_end_stub_runner(tmp_path):
    """A cancel over the real socket makes the real child exit 2 within its cancel grace."""
    _skip_if_cannot_spawn()
    proc, hs, sock, _gate_file = await _spawn(tmp_path, run_id="run-e2e2")
    try:
        async with ClientSession(connector=UnixConnector(path=sock)) as s:
            r = await s.post(
                f"http://x/runs/{hs.run_id}/cancel",
                json={"requested_by": "u"},
                headers={"Authorization": "Bearer tok"},
            )
            assert r.status == 200
        code = await asyncio.wait_for(proc.wait(), timeout=60)
        assert code == 2
    finally:
        if proc.returncode is None:
            proc.kill()


@pytest.mark.asyncio
async def test_child_crash_before_terminal_action(tmp_path):
    """A child killed mid-run exits non-zero and never delivered a run/closed action.

    Parent-side classification of this scenario (``process_exited``) is
    exercised via ``HeadlessRunProcess`` in TASK-3202's own tests — this
    test only asserts the child-side contract: no clean exit code without a
    terminal action.
    """
    _skip_if_cannot_spawn()
    proc, hs, sock, _gate_file = await _spawn(tmp_path, run_id="run-e2e3")
    try:
        assert proc.returncode is None  # still running, waiting on the gate
        proc.kill()
        code = await asyncio.wait_for(proc.wait(), timeout=10)
        assert code != 0
    finally:
        if proc.returncode is None:
            proc.kill()
