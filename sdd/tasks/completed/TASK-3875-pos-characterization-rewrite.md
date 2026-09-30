# TASK-3875: Re-pin ProductOnShelves characterization tests on the new cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3865, TASK-3871
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12** ("Rewrite characterization tests to pin retained business behavior on the new cycle,
rather than deleting coverage"), §4 ("do not preserve legacy score formulas merely to keep characterization
tests green"), §7 Known Risks ("Large cleanup hides behavior regressions") and AC8/AC9/AC16.

The two FEAT-574 characterization files pin `ProductOnShelves.check_planogram_compliance`,
`_check_illumination`, `_ocr_fact_tags`, `_corroborate_products_with_fact_tags` and
`_assign_products_to_shelves` — the legacy half that TASK-3865 deletes and the base helpers TASK-3870 deletes.
After those tasks both files fail at collection or at attribute lookup. This task rewrites them so that
the **business rules that survive** are pinned through the new cycle: `ProductOnShelves.compare()` on
hand-built stage-1/stage-2 outputs (deterministic, vision that raises on every call) plus one
`PlanogramCompliance.run()` round trip with the stage-1/2 hooks stubbed.

---

## Scope

- Replace the whole content of `test_pos_compliance_characterization.py` with cycle-level regression tests
  (one ComplianceResult per definition shelf in definition order; matched shelf COMPLIANT; EMPTY facing listed
  as missing and kept in the denominator; MISPLACED receives lenient 0.5; wrong product is MISMATCH; threshold
  decides status; zone-only header with unassessed mandatory rule is inconclusive and not compliant; mandatory
  text requirement miss fails; illumination penalty applied once; compare never calls vision).
- Replace the whole content of `test_pos_fact_tags_illumination_characterization.py` with evidence-based
  tests (illumination ON/OFF/unknown/conflicting observations; fact-tag text corroborates an observed facing
  but never makes an unseen product present; fact tag naming another shelf's or an unknown product has no
  effect; observed rows register to definition shelves in order; off-fixture shapes never register;
  one `run()` round trip returns the eight legacy keys with measured, non-legacy status).
- Keep both file names (other tooling references them) and use only synthetic, generic product labels.

**NOT in scope**:
- Any source change. If a retained behaviour cannot be observed through public hooks, record it in the
  Completion Note — do not add hooks here (TASK-3865 owns `product_on_shelves.py`).
- Shared comparison unit tests (`test_shared_comparison.py`, TASK-3863), identity resolution
  (`test_comparison_identity.py`, TASK-3861), rule evidence collection (`test_rule_evidence.py`, TASK-3859),
  migrated POS hook tests (`test_pos_migrated_*.py`, TASK-3865), neutral/type suites (TASK-3876).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py` | MODIFY | Full rewrite: shelf/facing/rule business rules via `compare()` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py` | MODIFY | Full rewrite: illumination evidence, fact-tag corroboration, row registration, `run()` round trip |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.compliance import ComplianceResult, ComplianceStatus        # parrot/models/compliance.py:51
from parrot.models.detections import DetectionBox                              # parrot/models/detections.py:37
from parrot_pipelines.models import PlanogramConfig                            # models.py:32
from parrot_pipelines.planogram import plan as plan_module                     # used at test_run_template.py:15
from parrot_pipelines.planogram.plan import PlanogramCompliance                # plan.py:48
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves  # product_on_shelves.py:64
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition  # definition.py:88,218
from parrot_pipelines.planogram.contracts import (                             # contracts.py
    AssessmentStatus,      # :161
    CreditPolicy,          # :221 (CreditPolicy.default())
    CycleContext,          # :322
    EvidenceWeights,       # :282
    FacingStatus,          # :146
    FixtureMembership,     # :35
    Identification,        # :101
    IdentificationResult,  # :137
    ObservationSource,     # :26
    PerceptionResult,      # :86
    Shape,                 # :50
    ShapeKind,             # :15
    Slot,                  # :67
)
```

### Existing Signatures to Use
```python
# contracts.py
class Shape(BaseModel): shape_id, image_id, kind: ShapeKind, box: DetectionBox, row_index, slot_index,
                        ocr_text, ocr_confidence, source, membership: FixtureMembership        # :50-64
class Slot(BaseModel): slot_id ("<image_id>:r<row>:s<slot>"), image_id, row_index, slot_index, box,
                       anchor_shape_id, inferred                                                # :67-76
class Identification(BaseModel): shape_id, image_id, product, brand, text, descriptors,
                                  occupancy ("occupied"|"empty"|"unknown"), raw_confidence, evidence, source, uncertain  # :101-114
class PositionResult(BaseModel): facing_id, shelf_id, status, strict_credit, lenient_credit, identity  # :191
class ComparisonResult(BaseModel): compliance_results, position_results, shelf_scores, overall_compliance_score,
    strict_compliance_score, overall_compliant, coverage, detected_products, evidence_quality, assessment_status  # :295
CreditPolicy.default(): MATCH 1/1; INFERRED_PRESENT & VARIANT_UNRESOLVED 0/1; MISPLACED 0/0.5; others 0/0  # :250-270

# comparison/projection.py:53 project_compliance — one ComplianceResult per definition shelf, definition order;
#   COMPLIANT iff complete & facing_lenient >= threshold & no failed mandatory rule; MISSING iff complete & all EMPTY;
#   MISPLACED iff complete & every violation MISPLACED; missing_products lists only EMPTY facings (+ illumination detail);
#   result.assessment.assessment_status ∈ {"complete","inconclusive"}                                   # :53-136

# comparison/registration.py:172 register_image — rows (sorted row_index) map to definition shelves WITH facings in a
#   strictly increasing assignment; more rows than shelves or ambiguity ⇒ no assignment (facings not_visible)

# packages/ai-parrot-pipelines/tests/conftest.py
class FakeVisionClient: client_name = "fake"; queue(method, *responses); calls_to(method) -> list[dict]   # :46-156
@pytest.fixture fake_vision_client / synthetic_shelf_image (800x1000 RGB)                                  # :158-165
# test_run_template.py:126-142 — _InlineExecutor + `monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)`
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 (contracts.py) — spec §3 M1 skeleton
FacingStatus.EXPECTED_EMPTY / FacingStatus.UNEXPECTED_OCCUPIED
class RuleObservation(BaseModel):
    image_id: str; target_id: str
    kind: Literal["illumination", "visual_features", "zone_present"]
    value: str | bool | list[str] | None = None; assessed: bool = False
    source: ObservationSource; evidence: list[str] = Field(default_factory=list)
IdentificationResult.rule_observations: list[RuleObservation] = default_factory(list)
PerceptionResult.ocr_readings: dict[str, OcrReading] = default_factory(dict)   # OcrReading(text, confidence)
CycleContext.layout: Any = None; CycleContext.images: dict[str, Any] = default_factory(dict)
# TASK-3865 (product_on_shelves.py)
@classmethod
def default_layout_profile(cls) -> LayoutProfile: ...          # four CV profiles, shape-is-slot, full image, threshold 3
async def compare(self, perceptions, identifications, ctx) -> ComparisonResult: ...  # composes stages/compare.py; pure
# TASK-3871 (plan.py / contracts.py): PerceptionResult.legacy and LegacyPayload are removed; run() keeps its
#   public signature; result carries the eight legacy keys + measured additive keys.
```
Before writing tests, read the Completion Notes of TASK-3865, TASK-3863 and TASK-3871 for: the observation
`target_id` a POS illumination binding matches (zone shape id vs `<image_id>:zone-region:<zone_id>`), how
fact-tag text is consumed (shape `ocr_text` vs `PerceptionResult.ocr_readings`) and the corroborated status.

### Does NOT Exist (after the dependencies)
- ~~`ProductOnShelves.check_planogram_compliance`, `_ocr_fact_tags`, `_corroborate_products_with_fact_tags`,
  `_assign_products_to_shelves`, `_generate_virtual_shelves`~~ — deleted by TASK-3865 (were :1024, :1857, :2022, :2131, :1770).
- ~~`AbstractPlanogramType._check_illumination` / `_vision_kwargs`~~ — deleted by TASK-3870 (were abstract.py:167, :573).
- ~~`roi_detection_prompt` / `object_identification_prompt` being required~~ — accepted and ignored (spec §2).
- ~~A fact-tag "injected" synthetic product~~ — spec M6: fact tags corroborate, never prove an unseen product.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CreditPolicy.default",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentificationResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#project_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py#register_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run"
  ]
}
```

---

## Implementation Notes

### Legacy-only vs retained — `test_pos_compliance_characterization.py` (380 lines today)
| Current test (line) | Verdict | New pin |
|---|---|---|
| `test_one_result_per_shelf_in_config_order` (:102) | RETAIN | one result per **definition** shelf, definition order |
| `test_pos_basic_score_and_status_characterization` (:116) | REWRITE | full match ⇒ COMPLIANT; EMPTY facing ⇒ listed in `missing_products`, lenient < 1 (drop the `0.3` legacy formula) |
| `test_pos_weights_sum_quirk_characterization` (:129) | DELETE | legacy 0.8/0.1/0.2 clamp quirk — spec §4 forbids pinning it |
| `test_pos_threshold_uses_basic_score_only_characterization` (:139) | REWRITE | status decided by facing_lenient vs shelf threshold (same data, two thresholds) |
| `test_pos_explicit_shelf_weights_characterization` (:153) | DELETE | legacy combined-score weights; FEAT-574 weights are covered by `test_scoring_projection.py` |
| `test_pos_zone_only_shelf_characterization` (:170) | REWRITE | zone-only shelf with unassessed mandatory `zone_present` ⇒ inconclusive, never COMPLIANT (AC9) |
| `test_pos_never_emits_misplaced_characterization` (:192) | REWRITE (inverse) | product at another shelf's slot ⇒ `MISPLACED`, lenient 0.5 (spec §2 credits) |
| `test_pos_illumination_penalty_characterization` (:205) | REWRITE | OFF observation vs required ON ⇒ penalty applied once, shelf not COMPLIANT |
| `test_pos_header_text_requirements_characterization` (:251) | REWRITE | mandatory text miss ⇒ rule failed; optional miss does not fail |
| `test_pos_header_no_promos_keeps_text_score_characterization` (:281) | DELETE | legacy quirk (score stays 1.0) |
| `test_pos_header_brand_gate_characterization` (:292) | DELETE | legacy brand gate, no cycle equivalent |
| `test_pos_matching_rules_characterization` (:334) | DELETE | replaced by identity resolution (TASK-3861 tests) |
| `test_pos_unexpected_products_characterization` (:363) | REWRITE | a different product at an expected slot ⇒ `MISMATCH`, 0/0 credit |

### Legacy-only vs retained — `test_pos_fact_tags_illumination_characterization.py` (256 lines today)
| Current test (line) | Verdict | New pin |
|---|---|---|
| `test_check_illumination_answer_parsing` (:116), `_failure_returns_none` (:126), `_crop_precedence` (:132) | REWRITE | illumination from `RuleObservation`: ON passes, OFF fails with penalty, none ⇒ unassessed, conflicting photos ⇒ unassessed |
| `test_ocr_fact_tags_strip_per_foreground_shelf` (:148), `_detected_tags_refine_rows` (:163), `_isolates_shelf_failure` (:174) | DELETE | legacy LLM strip OCR; own-target OCR is pinned by `test_target_ocr.py` (TASK-3857) |
| `test_corroborate_injects_missing_expected_model` (:186) | REWRITE (inverse) | fact tag naming an expected but unobserved product ⇒ facing stays not present |
| `test_corroborate_skip_rules` (:206) | REWRITE | tag text of another shelf's / unknown product changes nothing |
| `test_assign_products_default_max_overlap` (:215), `_promotional_and_missing_box` (:224), `_y1_mode_uses_centre_bottom_up` (:237), `_no_shelves_is_noop` (:252) | REWRITE | observed rows register to shelves in order; off-fixture never registers; more rows than shelves ⇒ no assignment |
| (new) | ADD | `run()` round trip: eight keys, both compliance keys equal, `assessment_status` never `legacy_unmeasured` |

### Key Constraints
- Build the handler like `test_pos_migrated_compare.py:57-69` (MagicMock pipeline, config with `slots_definition`);
  build `ctx` with `CreditPolicy.default()`, `EvidenceWeights()`, `ctx.layout = ProductOnShelves.default_layout_profile()`
  and `ctx.vision = _RaisingVision()` — compare must never call it (AC8).
- Synthetic ids/labels only (`P-100`, `P-200`, "Acme"); never retailer SKUs.
- Assert statuses/credits/membership, not legacy numeric formulas (spec §4). Where exact numbers are asserted, derive
  them from `CreditPolicy.default()` values quoted above.
- The `run()` test stubs `ProductOnShelves.perceive`/`identify` with `monkeypatch.setattr` on the class and uses the
  `_InlineExecutor` pattern (`test_run_template.py:126-142`); the fake client is `FakeVisionClient` with no queued answers.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read TASK-3863/3865/3871 Completion Notes for the observation-target and fact-tag conventions — *why*: tests must use the implemented binding, not a guessed one.
2. Replace `test_pos_compliance_characterization.py` (blocks 1-2) — *why*: its legacy methods no longer exist.
3. Replace `test_pos_fact_tags_illumination_characterization.py` (block 3) — *why*: same, and fact tags become corroboration only.
4. Run the Validation Commands — *why*: AC16 requires retained behaviour coverage after rewrites.

### `test_pos_compliance_characterization.py` (MODIFY) — block 1: header and builders
```python
# occurrences: 1 (verified: grep -Fxc '"""Characterization tests: ProductOnShelves.check_planogram_compliance as it behaves TODAY (FEAT-574).' → line 1)
# REPLACE lines 1-380 (whole file). Block 1 = top of the new file.
"""Regression tests: ProductOnShelves business rules on the perceive → identify → compare cycle (FEAT-612).

Replaces the FEAT-574 legacy characterization. Pins retained behaviour — shelf order, facing statuses and
credits, thresholds, zone and text rules, illumination — never legacy score formulas (spec §4).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from parrot.models.compliance import ComplianceStatus
from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, CreditPolicy, CycleContext, EvidenceWeights, FacingStatus, FixtureMembership,
    Identification, IdentificationResult, PerceptionResult, Shape, ShapeKind, Slot,
)
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


class _RaisingVision:
    """Any attribute access or call proves compare() tried to use the vision adapter (AC8)."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"compare() must not touch vision ({name})")


def definition(shelves: Dict[str, List[str]], zones: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Raw definition: ``{"top": ["P-100", "P-200"], ...}`` in top→bottom order; generic labels only."""
    # FILL IN: build {"shelves": [...], "zones": list(zones)} with shelf_id=level, shelf_number=index,
    #   facing_id=f"{level}:{slot}", descriptors={"display_name": p, "identifiers": [p]} — bounded by
    #   load_slots_definition validation (definition.py:218)
    raise NotImplementedError


def handler(raw_definition: Dict[str, Any], **planogram_config: Any) -> ProductOnShelves:
    """ProductOnShelves over a MagicMock pipeline (pattern: test_pos_migrated_compare.py:57-69)."""
    # FILL IN: PlanogramConfig(config_name="pos-regression", planogram_type="product_on_shelves",
    #   planogram_config={"brand": "Acme", **planogram_config}, slots_definition=raw_definition)
    raise NotImplementedError


def ctx(raw_definition: Dict[str, Any], bindings: Sequence[Dict[str, Any]] = ()) -> CycleContext:
    """Deterministic context: default credits/weights, POS default layout, vision that raises."""
    # FILL IN: defn = load_slots_definition(raw_definition); CycleContext(definition=defn,
    #   bindings=[RuleBinding(**b) for b in bindings], credit_policy=CreditPolicy.default(),
    #   evidence_weights=EvidenceWeights(), layout=ProductOnShelves.default_layout_profile(), vision=_RaisingVision())
    raise NotImplementedError


def observe(rows: List[List[Optional[str]]], image_id: str = "img0") -> tuple[PerceptionResult, IdentificationResult]:
    """One on-fixture product shape + slot per cell; ``None`` = observed empty; row 0 is the top row."""
    # FILL IN: Shape(kind=PRODUCT, membership=ON_FIXTURE, row_index=r, slot_index=s) with a DetectionBox per cell,
    #   Slot(slot_id=f"{image_id}:r{r}:s{s}", anchor_shape_id=shape_id), Identification(shape_id=shape_id,
    #   product=label, occupancy="occupied"|"empty", raw_confidence=0.9) — bounded by register_image (registration.py:172)
    raise NotImplementedError
```
**Why**: these helpers are the whole fixture surface; `_RaisingVision` turns any hidden provider call during
compare into a test failure (AC8) and `observe` only produces what a camera could have seen.

### `test_pos_compliance_characterization.py` (MODIFY) — block 2: tests (append after block 1)
```python
async def _compare(h: ProductOnShelves, c: CycleContext, *images) -> "ComparisonResult":  # noqa: F821
    return await h.compare([p for p, _ in images], [i for _, i in images], c)


async def test_one_result_per_definition_shelf_in_definition_order() -> None:
    raw = definition({"top": ["P-100"], "middle": ["P-200"], "bottom": ["P-300"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-100"], ["P-200"], ["P-300"]]))
    assert [r.shelf_level for r in result.compliance_results] == ["top", "middle", "bottom"]


async def test_fully_matched_shelf_is_compliant_and_complete() -> None:
    # FILL IN: every facing observed with its product ⇒ COMPLIANT, assessment "complete", positions all MATCH (1/1)
    ...


async def test_empty_facing_is_missing_and_stays_in_denominator() -> None:
    # FILL IN: one observed empty slot ⇒ its label in missing_products; PositionResult EMPTY 0/0;
    #   ShelfScore.expected_facings counts it; overall not compliant
    ...


async def test_threshold_decides_status_on_the_same_evidence() -> None:
    # FILL IN: 3 of 4 matched + 1 EMPTY; planogram_config shelves threshold 0.8 ⇒ NON_COMPLIANT, 0.7 ⇒ COMPLIANT
    #   (lenient 0.75); _threshold() (projection.py:45) reads ShelfConfig.compliance_threshold of the legacy description shelf with the same level, default 0.8 — verify TASK-3865 still passes a description
    ...


async def test_product_seen_at_another_shelf_slot_is_misplaced_half_credit() -> None:
    # FILL IN: status MISPLACED, strict 0.0, lenient 0.5 (CreditPolicy.default) — inverse of the legacy "never MISPLACED" quirk
    ...


async def test_different_product_at_expected_slot_is_mismatch() -> None:
    # FILL IN: observed "P-999" where "P-100" expected ⇒ MISMATCH, strict 0, lenient 0
    ...


async def test_zone_only_header_with_unassessed_mandatory_rule_is_inconclusive() -> None:
    # FILL IN: header zone (required) + mandatory zone_present binding, no zone observed ⇒ header result
    #   assessment "inconclusive", status != COMPLIANT, overall_compliant False (AC9)
    ...


async def test_mandatory_text_requirement_miss_fails_optional_does_not() -> None:
    # FILL IN: text_requirements binding on the header zone with one mandatory + one optional requirement;
    #   zone observed with OCR text containing only the optional text ⇒ rule failed; swap ⇒ rule passed
    ...


async def test_illumination_mismatch_penalty_applied_once() -> None:
    # FILL IN: illumination binding {"required": "on", "penalty": 0.5}; RuleObservation(kind="illumination", value="off")
    #   ⇒ shelf not COMPLIANT and lenient_score == facing score * (1 - 0.5) exactly once (read score_shelves)
    ...
```
**Why**: each test maps one row of the Implementation Notes table to spec §2 Stage 3 rules; none asserts a legacy formula.

### `test_pos_fact_tags_illumination_characterization.py` (MODIFY) — block 3: whole new file
```python
# occurrences: 1 (verified: grep -Fxc '"""Characterization tests: fact-tag OCR, corroboration, shelf assignment, illumination — as they behave TODAY (FEAT-574)."""' → line 1)
# REPLACE lines 1-256 (whole file).
"""Regression tests: illumination evidence, fact-tag corroboration and row registration on the cycle (FEAT-612)."""

from __future__ import annotations
# FILL IN: imports — same set as block 1 plus `from parrot_pipelines.planogram import plan as plan_module`,
#   `from parrot_pipelines.planogram.plan import PlanogramCompliance`, ObservationSource and (TASK-3854) RuleObservation;
#   copy the builder helpers from block 1 (definition/handler/ctx/observe/_RaisingVision) — test files do not import each other

LEGACY_KEYS = (
    "step3_compliance_results", "compliance_results", "overall_compliance_score", "overall_compliant",
    "identified_products", "shelf_regions", "rendered_image", "overlay_path",
)


@pytest.mark.parametrize("value,passed", [("on", True), ("off", False)])
async def test_illumination_rule_follows_observation(value: str, passed: bool) -> None:
    # FILL IN: required "on"; one assessed observation ⇒ RuleOutcome.assessed True, passed == passed
    ...


async def test_illumination_without_observation_is_unassessed() -> None:
    # FILL IN: no RuleObservation ⇒ outcome assessed False, shelf inconclusive, never COMPLIANT
    ...


async def test_conflicting_illumination_across_photos_is_unassessed() -> None:
    # FILL IN: img0 "on", img1 "off" (both assessed) ⇒ assessed False with a conflict detail — no first-photo-wins
    ...


async def test_fact_tag_never_makes_an_unseen_product_present() -> None:
    # FILL IN: FACT_TAG shape with text "P-200" on the top row, no product shape for P-200's slot ⇒
    #   P-200 facing status not in {MATCH, INFERRED_PRESENT, VARIANT_UNRESOLVED}; lenient credit 0
    ...


async def test_fact_tag_corroborates_an_observed_facing() -> None:
    # FILL IN: occupied slot with unreadable product + tag "P-200" under it ⇒ status per TASK-3865 Completion Note;
    #   bounded by: lenient credit > 0 and strict credit <= lenient
    ...


@pytest.mark.parametrize("tag_text", ["P-300", "UNKNOWN-LABEL"])
async def test_fact_tag_for_other_shelf_or_unknown_product_changes_nothing(tag_text: str) -> None:
    # FILL IN: compare with and without the tag ⇒ identical position_results
    ...


async def test_observed_rows_register_to_definition_shelves_in_order() -> None:
    # FILL IN: two observed rows ⇒ row 0 facings land on "top", row 1 on "bottom" (PositionResult.shelf_id)
    ...


async def test_off_fixture_shapes_never_register() -> None:
    # FILL IN: same observation but membership OFF_FIXTURE ⇒ facings not MATCH, detected_products == 0
    ...


async def test_run_round_trip_returns_legacy_keys_measured(monkeypatch, fake_vision_client, synthetic_shelf_image) -> None:
    # FILL IN: stub ProductOnShelves.perceive/identify with monkeypatch (return observe(...) parts), inline executor;
    #   result = await PlanogramCompliance(planogram_config=..., llm=fake_vision_client).run(synthetic_shelf_image)
    #   assert set(LEGACY_KEYS) <= result.keys(); result["compliance_results"] == result["step3_compliance_results"];
    #   no "legacy_unmeasured"/"legacy_llm" anywhere in result assessment/source fields (AC11)
    ...
```
**Why**: illumination and fact tags are exactly the behaviours spec M6/§2 re-define (evidence, corroboration only);
the round trip proves the rewritten POS path is reachable through the public `run()` (AC2/AC11).

### FILL IN checklist
- [ ] Builders `definition`/`handler`/`ctx`/`observe` — generic labels; bounded by definition validation
- [ ] Nine compliance tests — statuses/credits from `CreditPolicy.default()`; bounded by AC8/AC9
- [ ] Illumination tests — observation target per TASK-3863 note; bounded by AC7 (no invented evidence)
- [ ] Fact-tag tests — corroboration only; bounded by spec M6
- [ ] Round-trip test — eight keys, measured status; bounded by AC2/AC11

---

## Acceptance Criteria

- [ ] Neither file references a removed legacy method (`grep -nE 'check_planogram_compliance|_check_illumination|_ocr_fact_tags|_corroborate_products|_assign_products_to_shelves' <both files>` → nothing).
- [ ] Every "RETAIN/REWRITE" row above has a named test; every "DELETE" row is gone — AC16.
- [ ] `compare()` is exercised with a vision object that raises on use — AC8.
- [ ] Expected-product lists never feed an observation; fact tags never make an unseen facing present — AC7.
- [ ] Only synthetic labels; no retailer names or photos.
- [ ] Validation Commands pass; `ruff check` and `black --check` clean — AC16.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_fact_tags_illumination_characterization.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q`

---

## Test Specification

```python
# test_pos_compliance_characterization.py
async def test_one_result_per_definition_shelf_in_definition_order(): ...   # levels == ["top","middle","bottom"]
async def test_fully_matched_shelf_is_compliant_and_complete(): ...         # COMPLIANT, "complete", all MATCH 1/1
async def test_empty_facing_is_missing_and_stays_in_denominator(): ...      # label in missing_products, EMPTY 0/0, expected_facings unchanged
async def test_threshold_decides_status_on_the_same_evidence(): ...         # 0.8 ⇒ NON_COMPLIANT, 0.7 ⇒ COMPLIANT
async def test_product_seen_at_another_shelf_slot_is_misplaced_half_credit(): ...  # MISPLACED, strict 0, lenient 0.5
async def test_different_product_at_expected_slot_is_mismatch(): ...        # MISMATCH 0/0
async def test_zone_only_header_with_unassessed_mandatory_rule_is_inconclusive(): ...  # inconclusive, not compliant
async def test_mandatory_text_requirement_miss_fails_optional_does_not(): ...  # failed vs passed rule
async def test_illumination_mismatch_penalty_applied_once(): ...           # single penalty, not COMPLIANT
# test_pos_fact_tags_illumination_characterization.py
async def test_illumination_rule_follows_observation(value, passed): ...   # on ⇒ pass, off ⇒ fail
async def test_illumination_without_observation_is_unassessed(): ...       # assessed False
async def test_conflicting_illumination_across_photos_is_unassessed(): ... # assessed False + conflict detail
async def test_fact_tag_never_makes_an_unseen_product_present(): ...       # lenient 0
async def test_fact_tag_corroborates_an_observed_facing(): ...             # lenient > 0
async def test_fact_tag_for_other_shelf_or_unknown_product_changes_nothing(tag_text): ...  # identical positions
async def test_observed_rows_register_to_definition_shelves_in_order(): ...  # shelf_id per row
async def test_off_fixture_shapes_never_register(): ...                     # detected_products == 0
async def test_run_round_trip_returns_legacy_keys_measured(...): ...        # 8 keys, equal lists, no legacy status
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3875 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean. Deviations confirmed against source: MISPLACED decided within one shelf; MISMATCH needs differing brand; fact tag naming another shelf's product resolves the unreadable slot to that product.

