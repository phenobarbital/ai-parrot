# TASK-3421: Cycle contracts and additive ShelfAssessment

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** and §2 *Data Models*. The three stages of the new cycle
(perceive → identify → compare) exchange Pydantic models. Every other task of this feature
imports them from ONE module, so the names, field names and defaults fixed here are the
vocabulary of the whole feature. The task also adds one optional, additive field to the core
`ComplianceResult` so a shelf can explain an incomplete assessment without changing the
existing `ComplianceStatus` enum.

---

## Scope

- Create `parrot_pipelines/planogram/contracts.py` with every enum and model listed in the
  Implementation Blueprint — field names, types and defaults exactly as written there.
- Implement `CreditPolicy.default()`, its validation (`0 <= credit <= 1`, `strict <= lenient`,
  every `FacingStatus` present in both maps) and `CreditPolicy.is_resolved()`.
- Implement `EvidenceWeights` with defaults `cv=1.0, llm_added=0.5, llm=0.5, legacy_llm=0.5`
  and `weight_for(source)`.
- Add `ShelfAssessment` and the optional `ComplianceResult.assessment` field to
  `parrot/models/compliance.py` (additive only).
- Write `test_contracts.py`.

**NOT in scope**: the slots-definition models (`SlotsDefinition`, `RuleBinding`, … belong to
TASK-3435), any algorithm, any change to `ComplianceStatus` or to an existing
`ComplianceResult` field.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | CREATE | Enums + Pydantic contracts of the cycle |
| `packages/ai-parrot/src/parrot/models/compliance.py` | MODIFY | Add `ShelfAssessment` + optional `ComplianceResult.assessment` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, model_validator
from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion  # verified: packages/ai-parrot/src/parrot/models/detections.py:37, :71, :62
from parrot.models.compliance import ComplianceResult, ComplianceStatus           # verified: packages/ai-parrot/src/parrot/models/compliance.py:32, :9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py
class DetectionBox(BaseModel):          # :37-60
    x1: int; y1: int; x2: int; y2: int  # :39-42
    confidence: float                   # :43  REQUIRED, ge=0 le=1 (non-numeric coerced to 0.5 by a validator :45-52)
    class_id: int = None; class_name: str = None; area: int = None   # :53-55
    label: Optional[str] = None         # :56
    ocr_text: Optional[str] = None      # :57-60
class ShelfRegion(BaseModel):           # :62-68   shelf_id, bbox: DetectionBox, level, objects, is_background
class IdentifiedProduct(BaseModel):     # :71-206  product_type (required), confidence (required), …

# packages/ai-parrot/src/parrot/models/compliance.py   (208 lines; imports at :1-6: typing List/Optional/Tuple/Iterable/Set,
#                                                        Enum, re, unicodedata, SequenceMatcher, pydantic BaseModel/Field)
class ComplianceStatus(str, Enum):      # :9-14   COMPLIANT | NON_COMPLIANT | MISSING | MISPLACED   — DO NOT TOUCH
class ComplianceResult(BaseModel):      # :32-52
    shelf_level: str                    # :34
    expected_products / found_products / missing_products / unexpected_products: List[str]   # :35-38
    compliance_status: ComplianceStatus # :39-41
    compliance_score: float             # :42-46  ge=0.0, le=1.0
    text_compliance_results: List[TextComplianceResult]           # :47
    brand_compliance_result: Optional[BrandComplianceResult]      # :48-50
    text_compliance_score: float = Field(default=1.0)             # :51
    overall_text_compliant: bool = Field(default=True)            # :52   <-- LAST field; the new field goes right below
# No model_config / class Config anywhere in compliance.py or detections.py (extra="ignore").
```

### Does NOT Exist
- ~~`parrot_pipelines/planogram/contracts.py`~~ — created by this task.
- ~~`ComplianceResult.assessment`, `ShelfAssessment`~~ — created by this task.
- ~~`typing.Dict` / `typing.Any` imported in `compliance.py`~~ — only `List, Optional, Tuple, Iterable, Set` are imported (:1); extend that import line.
- ~~a `PixelBox` / `Box` model~~ — boxes are always `DetectionBox` (which REQUIRES `confidence`).
- ~~`ComplianceStatus.INCONCLUSIVE` / `UNKNOWN`~~ — the enum is unchanged; incompleteness lives in `ShelfAssessment`.
- ~~`model_config = ConfigDict(extra="forbid")` on existing core models~~ — none; do not add it to them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/models/compliance.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#ShelfRegion",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#IdentifiedProduct",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceResult",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceStatus"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2. Google-style docstrings on every class. 120-column lines (`black`).
- `contracts.py` must import **only** pydantic, stdlib and `parrot.models.*` — never another
  module of this feature (it is a root of the task graph; importing anything else creates a cycle).
- Service handles inside `CycleContext` are typed `Any` on purpose (same reason).
- Every list/dict default uses `Field(default_factory=...)`.
- Field names below are load-bearing: later tasks were written against them. Do not rename,
  do not change a default, do not make an optional field required.
- Run tests inside the worktree with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src pytest <file> -q`
  (the shared `.venv` is editable-installed against the main checkout).

### References in Codebase
- `packages/ai-parrot/src/parrot/models/compliance.py` — style of the existing result models.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, field name, default or file path the blueprint fixes. The three
> `contracts.py` blocks are ONE file, in this order.

### Steps (in order)
1. Create `contracts.py` from blocks 1-3 — *why*: every other task imports these names.
2. Fill in `CreditPolicy.default()`, its validator and `is_resolved` — *why*: the credit table of
   spec §2 must exist in exactly one place.
3. Apply the two edits to `compliance.py` — *why*: the projection task needs a place to explain an
   incomplete shelf without touching the enum.
4. Write the tests, run the Validation Command, then `ruff check` both source files.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` (CREATE) — block 1/3: enums + perception
```python
"""Shared Pydantic contracts of the perceive → identify → compare cycle (FEAT-574)."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.models.compliance import ComplianceResult
from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion


class ShapeKind(str, Enum):
    """Kind of a perceived shape."""

    PRICE_TAG = "price_tag"
    PRODUCT = "product"
    BOX = "box"
    FACT_TAG = "fact_tag"
    ZONE = "zone"
    UNKNOWN = "unknown"


class ObservationSource(str, Enum):
    """Who produced an observation. Never implies SKU identity."""

    CV = "cv"
    LLM_ADDED = "llm_added"
    LLM = "llm"
    LEGACY_LLM = "legacy_llm"


class FixtureMembership(str, Enum):
    """Whether a shape belongs to the fixture under assessment."""

    ON_FIXTURE = "on_fixture"
    OFF_FIXTURE = "off_fixture"
    UNCERTAIN = "uncertain"


class IdentifyStrategy(str, Enum):
    """LLM call granularity declared by a planogram type."""

    FULL_IMAGE = "full_image"
    STRIPS = "strips"
```

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
class Shape(BaseModel):
    """One perceived shape, in SOURCE-image pixels."""

    shape_id: str
    image_id: str
    kind: ShapeKind = ShapeKind.UNKNOWN
    box: DetectionBox
    profile: Optional[str] = None
    row_index: Optional[int] = None          # 0-based, top → bottom
    slot_index: Optional[int] = None         # 1..n inside its row
    ocr_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    source: ObservationSource = ObservationSource.CV
    membership: FixtureMembership = FixtureMembership.UNCERTAIN
    membership_evidence: List[str] = Field(default_factory=list)


class Slot(BaseModel):
    """A product position derived from shapes (or gap-filled)."""

    slot_id: str                             # "<image_id>:r<row_index>:s<slot_index>"
    image_id: str
    row_index: int
    slot_index: int
    box: DetectionBox
    anchor_shape_id: Optional[str] = None
    inferred: bool = False


class LegacyPayload(BaseModel):
    """What the legacy adapter carries between hooks."""

    identified_products: List[IdentifiedProduct] = Field(default_factory=list)
    shelf_regions: List[ShelfRegion] = Field(default_factory=list)


class PerceptionResult(BaseModel):
    """Stage-1 output for one image."""

    image_id: str = "img0"
    image_size: Tuple[int, int] = (0, 0)     # (width, height)
    shapes: List[Shape] = Field(default_factory=list)
    slots: List[Slot] = Field(default_factory=list)
    zones: List[Shape] = Field(default_factory=list)
    row_count: int = 0
    detection_source: str = "cv"             # "cv" | "llm" | "legacy_llm"
    ocr_available: bool = False
    legacy: Optional[LegacyPayload] = None
    errors: List[str] = Field(default_factory=list)
```
**Why this shape**: enum *values* are the strings the result dict exposes (`source="llm_added"`,
`detection_source="llm"`), so they are fixed by spec §2. `detection_source` is a plain `str`
because the run-level value may also be `"mixed"`. `Slot.slot_id` format and 0-based `row_index`
are the conventions the perception and registration tasks were written against.

### `…/planogram/contracts.py` (CREATE) — block 2/3: identification
```python
class Identification(BaseModel):
    """Stage-2 output for one shape or slot. Also the item type the LLM returns."""

    shape_id: str                            # a Shape.shape_id OR a Slot.slot_id
    image_id: Optional[str] = None           # pipeline-owned: overwritten after validation
    product: Optional[str] = None
    brand: Optional[str] = None
    text: Optional[str] = None               # OCR text confirmed / corrected by the LLM
    descriptors: Dict[str, Any] = Field(default_factory=dict)
    occupancy: str = "unknown"               # "occupied" | "empty" | "unknown"
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)   # model-reported, NEVER modified
    evidence: List[str] = Field(default_factory=list)
    source: ObservationSource = ObservationSource.CV             # pipeline-owned
    uncertain: bool = False


class AddedShape(BaseModel):
    """A shape the LLM proposes that perception missed. Has no authority over existing ids."""

    box_norm: List[int]                      # [ymin, xmin, ymax, xmax], 0-1000, relative to the image/strip sent
    kind: ShapeKind = ShapeKind.UNKNOWN
    product: Optional[str] = None
    brand: Optional[str] = None
    text: Optional[str] = None
    descriptors: Dict[str, Any] = Field(default_factory=dict)
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class IdentificationResponse(BaseModel):
    """Structured output of one identification call."""

    existing_identifications: List[Identification] = Field(default_factory=list)
    added_shapes: List[AddedShape] = Field(default_factory=list)


class IdentificationResult(BaseModel):
    """Stage-2 output for one image, after validation."""

    image_id: str = "img0"
    identifications: List[Identification] = Field(default_factory=list)
    added: List[Shape] = Field(default_factory=list)   # accepted additions, pipeline-owned ids, source=LLM_ADDED
    errors: List[str] = Field(default_factory=list)
```
**Why this shape**: `existing_identifications` and `added_shapes` are separate collections
(spec §2 *Observation validity*). `occupancy` is the explicit field behind the "visibly `empty`"
facing status — absence of evidence must stay `"unknown"`. `image_id` and `source` are optional
in the LLM-facing item precisely because the pipeline, not the model, owns them.

### `…/planogram/contracts.py` (CREATE) — block 3/3: comparison, policies, context
```python
class FacingStatus(str, Enum):
    """Decision for one expected facing."""

    MATCH = "match"
    MISPLACED = "misplaced"
    VARIANT_UNRESOLVED = "variant_unresolved"
    MISMATCH = "mismatch"
    EMPTY = "empty"
    INFERRED_PRESENT = "inferred_present"
    OCCUPIED_UNASSIGNED = "occupied_unassigned"
    CONFLICT = "conflict"
    NOT_ASSESSED = "not_assessed"
    NOT_VISIBLE = "not_visible"


class AssessmentStatus(str, Enum):
    """Completeness of an assessment — independent of whether violations exist."""

    COMPLETE = "complete"
    INCONCLUSIVE = "inconclusive"
    LEGACY_UNMEASURED = "legacy_unmeasured"


class ObservationRef(BaseModel):
    """Provenance of one observation that supports a facing decision."""

    image_id: str
    shape_id: str
    source: ObservationSource
    raw_confidence: float = 0.0
    product: Optional[str] = None


class RuleOutcome(BaseModel):
    """Result of one bound non-product rule."""

    rule_id: str
    assessed: bool = False
    passed: Optional[bool] = None
    score: float = 1.0
    penalty: float = 0.0
    detail: Optional[str] = None


class PositionResult(BaseModel):
    """Decision for one expected facing, merged across photos."""

    facing_id: str
    shelf_id: str
    status: FacingStatus = FacingStatus.NOT_ASSESSED
    strict_credit: float = 0.0
    lenient_credit: float = 0.0
    identity: Optional[str] = None
    observations: List[ObservationRef] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class ShelfScore(BaseModel):
    """Per-shelf measures (spec §2 scoring contract)."""

    shelf_id: str
    shelf_level: str
    expected_facings: int = 0
    facing_strict: float = 0.0
    facing_lenient: float = 0.0
    strict_score: float = 0.0                # shelf_compliance(s, strict)
    lenient_score: float = 0.0               # shelf_compliance(s, lenient)
    coverage: float = 0.0
    visible_fraction: float = 0.0
    occupied_fraction: float = 0.0
    rule_results: List[RuleOutcome] = Field(default_factory=list)
```

### `…/planogram/contracts.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
class CreditPolicy(BaseModel):
    """Strict / lenient credit per FacingStatus."""

    strict: Dict[FacingStatus, float]
    lenient: Dict[FacingStatus, float]

    @model_validator(mode="after")
    def _check(self) -> "CreditPolicy":
        """Every status present in both maps, 0<=credit<=1, strict<=lenient."""
        # FILL IN: raise ValueError naming the offending status — bounded by the three rules in the docstring
        return self

    @classmethod
    def default(cls) -> "CreditPolicy":
        """The provisional table of spec §2."""
        # FILL IN: MATCH 1.0/1.0; MISPLACED, VARIANT_UNRESOLVED, INFERRED_PRESENT 0.0/0.5; all others 0.0/0.0
        raise NotImplementedError

    def is_resolved(self, status: FacingStatus) -> bool:
        """True for MATCH, MISPLACED, MISMATCH, EMPTY — the statuses that count for coverage."""
        # FILL IN: membership test on exactly those four statuses
        raise NotImplementedError


class EvidenceWeights(BaseModel):
    """Evidence-quality weight per source. NEVER multiplies compliance credit."""

    cv: float = 1.0
    llm_added: float = 0.5
    llm: float = 0.5
    legacy_llm: float = 0.5

    def weight_for(self, source: ObservationSource) -> float:
        """Weight of one source."""
        return float(getattr(self, source.value))


class ComparisonResult(BaseModel):
    """Stage-3 output."""

    compliance_results: List[ComplianceResult] = Field(default_factory=list)
    position_results: List[PositionResult] = Field(default_factory=list)
    shelf_scores: List[ShelfScore] = Field(default_factory=list)
    overall_compliance_score: float = 0.0
    strict_compliance_score: Optional[float] = None
    overall_compliant: bool = False
    coverage: Optional[float] = None
    definition_coverage: Optional[float] = None
    evidence_quality: Optional[float] = None
    assessment_status: AssessmentStatus = AssessmentStatus.INCONCLUSIVE
    errors: List[str] = Field(default_factory=list)


class RenderRecord(BaseModel):
    """Render of one input image."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    image_id: str
    rendered_image: Optional[Any] = None     # PIL.Image.Image
    overlay_path: Optional[str] = None


class CycleContext(BaseModel):
    """Per-run shared services handed to every hook."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vision: Any = None                       # VisionAdapter
    executor: Any = None                     # CpuExecutor
    ocr: Any = None                          # OcrReader
    definition: Optional[Any] = None         # SlotsDefinition
    bindings: List[Any] = Field(default_factory=list)   # RuleBinding
    credit_policy: CreditPolicy = Field(default_factory=CreditPolicy.default)
    evidence_weights: EvidenceWeights = Field(default_factory=EvidenceWeights)
    output_dir: Optional[Path] = None
    errors: List[str] = Field(default_factory=list)
```
**Why this shape**: `overall_compliant` defaults to `False` and `assessment_status` to
`INCONCLUSIVE` so that a half-built result can never read as a pass (spec G14). Coverage-type
fields are `Optional` because the legacy adapter must report `None`, not a fabricated value.
`CycleContext` service fields are `Any` so this module stays a root of the task graph.

### `packages/ai-parrot/src/parrot/models/compliance.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from typing import List, Optional, Tuple, Iterable, Set$' packages/ai-parrot/src/parrot/models/compliance.py)
# REPLACE the line `from typing import List, Optional, Tuple, Iterable, Set` (verified: compliance.py:1) with:
from typing import Any, Dict, List, Optional, Tuple, Iterable, Set

# occurrences: 1 (verified: grep -c '^class ComplianceResult(BaseModel):$' packages/ai-parrot/src/parrot/models/compliance.py)
# BEFORE — insert ABOVE `class ComplianceResult(BaseModel):` (verified: compliance.py:32), separated by one blank line:
class ShelfAssessment(BaseModel):
    """Additive shelf assessment metadata (FEAT-574). Every field is optional so legacy producers need not set it."""
    assessment_status: Optional[str] = Field(default=None, description="complete | inconclusive | legacy_unmeasured")
    coverage: Optional[float] = Field(default=None, description="Resolved facings / expected facings on this shelf")
    strict_score: Optional[float] = Field(default=None)
    lenient_score: Optional[float] = Field(default=None)
    expected_facings: Optional[int] = Field(default=None)
    resolved_facings: Optional[int] = Field(default=None)
    unresolved_facing_ids: List[str] = Field(default_factory=list)
    rule_results: List[Dict[str, Any]] = Field(default_factory=list)

# occurrences: 1 (verified: grep -c 'overall_text_compliant: bool = Field(default=True)' packages/ai-parrot/src/parrot/models/compliance.py)
# AFTER — insert below `    overall_text_compliant: bool = Field(default=True)` (verified: compliance.py:52):
    assessment: Optional[ShelfAssessment] = Field(
        default=None, description="Additive assessment metadata; None for legacy producers."
    )
```
**Why**: core cannot import from `parrot_pipelines`, so `rule_results` is a list of plain dicts
(`RuleOutcome.model_dump()`), and `assessment_status` is a string. The field is optional and
last, so every existing constructor call and every serialised consumer keeps working.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py` (CREATE)
```python
"""Tests for the FEAT-574 cycle contracts."""
import pytest
from parrot.models.compliance import ComplianceResult, ComplianceStatus, ShelfAssessment
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, ComparisonResult, CreditPolicy, CycleContext, EvidenceWeights,
    FacingStatus, Identification, IdentificationResponse, ObservationSource, PerceptionResult,
)


def test_credit_policy_defaults_and_validation() -> None:
    """Spec §2 credit table; strict > lenient is rejected."""
    # FILL IN: assert every row of the table; pytest.raises(ValueError) for strict > lenient, credit > 1, missing status


def test_is_resolved_is_exactly_four_statuses() -> None:
    # FILL IN: MATCH, MISPLACED, MISMATCH, EMPTY → True; the six others → False


def test_compliance_result_assessment_is_optional() -> None:
    """Legacy construction without `assessment` still validates; with it, round-trips."""
    # FILL IN: build ComplianceResult with only the pre-existing required fields; then with ShelfAssessment(...)


def test_safe_defaults_never_read_as_pass() -> None:
    # FILL IN: ComparisonResult() → overall_compliant False, INCONCLUSIVE, coverage None


def test_enum_values_are_public_strings() -> None:
    # FILL IN: ObservationSource.LLM_ADDED.value == "llm_added", AssessmentStatus.LEGACY_UNMEASURED.value == "legacy_unmeasured", …


def test_identification_defaults_and_bounds() -> None:
    # FILL IN: occupancy "unknown", source CV, raw_confidence outside [0,1] rejected; IdentificationResponse() has two empty lists


def test_cycle_context_builds_with_defaults() -> None:
    # FILL IN: CycleContext() works; credit_policy is CreditPolicy.default(); EvidenceWeights().weight_for(LLM_ADDED) == 0.5
```
**Why**: each test locks one promise other tasks rely on (credit table, safe defaults, public
enum strings, additive core field).

### FILL IN checklist
- [ ] `contracts.py::CreditPolicy._check` — validation; bounded by: all statuses in both maps, `0<=credit<=1`, `strict<=lenient`
- [ ] `contracts.py::CreditPolicy.default` — bounded by the spec §2 credit table (values in the stub comment)
- [ ] `contracts.py::CreditPolicy.is_resolved` — bounded by: exactly MATCH, MISPLACED, MISMATCH, EMPTY
- [ ] `test_contracts.py` — seven test bodies; bounded by the assertions named in each stub

---

## Acceptance Criteria

- [ ] Every class and field of the blueprint exists with the given name, type and default
- [ ] `contracts.py` imports nothing from `parrot_pipelines` other than itself
- [ ] `ComplianceStatus` and every pre-existing `ComplianceResult` field are unchanged; `ComplianceResult(...)` without `assessment` validates
- [ ] `CreditPolicy.default()` equals the spec §2 table; invalid policies raise `ValueError`
- [ ] `ComparisonResult()` defaults: `overall_compliant=False`, `assessment_status=INCONCLUSIVE`, coverage fields `None`
- [ ] Tests pass; `ruff check` clean on both source files
- [ ] Imports work: `from parrot_pipelines.planogram.contracts import CycleContext, PerceptionResult`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py -q`

---

## Test Specification

See the `test_contracts.py` blueprint block above — the seven functions are the required
minimum. Add cases freely; never weaken one.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Data Models, §3 Module 2)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code, confirm the three `compliance.py` anchors still match (`grep -c`); if anything has changed, update the contract FIRST
4. **Update status** in `sdd/tasks/index/new-planogram-pipeline.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, and never change a name, default or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3421-cycle-contracts.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented by native sonnet coder: planogram/contracts.py (all cycle contracts, CreditPolicy validation/default, is_resolved), additive ShelfAssessment + optional ComplianceResult.assessment in parrot/models/compliance.py, tests/planogram_cycle/test_contracts.py (7 passed).

Review fix: coder added an unlisted tests/planogram_cycle/__init__.py (fidelity_violation); removed in aaf0a845e (not needed — collection works without it). Model feedback recorded: coder-feedback:e0daa670b250251730937ce3 (pattern unlisted-file-added); review: coder-review:2a878068f57cf17a4a4a1e42.
Merge-tier tests: all green except 2 failures pre-existing on origin/dev (test_dataset_models::test_neither_query_nor_slug_fails_validation, test_endcap_no_shelves_promotional::test_status_not_missing_when_found). Note: select_tests must run with PYTHONPATH pointing at the worktree's packages/*/src, else it imports the main checkout.
Engine lint commit 4186b7167 (black); residual B905/B007 in pre-existing TextMatcher code left for /sdd-done.

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: 256s · Tokens: 78.8k (total)
