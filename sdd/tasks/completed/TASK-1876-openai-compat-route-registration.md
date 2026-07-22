# TASK-1876: Register OpenAI-compat routes in manager + integration test

**Feature**: FEAT-247 — LiveAvatar FULL Mode Custom LLM
**Spec**: `sdd/specs/liveavatar-full-mode-custom-llm.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1874, TASK-1875
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The OpenAI-compat endpoint (TASK-1874) and the start-flow
wiring (TASK-1875) are built but not registered in the aiohttp router. This
task wires them into `manager.py` alongside the existing FULL mode routes and
adds an integration test that exercises the full round-trip using the `openai`
Python SDK.

---

## Scope

- Modify `manager/manager.py` to call `register_openai_compat_routes(router)`
  after the existing `_register_fullmode_avatar_routes(router)` call
- The OpenAI-compat routes should be guarded by the same defensive import
  pattern (try/except ImportError) as the fullmode routes
- Add an integration test that points the `openai` Python SDK at the
  per-session URL and verifies streaming works end-to-end

**NOT in scope**: the endpoint implementation (TASK-1874), the start response
modification (TASK-1875).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Register openai_compat routes (~line 1842) |
| `packages/ai-parrot-server/tests/handlers/test_openai_compat.py` | MODIFY | Add SDK integration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# manager/manager.py:1621-1623 — existing fullmode route registration pattern
from ..handlers.avatar_fullmode import (
    close_all_fullmode_sessions,
    register_fullmode_routes,
)

# To add:
from ..handlers.openai_compat import register_openai_compat_routes
```

### Existing Signatures to Use
```python
# manager/manager.py:1606
def _register_fullmode_avatar_routes(self, router) -> bool:
    # line 1621-1633: try/except ImportError, call register_fullmode_routes(router)

# manager/manager.py:1839-1842 — where routes are registered in setup:
#   # FULL mode avatar routes (FEAT-248)
#   self._register_fullmode_avatar_routes(router)

# handlers/openai_compat.py (created by TASK-1874):
def register_openai_compat_routes(router) -> bool: ...
```

### Does NOT Exist
- ~~OpenAI-compat route registration in manager.py~~ — this task adds it
- ~~`_register_openai_compat_routes` method on BotManager~~ — this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# manager/manager.py — add a method mirroring _register_fullmode_avatar_routes:
def _register_openai_compat_routes(self, router) -> bool:
    """Register OpenAI-compatible endpoints (FEAT-247)."""
    try:
        from ..handlers.openai_compat import register_openai_compat_routes
    except ImportError as exc:
        _logger.warning(
            "OpenAI-compat endpoints disabled (%s)", exc,
        )
        return False
    return register_openai_compat_routes(router)

# In setup(), after _register_fullmode_avatar_routes:
self._register_openai_compat_routes(router)
```

### Key Constraints
- Must not break existing route registration
- The `openai` SDK is a dev/test dependency only — do not add it to core deps
- Integration test should be marked with a pytest marker for optional deps
  (e.g. `@pytest.mark.skipif` if `openai` not installed)

---

## Acceptance Criteria

- [ ] OpenAI-compat routes registered in manager setup
- [ ] Routes guarded by defensive ImportError (graceful degradation)
- [ ] `openai` SDK pointed at the per-session URL can stream a completion (integration test)
- [ ] Existing FULL mode routes and all other routes unaffected
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_openai_compat.py
import pytest

openai = pytest.importorskip("openai")


class TestOpenAICompatIntegration:
    async def test_openai_sdk_streams_completion(self, aiohttp_client, fake_bot):
        """The openai Python SDK pointed at our URL streams a completion."""
        # Create aiohttp test app with routes registered
        # Point openai.AsyncOpenAI(base_url=...) at test server
        # Call client.chat.completions.create(stream=True)
        # Collect chunks, assert content matches fake_bot output
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/liveavatar-full-mode-custom-llm.spec.md`
2. **Check dependencies** — TASK-1874 and TASK-1875 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — re-read `manager.py:1606-1642` for the pattern
4. **Update status** in `sdd/tasks/index/liveavatar-full-mode-custom-llm.json` → `"in-progress"`
5. **Implement** the route registration + integration test
6. **Run full test suite**: `pytest packages/ai-parrot-server/tests/ -x -q`
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-07-23
**Notes**:
- Added `BotManager._register_openai_compat_routes(router)` mirroring the
  exact `_register_fullmode_avatar_routes` pattern (defensive `ImportError`
  guard, warning log on failure), and wired it into `setup()` right after
  `self._register_fullmode_avatar_routes(router)`.
- Integration test drives the real `openai` Python SDK against a real
  aiohttp test server (`aiohttp_client` fixture — genuine TCP socket, not
  mocked). Because LiveAvatar's Custom LLM posts directly to the minted
  per-session URL (`/v1/chat/completions/{session_id}`), which the SDK's
  high-level `chat.completions.create()` cannot target (it always appends
  a fixed `/chat/completions` suffix to `base_url`), the test uses the
  SDK's low-level `client.post(path, ..., stream_cls=AsyncStream[...])`
  escape hatch instead — this exercises the actual SDK SSE decoder against
  our endpoint, which is what makes it a genuine wire-format conformance
  check rather than a re-implementation of our own parsing.
- `openai` is already present in the dev venv (2.41.0) but is not declared
  as a project dependency; the test uses `pytest.importorskip("openai")`
  per the task's test spec so the suite skips gracefully wherever the
  optional SDK isn't installed.
- Verified no regressions: ran the full `ai-parrot-server` test suite
  (`--continue-on-collection-errors` to skip two pre-existing
  `fakeredis`-missing collection errors, unrelated to this feature). 4
  pre-existing failures (host-handlers stub-file check + 3 A2A vertical
  broker tests) reproduce identically on a clean stash of this branch —
  confirmed unrelated to FEAT-247. 551 passed, only the two known-missing
  `fakeredis` modules blocked collection (also pre-existing).
- `ruff check` clean on `manager.py` and the test file.

**Deviations from spec**: none
