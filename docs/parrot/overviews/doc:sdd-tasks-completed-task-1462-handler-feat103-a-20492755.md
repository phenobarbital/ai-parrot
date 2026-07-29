---
type: Wiki Overview
title: 'TASK-1462: Align FEAT-103 handler auto-save with the structured artifact envelope'
id: doc:sdd-tasks-completed-task-1462-handler-feat103-autosave-alignment-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of FEAT-224 (G5). The AgentTalk handler auto-save
relates_to:
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1462: Align FEAT-103 handler auto-save with the structured artifact envelope

**Feature**: FEAT-224 — Structured Config Homologation (`artifacts[]` envelope)
**Spec**: `sdd/specs/structured-config-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1459, TASK-1461
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-224 (G5). The AgentTalk handler auto-save
(`agent.py:2667-2714`) currently fires only for `output_mode in
('chart','dataframe','export')` and persists `response.data` (the rows) as the
artifact `definition` — the wrong half. After TASK-1461, the agent already
attaches the correct config envelope to `response.artifacts`. This task makes the
handler recognise the `structured_*` modes and persist the artifact `definition`
(the config), mapped to the right `ArtifactType`, reusing the envelope the agent
already built (and its `artifact_id`).

---

## Scope

- Extend the auto-save guard to also fire for `structured_chart`,
  `structured_table`, `structured_map`.
- For those modes, persist the artifact `definition` taken from
  `response.artifacts[]` (built by TASK-1461) — NOT `response.data`.
- Map mode → `ArtifactType`: `structured_chart→CHART`, `structured_map→MAP`,
  `structured_table→TABLE`. Keep the existing `chart/dataframe/export` mappings.
- Reuse `response.artifact_id` rather than minting a new id when the envelope is
  present (avoid double ids).
- Prefer `Artifact.from_structured_config(cfg, artifact_type, ...)` if a typed
  config is reconstructable; otherwise persist the `definition` dict directly.
- Unit test the structured branch persists `definition` with the correct type.

**NOT in scope**: changing the non-structured (`chart/dataframe/export`) legacy
path beyond adding the new mappings; the agent envelope construction (TASK-1461).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Extend FEAT-103 auto-save for structured_* modes |
| `packages/ai-parrot-server/tests/handlers/test_agent_autosave_structured.py` | CREATE | Unit tests (or extend existing handler test module) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Imported lazily inside the auto-save block today (keep that style):
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator  # storage/models.py:244,254,273
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py  (AgentTalk)
#   FEAT-103 auto-save block                                               # lines 2667-2714
#   guard (EXTEND):
#       artifact_store and user_id and session_id
#       and response.data is not None
#       and output_mode in ('chart', 'dataframe', 'export')                # line 2675  ← add structured_*
#   _type_map (EXTEND):                                                    # lines 2684-2688
#       {'chart': ArtifactType.CHART, 'dataframe': ArtifactType.DATAFRAME, 'export': ArtifactType.EXPORT}
#   _art_id = f"{output_mode}-{_uuid.uuid4().hex[:8]}"                      # line 2690  ← reuse response.artifact_id if present
#   _definition = response.data if isinstance(response.data, dict) else {"raw": ...}   # lines 2691-2694  ← use config for structured_*
#   Artifact(artifact_id=..., artifact_type=..., title=..., created_at=..., updated_at=...,
#            source_turn_id=client_message_id, created_by=ArtifactCreator.AGENT, definition=...)  # lines 2695-2704
#   artifact_store.save_artifact(user_id=, agent_id=, session_id=, artifact=)  # lines 2706-2711

# storage/models.py
#   Artifact.from_structured_config(cfg, artifact_type, artifact_id, title, created_at, updated_at, **kwargs)  # added by TASK-1459

# AIMessage (models/responses.py)
#   artifacts: List[Dict[str, Any]]  # line 206 — entries: {type, artifactId, definition}
#   artifact_id: Optional[str]       # line 214
#   data: Optional[Any]              # line 86  — rows; NOT the definition for structured_*
```

### Does NOT Exist
- ~~`response.definition`~~ — the config lives in `response.artifacts[i]["definition"]`.
- ~~`Artifact.from_table_config` / `from_map_config`~~ — use the generic `from_structured_config`.
- ~~`artifact_store.save_structured_artifact`~~ — only `save_artifact(...)` exists.

---

## Implementation Notes

### Pattern to Follow
```python
_STRUCTURED_TYPE_MAP = {
    'structured_chart': ArtifactType.CHART,
    'structured_map':   ArtifactType.MAP,
    'structured_table': ArtifactType.TABLE,
}
_type_map = {**_legacy_type_map, **_STRUCTURED_TYPE_MAP}

is_structured = output_mode in _STRUCTURED_TYPE_MAP
if artifact_store and user_id and session_id and (
        (is_structured and response.artifacts) or
        (not is_structured and response.data is not None and output_mode in _legacy_type_map)):

    if is_structured:
        env = next((a for a in response.artifacts if a.get("definition")), None)
        if env is None:
            return  # nothing to persist
        _art_id = response.artifact_id or env.get("artifactId") or f"{output_mode}-{_uuid.uuid4().hex[:8]}"
        _definition = env["definition"]          # the config, NOT response.data
        _atype = _type_map[output_mode]
    else:
        # ...existing legacy path unchanged...
```

### Key Constraints
- Keep the lazy import + `create_task(...)` fire-and-forget pattern.
- Wrap in the existing `try/except` that only logs a warning on failure.
- Do not break the legacy `chart/dataframe/export` behavior.
- Reuse `response.artifact_id` for id stability across agent + persistence.

---

## Acceptance Criteria

- [ ] Auto-save fires for `structured_chart|table|map` when `response.artifacts`
      carries an envelope.
- [ ] The persisted `Artifact.definition` is the config (envelope `definition`),
      not `response.data`.
- [ ] `artifact_type` is CHART/MAP/TABLE per mode; `artifact_id` reuses
      `response.artifact_id`.
- [ ] Legacy `chart/dataframe/export` path unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_agent_autosave_structured.py -v`
- [ ] No lint errors on the modified handler block.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_agent_autosave_structured.py
# Drive the auto-save branch with a fake artifact_store capturing save_artifact(artifact=...).
import pytest


class _FakeStore:
    def __init__(self):
        self.saved = []
    async def save_artifact(self, *, user_id, agent_id, session_id, artifact):
        self.saved.append(artifact)


async def test_structured_chart_persists_definition_not_data(handler_ctx, fake_store):
    # response: output_mode="structured_chart", artifacts=[{type,artifactId,definition}], data=<rows>
    await run_autosave(handler_ctx, output_mode="structured_chart",
                       artifacts=[{"type": "chart", "artifactId": "chart-x",
                                   "definition": {"type": "bar", "x": "m", "y": ["s"]}}],
                       artifact_id="chart-x",
                       data=[{"m": "Jan", "s": 1}])
    art = fake_store.saved[0]
    assert art.artifact_type.value == "chart"
    assert art.artifact_id == "chart-x"
    assert art.definition == {"type": "bar", "x": "m", "y": ["s"]}  # config, NOT rows


async def test_structured_table_maps_to_table_type(handler_ctx, fake_store):
    await run_autosave(handler_ctx, output_mode="structured_table",
                       artifacts=[{"type": "table", "artifactId": "table-y",
                                   "definition": {"columns": []}}],
                       artifact_id="table-y", data=[{"id": 1}])
    assert fake_store.saved[0].artifact_type.value == "table"
```

---

## Agent Instructions

1. Read the spec for full context.
2. Confirm TASK-1459 and TASK-1461 are in `sdd/tasks/completed/`.
3. Verify the Codebase Contract anchors before editing.
4. Update status in the per-spec index → `in-progress`.
5. Implement per scope.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update index → `done`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
