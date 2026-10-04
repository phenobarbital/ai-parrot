# TASK-4005: Evaluate fact_tag_present in evaluate_rules

**Feature**: FEAT-624 — Planogram `fact_tag_present` rule
**Spec**: `sdd/specs/planogram-fact-tag-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4003, TASK-4004
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and the outcome table in spec §2. Implements `_rule_fact_tag` and dispatches
`fact_tag_present` bindings to it. Evaluation uses only perceptions, identifications and image
registrations — no provider call, no `RuleObservation`.

---

## Scope

- Add `_rule_fact_tag(binding, perceptions, identifications, registrations) -> RuleOutcome` to
  `comparison/rules.py`.
- Add the `elif binding.kind == "fact_tag_present"` branch to `evaluate_rules`.
- Write the tests listed below.

**NOT in scope**: routing the outcome in scoring/projection (TASK-4006). The outcome is returned
in the `evaluate_rules` dict like any other rule; where it lands is TASK-4006's job.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | `_rule_fact_tag` + dispatch |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_rule.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in comparison/rules.py (lines 12-25): RuleBinding, SlotsDefinition, ImageRegistration,
#   CycleContext, FixtureMembership, Identification, IdentificationResult, ObservationRef,
#   ObservationSource, PerceptionResult, RuleObservation, RuleOutcome, Shape
from parrot_pipelines.planogram.contracts import ShapeKind, Slot  # verified: contracts.py:15,68 — ADD to the contracts import
from parrot_pipelines.planogram.comparison.tags import slot_above, tag_price, tag_text  # created by TASK-4004
from parrot_pipelines.planogram.comparison.definition import RuleBinding  # verified: comparison/definition.py:118
from parrot_pipelines.planogram.comparison.registration import ImageRegistration  # verified: comparison/registration.py:35
from parrot_pipelines.planogram.comparison.rules import evaluate_rules  # verified: comparison/rules.py:459
from parrot.models.detections import DetectionBox  # verified: packages/ai-parrot/src/parrot/models/detections.py:37
```

### Existing Signatures to Use
```python
# comparison/rules.py
def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome:                       # line 100
def _ref(image_id: str, target_id: str, source: ObservationSource) -> ObservationRef:   # line 105
def _dedupe_refs(refs: Sequence[ObservationRef]) -> List[ObservationRef]:               # line 110
def _rule_zone_present(...) -> RuleOutcome:   # line 280 — shape to mirror
def evaluate_rules(perceptions, identifications, registrations, ctx: CycleContext) -> Dict[str, RuleOutcome]:  # line 459
    #   reads ctx.definition, ctx.layout, ctx.bindings, ctx.errors
    #   else branch (line 485): outcome = _unassessed(binding, "unknown rule kind")

# comparison/registration.py:35
class ImageRegistration(BaseModel):
    image_id: str
    row_to_shelf: Dict[int, str]
    assignments: Dict[str, str]   # Identification.shape_id (a Shape.shape_id OR a Slot.slot_id) -> facing_id
    ambiguous: bool = False

# contracts.py
class Shape: shape_id, image_id, kind: ShapeKind, box, ocr_text, source: ObservationSource, membership: FixtureMembership  # line 51
class Slot: slot_id, image_id, row_index, slot_index, box, anchor_shape_id: Optional[str]  # line 68
class PerceptionResult: image_id, image_size, shapes, slots, zones, ocr_readings: Dict[str, OcrReading]  # line 108
class IdentificationResult: image_id, identifications  # identifications: List[Identification]
class RuleOutcome: rule_id, assessed=False, passed=None, score=1.0, penalty=0.0, detail=None, observations=[]  # line 206
class FixtureMembership: ON_FIXTURE, OFF_FIXTURE, UNCERTAIN  # line 35
class ShapeKind: PRICE_TAG = "price_tag" (line 18), FACT_TAG = "fact_tag" (line 21)
```

### Does NOT Exist
- ~~`Slot.facing_id`~~ — the slot→facing link is `ImageRegistration.assignments`.
- ~~`ctx.vision` use in comparison~~ — no provider call here.
- ~~`RuleObservation(kind="fact_tag_present")`~~ — not used, not added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_rule.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#evaluate_rules",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_unassessed",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_ref",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_dedupe_refs",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py#ImageRegistration"
  ]
}
```

---

## Implementation Notes

### Algorithm (spec §2, fixed)
Per binding, for each perception:
1. `registered` = shape ids in that image's registration whose facing is `binding.target_id`.
2. `facing_slots` = slots whose `slot_id` or `anchor_shape_id` is in `registered`.
3. `tags` = shapes of kind `FACT_TAG` or `PRICE_TAG` with `membership != OFF_FIXTURE`.
4. A tag is **anchored** if it is the `anchor_shape_id` of a facing slot, or
   `slot_above(tag, perception.slots)` is a facing slot.
5. For each anchored tag: `text = tag_text(tag, perception.ocr_readings, reads)` where `reads`
   maps `shape_id -> Identification` for that image.

Merge: facing registered nowhere → `_unassessed(binding, "facing not observed")`. Any anchored tag
(with a `tag_price(text)` amount when `params.get("price_required")`) → pass. Anchored tag(s) but
no legible price under `price_required` → fail, `detail="fact tag present, price not legible"`.
Registered but no anchored tag anywhere → fail, `detail="fact tag not observed"`.
Always `penalty=0.0`; `score` is 1.0 / 0.0.

### Key Constraints
- No I/O, no provider call, deterministic order (iterate perceptions in the given order).
- `slot_above` is called with ALL the image's slots, then its result is checked against the
  facing's slots — so a tag under a neighbour is never credited to this facing.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the contracts import with `ShapeKind, Slot`; import the tag helpers — *why*: the algorithm needs both.
2. Add `_rule_fact_tag` above `evaluate_rules` — *why*: one function per rule kind, as for the other four.
3. Add the dispatch branch — *why*: without it the kind falls into "unknown rule kind".
4. Write the tests.

### `comparison/rules.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c '^from parrot_pipelines.planogram.comparison.registration import ImageRegistration' comparison/rules.py)
# AFTER — insert below `from parrot_pipelines.planogram.comparison.registration import ImageRegistration` (verified: comparison/rules.py:13)
from parrot_pipelines.planogram.comparison.tags import slot_above, tag_price, tag_text
# and add `ShapeKind,` and `Slot,` to the `from parrot_pipelines.planogram.contracts import (...)` block (lines 14-25), keeping alphabetical order
```

### `comparison/rules.py` (MODIFY — evaluator)
```python
# occurrences: 1 (verified: grep -c '^def evaluate_rules(' comparison/rules.py)
# BEFORE — insert above `def evaluate_rules(` (verified: comparison/rules.py:459)
_TAG_KINDS = frozenset({ShapeKind.FACT_TAG, ShapeKind.PRICE_TAG})


def _rule_fact_tag(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
) -> RuleOutcome:
    """Tag presence (and a legible price when ``params["price_required"]``) for one facing, merged across images.

    Informative rule: ``penalty`` is always 0.0. A tag seen in any image counts as present.
    """
    price_required = bool(binding.params.get("price_required"))
    reads = {result.image_id: {item.shape_id: item for item in result.identifications} for result in identifications}
    by_image = {registration.image_id: registration for registration in registrations}
    seen = False
    tagged: List[ObservationRef] = []
    priced: List[ObservationRef] = []
    facing_refs: List[ObservationRef] = []
    for perception in perceptions:
        registration = by_image.get(perception.image_id)
        if registration is None:
            continue
        registered = {shape_id for shape_id, facing in registration.assignments.items() if facing == binding.target_id}
        if not registered:
            continue
        seen = True
        facing_slots = {
            slot.slot_id for slot in perception.slots if slot.slot_id in registered or slot.anchor_shape_id in registered
        }
        anchors = {slot.anchor_shape_id for slot in perception.slots if slot.slot_id in facing_slots}
        # FILL IN: facing_refs.extend(_ref(perception.image_id, shape_id, ObservationSource.CV) for registered ids)
        #          — bounded by "observations reference the facing's registered shapes on a fail" (spec §3 M3)
        for tag in perception.shapes:
            if tag.kind not in _TAG_KINDS or tag.membership == FixtureMembership.OFF_FIXTURE:
                continue
            above: Optional[Slot] = slot_above(tag, perception.slots)
            if tag.shape_id not in anchors and (above is None or above.slot_id not in facing_slots):
                continue
            # FILL IN: append _ref(...tag.source) to `tagged`; when tag_price(tag_text(tag, perception.ocr_readings,
            #          reads.get(perception.image_id, {}))) is not None also append to `priced`
            #          — bounded by spec §2 outcome table
    # FILL IN: build the outcome per the §2 table from (seen, tagged, priced, price_required);
    #          use _unassessed(binding, "facing not observed") when not seen; penalty=0.0 always;
    #          observations=_dedupe_refs(priced or tagged) on pass, _dedupe_refs(facing_refs) on fail
    raise NotImplementedError
```

### `comparison/rules.py` (MODIFY — dispatch)
```python
# occurrences: 1 (verified: grep -c '                outcome = _unassessed(binding, "unknown rule kind")' comparison/rules.py)
# BEFORE — insert above the `            else:` line that precedes `                outcome = _unassessed(binding, "unknown rule kind")` (verified: comparison/rules.py:484-485)
            elif binding.kind == "fact_tag_present":
                outcome = _rule_fact_tag(binding, perceptions, identifications, registrations)
```

### `tests/planogram_cycle/test_fact_tag_rule.py` (CREATE)
```python
"""FEAT-624 — fact_tag_present evaluation (spec §2 outcome table)."""

from __future__ import annotations

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.comparison.rules import _rule_fact_tag, evaluate_rules
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    IdentificationResult,
    OcrReading,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)


def _box(x1, y1, x2, y2):
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _perception(image_id="img0", tag_text=None, with_tag=True, membership=FixtureMembership.ON_FIXTURE):
    """Two slots side by side (s1 left, s2 right); optionally one tag under s1."""
    slots = [
        Slot(slot_id=f"{image_id}:s1", image_id=image_id, row_index=0, slot_index=1, box=_box(0, 100, 100, 300)),
        Slot(slot_id=f"{image_id}:s2", image_id=image_id, row_index=0, slot_index=2, box=_box(100, 100, 200, 300)),
    ]
    shapes = []
    readings = {}
    if with_tag:
        shapes.append(Shape(shape_id=f"{image_id}:t1", image_id=image_id, kind=ShapeKind.FACT_TAG,
                            box=_box(20, 290, 80, 320), membership=membership))
        if tag_text:
            readings[f"{image_id}:t1"] = OcrReading(text=tag_text)
    return PerceptionResult(image_id=image_id, image_size=(200, 400), shapes=shapes, slots=slots, ocr_readings=readings)


def _registration(image_id="img0", facing_slot="s1"):
    return ImageRegistration(image_id=image_id, assignments={f"{image_id}:{facing_slot}": "f1"})


def _binding(price_required=False):
    return RuleBinding(rule_id="fact_tag_present:f1", kind="fact_tag_present", target_id="f1",
                       params={"price_required": price_required}, mandatory=False)


def _ids(*image_ids):
    return [IdentificationResult(image_id=i, identifications=[]) for i in image_ids]


def test_fact_tag_present_passes_with_anchored_tag():
    outcome = _rule_fact_tag(_binding(), [_perception()], _ids("img0"), [_registration()])
    assert (outcome.assessed, outcome.passed, outcome.penalty) == (True, True, 0.0)


def test_fact_tag_present_fails_when_facing_seen_without_tag():
    outcome = _rule_fact_tag(_binding(), [_perception(with_tag=False)], _ids("img0"), [_registration()])
    assert (outcome.assessed, outcome.passed, outcome.detail, outcome.penalty) == (True, False, "fact tag not observed", 0.0)


def test_tag_under_neighbour_is_not_credited():
    outcome = _rule_fact_tag(_binding(), [_perception()], _ids("img0"), [_registration(facing_slot="s2")])
    assert outcome.passed is False


def test_fact_tag_unassessed_when_facing_not_registered():
    outcome = _rule_fact_tag(_binding(), [_perception()], _ids("img0"), [ImageRegistration(image_id="img0")])
    assert (outcome.assessed, outcome.passed, outcome.detail) == (False, None, "facing not observed")


def test_fact_tag_price_required_needs_legible_price():
    no_price = _rule_fact_tag(_binding(True), [_perception(tag_text="ES-60W")], _ids("img0"), [_registration()])
    assert (no_price.passed, no_price.detail) == (False, "fact tag present, price not legible")
    priced = _rule_fact_tag(_binding(True), [_perception(tag_text="$129.99")], _ids("img0"), [_registration()])
    assert priced.passed is True


def test_fact_tag_seen_in_any_image_passes():
    # FILL IN: img0 without tag + img1 with tag, both registering f1 -> passed True — bounded by spec §2 "any image"
    ...


def test_fact_tag_anchor_shape_counts():
    # FILL IN: InkWall-style — a slot whose anchor_shape_id is the tag's shape id and is registered to f1,
    #          tag placed where slot_above returns None -> passed True — bounded by spec §2 anchoring rule
    ...


def test_off_fixture_tag_is_ignored():
    outcome = _rule_fact_tag(_binding(), [_perception(membership=FixtureMembership.OFF_FIXTURE)], _ids("img0"),
                             [_registration()])
    assert outcome.passed is False


def test_evaluate_rules_dispatches_fact_tag():
    # FILL IN: ctx = CycleContext(definition=<load_slots_definition with one described facing "f1">,
    #          bindings=[_binding()]); call evaluate_rules([_perception()], _ids("img0"), [_registration()], ctx);
    #          assert outcome.passed is True and outcome.detail != "unknown rule kind" — bounded by AC "dispatch"
    ...
```

### FILL IN checklist
- [ ] `_rule_fact_tag` — `facing_refs`, tag refs, and the final outcome; bounded by spec §2 table.
- [ ] Remove the trailing `raise NotImplementedError` once the outcome is returned.
- [ ] The three stubbed tests (`CycleContext` is at contracts.py:351; `vision` stays None).

---

## Acceptance Criteria

- [ ] Every row of the spec §2 outcome table has a passing test (`assessed`, `passed`, `detail`).
- [ ] `penalty == 0.0` for every outcome of this kind.
- [ ] A tag under a neighbouring slot, or off-fixture, never passes the facing.
- [ ] `evaluate_rules` dispatches the kind; no provider call is made.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_rule.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py -q`

---

## Test Specification

See the CREATE block. One test per row of the spec §2 outcome table, plus neighbour, off-fixture,
anchor-shape and dispatch cases.

---

## Agent Instructions

1. Work in the feature worktree; run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. Confirm TASK-4003 and TASK-4004 are `done` in `sdd/tasks/index/planogram-fact-tag-rule.json`.
3. Verify the Codebase Contract; mark `in-progress`; implement; run the Validation Commands.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4005 planogram-fact-tag-rule verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
