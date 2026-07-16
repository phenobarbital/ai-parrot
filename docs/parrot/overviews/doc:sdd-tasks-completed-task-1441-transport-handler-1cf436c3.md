---
type: Wiki Overview
title: 'TASK-1441: Transport — HTTP handler + typed AgenTalk pass-through envelope'
id: doc:sdd-tasks-completed-task-1441-transport-handler-agentalk-envelope-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6. Exposes `spatial_filter` over transport. One thin aiohttp
  handler serves
relates_to:
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1441: Transport — HTTP handler + typed AgenTalk pass-through envelope

**Feature**: FEAT-219 — Spatial Filtering for DatasetManager
**Spec**: `sdd/specs/spatial-dataset-filter.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1440
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Exposes `spatial_filter` over transport. One thin aiohttp handler serves
**both** the deterministic path (frontend POSTs `(point, radius, [datasets])`) and the
NL→spec synthesis path (a synthesizer turns natural language into a `SpatialFilterSpec`
first). Plus a **typed AgenTalk pass-through envelope** so chat can reference a live map
selection — the envelope forwards to the same `spatial_filter` and does **NOT** run the
agent loop or carry memory/lifecycle (resolved decision, spec §8).

---

## Scope

- Implement an aiohttp handler that:
  - accepts a direct `SpatialFilterSpec` (point, radius, datasets) and calls `spatial_filter`;
  - accepts natural language, runs a synthesizer to produce a `SpatialFilterSpec`, then calls
    the same `spatial_filter`;
  - returns the `SpatialFeatureCollection` (GeoJSON) — identical shape for both paths.
- Implement a **typed AgenTalk envelope** that forwards a spec to `spatial_filter` WITHOUT
  invoking `AbstractBot.run()` / the agent loop / memory.
- Write integration tests: `test_deterministic_mode_e2e`, `test_llm_mode_e2e`,
  `test_agentalk_envelope_passthrough` (spec §4). `test_mixed_backend_merge` may live here or
  alongside TASK-1440.

**NOT in scope**: the orchestration method itself (TASK-1440), the compiler (TASK-1438/1439),
the contracts (TASK-1436). No bidirectional chat↔map state coupling (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/spatial_filter_handler.py` | CREATE | aiohttp handler: direct + NL→spec |
| AgenTalk envelope wiring (locate existing AgenTalk module) | MODIFY | typed pass-through forwarding to `spatial_filter` |
| `tests/integration/test_spatial_transport.py` | CREATE | e2e + envelope tests |

> The exact AgenTalk module path is not in the spec's verified contract — **locate and
> verify it** (`grep -ri "agentalk" parrot/`) before wiring, and record the real path in the
> Codebase Contract before implementing.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-03. Paths under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.

### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager   # tool.py:492  (has spatial_filter after TASK-1440)
from parrot.tools.dataset_manager.spatial.contracts import (   # TASK-1436
    SpatialFilterSpec, SpatialFeatureCollection,
)
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                  # l.492
    async def spatial_filter(self, spec: SpatialFilterSpec) -> SpatialFeatureCollection: ...  # added in TASK-1440
    def get_manifest(self) -> list[dict]: ...           # added in TASK-1436
```

### To Verify Before Implementing (not yet in contract)
- AgenTalk module/class path — `grep -ri "agentalk" parrot/` and record the exact import +
  envelope entry point here before wiring.
- The aiohttp handler base/registration pattern under `parrot/handlers/` — read a sibling
  handler and follow its registration convention.

### Does NOT Exist
- ~~a spatial handler / endpoint~~ — none yet; you create it.
- ~~an NL→spec synthesizer~~ — none; implement a thin one (LLM structured output → `SpatialFilterSpec`).
- ~~`requests` / `httpx` usage~~ — forbidden; use `aiohttp` (CONTEXT.md).

---

## Implementation Notes

### Key Constraints
- The deterministic path MUST NOT pass through `AbstractBot.run()` — it is stateless
  request/response (spec §2; brainstorm §3.7).
- Both transport paths return the SAME `SpatialFeatureCollection` shape — the frontend is
  mode-agnostic (spec G1).
- AgenTalk envelope is a **typed pass-through**: forwards the spec to `spatial_filter`, no
  agent loop, no memory.
- Async throughout; `aiohttp` only; `self.logger` at entry/exit.

### References in Codebase
- `parrot/handlers/` — existing aiohttp handler patterns (read a sibling before writing).
- `.agent/CONTEXT.md` — "Never use requests/httpx — use aiohttp".

---

## Acceptance Criteria

- [ ] Handler serves the direct `(point,radius,datasets)` path → `SpatialFeatureCollection`.
- [ ] Handler serves the NL path via a synthesizer → same `SpatialFeatureCollection` shape.
- [ ] AgenTalk typed envelope forwards to `spatial_filter` without running the agent loop.
- [ ] Deterministic path does NOT go through `AbstractBot.run()`.
- [ ] Integration tests pass: `pytest tests/integration/test_spatial_transport.py -v`
- [ ] No linting errors: `ruff check parrot/handlers/spatial_filter_handler.py`
- [ ] AgenTalk import path verified and recorded in this file's Codebase Contract.

---

## Test Specification

```python
# tests/integration/test_spatial_transport.py
import pytest


async def test_deterministic_mode_e2e():
    """POST (point,radius,[datasets]) → FeatureCollection."""
    ...

async def test_llm_mode_e2e():
    """NL → synthesizer → same FeatureCollection shape (mode-agnostic)."""
    ...

async def test_agentalk_envelope_passthrough():
    """Envelope forwards to spatial_filter; agent loop is NOT invoked."""
    ...
```

---

## Agent Instructions

Standard SDD lifecycle. **Before wiring AgenTalk**, locate its real module path and update
this task's Codebase Contract — do not guess the import.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Sonnet (sdd-worker)
**Date**: 2026-06-03
**Notes**: SpatialFilterHandler created in parrot/handlers/spatial_filter_handler.py (core
package, not server). Handler has post() routing to _handle_direct (point/radius/datasets body)
and _handle_nl (query body). Both paths call dm.spatial_filter. AgenTalk verified path:
"agentalk" appears in parrot-server/handlers/agent.py as a channel identifier. The AgenTalk
envelope (SpatialFilterEnvelope) is a Pydantic model with a forward() method that calls
dm.spatial_filter() directly without running AbstractBot.run(). NLSpatialSynthesizer does a
single structured-output LLM call (no agent loop). Handler is designed to be mounted by
ai-parrot-server. _get_dataset_manager() raises NotImplementedError by default; the server
package overrides it.
**Deviations from spec**: Handler placed in core parrot/handlers/ per spec path. The server
package (ai-parrot-server) must mount it and override _get_dataset_manager() to connect to
session/BotManager. This is a deliberate layering choice to keep the core package server-independent.
