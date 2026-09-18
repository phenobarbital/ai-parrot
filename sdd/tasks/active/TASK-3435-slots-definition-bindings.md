# TASK-3435: SlotsDefinition models, loader, definition coverage and rule-binding validation

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3421
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9** (goal G9). `PlanogramConfig` says *what type* a planogram is; a separate
`slots_definition` (a dict — the JSONB column value — or a path to a JSON file) defines shelves,
slots, products and descriptors. For migrated types it **replaces**
`planogram_config.shelves[].products` as the expected-products reference. Non-product expectations
(illumination, text requirements, visual features, zone presence) stay in `planogram_config` and are
tied to the definition through explicit **rule bindings** (`planogram_config["rule_bindings"]`) that
target stable ids. This task creates the comparison package and the one module that parses,
normalises and validates all of that. Every later comparison task (registration, scoring, migration
tooling, identification vocabulary, verification) reads the models defined here.

`RuleBinding.rule_id` is the key under which the scoring stage later files a `RuleOutcome`
(`parrot_pipelines.planogram.contracts`, created by TASK-3421) — that is the only coupling to the
contracts module.

---

## Scope

- Create the package `parrot_pipelines/planogram/comparison/` (`__init__.py` with lazy-free, plain re-exports).
- Implement in `definition.py`: the Pydantic v2 models `Descriptors`, `FacingDefinition`,
  `ShelfDefinition`, `ZoneDefinition`, `RuleBinding`, `SlotsDefinition`; the exception
  `SlotsDefinitionError(ValueError)`; and the functions `load_slots_definition`,
  `definition_coverage`, `validate_bindings` with the exact signatures of the spec skeleton.
- Accept **two input layouts** and normalise both to `SlotsDefinition`:
  1. the *native* layout (`{"version", "meta", "shelves": [{"shelf_id", "shelf_number", "level", "facings": [...]}], "zones": [...]}`);
  2. the existing *page1* layout (`{"planogram": {...}, "shelves": [{"shelf", "shelf_number", "products": {"pos <shelf>:<n>": {...}}}]}`)
     — a position with `facings: n` expands to `n` `FacingDefinition`s with stable ids
     `p<position:03d>_f<index>`; shelf ids are `shelf_<shelf_number>`.
- Validation errors (all `SlotsDefinitionError`): slot sequence of a shelf is not exactly `1..n`;
  duplicate `facing_id` / `zone_id` / `shelf_id`; conflicting descriptors for one SKU (`product`);
  **zero described positions**; a shelf with neither facings nor zones.
- Undescribed facings are **legal** (descriptor-free facings stay in the definition); they are
  listed by `definition_coverage`, never fatal.
- `validate_bindings` reads `planogram_config["rule_bindings"]` and raises on a dangling
  `target_id`, an ambiguous `target_id` (matches ids in more than one namespace), a duplicate
  `rule_id`, or a zone-only shelf (no facings) that ends up with no bound rule. Rules are never
  silently dropped.
- Write the offline unit tests listed under Test Specification.

**NOT in scope**: the `PlanogramConfig.slots_definition` field itself (config task TASK-3426);
registration, scoring, projection; evaluating rules (`RuleOutcome` production); the conversion of
legacy configs into candidate definitions (migration-tooling task); price compliance; any LLM call.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/__init__.py` | CREATE | Package marker + re-exports of the definition API |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | CREATE | Models, loader, coverage, binding validation |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import json                                   # stdlib
from pathlib import Path                      # stdlib
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field, ValidationError   # pydantic v2 (workspace dependency)
```

### Existing Signatures to Use
```python
# Created by TASK-3421 (dependency) — packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
# (copied from spec §2 Data Models; re-read the file before relying on a field name)
class RuleOutcome(BaseModel):      # rule_id, assessed: bool, passed: Optional[bool], score: float, penalty: float, detail
# → RuleOutcome.rule_id == RuleBinding.rule_id. definition.py does NOT need to import contracts.
```

Algorithmic reference (**read-only, NEVER imported** — `plancheck` is not a package):
```python
# examples/planogram/plancheck/reference.py
def load_planogram(path: Path) -> PlanogramRef                       # :30  slots sorted by int(slot); must equal 1..n (:51-52);
                                                                     #      facing_id = f"p{position:03d}_f{index}" (:58); duplicate ids → ValueError (:74-75)
DESCRIPTOR_FIELDS = ("display_name","family","xl","colors","pack","identifiers","aliases","price")   # :96-105
def load_descriptors(path, planogram) -> tuple[Catalog, list[str], dict[str, Decimal]]   # :142  "described" == non-empty display_name;
                                                                     #      every described occurrence of one SKU must agree
```

`planogram_page1.json` layout (git-ignored; structure only — build a **synthetic** file in tests):
top level `{"planogram": {...}, "shelves": [...]}`; each shelf has `shelf`, `shelf_number`,
`product_count`, `facing_count`, `products` (dict keyed `"pos <shelf>:<n>"`); each position has
`position, segment, segment_number, slot, segment_slot, product, brand, shelf, facings, confidence,
read_method, notes` + descriptors `display_name, family, xl, colors, pack, identifiers, aliases, price`.

### Does NOT Exist
- ~~`parrot_pipelines/planogram/comparison/`~~ — this task creates it.
- ~~`PlanogramConfig.get_slots_definition()`~~ — no accessor on the config; the loader is a plain function.
- ~~a catalog file / `load_catalog()`~~ — descriptors live inside the definition JSON.
- ~~`from plancheck... import`~~ — the reference engine is a bare directory, not importable from the package.
- ~~`planogram_config["rule_bindings"]` in any existing config~~ — new key introduced by this feature; absent ⇒ `[]`.
- ~~a `price` requirement~~ — `price` is optional and never required for a position to count as described.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
- Pydantic v2 models, Google-style docstrings, strict type hints, 120-column lines, `logging.getLogger(__name__)`.
- `load_slots_definition` is **synchronous and does blocking file I/O** for a path source — its
  docstring must say "call via `asyncio.to_thread` from async code". Do not make it `async`.
- Normalise first (page1 → native dict), then build models, then run cross-object validation — one
  code path for validation regardless of the input layout.

### Key Constraints
- Every validation failure raises `SlotsDefinitionError` with a message naming the offending shelf /
  id — including a Pydantic `ValidationError` (wrap it: `raise SlotsDefinitionError(...) from exc`).
- "Described" == non-empty `descriptors.display_name`. "Sufficient descriptors" for
  `definition_coverage` == described **or** at least one non-empty `identifiers` entry.
- Two facings with the same `product` whose *described* descriptors differ ⇒ conflict. A described
  and an undescribed occurrence of the same SKU do **not** conflict (the described one wins for both).
- Ordering is part of the contract: shelves by `shelf_number`, facings by `(slot, facing_index)`.
- Tests run in a worktree with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` (shared venv is installed against the main checkout).

### References in Codebase
- `examples/planogram/plancheck/reference.py` — algorithmic reference only (see contract).
- `sdd/specs/new-planogram-pipeline.spec.md` §2 Data Models, §3 Module 9, §2 Scoring contract ("A shelf with neither expected facings nor bound rules is rejected").

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `comparison/__init__.py` exactly as below — *why*: later tasks import from the package root; keeping it a plain re-export avoids import cycles.
2. Create `definition.py` with the models first, then `SlotsDefinitionError`, then the three public functions — *why*: functions reference the models; the exception must exist before any validator raises it.
3. Implement `_normalise_page1` before `load_slots_definition` validation — *why*: a single validation path for both layouts is what keeps stable ids and error messages consistent.
4. Implement cross-object validation in `_validate` (slot sequence, duplicate ids, conflicting descriptors, zero described, empty shelf) — *why*: these are the exact failure modes the spec's acceptance criteria enumerate.
5. Implement `definition_coverage` and `validate_bindings` — *why*: coverage must be non-fatal, bindings must be fatal; keeping them separate functions preserves that difference.
6. Write the tests, run the validation command, then `ruff check` the two source files — *why*: TID251 import bans fail the merge gate.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/__init__.py` (CREATE)
```python
"""Comparison stage of the planogram cycle: slots definition, registration, scoring, projection."""
from .definition import (
    Descriptors,
    FacingDefinition,
    RuleBinding,
    ShelfDefinition,
    SlotsDefinition,
    SlotsDefinitionError,
    ZoneDefinition,
    definition_coverage,
    load_slots_definition,
    validate_bindings,
)

__all__ = [
    "Descriptors", "FacingDefinition", "RuleBinding", "ShelfDefinition", "SlotsDefinition",
    "SlotsDefinitionError", "ZoneDefinition", "definition_coverage", "load_slots_definition",
    "validate_bindings",
]
```
**Why this shape**: only names this task creates are exported. Later comparison tasks add their own
modules next to `definition.py` and import them by full module path — they must not need to edit
this file.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` (CREATE)
```python
"""Slots definition: what a fixture is expected to hold, plus the rule bindings that target it."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]
ZoneKind = Literal["header", "backlit", "poster", "box_stack"]


class SlotsDefinitionError(ValueError):
    """Invalid slots definition or rule bindings (fail fast at construction time)."""


class Descriptors(BaseModel):
    """Per-position product description. All optional; ``price`` is never required."""
    display_name: Optional[str] = None
    family: Optional[str] = None
    xl: Optional[bool] = None
    colors: List[str] = Field(default_factory=list)
    pack: Optional[int] = None
    identifiers: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    price: Optional[float] = None


class FacingDefinition(BaseModel):
    """One expected physical facing with a stable id."""
    facing_id: str
    shelf_id: str
    slot: int = Field(ge=1)
    product: str
    brand: Optional[str] = None
    facings: int = Field(default=1, ge=1)          # facing count of the source position (informational)
    facing_index: int = Field(default=1, ge=1)     # 1..facings
    position: Optional[int] = None                 # source position number (page1 layout)
    descriptors: Descriptors = Field(default_factory=Descriptors)


class ShelfDefinition(BaseModel):
    """One shelf; ``level`` matches ``ShelfConfig.level`` of planogram_config when both exist."""
    shelf_id: str
    shelf_number: int
    level: Optional[str] = None
    facings: List[FacingDefinition] = Field(default_factory=list)


class ZoneDefinition(BaseModel):
    """Non-product zone (header / backlit / poster / box stack) detected apart from product rows."""
    zone_id: str
    kind: ZoneKind
    shelf_id: Optional[str] = None
    required: bool = True


class RuleBinding(BaseModel):
    """Binds one non-product rule of planogram_config to a stable id of the definition."""
    rule_id: str
    kind: RuleKind
    target_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    mandatory: bool = True
```

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
class SlotsDefinition(BaseModel):
    """Versioned definition of shelves, facings and zones."""
    version: str = "1"
    meta: Dict[str, Any] = Field(default_factory=dict)
    shelves: List[ShelfDefinition]
    zones: List[ZoneDefinition] = Field(default_factory=list)

    def all_facings(self) -> List[FacingDefinition]:
        """Facings in shelf order, then (slot, facing_index)."""
        return [f for shelf in self.shelves for f in shelf.facings]


def _normalise_page1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the ``{"planogram": ..., "shelves": [{"products": {...}}]}`` layout to the native dict."""
    # FILL IN: build {"version": "1", "meta": data["planogram"], "shelves": [...], "zones": []};
    #   shelf_id = f"shelf_{shelf_number}"; per position expand `facings` n → n facing dicts with
    #   facing_id = f"p{int(position):03d}_f{index}", facing_index=index, descriptors from the 8 descriptor keys
    #   — bounded by: reference.py:30-81 id scheme; a missing "slot"/"position"/"product" key → SlotsDefinitionError
    raise NotImplementedError


def _validate(definition: SlotsDefinition) -> None:
    """Cross-object validation. Raises SlotsDefinitionError naming the offending shelf / id."""
    # FILL IN (in this order, first failure raises) — bounded by spec §3 Module 9 + AC "Slots definition validation rejects":
    #   1. duplicate shelf_id / zone_id / facing_id
    #   2. per shelf: sorted distinct `slot` values must equal 1..n (several facings may share a slot)
    #   3. a shelf with neither facings nor a zone whose shelf_id points at it
    #   4. conflicting DESCRIBED descriptors for one `product`
    #   5. zero described positions in the whole definition
    raise NotImplementedError


def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition:
    """Parse and validate a slots definition.

    Blocking file read for a path source — call via ``asyncio.to_thread`` from async code.

    Args:
        source: A dict (JSONB column value) or a path to a JSON file, in native or page1 layout.

    Returns:
        The validated definition; shelves ordered by ``shelf_number``, facings by ``(slot, facing_index)``.

    Raises:
        SlotsDefinitionError: unreadable / non-JSON source, schema error, or any rule of ``_validate``.
    """
    # FILL IN: read JSON when source is str|Path (OSError / JSONDecodeError → SlotsDefinitionError);
    #   detect page1 layout by the presence of a top-level "planogram" key or shelves[0]["products"];
    #   model_validate inside try/except ValidationError → SlotsDefinitionError; sort; _validate; log counts
    raise NotImplementedError


def definition_coverage(definition: SlotsDefinition) -> Tuple[float, List[str]]:
    """Return ``(fraction of facings with sufficient descriptors, undescribed facing_ids)``. Never raises."""
    # FILL IN: sufficient == non-empty display_name OR non-empty identifiers; a described occurrence of the
    #   same `product` elsewhere counts for every facing of that product — bounded by spec §2 "definition_coverage"
    raise NotImplementedError


def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:
    """Validate ``planogram_config["rule_bindings"]`` against the definition's stable ids.

    Raises:
        SlotsDefinitionError: malformed binding, duplicate ``rule_id``, dangling ``target_id``, ambiguous
            ``target_id`` (present in more than one of facing / zone / shelf namespaces), or a shelf with
            no facings that ends up with no bound rule.
    """
    # FILL IN: absent key → []; never drop a binding silently — every rejected binding raises
    raise NotImplementedError
```
**Why this shape**: model names, field names and the three function signatures come from spec §2
Data Models and the Module 9 Interface Skeleton and are not renegotiable. `facing_index` and
`position` are additive fields needed to make the page1 expansion reversible and the ids stable;
`facings` keeps the spec's name and records the source position's facing count. The empty-shelf
rule is split on purpose: the loader rejects "neither facings nor zones", `validate_bindings`
rejects "zone-only shelf with no bound rule" — together they implement the spec's "neither expected
facings nor bound rules" without the loader needing `planogram_config`.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py` (CREATE)
See **Test Specification** below — write that scaffold to disk and complete the bodies.

**Why**: the folder has no `__init__.py` by design (unique test basenames); do not add one.

### FILL IN checklist
- [ ] `definition.py::_normalise_page1` — page1 → native dict with stable ids; bounded by the reference id scheme (`p<position:03d>_f<index>`, `shelf_<n>`)
- [ ] `definition.py::_validate` — the five checks in the stated order; bounded by the acceptance criteria list
- [ ] `definition.py::load_slots_definition` — source handling, layout detection, error wrapping, ordering
- [ ] `definition.py::definition_coverage` — sufficiency rule; never raises
- [ ] `definition.py::validate_bindings` — dangling / ambiguous / duplicate / unbound zone-only shelf
- [ ] `test_slots_definition.py` — every test body

---

## Acceptance Criteria

- [ ] `from parrot_pipelines.planogram.comparison import load_slots_definition, SlotsDefinition, RuleBinding, validate_bindings, definition_coverage, SlotsDefinitionError` works.
- [ ] A dict and a path to a JSON file with the same content load to equal `SlotsDefinition`s.
- [ ] A synthetic file in the page1 layout normalises to stable ids (`p001_f1`, `shelf_1`, …); a position with `facings: 2` yields two facings.
- [ ] Rejected with `SlotsDefinitionError`: non-`1..n` slot sequence, duplicate facing/zone/shelf id, conflicting described descriptors for one SKU, zero described positions, shelf with neither facings nor zones.
- [ ] Undescribed facings load fine and are listed by `definition_coverage` (fraction + ids); it never raises.
- [ ] `validate_bindings` raises on dangling, ambiguous and duplicate bindings and on a zone-only shelf without a bound rule; returns `[]` when the key is absent.
- [ ] No import of `plancheck`, `requests`, `httpx`; no `print`.
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py
import copy
import json

import pytest

from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError, definition_coverage, load_slots_definition, validate_bindings,
)


@pytest.fixture
def native_definition() -> dict:
    """2 shelves x 3 facings (2 described, 1 undescribed per shelf) + one required header zone on its own shelf."""
    # FILL IN: build the dict by hand; shelf ids shelf_1, shelf_2, shelf_header; zone id zone_header
    raise NotImplementedError


@pytest.fixture
def page1_definition() -> dict:
    """Synthetic file in the planogram_page1.json layout: 1 shelf, 3 positions, one with facings=2."""
    raise NotImplementedError


def test_loads_dict_and_path_equally(native_definition, tmp_path): ...
def test_slots_definition_accepts_page1_layout(page1_definition): ...          # stable ids, 4 facings
def test_slots_definition_validation_errors(native_definition): ...            # parametrise the 5 failure modes
def test_undescribed_facings_are_legal_and_listed(native_definition): ...      # definition_coverage == (4/6, [...])
def test_described_elsewhere_counts_for_same_product(native_definition): ...
def test_rule_bindings_reject_dangling_and_ambiguous(native_definition): ...   # + duplicate rule_id
def test_zone_only_shelf_without_binding_is_rejected(native_definition): ...
def test_missing_rule_bindings_key_returns_empty(native_definition): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Data Models, §3 Module 9) for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read the reference file lines quoted above; never import from `plancheck`
4. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   and never change a signature or path the blueprint fixes
5. **Verify** all acceptance criteria are met; run the Validation Command with the `PYTHONPATH` prefix from Implementation Notes
6. Commit only the three files listed above; never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
