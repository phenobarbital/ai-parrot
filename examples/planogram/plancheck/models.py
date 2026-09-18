"""Shared Pydantic v2 models for the planogram compliance check (FEAT-565)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Box = tuple[int, int, int, int]  # x1, y1, x2, y2 — ORIGINAL image pixels
SlotOrigin = Literal["tag_anchored", "gap_filled", "untagged_row"]
OccupancyState = Literal["occupied", "empty", "uncertain"]
Visibility = Literal["full", "partial", "unusable"]
Resolution = Literal["direct", "verified_by_expectation", "inferred", "ambiguous", "unresolved"]
Grade = Literal["high", "medium", "low"]
PriceStatus = Literal["read", "partial", "unreadable", "not_assessed", "conflict"]
PositionStatus = Literal[
    "match",
    "misplaced",
    "variant_unresolved",
    "mismatch",
    "empty",
    "inferred_present",
    "occupied_unassigned",
    "conflict",
    "not_assessed",
    "not_visible",
]


class StrictModel(BaseModel):
    """Base model: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class PlanogramFacing(StrictModel):
    """One expected physical facing. ``facing_id`` is ``f"p{position:03d}_f{facing}"``."""

    facing_id: str
    position: int
    shelf: int
    segment: str
    slot: int  # physical left→right axis of the shelf (NOT ``position``)
    segment_slot: int
    facing: int
    sku: str
    brand: str | None
    identity_required: bool
    source_confidence: str = "unknown"
    reference_read_method: str = "unknown"  # direct | inferred | partial
    notes: str | None = None


class PlanogramRef(StrictModel):
    """The reference planogram as an ordered list of facings."""

    planogram_id: str
    source: str
    shelf_count: int
    facings: list[PlanogramFacing]

    def shelf(self, number: int) -> list[PlanogramFacing]:
        """Return the facings of one shelf ordered by ``(slot, facing)``."""
        return sorted((f for f in self.facings if f.shelf == number), key=lambda f: (f.slot, f.facing))


class CatalogItem(StrictModel):
    """What one planogram SKU's package shows — built from the descriptor fields of its planogram position."""

    sku: str
    brand: str
    display_name: str
    family: str | None = None
    xl: bool = False
    colors: list[str] = Field(default_factory=list)
    pack: int = 1
    identifiers: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    provenance: str | None = None


class Catalog(StrictModel):
    """Every described planogram SKU (derived from the planogram, never a separate file)."""

    items: list[CatalogItem]

    def by_sku(self, sku: str) -> CatalogItem | None:
        """Return the item with this SKU, or ``None``."""
        return next((item for item in self.items if item.sku == sku), None)


class Tag(StrictModel):
    """A detected price tag. ``tag_id`` is ``f"{image_id}_r{row:02d}_p{position:02d}"``."""

    tag_id: str
    image_id: str
    row: int
    position: int
    box: Box
    crop_box: Box
    rectangularity: float


class TagRow(StrictModel):
    """One visible tag row; the fitted line is in ORIGINAL pixels (y = slope * x + intercept)."""

    image_id: str
    row: int
    slope: float
    intercept: float
    tags: list[Tag]
    synthesized: bool = False


class Slot(StrictModel):
    """A product area. ``slot_id`` is ``f"{image_id}_r{row:02d}_s{index:02d}"``."""

    slot_id: str
    image_id: str
    row: int
    index: int
    box: Box
    tag_id: str | None = None
    tag_box: Box | None = None
    origin: SlotOrigin


class PriceReading(StrictModel):
    """A price read from a tag. ``amount`` is only set when dollars AND cents were read."""

    raw: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    source: Literal["ocr", "llm", "none"] = "none"
    status: PriceStatus = "not_assessed"


class SlotReading(StrictModel):
    """Pass-1 LLM contract: what the model sees in one slot."""

    slot_id: str
    occupancy: OccupancyState
    visibility: Visibility
    brand: str | None = None
    family: str | None = None
    xl: bool | None = None
    colors: list[str] = Field(default_factory=list, max_length=8)
    pack: int | None = None
    visible_text: list[str] = Field(default_factory=list, max_length=20)
    evidence: str = Field(default="", max_length=400)


class RowReading(StrictModel):
    """Pass-1 response for one row strip."""

    slots: list[SlotReading]


class VerificationReading(StrictModel):
    """Pass-2 LLM contract. ``choice`` is an offered SKU, ``"other"`` or ``"cannot_tell"``."""

    slot_id: str
    choice: str
    evidence: str = Field(default="", max_length=400)


class RowVerification(StrictModel):
    """Pass-2 response for one row strip."""

    slots: list[VerificationReading]


class TagPriceReading(StrictModel):
    """Price-fallback LLM contract: one numbered contact-sheet cell (1-based)."""

    cell: int
    price_text: str | None


class RowPriceReading(StrictModel):
    """Price-fallback response for one row."""

    tags: list[TagPriceReading]


# --- part 2 (TASK-3338): fusion, result and config models ---


class SlotObservation(StrictModel):
    """Everything known about one slot of one photo after perception, resolution and registration."""

    slot: Slot
    reading: SlotReading | None = None
    resolved_sku: str | None = None
    candidate_skus: list[str] = Field(default_factory=list)
    resolution: Resolution = "unresolved"
    price: PriceReading = Field(default_factory=PriceReading)
    facing_id: str | None = None  # None = unregistered
    registration_grade: Grade | None = None
    issues: list[str] = Field(default_factory=list)


class RowRegistration(StrictModel):
    """Alignment of one visible row to one planogram shelf."""

    image_id: str
    row: int
    shelf: int | None
    score: float
    anchors: int
    grade: Grade
    assignments: dict[str, str]  # slot_id -> facing_id


class ImageRegistration(StrictModel):
    """Best row→shelf assignment of one photo, with the runner-up for auditability."""

    image_id: str
    rows: list[RowRegistration]
    total_score: float
    runner_up_shelves: list[int | None] | None = None
    margin: float | None = None


class ScoringWeights(StrictModel):
    """Lenient-score partial credits (spec §8 Q2)."""

    misplaced: float = 0.5
    variant_unresolved: float = 0.5
    inferred_present: float = 0.5
    verified_by_expectation: float = 1.0


class PositionResult(StrictModel):
    """Merged verdict for one expected facing."""

    facing: PlanogramFacing
    status: PositionStatus
    resolution: Resolution | None = None
    strict_credit: float
    lenient_credit: float
    observed_sku: str | None = None
    observed_brand: str | None = None
    price: PriceReading | None = None
    price_expected: Decimal | None = None
    price_match: bool | None = None
    slot_ids: list[str] = Field(default_factory=list)


class ShelfScore(StrictModel):
    """Per-shelf metrics. ``*_pct`` are percentages 0–100 (2 dp); ``None`` when the denominator is 0."""

    shelf: int
    expected: int
    covered: int
    decided: int
    strict_pct: float | None
    lenient_pct: float | None
    occupancy_pct: float | None
    empty_facing_ids: list[str]


class BrandShare(StrictModel):
    """Expected vs observed share of one brand (facings and linear)."""

    brand: str
    expected_facings: int
    expected_share: float
    observed_facings: int
    observed_share: float | None
    linear_share: float | None
    occupancy_pct: float | None


class PriceCompliance(StrictModel):
    """Only present when an expected price exists (planogram ``price`` fields and/or ``--prices``)."""

    compared: int
    matched: int
    match_pct: float | None
    mismatches: list[str]
    skus_missing_from_prices: list[str]
    unknown_price_skus: list[str]


class ComplianceSummary(StrictModel):
    """Headline numbers; the ``*_direct_reference`` fields restrict to facings read ``direct`` in the planogram."""

    strict_pct: float | None
    lenient_pct: float | None
    coverage: float
    occupancy_pct: float | None
    products_expected: int
    products_present: int
    unexpected_skus: list[str]
    price: PriceCompliance | None = None
    reference_direct_facings: int
    strict_pct_direct_reference: float | None
    lenient_pct_direct_reference: float | None


class ImageInfo(StrictModel):
    """One input photo and what was found in it."""

    image_id: str
    path: str
    sha256: str
    width: int
    height: int
    tag_rows: int
    tags: int
    slots: int
    registration: ImageRegistration | None = None


class RunInfo(StrictModel):
    """Run metadata."""

    visit_id: str
    planogram_id: str
    llm: str
    ocr_llm: str
    verify_pass: bool
    started_at: str
    finished_at: str
    errors: list[str]
    undescribed_skus: list[str]
    registration_method: Literal["auto_alignment"] = "auto_alignment"
    reference_provisional: bool = True
    local_ocr_available: bool = True


class ComplianceReport(StrictModel):
    """The ``compliance.json`` document."""

    run: RunInfo
    images: list[ImageInfo]
    slots: list[SlotObservation]
    positions: list[PositionResult]
    shelves: list[ShelfScore]
    brands: list[BrandShare]
    compliance: ComplianceSummary
    notes: list[str]


class Settings(StrictModel):
    """Resolved run settings (all paths absolute by the time this is built)."""

    images: list[str]
    planogram: str
    output: str
    cache_dir: str
    prices: str | None = None
    llm: str = "google:gemini-3.8-flash"
    ocr_llm: str | None = None
    base_url: str | None = None
    roi: tuple[float, float, float, float] | None = None
    verify_pass: bool | None = None  # None = auto: True for cloud backends, False when the backend is local
    marks: bool = True
    concurrency: int = Field(default=4, ge=1, le=16)
    visit_id: str = "visit"
    work_width: int = Field(default=2048, ge=256)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
