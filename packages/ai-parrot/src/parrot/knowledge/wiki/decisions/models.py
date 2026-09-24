"""Typed contracts for the ADR decision plane (FEAT-578 Module 1).

Every model is Pydantic v2 with ``extra="forbid"`` and JSON-safe field
types, so a record round-trips through the canonical JSON envelope in
``decisions/codec.py`` without custom encoders.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Fixed diagnostic/error vocabulary (spec §2 "Errors and transport"). These
#: strings are a public contract: CLI JSON, MCP errors and tests all match on
#: them, so never re-spell one.
ADR_SCHEMA_UNSUPPORTED = "ADR_SCHEMA_UNSUPPORTED"
ADR_REVISION_CONFLICT = "ADR_REVISION_CONFLICT"
ADR_WRITE_UNSUPPORTED = "ADR_WRITE_UNSUPPORTED"
ADR_MANAGED_PAGE = "ADR_MANAGED_PAGE"
ADR_RECORD_TOO_LARGE = "ADR_RECORD_TOO_LARGE"
ADR_STATUS_CONFLICT = "ADR_STATUS_CONFLICT"
ADR_SUPERSESSION_CYCLE = "ADR_SUPERSESSION_CYCLE"
ADR_INVENTORY_LIMIT = "ADR_INVENTORY_LIMIT"
ADR_GENERATION_LIMIT = "ADR_GENERATION_LIMIT"
ADR_EVIDENCE_CHANGED = "ADR_EVIDENCE_CHANGED"
ADR_MODEL_FAILED = "ADR_MODEL_FAILED"
ADR_MODEL_TIMEOUT = "ADR_MODEL_TIMEOUT"
ADR_MODEL_UNCONFIGURED = "ADR_MODEL_UNCONFIGURED"
ADR_INVALID_ARGUMENT = "ADR_INVALID_ARGUMENT"
ADR_PARSE_FAILED = "ADR_PARSE_FAILED"
ADR_REFERENCE_MISSING = "ADR_REFERENCE_MISSING"
ADR_REFERENCE_AMBIGUOUS = "ADR_REFERENCE_AMBIGUOUS"
ADR_SOURCE_UNAVAILABLE = "ADR_SOURCE_UNAVAILABLE"
ADR_PATH_OUTSIDE_ROOT = "ADR_PATH_OUTSIDE_ROOT"
ADR_READ_ONLY = "ADR_READ_ONLY"

#: Page category for every managed ADR record.
ADR_CATEGORY = "adr"

#: Maximum serialized page size before ``ADR_RECORD_TOO_LARGE`` (spec §2).
MAX_RECORD_BYTES = 1024 * 1024


class DecisionError(ValueError):
    """A typed ADR failure carrying one of the fixed codes above."""

    def __init__(self, code: str, message: str, decision_id: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.decision_id = decision_id


class _Strict(BaseModel):
    """Shared strict base — forbids unknown fields on every ADR model."""

    model_config = ConfigDict(extra="forbid")


class DecisionConfig(_Strict):
    """Project-level ADR settings; generation is opt-in and off by default."""

    enabled: bool = True
    adr_globs: list[str] = Field(
        default_factory=lambda: ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]
    )
    max_records: int = Field(default=10_000, ge=1, le=100_000)
    generation_enabled: bool = False
    max_input_tokens: int = Field(default=12_000, gt=0)
    max_output_tokens: int = Field(default=2_000, gt=0)
    max_files: int = Field(default=8, gt=0)
    max_candidates: int = Field(default=3, gt=0)
    timeout_seconds: int = Field(default=60, gt=0)


class EvidenceRef(_Strict):
    """One cited source span with the hash of the bytes it was read from."""

    page_id: str = Field(..., min_length=1)
    rel_path: str = Field(..., min_length=1)
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)
    source_sha1: str = Field(..., min_length=1)
    excerpt: str = ""
    kind: Literal["adr", "code", "comment", "document"]

    @field_validator("rel_path")
    @classmethod
    def _validate_rel_path(cls, value: str) -> str:
        """Reject any path that is absolute or escapes the repository root."""
        normalized = value.replace("\\", "/")
        if value.startswith("/") or PurePosixPath(normalized).is_absolute():
            raise ValueError(f"rel_path must be repository-relative, got an absolute path: {value!r}")
        if len(value) >= 2 and value[1] == ":":
            # Windows drive-qualified path (e.g. "C:\\foo") — also absolute.
            raise ValueError(f"rel_path must be repository-relative, got a drive-qualified path: {value!r}")
        if any(part == ".." for part in PurePosixPath(normalized).parts):
            raise ValueError(f"rel_path must stay within the repository root, got: {value!r}")
        return value

    @model_validator(mode="after")
    def _check_line_range(self) -> "EvidenceRef":
        """Reject an inverted or empty line span."""
        if self.end_line < self.start_line:
            raise ValueError(f"end_line ({self.end_line}) must be >= start_line ({self.start_line})")
        return self


class DecisionLink(_Strict):
    """A typed, provenance-tagged association to another page or record."""

    target_id: str = Field(..., min_length=1)
    relation: Literal["explains", "supported_by", "supersedes"]
    provenance: Literal["extracted", "inferred", "asserted"]
    evidence_indexes: list[int] = Field(default_factory=list)


class ReviewEvent(_Strict):
    """One attributed review action, hashed before and after."""

    revision: int = Field(..., ge=1)
    action: Literal["accept", "reject", "revise", "link"]
    actor: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)
    reason: str = ""
    before_sha1: str = ""
    after_sha1: str = ""


class GenerationInfo(_Strict):
    """Provenance of one bounded model invocation that produced a candidate."""

    model_spec: str = Field(..., min_length=1)
    prompt_version: Literal[1] = 1
    scope_id: str = Field(..., min_length=1)
    input_sha1: str = Field(..., min_length=1)
    max_input_tokens: int = Field(..., gt=0)
    max_output_tokens: int = Field(..., gt=0)


class DecisionRecord(_Strict):
    """The single canonical, versioned record persisted per ``adr:`` page."""

    schema_version: Literal[1] = 1
    decision_id: str = Field(..., min_length=1)
    revision: int = Field(default=1, ge=1)
    title: str = ""
    context: str = ""
    decision: str = Field(..., min_length=1)
    consequences: str = ""
    source_status: Literal["unknown", "proposed", "accepted", "rejected", "deprecated", "superseded"] = "unknown"
    source_status_raw: str = ""
    origin: Literal["documented", "inferred"]
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
    source_path: str | None = None
    external_id: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    links: list[DecisionLink] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    review_history: list[ReviewEvent] = Field(default_factory=list)
    generation: GenerationInfo | None = None
    content_fingerprint: str = ""

    @model_validator(mode="after")
    def _check_invariants(self) -> "DecisionRecord":
        """Enforce the provenance invariants review may never violate."""
        if self.origin == "inferred" and self.source_status != "unknown":
            raise ValueError(
                "an origin='inferred' record must keep source_status='unknown'; "
                f"got source_status={self.source_status!r}"
            )
        evidence_len = len(self.evidence)
        for link in self.links:
            for idx in link.evidence_indexes:
                if not (0 <= idx < evidence_len):
                    raise ValueError(
                        f"DecisionLink.evidence_indexes entry {idx} does not address "
                        f"this record's own evidence list (len={evidence_len})"
                    )
        return self


class DecisionDiagnostic(_Strict):
    """A non-fatal condition reported alongside a typed result."""

    code: str = Field(..., min_length=1)
    message: str = ""
    path: str | None = None
    decision_id: str | None = None


class DecisionHit(_Strict):
    """One ranked decision with its labels, score, and citations."""

    decision_id: str = Field(..., min_length=1)
    revision: int = Field(..., ge=1)
    title: str = ""
    origin: Literal["documented", "inferred"]
    source_status: str = "unknown"
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
    freshness: Literal["current", "stale", "missing", "unverified"] = "unverified"
    score: float = 0.0
    decision: str = ""
    applicability: list[DecisionLink] = Field(default_factory=list)
    citations: list[EvidenceRef] = Field(default_factory=list)


class DecisionDossier(_Strict):
    """The retrieval result — documented and candidate groups stay separate."""

    status: Literal["ok", "empty", "ambiguous", "partial", "error"] = "ok"
    documented: list[DecisionHit] = Field(default_factory=list)
    candidates: list[DecisionHit] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)
    truncated: bool = False


class SyncResult(_Strict):
    """Counts and diagnostics from one ADR refresh pass."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    unresolved: int = 0
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)


class GenerationResult(_Strict):
    """Ids written, ids reused for the same evidence, and per-candidate failures."""

    decision_ids: list[str] = Field(default_factory=list)
    reused: list[str] = Field(default_factory=list)
    diagnostics: list[DecisionDiagnostic] = Field(default_factory=list)


class CandidateDraft(_Strict):
    """One model-authored candidate. The model supplies content only."""

    title: str = ""
    context: str = ""
    decision: str = Field(..., min_length=1)
    consequences: str = ""
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    evidence_indexes: list[int] = Field(default_factory=list)


class CandidateBatch(_Strict):
    """The structured-output contract handed to ``AbstractClient.invoke``."""

    candidates: list[CandidateDraft] = Field(default_factory=list)


class CandidateEdit(_Strict):
    """The only fields a maintainer revision may change."""

    title: str | None = None
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    observations: list[str] | None = None
    hypotheses: list[str] | None = None


class ReviewRequest(_Strict):
    """An attributed, revision-checked review action."""

    decision_id: str = Field(..., min_length=1)
    expected_revision: int = Field(..., ge=1)
    action: Literal["accept", "reject", "revise", "link"]
    actor: str = Field(..., min_length=1)
    reason: str = ""
    replacement: CandidateEdit | None = None
    documented_decision_id: str | None = None

    @model_validator(mode="after")
    def _check_action_payload(self) -> "ReviewRequest":
        """Cross-validate the payload each action requires and forbids."""
        if self.action == "revise" and self.replacement is None:
            raise ValueError("action='revise' requires a `replacement` CandidateEdit")
        if self.action != "revise" and self.replacement is not None:
            raise ValueError(f"`replacement` is only valid for action='revise', got action={self.action!r}")
        if self.action == "link" and self.documented_decision_id is None:
            raise ValueError("action='link' requires `documented_decision_id`")
        if self.action != "link" and self.documented_decision_id is not None:
            raise ValueError(f"`documented_decision_id` is only valid for action='link', got action={self.action!r}")
        return self


def as_json_dict(model: BaseModel) -> dict[str, Any]:
    """Dump a model in JSON mode — the only shape the codec and CLI emit."""
    return model.model_dump(mode="json")
