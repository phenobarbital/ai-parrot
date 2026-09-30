# TASK-3863: Evidence-only rule evaluation and shared compare stage

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3861, TASK-3862, TASK-3855, TASK-3856
**Assigned-to**: unassigned

---

## Context

Spec §2 **Stage 3** ("Rule evaluation uses only observations; `compare()` must work with a vision
object that raises on every call"), §2 **Layout and configuration contract** (zone selectors:
ordinal/region, ambiguity stays unassessed), §3 **Module 4** skeletons `evaluate_rules` and
`compare_observations`, and §7 (zone-region target ids, TextMatcher semantics retained).

Today each migrated type owns its compare: `InkWall.compare` (`ink_wall.py:263-298`) and
`ProductOnShelves.compare` + `_evaluate_rules` (`product_on_shelves.py:623-863`). The POS rule
evaluation calls the LLM during compare (`_rule_illumination` → `_check_illumination`,
`product_on_shelves.py:698`) and matches zones by definition rank (`_observed_zones`,
`:566-581`) — which shifts every observed zone onto the first expected one in a partial view.

This task creates the shared, pure stage 3:
1. `comparison/rules.py` — `evaluate_rules`: bindings → `RuleOutcome` from collected evidence only
   (TASK-3859's `RuleObservation`s, OCR, identifications, registrations).
2. `stages/compare.py` — `compare_observations`: canonicalise identities (TASK-3861
   `resolve_identity`) → register → merge → evaluate rules → score → summarise → project.

Type tasks TASK-3864…TASK-3869 then make every type's `compare` hook a one-line call.

---

## Scope

- Create `evaluate_rules(perceptions, identifications, registrations, ctx) -> dict[str, RuleOutcome]`
  with one outcome per `ctx.bindings` entry, kinds `illumination`, `text_requirements`,
  `visual_features`, `zone_present`; unknown / ambiguous / conflicting evidence ⇒ `assessed=False`
  with a detail; each outcome carries its deciding `ObservationRef`s in `observations`.
- Create `match_zone(...)`: selector-driven (profile, kind, region, ordinal) matching of one
  definition zone to at most one observed zone per image; ambiguity is explicit.
- Copy the text normaliser and visual-feature matcher as pure module functions (same semantics
  as `ProductOnShelves._normalize_ocr_text` / `_calculate_visual_feature_match`).
- Create `compare_observations(perceptions, identifications, ctx, description) -> ComparisonResult`,
  synchronous, no I/O, deterministic.
- Write `test_shared_comparison.py` (spec §4 rows "comparison", "neutral rule evidence",
  "zone-only").

**NOT in scope**:
- Collecting evidence / any provider call — TASK-3859. Scoring/projection formulas — TASK-3862.
- `resolve_identity` itself — TASK-3861. Definition/binding validation — TASK-3860.
- Type hooks (`InkWall._price_notes`, POS fact-tag corroboration) — TASK-3864 / TASK-3865; they
  post-process the returned `ComparisonResult` if needed.
- Editing `stages/__init__.py` (TASK-3856) or any type module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | CREATE | pure rule evaluation, zone matching, text/visual helpers |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py` | CREATE | `compare_observations` shared stage |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py` | CREATE | deterministic compare + rule tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.compliance import TextMatcher                                  # parrot/models/compliance.py:72
from parrot.models.detections import PlanogramDescription, TextRequirement        # parrot/models/detections.py:364, :328
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, ZoneDefinition  # definition.py:88, :98, :79
from parrot_pipelines.planogram.comparison.registration import ImageRegistration, register_image  # registration.py:35, :172
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize   # scoring.py:147, :297, :399
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance  # projection.py:137, :53
from parrot_pipelines.planogram.contracts import (                                # contracts.py
    ComparisonResult, CycleContext, FixtureMembership, Identification, IdentificationResult,
    ObservationRef, ObservationSource, PerceptionResult, RuleOutcome, Shape, Slot,
)   # :295, :322, :35, :101, :137, :169, :26, :86, :180, :50, :67
```

### Existing Signatures to Use
```python
# parrot/models/compliance.py
class TextMatcher:                                                                # :72
    @classmethod
    def check_text_match(cls, required_text: str, visual_features: List[str], match_type: str = "contains",
                         case_sensitive: bool = False, confidence_threshold: float = 0.6, ...)   # :137-147
        # -> TextComplianceResult(required_text, found, matched_features, confidence, match_type)
# parrot/models/detections.py:328
class TextRequirement(BaseModel): required_text; match_type="contains"; case_sensitive=False;
                                  confidence_threshold=0.7; mandatory=True

# comparison/registration.py
class ImageRegistration(BaseModel): image_id; row_to_shelf: Dict[int, str]; assignments: Dict[str, str]
                                    (Identification.shape_id -> facing_id); ambiguous: bool   # :35-41
def register_image(image_id: str, slots: Sequence[Slot], identifications: Sequence[Identification],
                   definition: SlotsDefinition) -> ImageRegistration              # :172 (skips shelves without facings)
# comparison/scoring.py / projection.py — signatures unchanged by TASK-3862
def merge_positions(definition, registrations, identifications, policy) -> List[PositionResult]   # :147
def score_shelves(positions, definition, bindings, rule_outcomes, description, policy) -> List[ShelfScore]  # :297
def summarize(shelf_scores, positions, definition, weights) -> ComparisonResult   # :399
def project_compliance(shelf_scores, positions, definition, description) -> List[ComplianceResult]  # projection.py:53
def finalize_comparison(comparison, compliance_results) -> ComparisonResult       # projection.py:137

# Behaviour to MIRROR (copy semantics, do not import the type — spec §7 "shared stages must not import concrete types"):
# types/product_on_shelves.py:1675-1688 _normalize_ocr_text(s) -> str
# types/product_on_shelves.py:1690-1757 _calculate_visual_feature_match(expected, detected) -> float
#     (1.0 when expected empty; 0.0 when detected empty; keyword + semantic_mappings match)
# types/product_on_shelves.py:667-710 _rule_illumination params {"required": "on", "penalty": 0.5, "name"};
#     failure detail f"{name} — backlight {STATE} (required: {REQUIRED})"
# types/product_on_shelves.py:712-743 _rule_text: TextRequirement list in params["requirements"];
#     score = Σ confidence(found) / len(results); passed = no mandatory missing; detail "missing mandatory text: …"
# types/product_on_shelves.py:745-760 _rule_visual: params {"expected": [...], "threshold": 0.5}
# types/product_on_shelves.py:595-621 _target_texts: shelf target expands to its zones + facings; "ocr:<text>" + text features
# types/product_on_shelves.py:773-783 _canonical_identity: exact product id first (casefold)
# types/ink_wall.py:300-321 _registrable_slots: on-fixture anchors, untagged next row, rows with evidence only
# types/ink_wall.py:391-396 _canonicalise: product = resolved id (None when unresolved) + descriptors["candidates"]
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py
class RuleObservation(BaseModel): image_id; target_id; kind: Literal["illumination", "visual_features", "zone_present"];
                                  value: str | bool | list[str] | None; assessed: bool; source: ObservationSource; evidence
# IdentificationResult.rule_observations; RuleOutcome.observations: list[ObservationRef]; PerceptionResult.ocr_readings
# CycleContext.layout: Any (LayoutProfile)
# TASK-3855 — layout.py: ZoneSelector(zone_id, profile, kind, ordinal, region); LayoutProfile.zone_selectors,
#   .descriptor_fields, .required_descriptor_fields, .untagged_bottom_row
# TASK-3861 — comparison/identity.py
def resolve_identity(identification: Identification, definition: SlotsDefinition, *,
                     vocabulary: Sequence[str] = ("family", "colors", "pack", "xl"),
                     required_fields: Sequence[str] = ("family", "xl")) -> tuple[str | None, list[str]]
# TASK-3862 — scoring/projection accept EXPECTED_EMPTY / zone-only units; summarize reads RuleOutcome.observations
# TASK-3859 — zone-region observation target id convention: f"{image_id}:zone-region:{zone_id}" (spec §7)
# TASK-3856 — stages/ package exists
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.comparison.rules`~~ / ~~`stages.compare`~~ — this task creates them.
- ~~images in compare~~ — `compare_observations` receives no images and must never read `ctx.images` or call `ctx.vision`.
- ~~a definition-rank zone match~~ — do NOT port `_observed_zones`' rank matching; use selectors (spec §2).
- ~~`ZoneDefinition.kind` on observed shapes~~ — observed zones are `Shape(kind=ShapeKind.ZONE, profile=...)`; a selector's `kind` is compared to `shape.kind.value`, `profile` to `shape.profile`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#TextMatcher.check_text_match",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#TextRequirement",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py#register_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py#ImageRegistration",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#merge_positions",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#score_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#summarize",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#project_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#finalize_comparison",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#RuleBinding",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ZoneDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._calculate_visual_feature_match",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._normalize_ocr_text",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._registrable_slots"
  ]
}
```

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- Selector matches are recorded by TASK-3856 as `membership=ON_FIXTURE` plus a `membership_evidence` entry `"zone_selector:<zone_id>"`; import `SELECTOR_EVIDENCE_PREFIX` from `parrot_pipelines.planogram.stages.perceive` and parse that — do not invent a second convention.


### Pattern to Follow
- The compare pipeline order is InkWall's (`ink_wall.py:282-298`): canonicalise → register per image
  → `merge_positions` → rules → `score_shelves` → `summarize` → attach positions/shelves →
  `finalize_comparison(project_compliance(...))`.
- Rule semantics are ProductOnShelves' (`product_on_shelves.py:623-771`), but every input is an
  observation already collected; "unknown is not failure" (`_unassessed`, `:663-665`).

### Key Constraints
- **Pure** (AC8): `compare_observations` and `evaluate_rules` are plain `def`, perform no I/O, never
  touch `ctx.vision`, `ctx.executor`, `ctx.images`; the same inputs always give an equal result.
  They may append to `ctx.errors` (same as POS today).
- **Zone matching** (`match_zone`, spec §2): candidates = this image's `perception.zones` that are
  not `OFF_FIXTURE`, ordered by `(box.y1, box.x1)`.
  - With a selector for the zone id: filter by `profile` (when set), `kind` (vs `shape.kind.value`,
    when set) and `region` (candidate centre inside the region scaled by `perception.image_size`).
    If `ordinal` is set, apply it ONLY when the number of filtered candidates equals the number of
    selectors sharing the same `(profile, kind)`; otherwise the match is ambiguous. Without an
    ordinal: exactly one candidate ⇒ match; zero ⇒ not observed; several ⇒ ambiguous.
  - Without a selector: match only when the definition has exactly one zone AND the image has
    exactly one candidate; zero candidates ⇒ not observed; anything else ⇒ ambiguous.
  - Never materialise an expected zone from a selector alone.
- **zone_present**: per image, matched zone ⇒ present; else an assessed `RuleObservation` with
  `target_id == f"{image_id}:zone-region:{zone_id}"` gives present/absent; else unknown. Across
  images: present somewhere AND absent somewhere ⇒ unassessed `"conflict: …"`; present ⇒ pass
  (score 1.0); absent only ⇒ `passed=False, score=0.0, detail="zone region inspected: absent"`;
  nothing ⇒ unassessed `"zone visibility unknown"` (spec: a missing zone fails only with positive
  inspection evidence).
- **illumination**: assessed `illumination` observations on the matched zone ids; states across
  images `{on, off}` both present ⇒ unassessed conflict; single state = `params["required"]` ⇒ pass;
  otherwise fail with `penalty = float(params.get("penalty", 0.5))` and the POS detail text.
  Facing/shelf targets have no illumination evidence ⇒ unassessed.
- **text_requirements**: features = matched zones' `ocr_text` and `perception.ocr_readings[zone id].text`,
  the zone's own identification (`text`, `product`, `evidence`), and every registered facing view's
  identification text; shelf targets expand to their zones + facings (as `_target_texts`).
  `TextMatcher.check_text_match` per requirement, POS score/pass/detail formulas.
- **visual_features**: detected = matched zones' `visual_features` observation values + the same
  text features; score via the copied matcher; `passed = score >= params.get("threshold", 0.5)`.
- **Provenance**: every assessed outcome lists its deciding observations first as `ObservationRef`
  (`image_id`, `shape_id`=observed target id, `source`) — TASK-3862's evidence quality reads
  `observations[0].source`.
- **Canonicalisation** (`compare_observations`): skip when no product and no text; exact catalogue
  product id (casefold) first; else `resolve_identity(..., vocabulary=layout.descriptor_fields,
  required_fields=layout.required_descriptor_fields)` (defaults when `ctx.layout` is None);
  unresolved ⇒ `product=None` and `descriptors["candidates"]=candidates` (InkWall semantics — an
  unresolved read is not an identity; spec: "multiple candidates remain unresolved").
- **Registrable slots**: InkWall's rule, generalised — anchored slots whose anchor is an
  `ON_FIXTURE` shape (including accepted `IdentificationResult.added`), anchor-less slots in an
  on-fixture row or (when `layout.untagged_bottom_row`) the row right below the last one, then only
  rows holding at least one reliable read (`occupancy` occupied/empty, product or brand).
- `ctx.definition is None` ⇒ `ValueError("compare_observations requires a slots definition")`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:263-321` — compare order and slot filter
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:595-783` — rule semantics

---

## Implementation Blueprint

### Steps (in order)
1. Confirm dependencies: `grep -n "def resolve_identity" .../comparison/identity.py`, `grep -n "class RuleObservation\|observations" .../contracts.py`, `grep -n "class ZoneSelector" .../layout.py`, `ls .../stages/__init__.py` — *why*: imported below; STOP if missing.
2. Write `rules.py` (helpers, `match_zone`, `evaluate_rules`) — *why*: `stages/compare.py` imports it.
3. Write `stages/compare.py` — *why*: composition only.
4. Write `test_shared_comparison.py`; run the Validation Commands — *why*: AC8/AC9 determinism and purity.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` (CREATE) — helpers
```python
"""Evidence-only evaluation of bound non-product rules (FEAT-612, spec §2 Stage 3 / Module 4). Pure, no I/O."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from parrot.models.compliance import TextMatcher
from parrot.models.detections import TextRequirement
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, ZoneDefinition
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationRef,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    RuleOutcome,
    Shape,
)

logger = logging.getLogger(__name__)

ZONE_REGION_TARGET: str = "{image_id}:zone-region:{zone_id}"  # same convention as identification/evidence.py (spec §7)
DEFAULT_ILLUMINATION_PENALTY: float = 0.5  # POS default, product_on_shelves.py:675
DEFAULT_VISUAL_THRESHOLD: float = 0.5  # POS default, product_on_shelves.py:752


def normalize_text(text: str) -> str:
    """Pure copy of ProductOnShelves._normalize_ocr_text (product_on_shelves.py:1675-1688)."""
    # FILL IN: copy the body verbatim (NFKC, strip combining marks, punctuation -> space, lower) — bounded by §7 TextMatcher semantics
    raise NotImplementedError


def visual_feature_match(expected: Sequence[str], detected: Sequence[str]) -> float:
    """Pure copy of ProductOnShelves._calculate_visual_feature_match (product_on_shelves.py:1690-1757)."""
    # FILL IN: copy the body verbatim, including stop words and semantic_mappings — bounded by AC8 (same results)
    raise NotImplementedError


def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome:
    """Unknown is not failure."""
    return RuleOutcome(rule_id=binding.rule_id, assessed=False, passed=None, score=0.0, penalty=0.0, detail=detail)


def _ref(image_id: str, target_id: str, source: ObservationSource) -> ObservationRef:
    """Provenance of one deciding observation."""
    return ObservationRef(image_id=image_id, shape_id=target_id, source=source)
```

### `rules.py` (CREATE, continued) — zone matching
```python
def match_zone(
    zone: ZoneDefinition,
    perception: PerceptionResult,
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> Tuple[Optional[Shape], str]:
    """Match one definition zone to at most one observed zone of one image.

    Args:
        zone: The expected zone.
        perception: One image's stage-1 output.
        definition: The slots definition (zone count when no selector exists).
        selectors: ``LayoutProfile.zone_selectors`` (``ZoneSelector`` objects).

    Returns:
        ``(shape, "matched")``, ``(None, "not_observed")`` or ``(None, "ambiguous")``.
    """
    candidates = sorted(
        (z for z in perception.zones if z.membership != FixtureMembership.OFF_FIXTURE),
        key=lambda z: (z.box.y1, z.box.x1),
    )
    selector = next((s for s in selectors if s.zone_id == zone.zone_id), None)
    # FILL IN: implement the "Zone matching" rules of Key Constraints exactly (profile/kind/region filters,
    #   ordinal only when len(filtered) == number of selectors with the same (profile, kind), no-selector rule)
    #   — bounded by spec §2 "partial view must not shift every observed zone onto the first expected one"
    raise NotImplementedError
```
**Why**: the old rank matching (`product_on_shelves.py:566-581`) is exactly the partial-view bug
the spec forbids; returning an explicit reason lets rules distinguish "not observed" from
"ambiguous" (both unassessed, different details).

### `rules.py` (CREATE, continued) — `evaluate_rules`
```python
def evaluate_rules(
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
    ctx: CycleContext,
) -> Dict[str, RuleOutcome]:
    """Evaluate bound rules on collected observations; uncertainty/conflict is unassessed.

    Args:
        perceptions: Stage-1 outputs (observed zones, OCR readings).
        identifications: Stage-2 outputs (identifications + neutral rule observations).
        registrations: One registration per image (facing views).
        ctx: Per-run data (definition, bindings, layout.zone_selectors, errors). Never calls ctx.vision.

    Returns:
        ``rule_id -> RuleOutcome`` for every binding, in binding order.
    """
    definition: SlotsDefinition = ctx.definition
    selectors = list(ctx.layout.zone_selectors) if ctx.layout is not None else []
    observations: List[RuleObservation] = [o for r in identifications for o in r.rule_observations]
    idents: Dict[Tuple[str, str], Identification] = {
        (r.image_id, i.shape_id): i for r in identifications for i in r.identifications
    }
    outcomes: Dict[str, RuleOutcome] = {}
    for binding in ctx.bindings:
        try:
            # FILL IN: dispatch binding.kind to private _illumination/_text/_visual/_zone_present helpers that
            #   implement the Key Constraints bullets (match_zone per perception, zone-region observations,
            #   facing views via reg.assignments == facing_id, shelf target expansion, conflict -> unassessed,
            #   deciding ObservationRef first); unknown kind -> _unassessed(binding, "unknown rule kind")
            outcome = _unassessed(binding, "not evaluated")
        except Exception as exc:  # noqa: BLE001 - one malformed binding never fails the comparison
            logger.warning("Rule %s not assessed: %s", binding.rule_id, exc)
            ctx.errors.append(f"rule {binding.rule_id}: {exc}")
            outcome = _unassessed(binding, str(exc))
        outcomes[binding.rule_id] = outcome
    return outcomes
```
**Why this shape**: spec §3 fixes the signature. Keeping one private helper per kind (each ≤ ~40
lines) mirrors the POS split (`_rule_illumination`, `_rule_text`, `_rule_visual`,
`_rule_zone_present`) so reviewers can compare semantics line by line.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py` (CREATE)
```python
"""Shared stage 3: canonicalise, register, merge, evaluate, score and project — no I/O (FEAT-612, Module 4)."""

from __future__ import annotations

import logging
from typing import List, Sequence

from parrot.models.detections import PlanogramDescription
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition
from parrot_pipelines.planogram.comparison.identity import resolve_identity
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.registration import ImageRegistration, register_image
from parrot_pipelines.planogram.comparison.rules import evaluate_rules
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize
from parrot_pipelines.planogram.contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    PerceptionResult,
    Shape,
    Slot,
)

logger = logging.getLogger(__name__)


def canonicalise(identification: Identification, definition: SlotsDefinition, ctx: CycleContext) -> Identification:
    """Copy with ``product`` = catalogue id, or unresolved (None) with ``descriptors["candidates"]``."""
    # FILL IN: Key Constraints → Canonicalisation (exact id first, then resolve_identity with profile vocabulary)
    raise NotImplementedError


def registrable_slots(
    perception: PerceptionResult, added: Sequence[Shape], idents: Sequence[Identification], ctx: CycleContext
) -> List[Slot]:
    """On-fixture slots of rows holding reliable evidence (InkWall rule, generalised)."""
    # FILL IN: Key Constraints → Registrable slots (ink_wall.py:300-321 without its LLM fallback slots)
    raise NotImplementedError


def compare_observations(
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    ctx: CycleContext,
    description: PlanogramDescription,
) -> ComparisonResult:
    """Canonicalize, register, merge, evaluate, score and project with no I/O."""
    definition: SlotsDefinition = ctx.definition
    if definition is None:
        raise ValueError("compare_observations requires a slots definition")
    by_image = {r.image_id: r for r in identifications}
    canonical: List[Identification] = []
    registrations: List[ImageRegistration] = []
    for perception in perceptions:
        result = by_image.get(perception.image_id)
        raw = [i for i in (result.identifications if result else []) if i.image_id in (None, perception.image_id)]
        idents = [canonicalise(i, definition, ctx).model_copy(update={"image_id": perception.image_id}) for i in raw]
        slots = registrable_slots(perception, result.added if result else [], idents, ctx)
        registrations.append(register_image(perception.image_id, slots, idents, definition))
        canonical.extend(idents)
    positions = merge_positions(definition, registrations, canonical, ctx.credit_policy)
    outcomes = evaluate_rules(perceptions, identifications, registrations, ctx)
    shelves = score_shelves(positions, definition, ctx.bindings, outcomes, description, ctx.credit_policy)
    comparison = summarize(shelves, positions, definition, ctx.evidence_weights)
    comparison = comparison.model_copy(update={"position_results": positions, "shelf_scores": shelves})
    return finalize_comparison(comparison, project_compliance(shelves, positions, definition, description))
```
**Why**: spec §3 fixes the signature (`description` is supplied by the type, which owns
`get_planogram_description` fallbacks such as `ink_wall.py:409-421`). `FixtureMembership` is used
by `registrable_slots`.

### FILL IN checklist
- [ ] `rules.py::normalize_text` / `visual_feature_match` — verbatim semantics; bounded by AC8
- [ ] `rules.py::match_zone` — selector rules; bounded by spec §2 selector paragraph
- [ ] `rules.py::evaluate_rules` + four kind helpers; bounded by AC7, AC8, AC9
- [ ] `stages/compare.py::canonicalise` — bounded by spec §2 identity paragraph
- [ ] `stages/compare.py::registrable_slots` — bounded by ink_wall.py:300-321

---

## Acceptance Criteria

- [ ] AC8: `compare_observations` succeeds with a `ctx.vision` whose every attribute access/call raises; two runs on the same input give equal `model_dump()`.
- [ ] AC8: partial and multiple-photo registration work; every expected facing stays in `position_results`; inferred/variant credits preserved.
- [ ] AC7/AC9: conflicting reliable observations across photos ⇒ unassessed with `"conflict"` detail; ambiguous zone matches ⇒ unassessed; a missing zone fails only with an assessed zone-region observation.
- [ ] AC9: zone-only definition (no physical shelves) evaluates through bindings; zero observations ⇒ `INCONCLUSIVE`, `overall_compliant` False.
- [ ] TextMatcher semantics retained: optional vs mandatory text; illumination ON / OFF / unknown; repeated same-kind zones resolved only by selectors (spec §7 regression list).
- [ ] Assessed outcomes carry deciding `ObservationRef`s in `observations`.
- [ ] `ruff check` / `black --check --line-length 120` pass on the three files.

---
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py`

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings
from parrot_pipelines.planogram.comparison.rules import evaluate_rules, match_zone, visual_feature_match
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, CycleContext, FixtureMembership, Identification, IdentificationResult,
    ObservationSource, PerceptionResult, RuleObservation, Shape, ShapeKind, Slot,
)
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.stages.compare import compare_observations


class ExplodingVision:
    """Any use fails the test: compare must never call the vision adapter."""
    def __getattr__(self, name):
        raise AssertionError(f"compare touched vision.{name}")

# fixtures: two-shelf definition with described facings; perception with slots anchored on ON_FIXTURE shapes;
# identifications reading the expected products; a minimal PlanogramDescription (see test_scoring_projection._description)


def test_compare_never_calls_vision_and_is_deterministic(): ...
    # ctx.vision=ExplodingVision(); r1 = compare_observations(...); r2 = compare_observations(...); r1.model_dump() == r2.model_dump()


def test_every_expected_facing_in_denominator_with_partial_photo(): ...
    # photo shows one of two rows -> len(position_results) == all facings; unseen ones NOT_VISIBLE


def test_unresolved_candidates_stay_unresolved(): ...
    # read matching two catalogue products -> product None, descriptors["candidates"] has both


def test_zone_matched_by_selector_region_and_ordinal(): ...
    # two same-kind observed zones + selectors with ordinals 0/1 -> each rule reads its own zone


def test_partial_view_ordinal_is_ambiguous(): ...
    # 2 selectors share (profile, kind) but only 1 observed candidate -> zone_present unassessed "ambiguous"


def test_zone_present_needs_positive_inspection_to_fail(): ...
    # no observed zone, no region observation -> unassessed; assessed zone-region value False -> passed False


def test_conflicting_photos_are_unassessed(): ...
    # illumination "on" in img0 and "off" in img1 for the matched zone -> assessed False, "conflict" in detail


def test_illumination_on_off_unknown(): ...
    # required "on": observed on -> pass; off -> fail with penalty 0.5 and POS detail; unknown -> unassessed


def test_text_requirements_optional_vs_mandatory(): ...
    # zone OCR "SUMMER SALE": mandatory "SALE" found -> pass; missing optional -> still pass, lower score


def test_visual_feature_match_semantics_copied(): ...
    # visual_feature_match([], ["x"]) == 1.0; (["logo"], []) == 0.0; (["illuminated logo"], ["backlit branding"]) == 1.0


def test_zone_only_zero_observations_inconclusive(): ...
    # zone-only definition + mandatory zone_present binding, no zones observed -> INCONCLUSIVE, overall_compliant False


def test_outcome_carries_deciding_observation(): ...
    # assessed zone_present outcome.observations[0].shape_id == observed zone id, source CV
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3863 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean (residual style debt left to /sdd-done).

