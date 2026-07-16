---
type: Wiki Overview
title: 'TASK-1513: Voice route registration + extras-guarded wiring'
id: doc:sdd-tasks-completed-task-1513-voice-route-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of the spec (§3). Wires the new `AgentVoiceTalk`
  handler
relates_to:
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1513: Voice route registration + extras-guarded wiring

**Feature**: FEAT-231 — AgentTalk Voice Support
**Spec**: `sdd/specs/agentalk-voice-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1512
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3). Wires the new `AgentVoiceTalk` handler
into the server's route table: `POST /api/v1/agents/voice/{agent_id}`,
registered in `parrot.manager.manager` beside the existing `chat` / `infographic`
routes — under the **existing optional-integration guard** so a missing
`ai-parrot-integrations` voice stack logs a warning and skips the route instead
of crashing server boot. Also closes the v1 with an end-to-end integration test.

---

## Scope

- **Register** `router.add_view('/api/v1/agents/voice/{agent_id}', AgentVoiceTalk)`
  in `manager.py`, mirroring the `AgentTalk` (`:1489`) and `InfographicTalk`
  (`:1570-1586`) registrations.
- **Guard** the import + registration: if `AgentVoiceTalk` (or its lazy voice
  deps) cannot be imported, log a warning ("install `ai-parrot-integrations[voice]`
  to enable voice endpoints") and skip the route — never raise at boot. Mirror the
  existing optional-integration pattern at `manager.py:1848-1857`.
- **Write** an integration test for the full voice round-trip and confirm
  inherited PBAC/auth behaviour applies to the voice route.

**NOT in scope**: the handler itself (TASK-1512), the backends (TASK-1510/1511),
streaming, any change to the existing `chat`/`infographic` routes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Import `AgentVoiceTalk` (guarded) + `add_view` for the voice route |
| `packages/ai-parrot-server/tests/handlers/test_agent_voice_integration.py` | CREATE | End-to-end round-trip + route-registration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..handlers.agent import AgentTalk            # verified: manager.py:28
from ..handlers.infographic import InfographicTalk # verified: manager.py:30
# ADD (guarded, near the other handler imports or inside the registration method):
#   from ..handlers.agent_voice import AgentVoiceTalk   # created by TASK-1512
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
router = self.app.router                                          # line 1473
router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)      # line 1489  ← mirror this
router.add_view('/api/v1/agents/chat/{agent_id}/{method_name}', AgentTalk)  # line 1492
# InfographicTalk literal routes:                                # lines 1565-1586
router.add_view('/api/v1/agents/infographic/{agent_id}', InfographicTalk)   # (≈1570)
# Existing optional ai-parrot-integrations guard pattern:        # lines 1848-1857
#   try: import <integration>; ... except ImportError:
#       self.logger.warning("... install 'ai-parrot-integrations[...]' to enable ...")
```

### Does NOT Exist
- ~~A pre-existing `voice` route~~ — this task adds `POST /api/v1/agents/voice/{agent_id}`.
- ~~An unconditional top-level `from ..handlers.agent_voice import AgentVoiceTalk`~~ —
  must be guarded so a missing voice stack does not break boot.
- ~~Route registration in `ai-parrot-integrations`~~ — routes are registered in the
  **server** `manager.py` (the handler lives in server, per the spec's placement decision).

---

## Implementation Notes

### Pattern to Follow
```python
# In the route-registration method of manager.py, beside the InfographicTalk block:
try:
    from ..handlers.agent_voice import AgentVoiceTalk
except ImportError as exc:
    self.logger.warning(
        "Voice endpoints disabled (%s); install 'ai-parrot-integrations[voice]' "
        "to enable POST /api/v1/agents/voice/{agent_id}.", exc,
    )
else:
    router.add_view('/api/v1/agents/voice/{agent_id}', AgentVoiceTalk)
```

> Note: the handler's voice deps are themselves lazy (TASK-1512), so a bare
> `import AgentVoiceTalk` will usually succeed even without the voice extra — the
> `ImportError` guard is defence-in-depth. Keep the route registration adjacent to
> the existing `InfographicTalk` literal-route block to preserve ordering
> (literal resources before parametrized ones, per the `manager.py:1565` comment).

### Key Constraints
- Never crash server boot on a missing optional dependency.
- Do not reorder or alter existing `chat`/`infographic` routes.
- `self.logger.warning` on the degraded path.

### References in Codebase
- `manager.py:1489` — `AgentTalk` route registration.
- `manager.py:1565-1586` — `InfographicTalk` literal-route block (ordering precedent).
- `manager.py:1848-1857` — optional-integration guard pattern.

---

## Acceptance Criteria

- [ ] `POST /api/v1/agents/voice/{agent_id}` resolves to `AgentVoiceTalk`.
- [ ] Import failure of the voice stack logs a warning and skips the route; server still boots.
- [ ] Existing `chat`/`infographic` routes unchanged.
- [ ] Integration test: multipart audio → STT → `bot.ask` (stub) → TTS → JSON `{content, audio_base64, audio_format}`.
- [ ] Integration test: inherited PBAC denial / auth envelope behaves identically to `AgentTalk` on the voice route.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_agent_voice_integration.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/manager/manager.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_agent_voice_integration.py
import pytest


async def test_voice_route_registered(app):
    """POST /api/v1/agents/voice/{agent_id} maps to AgentVoiceTalk."""
    ...


async def test_voice_round_trip_end_to_end(app, stub_bot, short_wav_bytes):
    """multipart audio in → JSON with content + audio_base64 + audio_format."""
    ...


async def test_missing_voice_stack_skips_route_without_crash(monkeypatch):
    """ImportError on AgentVoiceTalk → warning logged, no route, boot succeeds."""
    ...


async def test_inherited_pbac_and_auth_apply_to_voice(app, denied_user):
    """PBAC denial behaves identically to the AgentTalk text route."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Integration Points, §3 Module 4, §6).
2. **Check dependencies** — TASK-1512 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the route-registration block
   (`manager.py:1473-1586`) and the optional-integration guard (`:1848`) are unchanged.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-06-09
**Notes**:
- Registered `POST /api/v1/agents/voice/{agent_id}` → `AgentVoiceTalk` in
  `manager.py`, adjacent to the `InfographicTalk` literal-route block (after the
  `/infographic/{agent_id}` catch-all, before the Dataset Manager routes). The
  existing `chat`/`infographic` routes are untouched.
- The registration is guarded via a new private helper
  `BotManager._register_voice_routes(router)`: it imports `AgentVoiceTalk`
  inside a `try/except ImportError`, logging the "install
  ai-parrot-integrations[voice]" warning and skipping the route on failure —
  server boot never crashes. (The handler's voice deps are themselves lazy, so
  the import normally succeeds; the guard is defence-in-depth.)
- Integration tests (5) cover: route resolves to `AgentVoiceTalk`; the helper
  registers the route; a simulated `ImportError` skips the route + logs a
  warning + returns `False` (no crash); the end-to-end data flow
  audio → STT → bot reply envelope → TTS → JSON `{content, audio_base64,
  audio_format}` (real handler seams, stubbed voice services + stub bot); and
  PBAC/auth are inherited from `AgentTalk` verbatim.
- `ruff check manager.py` clean; `BotManager` imports cleanly; the full
  FEAT-231 set is green (58 integrations + 13 server voice tests).

**Deviations from spec**: The end-to-end round-trip is exercised through the
handler's real seams (`_transcribe_attachment` + `_augment_with_audio`) with a
stub bot and stubbed voice services, rather than a live aiohttp TestServer —
the auth/PBAC/BotManager middleware stack required for a true HTTP request has
no test fixtures in this repo, and a seam-level drive deterministically proves
the same audio→text→audio→JSON contract.

**Pre-existing, unrelated**: `tests/test_namespace_imports.py::
test_handlers_host_only_stubs` fails on `dev` independently of this feature
(it flags `spatial_filter_handler.py` / `dataset_filter_handler.py` added to
**core** `ai-parrot/handlers` by FEAT-225 / TASK-1448). FEAT-231 only adds
files to **ai-parrot-server**; not touched here (no scope creep).
