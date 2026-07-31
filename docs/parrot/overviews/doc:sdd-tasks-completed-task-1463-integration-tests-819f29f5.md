---
type: Wiki Overview
title: 'TASK-1463: End-to-end tests + flip frontend guide §2.5 to "implemented"'
id: doc:sdd-tasks-completed-task-1463-integration-tests-and-doc-update-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5** of FEAT-224. Adds end-to-end coverage proving the
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1463: End-to-end tests + flip frontend guide §2.5 to "implemented"

**Feature**: FEAT-224 — Structured Config Homologation (`artifacts[]` envelope)
**Spec**: `sdd/specs/structured-config-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1459, TASK-1460, TASK-1461, TASK-1462
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of FEAT-224. Adds end-to-end coverage proving the
canonical `artifacts[]` envelope contract holds across the three structured
modes, guards against FEAT-215/218/221/223 regressions, and updates the frontend
integration guide so its §2.5 "estado actual" table reflects the now-implemented
canonical contract.

---

## Scope

- Add integration tests that exercise a `PandasAgent` turn (or the closest
  testable seam) for `structured_chart`, `structured_table`, `structured_map`
  and assert the JSON envelope carries `artifacts[].definition` (config, no
  `data`), rows in `response.data`, and `code is None` on the chart path.
- Add a regression test asserting the FEAT-223 parity suite
  (`test_structured_parity.py`) still passes unchanged.
- Update `docs/frontend/structured-artifacts-frontend-guide.md` §2.5:
  - Move the "Estado actual del backend" table to reflect the implemented
    contract (config now in `artifacts[]`; chart `code` cleared; `artifacts[]`
    populated for the three modes; `response.output` mirror still present per G6).
  - Keep the `extractArtifact()` selector (it already prefers `artifacts[]`).

**NOT in scope**: removing the `response.output` mirror or the compat branches in
`extractArtifact` (deferred until consumers migrate, spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_structured_artifact_envelope_e2e.py` | CREATE | E2E envelope tests |
| `docs/frontend/structured-artifacts-frontend-guide.md` | MODIFY | Update §2.5 "estado actual" → implemented |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # models/outputs.py:37
from parrot.models.responses import AIMessage  # models/responses.py:72
from parrot.storage.models import ArtifactType  # storage/models.py:244 (TABLE via TASK-1459)
```

### Existing Signatures to Use
```python
# Reuse existing fixtures/patterns from the parity suite:
# packages/ai-parrot/tests/outputs/formats/test_structured_parity.py
#   _assert_envelope(out, wrapped, resp, *, explanation=None)
#   tests: test_table_envelope / test_chart_envelope / test_map_conforms_to_same_envelope

# AIMessage envelope fields (models/responses.py)
#   artifacts: List[Dict[str, Any]]  # line 206 — [{type, artifactId, definition}]
#   artifact_id: Optional[str]       # line 214
#   data: Optional[Any]              # line 86
#   code: Optional[str]              # line 90
#   output: Any                      # line 79 (mirror, G6)

# Doc section to edit:
# docs/frontend/structured-artifacts-frontend-guide.md  §2.5
#   "#### Estado actual del backend (lo que recibes HOY, antes del refactor)"
#   table columns: Modo | response.output | response.data | response.code | artifacts[]
```

### Does NOT Exist
- ~~a dedicated `PandasAgent.render_structured(...)` entry point~~ — drive via the
  normal ask/format path or reuse renderer-level fixtures from the parity suite.
- ~~`AIMessage.to_envelope()` wire serializer~~ — the handler serializes; tests can
  assert directly on the `AIMessage`/`response` object fields.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror test_structured_parity.py style; assert the canonical envelope:
def _assert_artifact_envelope(resp, expected_type):
    assert resp.artifacts, "artifacts[] populated"
    art = resp.artifacts[0]
    assert art["type"] == expected_type
    assert art["artifactId"] == resp.artifact_id
    assert "data" not in art["definition"]
    assert resp.data is not None          # rows still present
```

### Key Constraints
- Prefer the lightest seam that still proves the contract end-to-end; if a full
  agent turn is impractical, compose renderer + the TASK-1461 envelope helper.
- Doc edit must stay consistent with the already-decided §2.5 canonical contract;
  only the "estado actual" framing changes from "antes del refactor" to
  "implementado (FEAT-224)".

---

## Acceptance Criteria

- [ ] E2E tests assert the `artifacts[]` envelope for chart/table/map, rows in
      `response.data`, and chart `response.code is None`.
- [ ] FEAT-223 parity suite passes unchanged:
      `pytest packages/ai-parrot/tests/outputs/formats/test_structured_parity.py -v`
- [ ] New tests pass:
      `pytest packages/ai-parrot/tests/integration/test_structured_artifact_envelope_e2e.py -v`
- [ ] `docs/frontend/structured-artifacts-frontend-guide.md` §2.5 updated to mark
      the canonical contract as implemented (FEAT-224), `response.output` noted as
      deprecated mirror.
- [ ] Full structured test sweep green: `pytest packages/ai-parrot/tests/ -k structured -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_structured_artifact_envelope_e2e.py
import pytest


@pytest.mark.parametrize("mode,art_type,content", [
    ("structured_chart", "chart", {"type": "bar", "x": "m", "y": ["s"]}),
    ("structured_table", "table", {"columns": [{"name": "id", "type": "integer", "title": "ID"}]}),
    ("structured_map",   "map",   {"layers": []}),
])
async def test_envelope_contract(make_structured_response, mode, art_type, content):
    resp = await make_structured_response(mode=mode, content=content,
                                          rows=[{"m": "Jan", "s": 1}])
    assert resp.artifacts and resp.artifacts[0]["type"] == art_type
    assert resp.artifacts[0]["artifactId"] == resp.artifact_id
    assert "data" not in resp.artifacts[0]["definition"]
    assert resp.data is not None
    if mode == "structured_chart":
        assert resp.code is None


def test_parity_suite_still_passes():
    # Smoke import to ensure the parity module is collectible alongside new tests.
    import importlib
    importlib.import_module(
        "tests.outputs.formats.test_structured_parity")
```

---

## Agent Instructions

1. Read the spec for full context.
2. Confirm TASK-1459..1462 are in `sdd/tasks/completed/`.
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
