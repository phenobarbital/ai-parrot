# TASK-3441: Per-facing decision, multi-photo merge, scoring and projection to ComplianceResult

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3440
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 13** (second half) and spec §2 **"Scoring contract for migrated
types"**. After registration (TASK-3440) each expected facing gets **one status**
decided from every photo's observations, credits are summed per shelf with **all
expected facings in the denominator**, non-product rules are combined with the
shelf-local weights **once**, and the result is projected onto the existing
public vocabulary: one `ComplianceResult` per definition shelf, in definition
order, with the additive `ShelfAssessment`. Compliance, coverage and evidence
quality are **three separate measures**.

This task pins the brainstorm's open "scoring examples" item: the seven fixtures
below must pass with the exact values given.

Algorithmic reference (read, never import): `examples/planogram/plancheck/scoring.py`
— `_decide` :106 (10-step decision list), `_credits` :210, `merge_positions` :251,
`shelf_scores` :356, `summarize` :473. **Deviation from the reference**: there is no
`verified_by_expectation` match — an expected SKU offered in a verification prompt
is never evidence by itself (spec §2).

---

## Scope

- Implement `merge_positions`, `score_shelves`, `summarize` (scoring module) and
  `project_compliance` (projection module) with the exact spec signatures, plus
  one helper `finalize_comparison` in the projection module (see *Why*).
- Implement the scoring contract **verbatim**:

**Per-facing credits** (`CreditPolicy`; read credits from the policy, never hard-code):

| Facing status | Strict | Lenient | Assessment treatment |
|---|---|---|---|
| `match` (admissible exact identity evidence) | 1.0 | 1.0 | Resolved |
| `misplaced` (supported identity, wrong facing) | 0.0 | 0.5 | Resolved, placement violation |
| `variant_unresolved`, `inferred_present` | 0.0 | 0.5 | Partially supported; **unresolved** for coverage |
| `mismatch`, visibly `empty` | 0.0 | 0.0 | Resolved violation |
| `occupied_unassigned`, `conflict`, `not_assessed`, `not_visible` | 0.0 | 0.0 | Unresolved; never assert missing from absence of evidence |

**Formula** — for shelf *s* with expected facings *F_s* and bound rules *R_s*:

```
facing_strict(s)  = Σ strict_credit(f)  / |F_s|          for f in F_s      (|F_s| > 0)
facing_lenient(s) = Σ lenient_credit(f) / |F_s|
        # every expected facing stays in the denominator — a partial view
        # can never reach 100% by excluding unseen positions

text_score(s)     = Σ confidence(r) for found r / |text requirements|      (1.0 when none apply)
visual_score(s)   = mean(visual-feature match of matched facings/zones that
                         declare visual_features)                          (1.0 when none apply)
zone_score(s)     = fraction of required zones on s that were observed     (only for shelves with zones)

# weights — same resolution as today (product_on_shelves.py:745-764) …
header/endcap shelf : Wp = endcap.product_weight·(1-0.2)   Wt = endcap.text_weight   Wv = endcap.product_weight·0.2
other shelves       : Wv = shelf.visual_weight  or 0.2
                      Wt = shelf.text_weight    or 0.1
                      Wp = shelf.product_weight or (1 - Wv)
# … but NORMALISED for migrated types (today's non-header defaults sum to 1.1
# and are silently clamped, product_on_shelves.py:777):
W' = W / (Wp + Wt + Wv)  over the terms that APPLY to the shelf

product_term(s, mode) = facing_{mode}(s)            if |F_s| > 0
                      = zone_score(s)               if |F_s| == 0 and s has required zones
combined(s, mode)     = product_term·Wp' + text_score·Wt' + visual_score·Wv'

# illumination — existing penalty semantics, applied ONCE to the combined score
penalty(s)            = Σ illumination_penalty(mismatching bound rule) / max(1, |F_s|)
shelf_compliance(s, mode) = clamp01( combined(s, mode) · max(0, 1 - penalty(s)) )
```

- `ComplianceResult.compliance_score = shelf_compliance(s, lenient)`; the strict
  value is reported in the additive `ShelfAssessment`.
- `overall_compliance_score = mean_s shelf_compliance(s, lenient)` — unweighted
  shelf mean, **not** facing-weighted. `strict_compliance_score` is the same mean
  over `shelf_compliance(s, strict)`.
- `coverage` = resolved facings / expected facings, **globally over facings**,
  resolved = `match | misplaced | mismatch | empty`. Visible and occupied
  fractions are reported separately per shelf.
- `definition_coverage` comes from `definition_coverage(definition)` (TASK-3435).
- `evidence_quality` = mean of `EvidenceWeights[source]` over the **deciding
  observation** of each resolved facing; `None` when nothing is resolved. Weights
  never touch credits and never decide a conflict.
- `assessment_status = COMPLETE` only when every expected facing is resolved
  **and** every mandatory bound rule was assessed (`RuleOutcome.assessed`);
  otherwise `INCONCLUSIVE`.
- **Shelf status projection** (existing `ComplianceStatus`, unchanged):
  `COMPLIANT` iff the shelf is completely assessed, `facing_lenient(s) ≥
  shelf.compliance_threshold` (default 0.8), no mandatory rule failed, no
  illumination mismatch and no major unexpected product; `MISSING` iff completely
  assessed and every facing is visibly `empty`; `MISPLACED` iff completely
  assessed and every violation on the shelf is `misplaced`; otherwise
  `NON_COMPLIANT` — including every shelf with unresolved facings.
  `missing_products` lists **only facings proven `empty`** (plus illumination
  pseudo-entries `"<name> — backlight <DET> (required: <EXP>)"`); unseen products
  are never labelled missing.
- `overall_compliant = assessment_status == COMPLETE and all shelves COMPLIANT`;
  an **empty result list is never a pass**; zero usable evidence ⇒ score `0.0`.
- **Multi-photo merge**: observations are keyed by `image_id`; merge per
  `facing_id` **after** registration. Concordant observations keep all provenance;
  incompatible admissible identities ⇒ `conflict` regardless of source;
  uncertain/unreadable evidence never overrides a supported identification and
  never creates a conflict; CV localisation alone never wins an identity
  disagreement.

**Decision list per facing** (adapted from the reference `_decide`):
1. no registered observation in any image ⇒ `not_visible`
2. observations exist but none is reliable (all `uncertain`) ⇒ `not_assessed`
3. reliable observations disagree (occupied vs empty, or ≥ 2 distinct admissible product ids) ⇒ `conflict`
4. all reliable observations say empty ⇒ `empty`
5. admissible identity equals the facing's product ⇒ `match`
6. expected product admissibly identified at **another** facing of the same shelf ⇒ `misplaced`
7. brand (and descriptor family) agree but the exact product is not established ⇒ `variant_unresolved`
8. admissible identity of a different product, or a different brand ⇒ `mismatch`
9. occupied, registered, facing undescribed in the definition ⇒ `occupied_unassigned`
10. otherwise occupied with no identity evidence ⇒ `inferred_present`

**Conventions fixed here** (callers comply):
- `Identification.product` is the **canonical product id** as written in
  `FacingDefinition.product` (types canonicalise before calling); comparison is
  casefold/strip.
- *Admissible* = `not uncertain` **and** non-empty `evidence` **and** `product` set.
- *Empty* is signalled by the dedicated contract field `Identification.occupancy == "empty"`
  (TASK-3421; values `"occupied" | "empty" | "unknown"`). `"unknown"` is never treated as empty.
- Join rule (from TASK-3440): `ImageRegistration.assignments` maps
  `Identification.shape_id → facing_id`.

**NOT in scope**: evaluating rules (text / illumination / visual / zone) — callers
pass ready `RuleOutcome`s keyed by `rule_id`; identity resolution from
descriptors; registration itself; rendering; any type hook.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | CREATE | `merge_positions`, `score_shelves`, `summarize` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` | CREATE | `project_compliance`, `finalize_comparison` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py` | CREATE | Seven pinned fixtures + projection status tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.detections import PlanogramDescription, ShelfConfig, AdvertisementEndcap  # verified: detections.py:364, :302, :337
from parrot.models.compliance import ComplianceResult, ComplianceStatus                      # verified: compliance.py:32, :9
# Created by dependencies (re-verify once merged):
from parrot.models.compliance import ShelfAssessment                                         # TASK-3421 (additive)
from parrot_pipelines.planogram.contracts import (                                           # TASK-3421
    AssessmentStatus, ComparisonResult, CreditPolicy, EvidenceWeights, FacingStatus,
    Identification, ObservationSource, PositionResult, RuleOutcome, ShelfScore,
)
from parrot_pipelines.planogram.comparison.definition import (                               # TASK-3435
    FacingDefinition, RuleBinding, ShelfDefinition, SlotsDefinition, definition_coverage,
)
from parrot_pipelines.planogram.comparison.registration import ImageRegistration             # TASK-3440
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/compliance.py
class ComplianceStatus(str, Enum):   # :9-14   COMPLIANT | NON_COMPLIANT | MISSING | MISPLACED
class ComplianceResult(BaseModel):   # :32-52
    shelf_level: str; expected_products: List[str]; found_products: List[str]
    missing_products: List[str]; unexpected_products: List[str]
    compliance_status: ComplianceStatus
    compliance_score: float          # ge=0.0, le=1.0  -> clamp is MANDATORY
    text_compliance_results: List[TextComplianceResult] = []
    brand_compliance_result: Optional[BrandComplianceResult] = None
    text_compliance_score: float = 1.0
    overall_text_compliant: bool = True
    # assessment: Optional[ShelfAssessment] = None      <- added by TASK-3421

# packages/ai-parrot/src/parrot/models/detections.py
class ShelfConfig(BaseModel):        # :302-326  level :305, compliance_threshold: float = 0.8 :307,
                                     #           product_weight / text_weight / visual_weight: Optional[float] = None :313-315
class AdvertisementEndcap(BaseModel):# :337-354  enabled :339, position = "header" :343, product_weight = 0.8 :345, text_weight = 0.2 :346
class PlanogramDescription(BaseModel): # :364-407  shelves: List[ShelfConfig] :380, advertisement_endcap: Optional[AdvertisementEndcap] :384

# Today's weight resolution that the formula mirrors (READ ONLY — do not import):
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:745-764, clamp :777

# ---- Created by TASK-3421 (dependency) — copied from spec §2 Data Models / Module 2 skeleton ----
class FacingStatus(str, Enum):      # MATCH, MISPLACED, VARIANT_UNRESOLVED, MISMATCH, EMPTY, INFERRED_PRESENT,
                                    # OCCUPIED_UNASSIGNED, CONFLICT, NOT_ASSESSED, NOT_VISIBLE
class AssessmentStatus(str, Enum):  # COMPLETE, INCONCLUSIVE, LEGACY_UNMEASURED
class ObservationSource(str, Enum): # CV="cv", LLM_ADDED="llm_added", LLM="llm", LEGACY_LLM="legacy_llm"
class Identification(BaseModel):    # shape_id, image_id, product, brand, text, descriptors, raw_confidence, evidence, source, uncertain
class PositionResult(BaseModel):    # facing_id, shelf_id, status, strict_credit, lenient_credit, identity,
                                    # observations (provenance, per image_id), notes
class ShelfScore(BaseModel):        # shelf_id, shelf_level, expected_facings, facing_strict, facing_lenient,
                                    # strict_score, lenient_score, coverage, visible_fraction, occupied_fraction, rule_results
class RuleOutcome(BaseModel):       # rule_id, assessed: bool, passed: Optional[bool], score: float, penalty: float, detail
class CreditPolicy(BaseModel):      # strict / lenient: Dict[FacingStatus, float]; default(); is_resolved(status) -> bool
class EvidenceWeights(BaseModel):   # weight per ObservationSource (cv=1.0, llm_added=0.5, llm=0.5, legacy_llm=0.5)
class ComparisonResult(BaseModel):  # compliance_results, position_results, shelf_scores, overall_compliance_score,
                                    # strict_compliance_score, overall_compliant, coverage, definition_coverage,
                                    # evidence_quality, assessment_status, errors
class ShelfAssessment(BaseModel):   # assessment_status, coverage, strict_score, lenient_score, expected_facings,
                                    # resolved_facings, unresolved_facing_ids, rule_results   (core compliance.py)

# ---- Created by TASK-3435 (dependency) ----
class RuleBinding(BaseModel):       # rule_id, kind (illumination|text_requirements|visual_features|zone_present),
                                    # target_id (facing_id|zone_id|shelf_id), params, mandatory
class ZoneDefinition(BaseModel):    # zone_id, kind, shelf_id, required
def definition_coverage(definition: SlotsDefinition) -> Tuple[float, List[str]]

# ---- Created by TASK-3440 (dependency) ----
class ImageRegistration(BaseModel): # image_id, row_to_shelf: Dict[int, str], assignments: Dict[str, str] (shape_id -> facing_id), ambiguous
```
Field **types** of dependency models are fixed by their tasks — open the three
dependency modules and read them before coding. How `EvidenceWeights` exposes a
weight per source (dict vs attributes) must be read from `contracts.py`.

### Does NOT Exist
- ~~`parrot_pipelines.planogram.comparison.scoring` / `.projection`~~ — this task creates them.
- ~~`verified_by_expectation` resolution~~ — reference-engine concept, deliberately NOT ported.
- ~~`PlanogramDescription.visual_features_weight`, `AdvertisementEndcap.brand_weight`~~ — fields do not exist (today's code reads them through `getattr` defaults 0.2 / 0.0); use the constant `0.2` and no brand term.
- ~~A global numeric compliance threshold~~ — thresholds are per shelf (`ShelfConfig.compliance_threshold`); `PlanogramDescription.weighted_scoring` is dead and must not be read.
- ~~`ComplianceStatus.INCONCLUSIVE` / any new enum member~~ — the enum is unchanged; incompleteness lives in `ShelfAssessment`.
- ~~`ShelfScore.status` / `ShelfScore.compliance_status`~~ — status is decided in projection, not stored on `ShelfScore`.
- ~~`Identification.resolved_sku`, `.facing_id`~~ — not contract fields (see Conventions). (`Identification.occupancy` DOES exist — TASK-3421.)
- ~~`plancheck` as an importable package~~ — reference only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceResult",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceStatus",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#PlanogramDescription",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#ShelfConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#AdvertisementEndcap"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Pure, synchronous functions; module-level `logger`; no I/O; no LLM. Shelf ↔
`ShelfConfig` matching is by `ShelfDefinition.level == ShelfConfig.level`; a
definition shelf without a matching `ShelfConfig` uses the non-header defaults
and threshold `0.8` (log at debug).

### Key Constraints
- The "header/endcap" weight branch applies when
  `description.advertisement_endcap` is set, enabled, and its `position` equals
  the shelf level (today's code hard-codes the literal `"header"`; use the
  endcap's position).
- **Terms that apply**: product term applies when `|F_s| > 0` or the shelf has
  required zones; text term applies when a `text_requirements` binding targets
  the shelf (or one of its zones/facings); visual term applies when a
  `visual_features` binding does. Normalise over applying terms only.
  With no rule at all the shelf score equals the product term.
- Rule → shelf resolution: `RuleBinding.target_id` is a `facing_id`, `zone_id`
  or `shelf_id`; resolve it to its shelf through the definition.
- A rule is *failed* when `assessed and passed is False`; *unassessed mandatory*
  rules make the shelf (and the run) incomplete, not failed.
- `penalty(s)` sums `RuleOutcome.penalty` of failed `illumination` bindings.
- "Major unexpected product": this task receives no unexpected list — keep
  `unexpected_products=[]` and treat the condition as false; the type hook may
  post-fill it (document in the docstring).
- Floating point: compare in tests with `pytest.approx`.
- Tests run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `examples/planogram/plancheck/scoring.py` — decision list / merge to re-implement
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:717-777` — today's threshold, weights, penalty, clamp

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `contracts.py`, `comparison/definition.py`, `comparison/registration.py` — *why*: field types come from the dependency tasks, this blueprint only knows their names.
2. Write `scoring.py` (`_decide` → `merge_positions` → `_weights` → `score_shelves` → `summarize`) — *why*: each function feeds the next and the fixtures exercise them bottom-up.
3. Write `projection.py` — *why*: it depends only on contracts, so `scoring.py` never imports it (no cycle).
4. Write the seven fixtures first, then the projection tests — *why*: the fixture values are acceptance criteria of the whole feature (spec §5 "Scoring").

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` (CREATE)
```python
"""Per-facing decision, multi-photo merge and scoring for migrated planogram types (FEAT-574)."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Tuple

from parrot.models.detections import PlanogramDescription, ShelfConfig

from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, ComparisonResult, CreditPolicy, EvidenceWeights, FacingStatus,
    Identification, PositionResult, RuleOutcome, ShelfScore,
)
from parrot_pipelines.planogram.comparison.definition import (
    FacingDefinition, RuleBinding, ShelfDefinition, SlotsDefinition, definition_coverage,
)
from parrot_pipelines.planogram.comparison.registration import ImageRegistration

logger = logging.getLogger(__name__)

_DEFAULT_VISUAL_WEIGHT = 0.2
_DEFAULT_TEXT_WEIGHT = 0.1


def _norm(text: Optional[str]) -> Optional[str]:
    return text.casefold().strip() if text else None


def _is_admissible(obs: Identification) -> bool:
    """Not uncertain, product set, and at least one piece of crop-tied evidence."""
    return bool(not obs.uncertain and obs.product and obs.evidence)


def _decide(facing: FacingDefinition, views: Sequence[Identification],
            matched_elsewhere_on_shelf: bool) -> Tuple[FacingStatus, Optional[Identification]]:
    """Apply the 10-step decision list of the task Scope. Returns (status, deciding observation)."""
    if not views:
        return FacingStatus.NOT_VISIBLE, None
    # FILL IN: steps 2-10 exactly in the order of the Scope list — bounded by: uncertain views never
    #   create a conflict nor override an admissible one; source is never consulted here.
    raise NotImplementedError


def merge_positions(definition: SlotsDefinition, registrations: Sequence[ImageRegistration],
                    identifications: Sequence[Identification], policy: CreditPolicy) -> List[PositionResult]:
    """One PositionResult per expected facing, merging every image's registered observations.

    ``Identification.product`` must already be the canonical product id of the definition.
    Ambiguous registrations contribute nothing (their facings stay not_visible / not_assessed).
    """
    views: Dict[str, List[Identification]] = {}
    by_key = {(i.image_id, i.shape_id): i for i in identifications}
    for reg in registrations:
        if reg.ambiguous:
            continue
        for shape_id, facing_id in reg.assignments.items():
            obs = by_key.get((reg.image_id, shape_id))
            if obs is not None:
                views.setdefault(facing_id, []).append(obs)
    # FILL IN: first pass — admissible product ids seen per shelf (for `misplaced`); second pass — _decide per
    #   facing in definition order, credits from policy.strict/lenient, provenance = every view with its
    #   image_id and source — bounded by AC-2, AC-6.
    raise NotImplementedError


def _weights(shelf: ShelfDefinition, config: Optional[ShelfConfig], description: PlanogramDescription,
             applies: Tuple[bool, bool, bool]) -> Tuple[float, float, float]:
    """Normalised (Wp', Wt', Wv') over the terms that apply (product, text, visual)."""
    # FILL IN: header/endcap vs other-shelf resolution of the Scope formula, zero the non-applying terms,
    #   divide by the sum — bounded by fixture `weight_normalisation`; sum of returned weights == 1.0.
    raise NotImplementedError


def score_shelves(positions: Sequence[PositionResult], definition: SlotsDefinition,
                  bindings: Sequence[RuleBinding], rule_outcomes: Dict[str, RuleOutcome],
                  description: PlanogramDescription, policy: CreditPolicy) -> List[ShelfScore]:
    """One ShelfScore per definition shelf, in definition order (formula of the task Scope)."""
    # FILL IN: facing_strict/lenient with |F_s| in the denominator; text/visual/zone scores from rule_outcomes
    #   (mean of RuleOutcome.score per kind, 1.0 when none apply); product_term = zone_score for zone-only
    #   shelves; illumination penalty / max(1, |F_s|) applied ONCE; clamp01; coverage / visible / occupied
    #   fractions; rule_results = the shelf's RuleOutcomes — bounded by AC-1, AC-3, fixtures 1-7.
    raise NotImplementedError


def summarize(shelf_scores: Sequence[ShelfScore], positions: Sequence[PositionResult],
              definition: SlotsDefinition, weights: EvidenceWeights) -> ComparisonResult:
    """Global measures. ``compliance_results`` is left empty and ``overall_compliant`` False —
    the projection helper ``finalize_comparison`` sets both."""
    # FILL IN: unweighted shelf means (lenient -> overall_compliance_score, strict -> strict_compliance_score);
    #   coverage GLOBAL over facings; definition_coverage(definition)[0]; evidence_quality = mean weight of the
    #   deciding observation of each RESOLVED facing (None when none); assessment_status COMPLETE iff all facings
    #   resolved and no mandatory rule unassessed; no shelves => scores 0.0 — bounded by AC-4, AC-5.
    raise NotImplementedError
```
**Why this shape**: the four public signatures are the spec Module 13 skeleton. `summarize` cannot know shelf
statuses (they need `PlanogramDescription`, which its fixed signature lacks), so it leaves `compliance_results`
empty and `overall_compliant=False`; `finalize_comparison` in the projection module completes the result. This
keeps `scoring` free of any import from `projection` and makes "empty result list is never a pass" the default.
`_decide` never reads `source`: evidence weights feed only `evidence_quality`.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` (CREATE)
```python
"""Projection of shelf scores onto the public ComplianceResult vocabulary (FEAT-574)."""
from __future__ import annotations

import logging
from typing import List, Sequence

from parrot.models.compliance import ComplianceResult, ComplianceStatus, ShelfAssessment
from parrot.models.detections import PlanogramDescription

from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, ComparisonResult, FacingStatus, PositionResult, ShelfScore,
)
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition

logger = logging.getLogger(__name__)

_RESOLVED = {FacingStatus.MATCH, FacingStatus.MISPLACED, FacingStatus.MISMATCH, FacingStatus.EMPTY}


def project_compliance(shelf_scores: Sequence[ShelfScore], positions: Sequence[PositionResult],
                       definition: SlotsDefinition, description: PlanogramDescription
                       ) -> List[ComplianceResult]:
    """One ComplianceResult per definition shelf, definition order. Sets ``ComplianceResult.assessment``.

    Status rules: COMPLIANT iff completely assessed, facing_lenient >= shelf threshold, no mandatory rule
    failed, no illumination mismatch; MISSING iff completely assessed and every facing is EMPTY; MISPLACED
    iff completely assessed and every violation is MISPLACED; otherwise NON_COMPLIANT. ``missing_products``
    lists only facings proven EMPTY (plus illumination pseudo-entries). ``unexpected_products`` is left
    empty for the type hook to fill.
    """
    results: List[ComplianceResult] = []
    # FILL IN: per shelf — expected_products (display_name or product per facing), found_products (identity of
    #   MATCH/MISPLACED/MISMATCH/VARIANT_UNRESOLVED facings), missing_products (EMPTY only + illumination
    #   pseudo-entries from failed illumination RuleOutcome.detail), status per the docstring, compliance_score =
    #   shelf lenient_score (already clamped), ShelfAssessment(...) — bounded by AC-7, AC-8.
    raise NotImplementedError


def finalize_comparison(comparison: ComparisonResult, compliance_results: Sequence[ComplianceResult]
                        ) -> ComparisonResult:
    """Attach the projected results and decide ``overall_compliant``.

    True only when the assessment is COMPLETE, the list is non-empty and every shelf is COMPLIANT.
    """
    compliant = bool(
        compliance_results
        and comparison.assessment_status == AssessmentStatus.COMPLETE
        and all(r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results)
    )
    return comparison.model_copy(update={"compliance_results": list(compliance_results),
                                         "overall_compliant": compliant})
```
**Why**: status rules are spec §2 verbatim. `finalize_comparison` is the one addition to the skeleton — it is
the only place `overall_compliant` can become `True`, so an empty list or an inconclusive run can never pass.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py` (CREATE)
```python
"""Pinned scoring fixtures and projection status tests (FEAT-574, spec §4)."""
from __future__ import annotations

import pytest

from parrot.models.compliance import ComplianceStatus
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, CreditPolicy, EvidenceWeights, FacingStatus, Identification, RuleOutcome,
)
from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize


def _run(definition, description, registrations, identifications, bindings=(), outcomes=None):
    """merge -> score -> summarize -> project -> finalize; returns the final ComparisonResult."""
    policy = CreditPolicy.default()
    positions = merge_positions(definition, registrations, identifications, policy)
    shelves = score_shelves(positions, definition, list(bindings), outcomes or {}, description, policy)
    comparison = summarize(shelves, positions, definition, EvidenceWeights())
    results = project_compliance(shelves, positions, definition, description)
    return finalize_comparison(comparison.model_copy(update={"position_results": positions,
                                                             "shelf_scores": shelves}), results)

# FILL IN: builders `_definition(n_shelves, per_shelf, undescribed=0, header_zone=False)`,
#   `_description(levels, endcap=False)` (PlanogramDescription via PlanogramDescriptionFactory or direct model),
#   `_obs(image_id, shape_id, product, source="cv", uncertain=False, evidence=("sku text",), empty=False)` and
#   `_reg(image_id, {shape_id: facing_id})` — bounded by the dependency contracts.

def test_scoring_fixture_zero_evidence(): ...
def test_scoring_fixture_partial_identity(): ...
def test_scoring_fixture_incomplete_definition(): ...
def test_scoring_fixture_conflicting_photos(): ...
def test_scoring_fixture_zone_only_shelf(): ...
def test_scoring_fixture_full_llm_fallback(): ...
def test_scoring_fixture_weight_normalisation(): ...
def test_projection_statuses(): ...
def test_unseen_products_never_in_missing_products(): ...
def test_empty_result_list_is_never_a_pass(): ...
def test_coverage_is_global_over_facings_not_mean_of_shelves(): ...
def test_overall_score_is_unweighted_shelf_mean(): ...
```
**Why**: the seven `test_scoring_fixture_*` names and values are spec §4; the remaining tests pin spec §5
"Scoring" acceptance criteria one by one.

### FILL IN checklist
- [ ] `scoring.py::_decide` — steps 2-10; bounded by "uncertain never conflicts, source never consulted"
- [ ] `scoring.py::merge_positions` — two passes, provenance kept; bounded by AC-2, AC-6
- [ ] `scoring.py::_weights` — resolution + normalisation; bounded by fixture `weight_normalisation`
- [ ] `scoring.py::score_shelves` — formula; bounded by AC-1, AC-3, fixtures
- [ ] `scoring.py::summarize` — global measures; bounded by AC-4, AC-5
- [ ] `projection.py::project_compliance` — status rules and lists; bounded by AC-7, AC-8
- [ ] `test_scoring_projection.py` — builders + twelve test bodies with the exact values below

---

## Acceptance Criteria

- [ ] AC-1: Every expected facing stays in the shelf denominator; a partial view cannot reach 100 %.
- [ ] AC-2: `merge_positions` returns exactly one `PositionResult` per definition facing, in definition order, with credits read from `CreditPolicy`.
- [ ] AC-3: Weights are normalised over applying terms; illumination penalty multiplies the combined score once; every shelf score is within `[0, 1]`; zone-only shelves never divide by zero.
- [ ] AC-4: `overall_compliance_score` / `strict_compliance_score` are unweighted shelf means; `coverage` is global over facings.
- [ ] AC-5: `evidence_quality` uses `EvidenceWeights` only; it never changes a credit or a status; a full-`llm` run can reach compliance 1.0.
- [ ] AC-6: Incompatible admissible identities across photos ⇒ `conflict` with both provenances kept; an uncertain second photo does not create a conflict.
- [ ] AC-7: Status projection follows the four rules; `ComplianceStatus` is unchanged; every result carries a `ShelfAssessment`.
- [ ] AC-8: `missing_products` contains only `empty` facings (+ illumination pseudo-entries); `not_visible` / `not_assessed` facings never appear there.
- [ ] AC-9: `overall_compliant` is `True` only via `finalize_comparison` with a non-empty list, `COMPLETE` status and all shelves `COMPLIANT`.
- [ ] AC-10: The seven pinned fixtures pass with the exact values of the Test Specification.
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`

---

## Test Specification

**Pinned scoring fixtures** (spec §4 — values are not negotiable):

| Fixture | Setup | Expected |
|---|---|---|
| `zero_evidence` | no observations at all | every facing `not_assessed`; scores 0.0; coverage 0.0; `inconclusive`; `overall_compliant=False` |
| `partial_identity` | 10 facings: 6 `match`, 4 `variant_unresolved` | `facing_lenient=0.8`, `facing_strict=0.6`, coverage 0.6, `inconclusive`, shelf `NON_COMPLIANT` |
| `incomplete_definition` | 10 facings, 4 undescribed and unreadable | `definition_coverage=0.6`; the 4 stay unresolved; an independently readable identifier resolves one |
| `conflicting_photos` | two photos, incompatible admissible identities for one facing | `conflict`, credits 0/0, both provenances kept; an unreadable second photo does **not** create a conflict |
| `zone_only_shelf` | header shelf: 0 facings, required backlit zone, 2 text requirements, illumination rule | no division by zero; `product_term = zone_score`; illumination mismatch multiplies once |
| `full_llm_fallback` | all shapes `source="llm"`, all matched with admissible evidence | compliance 1.0, `complete`, `overall_compliant=True`, `evidence_quality=0.5`, `detection_source="llm"` |
| `weight_normalisation` | non-header shelf, default weights, `facing_lenient=0.9`, text 1.0, visual 1.0 | `(0.9·0.8+0.1+0.2)/1.1 = 0.927…` — not the legacy clamped 1.0 |

Notes for the executor:
- `zero_evidence`: the spec says `not_assessed` for this fixture. With **no registration at all** the decision
  list yields `not_visible`; build the fixture as "registered observations exist but all are `uncertain`" so the
  status is `not_assessed`, and add a second assertion that the no-registration variant yields `not_visible`
  with the same zero scores.
- `full_llm_fallback`: `detection_source` is a run-level key owned by the `run()` template — here assert only
  the `source` of every provenance entry is `llm`.
- `weight_normalisation` needs a text and a visual binding on the shelf with `RuleOutcome(score=1.0, passed=True)`
  so all three terms apply.

```python
def test_scoring_fixture_weight_normalisation():
    ...
    shelf = result.shelf_scores[0]
    assert shelf.facing_lenient == pytest.approx(0.9)
    assert shelf.lenient_score == pytest.approx((0.9 * 0.8 + 0.1 + 0.2) / 1.1)   # 0.92727…
    assert shelf.lenient_score < 1.0


def test_scoring_fixture_partial_identity():
    ...
    shelf = result.shelf_scores[0]
    assert shelf.facing_lenient == pytest.approx(0.8)
    assert shelf.facing_strict == pytest.approx(0.6)
    assert result.coverage == pytest.approx(0.6)
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.compliance_results[0].compliance_status == ComplianceStatus.NON_COMPLIANT
    assert result.overall_compliant is False


def test_scoring_fixture_zone_only_shelf():
    ...  # header: 0 facings, zone observed, text outcomes 1.0 and 0.5, illumination failed with penalty 0.5
    header = result.shelf_scores[0]
    assert header.expected_facings == 0
    # product_term = zone_score = 1.0 ; text = 0.75 ; header weights 0.64/0.2/(0.16 not applying) -> normalised
    expected = ((1.0 * 0.64 + 0.75 * 0.2) / (0.64 + 0.2)) * (1 - 0.5 / 1)
    assert header.lenient_score == pytest.approx(expected)
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
7. **Move this file** to `tasks/completed/TASK-3441-scoring-projection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
comparison/scoring.py: _decide (10-step list; reliable = not uncertain and saying occupancy/product/brand; empty only via occupancy=='empty'; uncertain never conflicts; source never consulted), merge_positions (one PositionResult per facing in definition order, credits from CreditPolicy, deciding observation FIRST in observations + 'deciding:<image>/<shape>' note, all provenance kept, ambiguous registrations ignored), _weights (header/endcap branch keyed on endcap.position; non-header defaults 0.8/0.1/0.2; normalised over applying terms), score_shelves (|F_s| always in the denominator, zone_score = required zones with a passed zone_present outcome, text/visual = mean assessed outcome score (unassessed earn 0), illumination penalty / max(1,|F|) applied once via _combine, clamp01), summarize (unweighted shelf means, global coverage, definition_coverage, evidence_quality from the deciding observation of resolved facings, COMPLETE iff all facings resolved and all rule_results assessed).
comparison/projection.py: project_compliance (status rules; missing_products = EMPTY facings + illumination pseudo-entries; ShelfAssessment on every result) and finalize_comparison (only place overall_compliant can be True).
Design decision (signature gap): project_compliance cannot see bindings, so score_shelves puts into ShelfScore.rule_results only status-relevant outcomes — every MANDATORY binding (unassessed placeholder when no outcome) plus assessed illumination ones; projection treats a failed entry as blocking and a failed entry with penalty>0 (only illumination rules carry penalties) as an illumination pseudo-entry. Zero-facing shelves satisfy the facing threshold vacuously (rules decide).
Tests: test_scoring_projection.py 12 passed — the 7 pinned fixtures with the spec values (weight_normalisation 0.92727, zone_only ((0.64+0.15)/0.84)*0.5, partial_identity 0.8/0.6/0.6, full_llm evidence_quality 0.5, ...) + 5 projection tests. ruff clean on comparison/.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
