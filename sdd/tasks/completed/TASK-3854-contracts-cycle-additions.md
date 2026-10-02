# TASK-3854: Cycle contract additions: OCR, reference, rule-evidence models and new enum values

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** ("Additions to existing contracts") and §2 Stage 2 / Stage 3. Every later
FEAT-612 module exchanges data through `planogram/contracts.py`: the shared perception stage
(TASK-3856) stores own-target OCR reads, the reference bank (TASK-3857) needs a per-run
`ReferenceImage`, the rule-evidence collector (TASK-3859) emits neutral `RuleObservation`s, and
scoring (TASK-3862) needs two new facing statuses for expected-empty positions. This task adds
those models, fields and enum values **additively** — nothing is removed. `LegacyPayload` and
`PerceptionResult.legacy` stay until TASK-3871 cuts the orchestrator over; historical enum values
(`ObservationSource.LEGACY_LLM`, `AssessmentStatus.LEGACY_UNMEASURED`, `EvidenceWeights.legacy_llm`)
stay permanently for reading old serialized results (spec §2 compatibility policy, §8).

---

## Scope

- Add `IdentifyStrategy.SLOTS = "slots"` (the opt-in per-slot crop strategy, spec §2 layout table).
- Add `FacingStatus.EXPECTED_EMPTY = "expected_empty"` and `FacingStatus.UNEXPECTED_OCCUPIED = "unexpected_occupied"`.
- Extend `CreditPolicy.default()` so `EXPECTED_EMPTY` gets strict 1.0 / lenient 1.0 and
  `UNEXPECTED_OCCUPIED` gets 0.0 / 0.0 (spec §2 Stage 3); extend `CreditPolicy.is_resolved` so
  both new statuses are resolved.
- Add the three new models `OcrReading`, `ReferenceImage`, `RuleObservation` exactly as the M1 skeleton.
- Add the fields `PerceptionResult.ocr_readings`, `Identification.reference_id`,
  `IdentificationResult.rule_observations`, `RuleOutcome.observations` (reusing the existing
  `ObservationRef`), `CycleContext.layout`, `CycleContext.reference_bank`, `CycleContext.images`.
- Extend `tests/planogram_cycle/test_contracts.py` for every addition and update the one test that
  pins the exact resolved-status set.

**NOT in scope**: removing `LegacyPayload` / `PerceptionResult.legacy` (TASK-3871); the
`LayoutProfile` model itself (TASK-3855 — `CycleContext.layout` is typed `Any` on purpose);
using the new statuses in `merge_positions` / `score_shelves` / projection (TASK-3862); filling
`ocr_readings` (TASK-3857/3859); filling `rule_observations` (TASK-3859); reading
`RuleOutcome.observations` (TASK-3862/3863). Do not touch any other source file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | New enum values, three new models, seven new fields, credit policy update |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py` | MODIFY | Tests for every addition; update resolved-set test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already at the top of contracts.py — reuse, add nothing new
from enum import Enum                                                      # contracts.py:5
from pathlib import Path                                                   # contracts.py:6
from typing import Any, Dict, List, Optional, Tuple                        # contracts.py:7
from pydantic import BaseModel, ConfigDict, Field, model_validator         # contracts.py:9
from parrot.models.compliance import ComplianceResult                      # contracts.py:11
from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion   # contracts.py:12
```
`from __future__ import annotations` is on line 3 — define every new model ABOVE the first model
that references it so Pydantic resolves the annotation at class-creation time.

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class ObservationSource(str, Enum): CV="cv", LLM_ADDED="llm_added", LLM="llm", LEGACY_LLM="legacy_llm"   # :26-32
class IdentifyStrategy(str, Enum): FULL_IMAGE="full_image", STRIPS="strips"                          # :43-47
class Slot(BaseModel): ...                                                                            # :67-76
class LegacyPayload(BaseModel): identified_products, shelf_regions                                   # :79-83 (KEEP)
class PerceptionResult(BaseModel):                                                                    # :86
    image_id, image_size, shapes, slots, zones, row_count, detection_source, ocr_available,
    legacy: Optional[LegacyPayload] = None                                                            # :97
    errors: List[str]                                                                                  # :98
class Identification(BaseModel): ... source ... # :113 ; uncertain: bool = False                     # :101-114
class IdentificationResult(BaseModel): image_id, identifications, added (:142), errors (:143)         # :137-143
class FacingStatus(str, Enum): MATCH … NOT_VISIBLE = "not_visible"                                    # :146-158
class ObservationRef(BaseModel): image_id, shape_id, source, raw_confidence, product, occupancy        # :169-177
class RuleOutcome(BaseModel): rule_id, assessed, passed, score, penalty, detail (:188)                # :180-188
class CreditPolicy(BaseModel):                                                                        # :221
    strict: Dict[FacingStatus, float]; lenient: Dict[FacingStatus, float]
    _check validator: every FacingStatus in both maps, 0..1, strict <= lenient                         # :227-247
    @classmethod
    def default(cls) -> "CreditPolicy"                                                                # :249-268
        # branch for INFERRED_PRESENT / VARIANT_UNRESOLVED at :259
    def is_resolved(self, status: FacingStatus) -> bool                                               # :270-279
class EvidenceWeights(BaseModel): cv, llm_added, llm, legacy_llm                                      # :282-292 (KEEP legacy_llm)
class CycleContext(BaseModel):                                                                        # :322
    model_config = ConfigDict(arbitrary_types_allowed=True)                                           # :325
    vision, executor, ocr, definition, bindings, credit_policy, evidence_weights,
    output_dir: Optional[Path] = None                                                                 # :334
    errors: List[str]                                                                                  # :335
```

Only one caller builds a `CreditPolicy` outside tests: `plan.py:237` (`CreditPolicy.default()`).
No source code iterates `FacingStatus` except `CreditPolicy` (verified: `grep -rn 'for status in FacingStatus' src`).

### Does NOT Exist
- ~~`IdentifyStrategy.SLOTS`~~, ~~`FacingStatus.EXPECTED_EMPTY`~~, ~~`FacingStatus.UNEXPECTED_OCCUPIED`~~ — this task adds them.
- ~~`OcrReading`~~, ~~`ReferenceImage`~~, ~~`RuleObservation`~~ — this task adds them.
- ~~`PerceptionResult.ocr_readings`~~, ~~`Identification.reference_id`~~, ~~`IdentificationResult.rule_observations`~~,
  ~~`RuleOutcome.observations`~~, ~~`CycleContext.layout` / `.reference_bank` / `.images`~~ — this task adds them.
- ~~`parrot_pipelines.planogram.layout`~~ — created by TASK-3855; contracts.py must NEVER import it (spec §7:
  "contracts keep layout as an opaque, constructor-validated service" — `perception/slots.py` imports
  contracts, and layout imports slots, so importing layout here would be a cycle).
- ~~A new `ObservationRef`~~ — it already exists at `:169`; reuse it for `RuleOutcome.observations`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ObservationSource",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentifyStrategy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#LegacyPayload",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Identification",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentificationResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#FacingStatus",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ObservationRef",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#RuleOutcome",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CreditPolicy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CreditPolicy.default",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CreditPolicy.is_resolved",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#EvidenceWeights",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Every existing contract model is a plain `BaseModel` with `Field(default_factory=...)` for mutable
defaults and short inline comments naming who owns a field (e.g. `# pipeline-owned`). Follow that
style; do not add `extra="forbid"` to these models (existing serialized results must keep parsing —
spec §7 "Unknown obsolete payload fields follow existing Pydantic parsing behavior").

### Key Constraints
- **Additive only.** Every existing field, default and enum value keeps its name, value and order;
  append new enum members at the END of their enum so `list(FacingStatus)` order of old members is unchanged.
- `CycleContext.layout` is `Any = None` — never import `LayoutProfile` here (import cycle, see Does NOT Exist).
- `CycleContext.images` holds run-owned PIL images; it is per-run state (spec §2 Overview:
  "Per-run state belongs to CycleContext") — `arbitrary_types_allowed=True` is already set.
- `ReferenceImage.image` is raw encoded bytes; never add a PIL object to it.
- `RuleObservation` is a neutral observation (what is visible), never a rule verdict: it has no
  `passed` field (spec §2 Stage 2 "Ask what is visible, never whether the configured expected answer is satisfied").
- `CreditPolicy._check` demands every status in both maps; after adding enum members,
  `CreditPolicy.default()` must emit them or `CycleContext()` itself fails to construct.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the worktree.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:169-188` — `ObservationRef` / `RuleOutcome` style
- spec §3 Module 1 skeleton (lines 373-404 of the spec) — normative field list

---

## Implementation Blueprint

### Steps (in order)
1. Add `SLOTS` to `IdentifyStrategy` — *why*: `LayoutProfile.identify_strategy` (TASK-3855) validates against this enum.
2. Add the two `FacingStatus` members at the end of the enum — *why*: scoring (TASK-3862) must not reuse MATCH for an empty slot (spec §2 Stage 3).
3. Insert `OcrReading`, `ReferenceImage`, `RuleObservation` above `LegacyPayload` — *why*: they must be defined before `PerceptionResult`, `IdentificationResult` and `CycleContext` reference them.
4. Add the four result-model fields and the three `CycleContext` fields — *why*: per-run OCR/reference/evidence data needs a home that is not a reusable type instance (spec §2 Overview).
5. Update `CreditPolicy.default()` and `is_resolved()` — *why*: `_check` rejects a policy missing any status, and coverage counts expected-empty positions as resolved.
6. Extend `test_contracts.py`, run the validation commands — *why*: AC9 / AC16 regression coverage.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc '    STRIPS = "strips"' contracts.py)
# AFTER — insert below `    STRIPS = "strips"` (verified: contracts.py:47)
    SLOTS = "slots"  # opt-in: one padded crop per slot (FEAT-612)
```
```python
# occurrences: 1 (verified: grep -Fxc '    NOT_VISIBLE = "not_visible"' contracts.py)
# AFTER — insert below `    NOT_VISIBLE = "not_visible"` (verified: contracts.py:158)
    EXPECTED_EMPTY = "expected_empty"  # expected-empty position observed empty (strict 1 / lenient 1)
    UNEXPECTED_OCCUPIED = "unexpected_occupied"  # expected-empty position observed occupied (0 / 0)
```
```python
# occurrences: 1 (verified: grep -Fxc 'class LegacyPayload(BaseModel):' contracts.py)
# BEFORE — insert above `class LegacyPayload(BaseModel):` (verified: contracts.py:79), two blank lines around
class OcrReading(BaseModel):
    """Local read keyed by an observed target id."""

    text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReferenceImage(BaseModel):
    """Per-run encoded reference with opaque prompt label and catalogue metadata."""

    label: str  # opaque prompt label, e.g. "ref-0001" — never an expected placement
    image: bytes  # encoded image bytes (loaded once per run)
    catalog_key: str  # key of PlanogramCompliance.reference_images it came from
    brand: Optional[str] = None


class RuleObservation(BaseModel):
    """Neutral crop-tied observation, not an expected-rule verdict."""

    image_id: str
    target_id: str  # observed zone/shape id, or "<image_id>:zone-region:<zone_id>" for an inspected region
    kind: Literal["illumination", "visual_features", "zone_present"]
    value: str | bool | List[str] | None = None
    assessed: bool = False
    source: ObservationSource
    evidence: List[str] = Field(default_factory=list)
```
```python
# occurrences: 1 (verified: grep -Fxc '    legacy: Optional[LegacyPayload] = None' contracts.py)
# AFTER — insert below `    legacy: Optional[LegacyPayload] = None` (verified: contracts.py:97)
    ocr_readings: Dict[str, OcrReading] = Field(default_factory=dict)  # target id -> own-box local read
```
```python
# occurrences: 1 (verified: grep -Fxc '    uncertain: bool = False' contracts.py)
# AFTER — insert below `    uncertain: bool = False` (verified: contracts.py:114, inside Identification)
    reference_id: Optional[str] = None  # opaque reference label offered in THIS call, else None
```
```python
# occurrences: 1 (verified: grep -Fxc '    added: List[Shape] = Field(default_factory=list)  # accepted additions, pipeline-owned ids, source=LLM_ADDED' contracts.py)
# AFTER — insert below that `added:` line (verified: contracts.py:142, inside IdentificationResult)
    rule_observations: List[RuleObservation] = Field(default_factory=list)  # neutral, per-run evidence
```
```python
# occurrences: 1 (verified: grep -Fxc '    detail: Optional[str] = None' contracts.py)
# AFTER — insert below `    detail: Optional[str] = None` (verified: contracts.py:188, inside RuleOutcome)
    observations: List[ObservationRef] = Field(default_factory=list)  # deciding zone/rule evidence
```
```python
# occurrences: 1 (verified: grep -Fxc '    output_dir: Optional[Path] = None' contracts.py)
# AFTER — insert below `    output_dir: Optional[Path] = None` (verified: contracts.py:334, inside CycleContext)
    layout: Any = None  # validated LayoutProfile (typed Any: avoids the slots/contracts import cycle)
    reference_bank: List[ReferenceImage] = Field(default_factory=list)
    images: Dict[str, Any] = Field(default_factory=dict)  # image_id -> PIL image, run-owned
```
```python
# REPLACE the typing import (verified: contracts.py:7, occurrences: 1)
from typing import Any, Dict, List, Literal, Optional, Tuple
```
```python
# CreditPolicy.default (verified: contracts.py:249-268). REPLACE the `if status is FacingStatus.MATCH:` test
# (contracts.py:256) so EXPECTED_EMPTY shares the MATCH branch; UNEXPECTED_OCCUPIED falls to the final else (0/0).
            if status in {FacingStatus.MATCH, FacingStatus.EXPECTED_EMPTY}:
```
```python
# CreditPolicy.is_resolved (verified: contracts.py:270-279). occurrences: 1
# AFTER — insert below `            FacingStatus.VARIANT_UNRESOLVED,` (verified: contracts.py:278)
            FacingStatus.EXPECTED_EMPTY,
            FacingStatus.UNEXPECTED_OCCUPIED,
```
**Why**: the M1 skeleton fixes every name, type and default; placement before first use keeps
Pydantic's forward-reference resolution trivial. `value: str | bool | List[str] | None` is legal
with `from __future__ import annotations` on Python ≥3.10 (the package already uses `set[str]` in
`comparison/definition.py:164`). The credit numbers are spec §2 Stage 3 verbatim; do NOT touch the
MISPLACED 0.5 or INFERRED/VARIANT 1.0 lenient credits.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc '        FacingStatus.INFERRED_PRESENT,' test_contracts.py)
# AFTER — insert below `        FacingStatus.INFERRED_PRESENT,` (verified: test_contracts.py:76, inside
# test_is_resolved_includes_occupied_expected_positions' `resolved` set)
        FacingStatus.EXPECTED_EMPTY,
        FacingStatus.UNEXPECTED_OCCUPIED,
```
Extend the import block (`test_contracts.py:5-16`) with `IdentificationResult, IdentifyStrategy,
OcrReading, ReferenceImage, RuleObservation, RuleOutcome, ObservationRef` and append the new test
functions from the Test Specification at the end of the file.

**Why**: `test_is_resolved_includes_occupied_expected_positions` asserts the EXACT resolved set for
every `FacingStatus`, so it fails the moment the enum grows unless updated.

### FILL IN checklist
- [ ] `contracts.py` — placement of the three new models above `LegacyPayload`; bounded by: no forward refs to later classes.
- [ ] `CreditPolicy.default` — EXPECTED_EMPTY 1/1, UNEXPECTED_OCCUPIED 0/0; bounded by spec §2 Stage 3 and `_check`.
- [ ] `test_contracts.py` — new tests per Test Specification; bounded by AC9/AC16.

---

## Acceptance Criteria

- [ ] `IdentifyStrategy("slots") is IdentifyStrategy.SLOTS`; `FULL_IMAGE`/`STRIPS` unchanged (spec M1).
- [ ] `CreditPolicy.default()` validates and gives EXPECTED_EMPTY 1.0/1.0, UNEXPECTED_OCCUPIED 0.0/0.0;
      all previous credits unchanged (MATCH 1/1, INFERRED_PRESENT and VARIANT_UNRESOLVED 0/1, MISPLACED 0/0.5) (spec AC8/AC9).
- [ ] `is_resolved` is True for both new statuses and unchanged for all old ones.
- [ ] `OcrReading(confidence=1.5)` and `OcrReading(confidence=-0.1)` raise `ValueError`; defaults are `("", 0.0)`.
- [ ] `RuleObservation` requires `image_id`, `target_id`, `kind`, `source`; `assessed` defaults False; it has no `passed` field (AC7).
- [ ] New fields default to empty/None: `PerceptionResult().ocr_readings == {}`, `Identification(shape_id=...).reference_id is None`,
      `IdentificationResult().rule_observations == []`, `RuleOutcome(rule_id="r").observations == []`,
      `CycleContext().layout is None`, `.reference_bank == []`, `.images == {}`.
- [ ] Historical values still deserialize: `ObservationSource("legacy_llm")`, `AssessmentStatus("legacy_unmeasured")`,
      `EvidenceWeights().legacy_llm == 0.5`, `PerceptionResult(legacy=LegacyPayload())` (spec §2 compatibility policy).
- [ ] `contracts.py` does not import `parrot_pipelines.planogram.layout`.
- [ ] Every pytest command below passes; `ruff check` and `black --check` are clean on both files.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py  (append)
from parrot_pipelines.planogram.contracts import (  # merge into the existing import block
    IdentificationResult, IdentifyStrategy, LegacyPayload, ObservationRef, OcrReading,
    ReferenceImage, RuleObservation, RuleOutcome,
)


def test_slots_identify_strategy_value() -> None:
    assert IdentifyStrategy.SLOTS.value == "slots"
    assert IdentifyStrategy("full_image") is IdentifyStrategy.FULL_IMAGE
    assert IdentifyStrategy("strips") is IdentifyStrategy.STRIPS


def test_expected_empty_credits_and_resolution() -> None:
    policy = CreditPolicy.default()
    assert policy.strict[FacingStatus.EXPECTED_EMPTY] == 1.0
    assert policy.lenient[FacingStatus.EXPECTED_EMPTY] == 1.0
    assert policy.strict[FacingStatus.UNEXPECTED_OCCUPIED] == 0.0
    assert policy.lenient[FacingStatus.UNEXPECTED_OCCUPIED] == 0.0
    assert policy.is_resolved(FacingStatus.EXPECTED_EMPTY)
    assert policy.is_resolved(FacingStatus.UNEXPECTED_OCCUPIED)
    # FILL IN: assert the pre-existing credits (MATCH 1/1, MISPLACED 0/0.5, INFERRED_PRESENT 0/1) are unchanged


def test_ocr_reading_bounds() -> None:
    assert OcrReading().text == "" and OcrReading().confidence == 0.0
    # FILL IN: pytest.raises(ValueError) for confidence 1.5 and -0.1


def test_reference_image_is_bytes_and_label() -> None:
    ref = ReferenceImage(label="ref-0001", image=b"\x89PNG", catalog_key="refs")
    assert ref.brand is None and ref.image == b"\x89PNG"


def test_rule_observation_is_neutral() -> None:
    obs = RuleObservation(image_id="img0", target_id="img0:zone-region:z1", kind="zone_present",
                          source=ObservationSource.LLM)
    assert obs.assessed is False and obs.value is None and obs.evidence == []
    assert "passed" not in RuleObservation.model_fields
    # FILL IN: pytest.raises(ValueError) for kind="text_requirements" (not an allowed observation kind)


def test_new_fields_default_empty() -> None:
    assert PerceptionResult().ocr_readings == {}
    assert Identification(shape_id="img0:r0:s1").reference_id is None
    assert IdentificationResult().rule_observations == []
    assert RuleOutcome(rule_id="r").observations == []
    ctx = CycleContext()
    assert ctx.layout is None and ctx.reference_bank == [] and ctx.images == {}
    # FILL IN: RuleOutcome(rule_id="r", observations=[ObservationRef(image_id="img0", shape_id="z",
    #          source=ObservationSource.CV)]) round-trips through model_dump()/model_validate()


def test_historical_values_still_parse() -> None:
    assert ObservationSource("legacy_llm") is ObservationSource.LEGACY_LLM
    assert AssessmentStatus("legacy_unmeasured") is AssessmentStatus.LEGACY_UNMEASURED
    assert EvidenceWeights().legacy_llm == 0.5
    assert PerceptionResult(legacy=LegacyPayload()).legacy is not None
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3854 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented by coder seat via sdd-worker orchestration (merge-tier tests green for planogram scope; unrelated ai-parrot-server collection errors due to missing fakeredis in shared env).

