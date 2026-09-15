"""Tests for HeadlessRunProcess (TASK-3202) using fake_child.py."""

import os
import sys
from pathlib import Path

import pytest

from parrot.integrations.devloop.models import DevLoopIntegrationConfig, SpawnError
from parrot.integrations.devloop.process import HeadlessRunProcess

_CHILD = Path(__file__).with_name("fake_child.py")


def _cfg(tmp_path) -> DevLoopIntegrationConfig:
    return DevLoopIntegrationConfig(
        name="t", enabled=True, repo_path=str(tmp_path), command=[sys.executable, str(_CHILD)]
    )


async def _spawn(tmp_path, run_id="run-t1", **env):
    os.environ.update(env)
    try:
        return await HeadlessRunProcess.spawn(
            config=_cfg(tmp_path),
            run_id=run_id,
            brief_path=str(tmp_path / "b.json"),
            socket_path=str(tmp_path / "s.sock"),
            port=None,
            token="tok",
        )
    finally:
        for k in env:
            os.environ.pop(k, None)


@pytest.mark.asyncio
async def test_spawn_reads_handshake(tmp_path):
    proc = await _spawn(tmp_path)
    hs = await proc.wait_ready(timeout=20)
    assert hs.run_id == "run-t1" and hs.command_endpoint.startswith("unix://")
    await proc.terminate()
    assert await proc.wait() in (2, -15)


@pytest.mark.asyncio
async def test_no_handshake_raises_spawn_error(tmp_path):
    proc = await _spawn(tmp_path, FAKE_CHILD_NO_HANDSHAKE="1")
    with pytest.raises(SpawnError) as exc:
        await proc.wait_ready(timeout=20)
    assert exc.value.exit_code == 3 and "boom" in exc.value.stderr_tail
    await proc.wait()


@pytest.mark.asyncio
async def test_pipes_drained(tmp_path):
    proc = await _spawn(tmp_path, FAKE_CHILD_SPAM="1", FAKE_CHILD_EXIT="0")
    hs = await proc.wait_ready(timeout=20)
    assert hs.run_id == "run-t1"
    # The child idles for up to 30s waiting for cancellation; cancel it via
    # terminate() so this test does not itself wait 30s for the natural exit.
    await proc.terminate()
    code = await proc.wait()
    assert code in (0, -15)
    assert len(proc.stderr_tail()) <= 4096


@pytest.mark.asyncio
async def test_cleanup_removes_socket_and_brief(tmp_path):
    sock = tmp_path / "s.sock"
    brief = tmp_path / "b.json"
    brief.write_text("{}")
    proc = await _spawn(tmp_path)
    await proc.wait_ready(timeout=20)
    assert sock.exists()  # the real child bound the socket
    await proc.terminate()
    await proc.wait()
    proc.cleanup()
    assert not sock.exists() and not brief.exists()
    # Idempotent: calling again must not raise.
    proc.cleanup()


@pytest.mark.asyncio
async def test_cancel_exits_with_code_2(tmp_path):
    """Real cross-process cancel: POST /cancel makes the fake child exit 2."""
    from aiohttp import ClientSession, UnixConnector

    proc = await _spawn(tmp_path, run_id="run-cancel-me")
    hs = await proc.wait_ready(timeout=20)
    sock_path = hs.command_endpoint[len("unix://") :]
    async with ClientSession(connector=UnixConnector(path=sock_path)) as s:
        r = await s.post(
            "http://x/runs/run-cancel-me/cancel",
            json={"requested_by": "u"},
            headers={"Authorization": "Bearer tok"},
        )
        assert r.status == 200
    code = await proc.wait()
    assert code == 2
