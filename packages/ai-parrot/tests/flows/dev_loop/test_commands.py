"""Endpoint contract tests for the REST command layer (FEAT-322 TASK-1855).

Uses ``aiohttp_client`` (pytest-aiohttp) against a real ``web.Application``
wired via :func:`register_command_routes`, backed by a real
``DevLoopRunner``/``SessionHost`` pair (registered directly via the
runner's private host-registration helper — this task's scope is the REST
adapter layer, not the full run lifecycle, which is already covered by
``test_runner_host.py``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp import web

from parrot.flows.dev_loop import DevLoopRunner
from parrot.flows.dev_loop.commands import register_command_routes

RUN_ID = "run-cmd0001"


def _build_app(runner: DevLoopRunner) -> web.Application:
    app = web.Application()
    register_command_routes(app, runner)
    return app


@pytest.fixture
def runner() -> DevLoopRunner:
    return DevLoopRunner(MagicMock(), max_concurrent_runs=2)


@pytest.fixture
def host(runner: DevLoopRunner):
    return runner._register_host(RUN_ID)  # noqa: SLF001 - test-only, REST-layer scope


# ---------------------------------------------------------------------------
# resolve_gate — 200 / 400 / 404 / 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_gate_200_envelope(aiohttp_client, runner, host):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "alice", "comment": "lgtm"},
    )

    assert resp.status == 200
    data = await resp.json()
    envelope = data["envelope"]
    assert envelope["action"]["type"] == "gate/resolved"
    assert envelope["origin"] == {"client_id": "alice", "client_seq": 0}
    assert host.state.gates[gate_id].status == "approved"


@pytest.mark.asyncio
async def test_resolve_gate_records_client_seq(aiohttp_client, runner, host):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "alice", "client_seq": 7},
    )

    data = await resp.json()
    assert data["envelope"]["origin"]["client_seq"] == 7


@pytest.mark.asyncio
async def test_resolve_gate_404_unknown_run(aiohttp_client, runner):
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/runs/no-such-run/gates/g1/resolve",
        json={"resolution": "approved", "resolved_by": "alice"},
    )

    assert resp.status == 404
    data = await resp.json()
    assert data["error"] == "unknown_run"


@pytest.mark.asyncio
async def test_resolve_gate_404_unknown_gate(aiohttp_client, runner, host):
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/no-such-gate/resolve",
        json={"resolution": "approved", "resolved_by": "alice"},
    )

    assert resp.status == 404
    data = await resp.json()
    assert data["error"] == "unknown_gate"


@pytest.mark.asyncio
async def test_resolve_gate_409_names_first_resolver(aiohttp_client, runner, host):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    host.resolve_gate(gate_id, "approved", resolved_by="alice", comment="first")
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "rejected", "resolved_by": "bob"},
    )

    assert resp.status == 409
    data = await resp.json()
    assert data["error"] == "already_resolved"
    assert data["status"] == "approved"
    assert data["resolved_by"] == "alice"
    assert data["resolved_at"] is not None


@pytest.mark.asyncio
async def test_resolve_gate_400_bad_resolution(aiohttp_client, runner, host):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "maybe", "resolved_by": "alice"},
    )

    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "invalid_body"


@pytest.mark.asyncio
async def test_resolve_gate_400_missing_resolved_by(aiohttp_client, runner, host):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "approved"},
    )

    assert resp.status == 400


@pytest.mark.asyncio
async def test_resolve_gate_400_invalid_json(aiohttp_client, runner, host):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        data="not json",
        headers={"Content-Type": "application/json"},
    )

    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "invalid_json"


# ---------------------------------------------------------------------------
# cancel_run — 200 / 404, terminal-sticky
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_run_200_terminal(aiohttp_client, runner, host):
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        f"/runs/{RUN_ID}/cancel", json={"requested_by": "alice"}
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["envelope"]["action"]["type"] == "run/cancelled"
    assert host.state.phase == "cancelled"


@pytest.mark.asyncio
async def test_cancel_run_second_cancel_is_200_noop(aiohttp_client, runner, host):
    app = _build_app(runner)
    client = await aiohttp_client(app)

    await client.post(f"/runs/{RUN_ID}/cancel", json={"requested_by": "alice"})
    resp = await client.post(f"/runs/{RUN_ID}/cancel", json={"requested_by": "bob"})

    # Terminal-sticky at the reducer level: cancel is never arbitrated
    # (unlike gates) — the second call still sequences and returns 200,
    # but the reducer no-ops on phase/attribution.
    assert resp.status == 200
    assert host.state.phase == "cancelled"
    assert host.state.cancel_requested_by == "alice"


@pytest.mark.asyncio
async def test_cancel_run_404_unknown_run(aiohttp_client, runner):
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/runs/no-such-run/cancel", json={"requested_by": "alice"}
    )

    assert resp.status == 404
    data = await resp.json()
    assert data["error"] == "unknown_run"


@pytest.mark.asyncio
async def test_cancel_run_400_missing_requested_by(aiohttp_client, runner, host):
    app = _build_app(runner)
    client = await aiohttp_client(app)

    resp = await client.post(f"/runs/{RUN_ID}/cancel", json={})

    assert resp.status == 400
