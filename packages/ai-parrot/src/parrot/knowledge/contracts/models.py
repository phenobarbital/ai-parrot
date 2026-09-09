"""Typed contract models — the normative data plane of FEAT-539.

Every model here is a Pydantic v2 model with closed taxonomies, bounded
payloads and stable *provenance paths* so that any extracted field can be
traced back to a quote in an indexed document.

:class:`ContractCard` is a **sibling** of
:class:`~parrot.knowledge.bookstore.models.BookCard`, not a subclass: the
two card families share only the :class:`TocEntry` row type and the
"one slug, one tree, one card" identity rule.

Design contract: spec ``sdd/specs/contracts-card-ontology.spec.md`` §2.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, Optional, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..bookstore.models import TocEntry

__all__ = (
    "MAX_QUOTE_CHARS",
    "UNSUBSTANTIATED_CONFIDENCE_CAP",
    "ContractType",
    "ContractStatus",
    "PartyRole",
    "ObligationKind",
    "Obligor",
    "VerificationState",
    "ProvenanceOrigin",
    "SourceFormat",
    "CardOrigin",
    "VersionKind",
    "AnswerKind",
    "AnswerProvenance",
    "PublicationTarget",
    "PublicationState",
    "IngestOutcome",
    "RelationKind",
    "CONTRACT_TYPES",
    "CONTRACT_STATUSES",
    "PARTY_ROLES",
    "OBLIGATION_KINDS",
    "OBLIGORS",
    "VERIFICATION_STATES",
    "PROVENANCE_ORIGINS",
    "SOURCE_FORMATS",
    "VERSION_KINDS",
    "ANSWER_KINDS",
    "RELATION_KINDS",
    "TocEntry",
    "Evidence",
    "Extracted",
    "FieldProvenance",
    "Party",
    "Signatory",
    "TermSpec",
    "Obligation",
    "ContractVersion",
    "ContractCard",
    "card_snapshot_payload",
    "PartyDraft",
    "SignatoryDraft",
    "ContractHeaderDraft",
    "ObligationClauseDraft",
    "ObligationsDraft",
    "Citation",
    "HandoffBrief",
    "ContractAnswer",
    "derive_provenance",
    "AuthorizationOutcome",
    "AnswerRecord",
    "PublicationRecord",
    "SourceItem",
    "SourceDeltaToken",
    "PartyAlias",
    "RelationJudgement",
    "ContractRelation",
    "IngestResult",
    "IngestItemReport",
    "IngestReport",
)

#: Hard cap for any evidential quote persisted or released (spec §2).
MAX_QUOTE_CHARS = 300


def trim_quote(value: Any) -> Any:
    """Trim an over-long quote to :data:`MAX_QUOTE_CHARS` at a word boundary.

    Models regularly return excerpts a little longer than the requested
    bound. Rejecting the whole structured draft for that discards every
    other clause in the section, so the excerpt is shortened instead: a
    verbatim prefix is still verbatim, and evidence validation checks it
    against the indexed text afterwards exactly as before.
    """
    if not isinstance(value, str) or len(value) <= MAX_QUOTE_CHARS:
        return value
    cut = value[:MAX_QUOTE_CHARS]
    space = cut.rfind(" ")
    if space > MAX_QUOTE_CHARS // 2:
        cut = cut[:space]
    return cut.rstrip()


#: An absent or invalid quote caps extraction confidence at this value and
#: prioritises verification; it can never substantiate a released citation.
UNSUBSTANTIATED_CONFIDENCE_CAP = 0.5


# --------------------------------------------------------------------------
# Closed taxonomies
# --------------------------------------------------------------------------

ContractType = Literal[
    "msa",
    "sow",
    "nda",
    "dpa",
    "amendment",
    "order_form",
    "license",
    "sla",
    "other",
]

ContractStatus = Literal[
    "draft",
    "active",
    "expired",
    "terminated",
    "superseded",
    "unknown",
]

PartyRole = Literal["customer", "vendor", "partner", "affiliate", "us", "other"]

ObligationKind = Literal[
    "compliance",
    "insurance",
    "data_protection",
    "security",
    "sla",
    "audit_right",
    "reporting",
    "payment",
    "confidentiality",
    "termination",
    "notice",
    "deliverable",
    "other",
]

Obligor = Literal["us", "counterparty", "both"]

#: Verification state and provenance origin are *independent* axes: a field
#: can be ``rule``-derived and ``verified``, or ``manual`` and ``stale``.
VerificationState = Literal["extracted", "verified", "stale"]
ProvenanceOrigin = Literal["llm", "rule", "manual"]

SourceFormat = Literal["pdf", "docx", "md", "txt"]
CardOrigin = Literal["llm", "fallback", "manual"]
VersionKind = Literal["original", "amendment", "renewal", "restatement"]

AnswerKind = Literal[
    "lookup",
    "interpretation_required",
    "not_found",
    "out_of_scope",
    "denied",
]
AnswerProvenance = Literal["verified", "mixed", "extracted"]

PublicationTarget = Literal["ontology", "temporal"]
PublicationState = Literal["pending", "in_flight", "published", "failed"]

IngestOutcome = Literal["added", "updated", "skipped", "error"]

#: Relation kinds judged by an LLM at explicit ingest/relate time (M7).
#: ``conflicts_with`` is symmetric; ``references_obligation`` is directed and
#: cross-contract; ``none`` records a negative judgement.
RelationKind = Literal["conflicts_with", "references_obligation", "none"]

CONTRACT_TYPES: tuple[str, ...] = get_args(ContractType)
CONTRACT_STATUSES: tuple[str, ...] = get_args(ContractStatus)
PARTY_ROLES: tuple[str, ...] = get_args(PartyRole)
OBLIGATION_KINDS: tuple[str, ...] = get_args(ObligationKind)
OBLIGORS: tuple[str, ...] = get_args(Obligor)
VERIFICATION_STATES: tuple[str, ...] = get_args(VerificationState)
PROVENANCE_ORIGINS: tuple[str, ...] = get_args(ProvenanceOrigin)
SOURCE_FORMATS: tuple[str, ...] = get_args(SourceFormat)
VERSION_KINDS: tuple[str, ...] = get_args(VersionKind)
ANSWER_KINDS: tuple[str, ...] = get_args(AnswerKind)
RELATION_KINDS: tuple[str, ...] = get_args(RelationKind)


# --------------------------------------------------------------------------
# Evidence and provenance
# --------------------------------------------------------------------------


class Evidence(BaseModel):
    """A verbatim excerpt anchoring one extracted fact to a tree node.

    Args:
        node_id: PageIndex node id the quote was read from.
        quote: Verbatim excerpt, at most :data:`MAX_QUOTE_CHARS` chars.
            An empty quote is representable (the extractor found the fact
            without an excerpt) but never *substantiating*.
        page: Physical page number (PDF trees), 1-based.
    """

    node_id: str = Field(..., min_length=1)
    quote: str = Field(default="", max_length=MAX_QUOTE_CHARS)

    @field_validator("quote", mode="before")
    @classmethod
    def _trim_quote(cls, value: Any) -> Any:
        return trim_quote(value)

    page: Optional[int] = Field(default=None, ge=1)

    @property
    def substantiates(self) -> bool:
        """True when this evidence carries a nonempty quote."""
        return bool(self.quote.strip())


T = TypeVar("T")


class Extracted(BaseModel, Generic[T]):
    """One typed value produced by extraction, with its evidence.

    Uses a typed generic rather than ``value: object`` so drafts keep their
    field types through structured-output round trips.

    Args:
        value: The extracted value, or ``None`` when not found.
        evidence: Supporting excerpt; absent/blank quotes cap ``confidence``
            at :data:`UNSUBSTANTIATED_CONFIDENCE_CAP`.
        confidence: Extractor confidence in ``[0, 1]``.
    """

    value: Optional[T] = None
    evidence: Optional[Evidence] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _cap_unsubstantiated_confidence(self) -> "Extracted[T]":
        if not (self.evidence and self.evidence.substantiates):
            if self.confidence > UNSUBSTANTIATED_CONFIDENCE_CAP:
                self.confidence = UNSUBSTANTIATED_CONFIDENCE_CAP
        return self

    @property
    def substantiated(self) -> bool:
        """True when a nonempty quote backs this value."""
        return bool(self.evidence and self.evidence.substantiates)


class FieldProvenance(BaseModel):
    """Where one card field came from and whether a human confirmed it.

    ``origin`` and ``verification`` are independent axes so field-state
    transitions are unambiguous: correcting a value makes the origin
    ``manual``; confirming an extracted value only moves ``verification``.

    Args:
        origin: ``llm`` extraction, ``rule`` derivation or ``manual`` entry.
        verification: ``extracted`` / ``verified`` / ``stale``.
        node_id: Node the quote was read from.
        page: Physical page (PDF sources).
        quote: Verbatim excerpt, at most :data:`MAX_QUOTE_CHARS` chars.
        confidence: Extractor confidence in ``[0, 1]``.
        verified_by: Authenticated actor who verified/corrected the field.
        verified_at: Verification timestamp.
        derived_from: Provenance paths a ``rule`` origin consumed.
        candidate: Refresh candidate value kept aside when new evidence
            contradicts a previously verified value (never overwrites it).
    """

    origin: ProvenanceOrigin = "llm"
    verification: VerificationState = "extracted"
    node_id: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    quote: Optional[str] = Field(default=None, max_length=MAX_QUOTE_CHARS)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    derived_from: list[str] = Field(default_factory=list)
    candidate: Optional[Any] = None

    @model_validator(mode="after")
    def _check_axes(self) -> "FieldProvenance":
        if self.verification == "verified" and not (self.verified_by and self.verified_at):
            raise ValueError("verified provenance requires verified_by and verified_at")
        if self.origin == "rule" and not self.derived_from:
            raise ValueError("rule-derived provenance must identify its derived_from paths")
        if not (self.quote or "").strip():
            if self.confidence is not None and self.confidence > UNSUBSTANTIATED_CONFIDENCE_CAP:
                self.confidence = UNSUBSTANTIATED_CONFIDENCE_CAP
        return self

    @property
    def substantiates(self) -> bool:
        """True when a nonempty quote backs this field."""
        return bool((self.quote or "").strip())


# --------------------------------------------------------------------------
# Card components
# --------------------------------------------------------------------------


class Party(BaseModel):
    """One legal entity bound by a contract.

    Args:
        party_id: Stable catalog identity (canonical after party merges).
        name: Entity name as written on the document.
        role: Commercial role in this agreement.
        is_us: True for our own entity; at most one per card.
    """

    party_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    role: PartyRole = "other"
    is_us: bool = False


class Signatory(BaseModel):
    """One person who signed on behalf of a party.

    Args:
        person_id: Stable identity for the signing person.
        name: Person name as signed.
        party_id: Party they signed for; must resolve to a card party.
        title: Signing title/role.
        signed_on: Signature date.
        employee_id: Internal employee id when the signer is one of ours.
    """

    person_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    party_id: str = Field(..., min_length=1)
    title: Optional[str] = None
    signed_on: Optional[date] = None
    employee_id: Optional[str] = None


class TermSpec(BaseModel):
    """Duration, renewal and notice facts of an agreement.

    ``notice_deadline`` and ``next_renewal_date`` are *derived* in Python
    (spec §2 carding step 6), never extracted by a model.

    Args:
        effective_date: Contractual start date.
        expiration_date: Contractual end date of the current term.
        initial_term_months: Initial term length in months.
        auto_renew: Whether the term renews automatically.
        renewal_period_months: Renewal period in months (positive).
        notice_days: Days of notice required before non-renewal.
        notice_deadline: ``expiration_date - notice_days`` (derived).
        next_renewal_date: ``expiration_date`` when ``auto_renew`` (derived).
    """

    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    initial_term_months: Optional[int] = Field(default=None, ge=0)
    auto_renew: bool = False
    renewal_period_months: Optional[int] = Field(default=None, gt=0)
    notice_days: Optional[int] = Field(default=None, ge=0)
    notice_deadline: Optional[date] = None
    next_renewal_date: Optional[date] = None


class Obligation(BaseModel):
    """One clause-level commitment, quoted verbatim from the source.

    Args:
        obligation_id: Stable id, unique within its contract.
        contract_id: Owning contract id.
        kind: Closed obligation taxonomy value.
        obligor: Who owes the commitment.
        text: Verbatim clause text.
        node_id: Node the clause was read from.
        page: Physical page (PDF sources).
        standard_id: Resolved compliance standard id, when the clause
            requires one (see :mod:`parrot.knowledge.contracts.standards`).
        due_date: Fixed due date, when stated.
        recurrence: Recurrence rule text as written (``"annually"``…).
        verification: Verification state of this obligation.
        provenance: Field provenance for the clause extraction.
        active: False once the contract is retracted (history is kept).
    """

    obligation_id: str = Field(..., min_length=1)
    contract_id: str = Field(..., min_length=1)
    kind: ObligationKind = "other"
    obligor: Obligor = "counterparty"
    text: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    standard_id: Optional[str] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    verification: VerificationState = "extracted"
    provenance: FieldProvenance = Field(default_factory=FieldProvenance)
    active: bool = True


class ContractVersion(BaseModel):
    """One recorded revision of a card, with its contractual interval.

    Recorded time (``recorded_at``, ``revision``) and contractual effective
    time (``valid_from`` / ``valid_to``) answer different questions and are
    deliberately kept apart. Unknown effective dates stay ``None`` instead of
    silently becoming today.

    Args:
        n: Contractual version number (1 = original), 1-based.
        revision: Recorded revision of this version; administrative
            corrections bump the revision without inventing an interval.
        valid_from: Inclusive contractual start of this version.
        valid_to: Exclusive contractual end, or ``None`` while in force.
        kind: What produced this version.
        amended_by: Contract id of the amendment that produced it.
        source_sha256: SHA-256 of the source bytes behind this version.
        card_snapshot: Card payload **without** its own ``versions`` list.
        recorded_at: When this revision was recorded in the catalog.
        evidence_ref: Archive reference for this version's evidence.
    """

    n: int = Field(..., ge=1)
    revision: int = Field(default=1, ge=1)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    kind: VersionKind = "original"
    amended_by: Optional[str] = None
    source_sha256: str = ""
    card_snapshot: dict[str, Any] = Field(default_factory=dict)
    recorded_at: Optional[datetime] = None
    evidence_ref: Optional[str] = None

    @field_validator("card_snapshot")
    @classmethod
    def _no_recursive_snapshot(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("versions"):
            raise ValueError("card_snapshot must omit its own 'versions' list " "(use card_snapshot_payload())")
        return value

    @model_validator(mode="after")
    def _check_interval(self) -> "ContractVersion":
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be exclusive and after valid_from")
        return self

    def in_force(self, as_of: date) -> bool:
        """Whether this version is contractually in force on ``as_of``.

        Args:
            as_of: The date to test.

        Returns:
            True when ``valid_from <= as_of < valid_to``; an unknown
            ``valid_from`` never claims to be in force.
        """
        if self.valid_from is None or as_of < self.valid_from:
            return False
        return self.valid_to is None or as_of < self.valid_to


class ContractCard(BaseModel):
    """The durable catalog card for one indexed contract document.

    ``contract_id`` doubles as the PageIndex ``tree_name`` — one slug, one
    tree, one card — mirroring the bookstore identity rule without
    inheriting from ``BookCard``.
    """

    model_config = ConfigDict(validate_assignment=False)

    contract_id: str = Field(..., min_length=1)
    tree_name: str = ""
    title: str = Field(..., min_length=1)
    contract_type: ContractType = "other"
    status: ContractStatus = "unknown"

    parties: list[Party] = Field(default_factory=list)
    signatories: list[Signatory] = Field(default_factory=list)
    term: TermSpec = Field(default_factory=TermSpec)
    governing_law: Optional[str] = None
    parent_contract_id: Optional[str] = None
    supersedes_contract_id: Optional[str] = None
    obligations: list[Obligation] = Field(default_factory=list)

    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    owner_employee_id: Optional[str] = None
    department: Optional[str] = None
    language: str = "en"

    source_uri: str = Field(..., min_length=1)
    source_path: Optional[str] = None
    source_sha256: str = ""
    source_format: SourceFormat = "pdf"
    page_count: Optional[int] = Field(default=None, ge=0)
    toc: list[TocEntry] = Field(default_factory=list)
    toc_digest: str = ""

    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    verification: VerificationState = "extracted"
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    stale_fields: list[str] = Field(default_factory=list)
    card_origin: CardOrigin = "llm"

    #: Human-confirmed termination. Termination is never inferred from the
    #: mere presence of a termination clause (spec §2 status precedence).
    termination_confirmed: bool = False
    terminated_on: Optional[date] = None

    versions: list[ContractVersion] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    active: bool = True
    added_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _check_identity_and_references(self) -> "ContractCard":
        if not self.tree_name:
            self.tree_name = self.contract_id
        elif self.tree_name != self.contract_id:
            raise ValueError("contract_id and tree_name must be the same slug")

        party_ids = [party.party_id for party in self.parties]
        if len(party_ids) != len(set(party_ids)):
            raise ValueError("party_id values must be unique on a card")
        if sum(1 for party in self.parties if party.is_us) > 1:
            raise ValueError("at most one is_us party is allowed on a card")

        known = set(party_ids)
        for signatory in self.signatories:
            if signatory.party_id not in known:
                raise ValueError(
                    f"signatory {signatory.person_id!r} references unknown " f"party {signatory.party_id!r}"
                )

        for obligation in self.obligations:
            if obligation.contract_id != self.contract_id:
                raise ValueError(
                    f"obligation {obligation.obligation_id!r} belongs to " f"contract {obligation.contract_id!r}"
                )

        if self.verification == "verified" and not (self.verified_by and self.verified_at):
            raise ValueError("a verified card requires verified_by and verified_at")

        if self.termination_confirmed and self.terminated_on is None:
            raise ValueError("confirmed termination requires terminated_on")

        return self

    @property
    def counterparties(self) -> list[Party]:
        """Every party that is not our own entity."""
        return [party for party in self.parties if not party.is_us]

    def brief(self) -> dict[str, Any]:
        """Compact dict for bounded tool/list payloads.

        Returns:
            The fields an agent needs to pick a contract, without the ToC,
            obligations or provenance payloads.
        """
        first_line = self.summary.split("\n", 1)[0] if self.summary else ""
        return {
            "contract_id": self.contract_id,
            "title": self.title,
            "contract_type": self.contract_type,
            "status": self.status,
            "counterparties": [party.name for party in self.counterparties],
            "effective_date": self.term.effective_date.isoformat() if self.term.effective_date else None,
            "expiration_date": self.term.expiration_date.isoformat() if self.term.expiration_date else None,
            "verification": self.verification,
            "owner_employee_id": self.owner_employee_id,
            "department": self.department,
            "summary": first_line,
            "obligation_count": len(self.obligations),
        }


def card_snapshot_payload(card: ContractCard) -> dict[str, Any]:
    """Serialise ``card`` for a :class:`ContractVersion` snapshot.

    Drops the card's own ``versions`` list so version history cannot grow
    recursively with every recorded revision.

    Args:
        card: The card to snapshot.

    Returns:
        A JSON-mode dict without the ``versions`` key.
    """
    payload = card.model_dump(mode="json")
    payload.pop("versions", None)
    return payload


# --------------------------------------------------------------------------
# Extraction drafts (LLM structured outputs)
# --------------------------------------------------------------------------


class PartyDraft(BaseModel):
    """Evidenced party candidate from the header extraction call."""

    name: str = Field(..., min_length=1)
    role: PartyRole = "other"
    is_us: bool = False
    evidence: Optional[Evidence] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SignatoryDraft(BaseModel):
    """Evidenced signatory candidate from the header extraction call."""

    name: str = Field(..., min_length=1)
    party_name: Optional[str] = None
    title: Optional[str] = None
    signed_on: Optional[date] = None
    employee_id: Optional[str] = None
    evidence: Optional[Evidence] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ContractHeaderDraft(BaseModel):
    """Structured output of the single bounded header extraction call.

    Deliberately carries **no** derived facts: status, ``notice_deadline``,
    ``next_renewal_date`` and ``parent_contract_id`` are computed in Python
    from these evidenced values (spec §2 carding steps 5–6).
    """

    title: Extracted[str] = Field(default_factory=Extracted[str])
    contract_type: Extracted[ContractType] = Field(default_factory=Extracted[ContractType])
    effective_date: Extracted[date] = Field(default_factory=Extracted[date])
    expiration_date: Extracted[date] = Field(default_factory=Extracted[date])
    initial_term_months: Extracted[int] = Field(default_factory=Extracted[int])
    auto_renew: Extracted[bool] = Field(default_factory=Extracted[bool])
    renewal_period_months: Extracted[int] = Field(default_factory=Extracted[int])
    notice_days: Extracted[int] = Field(default_factory=Extracted[int])
    governing_law: Extracted[str] = Field(default_factory=Extracted[str])
    parent_contract_title: Extracted[str] = Field(default_factory=Extracted[str])
    parties: list[PartyDraft] = Field(default_factory=list)
    signatories: list[SignatoryDraft] = Field(default_factory=list)
    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    language: str = "en"


class ObligationClauseDraft(BaseModel):
    """One evidenced obligation clause candidate.

    IDs, standard resolution and provenance are added deterministically
    during assembly, never by the model.
    """

    excerpt: str = Field(default="", max_length=MAX_QUOTE_CHARS)
    node_id: str = Field(..., min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    kind: ObligationKind = "other"

    @field_validator("excerpt", mode="before")
    @classmethod
    def _trim_excerpt(cls, value: Any) -> Any:
        return trim_quote(value)

    obligor: Obligor = "counterparty"
    standard_name: Optional[str] = None
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ObligationsDraft(BaseModel):
    """Structured output of one bounded obligation-section call."""

    clauses: list[ObligationClauseDraft] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Answering
# --------------------------------------------------------------------------


class Citation(BaseModel):
    """One released evidence pointer, pinned to an immutable version.

    ``version_n`` and ``source_sha256`` are part of the citation identity so
    a historical node id can never silently resolve against current text.

    Args:
        contract_id: Cited contract.
        title: Contract title at release time (derived from evidence).
        node_id: Node the quote belongs to.
        quote: Verbatim excerpt; never empty in a released citation.
        page: Physical page (PDF sources).
        verification: Verification state of the cited field/clause.
        version_n: Contract version the quote was read from.
        source_sha256: SHA-256 of that version's source bytes.
    """

    contract_id: str = Field(..., min_length=1)
    title: str = ""
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
        """The ``(contract_id, node_id)`` pair used by retirement rules."""
        return (self.contract_id, self.node_id)


class HandoffBrief(BaseModel):
    """What a human needs to adjudicate an interpretation request."""

    question: str = Field(..., min_length=1)
    why_judgment: str = Field(..., min_length=1)
    located_clauses: list[Citation] = Field(default_factory=list)
    related_contracts: list[str] = Field(default_factory=list)
    suggested_owner: Optional[str] = None


class ContractAnswer(BaseModel):
    """The single answer shape shared by the ReAct agent and fixed flow.

    Kind invariants (spec §2 "Answering and authorization"):

    * ``lookup`` — requires answer text and at least one citation.
    * ``interpretation_required`` — requires a handoff and carries **no**
      judgment answer.
    * ``not_found`` / ``out_of_scope`` / ``denied`` — carry no fabricated
      answer, evidence or handoff.

    ``provenance`` is always derived from the surviving citations, never
    taken from model output.
    """

    answer_kind: AnswerKind
    answer: Optional[str] = None
    citations: list[Citation] = Field(default_factory=list)
    provenance: AnswerProvenance = "extracted"
    handoff: Optional[HandoffBrief] = None
    pattern: Optional[str] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _check_kind_invariants(self) -> "ContractAnswer":
        kind = self.answer_kind
        if kind == "lookup":
            if not (self.answer or "").strip():
                raise ValueError("a lookup answer requires answer text")
            if not self.citations:
                raise ValueError("a lookup answer requires at least one citation")
            if self.handoff is not None:
                raise ValueError("a lookup answer must not carry a handoff")
        elif kind == "interpretation_required":
            if self.handoff is None:
                raise ValueError("interpretation_required requires a handoff brief")
            if (self.answer or "").strip():
                raise ValueError("interpretation_required must not carry a judgment answer")
        else:
            if (self.answer or "").strip():
                raise ValueError(f"{kind} answers must not carry answer text")
            if self.citations:
                raise ValueError(f"{kind} answers must not carry citations")
            if self.handoff is not None:
                raise ValueError(f"{kind} answers must not carry a handoff")

        self.provenance = derive_provenance(self.citations)
        return self


def derive_provenance(citations: list[Citation]) -> AnswerProvenance:
    """Derive the top-level provenance of an answer from its citations.

    Args:
        citations: The surviving, verified citations of an answer.

    Returns:
        ``verified`` when every citation is verified, ``mixed`` when
        verified and unverified citations coexist, otherwise ``extracted``
        (also the conservative value for empty evidence).
    """
    if not citations:
        return "extracted"
    verified = sum(1 for citation in citations if citation.verification == "verified")
    if verified == len(citations):
        return "verified"
    if verified:
        return "mixed"
    return "extracted"


class AuthorizationOutcome(BaseModel):
    """The recorded result of the shared authorization gate."""

    allowed: bool
    principal: Optional[str] = None
    matched_rule: Optional[str] = None
    reason: Optional[str] = None


class AnswerRecord(BaseModel):
    """One audited answer, persisted before the answer is released.

    Denials and empty answers are retained: the audit trail is the reason a
    citation can later be retired and suppressed.
    """

    answer_id: str = Field(..., min_length=1)
    asked_at: datetime
    user: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer_kind: AnswerKind
    pattern: Optional[str] = None
    answer: Optional[str] = None
    citations: list[Citation] = Field(default_factory=list)
    authorization: AuthorizationOutcome
    retired_by: Optional[str] = None
    retired_at: Optional[datetime] = None
    retirement_reason: Optional[str] = None

    @property
    def retired(self) -> bool:
        """True once this answer has been retired by an owner."""
        return self.retired_at is not None


# --------------------------------------------------------------------------
# Publication, sources and relations
# --------------------------------------------------------------------------


class PublicationRecord(BaseModel):
    """One durable outbox row for a card revision and publication target.

    The ``(tenant_id, contract_id, version_n, revision, target)`` tuple is
    the queue identity; ``run_id`` is stable per revision so an
    acknowledged-but-unrecorded commit can be recovered instead of
    republished.
    """

    tenant_id: str = Field(..., min_length=1)
    contract_id: str = Field(..., min_length=1)
    version_n: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    target: PublicationTarget
    run_id: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    state: PublicationState = "pending"
    receipt: Optional[str] = None
    attempts: int = Field(default=0, ge=0)
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def key(self) -> tuple[str, str, int, int, str]:
        """The durable queue identity of this record."""
        return (
            self.tenant_id,
            self.contract_id,
            self.version_n,
            self.revision,
            self.target,
        )


class SourceItem(BaseModel):
    """Stable identity of one remote source file across renames/moves.

    Recorded so a delta rename is not mistaken for a new document and a
    tombstone retracts the right contract.
    """

    source: str = Field(..., min_length=1)
    drive_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    current_uri: str = ""
    name: Optional[str] = None
    contract_id: Optional[str] = None
    sha256: Optional[str] = None
    deleted: bool = False
    last_seen_at: Optional[datetime] = None


class SourceDeltaToken(BaseModel):
    """The committed opaque continuation token for one configured source."""

    source_uri: str = Field(..., min_length=1)
    token: str = ""
    updated_at: Optional[datetime] = None


class PartyAlias(BaseModel):
    """One normalized alias mapped onto a canonical party identity."""

    alias: str = Field(..., min_length=1)
    party_id: str = Field(..., min_length=1)
    actor: Optional[str] = None
    created_at: Optional[datetime] = None


class RelationJudgement(BaseModel):
    """One logged LLM relation judgement, including negative outcomes.

    Judgements are made only at explicit ingest/relate time and are
    invalidated when either endpoint's source hash changes.
    """

    judgement_id: str = Field(..., min_length=1)
    source_contract_id: str = Field(..., min_length=1)
    target_contract_id: str = Field(..., min_length=1)
    outcome: RelationKind = "none"
    source_sha256: str = ""
    target_sha256: str = ""
    source_obligation_id: Optional[str] = None
    target_obligation_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    model: str = ""
    judged_at: Optional[datetime] = None
    origin: Literal["llm", "manual"] = "llm"
    active: bool = True

    @model_validator(mode="after")
    def _reject_self_judgement(self) -> "RelationJudgement":
        if self.source_contract_id == self.target_contract_id:
            raise ValueError("a contract cannot be judged against itself")
        return self


class ContractRelation(BaseModel):
    """One active, judged edge between two contracts."""

    source_contract_id: str = Field(..., min_length=1)
    target_contract_id: str = Field(..., min_length=1)
    kind: Literal["conflicts_with", "references_obligation"]
    source_obligation_id: Optional[str] = None
    target_obligation_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    origin: Literal["llm", "manual"] = "llm"
    judged_at: Optional[datetime] = None
    active: bool = True

    @model_validator(mode="after")
    def _canonicalize_symmetric(self) -> "ContractRelation":
        if self.source_contract_id == self.target_contract_id:
            raise ValueError("a contract cannot relate to itself")
        if self.kind == "conflicts_with" and self.target_contract_id < self.source_contract_id:
            self.source_contract_id, self.target_contract_id = (
                self.target_contract_id,
                self.source_contract_id,
            )
        return self


# --------------------------------------------------------------------------
# Ingestion reporting
# --------------------------------------------------------------------------


class IngestResult(BaseModel):
    """The outcome of ingesting one source document.

    ``card`` is ``None`` for ``skipped``/``error`` outcomes, and ``reason``
    is always explicit (unchanged content, no extractable text, …).
    """

    card: Optional[ContractCard] = None
    outcome: IngestOutcome
    reason: str = ""
    source_uri: str = ""
    publication_state: Optional[PublicationState] = None

    @model_validator(mode="after")
    def _check_outcome(self) -> "IngestResult":
        if self.outcome in ("added", "updated") and self.card is None:
            raise ValueError(f"{self.outcome} results must carry a card")
        if self.outcome in ("skipped", "error") and not self.reason.strip():
            raise ValueError(f"{self.outcome} results must carry an explicit reason")
        if self.card is not None and not self.source_uri:
            self.source_uri = self.card.source_uri
        return self


class IngestItemReport(BaseModel):
    """Per-file outcome inside a batch ingestion report."""

    source_uri: str = Field(..., min_length=1)
    outcome: IngestOutcome
    contract_id: Optional[str] = None
    reason: str = ""
    publication_state: Optional[PublicationState] = None

    @classmethod
    def from_result(cls, result: IngestResult) -> "IngestItemReport":
        """Build a report row from a single :class:`IngestResult`."""
        return cls(
            source_uri=result.source_uri or "unknown",
            outcome=result.outcome,
            contract_id=result.card.contract_id if result.card else None,
            reason=result.reason,
            publication_state=result.publication_state,
        )


class IngestReport(BaseModel):
    """Deterministic per-batch ingestion report."""

    items: list[IngestItemReport] = Field(default_factory=list)
    cursor_advanced: bool = False
    cursor: Optional[str] = None

    def _count(self, outcome: str) -> int:
        return sum(1 for item in self.items if item.outcome == outcome)

    @property
    def added(self) -> int:
        """Number of newly carded documents."""
        return self._count("added")

    @property
    def updated(self) -> int:
        """Number of documents that produced a new revision."""
        return self._count("updated")

    @property
    def skipped(self) -> int:
        """Number of documents deliberately skipped, with a reason."""
        return self._count("skipped")

    @property
    def errors(self) -> int:
        """Number of documents that failed with a recorded reason."""
        return self._count("error")

    def summary(self) -> dict[str, int]:
        """Compact counts for logs and operator output."""
        return {
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }
