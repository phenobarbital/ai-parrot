# TASK-3446: ProductOnShelves compare hook and rule evaluation through bindings

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3441, TASK-3445
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 17** (second half) and §2 **Scoring contract for migrated
types**. After TASK-3445 `ProductOnShelves` perceives and identifies through
the new cycle; this task adds stage 3: the `compare` hook and
`_evaluate_rules`, which turns every validated `RuleBinding` into a
`RuleOutcome` using the **existing, characterized** logic of this file
(illumination check, `TextMatcher` text requirements, visual-feature match,
zone presence). Expected products come only from `slots_definition`;
non-product rules come only through bindings (spec G9).

---

## Scope

- Add `async def _evaluate_rules(self, bindings, images, identifications, ctx) -> Dict[str, RuleOutcome]`
  — one outcome per `RuleBinding`, by `kind`:
  - `illumination` → `self._check_illumination(...)` on the image of the bound
    zone/facing, compared with `params["required"]`; mismatch ⇒
    `passed=False`, `penalty=float(params.get("penalty", 0.5))` (0.5 is this
    type's legacy default, `product_on_shelves.py:436`).
  - `text_requirements` → `TextMatcher.check_text_match` per requirement over
    the OCR / identification text of the bound zone; `score = Σ confidence(found) / len(requirements)`;
    `passed=False` when a mandatory requirement is not found.
  - `visual_features` → `self._calculate_visual_feature_match(expected, detected)`.
  - `zone_present` → `score=1.0 / passed=True` when the bound zone was observed
    `on_fixture` in any image.
  - a rule that could not be evaluated ⇒ `assessed=False` (never `passed=False`).
- Override `compare(perceptions, identifications, ctx) -> ComparisonResult`:
  register each image, merge positions, evaluate rules, score shelves,
  summarize, project to `List[ComplianceResult]`.
- Offline tests, including both perception modes end to end through the hooks.

**NOT in scope**: changing the scoring formula (fixed in the scoring task);
editing `check_planogram_compliance` or any other legacy method; handler or
`run()` changes; promotional aliasing beyond reusing the `_PROMO_TYPES` alias
set as a module-level constant for zone-kind matching.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | `compare`, `_evaluate_rules`, per-kind rule helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py` | CREATE | offline tests for rule outcomes and the compare hook |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already imported at the top of product_on_shelves.py (verified :26-32)
from parrot.models.compliance import (ComplianceResult, BrandComplianceResult,
    TextComplianceResult, ComplianceStatus, TextMatcher)

# to ADD — created by dependency tasks
from typing import Sequence
from parrot_pipelines.planogram.contracts import ComparisonResult, RuleOutcome          # TASK-3421
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition   # TASK-3435
from parrot_pipelines.planogram.comparison.registration import register_image           # TASK-3440
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize   # TASK-3441
from parrot_pipelines.planogram.comparison.projection import project_compliance          # TASK-3441
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
def _normalize_ocr_text(self, s: str) -> str                                             # :1037-1050
def _calculate_visual_feature_match(self, expected_features: List[str],
                                    detected_features: List[str]) -> float              # :1052-1119
    # 1.0 when expected is empty (:1056-1057); 0.0 when detected is empty (:1058-1059)
# legacy text-requirement evaluation to MIRROR (do not call, do not edit): :666-715
#   TextMatcher.check_text_match(required_text=, visual_features=, match_type=, case_sensitive=,
#                                confidence_threshold=)                                  # :700-706
#   text_score = sum(r.confidence for r in text_results if r.found) / len(text_results)  # :711
# legacy illumination lookup to MIRROR: closures :420-436 (default penalty 0.5 :436)
# _PROMO_TYPES alias set (local variable inside check_planogram_compliance): :391-404

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
@staticmethod
def _extract_illumination_state(features: List[str]) -> Optional[str]                    # :132-149 → "on" | "off" | None
async def _check_illumination(self, img: Image.Image, zone_bbox: Optional[Any] = None,
    roi: Optional[Any] = None, planogram_description: Optional[Any] = None) -> Optional[str]   # :151-249
    # returns "illumination_status: ON" / "illumination_status: OFF", or None on failure

# packages/ai-parrot/src/parrot/models/compliance.py
class TextMatcher:                                                                       # :55-208
    @staticmethod-style: check_text_match(required_text, visual_features, match_type="contains",
        case_sensitive=False, confidence_threshold=0.6, ngram_range=(1,3), min_token_len=2)   # :118-208
        -> TextComplianceResult(required_text, found, matched_features, confidence, match_type)   # :17-23
# packages/ai-parrot/src/parrot/models/detections.py
class TextRequirement(BaseModel)   # :328-334  required_text, match_type, case_sensitive, confidence_threshold=0.7, mandatory
```

```python
# Created by TASK-3421 (dependency) — planogram/contracts.py
class RuleOutcome(BaseModel):      rule_id, assessed: bool, passed: Optional[bool], score: float, penalty: float, detail
class ComparisonResult(BaseModel): compliance_results, position_results, shelf_scores, overall_compliance_score,
                                   strict_compliance_score, overall_compliant, coverage, definition_coverage,
                                   evidence_quality, assessment_status, errors
# Created by TASK-3435 (dependency) — comparison/definition.py
class RuleBinding(BaseModel):      rule_id, kind (illumination|text_requirements|visual_features|zone_present),
                                   target_id (facing_id|zone_id|shelf_id), params, mandatory
# Created by TASK-3440 / TASK-3441 (dependencies)
def register_image(image_id: str, slots: Sequence[Slot], identifications: Sequence[Identification],
                   definition: SlotsDefinition) -> ImageRegistration
def merge_positions(definition, registrations, identifications, policy: CreditPolicy) -> List[PositionResult]
def score_shelves(positions, definition, bindings, rule_outcomes: Dict[str, RuleOutcome],
                  description: PlanogramDescription, policy: CreditPolicy) -> List[ShelfScore]
def summarize(shelf_scores, positions, definition, weights: EvidenceWeights) -> ComparisonResult
def project_compliance(shelf_scores, positions, definition, description) -> List[ComplianceResult]
# Created by TASK-3445 (dependency) — this file
async def perceive(...) -> PerceptionResult ;  async def identify(...) -> IdentificationResult
```

### Does NOT Exist
- ~~`ProductOnShelves.compare` / `._evaluate_rules`~~ — this task adds them.
- ~~`ShelfConfig.illumination_required` / `illumination_penalty`~~ — never Pydantic fields; for migrated configs they arrive as `RuleBinding.params`.
- ~~`PlanogramDescription.visual_features_weight`, `AdvertisementEndcap.brand_weight`~~ — do not exist (legacy reads them via `getattr` defaults).
- ~~a module-level `_PROMO_TYPES`~~ — today it is a local variable (:391-404); leave that one alone and define a separate module constant if you need the alias set.
- ~~images inside `PerceptionResult`~~ — `compare` does not receive images; see the blueprint for how `_evaluate_rules` gets them.
- ~~`TextMatcher` "exact" branch~~ — `match_type="exact"` falls through to the n-gram path (`compliance.py:155-198`); do not special-case it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._calculate_visual_feature_match",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._normalize_ocr_text",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._check_illumination",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType._extract_illumination_state",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#TextMatcher",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#TextComplianceResult",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#TextRequirement"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- **Images for rules**: the `compare` hook signature carries no images. `perceive`
  (TASK-3445) runs first for every image — cache each image there in
  `self._cycle_images: Dict[str, Image.Image]` (add that one line to `perceive`
  and initialise the dict in `__init__`), and clear it at the end of `compare`.
  Because both hooks are in this file, this stays a private detail of the type.
- "Apply once": this method produces outcomes only. Weight combination and the
  illumination multiplier are applied by `score_shelves` — never multiply a
  score here.
- Unknown is not failure: no image for the target, LLM error, or zone not
  observed ⇒ `RuleOutcome(assessed=False, passed=None, score=0.0, penalty=0.0)`.
  A mandatory unassessed rule makes the assessment `inconclusive` downstream.

### Key Constraints
- `_check_illumination` is async and LLM-backed — await it; call it at most once
  per (image, zone) pair.
- Legacy methods stay byte-identical; ProductOnShelves characterization tests stay green.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:666-715` — text-requirement semantics to mirror
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:420-436` — illumination defaults
- spec §2 "Scoring contract for migrated types" — what `score_shelves` does with the outcomes

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the imports and `self._cycle_images` (init in `__init__`, fill in `perceive`) — *why*: rule evaluation needs the source images and the hook signature does not carry them.
2. Add the four per-kind helpers — *why*: each mirrors one characterized legacy rule and is unit-testable alone.
3. Add `_evaluate_rules` dispatching on `binding.kind` — *why*: one outcome per binding, keyed by `rule_id`, is the contract `score_shelves` consumes.
4. Add `compare` — *why*: wires registration → merge → rules → scoring → summarize → projection in the order fixed by spec Module 13.
5. Write tests; run the Validation Command and the ProductOnShelves characterization tests.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` (MODIFY) — block 1: rule evaluation
```python
# occurrences: 1 (verified: grep -c '    async def _detect_with_grid(' product_on_shelves.py)
# BEFORE — insert above `    async def _detect_with_grid(` (verified: product_on_shelves.py:224 before TASK-3445; re-locate by text)
    async def _evaluate_rules(self, bindings: Sequence[RuleBinding], images: Dict[str, Image.Image],
                              identifications: Sequence[IdentificationResult], ctx: CycleContext
                              ) -> Dict[str, RuleOutcome]:
        """Evaluate every bound non-product rule once.

        Returns:
            rule_id → RuleOutcome. Rules that cannot be evaluated are returned with assessed=False.
        """
        outcomes: Dict[str, RuleOutcome] = {}
        for binding in bindings:
            try:
                if binding.kind == "illumination":
                    outcome = await self._rule_illumination(binding, images, ctx)
                elif binding.kind == "text_requirements":
                    outcome = self._rule_text(binding, identifications)
                elif binding.kind == "visual_features":
                    outcome = self._rule_visual(binding, identifications)
                elif binding.kind == "zone_present":
                    outcome = self._rule_zone_present(binding, identifications)
                else:
                    raise ValueError(f"Unknown rule kind '{binding.kind}'")
            except Exception as exc:  # isolate one rule; never fail the run
                self.logger.warning("Rule %s not assessed: %s", binding.rule_id, exc)
                ctx.errors.append(f"rule {binding.rule_id}: {exc}")
                outcome = RuleOutcome(rule_id=binding.rule_id, assessed=False, passed=None,
                                      score=0.0, penalty=0.0, detail=str(exc))
            outcomes[binding.rule_id] = outcome
        return outcomes

    async def _rule_illumination(self, binding: RuleBinding, images: Dict[str, Image.Image],
                                 ctx: CycleContext) -> RuleOutcome:
        """params: {"required": "on"|"off", "penalty": float=0.5}."""
        # FILL IN: locate the target zone/facing box + its image_id; call
        #   await self._check_illumination(img, zone_bbox=box); state = self._extract_illumination_state([result])
        #   — bounded by: result None ⇒ assessed=False; mismatch ⇒ passed=False,
        #   penalty=float(params.get("penalty", 0.5)); match ⇒ passed=True, penalty=0.0.
        raise NotImplementedError

    def _rule_text(self, binding: RuleBinding, identifications: Sequence[IdentificationResult]) -> RuleOutcome:
        """params: {"requirements": [TextRequirement dicts]}."""
        # FILL IN: features = identification text + f"ocr:{...}" of the target zone, normalised
        #   with self._normalize_ocr_text; per requirement call TextMatcher.check_text_match —
        #   bounded by legacy semantics :700-711: score = Σ confidence(found)/len(all);
        #   passed False iff a mandatory requirement is not found; no zone observed ⇒ assessed=False.
        raise NotImplementedError

    def _rule_visual(self, binding: RuleBinding, identifications: Sequence[IdentificationResult]) -> RuleOutcome:
        """params: {"expected": [str]} → self._calculate_visual_feature_match(expected, detected)."""
        raise NotImplementedError  # FILL IN — bounded by: target not identified ⇒ assessed=False

    def _rule_zone_present(self, binding: RuleBinding,
                           identifications: Sequence[IdentificationResult]) -> RuleOutcome:
        """score 1.0 when the bound zone was observed on_fixture in any image, else 0.0 (assessed=True)."""
        raise NotImplementedError  # FILL IN — bounded by: uncertain membership ⇒ assessed=False
```
**Why this shape**: one helper per `RuleBinding.kind` (the four kinds fixed in
spec §2 Data Models). The `try/except` isolates a rule failure into `errors`
+ `assessed=False`, which is how spec G14 keeps "unknown" separate from "failed".

### same file — block 2: compare hook
```python
# AFTER — insert directly below block 1
    async def compare(self, perceptions: Sequence[PerceptionResult],
                      identifications: Sequence[IdentificationResult], ctx: CycleContext) -> ComparisonResult:
        """Stage 3: registration → merge → rules → shelf scores → summary → ComplianceResult projection."""
        definition: SlotsDefinition = ctx.definition
        description = self.config.get_planogram_description()
        by_image = {i.image_id: i for i in identifications}
        registrations = []
        for perception in perceptions:
            ident = by_image.get(perception.image_id)
            # FILL IN: only on_fixture observations enter registration — bounded by spec G13;
            #   pass ident.identifications (+ accepted additions) of THIS image only.
            registrations.append(register_image(perception.image_id, perception.slots, [], definition))
        all_identifications = [x for i in identifications for x in i.identifications]
        positions = merge_positions(definition, registrations, all_identifications, ctx.credit_policy)
        outcomes = await self._evaluate_rules(ctx.bindings, self._cycle_images, identifications, ctx)
        shelf_scores = score_shelves(positions, definition, ctx.bindings, outcomes, description, ctx.credit_policy)
        result = summarize(shelf_scores, positions, definition, ctx.evidence_weights)
        result.compliance_results = project_compliance(shelf_scores, positions, definition, description)
        # FILL IN: overall_compliant = assessment complete AND every shelf COMPLIANT — bounded by
        #   spec §2 (inconclusive ⇒ False; empty result list is never a pass); append ctx.errors.
        self._cycle_images.clear()
        return result
```
**Why**: the call order and every callee signature are fixed by spec Module 13;
this hook adds nothing but the ProductOnShelves rule outcomes.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py` (CREATE)
See **Test Specification**.

### FILL IN checklist
- [ ] `_rule_illumination` — target lookup, single LLM call per (image, zone), penalty default 0.5
- [ ] `_rule_text` — legacy score formula, mandatory flag, unassessed when zone unseen
- [ ] `_rule_visual`, `_rule_zone_present`
- [ ] `compare` — on-fixture filter per image; `overall_compliant`; errors
- [ ] `self._cycle_images` init in `__init__` and fill in `perceive`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Every `RuleBinding` yields exactly one `RuleOutcome` keyed by `rule_id`.
- [ ] Illumination mismatch ⇒ `passed=False`, `penalty=params.penalty` (default 0.5); `_check_illumination` returning `None` ⇒ `assessed=False`.
- [ ] Text rule score equals `Σ confidence(found) / len(requirements)`; a missing mandatory requirement ⇒ `passed=False`.
- [ ] A rule raising an exception is isolated: outcome `assessed=False`, message appended to `ctx.errors`, other rules evaluated.
- [ ] `compare` never reads `planogram_config["shelves"][*]["products"]` for expected products.
- [ ] A zone-only header shelf with an illumination mismatch scores without division by zero and the penalty is applied exactly once (end-to-end through `compare`).
- [ ] `overall_compliant` is `False` whenever `assessment_status != "complete"`.
- [ ] Legacy methods unchanged; `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q` passes offline.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py
"""Offline tests for ProductOnShelves.compare and rule evaluation."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


@pytest.fixture
def handler() -> ProductOnShelves:
    """ProductOnShelves with MagicMock pipeline/config (see TASK-3445's test helper)."""
    ...


@pytest.mark.asyncio
async def test_illumination_mismatch_sets_penalty(handler):
    handler._check_illumination = AsyncMock(return_value="illumination_status: OFF")
    # binding params {"required": "on"} → passed False, penalty 0.5


@pytest.mark.asyncio
async def test_illumination_unknown_is_unassessed(handler):
    handler._check_illumination = AsyncMock(return_value=None)


def test_text_rule_score_and_mandatory(handler):
    """2 requirements, 1 found with confidence 1.0 → score 0.5; mandatory missing → passed False."""


def test_visual_rule_uses_calculate_visual_feature_match(handler): ...


def test_zone_present_uncertain_membership_is_unassessed(handler): ...


@pytest.mark.asyncio
async def test_rule_exception_is_isolated(handler): ...


@pytest.mark.asyncio
async def test_compare_zone_only_header_shelf_penalty_once(handler): ...


@pytest.mark.asyncio
async def test_compare_inconclusive_is_not_compliant(handler): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3446-pos-migration-compare-rules.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
product_on_shelves.py (insertions only; legacy methods and __init__ byte-identical): _evaluate_rules (one RuleOutcome per binding, per-rule exception isolation -> assessed=False + ctx.errors), _rule_illumination (one _check_illumination per (image, box), cached; None -> unassessed; mismatch -> passed False, penalty params.penalty default 0.5, detail '<name> — backlight <DET> (required: <EXP>)' which projection turns into the illumination pseudo-entry), _rule_text (TextMatcher.check_text_match over normalised zone OCR / registered identification text; score = sum conf(found)/len(all); mandatory miss -> passed False; target unseen -> unassessed), _rule_visual (_calculate_visual_feature_match, passed at params.threshold default 0.5), _rule_zone_present (on_fixture -> 1.0, uncertain -> unassessed, absent -> 0.0), compare (canonical identity: exact product id then ink_wall.resolve_identity, unresolved reads kept; only on-fixture slots registered; merge -> rules -> score_shelves -> summarize -> project -> finalize_comparison; image cache cleared).
Design decisions: definition zones are matched to observed zone shapes by order (definition order <-> top-to-bottom) since observed zones carry no sub-kind; the image cache (_cycle_images) is created lazily by perceive instead of in __init__ (keeps the legacy __init__ byte-identical); compare stashes perceptions/registrations in a private _rule_context for the fixed _evaluate_rules signature; ctx.errors are not copied into ComparisonResult.errors because run() already merges both (would duplicate).
ProductOnShelves is now a full cycle type (prompts no longer required, slots_definition required).
Tests: test_pos_migrated_compare.py 11 passed (incl. zone-only header shelf with the penalty applied once, inconclusive never compliant, off-fixture ignored); full packages/ai-parrot-pipelines/tests 336 passed (+1 pre-existing), tests/pipelines 138, handler suite unchanged (2 pre-existing). No new ruff findings.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
