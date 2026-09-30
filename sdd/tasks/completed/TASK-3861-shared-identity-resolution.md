# TASK-3861: Shared descriptor-aware identity resolution and verify-pass evidence gating

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3860
**Assigned-to**: unassigned

---

## Context

Spec §2 **Stage 3** identity paragraph and §3 **Module 4** skeleton (`comparison/identity.py`).
Identity resolution — mapping what a photo showed to exactly one catalogue product id of the slots
definition — lives today inside `types/ink_wall.py:74-146` (`resolve_identity`) with the ink
vocabulary hardcoded (`family` + non-contradicting `colors`/`pack`/`xl`, resolution only when `xl`
was read). `ProductOnShelves` imports it from `ink_wall` (`product_on_shelves.py:45`). FEAT-612 makes
it a shared, profile-driven function: the profile chooses the descriptor vocabulary and required
fields, custom `Descriptors.attributes` (TASK-3860) take part, and expected-empty positions are never
identity anchors. The optional closed-set verify pass (`identification/verify.py`) must equally skip
expected-empty positions and never treat an offered candidate as evidence. TASK-3864 later re-points
the historical `ink_wall.resolve_identity` name to this module; this task does NOT edit `ink_wall.py`.

---

## Scope

- Create `comparison/identity.py` with `resolve_identity(identification, definition, *, vocabulary,
  required_fields)` exactly as the M4 skeleton, preserving the three ordered rules of the ink
  implementation: (1) exact read identifier, (2) non-contradicting required-descriptor signature,
  (3) fuzzy alias (`rapidfuzz.fuzz.token_set_ratio >= 92`). Never uses the expected facing of a slot;
  several matches ⇒ unresolved with candidates.
- With the default arguments the result must equal today's `ink_wall.resolve_identity` for every input
  (behavioral parity; verified by a parity test).
- Generic behavior: vocabulary/required fields may name typed descriptor fields or custom
  `Descriptors.attributes` keys; `required_fields=()` disables the signature step.
- Exclude facings with `expected_occupancy == "empty"` from every rule.
- In `identification/verify.py`: exclude expected-empty facings from `pick_candidates`, compare
  custom attributes the read carries, skip identifications observed `occupancy == "empty"` in
  `verify_unresolved`; keep the evidence gate (`_evidence_supports`) unchanged.
- Create `tests/planogram_cycle/test_comparison_identity.py` covering identity and verify gating.

**NOT in scope**: editing `types/ink_wall.py` or `types/product_on_shelves.py` (TASK-3864 re-points the
alias; TASK-3865 migrates POS); scoring (TASK-3862); rule evaluation and the compare stage
(TASK-3863); reference-image matching (TASK-3858); `LayoutProfile.descriptor_fields` wiring
(callers pass `vocabulary=profile.descriptor_fields or default`, done by the type tasks). Do not change
the public signatures of `pick_candidates` / `verify_unresolved`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/identity.py` | CREATE | Shared `resolve_identity` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py` | MODIFY | Skip expected-empty facings / observed-empty slots; attribute comparison |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py` | CREATE | Parity, generic vocabulary, empty exclusion, verify gating |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from rapidfuzz import fuzz                                                          # used at ink_wall.py:12
from parrot_pipelines.planogram.contracts import Identification                     # contracts.py:101
from parrot_pipelines.planogram.comparison.definition import Descriptors, FacingDefinition, SlotsDefinition  # definition.py:33, 56, 98
from parrot_pipelines.planogram.types.ink_wall import resolve_identity as ink_resolve_identity  # ink_wall.py:74 (TEST ONLY, parity)
from parrot_pipelines.planogram.identification.verify import (CHOICE_CANNOT_TELL, VerificationAnswer,
    pick_candidates, verify_unresolved)                                             # verify.py:26, 31, 55, 205
```
`comparison/identity.py` must NOT import any `types/*` module (spec §7: shared stages never import
concrete types; `ink_wall.py` will import this module in TASK-3864 — importing back would be a cycle).

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py  (REFERENCE — port, do not edit)
ALIAS_MIN_RATIO = 92.0                                                              # :44
_LINE_SPLIT = re.compile(r"\s*(?:\n|\|)\s*")                                        # :48
def _norm(text: Optional[str]) -> str                                               # :51-53 (casefold/strip, "" for None)
def _text_lines(identification: Identification) -> List[str]                       # :56-62 (product, text, evidence lines)
def _dedupe(facings: Sequence[FacingDefinition]) -> List[str]                       # :65-71 (distinct product ids, order kept)
def resolve_identity(identification: Identification, definition: SlotsDefinition) -> Tuple[Optional[str], List[str]]  # :74-146
    # brand filter :87-91; rule 1 identifiers :94-101; rule 2 signature :103-127; rule 3 alias :129-146

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:101-114
class Identification(BaseModel): shape_id, image_id, product, brand, text, descriptors: Dict[str, Any],
                                 occupancy: str = "unknown", raw_confidence, evidence: List[str], source, uncertain

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py
_COMPARABLE_FIELDS = ("family", "xl", "pack")                                        # :28
def _norm(value: object) -> Optional[str]                                            # :39-44
def _partial_read(identification: Identification) -> bool                           # :47-52
def pick_candidates(identification, definition, n: int) -> List[FacingDefinition]    # :55-88
    # read = {k: _norm(...) for k in _COMPARABLE_FIELDS}  :71 ; loop `for facing in definition.all_facings():` :73
    # brand check :74 ; contradiction loop `for key, observed in read.items():` :77-81 ; sort by (not described, product) :87
def _evidence_supports(answer, candidate, others=()) -> bool                         # :107-129 (KEEP UNCHANGED)
async def verify_unresolved(image, identifications, definition, ctx, *, n_distractors: int = 3,
                            boxes=None) -> List[Identification]                      # :205-247
    # skip resolved `if ident.product is not None and not ident.uncertain:` :235
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3860 — comparison/definition.py
class Descriptors(BaseModel): ...; attributes: Dict[str, str | int | float | bool | List[str]] = {}
class FacingDefinition(BaseModel): ...; product: Optional[str] = None; expected_occupancy: Literal["occupied", "empty"] = "occupied"
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.comparison.identity`~~ — this task creates it.
- ~~A slot / facing / position parameter on `resolve_identity`~~ — never add one (spec: "Never select by expected slot").
- ~~`Identification.reference_id` used for identity here~~ — reference mapping is TASK-3858's; ignore it.
- ~~`LayoutProfile` import in identity.py~~ — callers pass plain sequences; keep this module profile-agnostic.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/identity.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#resolve_identity",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#_text_lines",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#_dedupe",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Identification",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#Descriptors",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#FacingDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py#pick_candidates",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py#verify_unresolved",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py#_evidence_supports",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py#_partial_read"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Port `ink_wall.py:51-146` into `identity.py` and generalize ONLY rule 2. The generalization that
reproduces the ink behavior exactly with `vocabulary=("family","colors","pack","xl")`,
`required_fields=("family","xl")`:

- **Anchor field** = `required_fields[0]` (ink: `family`). The signature step runs only when the
  read value of the anchor is observed (not `None`, `""`, `[]`). A facing is a candidate only when
  its expected anchor value is present AND agrees with the read.
- **Other compared fields** = the ordered union of `vocabulary` and `required_fields` minus the
  anchor. A facing is dropped only on a *contradiction*: both the read and the expected value are
  present and they disagree (ink: `colors`, `pack`, `xl`).
- **Resolution gate**: exactly one distinct product AND every required field observed in the read
  ⇒ resolved; otherwise ⇒ `(None, candidates)` (ink: an unknown `xl` yields candidates only).
  When the signature step yields candidates it RETURNS (does not fall through to aliases) — exactly
  as `ink_wall.py:122-127`.
- `required_fields=()` ⇒ the signature step is skipped entirely (spec §7: "no required fields means
  the signature step is disabled and resolution relies on identifiers/aliases/reference evidence").
- **Value lookup**: a field that is a typed `Descriptors` field (any of `Descriptors.model_fields`
  except `attributes`) is read with `getattr(descriptors, field)`; any other name is read from
  `descriptors.attributes.get(field)`.
- **Agreement** (`_agrees(read, expected)`): list vs list ⇒ equal sets of `_norm`ed items;
  expected list vs read scalar ⇒ `_norm(read)` in that set; expected `bool` ⇒ `bool(read) == expected`;
  otherwise ⇒ `_norm(str(read)) == _norm(str(expected))` (ink `pack` compares via `str`).

### Key Constraints
- Pool = facings of the definition with `expected_occupancy == "occupied"` (spec §2 Stage 3: expected-empty
  positions are not product identity anchors), then brand-filtered exactly as `ink_wall.py:87-91`.
- Deterministic: `_dedupe` keeps definition order; no sets in the returned candidate list.
- Pure function: no logging of product text at INFO, no I/O, no mutation of the identification.
- `verify.py` changes are minimal: (a) `pick_candidates` skips `facing.expected_occupancy == "empty"`
  (their `product` may be `None`, which would also break the `(not described, product)` sort at `:87`);
  (b) `read` also includes every key the identification's `descriptors` shares with the facing's
  `descriptors.attributes`, compared with `_norm` for contradiction; (c) `verify_unresolved` skips
  identifications with `occupancy == "empty"` — an observed-empty slot has nothing to verify.
  `_evidence_supports`, `_prompt`, `option_order`, `VERIFY_PROMPT_VERSION` stay byte-identical (the
  evidence gate is what guarantees "offered candidates are never evidence"; changing the prompt would
  also invalidate vision cache keys).
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### Transitional note
`test_ink_wall.py::test_resolve_identity_never_reads_expected_facing` pins the parameter list of
`ink_wall.resolve_identity` to `["identification", "definition"]`; this task does not change that
function, so the test stays green. TASK-3864 re-points the alias and updates that test.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:74-146` — implementation to port
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:186-229` — identity behaviors to mirror
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py:34-53, 60-120` — verify stubs / definition fixture pattern

---

## Implementation Blueprint

### Steps (in order)
1. Create `identity.py` with the ported helpers (`_norm`, `_text_lines`, `_dedupe`) — *why*: identical text normalization keeps parity.
2. Add `_expected`, `_observed`, `_agrees` — *why*: one value model for typed fields and custom attributes.
3. Write `resolve_identity` rules 1→2→3 on the occupied, brand-filtered pool — *why*: spec §2 ordered rules.
4. Patch `verify.py` (three small edits) — *why*: expected-empty positions never offered; observed-empty never verified.
5. Write the tests (parity first), run the validation commands.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/identity.py` (CREATE)
```python
"""Shared, descriptor-aware identity resolution: photo evidence -> one catalogue product id (FEAT-612)."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

from ..contracts import Identification
from .definition import Descriptors, FacingDefinition, SlotsDefinition

ALIAS_MIN_RATIO = 92.0
DEFAULT_VOCABULARY: Tuple[str, ...] = ("family", "colors", "pack", "xl")
DEFAULT_REQUIRED_FIELDS: Tuple[str, ...] = ("family", "xl")
_LINE_SPLIT = re.compile(r"\s*(?:\n|\|)\s*")
_TYPED_FIELDS = frozenset(Descriptors.model_fields) - {"attributes"}


def _norm(text: Optional[str]) -> str:
    """Casefold/strip; empty string for None."""
    return str(text).casefold().strip() if text else ""


def _text_lines(identification: Identification) -> List[str]:
    """Normalised text lines the identification carries: read product, text (OCR/LLM) and evidence."""
    # FILL IN: port ink_wall.py:56-62 verbatim


def _dedupe(facings: Sequence[FacingDefinition]) -> List[str]:
    """Distinct product ids in definition order."""
    # FILL IN: port ink_wall.py:65-71 verbatim


def _observed(value: Any) -> bool:
    """A read value counts as observed unless it is None, "" or an empty list/dict (False IS observed)."""
    return value is not None and value != "" and value != [] and value != {}


def _expected(descriptors: Descriptors, field: str) -> Any:
    """Expected value of ``field``: a typed descriptor field, else a custom attribute (None when absent)."""
    return getattr(descriptors, field) if field in _TYPED_FIELDS else descriptors.attributes.get(field)


def _agrees(read: Any, expected: Any) -> bool:
    """Whether a read value agrees with an expected one (rules of the task's Implementation Notes)."""
    # FILL IN: list/list sets; expected list vs scalar membership; bool; str-normalised equality


def resolve_identity(identification: Identification, definition: SlotsDefinition, *,
                     vocabulary: Sequence[str] = ("family", "colors", "pack", "xl"),
                     required_fields: Sequence[str] = ("family", "xl")) -> tuple[str | None, list[str]]:
    """Resolve photo evidence to one catalogue id, or return unresolved candidates; no slot expectation.

    Rules in order — identifier, descriptor signature, alias. Several matches => (None, candidates);
    nothing => (None, []). Expected-empty facings never participate.

    Args:
        identification: What the model / OCR read for one observed target.
        definition: The slots definition (the only catalogue of product ids and descriptors).
        vocabulary: Descriptor fields compared for contradictions (typed fields or custom attribute keys).
        required_fields: Fields whose observation gates a signature resolution; the first one anchors the step.

    Returns:
        ``(product_id, candidates)``.
    """
    facings = [f for f in definition.all_facings() if f.expected_occupancy == "occupied"]
    brand = _norm(identification.brand)
    pool = [f for f in facings if not brand or _norm(f.brand) == brand]
    if brand and not pool:
        return None, []
    lines = set(_text_lines(identification))
    # FILL IN: rule 1 — port ink_wall.py:94-101
    # FILL IN: rule 2 — generalized signature (anchor = required_fields[0]; contradiction on the other fields;
    #          resolve only when one id AND every required field observed; return candidates otherwise) — spec §2/§7
    # FILL IN: rule 3 — port ink_wall.py:129-145 with ALIAS_MIN_RATIO
    return None, []
```
**Why this shape**: the signature is the M4 skeleton verbatim (keyword-only `vocabulary` /
`required_fields` with the ink defaults), so TASK-3864 can re-export it from `ink_wall.py` with a plain
import and the other types can pass their profile vocabulary. `DEFAULT_VOCABULARY` / `DEFAULT_REQUIRED_FIELDS` are exported constants for callers; keep the
literal defaults in the signature equal to them.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc '    for facing in definition.all_facings():' verify.py)
# AFTER — insert as the FIRST statement of that loop body, above `        if brand and _norm(facing.brand) != brand:`
# (verified: verify.py:73-74, inside pick_candidates)
        if facing.expected_occupancy == "empty":
            continue  # an expected-empty position is never an offered product
```
```python
# occurrences: 1 (verified: grep -Fxc '        for key, observed in read.items():' verify.py)
# AFTER the existing contradiction loop (verify.py:77-81) and BEFORE `        if contradicts:` (verify.py:82), insert:
        for key, value in facing.descriptors.attributes.items():
            observed = _norm(identification.descriptors.get(key))
            expected = _norm(value)
            if observed and expected and observed != expected:
                contradicts = True
                break
```
```python
# occurrences: 1 (verified: grep -Fxc '        if ident.product is not None and not ident.uncertain:' verify.py)
# BEFORE — insert above that line (verified: verify.py:235, inside verify_unresolved's loop)
        if ident.occupancy == "empty":
            continue  # observed empty: nothing to verify, never offer candidates for it
```
**Why**: three single-occurrence anchors, no signature change, evidence gate untouched. List-valued
attributes compare through `_norm(str(list))` in this block — acceptable because a contradiction only
*removes* a candidate and a missing read never contradicts; do not add more logic here.
Also update the docstrings of `pick_candidates` ("expected-empty facings are never candidates") and
`verify_unresolved` ("Untouched when: ... observed empty ...").

### FILL IN checklist
- [ ] `_text_lines`, `_dedupe` — verbatim ports; bounded by parity test.
- [ ] `_agrees` — value rules of Implementation Notes.
- [ ] `resolve_identity` rules 1-3 — parity with `ink_wall.resolve_identity` for the defaults (AC7, AC8).
- [ ] `verify.py` three edits — AC7.

---

## Acceptance Criteria

- [ ] `resolve_identity` with default arguments returns the same tuple as `ink_wall.resolve_identity` for
      every identification in the parity table (identifier, signature with/without `xl`, several families,
      alias, unknown brand, nothing read).
- [ ] The function has no slot/facing parameter; the same reading resolves identically for any `shape_id` (spec §2).
- [ ] `required_fields=()` disables the signature step (a family-only read resolves nothing without identifiers/aliases).
- [ ] A custom attribute in `vocabulary` / `required_fields` can resolve a product; a contradicting attribute excludes it.
- [ ] Expected-empty facings are never returned as a resolution or candidate by `resolve_identity` or `pick_candidates` (AC7/AC9).
- [ ] `verify_unresolved` makes no vision call for an identification observed `occupancy="empty"`; an offered
      choice without supporting visible text still leaves the identification untouched (AC7).
- [ ] `comparison/identity.py` imports no `types/*` module.
- [ ] Validation commands pass; `ruff check` and `black --check` clean.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/identity.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/identity.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_comparison_identity.py
"""Shared identity resolution and verify-pass evidence gating (FEAT-612, Module 4)."""

import inspect

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.comparison.identity import resolve_identity
from parrot_pipelines.planogram.contracts import CycleContext, Identification
from parrot_pipelines.planogram.identification.verify import VerificationAnswer, pick_candidates, verify_unresolved
from parrot_pipelines.planogram.types.ink_wall import resolve_identity as ink_resolve_identity

BOX = DetectionBox(x1=10, y1=10, x2=60, y2=60, confidence=1.0)
IMAGE = np.full((100, 100, 3), 200, np.uint8)


class _InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class _CountingAdapter:
    """Vision stub: records calls, answers from a queue."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append(stage)
        return self.answers.pop(0)


def _definition(extra_facings=()) -> "SlotsDefinition":
    """Generic synthetic catalogue: two families, xl variants, one custom attribute, optional extras."""
    facings = [
        {"facing_id": "f1", "shelf_id": "s1", "slot": 1, "product": "P-1", "brand": "Acme",
         "descriptors": {"display_name": "P one", "family": "F1", "xl": False, "identifiers": ["ID-1"],
                         "attributes": {"finish": "matte"}}},
        {"facing_id": "f2", "shelf_id": "s1", "slot": 2, "product": "P-2", "brand": "Acme",
         "descriptors": {"display_name": "P two", "family": "F1", "xl": True, "aliases": ["Acme Mega Bottle"],
                         "attributes": {"finish": "gloss"}}},
        {"facing_id": "f3", "shelf_id": "s1", "slot": 3, "product": "P-3", "brand": "Acme",
         "descriptors": {"display_name": "P three", "family": "F2"}},
        *extra_facings,
    ]
    return load_slots_definition({"shelves": [{"shelf_id": "s1", "shelf_number": 1, "facings": facings}]})


def _ident(**kwargs) -> Identification:
    return Identification(shape_id="s", image_id="img0", **kwargs)


PARITY_READS = [
    dict(brand="Acme", text="ID-1"),
    dict(brand="Acme", descriptors={"family": "f1"}),
    dict(brand="Acme", descriptors={"family": "f1", "xl": True}),
    dict(brand="Acme", descriptors={"family": "F2", "xl": False}),
    dict(brand="Acme", text="acme mega bottle 2"),
    dict(brand="Other", text="ID-1"),
    dict(brand="Acme"),
]


@pytest.mark.parametrize("read", PARITY_READS)
def test_default_arguments_match_ink_wall(read):
    definition = _definition()
    assert resolve_identity(_ident(**read), definition) == ink_resolve_identity(_ident(**read), definition)


def test_no_slot_parameter_and_shape_id_independent():
    assert list(inspect.signature(resolve_identity).parameters) == [
        "identification", "definition", "vocabulary", "required_fields"]
    # FILL IN: same read with shape_id "a" and "b" resolves identically


def test_required_fields_empty_disables_signature():
    # FILL IN: resolve_identity(_ident(brand="Acme", descriptors={"family": "F2"}), _definition(),
    #          required_fields=()) == (None, [])


def test_custom_attribute_resolves_and_contradicts():
    # FILL IN: vocabulary=("family", "finish"), required_fields=("family", "finish"):
    #          {"family": "F1", "finish": "matte"} -> ("P-1", ["P-1"]); {"family": "F1", "finish": "satin"} -> (None, [])


def test_expected_empty_facing_never_candidate():
    empty = {"facing_id": "f4", "shelf_id": "s1", "slot": 4, "product": None, "expected_occupancy": "empty",
             "brand": "Acme", "descriptors": {"family": "F2"}}
    definition = _definition([empty])
    assert resolve_identity(_ident(brand="Acme", descriptors={"family": "F2", "xl": False}), definition) == \
        ("P-3", ["P-3"])
    assert all(f.facing_id != "f4" for f in pick_candidates(_ident(brand="Acme", uncertain=True), definition, 5))


async def test_verify_skips_observed_empty_slot():
    adapter = _CountingAdapter()
    ctx = CycleContext(vision=adapter, executor=_InlineExecutor())
    ident = _ident(brand="Acme", occupancy="empty", uncertain=True)
    result = await verify_unresolved(IMAGE, [ident], _definition(), ctx, boxes={"s": BOX})
    assert result[0] is ident and adapter.calls == []


async def test_offered_candidate_without_visible_text_is_not_evidence():
    # FILL IN: VerificationAnswer(choice="P-1", visible_text=[]) -> identification unchanged, still uncertain


def test_pick_candidates_attribute_contradiction():
    # FILL IN: read descriptors {"family": "F1", "finish": "gloss"} -> candidates contain P-2, not P-1
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3861 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean; coder-reported task tests pass.

