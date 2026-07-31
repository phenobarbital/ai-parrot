---
type: Wiki Overview
title: 'TASK-1458: Homologation tests + migration note'
id: doc:sdd-tasks-completed-task-1458-tests-and-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 5**. With the shared base (TASK-1454), the deterministic
  chart (TASK-1455), config
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1458: Homologation tests + migration note

**Feature**: FEAT-223 — Structured Artifact Contract
**Spec**: `sdd/specs/structured-artifact-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1455, TASK-1456, TASK-1457
**Assigned-to**: unassigned

---

## Context

Implements **Module 5**. With the shared base (TASK-1454), the deterministic chart (TASK-1455), config
convergence (TASK-1456) and the map conformance + `ArtifactType.MAP` (TASK-1457) in place, add the
cross-cutting tests that prove the **homologated contract** holds, and document that the
library-specific `OutputMode`s remain (retired next release, per spec Non-Goals + Q5).

---

## Scope

- **Envelope parity test**: chart and table (and map) produce the SAME envelope shape — `data` excluded
  from `output`, rows/payloads in `response.data`, explanation as `wrapped`.
- **Chart determinism test**: rows come from the DataFrame not the LLM; x/y ∈ real columns; absent
  LLM x/y → deterministic fallback; never raises. (May reuse/extend TASK-1455's tests as the integration-level proof.)
- **Convergence serialization test**: infographic `ChartBlock` + `Artifact` CHART `definition` serialize
  the converged config.
- **Map contract test**: `ArtifactType.MAP` + `OutputMode.STRUCTURED_MAP` exist; map config excludes data.
- **Library-modes-remain test**: assert the library-specific `OutputMode`s still resolve a renderer
  (no removal this FEAT).
- **Migration note**: document in the spec / a short `docs/` note that library-specific modes stay now
  and are retired next release.
- Run the FULL `structured_*` suite; ensure no real client data in fixtures/prompts (placeholders only).

**NOT in scope**: behavioral changes to any renderer (those are TASK-1454/1455/1457) — this task only
adds tests + the migration note. If a test reveals a contract gap, file it back against the owning task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/formats/test_structured_parity.py` | CREATE | Cross-renderer envelope parity (table/chart/map) |
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` | MODIFY | Determinism assertions (if not already covered by TASK-1455) |
| `packages/ai-parrot/tests/ ...` (infographic/storage) | MODIFY | Convergence serialization assertions |
| `docs/` or spec migration note | CREATE/MODIFY | "Library-specific OutputModes remain; retired next release" |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFY before coding. All of TASK-1455/1456/1457 must be in `tasks/completed/` first.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredChartConfig, StructuredTableConfig, StructuredMapConfig
from parrot.storage.models import ArtifactType        # ArtifactType.MAP added by TASK-1457
from parrot.outputs.formats import get_renderer        # __init__.py — dispatch
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
_MODULE_MAP: dict = { ... }                # :20  (STRUCTURED_CHART/TABLE/MAP + library modes)
def register_renderer(mode, system_prompt=None): ...   # :50
def get_renderer(mode: OutputMode): ...                # lazy import from _MODULE_MAP

# Existing test patterns to mirror:
#   packages/ai-parrot/tests/outputs/formats/test_structured_table.py        (554 lines)
#   packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py (414 lines)
#   packages/ai-parrot/tests/outputs/formats/test_structured_chart.py        (706 lines)
#   packages/ai-parrot/tests/outputs/formats/test_structured_map_renderer.py (372 lines)
```

### Does NOT Exist
- ~~A cross-renderer parity test~~ — this task creates it.
- ~~Any removal of library-specific OutputModes~~ — they must still resolve a renderer; the test asserts this.

---

## Implementation Notes

### Key Constraints
- Reuse `test_structured_chart.py` / `test_structured_table.py` fixture patterns; placeholder data only
  (`cat` / `val` — NO real client figures).
- Tests must be async where they call `render`.
- Do NOT change renderer behavior here — tests only.

---

## Acceptance Criteria

- [ ] Parity test proves table/chart/map share the envelope shape.
- [ ] Chart determinism asserted (rows from DataFrame; x/y ∈ real columns; deterministic fallback).
- [ ] Convergence serialization asserted (ChartBlock + Artifact CHART definition).
- [ ] `ArtifactType.MAP` + `OutputMode.STRUCTURED_MAP` asserted to exist.
- [ ] Library-specific modes still resolve a renderer (no removal this FEAT).
- [ ] Migration note written.
- [ ] Full suite passes: `pytest packages/ai-parrot/tests/outputs/formats/ -v`
- [ ] No real client data in any fixture or prompt.

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/formats/test_structured_parity.py
import pytest
from parrot.models.outputs import OutputMode


class TestEnvelopeParity:
    async def test_chart_and_table_same_envelope_shape(self):
        """Both exclude 'data' from output and route rows to response.data; explanation wrapped."""
        ...

    async def test_map_conforms_to_same_envelope(self):
        ...


class TestLibraryModesRemain:
    @pytest.mark.parametrize("mode", [ ... ])  # library-specific OutputModes
    def test_library_mode_still_resolves(self, mode):
        from parrot.outputs.formats import get_renderer
        assert get_renderer(mode) is not None
```

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-04
**Notes**: Created test_structured_parity.py (23 tests: envelope parity across table/chart/map, chart determinism integration, symbol existence, 9 library-mode retention, convergence serialization). Created docs/migration/feat-223-structured-artifact-contract.md. 23/23 parity tests pass; 204/205 outputs/formats suite (1 pre-existing pep420 env failure unrelated to FEAT-223).
**Deviations from spec**: none
