"""Unit tests for the async `ChromeManager` (HOTFIX-chromemanager-async-migration-1).

Module 1 tests cover `ChromeManager` itself (`parrot.mcp.chrome`):
readiness probing via `aiohttp`, spawning via `asyncio.create_subprocess_exec`,
and process shutdown via `asyncio.wait_for`. Task 2 appends Module 2 tests
(the pure factory + `ensure_chrome_running()`) to this same file.
"""
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

import parrot.mcp.chrome as chrome_mod
from parrot.mcp.chrome import ChromeManager


@pytest.fixture
def manager():
    return ChromeManager(port=9555)


@pytest.fixture
def fake_proc():
    proc = MagicMock()
    proc.returncode = None
    proc.wait = AsyncMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


def test_no_requests_import():
    src = inspect.getsource(chrome_mod)
    assert "import requests" not in src
    assert "time.sleep" not in src
    assert "subprocess." not in src.replace("asyncio.subprocess.", "")


async def test_is_running_true_on_200(manager):
    resp = MagicMock(status=200)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    with patch("parrot.mcp.chrome.aiohttp.ClientSession", return_value=session):
        assert await manager.is_running() is True


async def test_is_running_false_on_connection_error(manager):
    with patch(
        "parrot.mcp.chrome.aiohttp.ClientSession",
        side_effect=aiohttp.ClientConnectionError(),
    ):
        assert await manager.is_running() is False


async def test_is_chrome_running_warns_and_delegates(manager):
    with patch.object(manager, "is_running", AsyncMock(return_value=True)):
        with pytest.warns(DeprecationWarning):
            assert await manager.is_chrome_running() is True


async def test_start_returns_true_when_already_running(manager):
    with patch.object(manager, "is_running", AsyncMock(return_value=True)), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock()) as spawn:
        assert await manager.start() is True
        spawn.assert_not_called()


async def test_start_spawns_and_polls(manager, fake_proc):
    with patch.object(manager, "is_running", AsyncMock(side_effect=[False, False, True])), \
         patch("parrot.mcp.chrome.shutil.which", return_value="/usr/bin/google-chrome"), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)) as spawn, \
         patch("parrot.mcp.chrome.asyncio.sleep", AsyncMock()):
        assert await manager.start(headless=True, timeout=5) is True
    argv = spawn.call_args.args
    assert "--remote-debugging-port=9555" in argv and "--headless=new" in argv


async def test_start_no_binary_found_falls_back(manager, fake_proc):
    with patch.object(manager, "is_running", AsyncMock(side_effect=[False, True])), \
         patch("parrot.mcp.chrome.shutil.which", return_value=None), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)) as spawn, \
         patch("parrot.mcp.chrome.asyncio.sleep", AsyncMock()):
        assert await manager.start(timeout=5) is True
    argv = spawn.call_args.args
    assert argv[0] == "google-chrome"


async def test_start_times_out(manager, fake_proc):
    with patch.object(manager, "is_running", AsyncMock(return_value=False)), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        assert await manager.start(timeout=0.2) is False


async def test_start_spawn_exception_returns_false(manager):
    with patch.object(manager, "is_running", AsyncMock(return_value=False)), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("boom"))):
        assert await manager.start(timeout=1) is False


async def test_start_does_not_block_loop(manager, fake_proc):
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    t = asyncio.create_task(ticker())
    with patch.object(manager, "is_running", AsyncMock(return_value=False)), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        await manager.start(timeout=0.5)
    t.cancel()
    assert ticks >= 5


async def test_stop_terminates_then_kills(manager, fake_proc):
    async def hang():
        await asyncio.sleep(60)

    fake_proc.wait = hang
    manager.process = fake_proc
    with patch("parrot.mcp.chrome.asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)):
        await manager.stop()
    fake_proc.terminate.assert_called_once()
    fake_proc.kill.assert_called_once()
    assert manager.process is None


async def test_stop_noop_when_no_process(manager):
    manager.process = None
    await manager.stop()
    assert manager.process is None


# ---------------------------------------------------------------------------
# Module 2 (HOTFIX-chromemanager-async-migration-2): pure factory,
# ensure_chrome_running(), ensure_running kwarg, async shutdown.
# ---------------------------------------------------------------------------
from parrot.mcp import integration as integ  # noqa: E402


def test_factory_has_no_side_effects():
    with patch.object(integ.ChromeManager, "start", AsyncMock()) as start, \
         patch.dict(integ._chrome_managers, {}, clear=True):
        cfg = integ.create_chrome_devtools_mcp_server()
        assert integ._chrome_managers == {}
    start.assert_not_called()
    assert cfg.command == "npx"
    assert "--browser-url=http://127.0.0.1:9222" in cfg.args


async def test_ensure_chrome_running_remote_url_returns_none():
    with patch.dict(integ._chrome_managers, {}, clear=True), \
         patch.object(integ.ChromeManager, "start", AsyncMock()) as start:
        assert await integ.ensure_chrome_running("http://10.0.0.5:9222") is None
        assert integ._chrome_managers == {}
    start.assert_not_called()


async def test_ensure_chrome_running_local_reuses_manager():
    with patch.dict(integ._chrome_managers, {}, clear=True), \
         patch.object(integ.ChromeManager, "start", AsyncMock(return_value=True)) as start:
        m1 = await integ.ensure_chrome_running("http://127.0.0.1:9333", headless=True)
        m2 = await integ.ensure_chrome_running("http://localhost:9333")
        assert integ._chrome_managers == {9333: m1}
    assert m1 is m2
    assert m1.port == 9333
    assert start.await_count == 2
    start.assert_any_await(headless=True)


async def test_ensure_chrome_running_warns_when_start_fails(caplog):
    with patch.dict(integ._chrome_managers, {}, clear=True), \
         patch.object(integ.ChromeManager, "start", AsyncMock(return_value=False)), \
         caplog.at_level("WARNING", logger="MCPEnabledMixin"):
        manager = await integ.ensure_chrome_running("http://127.0.0.1:9444")
    assert manager is not None
    assert "9444" in caplog.text


class _Host(integ.MCPEnabledMixin):
    def __init__(self):
        self.add_mcp_server = AsyncMock(return_value=["click"])


@pytest.mark.parametrize(
    "kwargs,expected",
    [({}, 1), ({"ensure_running": False}, 0), ({"auto_connect": True}, 0)],
)
async def test_add_chrome_devtools_ensure_running(kwargs, expected):
    host = _Host()
    with patch.object(integ, "ensure_chrome_running", AsyncMock()) as ensure:
        tools = await host.add_chrome_devtools_mcp_server(
            browser_url="http://127.0.0.1:9222", headless=True, **kwargs
        )
    assert ensure.await_count == expected
    if expected:
        ensure.assert_awaited_once_with("http://127.0.0.1:9222", headless=True)
    host.add_mcp_server.assert_awaited_once()
    assert tools == ["click"]
    config = host.add_mcp_server.await_args.args[0]
    assert "ensure_running" not in str(config.args)


async def test_shutdown_awaits_stop():
    host = _Host()
    host.tool_manager = MagicMock(disconnect_all_mcp=AsyncMock())
    mgr = MagicMock()
    mgr.stop = AsyncMock()
    with patch.dict(integ._chrome_managers, {9222: mgr}, clear=True):
        await host.shutdown()
        mgr.stop.assert_awaited_once()
        assert integ._chrome_managers == {}
