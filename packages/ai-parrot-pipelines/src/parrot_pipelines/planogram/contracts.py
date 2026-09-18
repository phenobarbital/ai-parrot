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


class CreditPolicy(BaseModel):
    """Strict / lenient credit per FacingStatus."""

    strict: Dict[FacingStatus, float]
    lenient: Dict[FacingStatus, float]

    @model_validator(mode="after")
    def _check(self) -> "CreditPolicy":
        """Every status present in both maps, 0<=credit<=1, strict<=lenient."""
        for status in FacingStatus:
            if status not in self.strict:
                raise ValueError(f"CreditPolicy.strict is missing {status!r}")
            if status not in self.lenient:
                raise ValueError(f"CreditPolicy.lenient is missing {status!r}")
        for status, credit in self.strict.items():
            if not 0.0 <= credit <= 1.0:
                raise ValueError(f"CreditPolicy.strict[{status!r}] must be in [0, 1], got {credit!r}")
        for status, credit in self.lenient.items():
            if not 0.0 <= credit <= 1.0:
                raise ValueError(f"CreditPolicy.lenient[{status!r}] must be in [0, 1], got {credit!r}")
        for status in FacingStatus:
            if self.strict[status] > self.lenient[status]:
                raise ValueError(
                    f"CreditPolicy.strict[{status!r}] ({self.strict[status]!r}) "
                    f"must be <= lenient[{status!r}] ({self.lenient[status]!r})"
                )
        return self

    @classmethod
    def default(cls) -> "CreditPolicy":
        """The provisional table of spec §2."""
        lenient_boosted = {
            FacingStatus.MISPLACED,
            FacingStatus.VARIANT_UNRESOLVED,
            FacingStatus.INFERRED_PRESENT,
        }
        strict: Dict[FacingStatus, float] = {}
        lenient: Dict[FacingStatus, float] = {}
        for status in FacingStatus:
            if status is FacingStatus.MATCH:
                strict[status] = 1.0
                lenient[status] = 1.0
            elif status in lenient_boosted:
                strict[status] = 0.0
                lenient[status] = 0.5
            else:
                strict[status] = 0.0
                lenient[status] = 0.0
        return cls(strict=strict, lenient=lenient)

    def is_resolved(self, status: FacingStatus) -> bool:
        """True for MATCH, MISPLACED, MISMATCH, EMPTY — the statuses that count for coverage."""
        return status in {
            FacingStatus.MATCH,
            FacingStatus.MISPLACED,
            FacingStatus.MISMATCH,
            FacingStatus.EMPTY,
        }


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
