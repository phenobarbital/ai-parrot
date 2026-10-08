# TASK-4166: Preserve descriptor SKU in native and page1 definitions

**Feature**: FEAT-645 — Planogram Ink Wall — model-based labels and slot presence
**Spec**: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec §3 M1. The loader currently discards SKU, so presence cannot expose a stable secondary identifier.

## Scope

- Add optional SKU and int/string normalization to Descriptors.
- Include SKU in page1 descriptor extraction.
- Add loader and collision regression tests without changing existing assertions.

**NOT in scope**: scoring/credit/status changes, vision identification improvements, database writes,
flowtask persistence, dependencies, or files outside the table below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | SKU field, validator and page1 key |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_sku.py` | CREATE | SKU parsing tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` during decomposition, 2026-10-08. Recheck anchors after dependencies land.
Existing imports below are verified in their source modules or installed dependencies.
Imports explicitly tagged with a task ID are planned dependency interfaces, not existing symbols at planning time.
Retain unrelated existing imports in MODIFY targets.

### Verified Imports

```python
from typing import Any, Optional, Tuple
from pydantic import field_validator  # installed Pydantic 2.12.5
import pytest
from parrot_pipelines.planogram.comparison.definition import Descriptors, SlotsDefinitionError, load_slots_definition
```

### Existing Signatures to Use

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:45` — `Descriptors`: optional descriptor model; _no_typed_collision at 59 rejects keys shadowing typed fields
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:41` — `SlotsDefinitionError`: ValueError subclass
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:144` — `_normalise_page1`: extracts descriptor keys at 168 before expanding facings
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:280` — `load_slots_definition`: (source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition; wraps ValidationError

### Does NOT Exist

- `Descriptors.sku` and `_sku_to_str` do not exist yet.
- `_DESCRIPTOR_KEYS` has no SKU entry. Do not invent a separate SKU resolver.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_sku.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#Descriptors",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinitionError",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#_normalise_page1",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition"
  ]
}
```

## Implementation Notes

Ops merge prerequisite from spec §7: the owner must check stored definitions for descriptors.attributes.sku collisions. Do not query or mutate production data as part of this task.

**Parallelism**: No task dependencies: modifies definition.py and creates test_descriptor_sku.py; no other root task writes these files. All mutations stay within declared files; `parallel: true`.
Do not change shared conftest files, rebuild extensions, or alter the environment.
Use the already-installed Pydantic v2 and pytest dependencies. No new dependency is needed.
Use strict type hints, Google-style docstrings, black (120 columns), and ruff on touched files.
Pure comparison helpers remain synchronous and perform no I/O.
Blueprint gaps are planning scaffolds only: completed implementation must contain no placeholders.

## Implementation Blueprint

### Steps (in order)
1. Add SKU extraction and normalization — because native and page1 must yield the same typed value.
2. Retain _no_typed_collision and add focused tests — because accepting ambiguous attributes.sku would hide a schema error.
3. Run new tests and existing definition tests — because SKU must not alter other descriptor rules.

---

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` (MODIFY)

```python
# AFTER — add separate import `from pydantic import BaseModel, Field, ValidationError, model_validator`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:10)
# MODIFY — append sku inside tuple `_DESCRIPTOR_KEYS: Tuple[str, ...] = (`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:28)
# AFTER — insert field and validator in Descriptors `    display_name: Optional[str] = None`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:48)
from pydantic import field_validator

# Replace _DESCRIPTOR_KEYS with the complete tuple, retaining every existing key:
_DESCRIPTOR_KEYS: Tuple[str, ...] = (
    "display_name", "family", "xl", "colors", "pack", "identifiers",
    "aliases", "price", "attributes", "sku",
)
# Inside Descriptors, after display_name:
    sku: Optional[str] = None

    @field_validator("sku", mode="before")
    @classmethod
    def _sku_to_str(cls, value: Any) -> Optional[str]:
        """Normalize integer/string SKUs; treat absent or blank values as missing."""
        # FILL IN: normalize None/int/str; reject other input types (AC-1).
        # Preserve zero and leading zeroes in string inputs; strip whitespace.
        pass
```

**Why**: Typed SKU must survive both loaders, and the existing collision validator must continue to protect typed fields.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_sku.py` (CREATE)

```python
"""SKU preservation and normalization for FEAT-645."""
from typing import Any
import pytest
from parrot_pipelines.planogram.comparison.definition import Descriptors, SlotsDefinitionError, load_slots_definition


@pytest.mark.parametrize("value, expected", [(6347569, "6347569"), (0, "0"), (" 00123 ", "00123"), (" ", None), (None, None)])
def test_descriptor_sku_normalization(value: Any, expected: str | None) -> None:
    """Retain identifiers without losing zeroes or representing absence as text."""
    # FILL IN: direct-model assertion and missing-field default (AC-1).
    pass


@pytest.mark.parametrize("layout", ["native", "page1"])
def test_descriptor_sku_kept_native_and_page1(layout: str) -> None:
    """Both supported definition shapes preserve numeric and string SKUs."""
    # FILL IN: independent valid fixture with slots 1..n and display_name (AC-2).
    pass


def test_descriptor_sku_attribute_collision() -> None:
    """The new typed field cannot be shadowed in custom attributes."""
    # FILL IN: loader raises SlotsDefinitionError for attributes.sku (AC-3).
    pass
```

**Why**: Use valid tiny loader inputs to isolate SKU behavior from definition coverage validation.

---

### FILL IN checklist

- [ ] Implement SKU normalization and bad-type handling (AC-1).
- [ ] Build native/page1 fixtures and collision test (AC-2/3).

---

## Acceptance Criteria

- [ ] AC-1: Missing/blank SKU is None; integer 6347569 becomes "6347569"; string whitespace is stripped, leading zeroes retained; unsupported types are rejected.
- [ ] AC-2: Both native descriptors.sku and page1 product-level sku survive loading and model_dump; input mappings are not mutated.
- [ ] AC-3: Existing attributes collision protection rejects attributes.sku; existing definition tests pass without changed assertions.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_descriptor_sku.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py -q`

---

## Test Specification

Use native descriptors and page1 products fixtures with positive contiguous slots and at least one display_name. Include multi-facing page1 expansion: each expanded facing retains SKU.

---

## Agent Instructions

1. Use `$sdd-start TASK-4166` to provision the feature worktree; never implement on `dev`.
2. Read the spec and this task; confirm dependencies are done in `sdd/tasks/index/planogram-ink-wall-slot-presence.json`.
3. Reverify imports, signatures and anchors; refresh the contract first if code moved.
4. Implement only the declared files from the blueprint, completing every FILL IN item.
5. Run Validation Commands; store test logs under `artifacts/logs/`. Run black and ruff on touched Python files.
6. Commit scoped code, then finalize using `scripts.sdd.finalize_task` with real
   `TaskCompletionEvidence` and the exact implementation HEAD, per the Codex adaptation contract.
   Do not use the legacy close_task.sh path or manually move this task/change its Completion Note.

## Completion Note

Populated by the task finalizer after implementation and verification.
