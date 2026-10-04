"""Typed manual/procedure models — the data plane of FEAT-601 (spec §2, §3 M2)."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parrot.knowledge.bookstore.models import TocEntry
from parrot.knowledge.common.provenance import (
    MAX_QUOTE_CHARS,
    AnswerProvenance,
    Evidence,
    Extracted,
    FieldProvenance,
    VerificationState,
)

ProcedureKind = Literal["assembly", "disassembly", "maintenance", "inspection", "troubleshooting"]
MediaKind = Literal["figure", "photo", "video_segment"]
MediaRole = Literal["primary", "secondary", "overview"]
HazardSeverity = Literal["caution", "warning", "danger"]
TipOrigin = Literal["manual", "technician", "memory"]
SourceFormat = Literal["pdf", "docx", "md", "txt"]
CardOrigin = Literal["llm", "fallback", "manual"]
ProcedureAnswerKind = Literal[
    "procedure", "step", "prerequisites", "lookup", "clarification", "not_found", "out_of_scope", "denied", "incomplete"
]
Applies = Literal["yes", "no", "unknown"]

_ARANGO_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_\-:.@()+,=;$!*'%]")
_SERIAL_TOKEN = re.compile(r"\d+|[A-Za-z]+|[^A-Za-z\d]+")
_MANUAL_ID = re.compile(r"^[a-z0-9][a-z0-9\-_.]*$")


def _normalized_text(value: str) -> str:
    """Return case-insensitive, whitespace-normalized canonical text."""
    return " ".join(value.split()).casefold()


def mint_step_id(manual_id: str, procedure_slug: str) -> str:
    """Return a minted, Arango-safe step id independent of display order."""
    safe_manual_id = _ARANGO_KEY_UNSAFE.sub("-", manual_id)
    safe_procedure_slug = _ARANGO_KEY_UNSAFE.sub("-", procedure_slug)
    return f"{safe_manual_id}:{safe_procedure_slug}:{uuid.uuid4().hex[:12]}"


def content_hash(
    text: str,
    *,
    torque: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    applies_to: Sequence[str] = (),
) -> str:
    """Return an equality-only hash for normalized step content and qualifiers."""
    canonical = "\x1f".join(
        [
            _normalized_text(text),
            _normalized_text(torque) if torque is not None else "",
            str(duration_minutes) if duration_minutes is not None else "",
            *sorted(_normalized_text(value) for value in applies_to),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class StepIdentity(BaseModel):
    """Immutable identity of a step, independent of display order (R1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(..., min_length=1)
    source_identity: Optional[str] = None
    content_hash: str = Field(..., min_length=64, max_length=64)


class PartRef(BaseModel):
    """One part referenced by a procedure step."""

    model_config = ConfigDict(extra="forbid")

    part_id: str
    part_number: Optional[str] = None
    name: Extracted[str]
    quantity: Optional[int] = Field(default=None, ge=1)
    resolved: bool = False


class ToolRef(BaseModel):
    """One tool referenced by a procedure step."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str
    name: Extracted[str]
    spec: Optional[str] = None


class Hazard(BaseModel):
    """One safety hazard associated with a procedure step."""

    model_config = ConfigDict(extra="forbid")

    hazard_id: str
    severity: HazardSeverity
    text: Extracted[str]
    applies_to: list[str] = Field(default_factory=list)


class Callout(BaseModel):
    """One numbered callout read off an exploded view (vision structured output, Q8)."""

    label: str
    description: str = ""
    part_number: Optional[str] = None
    bbox: Optional[tuple[float, float, float, float]] = None


class CalloutMap(BaseModel):
    """Vision structured-output callouts for one exploded view."""

    callouts: list[Callout] = Field(default_factory=list)


class CalloutLink(BaseModel):
    """Link a media callout to a canonical part."""

    model_config = ConfigDict(extra="forbid")

    media_id: str
    part_id: str
    callout: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    origin: Literal["vision"] = "vision"


class MediaRef(BaseModel):
    """A figure, photo or video segment — a reference, never a stored URL (G4)."""

    model_config = ConfigDict(extra="forbid")

    media_id: str
    kind: MediaKind
    storage_key: Optional[str] = None
    uri: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None
    label: Optional[str] = None
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    origin: TipOrigin = "manual"
    callouts: list[CalloutLink] = Field(default_factory=list)
    unresolved_callouts: list[Callout] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_kind(self) -> "MediaRef":
        if self.kind in {"figure", "photo"} and not self.storage_key:
            raise ValueError("figure and photo media require storage_key")
        if self.kind == "video_segment":
            if not self.uri:
                raise ValueError("video_segment media require uri")
            if self.t_start is None or self.t_end is None or self.t_start >= self.t_end:
                raise ValueError("video_segment media require t_start < t_end")
        if self.storage_key and self.storage_key.lower().startswith(("http://", "https://", "file://")):
            raise ValueError("storage_key must not be a URL")
        return self


class MediaLink(BaseModel):
    """Attach media to a step with its presentation role."""

    model_config = ConfigDict(extra="forbid")

    media_id: str
    role: MediaRole
    confidence: float = Field(..., ge=0.0, le=1.0)
    origin: Literal["manual", "llm"] = "manual"


class SerialRange(BaseModel):
    """One vendor-preserved serial interval."""

    model_config = ConfigDict(extra="forbid")

    start: Optional[str] = None
    end: Optional[str] = None
    format: str = Field(..., min_length=1)


class Applicability(BaseModel):
    """Model qualifiers plus evidence-backed serial ranges; empty applies globally."""

    model_config = ConfigDict(extra="forbid")

    models: list[str] = Field(default_factory=list)
    serial_ranges: list[SerialRange] = Field(default_factory=list)
    evidence: Optional[Evidence] = None

    @model_validator(mode="after")
    def _serials_need_evidence(self) -> "Applicability":
        if self.serial_ranges and not (self.evidence and self.evidence.substantiates):
            raise ValueError("serial ranges require substantiating evidence")
        return self


def _serial_shape(value: str) -> list[tuple[str, str]]:
    """Tokenize a serial into digit, letter, and literal separator groups."""
    tokens = _SERIAL_TOKEN.findall(value)
    if not tokens or "".join(tokens) != value:
        raise ValueError("serial must not be empty")
    return [("digit" if token.isdigit() else "letter" if token.isalpha() else "separator", token) for token in tokens]


def normalize_serial(value: str, *, format: str) -> tuple[int, ...]:
    """Return a comparison key after enforcing the vendor format's shape."""
    value_tokens = _serial_shape(value)
    format_tokens = _serial_shape(format)
    if len(value_tokens) != len(format_tokens):
        raise ValueError("serial does not match vendor format")
    for (value_kind, value_token), (format_kind, format_token) in zip(value_tokens, format_tokens, strict=True):
        if value_kind != format_kind or (value_kind == "separator" and value_token != format_token):
            raise ValueError("serial does not match vendor format")
    return tuple(int(token) for kind, token in value_tokens if kind == "digit")


def applies(step: "Step", *, model: Optional[str], serial: Optional[str]) -> Applies:
    """Return the deterministic applicability decision for an equipment context."""
    applicability = step.applicability
    if applicability.models and model not in applicability.models:
        return "no"
    if not applicability.serial_ranges:
        return "yes"
    if serial is None:
        return "unknown"

    undecidable = False
    for serial_range in applicability.serial_ranges:
        try:
            value = normalize_serial(serial, format=serial_range.format)
            start = normalize_serial(serial_range.start, format=serial_range.format) if serial_range.start else None
            end = normalize_serial(serial_range.end, format=serial_range.format) if serial_range.end else None
        except ValueError:
            undecidable = True
            continue
        if (start is None or value >= start) and (end is None or value <= end):
            return "yes"
    return "unknown" if undecidable else "no"


class Step(BaseModel):
    """One evidenced, immutably identified procedure step."""

    model_config = ConfigDict(extra="forbid")

    identity: StepIdentity
    order: int = Field(..., ge=1)
    text: Extracted[str]
    torque: Optional[Extracted[str]] = None
    duration_minutes: Optional[Extracted[int]] = None
    applicability: Applicability = Field(default_factory=Applicability)
    figure_refs: list[str] = Field(default_factory=list)
    parts: list[PartRef] = Field(default_factory=list)
    tools: list[ToolRef] = Field(default_factory=list)
    hazards: list[Hazard] = Field(default_factory=list)
    media: list[MediaLink] = Field(default_factory=list)
    cross_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _text_needs_evidence(self) -> "Step":
        if not (self.text.evidence and self.text.evidence.substantiates):
            raise ValueError("step text requires substantiating evidence")
        return self


class ManualVersion(BaseModel):
    """One bitemporal manual-card revision."""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(..., ge=1)
    revision: str = Field(..., min_length=1)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    source_sha256: str = ""
    card_snapshot: dict[str, Any] = Field(default_factory=dict)
    recorded_at: Optional[datetime] = None
    evidence_ref: Optional[str] = None

    @field_validator("card_snapshot")
    @classmethod
    def _no_recursive_snapshot(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("versions"):
            raise ValueError("card_snapshot must omit its own 'versions' list (use manual_snapshot_payload())")
        return value

    @model_validator(mode="after")
    def _check_interval(self) -> "ManualVersion":
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be exclusive and after valid_from")
        return self

    def in_force(self, as_of: date) -> bool:
        """Return whether the revision is in force at ``as_of``."""
        if self.valid_from is None or as_of < self.valid_from:
            return False
        return self.valid_to is None or as_of < self.valid_to


class Procedure(BaseModel):
    """One procedure embedded in a manual card."""

    model_config = ConfigDict(extra="forbid")

    procedure_id: str
    slug: str
    kind: ProcedureKind
    title: Extracted[str]
    steps: list[Step] = Field(default_factory=list)
    estimated_minutes: Optional[int] = None
    skill_level: Optional[str] = None
    active: bool = True
    verification: VerificationState = "extracted"
    versions: list[ManualVersion] = Field(default_factory=list)
    supersedes: Optional[str] = None


class EquipmentRef(BaseModel):
    """Equipment described by a manual card."""

    model_config = ConfigDict(extra="forbid")

    equipment_id: str
    model: str
    family: Optional[str] = None
    revision: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class Tip(BaseModel):
    """A technician or manual tip tied to a source revision."""

    model_config = ConfigDict(extra="forbid")

    tip_id: str
    text: str = Field(..., min_length=1)
    origin: TipOrigin = "technician"
    author_employee_id: Optional[str] = None
    created_at: datetime
    active: bool = True
    orphaned: bool = False
    source_revision: str
    attached_step_id: Optional[str] = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class ManualCard(BaseModel):
    """The durable card for exactly one PageIndex manual document."""

    model_config = ConfigDict(extra="forbid")

    manual_id: str
    equipment: list[EquipmentRef] = Field(default_factory=list)
    revision: str
    source_uri: Optional[str] = None
    source_sha256: str = ""
    source_format: SourceFormat = "pdf"
    toc: list[TocEntry] = Field(default_factory=list)
    toc_digest: str = ""
    page_count: int = Field(default=0, ge=0)
    procedures: list[Procedure] = Field(default_factory=list)
    global_parts: list[PartRef] = Field(default_factory=list)
    global_tools: list[ToolRef] = Field(default_factory=list)
    global_hazards: list[Hazard] = Field(default_factory=list)
    figures: list[MediaRef] = Field(default_factory=list)
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    verification: VerificationState = "extracted"
    versions: list[ManualVersion] = Field(default_factory=list)
    card_origin: CardOrigin = "llm"

    @model_validator(mode="after")
    def _check_identity(self) -> "ManualCard":
        if not _MANUAL_ID.fullmatch(self.manual_id):
            raise ValueError("manual_id must be a PageIndex tree-name slug")
        slugs = [procedure.slug for procedure in self.procedures]
        if len(slugs) != len(set(slugs)):
            raise ValueError("procedure slugs must be unique on a manual card")
        return self


def manual_snapshot_payload(card: ManualCard) -> dict[str, Any]:
    """Return a JSON-mode card payload without its recursive versions list."""
    payload = card.model_dump(mode="json")
    payload.pop("versions", None)
    return payload


class ProcedureCitation(BaseModel):
    """One released evidence pointer pinned to an immutable manual version (mirrors contracts Citation :701-737)."""

    model_config = ConfigDict(extra="forbid")
    manual_id: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    quote: str = Field(..., min_length=1, max_length=MAX_QUOTE_CHARS)
    page: Optional[int] = Field(default=None, ge=1)
    verification: VerificationState = "extracted"
    version_n: int = Field(default=1, ge=1)
    source_sha256: str = ""

    @field_validator("quote")
    @classmethod
    def _nonblank_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a citation quote cannot be blank")
        return value

    @property
    def key(self) -> tuple[str, str]:
        """The ``(manual_id, node_id)`` pair."""
        return (self.manual_id, self.node_id)


def derive_provenance(citations: Sequence[ProcedureCitation]) -> AnswerProvenance:
    """Same rule as contracts/models.py:800-818."""
    if not citations:
        return "extracted"
    verifications = {citation.verification for citation in citations}
    if verifications == {"verified"}:
        return "verified"
    if "verified" in verifications:
        return "mixed"
    return "extracted"


class ProcedureRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_id: str
    manual_id: str
    slug: str
    title: str
    equipment_id: Optional[str] = None


class ProcedureView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_id: str
    manual_id: str
    title: str
    kind: ProcedureKind
    estimated_minutes: Optional[int] = None
    skill_level: Optional[str] = None
    verification: VerificationState = "extracted"


class StepView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    order: int = Field(..., ge=1)
    text: str = Field(..., min_length=1)
    torque: Optional[str] = None
    duration_minutes: Optional[int] = None
    applicability: Literal["yes", "unknown"] = "yes"
    applicability_note: Optional[str] = None
    part_ids: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    hazard_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_applicability_note(self) -> "StepView":
        if self.applicability == "unknown" and not (self.applicability_note or "").strip():
            raise ValueError("applicability_note is required when applicability is 'unknown'")
        return self


class HazardView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hazard_id: str
    severity: HazardSeverity
    text: str
    step_ids: list[str] = Field(default_factory=list)


class MediaView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_id: str
    kind: MediaKind
    role: MediaRole
    step_id: Optional[str] = None
    caption: Optional[str] = None
    label: Optional[str] = None
    page: Optional[int] = None
    t_start: Optional[float] = None
    t_end: Optional[float] = None


class TipView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tip_id: str
    step_id: str
    text: str
    author_employee_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Prerequisites(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[PartRef] = Field(default_factory=list)
    tools: list[ToolRef] = Field(default_factory=list)
    hazards: list[HazardView] = Field(default_factory=list)


class ProcedureAnswer(BaseModel):
    """The single channel-agnostic answer shape (spec §2). ``answer`` is the only model-authored field."""

    model_config = ConfigDict(extra="forbid")
    answer_kind: ProcedureAnswerKind
    answer: str = ""
    procedure: Optional[ProcedureView] = None
    steps: list[StepView] = Field(default_factory=list)
    prerequisites: Optional[Prerequisites] = None
    hazards: list[HazardView] = Field(default_factory=list)
    media: list[MediaView] = Field(default_factory=list)
    tips: list[TipView] = Field(default_factory=list)
    citations: list[ProcedureCitation] = Field(default_factory=list)
    provenance: AnswerProvenance = "extracted"
    pattern: Optional[str] = None
    reason: Optional[str] = None
    manual_revision: Optional[str] = None

    @model_validator(mode="after")
    def _check_kind_invariants(self) -> "ProcedureAnswer":
        kind = self.answer_kind
        if kind == "procedure":
            if self.reason:
                raise ValueError("a 'procedure' answer must not carry a 'reason'")
            if not self.procedure:
                raise ValueError("a 'procedure' answer must carry a procedure view")
            if not self.steps:
                raise ValueError("a 'procedure' answer must carry at least one step")
            orders = [step.order for step in self.steps]
            if orders != sorted(orders) or len(set(orders)) != len(orders):
                raise ValueError("a 'procedure' answer's steps must have strictly increasing, unique orders")
            step_ids = [step.step_id for step in self.steps]
            if len(step_ids) != len(set(step_ids)):
                raise ValueError("a 'procedure' answer's steps must have unique step_id values")
            if not self.citations:
                raise ValueError("a 'procedure' answer must carry at least one citation")
        elif kind == "step":
            if len(self.steps) != 1:
                raise ValueError("a 'step' answer must carry exactly one step")
            if not self.citations:
                raise ValueError("a 'step' answer must carry at least one citation")
        elif kind == "prerequisites":
            if not self.prerequisites:
                raise ValueError("a 'prerequisites' answer must carry prerequisites")
            if not self.citations:
                raise ValueError("a 'prerequisites' answer must carry at least one citation")
        elif kind == "lookup":
            if not self.answer.strip():
                raise ValueError("a 'lookup' answer must carry non-blank answer text")
            if not self.citations:
                raise ValueError("a 'lookup' answer must carry at least one citation")
            if self.steps:
                raise ValueError("a 'lookup' answer must not carry steps")
            if self.procedure:
                raise ValueError("a 'lookup' answer must not carry a procedure")
        elif kind == "incomplete":
            if not (self.reason or "").strip():
                raise ValueError("an 'incomplete' answer must carry a non-blank reason")
            if self.steps:
                raise ValueError("an 'incomplete' answer must not carry steps")
            if self.media:
                raise ValueError("an 'incomplete' answer must not carry media")
            if self.tips:
                raise ValueError("an 'incomplete' answer must not carry tips")
        elif kind in ("clarification", "not_found", "out_of_scope"):
            if self.steps:
                raise ValueError(f"a '{kind}' answer must not carry steps")
            if self.media:
                raise ValueError(f"a '{kind}' answer must not carry media")
            if self.tips:
                raise ValueError(f"a '{kind}' answer must not carry tips")
            if self.citations:
                raise ValueError(f"a '{kind}' answer must not carry citations")
        elif kind == "denied":
            if self.answer.strip():
                raise ValueError("a 'denied' answer must not carry answer text")
            if self.steps:
                raise ValueError("a 'denied' answer must not carry steps")
            if self.media:
                raise ValueError("a 'denied' answer must not carry media")
            if self.tips:
                raise ValueError("a 'denied' answer must not carry tips")
            if self.citations:
                raise ValueError("a 'denied' answer must not carry citations")
            if self.procedure:
                raise ValueError("a 'denied' answer must not carry a procedure")
            if self.prerequisites:
                raise ValueError("a 'denied' answer must not carry prerequisites")
        self.provenance = derive_provenance(self.citations)
        return self
