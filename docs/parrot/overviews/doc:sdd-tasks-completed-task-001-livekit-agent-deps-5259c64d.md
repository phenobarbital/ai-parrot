---
type: Wiki Overview
title: 'TASK-001: LiveKit-agent optional deps + package skeleton + data models'
id: doc:sdd-tasks-completed-task-001-livekit-agent-deps-and-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation task for Phase C (spec §2 "Data Models", §3 Module 1, §7 "External
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
---

# TASK-001: LiveKit-agent optional deps + package skeleton + data models

**Feature**: FEAT-243 — LiveAvatar Phase C (voice-native hybrid, ai-parrot as the brain)
**Spec**: `sdd/specs/liveavatar-phase-c-voice-native.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: sdd-worker (Opus)

---

## Context

Foundation task for Phase C (spec §2 "Data Models", §3 Module 1, §7 "External
Dependencies", Open Question **P5**). Before any worker / `llm_node` / output-bridge
code can be written, the `livekit-agents` voice pipeline must be available as an
**optional extra** (pinned — P5) and the two Pydantic contracts the rest of the
feature passes around must exist:

- `AvatarJobMetadata` — parsed from `ctx.job.metadata` (JSON) to inject
  `tenant_id` / `agent_name` / `session_id` into the worker.
- `StructuredOutputMessage` — the output-bridge contract (P4) carried from the
  `llm_node` to the AgentChat UI.

This task is **NOT blocked by FEAT-242** — it touches only new files and
`pyproject.toml`, with no reference to FEAT-242 artifacts.

---

## Scope

- Add a new optional extra to `packages/ai-parrot-integrations/pyproject.toml`
  (e.g. `liveavatar-voice`) that pins `livekit-agents` and the required plugins
  (P5). Pin exact/compatible versions — do NOT leave unpinned.
- Create the `livekit_agent` sub-package under the FEAT-242 `liveavatar` package:
  `__init__.py` (empty/namespace export) and `models.py`.
- Implement `AvatarJobMetadata` and `StructuredOutputMessage` as Pydantic v2
  `BaseModel`s in `models.py`, exactly per the spec §2 "Data Models".
- Write unit tests: `test_job_metadata_parsing` (JSON `ctx.job.metadata` →
  `AvatarJobMetadata`) plus a `StructuredOutputMessage` round-trip/contract test.

**NOT in scope**:
- The `OutputBridge` class (TASK-002).
- `LiveAvatarAgent` / `llm_node` (TASK-003).
- `worker.py` / `pipeline.py` (TASK-004).
- Any reference to FEAT-242 artifacts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | Add `liveavatar-voice` optional extra pinning `livekit-agents` + `livekit-plugins-*` (P5) |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/__init__.py` | CREATE | Sub-package init |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/models.py` | CREATE | `AvatarJobMetadata`, `StructuredOutputMessage` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/__init__.py` | CREATE | Test package init (if absent) |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent_models.py` | CREATE | Model unit tests |

> **Package-root note**: FEAT-242 places the `liveavatar` package at
> `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/`
> (per FEAT-242 spec §3 paths + the `pytest packages/.../tests/integrations/liveavatar`
> acceptance line). Confirm this exact root once FEAT-242 has merged; if FEAT-242
> placed it elsewhere, mirror that location and STOP to flag the divergence.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field          # verified: used across packages/ai-parrot-integrations
from typing import Optional
```

### Existing Signatures to Use
```python
# Optional-dependencies block already exists — append a new extra, do NOT overwrite:
# packages/ai-parrot-integrations/pyproject.toml:33  -> [project.optional-dependencies]
# package name: ai-parrot-integrations  (pyproject.toml:6)
```

### Data Models to Implement (spec §2 — verbatim contract)
```python
# .../liveavatar/livekit_agent/models.py
class AvatarJobMetadata(BaseModel):     # parsed from ctx.job.metadata (JSON)
    ws_url: str
    session_id: str
    agent_name: str
    tenant_id: Optional[str] = None

class StructuredOutputMessage(BaseModel):   # output-bridge contract (P4)
    type: str                               # e.g. "chart" | "data" | "canvas" | "tool_call"
    session_id: str
    payload: dict
    turn_id: Optional[str] = None
```

### Does NOT Exist
- ~~`livekit.agents` / `livekit.plugins.*` installed in the venv~~ — NOT installed
  yet; this task ADDS them as an optional extra (do not `import` them at module top
  level in `models.py` — the models are pure Pydantic and must import cleanly without
  the extra).
- ~~`parrot/integrations/liveavatar/...` (FEAT-242 artifacts)~~ — created by FEAT-242;
  this task does NOT import them.
- ~~a pre-existing `AvatarJobMetadata` / `StructuredOutputMessage`~~ — created here.

---

## Implementation Notes

### Pattern to Follow
- Pure Pydantic v2 models; no third-party imports beyond `pydantic`/`typing` so the
  module imports even when the `liveavatar-voice` extra is absent.
- A classmethod helper for JSON parsing is acceptable, e.g.
  `AvatarJobMetadata.model_validate_json(ctx.job.metadata)` (Pydantic v2 native) — the
  test should exercise exactly that path.

### Key Constraints
- Pin versions in the extra (P5). Suggested anchor from spec §7: `livekit-agents ~= 1.5`
  plus `livekit-plugins-deepgram`, `livekit-plugins-cartesia`, `livekit-plugins-silero`,
  `livekit-plugins-turn-detector` (confirm final plugin set — Q-plugins). Validate the
  exact pin against the published package at implementation time.
- No `print`; use module logger if any logging is needed.

### References in Codebase
- `packages/ai-parrot-integrations/pyproject.toml:33` — existing extras block to extend.

---

## Acceptance Criteria

- [ ] `liveavatar-voice` optional extra added with **pinned** `livekit-agents` + plugins (P5)
- [ ] `AvatarJobMetadata` and `StructuredOutputMessage` implemented exactly per spec §2
- [ ] `models.py` imports cleanly WITHOUT the `liveavatar-voice` extra installed
- [ ] `test_job_metadata_parsing` passes (JSON → `AvatarJobMetadata`)
- [ ] `StructuredOutputMessage` contract test passes
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent`
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent_models.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_livekit_agent_models.py
import json
import pytest
from parrot.integrations.liveavatar.livekit_agent.models import (
    AvatarJobMetadata,
    StructuredOutputMessage,
)


def test_job_metadata_parsing():
    raw = json.dumps({
        "ws_url": "wss://example.livekit.cloud",
        "session_id": "s1",
        "agent_name": "demo",
        "tenant_id": "t1",
    })
    meta = AvatarJobMetadata.model_validate_json(raw)
    assert meta.session_id == "s1"
    assert meta.agent_name == "demo"
    assert meta.tenant_id == "t1"


def test_job_metadata_optional_tenant():
    meta = AvatarJobMetadata(ws_url="wss://x", session_id="s", agent_name="a")
    assert meta.tenant_id is None


def test_structured_output_message_contract():
    msg = StructuredOutputMessage(type="chart", session_id="s1", payload={"k": "v"})
    assert msg.type == "chart"
    assert msg.session_id == "s1"
    assert msg.payload == {"k": "v"}
    assert msg.turn_id is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm the pyproject extras block at the listed
   line still exists before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-18
**Notes**: Added the `liveavatar-voice` optional extra to
`packages/ai-parrot-integrations/pyproject.toml` (pinned `livekit-agents~=1.5`
+ deepgram/cartesia/silero/turn-detector plugins, all `~=1.5`) and wired it into
the `all` meta-extra. Created the `livekit_agent` sub-package with `__init__.py`
(re-exports the two models) and `models.py` containing `AvatarJobMetadata` and
`StructuredOutputMessage` exactly per spec §2 — pure Pydantic v2, no
`livekit-agents` import, so the module loads without the extra. Added 5 unit
tests (incl. `test_job_metadata_parsing` via `model_validate_json`); all pass.
`ruff` clean; pyproject TOML validated.

**Testing note**: the worktree shares the main repo's editable venv, whose
`.pth` resolves `parrot` to the main-repo source roots. Tests were run with the
worktree's `packages/ai-parrot-integrations/src` prepended to `PYTHONPATH` so
`parrot.integrations.liveavatar` resolves from the worktree:
`PYTHONPATH=<wt>/packages/ai-parrot-integrations/src python -m pytest ...` →
`5 passed`.

**Deviations from spec**: none. Did NOT create `liveavatar/__init__.py` — that
parent package file belongs to FEAT-242 (out of this task's scope); the
`livekit_agent` sub-package imports correctly because `parrot.integrations` is a
PEP 420 namespace package that merges the source roots. P5 pin (`~=1.5`) is a
provisional anchor from spec §7 — TASK-003/004 must validate signatures against
the actually-resolved version before finalising.
