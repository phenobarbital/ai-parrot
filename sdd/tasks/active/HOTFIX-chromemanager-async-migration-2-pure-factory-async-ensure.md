# HOTFIX-chromemanager-async-migration-2: Pure `create_chrome_devtools_mcp_server()` + async `ensure_chrome_running()` / `shutdown()`

**Feature**: hotfix `chromemanager-async-migration` (no Jira ticket — user decision 2026-09-05) — ChromeManager async migration (requests → aiohttp) *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/chromemanager-async-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-chromemanager-async-migration-1
**Assigned-to**: unassigned

---

## Context

After task 1, `ChromeManager.start()`/`stop()` are coroutines, but the callers
in `packages/ai-parrot/src/parrot/mcp/integration.py` still call them
synchronously: the **sync** config factory `create_chrome_devtools_mcp_server()`
starts Chrome as a side effect (lines 1158-1166) and `MCPEnabledMixin.shutdown()`
calls `manager.stop()` without awaiting (line 1849). This task implements spec
§3 Module 2: the factory becomes a pure config builder, the launch moves into
a new async helper called from the async mixin hook behind an
`ensure_running=True` keyword, and `shutdown()` awaits `stop()`. `WebAgent`
behaviour stays the same. It also fixes the test-hygiene defect where
`packages/ai-parrot/tests/bots/test_chrome.py:78-100` spawn Chrome during the
unit run.

---

## Scope

- In `packages/ai-parrot/src/parrot/mcp/integration.py`:
  - Delete the launch block in `create_chrome_devtools_mcp_server()` (lines 1158-1166) and the now-unused URL parsing (1139-1156). Keep the signature and every argument's effect on the rendered `args` list. Update the docstring: "This factory does not start Chrome; see `ensure_chrome_running()` / `MCPEnabledMixin.add_chrome_devtools_mcp_server(ensure_running=True)`."
  - Add module-level `async def ensure_chrome_running(browser_url: str, headless: bool = False) -> Optional[ChromeManager]`: parse with `urllib.parse.urlparse`; port from URL else 9222; local iff hostname in `("localhost", "127.0.0.1", "0.0.0.0", "::1")` (unparseable → treat as local, same as today); return `None` for non-local; get-or-create `_chrome_managers[port]`; `ok = await manager.start(headless=headless)`; if not `ok`, `logger.warning(...)` (do not raise — spec §8 keeps warn-and-continue); return the manager.
  - In `MCPEnabledMixin.add_chrome_devtools_mcp_server()` (line 1476) add `ensure_running: bool = True` after `auto_connect`; before `add_mcp_server(config)`: `if ensure_running and not auto_connect: await ensure_chrome_running(browser_url, headless=headless)`. Docstring updated.
  - In `MCPEnabledMixin.shutdown()` (line 1842): `await manager.stop()` inside the existing try/except; keep `_chrome_managers.clear()`.
- Append Module 2 tests to `tests/mcp/test_chrome_manager.py` and add the `ensure_running=False` integration test to `packages/ai-parrot/tests/bots/test_chrome.py`.

**NOT in scope**: `ChromeConfig` / `WebAgent.configure()` (unchanged); `chrome.py` (task 1); docs and changelog (task 3); the `requests` pin in `packages/ai-parrot/pyproject.toml:114`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | pure factory, `ensure_chrome_running`, `ensure_running` kwarg, async shutdown |
| `tests/mcp/test_chrome_manager.py` | MODIFY | append Module 2 tests |
| `packages/ai-parrot/tests/bots/test_chrome.py` | MODIFY | add `ensure_running=False` test |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-05 on `dev` `b53df1006`; `integration.py` and `bots/chrome.py` are byte-identical on `main`.

### Verified Imports
```python
from parrot.mcp.integration import create_chrome_devtools_mcp_server, MCPEnabledMixin, _chrome_managers  # lines 1105, 1341, 45
from parrot.mcp.chrome import ChromeManager          # integration.py:36 does `from .chrome import ChromeManager`
from parrot.bots.chrome import ChromeConfig, WebAgent # bots/chrome.py:15, 290
import asyncio                                        # already imported at integration.py:8
from urllib.parse import urlparse                     # currently imported locally at integration.py:1143; hoist to module level or keep local
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/integration.py
from .chrome import ChromeManager                                     # line 36  — keep; do NOT import any other name from .chrome
_chrome_managers: Dict[int, ChromeManager] = {}                       # line 45
def create_chrome_devtools_mcp_server(browser_url="http://127.0.0.1:9222", name="chrome-devtools", headless=False,
    user_data_dir=None, channel=None, viewport=None, executable_path=None, isolated=False,
    no_usage_statistics=True, auto_connect=False, **kwargs) -> MCPServerConfig      # line 1105
    #   urlparse/is_local: 1139-1156 ; launch block: 1158-1166 ; args build: 1168-1185 ; return MCPServerConfig(name, command="npx", args, transport="stdio", **kwargs): 1187-1192
class MCPEnabledMixin:                                                # line 1341
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]                   # line 1348
    async def add_chrome_devtools_mcp_server(self, browser_url=..., name=..., headless=False, ..., auto_connect=False, **kwargs) -> List[str]  # line 1476; factory call 1508-1519; `return await self.add_mcp_server(config)` 1520
    async def shutdown(self, **kwargs)                                # line 1842; `for port, manager in list(_chrome_managers.items()): manager.stop()` 1847-1853; `_chrome_managers.clear()` 1854

# packages/ai-parrot/src/parrot/bots/chrome.py
class ChromeConfig(BaseModel)   # line 15: browser_url, headless(False), user_data_dir, channel, viewport, executable_path, isolated, no_usage_statistics(True), auto_connect(False), port(9222)
class WebAgent(BasicAgent):     # line 290
    async def configure(self, app=None) -> None   # line 302; awaits self.add_chrome_devtools_mcp_server(browser_url=config.browser_url or f"http://127.0.0.1:{config.port}", headless=..., ..., auto_connect=config.auto_connect) at 308-322

# after task 1 (server package)
class ChromeManager: async def is_running(); async def start(headless=True, timeout=10.0) -> bool; async def stop() -> None

# tests
# tests/unit/test_mcp_validator.py:64  →  _mod.ChromeManager = MagicMock()   (loads integration.py from source with stubs; must keep passing → import ONLY ChromeManager from .chrome)
# packages/ai-parrot/tests/bots/test_chrome.py:15 imports create_chrome_devtools_mcp_server; 78-100 call it with defaults; 221-226 mock agent.add_chrome_devtools_mcp_server with AsyncMock
```

### Does NOT Exist
- ~~`ensure_chrome_running`~~, ~~`ensure_running=`~~ — introduced by this task.
- ~~`ChromeManager.is_chrome_running()` (sync)~~ — after task 1 it is an async deprecated alias; call `is_running()`.
- ~~`MCPEnabledMixin.remove_chrome_devtools_mcp_server`~~ — no such method.
- ~~`parrot.mcp.chrome.ensure_chrome_running`~~ — the helper lives in `integration.py`, not in the server package (keeps the validator stub valid).

---

## Implementation Notes

### Pattern to Follow
```python
async def ensure_chrome_running(browser_url: str, headless: bool = False) -> Optional[ChromeManager]:
    """Start (or reuse) the managed local Chrome behind *browser_url*. Returns None for non-local hosts."""
    port, is_local = 9222, True
    try:
        parsed = urlparse(browser_url)
        port = parsed.port or 9222
        is_local = (parsed.hostname or "localhost") in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    except Exception:
        is_local = True
    if not is_local:
        return None
    manager = _chrome_managers.setdefault(port, ChromeManager(port=port))
    if not await manager.start(headless=headless):
        logging.getLogger("MCPEnabledMixin").warning("Chrome on port %s did not become ready", port)
    return manager
```

### Key Constraints
- The factory must have **zero** side effects; the existing default-args tests must no longer touch `ChromeManager`.
- Keep `from .chrome import ChromeManager` as the only import from `.chrome`.
- `pytest.ini:3` sets `asyncio_mode = auto`; plain `async def test_*` functions run without a marker.

### References in Codebase
- `integration.py:1139-1166` — logic being moved (copy the host allow-list verbatim).
- `packages/ai-parrot/tests/bots/test_chrome.py:210-230` — mixin/agent mocking pattern.

---

## Acceptance Criteria

- [ ] `create_chrome_devtools_mcp_server()` never references `ChromeManager` or `_chrome_managers`.
- [ ] `ensure_chrome_running()` returns `None` for `http://10.0.0.5:9222` and leaves `_chrome_managers` untouched; for loopback it reuses the manager per port.
- [ ] `add_chrome_devtools_mcp_server(ensure_running=True, auto_connect=False)` awaits the helper before `add_mcp_server`; `ensure_running=False` or `auto_connect=True` skips it.
- [ ] `shutdown()` awaits `stop()` on every manager and clears the registry.
- [ ] `pytest tests/mcp/test_chrome_manager.py packages/ai-parrot/tests/bots/test_chrome.py tests/unit/test_mcp_validator.py -v` passes; the validator test file is unmodified.
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/integration.py` clean.

---

## Test Specification

```python
# tests/mcp/test_chrome_manager.py  (Module 2 part, appended)
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from parrot.mcp import integration as integ


def test_factory_has_no_side_effects():
    with patch.object(integ.ChromeManager, "start", AsyncMock()) as start, patch.dict(integ._chrome_managers, {}, clear=True):
        cfg = integ.create_chrome_devtools_mcp_server()
    start.assert_not_called()
    assert integ._chrome_managers == {} and cfg.command == "npx"


async def test_ensure_chrome_running_remote_url_returns_none():
    with patch.dict(integ._chrome_managers, {}, clear=True):
        assert await integ.ensure_chrome_running("http://10.0.0.5:9222") is None
        assert integ._chrome_managers == {}


async def test_ensure_chrome_running_local_reuses_manager():
    with patch.dict(integ._chrome_managers, {}, clear=True), \
         patch.object(integ.ChromeManager, "start", AsyncMock(return_value=True)) as start:
        m1 = await integ.ensure_chrome_running("http://127.0.0.1:9333", headless=True)
        m2 = await integ.ensure_chrome_running("http://localhost:9333")
    assert m1 is m2 and m1.port == 9333 and start.await_count == 2
    start.assert_any_await(headless=True)


class _Host(integ.MCPEnabledMixin):
    def __init__(self): self.add_mcp_server = AsyncMock(return_value=["click"])


@pytest.mark.parametrize("kwargs,expected", [({}, 1), ({"ensure_running": False}, 0), ({"auto_connect": True}, 0)])
async def test_add_chrome_devtools_ensure_running(kwargs, expected):
    host = _Host()
    with patch.object(integ, "ensure_chrome_running", AsyncMock()) as ensure:
        await host.add_chrome_devtools_mcp_server(browser_url="http://127.0.0.1:9222", headless=True, **kwargs)
    assert ensure.await_count == expected
    host.add_mcp_server.assert_awaited_once()


async def test_shutdown_awaits_stop():
    host = _Host(); host.tool_manager = MagicMock(disconnect_all_mcp=AsyncMock())
    mgr = MagicMock(); mgr.stop = AsyncMock()
    with patch.dict(integ._chrome_managers, {9222: mgr}, clear=True):
        await host.shutdown()
        mgr.stop.assert_awaited_once()
        assert integ._chrome_managers == {}
```
```python
# packages/ai-parrot/tests/bots/test_chrome.py (append)
async def test_webagent_configure_does_not_launch_when_ensure_running_false():
    # WebAgent.configure() is unchanged; this covers the mixin path with ensure_running=False
    from parrot.mcp import integration as integ
    agent = WebAgent.__new__(WebAgent)
    agent.add_mcp_server = AsyncMock(return_value=[])
    with patch.object(integ, "ensure_chrome_running", AsyncMock()) as ensure:
        await integ.MCPEnabledMixin.add_chrome_devtools_mcp_server(agent, ensure_running=False)
    ensure.assert_not_awaited()
```

---

## Agent Instructions

1. Confirm task 1 is in `sdd/tasks/completed/` and `ChromeManager.start` is a coroutine.
2. Verify the Codebase Contract line numbers in the worktree before editing.
3. Implement, run the three test targets above plus `ruff check`.
4. Update the per-spec index → `in-progress` / `done`; move this file to `sdd/tasks/completed/`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
