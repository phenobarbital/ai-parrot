# TASK-4168: Enable reporting defaults only for ink-wall layouts

**Feature**: FEAT-645 — Planogram Ink Wall — model-based labels and slot presence
**Spec**: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4167
**Assigned-to**: unassigned

## Context

Implement spec §3 M3. Only ink_wall opts in by default; configuration overrides continue through the existing deep merge.

## Scope

- Add LayoutProfile.reporting with a fresh default.
- Enable product labels and presence in InkWall.default_layout_profile.
- Test overrides and every entry in the current type registry.

**NOT in scope**: scoring/credit/status changes, vision identification improvements, database writes,
flowtask persistence, dependencies, or files outside the table below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py` | MODIFY | Declare reporting field |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` | MODIFY | Enable ink-wall reporting defaults |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_layout.py` | CREATE | Defaults and override tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` during decomposition, 2026-10-08. Recheck anchors after dependencies land.
Existing imports below are verified in their source modules or installed dependencies.
Imports explicitly tagged with a task ID are planned dependency interfaces, not existing symbols at planning time.
Retain unrelated existing imports in MODIFY targets.

### Verified Imports

```python
from pydantic import Field
import pytest
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy  # TASK-4167
from parrot_pipelines.planogram.layout import LayoutProfile, resolve_layout_profile
from parrot_pipelines.planogram.types.ink_wall import InkWall
from parrot_pipelines.planogram.plan import PlanogramCompliance
# Equivalent relative imports used by the two MODIFY blocks (ReportingPolicy: TASK-4167):
from .comparison.definition import ReportingPolicy, SlotsDefinition  # layout.py context
from ..comparison.definition import ReportingPolicy, SlotsDefinition  # types/ink_wall.py context
```

### Existing Signatures to Use

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py:66` — `LayoutProfile`: extra=forbid; fields include references and zone_selectors
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py:150` — `resolve_layout_profile`: (defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile; deep merge then validate
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:64` — `InkWall.default_layout_profile`: classmethod returning a fresh LayoutProfile
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:66` — `PlanogramCompliance`: _PLANOGRAM_TYPES at 79 enumerates six built-in types; no separate types.registry module

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:131` — `SlotsDefinition`: Existing import retained in layout.py and ink_wall.py.

### Does NOT Exist

- `LayoutProfile.reporting` does not yet exist.
- There is no types/registry.py; enumerate PlanogramCompliance._PLANOGRAM_TYPES in tests.
- ReportingPolicy is supplied by TASK-4167; do not redeclare it.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_layout.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#LayoutProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#resolve_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.default_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition"
  ]
}
```

## Implementation Notes

Do not change resolve_layout_profile: its existing recursive dict merge already supports the new nested field. Relative imports in MODIFY blocks are the same verified dependency interfaces listed above, with SlotsDefinition retained.

**Parallelism**: Consumes ReportingPolicy from TASK-4167 (comparison/definition.py); writes layout.py, types/ink_wall.py and its own new test file only. All mutations stay within declared files; `parallel: true`.
Do not change shared conftest files, rebuild extensions, or alter the environment.
Use the already-installed Pydantic v2 and pytest dependencies. No new dependency is needed.
Use strict type hints, Google-style docstrings, black (120 columns), and ruff on touched files.
Pure comparison helpers remain synchronous and perform no I/O.
Blueprint gaps are planning scaffolds only: completed implementation must contain no placeholders.

## Implementation Blueprint

### Steps (in order)
1. Declare the reporting field — because the strict layout model otherwise rejects configuration.
2. Set only the ink-wall default — because other planogram types must retain legacy labels.
3. Test registry defaults, nested freshness and partial overrides — because mutable/default merge regressions affect unrelated runs.

---

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py` (MODIFY)

```python
# REPLACE — extend definition import `from .comparison.definition import SlotsDefinition`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py:11)
# AFTER — add reporting field `    references: ReferencePolicy = Field(default_factory=ReferencePolicy)`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py:96)
# Replace the existing relative import with:
from .comparison.definition import ReportingPolicy, SlotsDefinition

# Inside LayoutProfile after references:
    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)
```

**Why**: A declared Pydantic field is required because extra fields are forbidden; default_factory keeps profiles independent.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` (MODIFY)

```python
# REPLACE — extend definition import `from ..comparison.definition import SlotsDefinition`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:14)
# AFTER — add reporting constructor argument `            required_descriptor_fields=list(_INK_REQUIRED),`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:76)
# Replace the existing relative import with:
from ..comparison.definition import ReportingPolicy, SlotsDefinition

# Add inside default_layout_profile's LayoutProfile constructor:
            reporting=ReportingPolicy(product_label="product", slot_presence=True),
```

**Why**: Only the ink-wall profile opts in. Keep all perception/identity settings unchanged.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_layout.py` (CREATE)

```python
"""Reporting defaults and configuration overrides for FEAT-645."""
import pytest
from parrot_pipelines.planogram.layout import resolve_layout_profile
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types.ink_wall import InkWall


def test_ink_wall_default_reporting() -> None:
    """Ink-wall enables model labels and independent presence defaults."""
    # FILL IN: product/True/0.9 plus fresh nested model per call (AC-1).
    pass


@pytest.mark.parametrize("kind", sorted(PlanogramCompliance._PLANOGRAM_TYPES))
def test_other_types_default_reporting(kind: str) -> None:
    """All registered types except ink-wall retain legacy reporting."""
    # FILL IN: check every registry entry; separately assert ink-wall opt-in (AC-2).
    pass


def test_layout_profile_reporting_override() -> None:
    """A partial override disables presence while preserving model labels."""
    # FILL IN: resolve layout_profile.reporting.slot_presence=False; no mutation (AC-3).
    pass
```

**Why**: Registry iteration protects defaults for all built-in types, while the existing resolver proves partial override behavior.

---

### FILL IN checklist

- [ ] Fill default/freshness, registry and resolver tests (AC-1/2/3).

---

## Acceptance Criteria

- [ ] AC-1: InkWall defaults are product/True/0.9, freshly allocated on each call.
- [ ] AC-2: Every other registered type defaults to display_name/False/0.9; no existing layout setting changes.
- [ ] AC-3: layout_profile.reporting partial overrides work through resolve_layout_profile, including disabling presence without resetting labels; inputs are not mutated.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_layout.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_layout_profile.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

Assert nested policy identity differs across fresh profiles; mutate one policy and verify another is unchanged. No pipeline/provider invocation is needed for default checks.

---

## Agent Instructions

1. Use `$sdd-start TASK-4168` to provision the feature worktree; never implement on `dev`.
2. Read the spec and this task; confirm dependencies are done in `sdd/tasks/index/planogram-ink-wall-slot-presence.json`.
3. Reverify imports, signatures and anchors; refresh the contract first if code moved.
4. Implement only the declared files from the blueprint, completing every FILL IN item.
5. Run Validation Commands; store test logs under `artifacts/logs/`. Run black and ruff on touched Python files.
6. Commit scoped code, then finalize using `scripts.sdd.finalize_task` with real
   `TaskCompletionEvidence` and the exact implementation HEAD, per the Codex adaptation contract.
   Do not use the legacy close_task.sh path or manually move this task/change its Completion Note.

## Completion Note

Populated by the task finalizer after implementation and verification.
