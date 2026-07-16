---
type: Wiki Overview
title: 'TASK-1459: Add `ArtifactType.TABLE` + generalize `Artifact.from_structured_config`'
id: doc:sdd-tasks-completed-task-1459-artifacttype-table-and-structured-constructor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-224. The persisted `Artifact` model only
  knows
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1459: Add `ArtifactType.TABLE` + generalize `Artifact.from_structured_config`

**Feature**: FEAT-224 — Structured Config Homologation (`artifacts[]` envelope)
**Spec**: `sdd/specs/structured-config-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-224. The persisted `Artifact` model only knows
how to build CHART artifacts (`from_chart_config`) and the `ArtifactType` enum
has no `TABLE` member. The homologated `artifacts[]` envelope (G1) needs a
type-aware constructor for chart/map/table, and the auto-save path (TASK-1462)
needs `ArtifactType.TABLE`.

---

## Scope

- Add `TABLE = "table"` to `ArtifactType` (G4).
- Add `Artifact.from_structured_config(cfg, artifact_type, artifact_id, title,
  created_at, updated_at, **kwargs)` that serialises any `Structured*Config` via
  `cfg.model_dump(mode="json", by_alias=True, exclude={"data"})` into
  `definition`, with `artifact_type` selecting CHART/MAP/TABLE.
- Reduce `from_chart_config` to a thin wrapper delegating to
  `from_structured_config(cfg, ArtifactType.CHART, ...)` — identical output to
  today (backward compatible).
- Unit tests for the above.

**NOT in scope**: wiring the envelope onto `AIMessage` (TASK-1461); handler
persistence (TASK-1462); adding `as_table_config`/`as_map_config` round-trip
helpers (deferred per spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/models.py` | MODIFY | Add `ArtifactType.TABLE`; add `from_structured_config`; rewire `from_chart_config` |
| `packages/ai-parrot/tests/storage/test_artifact_structured_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator  # storage/models.py:244,254,273
from parrot.models.outputs import (
    StructuredChartConfig, StructuredTableConfig, StructuredMapConfig,
)  # models/outputs.py:309,520,723
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/storage/models.py
class ArtifactType(str, Enum):                       # line 244
    CHART = "chart"                                  # line 246
    MAP = "map"                                      # line 247
    CANVAS = "canvas"                                # line 248
    INFOGRAPHIC = "infographic"                      # line 249
    DATAFRAME = "dataframe"                          # line 250
    EXPORT = "export"                                # line 251
    # NO TABLE member today — this task adds it.

class Artifact(BaseModel):                           # line 273
    artifact_id: str                                 # line 283
    artifact_type: ArtifactType                      # line 284
    title: str                                       # line 285
    created_at: datetime                             # line 286
    updated_at: datetime                             # line 287
    source_turn_id: Optional[str] = None             # line 288
    created_by: ArtifactCreator = ArtifactCreator.USER  # line 289
    definition: Optional[Dict[str, Any]] = None      # line 290
    definition_ref: Optional[str] = None             # line 291

    @classmethod
    def from_chart_config(cls, cfg, artifact_id, title, created_at, updated_at, **kwargs):  # line 293
        # current body: definition=cfg.model_dump(mode="json", by_alias=True, exclude={"data"})  # line 325
        #               artifact_type=ArtifactType.CHART
    def as_chart_config(self) -> Any: ...            # line 329  (leave untouched)
```

### Does NOT Exist
- ~~`ArtifactType.TABLE`~~ — this task adds it.
- ~~`Artifact.from_structured_config`~~ / ~~`from_table_config`~~ / ~~`from_map_config`~~ — none exist; add only the generic one.
- ~~`Artifact.as_table_config` / `as_map_config`~~ — only `as_chart_config` exists; do NOT add here.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror the existing from_chart_config body exactly, parameterizing the type:
@classmethod
def from_structured_config(cls, cfg, artifact_type, artifact_id, title,
                           created_at, updated_at, **kwargs):
    return cls(
        artifact_id=artifact_id,
        artifact_type=artifact_type,        # CHART | MAP | TABLE
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        definition=cfg.model_dump(mode="json", by_alias=True, exclude={"data"}),
        **kwargs,
    )

@classmethod
def from_chart_config(cls, cfg, artifact_id, title, created_at, updated_at, **kwargs):
    return cls.from_structured_config(
        cfg, ArtifactType.CHART, artifact_id, title, created_at, updated_at, **kwargs,
    )
```

### Key Constraints
- `definition` MUST exclude `data` and use camelCase aliases (`by_alias=True`).
- Place `TABLE = "table"` adjacent to `CHART`/`MAP` for readability.
- Do not change `as_chart_config` behavior.

---

## Acceptance Criteria

- [ ] `ArtifactType.TABLE == "table"`.
- [ ] `from_structured_config` builds an artifact whose `definition` is the
      camelCase config dict without a `data` key, for chart/map/table.
- [ ] `from_chart_config` still returns a CHART artifact identical to before.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/storage/test_artifact_structured_config.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/storage/models.py`
- [ ] Imports work: `from parrot.storage.models import Artifact, ArtifactType`

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/test_artifact_structured_config.py
from datetime import datetime, timezone
import pytest
from parrot.storage.models import Artifact, ArtifactType
from parrot.models.outputs import (
    StructuredChartConfig, StructuredTableConfig, TableColumn,
)


def _now():
    return datetime(2026, 6, 4, tzinfo=timezone.utc)


def test_artifacttype_table_exists():
    assert ArtifactType.TABLE.value == "table"


def test_from_structured_config_chart_excludes_data():
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"],
                                data=[{"month": "Jan", "sales": 1}])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.CHART, "chart-1", "T", _now(), _now())
    assert art.artifact_type == ArtifactType.CHART
    assert "data" not in art.definition
    assert art.definition["x"] == "month"


def test_from_structured_config_table_type():
    cfg = StructuredTableConfig(columns=[TableColumn(name="id", type="integer", title="ID")])
    art = Artifact.from_structured_config(
        cfg, ArtifactType.TABLE, "table-1", "T", _now(), _now())
    assert art.artifact_type == ArtifactType.TABLE
    assert "data" not in art.definition


def test_from_chart_config_backcompat():
    cfg = StructuredChartConfig(type="line", x="d", y=["v"])
    art = Artifact.from_chart_config(cfg, "c", "T", _now(), _now())
    assert art.artifact_type == ArtifactType.CHART
    assert "data" not in art.definition
```

---

## Agent Instructions

1. Read the spec for full context.
2. Verify the Codebase Contract anchors before editing.
3. Update status in the per-spec index → `in-progress`.
4. Implement per scope.
5. Verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update index → `done`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
