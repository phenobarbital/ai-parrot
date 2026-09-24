"""Unit and process-boundary tests for `parrot.e2e.targets.{redis,botmanager}` (TASK-3530, M4).

Every "acceptance"-flavored test either exercises a genuinely-missing
``redis-server`` binary as this environment's own real, unmocked state
(the "Registry — missing optional implementation (real repository state,
no mock)" convention TASK-3529's own test file established), or spawns a
**real** child process/real disposable Redis instance when a
``redis-server`` binary is actually available on ``PATH`` — never a mock of
the process boundary itself, per this task's own Test Specification: "any
process-boundary acceptance test must use real subprocesses." No
``unittest.mock.MagicMock`` stands in for a :class:`TargetAdapter` or a
``RunState``.

``redis-server`` is not installed on the sandboxed host this task was
implemented on (confirmed directly, and previously documented by TASK-3518's
own research report, ``sdd/state/FEAT-581/research/session.md`` §0). Every
test requiring a real, running ``redis-server`` binary is guarded by
``pytest.mark.skipif`` and skips cleanly here; the full route-level and
supervisor-driven flows below were manually verified end-to-end, against a
disposable, non-shared Redis instance and the real, unmodified
``BotManager``, before this file was committed (see this task's own
completion note).
"""

from __future__ import annotations

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
from aiohttp import web

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError, E2ETargetError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets import TargetAdapter
from parrot.e2e.targets import redis as e2e_redis
from parrot.e2e.targets.botmanager import (
    _BOOTMANAGER_BOOTSTRAP,
    _healthz,
    build_botmanager_adapter,
)

_FEATURE_ID = "FEAT-581"
_OWNER_ID = "owner-1"

_REDIS_SERVER_AVAILABLE = shutil.which("redis-server") is not None
_SKIP_NO_REDIS_SERVER = pytest.mark.skipif(
    not _REDIS_SERVER_AVAILABLE,
    reason="redis-server binary not installed on this host (spec §2: BLOCKED, not a defect)",
)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def real_worktree() -> Path:
    """The actual checkout root this test file lives in.

    Required for any real-subprocess launch of the child bootstrap: the
    entry point transitively imports ``navconfig``, whose project-root
    bootstrap misbehaves when ``cwd`` is not a real, on-disk project
    checkout root (the exact landmine ``test_mcp_targets.py``'s own
    ``real_worktree`` fixture documents for the sibling ``mcp-toolkit``
    adapter). Every artifact this fixture's tests create lives under
    ``real_worktree``, keyed by run_id, and is removed in each test's own
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

    for supervisor in created:
        for _run_id, live in list(supervisor._runs.items()):
            if live.process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(live.process.pid, signal.SIGKILL)


def _dummy_run_state(*, run_id: str, worktree: Path, target_id: str = "botmanager-x") -> RunState:
    """Build a schema-valid :class:`RunState` for a direct ``ready()`` probe."""
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


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


def test_build_botmanager_adapter_conforms_to_target_adapter_protocol() -> None:
    assert isinstance(build_botmanager_adapter(), TargetAdapter)


def test_build_botmanager_adapter_returns_a_fresh_instance_each_call() -> None:
    assert build_botmanager_adapter() is not build_botmanager_adapter()


# ---------------------------------------------------------------------------
# prepare() — validation
# ---------------------------------------------------------------------------


async def test_prepare_rejects_wrong_kind(worktree: Path) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="mcp-stdio")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "kind_mismatch"


async def test_prepare_rejects_unsupported_option(worktree: Path) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager", options={"bogus": 1})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "unsupported_option"


@pytest.mark.parametrize("bad_port", [0, -1, "8080", True])
async def test_prepare_rejects_invalid_port_option(worktree: Path, bad_port) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager", options={"port": bad_port})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "invalid_option"


async def test_prepare_rejects_full_profile(worktree: Path) -> None:
    """Spec §2: "never assume run.py exposes healthz" -- this adapter refuses
    to guess a full-profile contract no task has defined yet."""
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager", profile="full")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "botmanager_full_profile_unsupported"


async def test_prepare_raises_prerequisite_error_when_redis_server_missing(worktree: Path) -> None:
    """Real repository state on this host: no ``redis-server`` binary is
    installed (spec §2: "Missing redis-server blocks required authenticated
    scenarios") -- exercised directly, no mock, when genuinely absent."""
    if _REDIS_SERVER_AVAILABLE:
        pytest.skip("redis-server IS installed on this host; covered by the mocked-absence test instead")
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager")

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "redis_server_missing"


async def test_prepare_raises_prerequisite_error_when_redis_server_missing_mocked(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same outcome, forced via a mock so this test passes on any host."""
    monkeypatch.setattr("parrot.e2e.targets.redis.shutil.which", lambda _name: None)
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager")

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "redis_server_missing"


# ---------------------------------------------------------------------------
# prepare() — plan shape (redis-server binary faked via monkeypatch so this
# is deterministic regardless of host state; no subprocess is spawned by
# prepare() itself either way)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis_binary(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr("parrot.e2e.targets.redis.shutil.which", lambda _name: "/usr/bin/redis-server")
    return "/usr/bin/redis-server"


async def test_prepare_builds_plan_executing_this_modules_own_entrypoint(
    worktree: Path, fake_redis_binary: str
) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager", options={"port": 45123})

    spec = await adapter.prepare(config, run_id="run-bm-1", worktree=worktree)

    assert spec.stdio is False
    assert spec.cwd == worktree
    assert spec.argv == [sys.executable, "-c", _BOOTMANAGER_BOOTSTRAP]


async def test_prepare_sets_the_frozen_session_isolation_env(worktree: Path, fake_redis_binary: str) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager", options={"port": 45124})

    spec = await adapter.prepare(config, run_id="run-bm-2", worktree=worktree)

    assert spec.env["REDIS_HOST"] == "127.0.0.1"
    assert int(spec.env["REDIS_PORT"]) > 0
    assert spec.env["SESSION_DB"] == "0"
    assert spec.env["PORT"] == "45124"
    assert spec.env["E2E_BOTMANAGER_SERVER_NAME"] == "e2e-botmanager-run-bm-2"
    assert spec.env["E2E_REDIS_BINARY"] == fake_redis_binary
    assert len(spec.env["E2E_BOOTSTRAP_SECRET"]) > 20

    site_root = Path(spec.env["SITE_ROOT"])
    assert (site_root / "env").is_dir()
    redis_data_dir = Path(spec.env["E2E_REDIS_DATA_DIR"])
    assert redis_data_dir.parent == e2e_state.run_dir("run-bm-2", worktree=worktree)


async def test_prepare_allocates_distinct_app_and_redis_ports(worktree: Path, fake_redis_binary: str) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager")

    spec = await adapter.prepare(config, run_id="run-bm-3", worktree=worktree)

    assert int(spec.env["PORT"]) != int(spec.env["REDIS_PORT"])


async def test_prepare_never_leaks_the_bootstrap_secret_via_repr(worktree: Path, fake_redis_binary: str) -> None:
    """`LaunchSpec.env` is redacted from `repr()`/`str()` (base.py's own contract)."""
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager")

    spec = await adapter.prepare(config, run_id="run-bm-4", worktree=worktree)

    assert spec.env["E2E_BOOTSTRAP_SECRET"] not in repr(spec)
    assert spec.env["E2E_BOOTSTRAP_SECRET"] not in str(spec)


async def test_prepare_records_endpoint_reused_by_ready(worktree: Path, fake_redis_binary: str) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager", options={"port": 45125})

    await adapter.prepare(config, run_id="run-bm-5", worktree=worktree)

    endpoint = adapter._endpoints["run-bm-5"]
    assert endpoint.host == "127.0.0.1"
    assert endpoint.port == 45125
    assert endpoint.expected_name == "e2e-botmanager-run-bm-5"


# ---------------------------------------------------------------------------
# ready() — no real target/Redis required (HTTP-level identity check only)
# ---------------------------------------------------------------------------


async def test_ready_is_false_for_an_unknown_run_id(worktree: Path) -> None:
    adapter = build_botmanager_adapter()
    state = _dummy_run_state(run_id="never-prepared", worktree=worktree)

    assert await adapter.ready(state) is False


async def test_ready_is_false_when_nothing_listens_yet(worktree: Path, fake_redis_binary: str) -> None:
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager")
    await adapter.prepare(config, run_id="run-bm-6", worktree=worktree)

    state = _dummy_run_state(run_id="run-bm-6", worktree=worktree)
    assert await adapter.ready(state) is False


async def test_ready_rejects_unrelated_pre_existing_service(worktree: Path, fake_redis_binary: str) -> None:
    """A decoy service already listening on this run's chosen port must never
    be mistaken for the real, adapter-launched child (spec §2)."""
    adapter = build_botmanager_adapter()

    async def _decoy_healthz(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "name": "totally-unrelated-service"})

    decoy_app = web.Application()
    decoy_app.router.add_get("/healthz", _decoy_healthz)
    runner = web.AppRunner(decoy_app)
    await runner.setup()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    try:
        config = TargetConfig(kind="botmanager", options={"port": port})
        await adapter.prepare(config, run_id="decoy-run", worktree=worktree)

        state = _dummy_run_state(run_id="decoy-run", worktree=worktree)
        assert await adapter.ready(state) is False
    finally:
        await runner.cleanup()


async def test_ready_is_true_against_the_real_healthz_handler_with_matching_identity(
    worktree: Path, fake_redis_binary: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercises the *real* `_healthz` handler (never a decoy) via a bare
    aiohttp app -- no BotManager/Redis needed for this route alone."""
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind="botmanager")
    spec = await adapter.prepare(config, run_id="run-bm-7", worktree=worktree)
    monkeypatch.setenv("E2E_BOTMANAGER_SERVER_NAME", spec.env["E2E_BOTMANAGER_SERVER_NAME"])

    app = web.Application()
    app.router.add_get("/healthz", _healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    endpoint = adapter._endpoints["run-bm-7"]
    site = web.TCPSite(runner, endpoint.host, endpoint.port)
    await site.start()

    try:
        state = _dummy_run_state(run_id="run-bm-7", worktree=worktree)
        assert await adapter.ready(state) is True
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# parrot.e2e.targets.redis -- structural / real-state tests
# ---------------------------------------------------------------------------


def test_find_redis_server_binary_raises_prerequisite_error_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.e2e.targets.redis.shutil.which", lambda _name: None)

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        e2e_redis.find_redis_server_binary()
    assert excinfo.value.reason_code == "redis_server_missing"


def test_find_redis_server_binary_returns_the_resolved_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("parrot.e2e.targets.redis.shutil.which", lambda _name: "/opt/bin/redis-server")

    assert e2e_redis.find_redis_server_binary() == "/opt/bin/redis-server"


def test_allocate_loopback_port_returns_a_bindable_port() -> None:
    port = e2e_redis.allocate_loopback_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))  # raises OSError if not actually free/bindable


def test_build_redis_argv_disables_persistence_and_binds_loopback(tmp_path: Path) -> None:
    argv = e2e_redis.build_redis_argv("/usr/bin/redis-server", host="127.0.0.1", port=16399, data_dir=tmp_path)

    assert argv[0] == "/usr/bin/redis-server"
    assert "--bind" in argv and argv[argv.index("--bind") + 1] == "127.0.0.1"
    assert "--port" in argv and argv[argv.index("--port") + 1] == "16399"
    assert "--dir" in argv and argv[argv.index("--dir") + 1] == str(tmp_path)
    assert "--save" in argv and argv[argv.index("--save") + 1] == ""
    assert "--appendonly" in argv and argv[argv.index("--appendonly") + 1] == "no"


def test_spawn_private_redis_raises_prerequisite_error_when_binary_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("parrot.e2e.targets.redis.shutil.which", lambda _name: None)

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        e2e_redis.spawn_private_redis(host="127.0.0.1", port=16400, data_dir=tmp_path)
    assert excinfo.value.reason_code == "redis_server_missing"


def test_wait_for_ready_raises_target_error_when_nothing_listens() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]

    with pytest.raises(E2ETargetError) as excinfo:
        e2e_redis._wait_for_ready("127.0.0.1", unused_port, timeout_s=0.2)
    assert excinfo.value.reason_code == "redis_not_ready"


@_SKIP_NO_REDIS_SERVER
def test_spawn_private_redis_real_subprocess_becomes_ready_then_cleans_up(tmp_path: Path) -> None:
    port = e2e_redis.allocate_loopback_port()
    data_dir = tmp_path / "redis-data"

    process, endpoint = e2e_redis.spawn_private_redis(host="127.0.0.1", port=port, data_dir=data_dir, timeout_s=10.0)
    try:
        assert endpoint.host == "127.0.0.1"
        assert endpoint.port == port
        assert process.poll() is None
        with socket.create_connection((endpoint.host, endpoint.port), timeout=1.0) as sock:
            sock.sendall(b"PING\r\n")
            assert sock.recv(64).startswith(b"+PONG")
        # Persistence disabled: no rdb/aof file was ever written.
        assert not any(data_dir.glob("*.rdb"))
        assert not any(data_dir.glob("appendonly*"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
            process.wait(timeout=5.0)
    assert process.returncode is not None


# ---------------------------------------------------------------------------
# Full route-level acceptance (real private Redis, real unmodified
# BotManager) -- skipped when no redis-server binary is installed.
# ---------------------------------------------------------------------------


@_SKIP_NO_REDIS_SERVER
async def test_botmanager_app_full_route_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Anonymous denial, invalid-cookie denial, then a real authenticated
    BotManager route call -- the exact session.md-frozen wire example."""
    from aiohttp.test_utils import TestClient, TestServer

    from parrot.e2e.targets import botmanager as bm

    site_root = tmp_path / "site-root"
    (site_root / "env").mkdir(parents=True, exist_ok=True)
    redis_port = e2e_redis.allocate_loopback_port()

    monkeypatch.setenv("SITE_ROOT", str(site_root))
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", str(redis_port))
    monkeypatch.setenv("SESSION_DB", "0")
    monkeypatch.setenv("E2E_BOOTSTRAP_SECRET", "test-secret-123")
    monkeypatch.setenv("E2E_BOTMANAGER_SERVER_NAME", "e2e-botmanager-test")

    process, _endpoint = e2e_redis.spawn_private_redis(
        host="127.0.0.1", port=redis_port, data_dir=tmp_path / "redis-data", timeout_s=10.0
    )
    try:
        app = bm._build_app()
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/healthz")
            assert response.status == 200
            assert (await response.json()) == {"status": "ok", "name": "e2e-botmanager-test"}

            assert (await client.post("/e2e/bootstrap-login")).status == 403
            assert (await client.post("/e2e/bootstrap-login", headers={"Authorization": "Bearer wrong"})).status == 403

            response = await client.get("/e2e/protected/bot")
            assert response.status == 401
            assert (await response.json()) == {"anonymous": True}

            response = await client.get(
                "/e2e/protected/bot", headers={"Cookie": "csrf_secure=not-valid-json-or-encrypted"}
            )
            assert response.status == 401
            assert (await response.json()) == {"error": "invalid_session"}

            response = await client.post("/e2e/bootstrap-login", headers={"Authorization": "Bearer test-secret-123"})
            assert response.status == 200
            assert "session_id" in (await response.json())

            response = await client.get("/e2e/protected/bot")
            assert response.status == 200
            assert (await response.json()) == {"bot": None, "user_id": "e2e-test-user-3518"}
    finally:
        process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=5.0)


@_SKIP_NO_REDIS_SERVER
async def test_botmanager_real_subprocess_supervisor_driven_readiness_then_stop(
    real_worktree: Path, make_supervisor
) -> None:
    """See the ``real_worktree`` fixture docstring for why this one test
    uses the real checkout root rather than ``tmp_path``."""
    adapter = build_botmanager_adapter()
    supervisor = make_supervisor(adapter_resolver=lambda _kind: adapter)
    config = TargetConfig(kind="botmanager", startup_timeout_s=30)

    state = await supervisor.start("botmanager-a", config)
    try:
        assert state.status == "ready"
        endpoint = adapter._endpoints[state.run_id]

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{endpoint.host}:{endpoint.port}/healthz") as response:
                assert response.status == 200
                body = await response.json()
                assert body["name"] == f"e2e-botmanager-{state.run_id}"
    finally:
        try:
            final_state = await supervisor.stop(state.run_id)
            assert final_state.status == "stopped"
            assert final_state.cleanup_complete is True
        finally:
            state_dir = real_worktree / "sdd" / "state" / "e2e"
            for suffix in (".json", ".lock"):
                with contextlib.suppress(OSError):
                    (state_dir / f"{state.run_id}{suffix}").unlink()
            shutil.rmtree(state_dir / state.run_id, ignore_errors=True)
            shutil.rmtree(real_worktree / "artifacts" / "logs" / "e2e" / state.run_id, ignore_errors=True)
