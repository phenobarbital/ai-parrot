---
type: Wiki Overview
title: 'TASK-1461: PandasAgent builds `artifacts[]` envelope + removes chart `response.code`
  staging'
id: doc:sdd-tasks-completed-task-1461-pandasagent-artifact-envelope-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-224 (G1, G2, G3, G6) — the core of the feature.
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1461: PandasAgent builds `artifacts[]` envelope + removes chart `response.code` staging

**Feature**: FEAT-224 — Structured Config Homologation (`artifacts[]` envelope)
**Spec**: `sdd/specs/structured-config-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1459, TASK-1460
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-224 (G1, G2, G3, G6) — the core of the feature.
After the structured renderer produces its config, `PandasAgent` must place that
config in the canonical `response.artifacts[]` envelope and set
`response.artifact_id`, while keeping `response.output` as a deprecated mirror
(G6) and leaving rows in `response.data` (G2). It must also remove the
`STRUCTURED_CHART` staging that wrote the config into `response.code` (G3) — the
chart renderer now reads from `response.output` (TASK-1460).

---

## Scope

- After final formatting (`bots/data.py` ~`1869-1872`), for `output_mode in
  {STRUCTURED_TABLE, STRUCTURED_CHART, STRUCTURED_MAP}` and when `content` (the
  config dict) is a non-empty dict:
  - mint an `artifact_id` (reuse `f"{output_mode.value}-{uuid4().hex[:8]}"`),
  - append `{"type": <ArtifactType value>, "artifactId": <id>, "definition": content}`
    to `response.artifacts`,
  - set `response.artifact_id = <id>`,
  - keep `response.output = content` (mirror, G6).
- Map each mode → artifact type string: `structured_chart→"chart"`,
  `structured_map→"map"`, `structured_table→"table"`.
- Remove the chart config staging into `response.code` (`~1587-1606`): keep the
  `data_variable` injection (so rows still land in `response.data`) but stop
  setting `response.code` to the config dump. Ensure `response.code` is `None` on
  the chart path unless real analysis code exists.
- Unit tests for all three modes + the chart `code is None` invariant.

**NOT in scope**: the generic `Artifact` constructor (TASK-1459); handler
persistence (TASK-1462); removing the `response.output` mirror (deferred, G6).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Build artifact envelope; remove chart `code` staging |
| `packages/ai-parrot/tests/bots/test_pandasagent_artifact_envelope.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import (
    OutputMode, StructuredChartConfig, StructuredTableConfig, StructuredMapConfig,
)  # models/outputs.py:37,309,520,723
from parrot.storage.models import ArtifactType   # storage/models.py:244 (TABLE added by TASK-1459)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py  (PandasAgent)
#   STRUCTURED_MAP staging (KEEP): routes SpatialResult to response.data       # lines 1561-1581
#   STRUCTURED_CHART staging (MODIFY): response.code = _cfg_out.model_dump(...) # lines 1587-1606
#       _cfg_out = response.output                                             # line 1588
#       if isinstance(_cfg_out, StructuredChartConfig):                        # line 1590
#           response.code = _cfg_out.model_dump(mode="json", by_alias=True)    # line 1591  ← REMOVE this assignment
#           _chart_data_var = _cfg_out.data_variable                           # line 1592  ← KEEP (data var injection)
#       await self._inject_data_from_variable(response, _chart_data_var)       # line 1604  ← KEEP
#   final formatting:
#       content, wrapped = await self.formatter.format(output_mode, response, **format_kwargs)  # lines 1857-1859
#       if output_mode != DEFAULT and not in [TELEGRAM, MSTEAMS]:              # line 1869
#           response.output = content                                          # line 1870  ← KEEP (mirror, G6)
#           response.response = wrapped                                        # line 1871
#           response.output_mode = output_mode                                 # line 1872
#       # ← INSERT artifact-envelope construction AFTER this block

# AIMessage fields (models/responses.py)
#   output: Any              # line 79
#   data: Optional[Any]      # line 86
#   code: Optional[str]      # line 90
#   artifacts: List[Dict[str, Any]] = []   # line 206
#   output_mode: OutputMode  # line 210
#   artifact_id: Optional[str] = None       # line 214
```

### Does NOT Exist
- ~~`response.set_artifact(...)`~~ — no such helper; append to `response.artifacts` directly (it is a `List[Dict[str, Any]]`).
- ~~`AIMessage.add_structured_artifact`~~ — only `add_artifact(type, content, **meta)` exists (responses.py:279); the envelope keys here (`type/artifactId/definition`) differ, so set the dict explicitly.
- ~~a global uuid import in data.py~~ — verify/`import uuid` if absent before use.

---

## Implementation Notes

### Pattern to Follow
```python
# AFTER: response.output = content; response.response = wrapped; response.output_mode = output_mode
_STRUCTURED_ARTIFACT_TYPE = {
    OutputMode.STRUCTURED_CHART: "chart",
    OutputMode.STRUCTURED_MAP:   "map",
    OutputMode.STRUCTURED_TABLE: "table",
}
art_type = _STRUCTURED_ARTIFACT_TYPE.get(output_mode)
if art_type and isinstance(content, dict) and content:
    art_id = f"{output_mode.value}-{uuid.uuid4().hex[:8]}"
    response.artifacts.append({
        "type": art_type,
        "artifactId": art_id,
        "definition": content,          # camelCase, no data (renderer already excluded it)
    })
    response.artifact_id = art_id
```
```python
# In the STRUCTURED_CHART staging block (~1587): DELETE the line
#   response.code = _cfg_out.model_dump(mode="json", by_alias=True)
# Keep extracting _chart_data_var and calling _inject_data_from_variable.
# (The chart renderer now reads its config from response.output — TASK-1460.)
```

### Key Constraints
- Do NOT evaluate `response.data` in a boolean context if it may be a DataFrame;
  this block only touches `content`/`response.artifacts`.
- `response.output` mirror stays (G6) — do not remove it.
- Async-first; use `self.logger.info` to record the minted `artifact_id`.
- Only mint an envelope when `content` is a real config dict (skip text/None).

---

## Acceptance Criteria

- [ ] For each of `structured_chart|table|map`, `response.artifacts[0]` equals
      `{"type": <chart|table|map>, "artifactId": <id>, "definition": <config>}`
      with `"data"` absent from `definition`, and `response.artifact_id` set.
- [ ] `response.data` still carries rows (table/chart) / per-layer payloads (map).
- [ ] On the chart path, `response.code` is `None` (no config duplication).
- [ ] `response.output` still mirrors the config (G6).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/bots/test_pandasagent_artifact_envelope.py -v`
- [ ] No lint errors on `bots/data.py` changes.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_pandasagent_artifact_envelope.py
# Prefer testing the envelope-construction helper in isolation if extracted;
# otherwise drive PandasAgent with a stubbed formatter returning (content, wrapped).
import pytest


def _assert_envelope(response, expected_type):
    assert response.artifacts, "artifacts[] must be populated"
    art = response.artifacts[0]
    assert art["type"] == expected_type
    assert art["artifactId"] == response.artifact_id
    assert "data" not in art["definition"]


def test_chart_envelope_and_code_cleared(agent_with_stub_formatter):
    resp = run_turn(agent_with_stub_formatter, output_mode="structured_chart",
                    content={"type": "bar", "x": "m", "y": ["s"]})
    _assert_envelope(resp, "chart")
    assert resp.code is None
    assert resp.output == {"type": "bar", "x": "m", "y": ["s"]}  # mirror (G6)


def test_table_envelope(agent_with_stub_formatter):
    resp = run_turn(agent_with_stub_formatter, output_mode="structured_table",
                    content={"columns": [{"name": "id", "type": "integer", "title": "ID"}]})
    _assert_envelope(resp, "table")


def test_map_envelope(agent_with_stub_formatter):
    resp = run_turn(agent_with_stub_formatter, output_mode="structured_map",
                    content={"layers": []})
    _assert_envelope(resp, "map")
```

> If wiring a full `PandasAgent` turn is too heavy, refactor the envelope
> construction into a small pure helper (e.g. `_attach_structured_artifact(
> response, output_mode, content)`) and unit-test that directly. Document the
> choice in the Completion Note.

---

## Agent Instructions

1. Read the spec for full context.
2. Confirm TASK-1459 and TASK-1460 are in `sdd/tasks/completed/`.
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
