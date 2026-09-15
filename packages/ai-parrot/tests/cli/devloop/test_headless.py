"""FEAT-555 TASK-3198 — headless child: handshake, endpoint auth, exit codes, cancel."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession, UnixConnector

from parrot.bots.flows.core.types import FlowStatus
from parrot.cli.devloop.headless import (
    HeadlessExit,
    HeadlessHandshake,
    mount_command_endpoint,
    run_headless,
)


class _Envelope:
    """Minimal stand-in for ActionEnvelope — only model_dump is used."""

    def model_dump(self, mode: str = "python") -> dict:
        return {"ok": True}


def _stub_runner() -> MagicMock:
    runner = MagicMock()
    runner.cancel_run = AsyncMock(return_value=_Envelope())
    runner.resolve_gate = AsyncMock(return_value=_Envelope())
    return runner


@pytest.mark.asyncio
async def test_unix_socket_requires_bearer(tmp_path):
    sock = str(tmp_path / "r.sock")
    fired = []
    app_runner, endpoint = await mount_command_endpoint(
        _stub_runner(), socket_path=sock, port=None, token="t0k", on_cancelled=lambda: fired.append(1)
    )
    assert endpoint == f"unix://{sock}"
    try:
        async with ClientSession(connector=UnixConnector(path=sock)) as s:
            r = await s.post("http://x/runs/run-1/cancel", json={"requested_by": "u"})
            assert r.status == 401

            r = await s.post(
                "http://x/runs/run-1/cancel",
                json={"requested_by": "u"},
                headers={"Authorization": "Bearer t0k"},
            )
            assert r.status == 200
            assert fired == [1]
    finally:
        await app_runner.cleanup()


@pytest.mark.asyncio
async def test_tcp_ephemeral_port_in_endpoint():
    fired = []
    app_runner, endpoint = await mount_command_endpoint(
        _stub_runner(), socket_path=None, port=0, token="t0k", on_cancelled=lambda: fired.append(1)
    )
    try:
        assert endpoint.startswith("http://127.0.0.1:")
        port = int(endpoint.rsplit(":", 1)[1])
        assert port > 0

        async with ClientSession() as s:
            r = await s.post(f"http://127.0.0.1:{port}/runs/run-1/cancel", json={"requested_by": "u"})
            assert r.status == 401

            r = await s.post(
                f"http://127.0.0.1:{port}/runs/run-1/cancel",
                json={"requested_by": "u"},
                headers={"Authorization": "Bearer t0k"},
            )
            assert r.status == 200
            assert fired == [1]
    finally:
        await app_runner.cleanup()


@pytest.mark.asyncio
async def test_run_headless_requires_token(tmp_path, monkeypatch):
    monkeypatch.delenv("PARROT_DEVLOOP_COMMAND_TOKEN", raising=False)
    code = await run_headless(brief_path=str(tmp_path / "b.json"), run_id=None, command_socket=None, command_port=None)
    assert code == int(HeadlessExit.BOOTSTRAP_FAILED)


@pytest.mark.asyncio
async def test_run_headless_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PARROT_DEVLOOP_COMMAND_TOKEN", "t0k")
    brief = SimpleNamespace(kind="bug")
    stub_runner = _stub_runner()
    stub_runner.run = AsyncMock(return_value=SimpleNamespace(status=FlowStatus.COMPLETED))
    runtime = SimpleNamespace(runner=stub_runner)
    sock = str(tmp_path / "run.sock")

    with (
        patch("parrot.cli.devloop.bootstrap.load_headless_brief", return_value=brief),
        patch("parrot.cli.devloop.bootstrap.build_runtime", AsyncMock(return_value=runtime)),
    ):
        code = await run_headless(
            brief_path=str(tmp_path / "b.json"), run_id="run-abcd1234", command_socket=sock, command_port=None
        )

    assert code == int(HeadlessExit.COMPLETED)
    out_lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(out_lines) == 1
    handshake = HeadlessHandshake.model_validate(json.loads(out_lines[0]))
    assert handshake.run_id == "run-abcd1234"
    assert handshake.command_endpoint == f"unix://{sock}"
    assert not __import__("os").path.exists(sock)

    # Failed run.
    stub_runner.run = AsyncMock(return_value=SimpleNamespace(status=FlowStatus.FAILED))
    with (
        patch("parrot.cli.devloop.bootstrap.load_headless_brief", return_value=brief),
        patch("parrot.cli.devloop.bootstrap.build_runtime", AsyncMock(return_value=runtime)),
    ):
        code = await run_headless(
            brief_path=str(tmp_path / "b.json"), run_id="run-abcd1235", command_socket=sock, command_port=None
        )
    assert code == int(HeadlessExit.FAILED)

    # Run raises.
    stub_runner.run = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch("parrot.cli.devloop.bootstrap.load_headless_brief", return_value=brief),
        patch("parrot.cli.devloop.bootstrap.build_runtime", AsyncMock(return_value=runtime)),
    ):
        code = await run_headless(
            brief_path=str(tmp_path / "b.json"), run_id="run-abcd1236", command_socket=sock, command_port=None
        )
    assert code == int(HeadlessExit.FAILED)

    # Bootstrap failure.
    with patch("parrot.cli.devloop.bootstrap.load_headless_brief", side_effect=FileNotFoundError("nope")):
        code = await run_headless(
            brief_path=str(tmp_path / "b.json"), run_id="run-abcd1237", command_socket=sock, command_port=None
        )
    assert code == int(HeadlessExit.BOOTSTRAP_FAILED)


@pytest.mark.asyncio
async def test_cancel_stops_run_task(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_DEVLOOP_COMMAND_TOKEN", "t0k")
    brief = SimpleNamespace(kind="bug")
    stub_runner = _stub_runner()

    async def _hang_forever(*_args, **_kwargs):
        await asyncio.Event().wait()

    stub_runner.run = _hang_forever
    runtime = SimpleNamespace(runner=stub_runner)
    sock = str(tmp_path / "cancel.sock")

    async def _cancel_when_ready():
        # Poll for the socket file to appear (created once the site starts).
        import os

        for _ in range(200):
            if os.path.exists(sock):
                break
            await asyncio.sleep(0.01)
        async with ClientSession(connector=UnixConnector(path=sock)) as s:
            r = await s.post(
                "http://x/runs/run-cancel-me/cancel",
                json={"requested_by": "u"},
                headers={"Authorization": "Bearer t0k"},
            )
            assert r.status == 200

    with (
        patch("parrot.cli.devloop.bootstrap.load_headless_brief", return_value=brief),
        patch("parrot.cli.devloop.bootstrap.build_runtime", AsyncMock(return_value=runtime)),
    ):
        run_task = asyncio.create_task(
            run_headless(
                brief_path=str(tmp_path / "b.json"),
                run_id="run-cancel-me",
                command_socket=sock,
                command_port=None,
                cancel_grace=5.0,
            )
        )
        canceller = asyncio.create_task(_cancel_when_ready())
        code = await asyncio.wait_for(run_task, timeout=10.0)
        await canceller

    assert code == int(HeadlessExit.CANCELLED)
