# TASK-2562: Compat shim (`artifact_definition_to_legacy`) + `attach_structured_artifact` helper

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2561
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `artifacts[]` entries move to v2
(`{type, artifactId, surfaceId, schemaVersion: 2, definition: <Component>}`,
G5) with a consumer cushion (G6): `artifact_definition_to_legacy` reproduces
the FEAT-224 v1 `definition` for legacy readers (shim window 0.30 → removed
0.32). The FEAT-224 inline minting block in `bots/data.py:2095-2135` becomes a
reusable core helper `attach_structured_artifact()` so DatabaseAgent can mint
too (TASK-2565 wires the call sites).

---

## Scope

- Extend `parrot/outputs/a2ui/compat.py`:
  - `is_legacy_artifact(entry: dict) -> bool` — `schemaVersion` absent or `1`.
  - `artifact_definition_to_legacy(entry: dict) -> dict` — v2 component node →
    FEAT-224 camelCase config dict: drop `id`/`component`/`catalogId`/`data`
    (and `datasets`), keep remaining props.
- **Extend (do NOT overwrite)** `parrot/outputs/a2ui/artifacts.py` with
  `attach_structured_artifact(response, output_mode) -> str | None`:
  - With `response.a2ui_envelope` present: read the root component via
    `adapters.structured.root_component(...)`, append the v2 entry with
    `surfaceId == artifactId` (from the envelope's `surfaceId`), set
    `response.artifact_id`, return the id.
  - Without an envelope: fall back to the FEAT-224 v1 config-dict `definition`
    (no `schemaVersion`), minting `f"{mode_str}-{uuid4().hex[:8]}"`.
  - Type map `{STRUCTURED_CHART: "chart", STRUCTURED_MAP: "map", STRUCTURED_TABLE: "table"}`;
    non-structured modes → return `None`, no-op.
- Unit tests (spec §4 Module-3 rows).

**NOT in scope**: replacing the call sites in `bots/data.py` /
`database/agent.py` / handlers (TASK-2565); the satellite hook (TASK-2563).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/compat.py` | MODIFY | `is_legacy_artifact`, `artifact_definition_to_legacy` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` | MODIFY | append `attach_structured_artifact` (file EXISTS — see contract) |
| `packages/ai-parrot/tests/outputs/a2ui/test_structured_artifacts.py` | CREATE | shim + helper tests |

---

## Codebase Contract (Anti-Hallucination)

> **[470-wt]** lines verified on `feat-470-a2ui-v1-dialect` @ `0da976674`.
> Re-verify against `dev` after the FEAT-470 merge.

### Verified Imports
```python
# core dev @ 8b40e0c
from parrot.models.outputs import OutputMode  # models/outputs.py:33 (STRUCTURED_CHART :61, STRUCTURED_TABLE :62, STRUCTURED_MAP :63)
from parrot.models.responses import AIMessage  # artifacts :206, output_mode :210, artifact_id :214, a2ui_envelope :222
# [470-wt]
from parrot.outputs.a2ui.compat import normalize_legacy, is_legacy_envelope, normalize_legacy_component  # compat.py:186/41/95
# from this feature (TASK-2561):
from parrot.outputs.a2ui.adapters.structured import root_component, SCHEMA_VERSION
```

### Existing Signatures to Use
```python
# ⚠️ parrot/outputs/a2ui/artifacts.py ALREADY EXISTS on dev (verified 2026-08-29 @ 8b40e0c) —
# the spec's "Does NOT Exist" list is WRONG about the module (right about the function).
# It currently holds:
class DeepLink(BaseModel)          # artifacts.py:23
class RenderedArtifact(BaseModel)  # artifacts.py:41
# → APPEND attach_structured_artifact; do not move or rename the existing models.

# dev bots/data.py:2095-2135 — the FEAT-224 inline block to replicate as the v1 fallback:
#   _STRUCTURED_ARTIFACT_TYPE = {STRUCTURED_CHART:"chart", STRUCTURED_MAP:"map", STRUCTURED_TABLE:"table"}  # :2099
#   _art_id = f"{_mode_str}-{uuid.uuid4().hex[:8]}"  # :2113
#   strips "data"/"datasets" from the config dump; response.artifacts.append({...}); response.artifact_id = _art_id  # :2128

# v2 artifacts[] entry shape (spec §2):
# {"type": "chart"|"table"|"map", "artifactId": str, "surfaceId": str, "schemaVersion": 2,
#  "definition": <v1.0 Component node: id="root", component, catalogId, props..., data={"path"}>}
# envelope shape: response.a2ui_envelope == {"version":"v1.0","createSurface":{"surfaceId":..., "components":[...], "dataModel":...}}
```

### Does NOT Exist
- ~~`compat.is_legacy_artifact`~~ / ~~`compat.artifact_definition_to_legacy`~~ — this task creates them.
- ~~`attach_structured_artifact`~~ — this task creates it (FEAT-224 logic is inline in `bots/data.py`, not a function).
- ~~`artifacts[].surfaceId` / `schemaVersion` anywhere today~~ — v2 is new.

---

## Implementation Notes

### Key Constraints
- `artifact_definition_to_legacy(v2_entry)` output must equal the FEAT-224 v1
  `definition` for the same config — this is AC-7's exact assertion.
- Helper is pure core: only `parrot.models.*` + `parrot.outputs.a2ui.*` imports (D4).
- Helper never raises to the caller — mirror the FEAT-224 block's defensive style;
  log at `warning` on malformed envelopes and fall back to v1.
- `surfaceId == artifactId == response.artifact_id` (AC-6).

### References in Codebase
- `bots/data.py:2095-2135` (dev) — canonical v1 minting behaviour
- `compat.py` [470-wt] — naming/docstring style for shim functions

---

## Acceptance Criteria

- [ ] `artifact_definition_to_legacy(v2_entry)` == FEAT-224 v1 dict (no `id`/`component`/`catalogId`/`data`) (AC-7)
- [ ] `is_legacy_artifact` true for entries without `schemaVersion` or `== 1`, false for `== 2`
- [ ] `attach_structured_artifact` with envelope → v2 entry, `surfaceId == artifactId == response.artifact_id`; without envelope → v1 entry (AC-6)
- [ ] Non-structured `output_mode` → `None`, response untouched
- [ ] Existing `DeepLink`/`RenderedArtifact` in `artifacts.py` untouched
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_structured_artifacts.py -v`; ruff clean

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/test_structured_artifacts.py
def test_artifact_definition_to_legacy(v2_artifact_entry): ...
def test_is_legacy_artifact(): ...
def test_attach_structured_artifact_v2_and_fallback(): ...
def test_attach_ignores_non_structured_modes(): ...
```

---

## Agent Instructions

1. Verify TASK-2561 is in `sdd/tasks/completed/`.
2. Read the CURRENT `artifacts.py` before editing — append only.
3. Implement, test, move to completed, update index, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
