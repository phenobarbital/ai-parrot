"""Unit and process-boundary tests for ``parrot.e2e.targets.mcp`` (TASK-3529, M4).

Every "acceptance"-flavored test spawns a **real** child process — either
directly (``subprocess``) or through a real
:class:`~parrot.e2e.supervisor.E2ESupervisor` — never a mock of the process
boundary itself, per this task's own Test Specification: "any
process-boundary acceptance test must use real subprocesses." No
``unittest.mock.MagicMock`` stands in for a :class:`TargetAdapter` or a
``RunState``: a permissive double would satisfy every ``hasattr`` check a
duck-typed Protocol performs and could mask a real defect.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pytest
import yaml
from aiohttp import web

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets import TargetAdapter
from parrot.e2e.targets.mcp import (
    _CLI_BOOTSTRAP,
    _HTTP_BASE_PATH,
    build_mcp_stdio_adapter,
    build_mcp_toolkit_adapter,
)

_FEATURE_ID = "FEAT-581"
_OWNER_ID = "owner-1"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def real_worktree() -> Path:
    """The actual checkout root this test file lives in.

    Verified directly: a ``parrot mcp serve --transport http`` child spawned
    via ``asyncio.create_subprocess_exec`` exits itself within ~1-2s
    (returncode 0, no signal, no traceback) whenever its ``cwd`` is any
    directory other than a real, on-disk project checkout root — including
    a plain ``tmp_path`` and even a *subdirectory* of this very checkout.
    Reproduced with no adapter code involved at all (bypassing this task's
    module and ``click`` entirely, calling ``parrot.mcp.cli._run_standalone_
    server`` directly), so this is pre-existing ``parrot.mcp.cli``/navconfig
    bootstrap behavior, out of this task's file scope to fix. Using this
    worktree's own root as ``worktree``/``cwd`` for exactly the one
    real-subprocess HTTP test that needs a genuinely running child avoids
    the landmine; every artifact it creates is removed by that test's own
    ``finally`` block.
    """
    return Path(__file__).resolve().parents[5]


@pytest.fixture
def make_supervisor(worktree: Path):
    created: list[E2ESupervisor] = []

    def _make(**kwargs) -> E2ESupervisor:
        supervisor = E2ESupervisor(worktree=worktree, owner_id=_OWNER_ID, feature_id=_FEATURE_ID, **kwargs)
        created.append(supervisor)
        return supervisor

    yield _make

    # Best-effort cleanup: reap any run left alive by a failing test so no
    # child process leaks past this test (mirrors test_supervisor.py).
    for supervisor in created:
        for _run_id, live in list(supervisor._runs.items()):
            if live.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(live.process.pid, signal.SIGKILL)


def _dummy_run_state(*, run_id: str, worktree: Path, target_id: str = "toolkit-x") -> RunState:
    """Build a schema-valid :class:`RunState` for a direct ``ready()`` probe.

    Uses this test process's own real, live identity (never a fabricated
    one) via the already-verified :func:`parrot.e2e.state.capture_process_identity`.
    """
    identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    now = datetime.now(timezone.utc)
    return RunState(
        feature_id=_FEATURE_ID,
        run_id=run_id,
        worktree=str(worktree.resolve()),
        owner_id=_OWNER_ID,
        controller_identity=identity,
        supervisor_identity=identity,
        process_identity=identity,
        target_id=target_id,
        status="starting",
        control_socket=str(worktree / "control.sock"),
        started_at=now,
        deadline=now + timedelta(seconds=60),
        log_path=str(worktree / "run.log"),
    )


async def _json_rpc_http(session: aiohttp.ClientSession, base_url: str, method: str, params: dict, request_id: int):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    async with session.post(f"{base_url}{_HTTP_BASE_PATH}", json=payload) as response:
        assert response.status == 200
        return await response.json()


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


def test_build_mcp_stdio_adapter_conforms_to_target_adapter_protocol() -> None:
    assert isinstance(build_mcp_stdio_adapter(), TargetAdapter)


def test_build_mcp_toolkit_adapter_conforms_to_target_adapter_protocol() -> None:
    assert isinstance(build_mcp_toolkit_adapter(), TargetAdapter)


def test_build_mcp_stdio_adapter_returns_a_fresh_instance_each_call() -> None:
    assert build_mcp_stdio_adapter() is not build_mcp_stdio_adapter()


def test_build_mcp_toolkit_adapter_returns_a_fresh_instance_each_call() -> None:
    assert build_mcp_toolkit_adapter() is not build_mcp_toolkit_adapter()


# ---------------------------------------------------------------------------
# mcp-stdio — prepare() validation and plan shape
# ---------------------------------------------------------------------------


async def test_mcp_stdio_prepare_rejects_wrong_kind(worktree: Path) -> None:
    adapter = build_mcp_stdio_adapter()
    config = TargetConfig(kind="mcp-toolkit")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "kind_mismatch"


async def test_mcp_stdio_prepare_rejects_unsupported_option(worktree: Path) -> None:
    adapter = build_mcp_stdio_adapter()
    config = TargetConfig(kind="mcp-stdio", options={"bogus": 1})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "unsupported_option"


async def test_mcp_stdio_prepare_builds_plan_executing_the_checkout_cli_module(worktree: Path) -> None:
    adapter = build_mcp_stdio_adapter()
    config = TargetConfig(kind="mcp-stdio")

    spec = await adapter.prepare(config, run_id="run-stdio-1", worktree=worktree)

    assert spec.stdio is True
    assert spec.cwd == worktree
    assert spec.argv[0] == sys.executable
    assert spec.argv[1] == "-c"
    assert spec.argv[2] == _CLI_BOOTSTRAP
    assert spec.argv[3] == "mcp-local"
    assert spec.argv[4] == "memory"
    assert spec.argv[5] == "--config"
    assert len(spec.argv) == 7
    config_path = Path(spec.argv[6])
    assert config_path.is_file()
    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert written["toolkits"]["memory"]["class"] == "parrot.tools.working_memory.tool.WorkingMemoryToolkit"


async def test_mcp_stdio_prepare_writes_private_config_under_run_dir(worktree: Path) -> None:
    adapter = build_mcp_stdio_adapter()
    config = TargetConfig(kind="mcp-stdio")

    spec = await adapter.prepare(config, run_id="run-stdio-2", worktree=worktree)

    run_directory = e2e_state.run_dir("run-stdio-2", worktree=worktree)
    assert Path(spec.argv[-1]).parent == run_directory


async def test_mcp_stdio_ready_is_always_true_and_never_touches_endpoint(worktree: Path) -> None:
    """``ready()`` never assumes an HTTP endpoint for a stdio launch."""
    adapter = build_mcp_stdio_adapter()
    state = _dummy_run_state(run_id="run-stdio-3", worktree=worktree)
    assert state.endpoint is None

    assert await adapter.ready(state) is True


# ---------------------------------------------------------------------------
# mcp-toolkit — prepare() validation and plan shape
# ---------------------------------------------------------------------------


async def test_mcp_toolkit_prepare_rejects_wrong_kind(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-stdio")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-2", worktree=worktree)
    assert excinfo.value.reason_code == "kind_mismatch"


async def test_mcp_toolkit_prepare_rejects_unsupported_option(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-toolkit", options={"bogus": 1})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-2", worktree=worktree)
    assert excinfo.value.reason_code == "unsupported_option"


@pytest.mark.parametrize("bad_port", [0, -1, "8080", True])
async def test_mcp_toolkit_prepare_rejects_invalid_port_option(worktree: Path, bad_port) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-toolkit", options={"port": bad_port})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-2", worktree=worktree)
    assert excinfo.value.reason_code == "invalid_option"


async def test_mcp_toolkit_prepare_builds_plan_executing_the_checkout_cli_module(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-toolkit", options={"port": 34567})

    spec = await adapter.prepare(config, run_id="run-http-1", worktree=worktree)

    assert spec.stdio is False
    assert spec.cwd == worktree
    assert spec.argv[0] == sys.executable
    assert spec.argv[1] == "-c"
    assert spec.argv[2] == _CLI_BOOTSTRAP
    assert spec.argv[3] == "mcp"
    assert spec.argv[4] == "serve"
    config_path = Path(spec.argv[5])
    assert spec.argv[6] == "--transport"
    assert spec.argv[7] == "http"
    assert spec.argv[8] == "--port"
    assert spec.argv[9] == "34567"
    assert len(spec.argv) == 10
    assert config_path.is_file()
    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert written["name"] == "e2e-mcp-toolkit-run-http-1"
    assert written["tools"] == [{"class": "WorkingMemoryToolkit", "module": "parrot.tools.working_memory.tool"}]


async def test_mcp_toolkit_prepare_allocates_a_free_port_by_default(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-toolkit")

    spec = await adapter.prepare(config, run_id="run-http-2", worktree=worktree)

    port = int(spec.argv[-1])
    assert 0 < port < 65536


async def test_mcp_toolkit_prepare_records_endpoint_reused_by_ready(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-toolkit", options={"port": 34568})

    await adapter.prepare(config, run_id="run-http-3", worktree=worktree)

    endpoint = adapter._endpoints["run-http-3"]
    assert endpoint.host == "127.0.0.1"
    assert endpoint.port == 34568
    assert endpoint.expected_name == "e2e-mcp-toolkit-run-http-3"


async def test_mcp_toolkit_ready_is_false_for_an_unknown_run_id(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    state = _dummy_run_state(run_id="never-prepared", worktree=worktree)

    assert await adapter.ready(state) is False


# ---------------------------------------------------------------------------
# mcp-toolkit — reject an unrelated pre-existing service's health response
# ---------------------------------------------------------------------------


async def test_mcp_toolkit_ready_rejects_unrelated_pre_existing_service(worktree: Path) -> None:
    """A decoy service already listening on this run's chosen port must never
    be mistaken for the real, adapter-launched child (spec §2)."""
    adapter = build_mcp_toolkit_adapter()

    async def _decoy_info(_request: web.Request) -> web.Response:
        return web.json_response(
            {"name": "totally-unrelated-service", "version": "0.0.1", "transport": "http", "tools_count": 0}
        )

    decoy_app = web.Application()
    decoy_app.router.add_get(f"{_HTTP_BASE_PATH}/info", _decoy_info)
    runner = web.AppRunner(decoy_app)
    await runner.setup()

    # Allocate a free loopback port ourselves, then hand that exact port to
    # the adapter via options["port"] so `prepare()` records the SAME
    # address `ready()` will poll -- the decoy occupies it first.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    try:
        config = TargetConfig(kind="mcp-toolkit", options={"port": port})
        await adapter.prepare(config, run_id="decoy-run", worktree=worktree)

        state = _dummy_run_state(run_id="decoy-run", worktree=worktree)
        assert await adapter.ready(state) is False
    finally:
        await runner.cleanup()


async def test_mcp_toolkit_ready_is_false_when_nothing_listens_yet(worktree: Path) -> None:
    adapter = build_mcp_toolkit_adapter()
    config = TargetConfig(kind="mcp-toolkit")
    await adapter.prepare(config, run_id="run-http-4", worktree=worktree)

    state = _dummy_run_state(run_id="run-http-4", worktree=worktree)
    assert await adapter.ready(state) is False


# ---------------------------------------------------------------------------
# mcp-toolkit — real subprocess, supervisor-driven, put/get/drop round trip
# ---------------------------------------------------------------------------


async def test_mcp_toolkit_real_subprocess_ready_then_put_get_drop(real_worktree: Path) -> None:
    """See the ``real_worktree`` fixture docstring for why this one test
    uses the real checkout root rather than ``tmp_path``."""
    adapter = build_mcp_toolkit_adapter()
    supervisor = E2ESupervisor(
        worktree=real_worktree, owner_id=_OWNER_ID, feature_id=_FEATURE_ID, adapter_resolver=lambda kind: adapter
    )
    config = TargetConfig(kind="mcp-toolkit", startup_timeout_s=30)

    state = await supervisor.start("toolkit-a", config)
    try:
        assert state.status == "ready"
        endpoint = adapter._endpoints[state.run_id]
        base_url = f"http://{endpoint.host}:{endpoint.port}"

        async with aiohttp.ClientSession() as session:
            info_resp = await session.get(f"{base_url}{_HTTP_BASE_PATH}/info")
            info = await info_resp.json()
            assert info["name"] == f"e2e-mcp-toolkit-{state.run_id}"

            init_resp = await _json_rpc_http(session, base_url, "initialize", {}, request_id=1)
            assert "result" in init_resp

            list_resp = await _json_rpc_http(session, base_url, "tools/list", {}, request_id=2)
            names = {tool["name"] for tool in list_resp["result"]["tools"]}
            # No exact tool-count assertion (spec §2) -- only that the fixed
            # put/get/drop surface this scenario needs is present.
            assert {"wm_store_result", "wm_get_result", "wm_drop_stored"} <= names

            store_resp = await _json_rpc_http(
                session,
                base_url,
                "tools/call",
                {"name": "wm_store_result", "arguments": {"key": "greeting", "data": "hello-e2e"}},
                request_id=3,
            )
            assert store_resp["result"]["isError"] is False

            get_resp = await _json_rpc_http(
                session,
                base_url,
                "tools/call",
                {"name": "wm_get_result", "arguments": {"key": "greeting"}},
                request_id=4,
            )
            assert get_resp["result"]["isError"] is False
            assert "hello-e2e" in get_resp["result"]["content"][0]["text"]

            drop_resp = await _json_rpc_http(
                session,
                base_url,
                "tools/call",
                {"name": "wm_drop_stored", "arguments": {"key": "greeting"}},
                request_id=5,
            )
            assert drop_resp["result"]["isError"] is False
    finally:
        try:
            final_state = await supervisor.stop(state.run_id)
            assert final_state.status == "stopped"
            assert final_state.cleanup_complete is True
        finally:
            # Never leave real-worktree debris behind: every artifact this
            # run created lives under `real_worktree`, keyed by run_id.
            state_dir = real_worktree / "sdd" / "state" / "e2e"
            for suffix in (".json", ".lock"):
                with contextlib.suppress(OSError):
                    (state_dir / f"{state.run_id}{suffix}").unlink()
            shutil.rmtree(state_dir / state.run_id, ignore_errors=True)
            shutil.rmtree(real_worktree / "artifacts" / "logs" / "e2e" / state.run_id, ignore_errors=True)


# ---------------------------------------------------------------------------
# mcp-stdio — real subprocess, supervisor-mediated handshake/notification/calls
# ---------------------------------------------------------------------------


async def test_mcp_stdio_real_subprocess_supervisor_mediated_round_trip(make_supervisor, worktree: Path) -> None:
    adapter = build_mcp_stdio_adapter()
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="mcp-stdio", startup_timeout_s=30)

    state = await supervisor.start("toolkit-b", config)
    try:
        assert state.status == "ready"
        assert state.endpoint is None

        init_resp = await supervisor.request_stdio(
            state.run_id, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert init_resp["id"] == 1
        assert init_resp["result"]["serverInfo"]["name"] == "parrot-memory"

        # A bare JSON-RPC notification gets no response line; `request_stdio`
        # always reads one back, so this is sent directly on the same
        # supervisor-retained pipe `request_stdio` itself writes/reads from
        # (never re-derived from a PID/PID file) -- exactly the "supervisor
        # retains pipes" contract this target's spec row fixes.
        live = supervisor._runs[state.run_id]
        notification = b'{"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}\n'
        live.process.stdin.write(notification)
        await live.process.stdin.drain()

        list_resp = await supervisor.request_stdio(
            state.run_id, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        names = {tool["name"] for tool in list_resp["result"]["tools"]}
        assert {"wm_store_result", "wm_get_result", "wm_drop_stored"} <= names

        store_resp = await supervisor.request_stdio(
            state.run_id,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "wm_store_result", "arguments": {"key": "greeting", "data": "hello-e2e"}},
            },
        )
        assert store_resp["result"]["isError"] is False

        get_resp = await supervisor.request_stdio(
            state.run_id,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "wm_get_result", "arguments": {"key": "greeting"}},
            },
        )
        assert get_resp["result"]["isError"] is False
        assert "hello-e2e" in get_resp["result"]["content"][0]["text"]
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True


# ---------------------------------------------------------------------------
# mcp-stdio — direct real subprocess: stdout JSON purity and EOF shutdown
# ---------------------------------------------------------------------------


def test_mcp_stdio_plan_stdout_purity_and_eof_shutdown(worktree: Path) -> None:
    """Exercise the adapter's own launch plan directly (no supervisor), proving
    it really is the ``mcp-local`` entry point: valid JSON-RPC on stdout, and
    a clean exit-0 shutdown once stdin reaches EOF."""

    async def _prepare() -> "asyncio.subprocess.Process":
        adapter = build_mcp_stdio_adapter()
        config = TargetConfig(kind="mcp-stdio")
        spec = await adapter.prepare(config, run_id="run-eof-1", worktree=worktree)
        return spec

    spec = asyncio.run(_prepare())

    proc = subprocess.Popen(
        spec.argv,
        cwd=str(spec.cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        import json as _json

        proc.stdin.write(_json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
        proc.stdin.flush()

        line = proc.stdout.readline()
        assert line, f"no stdout output (exit={proc.poll()}); stderr:\n{proc.stderr.read()}"
        response = _json.loads(line)  # raises if stdout isn't pure JSON-RPC
        assert response["id"] == 1
        assert response["result"]["serverInfo"]["name"] == "parrot-memory"
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    assert proc.returncode == 0
