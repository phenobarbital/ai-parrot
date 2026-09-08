# HOTFIX-chromemanager-async-migration-1: Async `ChromeManager` (aiohttp probe, asyncio subprocess)

**Feature**: hotfix `chromemanager-async-migration` (no Jira ticket — user decision 2026-09-05) — ChromeManager async migration (requests → aiohttp) *(hotfix — no `FEAT-<NNN>` reserved, FEAT-466)*
**Spec**: `sdd/specs/chromemanager-async-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`ChromeManager` (`packages/ai-parrot-server/src/parrot/mcp/chrome.py`) probes
for and launches a local Chrome with a remote-debugging port so
`chrome-devtools-mcp` can attach. It is fully blocking: `requests.get` for the
`/json/version` probe, `subprocess.run` + `subprocess.Popen` for the launch,
and up to ten `time.sleep(1)` calls for readiness. It is reached from the
async `MCPEnabledMixin.add_chrome_devtools_mcp_server()` hook, so
`WebAgent.configure()` can freeze the event loop for 10+ seconds (spec §1).
The project rules ban `requests`/`httpx` and blocking I/O in async code.

This task implements spec §3 Module 1: rewrite the class in place as an async
process supervisor with the same module path, class name, constructor and
attributes. Task 2 rewires the callers; do not touch `integration.py` here.

---

## Scope

- Rewrite `ChromeManager` in `packages/ai-parrot-server/src/parrot/mcp/chrome.py`:
  - Remove imports `requests`, `socket`, `subprocess`, `time`; add `asyncio`, `shutil`, `aiohttp`.
  - Keep `__init__(self, port: int = 9222, logger: logging.Logger | None = None)` and attributes `port`, `logger`, `process` (now `asyncio.subprocess.Process | None`).
  - Add `async def is_running(self) -> bool`: `aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.0))`, GET `http://127.0.0.1:{port}/json/version`, `True` iff status 200; catch `(aiohttp.ClientError, asyncio.TimeoutError, OSError)` → `False`.
  - Add `async def is_chrome_running(self) -> bool`: deprecated alias; emits `DeprecationWarning` via `warnings.warn(..., stacklevel=2)` and returns `await self.is_running()`.
  - Add `async def start(self, headless: bool = True, timeout: float = 10.0) -> bool`: return `True` early if running; discover the binary once with `shutil.which` over `("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")`, warn and fall back to `"google-chrome"` when none found; spawn with `asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)`; poll `is_running()` every 0.5 s with `asyncio.sleep` until `timeout` (use `loop.time()` deadline); log error and return `False` on timeout; any spawn exception → log error, return `False` (never raise — same contract as today).
  - Launch flags unchanged: `--remote-debugging-port={port}`, `--disable-gpu`, `--no-sandbox`, `--disable-dev-shm-usage`, `--remote-allow-origins=*`, plus `--headless=new` (inserted right after the binary) when `headless`.
  - Add `async def stop(self) -> None`: if `process` set → `terminate()`, `await asyncio.wait_for(process.wait(), 5)`, on `asyncio.TimeoutError` → `kill()`; always set `self.process = None`.
  - Delete `is_port_open()` and the module-level `shutil_which()`; delete the dead `chrome_bins`/`chrome_bin` block.
  - Google-style docstrings, full type hints, `self.logger` with `%s` formatting.
- Write `tests/mcp/test_chrome_manager.py` covering Module 1 (see Test Specification). Task 2 appends the Module 2 tests to the same file.

**NOT in scope**: any change to `packages/ai-parrot/src/parrot/mcp/integration.py` (callers still invoke the old sync API until task 2 — the two must land in the same worktree, sequentially). No dependency changes. No edits under `packages/*/build/lib/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/chrome.py` | MODIFY (rewrite) | async `ChromeManager` |
| `tests/mcp/test_chrome_manager.py` | CREATE | Module 1 unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-05 on `dev` `b53df1006`; `chrome.py` is byte-identical on `main`.

### Verified Imports
```python
from parrot.mcp.chrome import ChromeManager   # packages/ai-parrot-server/src/parrot/mcp/chrome.py:9
import aiohttp                                 # core dependency (packages/ai-parrot/pyproject.toml:804 comment: "already a core dependency")
import asyncio, shutil, warnings, logging      # stdlib
```
`parrot.mcp` is a split namespace: `parrot.mcp.__path__` = core `packages/ai-parrot/src/parrot/mcp` **and** server `packages/ai-parrot-server/src/parrot/mcp`. `chrome.py` exists only in the server package (`importlib.util.find_spec("parrot.mcp.chrome").origin` verified). Edit that file.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/chrome.py (135 lines, current)
import requests                                               # line 6   ← remove
class ChromeManager:                                          # line 9
    def __init__(self, port: int = 9222, logger: logging.Logger | None = None)   # line 12
    self.port / self.logger / self.process = None             # lines 13-15 (keep names)
    def is_port_open(self, host: str, port: int) -> bool      # line 17   ← delete
    def is_chrome_running(self) -> bool                       # line 23   (requests.get line 29) ← async alias
    def start(self, headless: bool = True) -> bool            # line 34   (dead chrome_bins 54-70; cmd 74-83; subprocess.run 88; Popen 101-106; sleep loop 108-113)
    def stop(self)                                            # line 122  (terminate 127, wait(timeout=5) 129, kill 131)
def shutil_which(pgm)                                         # line 133  ← delete

# Precedents to copy
# aiohttp timeout:      packages/ai-parrot/src/parrot/a2a/mesh.py:1008   aiohttp.ClientTimeout(total=...)
# asyncio subprocess:   packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:715-727
```

### Does NOT Exist
- ~~`packages/ai-parrot/src/parrot/mcp/chrome.py`~~ — only the server package has it.
- ~~`parrot.mcp.ChromeManager`~~ — not re-exported from `parrot/mcp/__init__.py`.
- ~~`parrot/mcp/transports/http.py`~~ — no such file.
- ~~`aioresponses`~~ — not a verified test dependency; mock `aiohttp.ClientSession` with `unittest.mock.patch` or patch `ChromeManager.is_running`.
- ~~`httpx`~~ — not a dependency; banned by `.agent/CONTEXT.md`.
- No existing tests for `ChromeManager`; `tests/unit/test_mcp_validator.py:64` only stubs the name.

---

## Implementation Notes

### Pattern to Follow
```python
async def is_running(self) -> bool:
    url = f"http://127.0.0.1:{self.port}/json/version"
    timeout = aiohttp.ClientTimeout(total=1.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return resp.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return False
```
Readiness loop: `deadline = asyncio.get_running_loop().time() + timeout` … `await asyncio.sleep(0.5)`.

### Key Constraints
- No blocking call anywhere in the module (`test_start_does_not_block_loop` enforces it).
- Never raise from `start()`/`stop()`; log and return.
- `pytest.ini:3` sets `asyncio_mode = auto`, so plain `async def test_*` functions run without a marker (root `pyproject.toml:211` adds `--strict-markers`; do not invent markers).

### References in Codebase
- `packages/ai-parrot/src/parrot/a2a/mesh.py:1008` — aiohttp health probe with `ClientTimeout`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:715` — `asyncio.create_subprocess_exec` usage.

---

## Acceptance Criteria

- [ ] `chrome.py` has no `import requests`, `import time`, `import subprocess`, `import socket` (asserted by `test_no_requests_import`).
- [ ] `is_running`, `is_chrome_running`, `start`, `stop` are coroutines; `is_chrome_running` warns `DeprecationWarning`.
- [ ] Probe uses `aiohttp.ClientTimeout(total=1.0)`; client errors and timeouts return `False`.
- [ ] `start()` honours `timeout`, spawns via `asyncio.create_subprocess_exec`, and never blocks the loop.
- [ ] `stop()` terminates, waits up to 5 s, then kills; `process` is reset to `None`.
- [ ] `pytest tests/mcp/test_chrome_manager.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/mcp/chrome.py` clean.
- [ ] `python -c "from parrot.mcp.chrome import ChromeManager"` works.

---

## Test Specification

```python
# tests/mcp/test_chrome_manager.py  (Module 1 part)
import asyncio, inspect
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
    proc = MagicMock(); proc.returncode = None
    proc.wait = AsyncMock(); proc.terminate = MagicMock(); proc.kill = MagicMock()
    return proc


def test_no_requests_import():
    src = inspect.getsource(chrome_mod)
    assert "import requests" not in src and "time.sleep" not in src and "subprocess." not in src.replace("asyncio.subprocess.", "")


async def test_is_running_true_on_200(manager):
    resp = MagicMock(status=200)
    cm = MagicMock(); cm.__aenter__ = AsyncMock(return_value=resp); cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock(); session.get = MagicMock(return_value=cm)
    session.__aenter__ = AsyncMock(return_value=session); session.__aexit__ = AsyncMock(return_value=False)
    with patch("parrot.mcp.chrome.aiohttp.ClientSession", return_value=session):
        assert await manager.is_running() is True


async def test_is_running_false_on_connection_error(manager):
    with patch("parrot.mcp.chrome.aiohttp.ClientSession", side_effect=aiohttp.ClientConnectionError()):
        assert await manager.is_running() is False


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


async def test_start_times_out(manager, fake_proc):
    with patch.object(manager, "is_running", AsyncMock(return_value=False)), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        assert await manager.start(timeout=0.2) is False


async def test_start_does_not_block_loop(manager, fake_proc):
    ticks = 0
    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05); ticks += 1
    t = asyncio.create_task(ticker())
    with patch.object(manager, "is_running", AsyncMock(return_value=False)), \
         patch("parrot.mcp.chrome.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        await manager.start(timeout=0.5)
    t.cancel()
    assert ticks >= 5


async def test_stop_terminates_then_kills(manager, fake_proc):
    async def hang(): await asyncio.sleep(60)
    fake_proc.wait = hang
    manager.process = fake_proc
    with patch("parrot.mcp.chrome.asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)):
        await manager.stop()
    fake_proc.terminate.assert_called_once(); fake_proc.kill.assert_called_once()
    assert manager.process is None
```

---

## Agent Instructions

1. Read the spec (§1, §2, §3 Module 1, §6, §7).
2. Verify every line in the Codebase Contract against the worktree (`origin/main` base) before editing.
3. Implement, run `pytest tests/mcp/test_chrome_manager.py -v` and `ruff check`.
4. Update the per-spec index `sdd/tasks/index/chromemanager-async-migration.json` → `in-progress`, then `done`; move this file to `sdd/tasks/completed/`.
5. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-05
**Notes**: Rewrote `ChromeManager` in place exactly per spec §3 Module 1:
removed `requests`/`socket`/`subprocess`/`time` imports, added
`asyncio`/`shutil`/`aiohttp`/`warnings`; `is_running()` uses
`aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.0))` against
`/json/version`, catching `(aiohttp.ClientError, asyncio.TimeoutError,
OSError)`; `is_chrome_running()` is now a coroutine that emits
`DeprecationWarning(stacklevel=2)` and delegates to `is_running()`;
`start(headless=True, timeout=10.0)` discovers the binary once via
`shutil.which` over the same candidate list, falls back to
`"google-chrome"` with a warning, spawns with
`asyncio.create_subprocess_exec(..., start_new_session=True)`, and polls
`is_running()` every 0.5s against a `loop.time()` deadline; never raises
(broad `except Exception` returns `False`, same contract as before);
`stop()` awaits `asyncio.wait_for(process.wait(), 5)`, kills on
`asyncio.TimeoutError`, and always resets `self.process = None`. Deleted
`is_port_open()` and the module-level `shutil_which()` and the dead
`chrome_bins`/`chrome_bin` block. `integration.py` was NOT touched (task 2
scope).

Created `tests/mcp/test_chrome_manager.py` with the 8 tests from the task's
Test Specification verbatim, plus 4 extra tests for coverage the spec's
acceptance criteria call for but the scaffold didn't enumerate explicitly
(`is_chrome_running` deprecation warning + delegation, binary-not-found
fallback to `"google-chrome"`, spawn-exception → `False`, `stop()` no-op
when `process` is `None`) — 12 tests total, all passing.

Real test results observed (see
`artifacts/logs/chromemanager-async-migration/task1-pytest.log`):
- `pytest tests/mcp/test_chrome_manager.py -v` → **12 passed in 1.37s**
- `pytest tests/unit/test_mcp_validator.py -q` → **12 passed in 0.30s**
- `ruff check packages/ai-parrot-server/src/parrot/mcp/chrome.py` → **All checks passed!**
- Coroutine check (`ChromeManager.start/stop/is_running/is_chrome_running`
  all `inspect.iscoroutinefunction() == True`) → **OK**, run with
  `PYTHONPATH=packages/ai-parrot-server/src` explicitly prepended — the
  shared venv's editable install for `ai-parrot-server` resolves
  `parrot.mcp.chrome` to the main-repo checkout
  (`/home/jesuslara/proyectos/ai-parrot/packages/...`) rather than this
  worktree when invoked as a bare `python -c` with no test-collection
  conftest in play; the repo's own root `conftest.py` documents and
  corrects exactly this precedence for the `pytest` invocations above, so
  both pytest runs picked up the worktree's rewritten file correctly
  without any workaround.

**Deviations from spec**: none in the implementation. Added 4 extra unit
tests beyond the task's minimal scaffold (noted above) to directly cover
acceptance criteria (deprecation warning, binary-fallback logging,
never-raise contract, stop() no-op) that the scaffold didn't test but the
Acceptance Criteria section requires.
