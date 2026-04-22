# TASK-802: Document the per-loop client cache contract for subclass authors

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-795, TASK-796
**Assigned-to**: unassigned

---

## Context

Spec §5 Acceptance Criteria lists:

> Documentation updated: `docs/agents/` or a new `docs/clients/per-loop-cache.md`
> explains the contract for subclass authors.

This task creates that doc. Audience: engineers writing a new
`AbstractClient` subclass (new LLM provider) or debugging cross-loop issues
in production (NextStop-class scenarios).

---

## Scope

Create `docs/clients/per-loop-cache.md` covering:

1. **Why per-loop caching exists** — summarise the "Future attached to a
   different loop" failure mode, the `navigator.background.coroutine_in_thread`
   thread-per-job pattern, and why a single cached client can't work.
2. **How the cache works** — the `_clients_by_loop` dict keyed by
   `id(asyncio.get_running_loop())`, `_LoopClientEntry.loop_ref` as a weakref,
   one `asyncio.Lock` per loop, cache-miss logging.
3. **Subclass contract** — what a new subclass MUST do, SHOULD do, MUST NOT do:
   - MUST: implement `async def get_client()` that returns a FRESH SDK client
     on every call (no internal caching on `self.client`).
   - MUST NOT: assign `self.client = ...` anywhere (the property setter rejects
     non-`None` writes).
   - SHOULD: override `_client_invalid_for_current(client, **hints)` only when
     the cached client is no longer valid under some hint (e.g. Google's
     model-class change). Use `_LoopClientEntry.metadata` for state.
   - SHOULD: call `await self._ensure_client()` at the top of public methods
     instead of raising "Client not initialized".
   - MAY: override `_filter_get_client_hints(**hints)` to select which hints
     reach `get_client(...)`.
4. **Invalidation hints worked example** — copy/adapt `GoogleGenAIClient`'s
   `_client_invalid_for_current` + `_ensure_client` wrapper pattern from
   TASK-796. Show the "stamp metadata after super().ensure returns" trick.
5. **Error-recovery mid-request** — use
   `await self._close_current_loop_entry()`, NEVER `await self.close()`.
   Explain why (evicts sibling loops).
6. **GeminiLiveClient caveat** — short subsection noting LiveConnect WebSocket
   sessions cannot migrate across loops (TASK-799 docstring is the primary
   source; this doc cross-links).
7. **Runbook: verifying no leaks** — brief step list for the acceptance
   criterion about 1,000 alternating calls, using `tracemalloc` and/or
   `aiohttp.TraceConfig`, as a manual runbook (not in CI).
8. **Related files**:
   - `parrot/clients/base.py` — base implementation.
   - `parrot/clients/google/client.py` — model-class invalidation example.
   - `parrot/clients/grok.py` — "minimal subclass" example (after TASK-797).
   - Spec: `sdd/specs/per-loop-llm-client-cache.spec.md`.

Use the existing `docs/` conventions — check a sibling file (e.g. the latest
`docs/clients/*.md` if any, or whichever pattern the repo uses) for tone,
heading style (GFM), and table syntax.

**NOT in scope**:
- API reference / auto-docs; this is a hand-written explainer.
- Diagrams (ASCII is fine; don't introduce mermaid/PlantUML unless the repo
  already uses them — verify first).
- Changes to `docs/agents/` — spec offered either location, and a new file
  is cleaner.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/clients/per-loop-cache.md` | CREATE | ~200-400 line explainer covering the 7 sections above. |
| (possibly) `docs/clients/README.md` | MODIFY | If an index exists, add a link to the new doc. Confirm via `ls docs/clients/` first — skip silently if no index. |

---

## Codebase Contract (Anti-Hallucination)

### Verified References

```python
# Implementation files this doc describes (line numbers at time of spec writing;
# verify freshness):
# parrot/clients/base.py                — per-loop cache (post-TASK-795)
# parrot/clients/google/client.py        — invalidation hook (post-TASK-796)
# parrot/clients/grok.py                 — minimal subclass (post-TASK-797)
# parrot/clients/live.py                 — GeminiLiveClient caveat (post-TASK-799)

# Spec:
# sdd/specs/per-loop-llm-client-cache.spec.md
```

### Does NOT Exist

- ~~`docs/agents/per-loop-cache.md`~~ — wrong location; spec §5 picked the new
  `docs/clients/` home.
- ~~`parrot.clients.ClientCache` abstraction~~ — there is none; the cache is
  inlined on `AbstractClient`.
- ~~Mermaid in this repo~~ — verify before using; fall back to ASCII box drawings.

---

## Implementation Notes

### Pattern to Follow

Section sketch:

```markdown
# Per-Loop LLM Client Cache

## Why this exists
...(failure mode story: background task + aiohttp session + fresh loop)...

## How it works
```python
# inside AbstractClient
self._clients_by_loop: dict[int, _LoopClientEntry] = {}
self._locks_by_loop: dict[int, asyncio.Lock] = {}
```
...(describe _ensure_client flow)...

## Writing a new subclass

### Minimal example (Anthropic-style)
```python
class MyClient(AbstractClient):
    client_type = "myprovider"
    async def get_client(self) -> MyAsyncSDK:
        return MyAsyncSDK(api_key=self.api_key)

    async def ask(self, prompt):
        await self._ensure_client()
        return await self.client.messages.create(...)
```

### With invalidation hints (Google-style)
...(show the metadata + hook pattern from TASK-796)...

## Error recovery mid-request
Use `_close_current_loop_entry()`, not `close()` — the latter would evict
sibling loops' healthy sessions.

## GeminiLiveClient caveat
...(short note + link to the class docstring)...

## Verifying no leaks (runbook)
1. ...
2. ...

## Related
- `parrot/clients/base.py`
- `parrot/clients/google/client.py`
- Spec: `sdd/specs/per-loop-llm-client-cache.spec.md`
```

### Key Constraints

- Plain Markdown. No frontmatter unless the repo already standardises one
  (check an existing `docs/*.md`).
- Code blocks must match the final implementation — verify by reading the
  relevant files AFTER TASK-795/796/797/799 have landed. If a signature
  differs, update this doc to match reality, not the spec draft.
- Keep the doc concise — 200-400 lines. This is an explainer, not a reference.
- Link back to the spec for deep rationale; do not duplicate §§1-2.

### References in Codebase

- Spec §7 Known Risks — best source for the runbook and gotchas.
- `GoogleGenAIClient` — the invalidation-hook worked example.

---

## Acceptance Criteria

- [ ] `docs/clients/per-loop-cache.md` exists and contains all 7 sections from Scope.
- [ ] The "minimal example" code block compiles against the actual
      `AbstractClient` signature (no invented methods).
- [ ] Every file path mentioned in the doc exists (verified via `ls`).
- [ ] `markdownlint` / `prettier` pass if the repo uses either (check a
      sibling doc; skip if no linter is wired).
- [ ] Doc links to the spec (`sdd/specs/per-loop-llm-client-cache.spec.md`) and
      to `GeminiLiveClient`'s docstring.
- [ ] If `docs/clients/README.md` exists, a link to the new doc has been added.

---

## Test Specification

No automated tests — the doc is human-read. A PR reviewer will validate
accuracy and clarity.

---

## Agent Instructions

1. Verify TASK-795 and TASK-796 are in `sdd/tasks/completed/`.
2. Read spec §§1, 2, 3, 7 and the completion notes of TASK-795/796/797/799.
3. `ls docs/clients/` — if the directory does not exist, create it.
4. Create `docs/clients/per-loop-cache.md` with the sections listed in Scope.
5. Read the actual implementation once more and sanity-check every code block
   against real signatures.
6. Move this file to `sdd/tasks/completed/`; update the index.
7. Commit: `sdd: TASK-802 — docs for per-loop client cache`.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-22
**Notes**: Created docs/clients/per-loop-cache.md with all 7 required sections:
why it exists, how it works, subclass contract (with rules table), minimal example,
Google-style invalidation worked example, error recovery mid-request, GeminiLiveClient
caveat, and leak verification runbook. No docs/clients/README.md existed to update.
All file paths mentioned in the doc verified to exist.
**Deviations from spec**: None.
