---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: hotfix
base_branch: main
---

# Feature Specification: ChromeManager async migration (requests → aiohttp)

**Jira**: TBD — *no `FEAT-<NNN>` reserved; a bugfix is not a feature (FEAT-466).
Fill in the issue key before creating the worktree.*
**Date**: 2026-09-05
**Author**: Jesus Lara
**Status**: draft
**Target version**: next patch of `ai-parrot` (0.29.x) and `ai-parrot-server` (0.28.x)
**Related**: FEAT-528 (`sdd/proposals/obscura-new-browser-headless.proposal.md`) — depends on this fix landing on `dev` via sync-down, but is a separate spec.

---

## 1. Motivation & Business Requirements

### Problem Statement

`ChromeManager` (`packages/ai-parrot-server/src/parrot/mcp/chrome.py`) is the
component that probes for, and if necessary launches, a local Chrome instance
with a remote-debugging port so that the Chrome DevTools MCP server can attach
to it. It is fully synchronous and blocking:

- it imports **`requests`** and calls `requests.get(".../json/version", timeout=1)`
  (lines 6, 29);
- it runs `subprocess.run(["google-chrome", "--version"], ...)` (line 88) and
  `subprocess.Popen(...)` (line 101);
- it polls readiness with up to ten `time.sleep(1)` calls (lines 109-111);
- `stop()` uses `process.wait(timeout=5)` (line 128).

The project rules (`.agent/CONTEXT.md`, "What NOT to Do") forbid `requests`
and `httpx` in favour of `aiohttp`, and forbid blocking I/O inside async code.
`ChromeManager` violates both, and the violation is reachable from an async
path: `MCPEnabledMixin.add_chrome_devtools_mcp_server()` (async,
`integration.py:1476`) calls the **synchronous** factory
`create_chrome_devtools_mcp_server()` (`integration.py:1105`), which calls
`ChromeManager.start()` (`integration.py:1166`) for every loopback
`browser_url` unless `auto_connect=True`. `WebAgent.configure()`
(`bots/chrome.py:308-322`) awaits that hook, so **an agent's `configure()` can
freeze the event loop for ~11 s or more** (1 s HTTP timeout, a blocking
`--version` subprocess, then ten 1 s sleeps) while Chrome comes up — or while
it fails to.

Two secondary defects live in the same code path and are fixed by the same
change:

1. **Implicit launch from a config builder.** `create_chrome_devtools_mcp_server()`
   is a pure `MCPServerConfig` factory by contract (it returns a config, has
   no async signature, and is imported directly by tests), yet it has the side
   effect of spawning a browser. `packages/ai-parrot/tests/bots/test_chrome.py:78-100`
   call it with default arguments and therefore try to launch Google Chrome
   on port 9222 during the unit-test run. FEAT-528 (Obscura) also needs this
   behaviour gone: with an Obscura endpoint configured but not yet listening,
   the factory currently starts Chrome on the same port instead of failing.
2. **Dead / inconsistent binary discovery.** `start()` builds a `chrome_bins`
   list and resolves `chrome_bin` via `shutil_which` (lines 54-70) but never
   uses the result; it then hardcodes `"google-chrome"` and re-discovers via a
   second, blocking `subprocess.run` (74-99). A module-level `shutil_which`
   wrapper at line 133 duplicates `shutil.which`.

### Goals

- Replace `requests` in `ChromeManager` with `aiohttp` and make every
  I/O-bearing method a coroutine (`is_running`, `start`, `stop`).
- Replace `subprocess.run`/`Popen` and `time.sleep` with
  `asyncio.create_subprocess_exec` and `asyncio.sleep` / `asyncio.wait_for`.
- Make `create_chrome_devtools_mcp_server()` a pure config builder with no
  process side effects.
- Move the "ensure Chrome is running" step to the async hook
  `MCPEnabledMixin.add_chrome_devtools_mcp_server()`, preserving today's
  default behaviour for agents (local URL + `auto_connect=False` ⇒ Chrome is
  started if absent).
- Make `MCPEnabledMixin.shutdown()` await the async `stop()`.
- Keep the module path, class name, constructor signature, and the
  `_chrome_managers` registry so existing imports and test stubs keep working.

### Non-Goals (explicitly out of scope)

- Adding Obscura support, `--ws-endpoint`, or any engine selection — that is
  FEAT-528.
- Removing the `requests>=2.33,<2.34` pin from `packages/ai-parrot/pyproject.toml`
  (line 114). It is kept for other transitive consumers; this spec only removes
  the import from `chrome.py`.
- Migrating to `httpx`. httpx does support `async`/`await`, but the project rule
  bans it alongside `requests`; aiohttp is already a core dependency and is the
  mandated client. Rejected by rule, not by capability.
- Changing `ChromeConfig` (`bots/chrome.py:15`) or the CLI flags rendered for
  `chrome-devtools-mcp`.
- Touching the stale copies under `packages/*/build/lib/` (build artefacts,
  not source).

---

## 2. Architectural Design

### Overview

`ChromeManager` becomes an async process supervisor with the same public
surface (constructor `(port=9222, logger=None)`, attributes `port`, `logger`,
`process`), but:

| Today (sync) | After (async) |
|---|---|
| `is_port_open(host, port) -> bool` (socket) | removed; the HTTP probe is sufficient and already implies the port is open |
| `is_chrome_running() -> bool` (`requests.get`) | `async is_running() -> bool` (`aiohttp` GET `/json/version`, `ClientTimeout(total=1.0)`); `is_chrome_running` kept as a deprecated alias coroutine for one release |
| `start(headless=True) -> bool` (`subprocess`, `time.sleep`) | `async start(headless=True, timeout=10.0) -> bool` (`shutil.which` discovery once, `asyncio.create_subprocess_exec`, `asyncio.sleep(0.5)` polling until `timeout`) |
| `stop()` (`process.wait(timeout=5)`) | `async stop()` (`terminate()`, `await asyncio.wait_for(process.wait(), 5)`, then `kill()`) |
| `shutil_which()` module helper | removed; use `shutil.which` directly |

Process ownership moves out of the sync factory:

- `create_chrome_devtools_mcp_server()` only builds and returns the
  `MCPServerConfig`. Its signature is unchanged; the `headless`,
  `auto_connect`, and `browser_url` parameters keep their meaning for the
  rendered CLI arguments.
- A new coroutine `ensure_chrome_running(browser_url, headless) -> ChromeManager | None`
  in `integration.py` encapsulates the former side effect: parse the URL,
  decide `is_local`, get-or-create the manager in `_chrome_managers`, and
  `await manager.start(headless=headless)`. It returns `None` for non-local
  URLs. It logs a warning (does not raise) when Chrome cannot be started, to
  match the current `start()` contract of returning `False`.
- `MCPEnabledMixin.add_chrome_devtools_mcp_server()` gains
  `ensure_running: bool = True` and calls
  `await ensure_chrome_running(...)` when `ensure_running and not auto_connect`
  **before** `add_mcp_server(config)`. Default behaviour for `WebAgent` is
  therefore unchanged; callers that manage the browser themselves pass
  `ensure_running=False`.
- `MCPEnabledMixin.shutdown()` awaits `manager.stop()`.

### Component Diagram

```
WebAgent.configure()                       (async, bots/chrome.py:302)
   └─▶ MCPEnabledMixin.add_chrome_devtools_mcp_server()   (async, integration.py:1476)
          ├─▶ create_chrome_devtools_mcp_server()          (sync, PURE — no side effects)
          ├─▶ ensure_chrome_running(browser_url, headless) (async, NEW)
          │      └─▶ _chrome_managers[port] : ChromeManager
          │             ├─ await is_running()   ── aiohttp GET /json/version
          │             └─ await start()        ── asyncio.create_subprocess_exec + asyncio.sleep
          └─▶ add_mcp_server(config)
MCPEnabledMixin.shutdown()  ──▶  await manager.stop()  ── terminate / wait_for / kill
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.mcp.chrome.ChromeManager` | rewritten in place | same module, class, constructor; methods become coroutines |
| `parrot.mcp.integration.create_chrome_devtools_mcp_server` | modified | side effect removed (lines 1158-1166 deleted) |
| `parrot.mcp.integration.ensure_chrome_running` | new | owns the `_chrome_managers` get-or-create + `await start()` |
| `parrot.mcp.integration.MCPEnabledMixin.add_chrome_devtools_mcp_server` | modified | new `ensure_running=True` kwarg; awaits the helper |
| `parrot.mcp.integration.MCPEnabledMixin.shutdown` | modified | `await manager.stop()` |
| `parrot.bots.chrome.WebAgent.configure` | unchanged | behaviour preserved through the hook default |
| `tests/unit/test_mcp_validator.py` | unchanged | it stubs `_mod.ChromeManager` only (line 64); the new helper lives in `integration.py`, so no new name is imported from `.chrome` |

### Data Models

No new Pydantic models. `MCPServerConfig` is unchanged.

### New Public Interfaces

```python
# packages/ai-parrot-server/src/parrot/mcp/chrome.py
class ChromeManager:
    def __init__(self, port: int = 9222, logger: logging.Logger | None = None) -> None: ...
    async def is_running(self) -> bool: ...            # aiohttp GET /json/version, 1 s total timeout
    async def is_chrome_running(self) -> bool: ...     # deprecated alias → is_running()
    async def start(self, headless: bool = True, timeout: float = 10.0) -> bool: ...
    async def stop(self) -> None: ...

# packages/ai-parrot/src/parrot/mcp/integration.py
async def ensure_chrome_running(
    browser_url: str, headless: bool = False
) -> ChromeManager | None: ...

class MCPEnabledMixin:
    async def add_chrome_devtools_mcp_server(
        self, browser_url: str = "http://127.0.0.1:9222", ..., auto_connect: bool = False,
        ensure_running: bool = True, **kwargs
    ) -> list[str]: ...
```

---

## 3. Module Breakdown

### Module 1: Async `ChromeManager`
- **Path**: `packages/ai-parrot-server/src/parrot/mcp/chrome.py`
- **Responsibility**: rewrite the class per §2. Remove the `requests`, `socket`,
  `subprocess`, and `time` imports; add `asyncio`, `shutil`, `aiohttp`. Binary
  discovery: iterate `("google-chrome", "google-chrome-stable", "chromium",
  "chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")`
  with `shutil.which` once; if none found, log a warning and fall back to
  `"google-chrome"` (today's behaviour). Launch flags unchanged
  (`--remote-debugging-port`, `--disable-gpu`, `--no-sandbox`,
  `--disable-dev-shm-usage`, `--remote-allow-origins=*`, `--headless=new` when
  headless). Keep `start_new_session=True`, `stdout`/`stderr` to `DEVNULL`.
- **Depends on**: nothing new (aiohttp is a core dependency).

### Module 2: Pure factory + async ensure/shutdown in `integration.py`
- **Path**: `packages/ai-parrot/src/parrot/mcp/integration.py`
- **Responsibility**: delete the launch block from
  `create_chrome_devtools_mcp_server` (lines 1143-1166, keeping URL parsing
  only if still needed — it is not, once the launch is gone); add
  `ensure_chrome_running()`; add `ensure_running` to
  `add_chrome_devtools_mcp_server` and call the helper; make `shutdown()`
  await `stop()`. Update the factory docstring: it no longer starts Chrome.
- **Depends on**: Module 1.

### Module 3: Tests
- **Paths**: `tests/mcp/test_chrome_manager.py` (new),
  `packages/ai-parrot/tests/bots/test_chrome.py` (extend).
- **Responsibility**: see §4.
- **Depends on**: Modules 1-2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_is_running_true_on_200` | 1 | `aiohttp` GET mocked to return 200 → `True` |
| `test_is_running_false_on_connection_error` | 1 | mocked `aiohttp.ClientConnectorError` / timeout → `False`, no exception |
| `test_start_returns_true_when_already_running` | 1 | `is_running` patched `True` → no subprocess spawned |
| `test_start_spawns_and_polls` | 1 | `asyncio.create_subprocess_exec` patched; `is_running` returns `False, False, True` → `True`; asserts `--remote-debugging-port=<port>` and `--headless=new` in argv |
| `test_start_times_out` | 1 | `is_running` always `False`, `timeout=0.2` → `False`, error logged |
| `test_start_does_not_block_loop` | 1 | run `start(timeout=0.5)` concurrently with a 50 ms ticker task; ticker must fire ≥ 5 times (proves no blocking sleep) |
| `test_stop_terminates_then_kills` | 1 | `process.wait` patched to hang → `terminate()` then `kill()` called |
| `test_no_requests_import` | 1 | `"requests" not in inspect.getsource(parrot.mcp.chrome)`; same for `time.sleep` and `subprocess.` |
| `test_factory_has_no_side_effects` | 2 | patch `ChromeManager.start` → `create_chrome_devtools_mcp_server()` with defaults never calls it |
| `test_add_chrome_devtools_ensures_running_by_default` | 2 | mixin with `add_mcp_server` mocked; `ensure_chrome_running` awaited once with `browser_url`/`headless` |
| `test_add_chrome_devtools_ensure_running_false` | 2 | helper not awaited |
| `test_add_chrome_devtools_auto_connect_skips_ensure` | 2 | `auto_connect=True` → helper not awaited |
| `test_ensure_chrome_running_remote_url_returns_none` | 2 | `http://10.0.0.5:9222` → `None`, registry untouched |
| `test_shutdown_awaits_stop` | 2 | manager in `_chrome_managers` with `stop = AsyncMock()` → awaited, registry cleared |

### Integration Tests

| Test | Description |
|---|---|
| `test_webagent_configure_does_not_launch_when_ensure_running_false` | `WebAgent` with `add_mcp_server` mocked and `ensure_running=False` threaded through — no `ChromeManager` interaction (extends existing `packages/ai-parrot/tests/bots/test_chrome.py:221-226` pattern) |
| *(manual, not CI)* | `WebAgent().configure()` against a real local Chrome: `configure()` returns, `/json/version` answers, `shutdown()` terminates the process |

### Test Data / Fixtures

```python
@pytest.fixture
def manager():
    from parrot.mcp.chrome import ChromeManager
    return ChromeManager(port=9555)

@pytest.fixture
def fake_proc():
    proc = MagicMock()
    proc.returncode = None
    proc.wait = AsyncMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc
```

Existing tests that must keep passing unchanged: `tests/unit/test_mcp_validator.py`
(stubs `ChromeManager` at line 64) and
`packages/ai-parrot/tests/bots/test_chrome.py:78-100` (factory arg rendering —
these become side-effect-free as a consequence of Module 2).

---

## 5. Acceptance Criteria

- [ ] `packages/ai-parrot-server/src/parrot/mcp/chrome.py` contains no `import requests`, no `import time`, no `import subprocess`, no `import socket`.
- [ ] `ChromeManager.is_running`, `.start`, `.stop` are coroutines; `is_chrome_running` is a coroutine alias that logs a `DeprecationWarning`.
- [ ] The HTTP probe uses `aiohttp.ClientSession` with `aiohttp.ClientTimeout(total=1.0)` and treats any `aiohttp.ClientError` / `asyncio.TimeoutError` as "not running".
- [ ] `start()` uses `asyncio.create_subprocess_exec` and `asyncio.sleep`; readiness polling respects the `timeout` argument; no blocking calls remain (verified by `test_start_does_not_block_loop`).
- [ ] `create_chrome_devtools_mcp_server()` never instantiates or starts a `ChromeManager`; calling it with default arguments in the test suite spawns no process.
- [ ] `MCPEnabledMixin.add_chrome_devtools_mcp_server()` accepts `ensure_running: bool = True` and, when `True` and `auto_connect` is `False`, awaits `ensure_chrome_running()` before `add_mcp_server()`.
- [ ] `ensure_chrome_running()` returns `None` for non-loopback hosts and reuses `_chrome_managers[port]` for loopback hosts.
- [ ] `MCPEnabledMixin.shutdown()` awaits `stop()` on every registered manager and clears the registry.
- [ ] `WebAgent.configure()` behaviour is unchanged for default `ChromeConfig` (Chrome is started if absent, headless per config).
- [ ] `tests/unit/test_mcp_validator.py` passes without modification.
- [ ] All new tests in §4 pass: `pytest tests/mcp/test_chrome_manager.py packages/ai-parrot/tests/bots/test_chrome.py -v`.
- [ ] Full suite unaffected: `pytest tests/mcp tests/unit packages/ai-parrot/tests/bots -q`.
- [ ] No new dependency added to any `pyproject.toml`.
- [ ] The Jira key replaces `TBD` in this document before the hotfix worktree is created.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-09-05 on `dev` (`b53df1006`); the three source files are
> byte-identical on `main` (`git diff --stat main dev -- <files>` is empty),
> so line numbers hold for the hotfix worktree.

### Package split (read first)

`parrot.mcp` is a **split namespace**: `parrot.mcp.__path__` resolves to both
`packages/ai-parrot/src/parrot/mcp` (core, owns `__init__.py`,
`integration.py`) and `packages/ai-parrot-server/src/parrot/mcp` (server,
owns `chrome.py`). Verified: `importlib.util.find_spec("parrot.mcp.chrome").origin`
→ `packages/ai-parrot-server/src/parrot/mcp/chrome.py`. Module 1 edits the
server package; Module 2 edits core. The relative import
`from .chrome import ChromeManager` at `integration.py:36` therefore crosses
distributions and must keep working.

### Verified Imports

```python
from parrot.mcp.chrome import ChromeManager            # server: packages/ai-parrot-server/src/parrot/mcp/chrome.py:9
from parrot.mcp.integration import (                    # core: packages/ai-parrot/src/parrot/mcp/integration.py
    create_chrome_devtools_mcp_server,                  # line 1105
    MCPEnabledMixin,                                    # line 1341
    _chrome_managers,                                   # line 45  (Dict[int, ChromeManager])
)
from parrot.bots.chrome import ChromeConfig, WebAgent   # packages/ai-parrot/src/parrot/bots/chrome.py:15, 290
import aiohttp                                          # core dependency (pyproject.toml comment line 804: "already a core dependency")
import asyncio                                          # already imported in integration.py:8
```

### Existing Class Signatures

```python
# packages/ai-parrot-server/src/parrot/mcp/chrome.py  (135 lines)
import requests                                                      # line 6  ← REMOVE
class ChromeManager:                                                  # line 9
    def __init__(self, port: int = 9222, logger: logging.Logger | None = None)  # line 12
    port: int; logger: logging.Logger; process: subprocess.Popen | None        # lines 13-15
    def is_port_open(self, host: str, port: int) -> bool              # line 17  (socket)      ← REMOVE
    def is_chrome_running(self) -> bool                               # line 23  (requests.get line 29) ← becomes async alias
    def start(self, headless: bool = True) -> bool                    # line 34  (subprocess.run 88, Popen 101, time.sleep 110)
    def stop(self)                                                    # line 122 (process.wait(timeout=5) line 128)
def shutil_which(pgm)                                                 # line 133 ← REMOVE

# packages/ai-parrot/src/parrot/mcp/integration.py
from .chrome import ChromeManager                                     # line 36
_chrome_managers: Dict[int, ChromeManager] = {}                       # line 45
def create_chrome_devtools_mcp_server(                                # line 1105
    browser_url: str = "http://127.0.0.1:9222", name: str = "chrome-devtools",
    headless: bool = False, user_data_dir=None, channel=None, viewport=None,
    executable_path=None, isolated: bool = False, no_usage_statistics: bool = True,
    auto_connect: bool = False, **kwargs) -> MCPServerConfig
    # URL parse + is_local: lines 1139-1156; launch block: 1158-1166; args: 1168-1185; return: 1187-1192
class MCPEnabledMixin:                                                # line 1341
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]      # line 1348
    async def add_chrome_devtools_mcp_server(self, browser_url=..., ..., auto_connect=False, **kwargs) -> List[str]  # line 1476; calls factory at 1508, add_mcp_server at 1520
    async def shutdown(self, **kwargs)                                # line 1842; sync manager.stop() loop at 1847-1853

# packages/ai-parrot/src/parrot/bots/chrome.py
class ChromeConfig(BaseModel)                                         # line 15  (browser_url, headless, ..., auto_connect, port)
class WebAgent(BasicAgent):                                           # line 290
    async def configure(self, app=None) -> None                       # line 302; awaits add_chrome_devtools_mcp_server at 308-322
```

### Integration Points

| New / Changed | Connects To | Via | Verified At |
|---|---|---|---|
| `ChromeManager.is_running()` | Chrome `/json/version` | `aiohttp.ClientSession.get` | pattern: `parrot/a2a/mesh.py:1008` (`ClientTimeout(total=...)`) |
| `ChromeManager.start()` | Chrome binary | `asyncio.create_subprocess_exec` | pattern: `parrot/flows/dev_loop/nodes/qa.py:715-727` |
| `ensure_chrome_running()` | `_chrome_managers` | dict get-or-create | `integration.py:45, 1161-1165` |
| `add_chrome_devtools_mcp_server()` | `ensure_chrome_running()` | `await` before `add_mcp_server` | `integration.py:1508-1520` |
| `shutdown()` | `ChromeManager.stop()` | `await` | `integration.py:1847-1853` |
| `test_mcp_validator.py` | `integration.py` | stubs `_mod.ChromeManager` | `tests/unit/test_mcp_validator.py:64` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/mcp/transports/http.py`~~ — no such file; do not look there for an aiohttp precedent.
- ~~`packages/ai-parrot/src/parrot/mcp/chrome.py`~~ — `chrome.py` lives only in **ai-parrot-server**.
- ~~`parrot.mcp.ChromeManager`~~ — not re-exported from `parrot/mcp/__init__.py`; import from `parrot.mcp.chrome`.
- ~~`ChromeManager.is_running()`~~, ~~`ensure_chrome_running()`~~, ~~`ensure_running=`~~ — do not exist yet; this spec introduces them.
- ~~`aioresponses`~~ — not verified as a test dependency; mock `aiohttp.ClientSession` with `unittest.mock` or patch `ChromeManager.is_running` instead.
- ~~`httpx`~~ — not a dependency and banned by project rule.
- No existing tests exercise `ChromeManager` directly (only the stub at `test_mcp_validator.py:64`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- aiohttp probe: `async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.0)) as s: async with s.get(url) as r: return r.status == 200`, catching `(aiohttp.ClientError, asyncio.TimeoutError, OSError)` → `False`. Precedent: `parrot/a2a/mesh.py:1008`.
- Subprocess: `asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)`. Precedent: `parrot/flows/dev_loop/nodes/qa.py:715`.
- Readiness loop: `deadline = loop.time() + timeout; while loop.time() < deadline: if await self.is_running(): return True; await asyncio.sleep(0.5)`.
- Stop: `terminate()`; `await asyncio.wait_for(proc.wait(), 5)`; on `asyncio.TimeoutError` → `kill()`; always set `self.process = None`.
- Logging via `self.logger` with `%s` formatting; no f-strings in log calls.
- Google-style docstrings and full type hints on every method (project rule).

### Known Risks / Gotchas
- **Behaviour change for direct factory callers.** Anyone calling
  `create_chrome_devtools_mcp_server()` and then `add_mcp_server()` themselves
  (not through the mixin hook) no longer gets Chrome auto-started. Grep found
  no such caller in the repo besides tests; document in the factory docstring
  and the changelog.
- **`is_port_open` removal.** It was only used inside `is_chrome_running`; no
  external caller (grep verified). If a bare TCP probe is still wanted, use
  `asyncio.open_connection` — do not reintroduce `socket` blocking calls.
- **Detached process + `stop()`.** `start_new_session=True` keeps Chrome alive
  if the parent dies; `shutdown()` remains the only cleanup path, as today.
- **Hotfix base.** Branch from `origin/main`, never `HEAD`/`dev`. The three
  files are identical on both branches, so no `dev`-only symbol may be
  assumed; in particular do not import anything added to `integration.py` on
  `dev` after `main`'s tag.
- **Sync-down.** After the hotfix PR merges to `main`, `sync-down.yml` (or
  `/sdd-done --sync-down`) must carry it to `dev` before FEAT-528 starts, since
  FEAT-528's process manager builds on the async `ChromeManager`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | already pinned by core | replaces `requests` for the `/json/version` probe |
| *(none added)* | | `requests` pin in core stays for unrelated transitive consumers |

---

## 8. Open Questions

- [x] **aiohttp or httpx?** — *Resolved (project rule, `.agent/CONTEXT.md`)*: aiohttp. httpx is async-capable but banned alongside `requests`; no exception is requested here.
- [x] **Where does the launch side effect go?** — *Resolved (design)*: into the async mixin hook via `ensure_chrome_running()`, gated by a new `ensure_running=True` kwarg so `WebAgent` defaults are unchanged.
- [x] **Keep `is_chrome_running` name?** — *Resolved*: keep as a deprecated coroutine alias for one release; primary name is `is_running`.
- [ ] Jira key for this hotfix — *Owner: Jesus Lara*. Replace `TBD` in the header and in the worktree/branch names.
- [ ] Should `ensure_chrome_running()` raise instead of warn when Chrome cannot be started? Today `start()` returns `False` and the MCP connection then fails later with a less clear error. Decide during implementation; default is to keep the warn-and-continue contract.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — three modules, one worktree, sequential (Module 2 depends on Module 1; Module 3 on both). One or two commits; `/sdd-task` is not required (FEAT-466 hotfix path).
- **Cross-feature dependencies**: none upstream. Downstream, FEAT-528 (Obscura) waits for this to reach `dev` via sync-down.
- **Worktree creation** (hotfix — from `origin/main`, never `HEAD`/`dev`):
  ```bash
  git worktree add -b hotfix-<KEY>-chromemanager-async-migration \
    .claude/worktrees/hotfix-<KEY>-chromemanager-async-migration origin/main
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-05 | Jesus Lara | Initial draft (split out of the FEAT-528 review; hotfix, no FEAT id) |
