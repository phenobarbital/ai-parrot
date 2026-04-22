# TASK-799: Audit GeminiLiveClient — document cross-loop constraints

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-795
**Assigned-to**: unassigned

---

## Context

`GeminiLiveClient` owns a WebSocket-based LiveConnect session that is created
per-interaction and **cannot be migrated across event loops**. The per-loop
cache in TASK-795 still works for this client because every LiveConnect call
site enters the wrapper via `async with` on a single loop — but this
constraint must be surfaced to future authors so nobody tries to share a Live
wrapper across background tasks.

See spec §3 (Module 4) and §2 Integration Points (GeminiLiveClient row).

---

## Scope

Modify `packages/ai-parrot/src/parrot/clients/live.py` — docstring + small
safety audit, no structural change.

- Update the `GeminiLiveClient` class docstring (line 467) to add a
  "Cross-loop reuse" section that states:
  1. The base `AbstractClient._ensure_client` cache is used, so reusing the
     wrapper from multiple loops will build multiple `genai.Client` instances
     — which is fine for the setup client but...
  2. The **LiveConnect WebSocket session** is opened via `async with` inside
     a single loop's body. That session must not be passed across loops.
  3. `close()` (now inherited from the base) must be awaited on a loop where
     at least one entry was built; dropping references for other loops is
     safe because LiveConnect sessions are short-lived.
- Verify (via grep) that `GeminiLiveClient.get_client()` does NOT write to
  `self.client`. If any `self.client = ...` write exists, remove it (same
  pattern as TASK-797 / TASK-798). Expected outcome: no code changes needed,
  `get_client()` already returns a fresh `genai.Client`.
- Verify no `_client_loop_id` / `_current_loop_id` references exist in this
  file (they should not — those were Google-only interim hacks).
- If any `"Client not initialized"` guard exists in a public method, migrate
  it to `await self._ensure_client()` per the TASK-798 pattern. Confirm via
  grep first.

**NOT in scope**:
- Any change to LiveConnect / WebSocket session handling.
- Adding cross-loop session handoff (spec §8 Q6: separate future spec).
- Changes to `get_client()` construction logic beyond removing any
  `self.client =` writes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/live.py` | MODIFY | Add "Cross-loop reuse" section to `GeminiLiveClient` class docstring; remove any `self.client =` write if present (audit); migrate any "Client not initialized" guard to `await self._ensure_client()` if present. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/clients/live.py — already imports:
from google import genai                                        # verified
from parrot.clients.base import AbstractClient                  # verified (subclass)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/live.py

class GeminiLiveClient(AbstractClient):                         # line 467
    client_type: str = 'google_live'                            # line 495
    client_name: str = 'google_live'                            # line 496
    _default_model: str = GoogleVoiceModel.DEFAULT.value        # line 497

    def __init__(self, model=None, api_key=None, vertexai=False, ..., **kwargs):  # line 499
        super().__init__(model=..., conversation_memory=..., ..., **kwargs)  # line 545

    async def get_client(self) -> genai.Client:                 # line 577
        # Returns a genai.Client configured for live/voice endpoints.
        # Does NOT assign to self.client in the current code.
```

### Does NOT Exist

- ~~`GeminiLiveClient._client_loop_id`~~ — never existed; only `GoogleGenAIClient` had this (and TASK-796 removes it).
- ~~`GeminiLiveClient.per_loop_websocket_handoff()`~~ — future spec (§8 Q6).
- ~~`GeminiLiveClient.use_session = True`~~ — verified no `use_session=True` anywhere in `parrot/clients/`.

---

## Implementation Notes

### Docstring Addition

Append this block (well-indented) to the existing `GeminiLiveClient`
class docstring, before the `Usage:` section:

```
Cross-loop reuse:
    The base per-loop cache (``AbstractClient._ensure_client``) transparently
    builds a new ``genai.Client`` for each event loop this wrapper is used
    from. That cache is safe for the setup client.

    The LiveConnect WebSocket session, however, is created inside the
    ``async with`` body of a specific call and **cannot be migrated to a
    different loop**. Always open LiveConnect (and consume its stream) on
    a single loop. Do not attempt to resume a Live session from a
    background task running on a fresh loop — use a new session instead.

    ``close()`` is inherited from ``AbstractClient`` and tears down every
    cached ``genai.Client``. Entries whose owning loop is no longer
    running are dropped without awaiting.
```

### Key Constraints

- Docstring-only change plus (possibly) a single-line `self.client = ...`
  removal if grep finds one. No API surface change.
- Do NOT introduce any new method.
- Do NOT touch the LiveConnect session lifecycle — it's correct as-is for
  single-loop use.

### References in Codebase

- Base class behavior: `parrot/clients/base.py` post-TASK-795.
- Google's model-class hook (for contrast, Live does not need one):
  `parrot/clients/google/client.py` post-TASK-796.

---

## Acceptance Criteria

- [ ] `GeminiLiveClient` class docstring contains a "Cross-loop reuse" section.
- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/live.py`
      returns NOTHING (any pre-existing write is removed).
- [ ] `grep -n "_client_loop_id\|_current_loop_id" packages/ai-parrot/src/parrot/clients/live.py`
      returns NOTHING.
- [ ] `grep -n "Client not initialized" packages/ai-parrot/src/parrot/clients/live.py`
      returns NOTHING (or if present, it's been migrated to `await self._ensure_client()`).
- [ ] Import smoke: `python -c "from parrot.clients.live import GeminiLiveClient"` succeeds.
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/live.py` is clean.

---

## Test Specification

> No new tests. Formal tests in TASK-800. Smoke import only:

```python
from parrot.clients.live import GeminiLiveClient
import inspect
assert "Cross-loop reuse" in inspect.getdoc(GeminiLiveClient)
```

---

## Agent Instructions

1. Verify TASK-795 is in `sdd/tasks/completed/`.
2. Read spec §3 Module 4, §2 Integration Points row for GeminiLiveClient.
3. Grep for each of the three checks (self.client =, _client_loop_id, "Client not initialized").
4. Edit the docstring at `GeminiLiveClient` line ~467.
5. Apply any removals the grep surfaced.
6. Run the smoke test.
7. Move this file to `sdd/tasks/completed/`; update the index.
8. Commit: `sdd: TASK-799 — GeminiLiveClient docstring on cross-loop reuse`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**:
