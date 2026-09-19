"""Unit and process-boundary tests for `parrot.e2e.targets.{ui,browser}` (TASK-3531, M4).

Every "acceptance"-flavored test either exercises a genuinely-missing
prerequisite as this environment's own real, unmocked state (the
"Registry -- missing optional implementation (real repository state, no
mock)" convention TASK-3529/TASK-3530's own test files established), or
spawns a **real** child process (a real ``obscura serve`` instance) when the
binary is actually available on ``PATH`` -- never a mock of the process
boundary itself, per this task's own Test Specification: "any
process-boundary acceptance test must use real subprocesses." No
``unittest.mock.MagicMock`` stands in for a :class:`TargetAdapter` or a
:class:`RunState`: a permissive double would satisfy every ``hasattr`` check
a duck-typed :class:`typing.Protocol` performs and could mask a real defect
-- every fixture below either constructs the real, schema-validated model
or a small, single-purpose fake with only the attributes actually read.

``pnpm``'s admin UI dependencies (``packages/ai-parrot-server/ui/
node_modules``) are **not installed** in this worktree (confirmed directly)
-- the real ``ui_dependencies_missing`` prerequisite failure is exercised
unmocked, mirroring how TASK-3530's own test file exercised a genuinely
missing ``redis-server``. ``obscura`` itself *is* installed on this host, so
`browser`'s real-subprocess tests run for real; a mocked-absence variant
covers the complementary case for any host where it is not.
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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets import TargetAdapter
from parrot.e2e.targets.browser import (
    _SENTINEL_SCRIPT,
    build_browser_adapter,
)
from parrot.e2e.targets.ui import (
    _PNPM_BINARY_ENV,
    _PUBLIC_API_URL_ENV,
    _UI_BOOTSTRAP,
    _UI_DIR_ENV,
    _UI_PORT_ENV,
    build_ui_adapter,
    run_ui_entrypoint,
)

_FEATURE_ID = "FEAT-581"
_OWNER_ID = "owner-1"

_OBSCURA_AVAILABLE = shutil.which("obscura") is not None
_SKIP_NO_OBSCURA = pytest.mark.skipif(
    not _OBSCURA_AVAILABLE,
    reason="obscura binary not installed on this host (spec §2: BLOCKED, not a defect)",
)

_REAL_WORKTREE = Path(__file__).resolve().parents[5]
_UI_NODE_MODULES_INSTALLED = (_REAL_WORKTREE / "packages" / "ai-parrot-server" / "ui" / "node_modules").is_dir()


class _StopExec(Exception):
    """Raised by a fake `os.execv` so `run_ui_entrypoint` tests never actually exec."""


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def real_worktree() -> Path:
    """The actual checkout root this test file lives in (real UI project tree)."""
    return _REAL_WORKTREE


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


def _dummy_run_state(*, run_id: str, worktree: Path, target_id: str = "target-x") -> RunState:
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


async def _wait_for_cdp_ready(port: int, *, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.0)) as session:
        while time.monotonic() < deadline:
            with contextlib.suppress(aiohttp.ClientError, asyncio.TimeoutError, OSError):
                async with session.get(f"http://127.0.0.1:{port}/json/version") as response:
                    if response.status == 200:
                        return
            await asyncio.sleep(0.05)
    raise RuntimeError(f"obscura at 127.0.0.1:{port} never became CDP-ready within {timeout_s}s")


async def _spawn_real_obscura(port: int) -> "asyncio.subprocess.Process":
    """Spawn a real, standalone ``obscura serve`` -- never through this task's own adapter."""
    binary = shutil.which("obscura")
    assert binary is not None
    process = await asyncio.create_subprocess_exec(
        binary,
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    await _wait_for_cdp_ready(port)
    return process


def _kill_process_group(process: "asyncio.subprocess.Process") -> None:
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(process.pid, signal.SIGKILL)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


def test_build_browser_adapter_conforms_to_target_adapter_protocol() -> None:
    assert isinstance(build_browser_adapter(), TargetAdapter)


def test_build_browser_adapter_returns_a_fresh_instance_each_call() -> None:
    assert build_browser_adapter() is not build_browser_adapter()


def test_build_ui_adapter_conforms_to_target_adapter_protocol() -> None:
    assert isinstance(build_ui_adapter(), TargetAdapter)


def test_build_ui_adapter_returns_a_fresh_instance_each_call() -> None:
    assert build_ui_adapter() is not build_ui_adapter()


# ---------------------------------------------------------------------------
# browser.prepare() -- validation
# ---------------------------------------------------------------------------


async def test_browser_prepare_rejects_wrong_kind(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="ui")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "kind_mismatch"


async def test_browser_prepare_rejects_unsupported_option_owned(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"bogus": 1})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "unsupported_option"


@pytest.mark.parametrize("bad_port", [0, -1, "8080", True])
async def test_browser_prepare_rejects_invalid_port_option(worktree: Path, bad_port) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"port": bad_port})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "invalid_option"


@pytest.mark.parametrize("key", ["stealth", "allow_private_network"])
async def test_browser_prepare_rejects_non_bool_owned_flags(worktree: Path, key: str) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={key: "yes"})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "invalid_option"


async def test_browser_prepare_rejects_adoption_under_minimal_profile(worktree: Path) -> None:
    """Spec §2: "deterministic browser checks require an owned isolated instance"."""
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", profile="minimal", options={"adopt": True, "port": 12345})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "browser_adoption_requires_full_profile"


async def test_browser_prepare_rejects_adoption_without_default_profile_too(worktree: Path) -> None:
    """`profile` defaults to "minimal" -- omitting it must not silently permit adoption."""
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"adopt": True, "port": 12345})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "browser_adoption_requires_full_profile"


async def test_browser_prepare_rejects_adoption_missing_port(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", profile="full", options={"adopt": True})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "adopt_requires_port"


async def test_browser_prepare_rejects_unsupported_option_adopted(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", profile="full", options={"adopt": True, "port": 12345, "stealth": True})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "unsupported_option"


async def test_browser_prepare_rejects_empty_adopted_host(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", profile="full", options={"adopt": True, "port": 12345, "host": ""})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "invalid_option"


async def test_browser_prepare_raises_prerequisite_error_when_obscura_missing_real_state(worktree: Path) -> None:
    if _OBSCURA_AVAILABLE:
        pytest.skip("obscura IS installed on this host; covered by the mocked-absence test instead")
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser")

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "obscura_binary_missing"


async def test_browser_prepare_raises_prerequisite_error_when_obscura_missing_mocked(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("parrot.e2e.targets.browser.shutil.which", lambda _name: None)
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser")

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "obscura_binary_missing"


async def test_browser_prepare_adoption_never_resolves_obscura_binary(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adoption must succeed even when `obscura` is entirely absent from PATH."""
    monkeypatch.setattr("parrot.e2e.targets.browser.shutil.which", lambda _name: None)
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", profile="full", options={"adopt": True, "port": 19999})

    spec = await adapter.prepare(config, run_id="run-adopt-1", worktree=worktree)

    assert spec.argv == [sys.executable, "-c", _SENTINEL_SCRIPT]
    assert spec.stdio is False
    assert spec.cwd == worktree


# ---------------------------------------------------------------------------
# browser.prepare() -- owned-mode plan shape (real obscura binary required
# only for resolution, never spawned by prepare() itself)
# ---------------------------------------------------------------------------


@_SKIP_NO_OBSCURA
async def test_browser_prepare_builds_owned_launch_spec(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"port": 34567, "stealth": True, "allow_private_network": True})

    spec = await adapter.prepare(config, run_id="run-owned-1", worktree=worktree)

    assert spec.stdio is False
    assert spec.cwd == worktree
    assert spec.argv[0] == shutil.which("obscura")
    assert spec.argv[1] == "serve"
    assert "--host" in spec.argv and "127.0.0.1" in spec.argv
    assert "--port" in spec.argv and "34567" in spec.argv
    assert "--storage-dir" in spec.argv
    assert "--stealth" in spec.argv
    assert "--allow-private-network" in spec.argv

    storage_dir = Path(spec.argv[spec.argv.index("--storage-dir") + 1])
    assert storage_dir.is_dir()
    assert storage_dir.parent == e2e_state.run_dir("run-owned-1", worktree=worktree)
    assert (storage_dir.stat().st_mode & 0o777) == e2e_state.RUN_DIR_MODE


@_SKIP_NO_OBSCURA
async def test_browser_prepare_allocates_a_fresh_port_by_default(worktree: Path) -> None:
    adapter = build_browser_adapter()

    spec_a = await adapter.prepare(TargetConfig(kind="browser"), run_id="run-owned-2", worktree=worktree)
    spec_b = await adapter.prepare(TargetConfig(kind="browser"), run_id="run-owned-3", worktree=worktree)

    port_a = spec_a.argv[spec_a.argv.index("--port") + 1]
    port_b = spec_b.argv[spec_b.argv.index("--port") + 1]
    assert port_a != port_b


@_SKIP_NO_OBSCURA
async def test_browser_prepare_records_endpoint_reused_by_ready(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"port": 34568})

    await adapter.prepare(config, run_id="run-owned-4", worktree=worktree)

    endpoint = adapter._endpoints["run-owned-4"]
    assert endpoint.adopted is False
    assert endpoint.manager.endpoint == "http://127.0.0.1:34568"


# ---------------------------------------------------------------------------
# browser.ready()
# ---------------------------------------------------------------------------


async def test_browser_ready_is_false_for_an_unknown_run_id(worktree: Path) -> None:
    adapter = build_browser_adapter()
    state = _dummy_run_state(run_id="never-prepared", worktree=worktree)

    assert await adapter.ready(state) is False


@_SKIP_NO_OBSCURA
async def test_browser_ready_is_false_when_nothing_listens_yet(worktree: Path) -> None:
    adapter = build_browser_adapter()
    config = TargetConfig(kind="browser", options={"port": 34569})
    await adapter.prepare(config, run_id="run-owned-5", worktree=worktree)

    state = _dummy_run_state(run_id="run-owned-5", worktree=worktree)
    assert await adapter.ready(state) is False


@_SKIP_NO_OBSCURA
async def test_browser_ready_true_for_a_real_adopted_endpoint(worktree: Path) -> None:
    """Adoption's own `ready()` attaches to the real, externally-owned CDP endpoint."""
    port = _free_test_port()
    process = await _spawn_real_obscura(port)
    try:
        adapter = build_browser_adapter()
        config = TargetConfig(kind="browser", profile="full", options={"adopt": True, "port": port})
        await adapter.prepare(config, run_id="run-adopt-2", worktree=worktree)

        state = _dummy_run_state(run_id="run-adopt-2", worktree=worktree)
        assert await adapter.ready(state) is True
    finally:
        _kill_process_group(process)
        with contextlib.suppress(ProcessLookupError):
            await process.wait()


def _free_test_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ---------------------------------------------------------------------------
# browser -- real subprocess, supervisor-driven owned round trip
# ---------------------------------------------------------------------------


@_SKIP_NO_OBSCURA
async def test_browser_owned_real_subprocess_supervisor_ready_then_stop(make_supervisor, worktree: Path) -> None:
    adapter = build_browser_adapter()
    supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
    config = TargetConfig(kind="browser", startup_timeout_s=15)

    state = await supervisor.start("browser-a", config)
    try:
        assert state.status == "ready"
        endpoint = adapter._endpoints[state.run_id]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.0)) as session:
            async with session.get(f"{endpoint.manager.endpoint}/json/version") as response:
                assert response.status == 200
                body = await response.json()
                assert "webSocketDebuggerUrl" in body
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True
        # The owned Obscura process is gone -- this mode's own kill authority
        # DID reach the process it spawned (contrast with the adoption test
        # below, where it must NOT).
        assert await adapter._endpoints[state.run_id].manager.is_running() is False


@_SKIP_NO_OBSCURA
async def test_browser_adopted_real_subprocess_never_killed_by_supervisor_stop(
    make_supervisor, worktree: Path
) -> None:
    """Core acceptance test for this task's Scope item 2: adoption never
    transfers kill ownership to the supervisor (spec §2: "Adopted browser
    processes are never signaled.")."""
    port = _free_test_port()
    adopted_process = await _spawn_real_obscura(port)
    try:
        adapter = build_browser_adapter()
        supervisor = make_supervisor(adapter_resolver=lambda kind: adapter)
        config = TargetConfig(
            kind="browser", profile="full", startup_timeout_s=15, options={"adopt": True, "port": port}
        )

        state = await supervisor.start("browser-b", config)
        assert state.status == "ready"
        assert _pid_alive(adopted_process.pid) is True

        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True

        # The supervisor killed its own sentinel placeholder -- it must
        # never have touched the real, externally-owned adopted browser.
        assert _pid_alive(adopted_process.pid) is True
        adapter_endpoint = adapter._endpoints[state.run_id]
        assert adapter_endpoint.adopted is True
        assert await adapter_endpoint.manager.is_running() is True
    finally:
        _kill_process_group(adopted_process)
        with contextlib.suppress(ProcessLookupError):
            await adopted_process.wait()


# ---------------------------------------------------------------------------
# ui.prepare() -- validation
# ---------------------------------------------------------------------------


async def test_ui_prepare_rejects_wrong_kind(worktree: Path) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="browser")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "kind_mismatch"


async def test_ui_prepare_rejects_unsupported_option(worktree: Path) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000", "bogus": 1})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "unsupported_option"


async def test_ui_prepare_rejects_missing_backend_url(worktree: Path) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui")

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "missing_backend_url"


@pytest.mark.parametrize("bad_url", ["", "not-a-url", "ftp://host/x", "http://"])
async def test_ui_prepare_rejects_invalid_backend_url(worktree: Path, bad_url: str) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": bad_url})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code in ("missing_backend_url", "invalid_option")


@pytest.mark.parametrize("bad_port", [0, -1, "8080", True])
async def test_ui_prepare_rejects_invalid_port_option(worktree: Path, bad_port) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000", "port": bad_port})

    with pytest.raises(E2EConfigError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "invalid_option"


async def test_ui_prepare_raises_prerequisite_error_when_pnpm_missing(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", lambda _name: None)
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "pnpm_binary_missing"


async def test_ui_prepare_raises_prerequisite_error_when_node_missing(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_which(name: str) -> str | None:
        return "/usr/bin/pnpm" if name == "pnpm" else None

    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", _fake_which)
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "node_binary_missing"


async def test_ui_prepare_raises_prerequisite_error_when_ui_dir_missing(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", lambda _name: "/usr/bin/fake")
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "ui_dir_missing"


async def test_ui_prepare_raises_prerequisite_error_when_node_modules_missing_real_state(
    real_worktree: Path,
) -> None:
    """Real repository state on this host: the admin UI's own `node_modules`
    is not installed in this worktree (confirmed directly)."""
    if _UI_NODE_MODULES_INSTALLED:
        pytest.skip("packages/ai-parrot-server/ui/node_modules IS installed here; covered by the mocked test")
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=real_worktree)
    assert excinfo.value.reason_code == "ui_dependencies_missing"


async def test_ui_prepare_raises_prerequisite_error_when_node_modules_missing_mocked(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", lambda _name: "/usr/bin/fake")
    ui_dir = worktree / "packages" / "ai-parrot-server" / "ui"
    ui_dir.mkdir(parents=True)
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        await adapter.prepare(config, run_id="run-1", worktree=worktree)
    assert excinfo.value.reason_code == "ui_dependencies_missing"


# ---------------------------------------------------------------------------
# ui.prepare() -- plan shape (binaries faked, real dir/node_modules scaffold)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_ui_project(worktree: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def _fake_which(name: str) -> str:
        return {"pnpm": "/usr/bin/pnpm", "node": "/usr/bin/node"}[name]

    monkeypatch.setattr("parrot.e2e.targets.ui.shutil.which", _fake_which)
    ui_dir = worktree / "packages" / "ai-parrot-server" / "ui"
    (ui_dir / "node_modules").mkdir(parents=True)
    return ui_dir


async def test_ui_prepare_builds_plan_executing_this_modules_own_entrypoint(
    worktree: Path, fake_ui_project: Path
) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000", "port": 45210})

    spec = await adapter.prepare(config, run_id="run-ui-1", worktree=worktree)

    assert spec.stdio is False
    assert spec.cwd == worktree
    assert spec.argv == [sys.executable, "-c", _UI_BOOTSTRAP]
    assert spec.env[_PNPM_BINARY_ENV] == "/usr/bin/pnpm"
    assert spec.env[_UI_DIR_ENV] == str(fake_ui_project)
    assert spec.env[_UI_PORT_ENV] == "45210"
    assert spec.env[_PUBLIC_API_URL_ENV] == "http://127.0.0.1:5000"


async def test_ui_prepare_allocates_a_free_port_by_default(worktree: Path, fake_ui_project: Path) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})

    spec = await adapter.prepare(config, run_id="run-ui-2", worktree=worktree)

    assert int(spec.env[_UI_PORT_ENV]) > 0


async def test_ui_prepare_records_endpoint_reused_by_ready(worktree: Path, fake_ui_project: Path) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000", "port": 45211})

    await adapter.prepare(config, run_id="run-ui-3", worktree=worktree)

    endpoint = adapter._endpoints["run-ui-3"]
    assert endpoint.host == "127.0.0.1"
    assert endpoint.port == 45211
    assert endpoint.backend_url == "http://127.0.0.1:5000"


# ---------------------------------------------------------------------------
# ui.ready()
# ---------------------------------------------------------------------------


async def test_ui_ready_is_false_for_an_unknown_run_id(worktree: Path) -> None:
    adapter = build_ui_adapter()
    state = _dummy_run_state(run_id="never-prepared", worktree=worktree)

    assert await adapter.ready(state) is False


async def test_ui_ready_is_false_when_nothing_listens_yet(worktree: Path, fake_ui_project: Path) -> None:
    adapter = build_ui_adapter()
    config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000"})
    await adapter.prepare(config, run_id="run-ui-4", worktree=worktree)

    state = _dummy_run_state(run_id="run-ui-4", worktree=worktree)
    assert await adapter.ready(state) is False


async def _run_local_server(app: web.Application) -> tuple[web.AppRunner, int]:
    runner = web.AppRunner(app)
    await runner.setup()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    return runner, port


async def test_ui_ready_false_when_admin_route_is_not_200(worktree: Path, fake_ui_project: Path) -> None:
    async def _admin(_request: web.Request) -> web.Response:
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/admin/", _admin)
    runner, port = await _run_local_server(app)
    try:
        adapter = build_ui_adapter()
        config = TargetConfig(kind="ui", options={"backend_url": "http://127.0.0.1:5000", "port": port})
        await adapter.prepare(config, run_id="run-ui-5", worktree=worktree)

        state = _dummy_run_state(run_id="run-ui-5", worktree=worktree)
        assert await adapter.ready(state) is False
    finally:
        await runner.cleanup()


async def test_ui_ready_false_when_admin_route_ok_but_backend_unreachable(
    worktree: Path, fake_ui_project: Path
) -> None:
    async def _admin(_request: web.Request) -> web.Response:
        return web.Response(status=200, text="<html></html>")

    app = web.Application()
    app.router.add_get("/admin/", _admin)
    runner, port = await _run_local_server(app)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_backend_port = probe.getsockname()[1]
    try:
        adapter = build_ui_adapter()
        config = TargetConfig(
            kind="ui", options={"backend_url": f"http://127.0.0.1:{closed_backend_port}", "port": port}
        )
        await adapter.prepare(config, run_id="run-ui-6", worktree=worktree)

        state = _dummy_run_state(run_id="run-ui-6", worktree=worktree)
        assert await adapter.ready(state) is False
    finally:
        await runner.cleanup()


async def test_ui_ready_true_when_admin_route_ok_and_backend_reachable(
    worktree: Path, fake_ui_project: Path
) -> None:
    async def _admin(_request: web.Request) -> web.Response:
        return web.Response(status=200, text="<html></html>")

    async def _backend_root(_request: web.Request) -> web.Response:
        # Any HTTP response counts as reachable -- even an error status.
        return web.Response(status=404)

    admin_app = web.Application()
    admin_app.router.add_get("/admin/", _admin)
    admin_runner, admin_port = await _run_local_server(admin_app)

    backend_app = web.Application()
    backend_app.router.add_get("/", _backend_root)
    backend_runner, backend_port = await _run_local_server(backend_app)
    try:
        adapter = build_ui_adapter()
        config = TargetConfig(
            kind="ui", options={"backend_url": f"http://127.0.0.1:{backend_port}/", "port": admin_port}
        )
        await adapter.prepare(config, run_id="run-ui-7", worktree=worktree)

        state = _dummy_run_state(run_id="run-ui-7", worktree=worktree)
        assert await adapter.ready(state) is True
    finally:
        await admin_runner.cleanup()
        await backend_runner.cleanup()


# ---------------------------------------------------------------------------
# ui.run_ui_entrypoint() -- build/preview two-step, no real pnpm invoked
# ---------------------------------------------------------------------------


def test_run_ui_entrypoint_builds_then_execs_preview(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import parrot.e2e.targets.ui as ui_module

    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    monkeypatch.setenv(_UI_DIR_ENV, str(ui_dir))
    monkeypatch.setenv(_PNPM_BINARY_ENV, "/usr/bin/pnpm")
    monkeypatch.setenv(_UI_PORT_ENV, "45300")
    monkeypatch.setenv(_PUBLIC_API_URL_ENV, "http://127.0.0.1:9000")

    calls: dict[str, object] = {}

    def _fake_run(argv, cwd=None, check=False):  # noqa: ANN001
        calls["build_argv"] = argv
        calls["build_cwd"] = cwd
        return subprocess.CompletedProcess(argv, 0)

    def _fake_chdir(path):  # noqa: ANN001
        calls["chdir"] = path

    def _fake_execv(path, argv):  # noqa: ANN001
        calls["exec_path"] = path
        calls["exec_argv"] = argv
        raise _StopExec()

    monkeypatch.setattr(ui_module.subprocess, "run", _fake_run)
    monkeypatch.setattr(ui_module.os, "chdir", _fake_chdir)
    monkeypatch.setattr(ui_module.os, "execv", _fake_execv)

    with pytest.raises(_StopExec):
        run_ui_entrypoint()

    assert calls["build_argv"] == ["/usr/bin/pnpm", "build"]
    assert calls["build_cwd"] == str(ui_dir)
    assert calls["chdir"] == str(ui_dir)
    assert calls["exec_path"] == "/usr/bin/pnpm"
    assert calls["exec_argv"] == [
        "/usr/bin/pnpm",
        "preview",
        "--port",
        "45300",
        "--host",
        "127.0.0.1",
        "--strictPort",
    ]


def test_run_ui_entrypoint_raises_systemexit_when_build_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import parrot.e2e.targets.ui as ui_module

    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    monkeypatch.setenv(_UI_DIR_ENV, str(ui_dir))
    monkeypatch.setenv(_PNPM_BINARY_ENV, "/usr/bin/pnpm")
    monkeypatch.setenv(_UI_PORT_ENV, "45301")
    monkeypatch.setenv(_PUBLIC_API_URL_ENV, "http://127.0.0.1:9000")

    monkeypatch.setattr(
        ui_module.subprocess, "run", lambda argv, cwd=None, check=False: subprocess.CompletedProcess(argv, 7)
    )
    monkeypatch.setattr(ui_module.os, "chdir", lambda _path: pytest.fail("chdir must not run on build failure"))
    monkeypatch.setattr(ui_module.os, "execv", lambda *_a: pytest.fail("execv must not run on build failure"))

    with pytest.raises(SystemExit) as excinfo:
        run_ui_entrypoint()
    assert excinfo.value.code == 7
