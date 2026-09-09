"""Staged contract ingestion and canonical source identity (FEAT-539 M4).

:class:`ContractLibrary` is the ingestion entry point: it validates a
source, resolves its identity (URI first, then content hash), builds the
PageIndex tree in a **staging** root, cards it under the bounded ``1 + N``
budget, archives the derived evidence immutably and persists the card,
obligations, version and publication work in one catalog transaction. The
staged tree is promoted only after that transaction commits, so a failure
anywhere in between leaves the previously published card/evidence pair
usable.

Verification and refresh (TASK-3035) and judged relations (TASK-3040)
extend this same class.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from ..bookstore.carding import derive_toc
from .carding import (
    DEFAULT_MAX_OBLIGATION_SECTIONS,
    assemble_card,
    derive_next_renewal_date,
    derive_notice_deadline,
    derive_status,
    draft_contract,
    load_bodies,
    slugify,
    unique_slug,
)
from .catalog import (
    CatalogError,
    ContractCatalogStore,
    DuplicateSourceError,
    UnknownContractError,
)
from .evidence import EvidenceArchive, EvidenceError, EvidenceRef, StagingArea
from .models import (
    ContractCard,
    ContractVersion,
    FieldProvenance,
    IngestItemReport,
    IngestReport,
    IngestResult,
    SourceFormat,
    card_snapshot_payload,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .relations import RelationStageReport

__all__ = (
    "SUPPORTED_FORMATS",
    "VERIFIABLE_PATHS",
    "TreeIndexer",
    "OwnerRule",
    "VerificationResult",
    "ContractLibrary",
    "deterministic_sections",
    "pdf_markdown",
    "merge_verified_fields",
    "get_card_field",
    "set_card_field",
)

logger = logging.getLogger(__name__)

#: Formats the pilot ingests. Scanned/no-text PDFs are skipped explicitly;
#: OCR is out of scope.
SUPPORTED_FORMATS: dict[str, SourceFormat] = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".docx": "docx",
    ".pdf": "pdf",
}

_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_PAGE_TITLE_RE = re.compile(r"^page\s+(\d+)$", re.IGNORECASE)
_DEFAULT_SECTION_CHARS = 2_000

#: Unverified fields below this confidence block whole-card verification.
LOW_CONFIDENCE = 0.6


class TreeIndexer(Protocol):
    """The PageIndex surface the library depends on.

    Satisfied by :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit`
    and by test doubles.
    """

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]: ...

    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: Optional[str] = None,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def get_tree(self, tree_name: str) -> dict[str, Any]: ...

    async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...


class OwnerRule(BaseModel):
    """A folder-path rule assigning ownership at ingest time.

    The **most specific** (longest) matching prefix wins; when nothing
    matches the card is left unassigned rather than guessed.

    Args:
        path_prefix: Folder prefix matched against the source URI/path.
        owner_employee_id: Owner assigned to matching documents.
        department: Department assigned to matching documents.
    """

    path_prefix: str = Field(..., min_length=1)
    owner_employee_id: Optional[str] = None
    department: Optional[str] = None


#: A numbered article caption in ALL CAPS, e.g. ``1. DEFINITIONS`` or
#: ``12. GOVERNING LAW AND VENUE`` — the structure contracts carry when a
#: DOCX has no Word heading styles.
_NUMBERED_CAPTION_RE = re.compile(r"^(?P<number>\d{1,3})\.?\s+(?P<title>[A-Z][A-Z0-9 ,;:&/\-()'\u2019]{2,90})\s*$")


def promote_numbered_headings(text: str) -> str:
    """Turn numbered ALL-CAPS article captions into markdown headings.

    The first non-empty line becomes the ``#`` document title and every
    ``N. TITLE`` caption a ``##`` section heading; every other line is left
    untouched, so the text stays verbatim for evidence checks. When no
    caption is found the text is returned unchanged (and the caller falls
    back to :func:`deterministic_sections`).

    Args:
        text: Heading-less markdown or plain text.

    Returns:
        Markdown with promoted headings, or ``text`` unchanged.
    """
    lines = (text or "").splitlines()
    captions = [index for index, line in enumerate(lines) if _NUMBERED_CAPTION_RE.match(line.strip())]
    if not captions:
        return text
    promoted = list(lines)
    for index in captions:
        promoted[index] = f"## {lines[index].strip()}"
    first = next((index for index, line in enumerate(promoted) if line.strip()), None)
    if first is not None and first < captions[0]:
        promoted[first] = f"# {promoted[first].strip()}"
    return "\n".join(promoted)


def deterministic_sections(
    text: str,
    *,
    chunk_chars: int = _DEFAULT_SECTION_CHARS,
    title_prefix: str = "Section",
) -> str:
    """Section heading-less text deterministically.

    Splits on blank lines and packs paragraphs into stable, numbered
    sections so a TXT (or heading-less markdown) document still produces a
    navigable tree without a model.

    Args:
        text: The raw document text.
        chunk_chars: Target characters per section.
        title_prefix: Heading prefix for generated sections.

    Returns:
        Markdown with ``## <title_prefix> N`` headings.
    """
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]
    if not paragraphs:
        return ""
    sections: list[list[str]] = [[]]
    size = 0
    for paragraph in paragraphs:
        if size and size + len(paragraph) > chunk_chars:
            sections.append([])
            size = 0
        sections[-1].append(paragraph)
        size += len(paragraph)
    return "\n\n".join(
        f"## {title_prefix} {index + 1}\n\n" + "\n\n".join(block) for index, block in enumerate(sections) if block
    )


def pdf_markdown(pages: Sequence[str]) -> str:
    """Render extracted PDF page text as page-anchored markdown.

    Each page becomes a ``## Page N`` section so evidence keeps a physical
    page anchor even when model-dependent indexing is unavailable.

    Args:
        pages: Text of each page, in order.

    Returns:
        Page-anchored markdown (empty when no page carried text).
    """
    chunks = [
        f"## Page {number}\n\n{text.strip()}" for number, text in enumerate(pages, start=1) if (text or "").strip()
    ]
    return "\n\n".join(chunks)


#: Card fields a human may confirm or correct through ``verify_card``.
#: Everything else is derived in code or belongs to another operation.
VERIFIABLE_PATHS: tuple[str, ...] = (
    "title",
    "contract_type",
    "governing_law",
    "language",
    "summary",
    "owner_employee_id",
    "department",
    "parent_contract_id",
    "supersedes_contract_id",
    "termination_confirmed",
    "terminated_on",
    "term.effective_date",
    "term.expiration_date",
    "term.initial_term_months",
    "term.auto_renew",
    "term.renewal_period_months",
    "term.notice_days",
)

#: Derived values recomputed after any correction; never set directly.
DERIVED_PATHS: tuple[str, ...] = (
    "status",
    "term.notice_deadline",
    "term.next_renewal_date",
)


def get_card_field(card: ContractCard, path: str) -> Any:
    """Read one card field by its provenance path.

    Args:
        card: The card to read.
        path: A dotted path such as ``"term.notice_days"`` or
            ``"parties.<party_id>.name"``.

    Returns:
        The current value.

    Raises:
        KeyError: When the path does not address a known field.
    """
    parts = path.split(".")
    if parts[0] == "term" and len(parts) == 2:
        return getattr(card.term, parts[1])
    if parts[0] == "parties" and len(parts) == 3:
        for party in card.parties:
            if party.party_id == parts[1]:
                return getattr(party, parts[2])
        raise KeyError(path)
    if parts[0] == "obligations" and len(parts) == 3:
        for obligation in card.obligations:
            if obligation.obligation_id == parts[1]:
                return getattr(obligation, parts[2])
        raise KeyError(path)
    if len(parts) == 1 and hasattr(card, parts[0]):
        return getattr(card, parts[0])
    raise KeyError(path)


def set_card_field(card: ContractCard, path: str, value: Any) -> ContractCard:
    """Return a copy of ``card`` with one field corrected.

    Args:
        card: The card to correct.
        path: A verifiable provenance path.
        value: The corrected value.

    Returns:
        The updated card.

    Raises:
        KeyError: When the path is not correctable.
    """
    parts = path.split(".")
    if parts[0] == "term" and len(parts) == 2:
        return card.model_copy(update={"term": card.term.model_copy(update={parts[1]: value})})
    if parts[0] == "parties" and len(parts) == 3:
        if not any(party.party_id == parts[1] for party in card.parties):
            raise KeyError(path)
        parties = [
            party.model_copy(update={parts[2]: value}) if party.party_id == parts[1] else party
            for party in card.parties
        ]
        return card.model_copy(update={"parties": parties})
    if parts[0] == "obligations" and len(parts) == 3:
        if not any(item.obligation_id == parts[1] for item in card.obligations):
            raise KeyError(path)
        obligations = [
            obligation.model_copy(update={parts[2]: value}) if obligation.obligation_id == parts[1] else obligation
            for obligation in card.obligations
        ]
        return card.model_copy(update={"obligations": obligations})
    if len(parts) == 1 and hasattr(card, parts[0]):
        return card.model_copy(update={parts[0]: value})
    raise KeyError(path)


def _recompute_derivations(card: ContractCard, *, today: date) -> ContractCard:
    """Recompute notice/renewal dates and the status after a correction."""
    term = card.term.model_copy(
        update={
            "notice_deadline": derive_notice_deadline(card.term.expiration_date, card.term.notice_days),
            "next_renewal_date": derive_next_renewal_date(card.term.expiration_date, card.term.auto_renew),
        }
    )
    status = derive_status(
        term=term,
        today=today,
        signed=bool(card.signatories),
        superseded=card.status == "superseded",
        termination_confirmed=card.termination_confirmed,
        terminated_on=card.terminated_on,
    )
    return card.model_copy(update={"term": term, "status": status})


def merge_verified_fields(
    previous: ContractCard,
    incoming: ContractCard,
    bodies: Mapping[str, str],
) -> ContractCard:
    """Carry human decisions across a refresh.

    For every field a human verified on ``previous``:

    * a **nonempty** quote found verbatim in the refreshed bodies proves the
      evidence is unchanged — the verified value and its verification are
      preserved and the evidence is rebound to the node that now holds it;
    * changed or missing evidence (and an empty quote, which never proves
      anything) keeps the **previous** value, records the incoming value as
      a separate ``candidate`` and marks the field stale for review.

    Args:
        previous: The currently published card.
        incoming: The freshly carded card.
        bodies: ``node_id -> markdown`` of the refreshed tree.

    Returns:
        The merged card.
    """
    merged = incoming
    provenance = dict(incoming.field_provenance)
    stale = list(incoming.stale_fields)

    quotes = {
        path: (prov.quote or "") for path, prov in previous.field_provenance.items() if prov.verification == "verified"
    }
    mapping = EvidenceArchive.map_evidence(quotes, bodies)

    for path, prov in previous.field_provenance.items():
        if prov.verification != "verified":
            continue
        try:
            previous_value = get_card_field(previous, path)
        except KeyError:
            continue
        try:
            incoming_value = get_card_field(incoming, path)
        except KeyError:
            incoming_value = None

        node_id = mapping.get(path)
        if node_id is not None:
            merged = set_card_field(merged, path, previous_value)
            provenance[path] = prov.model_copy(update={"node_id": node_id, "candidate": None})
            if path in stale:
                stale.remove(path)
            continue

        merged = set_card_field(merged, path, previous_value)
        provenance[path] = prov.model_copy(
            update={
                "verification": "stale",
                "candidate": incoming_value,
            }
        )
        if path not in stale:
            stale.append(path)

    verification = previous.verification if previous.verification == "verified" else "extracted"
    if stale:
        verification = "stale"
    return merged.model_copy(
        update={
            "field_provenance": provenance,
            "stale_fields": sorted(set(stale)),
            "verification": verification,
            "verified_by": previous.verified_by if verification == "verified" else None,
            "verified_at": previous.verified_at if verification == "verified" else None,
            "termination_confirmed": previous.termination_confirmed,
            "terminated_on": previous.terminated_on,
        }
    )


class VerificationResult(BaseModel):
    """What one ``verify_card`` call confirmed, corrected or blocked."""

    card: ContractCard
    verified: list[str] = Field(default_factory=list)
    corrected: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    @property
    def card_verified(self) -> bool:
        """Whether the whole card is now verified."""
        return self.card.verification == "verified"


def _utcnow() -> datetime:
    """Current UTC time (injectable for frozen-clock tests)."""
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    """Current UTC date (injectable for frozen-clock tests)."""
    return datetime.now(tz=timezone.utc).date()


async def docx_to_markdown(path: Path) -> str:
    """Delegate DOCX conversion without importing optional readers eagerly."""
    from ..bookstore.library import docx_to_markdown as convert

    return await convert(path)


def _default_content_store_factory(storage_dir: Path) -> Any:
    """Load PageIndex only when a caller actually needs content storage."""
    from ..pageindex.content_store import NodeContentStore

    return NodeContentStore(storage_dir)


class ContractLibrary:
    """Ingest, card and publish contracts for one tenant.

    Args:
        catalog: The tenant-bound authoritative catalog.
        storage_root: Root of the tenant's PageIndex storage (published and
            staging trees live underneath it).
        evidence_root: Root of the immutable evidence archive.
        adapter: A ``PageIndexLLMAdapter``-shaped object, or ``None`` for
            deterministic no-LLM ingestion.
        indexer_factory: ``(storage_dir, adapter) -> TreeIndexer``. Defaults
            to a real :class:`PageIndexToolkit`.
        content_store_factory: ``storage_dir -> NodeContentStore``.
        owner_rules: Folder-path ownership rules.
        max_obligation_sections: The ``N`` of the ``1 + N`` carding budget.
        max_candidates: Bound on relation candidates per source contract.
        relation_stage: Pre-built ``ContractRelationStage`` (optional).
        relate_on_ingest: Judge relations after each successful ingestion.
        now: Clock for recorded timestamps.
        today: Clock for contractual derivations.
    """

    def __init__(
        self,
        *,
        catalog: ContractCatalogStore,
        storage_root: str | Path,
        evidence_root: str | Path,
        adapter: Any = None,
        indexer_factory: Optional[Callable[[Path, Any], TreeIndexer]] = None,
        content_store_factory: Optional[Callable[[Path], Any]] = None,
        owner_rules: Sequence[OwnerRule] = (),
        max_obligation_sections: int = DEFAULT_MAX_OBLIGATION_SECTIONS,
        max_candidates: int = 8,
        relation_stage: Any = None,
        relate_on_ingest: bool = False,
        now: Callable[[], datetime] = _utcnow,
        today: Callable[[], date] = _today,
    ) -> None:
        self.catalog = catalog
        self.adapter = adapter
        self.staging = StagingArea(storage_root, tenant_id=catalog.tenant_id)
        self.evidence = EvidenceArchive(evidence_root, tenant_id=catalog.tenant_id)
        self.owner_rules = sorted(owner_rules, key=lambda rule: -len(rule.path_prefix))
        self.max_obligation_sections = max_obligation_sections
        self.max_candidates = max_candidates
        #: Judge relations right after a successful ingestion. Off by
        #: default: judgement is an explicit, budgeted operation.
        self.relate_on_ingest = relate_on_ingest
        self._relation_stage = relation_stage
        self._indexer_factory = indexer_factory or _default_indexer_factory
        self._content_store_factory = content_store_factory or _default_content_store_factory
        self._now = now
        self._today = today

    # -- public API --------------------------------------------------------

    async def add_contract(
        self,
        source: str | Path,
        *,
        source_uri: Optional[str] = None,
        force: bool = False,
    ) -> IngestResult:
        """Ingest one document, returning a card or an explicit reason.

        Args:
            source: Path to the document on disk.
            source_uri: Canonical location; defaults to the local path.
            force: Re-card even when the content hash is unchanged.

        Returns:
            An :class:`IngestResult` — ``added``/``updated`` with a card, or
            ``skipped``/``error`` with a reason. Never raises for expected
            outcomes (unsupported format, unreadable file, scanned PDF).
        """
        path = Path(source)
        uri = source_uri or path.as_uri() if path.is_absolute() else (source_uri or str(path))

        source_format = SUPPORTED_FORMATS.get(path.suffix.lower())
        if source_format is None:
            return IngestResult(
                outcome="skipped",
                reason=f"unsupported format {path.suffix or '(none)'}",
                source_uri=uri,
            )
        if not path.is_file():
            return IngestResult(outcome="error", reason=f"source not found: {path}", source_uri=uri)

        try:
            payload = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            return IngestResult(outcome="error", reason=f"unreadable source: {exc}", source_uri=uri)
        sha256 = hashlib.sha256(payload).hexdigest()

        existing = await self.catalog.find_by_source_uri(uri)
        if existing is None:
            by_content = await self.catalog.find_by_sha(sha256)
            if by_content is not None:
                # Duplicate content at another URI resolves to the existing
                # card; the original canonical URI is retained.
                return IngestResult(
                    card=by_content,
                    outcome="skipped",
                    reason=(
                        f"duplicate content of {by_content.contract_id!r} "
                        f"(canonical source {by_content.source_uri})"
                    ),
                    source_uri=uri,
                )
        elif existing.source_sha256 == sha256 and not force:
            try:
                await self._recover_promotion(existing)
            except EvidenceError as exc:
                return IngestResult(outcome="error", reason=f"promotion failed: {exc}", source_uri=uri)
            return IngestResult(
                card=existing,
                outcome="skipped",
                reason="unchanged content (identical sha256)",
                source_uri=uri,
            )

        try:
            markdown, pages = await self._to_markdown(path, source_format)
        except EvidenceError as exc:  # pragma: no cover - defensive
            return IngestResult(outcome="error", reason=str(exc), source_uri=uri)
        except Exception as exc:  # noqa: BLE001 - conversion failures are data errors
            logger.warning("Conversion failed for %s: %s", path, exc)
            return IngestResult(outcome="error", reason=f"conversion failed: {exc}", source_uri=uri)

        if not markdown.strip():
            reason = (
                "no extractable text (scanned PDF; OCR is out of scope)"
                if source_format == "pdf"
                else "document has no readable content"
            )
            return IngestResult(outcome="skipped", reason=reason, source_uri=uri)

        contract_id = existing.contract_id if existing else await self._allocate_slug(path)
        return await self._ingest(
            contract_id=contract_id,
            existing=existing,
            markdown=markdown,
            page_hints=pages,
            path=path,
            uri=uri,
            sha256=sha256,
            source_format=source_format,
        )

    async def add_folder(
        self,
        folder: str | Path,
        *,
        recursive: bool = False,
        force: bool = False,
    ) -> IngestReport:
        """Ingest every supported document in a folder, deterministically.

        Args:
            folder: Folder to walk.
            recursive: Walk sub-folders too.
            force: Re-card unchanged content.

        Returns:
            An :class:`IngestReport` with one row per document.
        """
        base = Path(folder)
        if not base.is_dir():
            return IngestReport(
                items=[
                    IngestItemReport(
                        source_uri=str(base),
                        outcome="error",
                        reason=f"not a folder: {base}",
                    )
                ]
            )

        def _walk() -> list[Path]:
            pattern = "**/*" if recursive else "*"
            return sorted(
                candidate
                for candidate in base.glob(pattern)
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_FORMATS
            )

        paths = await asyncio.to_thread(_walk)
        items: list[IngestItemReport] = []
        for candidate in paths:
            result = await self.add_contract(candidate, force=force)
            items.append(IngestItemReport.from_result(result))
        return IngestReport(items=items)

    async def verify_card(
        self,
        contract_id: str,
        fields: Optional[Mapping[str, Any]] = None,
        *,
        user: str,
        expected_revision: Optional[int] = None,
    ) -> VerificationResult:
        """Confirm or correct card fields on behalf of an authenticated human.

        ``fields=None`` verifies the *whole current card* and refuses while
        required evidence gaps, unresolved low-confidence fields or stale
        fields remain. A mapping verifies only the paths it names: a value
        equal to the current one (or ``None``) is a **confirmation** — the
        origin is untouched — while a different value is a **correction**,
        which additionally moves the origin to ``manual``.

        Args:
            contract_id: The card to verify.
            fields: ``path -> value`` to confirm/correct, or ``None``.
            user: Authenticated actor stamped on every touched field.
            expected_revision: Revision the caller read; a concurrent write
                raises :class:`CatalogConflictError`.

        Returns:
            A :class:`VerificationResult`.

        Raises:
            UnknownContractError: When the contract does not exist.
            KeyError: When a requested path is not correctable.
            CatalogConflictError: On a stale ``expected_revision``.
        """
        card = await self.catalog.get(contract_id)
        if card is None:
            raise UnknownContractError(contract_id)

        now = self._now()
        provenance = dict(card.field_provenance)
        stale = list(card.stale_fields)
        verified: list[str] = []
        corrected: list[str] = []

        targets = dict(fields) if fields is not None else {}
        if fields is not None:
            for path in targets:
                if path not in VERIFIABLE_PATHS and not path.startswith(("parties.", "obligations.")):
                    raise KeyError(f"{path!r} is not a verifiable field")

        for path, value in targets.items():
            current = get_card_field(card, path)
            existing_provenance = provenance.get(path) or FieldProvenance(origin="llm")
            if value is None or value == current:
                provenance[path] = existing_provenance.model_copy(
                    update={
                        "verification": "verified",
                        "verified_by": user,
                        "verified_at": now,
                        "candidate": None,
                    }
                )
                verified.append(path)
            else:
                card = set_card_field(card, path, value)
                provenance[path] = existing_provenance.model_copy(
                    update={
                        "origin": "manual",
                        "verification": "verified",
                        "verified_by": user,
                        "verified_at": now,
                        "candidate": None,
                        "confidence": 1.0,
                        "derived_from": [],
                    }
                )
                corrected.append(path)
            if path in stale:
                stale.remove(path)

        if fields is None:
            for path, prov in provenance.items():
                if prov.origin == "rule" or prov.verification == "verified":
                    continue
                provenance[path] = prov.model_copy(
                    update={
                        "verification": "verified",
                        "verified_by": user,
                        "verified_at": now,
                        "candidate": None,
                    }
                )
                verified.append(path)

        card = card.model_copy(update={"field_provenance": provenance, "stale_fields": sorted(set(stale))})
        card = _recompute_derivations(card, today=self._today())

        blockers = self._verification_blockers(card)
        if not blockers:
            card = card.model_copy(
                update={
                    "verification": "verified",
                    "verified_by": user,
                    "verified_at": now,
                }
            )
        elif card.verification == "verified":
            card = card.model_copy(update={"verification": "extracted", "verified_by": None, "verified_at": None})

        await self.catalog.upsert(
            card,
            expected_revision=expected_revision if expected_revision is not None else card.revision,
        )
        stored = await self.catalog.get(contract_id) or card
        return VerificationResult(
            card=stored,
            verified=sorted(set(verified)),
            corrected=sorted(set(corrected)),
            blockers=blockers,
        )

    def _verification_blockers(self, card: ContractCard) -> list[str]:
        """List what still blocks marking the whole card verified."""
        blockers: list[str] = []
        for path, prov in sorted(card.field_provenance.items()):
            if prov.origin == "rule" or prov.verification == "verified":
                continue
            if not prov.substantiates:
                blockers.append(f"{path}: missing evidence")
            elif (prov.confidence or 0.0) < LOW_CONFIDENCE:
                blockers.append(f"{path}: unresolved low confidence")
            else:
                blockers.append(f"{path}: unverified")
        blockers.extend(f"{path}: stale" for path in sorted(card.stale_fields))
        return blockers

    async def refresh_card(
        self,
        contract_id: str,
        *,
        source: Optional[str | Path] = None,
    ) -> IngestResult:
        """Re-card a contract while preserving every human decision.

        Verified values survive: unchanged nonempty evidence is rebound to
        its new node, and changed or missing evidence keeps the prior value,
        records the new one as a candidate and marks the field stale.

        Args:
            contract_id: The contract to refresh.
            source: Path to the new bytes; defaults to the recorded
                ``source_path`` and then the canonical ``source_uri``.

        Returns:
            An :class:`IngestResult` (``skipped`` when nothing changed).

        Raises:
            UnknownContractError: When the contract does not exist.
        """
        card = await self.catalog.get(contract_id)
        if card is None:
            raise UnknownContractError(contract_id)

        candidate = source or card.source_path or card.source_uri
        path = Path(str(candidate).replace("file://", "", 1))
        return await self.add_contract(path, source_uri=card.source_uri)

    async def apply_amendment_history(
        self,
        amendment_id: str,
        *,
        user: str,
    ) -> Optional[ContractVersion]:
        """Record a verified amendment on its base contract's history.

        Only a *verified* effective date and a resolved parent may create a
        new contractual interval: an unknown effective date stays
        unresolved instead of becoming today.

        Args:
            amendment_id: The amendment's contract id.
            user: Authenticated actor recorded on the base card's write.

        Returns:
            The version appended to the base contract, or ``None`` when the
            preconditions are not met.
        """
        amendment = await self.catalog.get(amendment_id)
        if amendment is None:
            raise UnknownContractError(amendment_id)
        if amendment.contract_type != "amendment" or not amendment.parent_contract_id:
            return None
        provenance = amendment.field_provenance.get("term.effective_date")
        effective = amendment.term.effective_date
        if effective is None or provenance is None or provenance.verification != "verified":
            return None

        base = await self.catalog.get(amendment.parent_contract_id)
        if base is None:
            return None
        history = await self.catalog.versions(base.contract_id)
        if any(version.amended_by == amendment_id for version in history):
            return None

        version = ContractVersion(
            n=(max((item.n for item in history), default=1)) + 1,
            valid_from=effective,
            kind="amendment",
            amended_by=amendment_id,
            source_sha256=base.source_sha256,
            card_snapshot=card_snapshot_payload(base),
            recorded_at=self._now(),
        )
        await self.catalog.upsert(base, expected_revision=base.revision, version=version)
        logger.info(
            "Amendment %s recorded on %s effective %s (actor=%s)",
            amendment_id,
            base.contract_id,
            effective,
            user,
        )
        return version

    async def relate_contracts(
        self,
        contract_ids: Optional[Sequence[str]] = None,
        *,
        force: bool = False,
    ) -> "RelationStageReport":
        """Judge contract relations explicitly (never during retrieval).

        Args:
            contract_ids: Source contracts to judge; ``None`` means the
                whole active catalog.
            force: Re-judge pairs that already carry an active judgement,
                appending a new record and replacing the active result.

        Returns:
            The relation stage's report.
        """
        from .relations import ContractRelationStage  # noqa: PLC0415 - avoid a cycle

        stage = self._relation_stage or ContractRelationStage(
            catalog=self.catalog,
            adapter=self.adapter,
            max_candidates=self.max_candidates,
            now=self._now,
        )
        self._relation_stage = stage
        return await stage.relate(contract_ids, force=force)

    # -- ingestion internals ----------------------------------------------

    async def _allocate_slug(self, path: Path) -> str:
        """Allocate a collision-free slug; SQL uniqueness is the real guard."""
        taken = await self.catalog.taken_slugs()
        base = slugify(path.stem) or "contract"
        return unique_slug(base, set(taken))

    async def _to_markdown(
        self,
        path: Path,
        source_format: SourceFormat,
    ) -> tuple[str, dict[int, int]]:
        """Convert a source document to markdown for indexing.

        Returns:
            ``(markdown, page_hints)`` where ``page_hints`` maps a generated
            section index to its physical page (PDF sources only).
        """
        if source_format == "docx":
            markdown = await docx_to_markdown(path)
            if not _HEADING_RE.search(markdown):
                # No Word heading styles: promote the numbered article
                # captions contracts almost always carry ("1. DEFINITIONS")
                # so the tree gets clause-level sections, and fall back to
                # deterministic sectioning when even those are absent.
                markdown = promote_numbered_headings(markdown)
            if not _HEADING_RE.search(markdown):
                markdown = deterministic_sections(markdown)
            return (markdown, {})
        if source_format == "pdf":
            pages = await self._extract_pdf_pages(path)
            markdown = pdf_markdown(pages)
            hints = {
                index: number
                for index, number in enumerate(
                    (number for number, text in enumerate(pages, start=1) if (text or "").strip()),
                    start=1,
                )
            }
            return markdown, hints

        text = await asyncio.to_thread(path.read_text, "utf-8")
        if source_format == "txt" or not _HEADING_RE.search(text):
            return (deterministic_sections(text), {})
        return (text, {})

    async def _extract_pdf_pages(self, path: Path) -> list[str]:
        """Extract text per PDF page.

        Raises:
            RuntimeError: When no PDF text extractor is installed.
        """

        def _extract() -> list[str]:
            try:
                import pymupdf  # noqa: PLC0415 - optional dependency
            except ImportError:  # pragma: no cover - depends on install extras
                try:
                    import fitz as pymupdf  # noqa: PLC0415
                except ImportError as exc:
                    raise RuntimeError(
                        "Text-PDF ingestion requires pymupdf. Install the PDF extra "
                        "(`pip install 'ai-parrot[pdf]'`)."
                    ) from exc
            with pymupdf.open(str(path)) as document:
                return [page.get_text() or "" for page in document]

        return await asyncio.to_thread(_extract)

    def _resolve_owner(
        self,
        uri: str,
        existing: Optional[ContractCard],
        *,
        path: Optional[Path] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve owner/department, preserving manual overrides.

        A manual override recorded on a previous revision survives later
        ingestion; otherwise the most specific (longest) matching folder
        prefix wins and an unmatched document stays unassigned. Rules may
        be written either as source URIs (``sharepoint://legal/emea``) or as
        local filesystem paths.
        """
        if existing is not None:
            provenance = existing.field_provenance.get("owner_employee_id")
            if provenance is not None and provenance.origin == "manual":
                return existing.owner_employee_id, existing.department
        candidates = {uri}
        if path is not None:
            candidates.add(str(path))
            candidates.add(str(path.resolve()))
        for rule in self.owner_rules:
            if any(candidate.startswith(rule.path_prefix) for candidate in candidates):
                return rule.owner_employee_id, rule.department
        return (None, None)

    async def _ingest(
        self,
        *,
        contract_id: str,
        existing: Optional[ContractCard],
        markdown: str,
        page_hints: dict[int, int],
        path: Path,
        uri: str,
        sha256: str,
        source_format: SourceFormat,
    ) -> IngestResult:
        """Build the staged tree, card it, archive evidence and persist."""
        staging_root = await self.staging.begin(contract_id)
        indexer = self._indexer_factory(staging_root, self.adapter)
        content_store = self._content_store_factory(staging_root)

        try:
            await indexer.create_tree(contract_id, doc_name=path.name)
            await indexer.insert_markdown(contract_id, markdown, doc_name=path.name)
            tree = await indexer.get_tree(contract_id)
        except Exception as exc:  # noqa: BLE001 - staging failures are reported
            logger.warning("Staging failed for %s: %s", contract_id, exc)
            await self.staging.discard(contract_id)
            return IngestResult(outcome="error", reason=f"indexing failed: {exc}", source_uri=uri)

        toc, toc_digest = derive_toc(tree)
        loader = content_store.loader_for(contract_id)
        pages = self._page_map(toc, page_hints)

        try:
            draft = await draft_contract(
                self.adapter,
                filename=path.name,
                toc=toc,
                toc_digest=toc_digest,
                loader=loader,
                max_obligation_sections=self.max_obligation_sections,
            )
            owner, department = self._resolve_owner(uri, existing, path=path)
            candidates = [card for card in await self.catalog.list_cards() if card.contract_id != contract_id]
            now = self._now()
            card = assemble_card(
                draft,
                contract_id=contract_id,
                source_uri=existing.source_uri if existing else uri,
                source_sha256=sha256,
                source_format=source_format,
                today=self._today(),
                toc=toc,
                toc_digest=toc_digest,
                page_count=len(page_hints) or None,
                owner_employee_id=owner,
                department=department,
                party_aliases=await self._alias_map(),
                candidates=candidates,
                added_at=existing.added_at if existing else now,
            )
            for obligation in card.obligations:
                if obligation.page is None and obligation.node_id in pages:
                    obligation.page = pages[obligation.node_id]

            if existing is not None:
                bodies = await load_bodies(loader, [entry.node_id for entry in toc])
                card = merge_verified_fields(existing, card, bodies)

            version_n = 1
            if existing is not None:
                history = await self.catalog.versions(contract_id)
                version_n = (max((item.n for item in history), default=1)) + 1
            evidence_ref = self.evidence.reference(
                contract_id,
                version_n=version_n,
                revision=(existing.revision + 1) if existing else 1,
                source_sha256=sha256,
            )
            await self.evidence.archive_from_loader(
                evidence_ref,
                loader,
                [entry.node_id for entry in toc],
                pages=pages,
                overwrite=True,
            )

            version = ContractVersion(
                n=version_n,
                valid_from=card.term.effective_date,
                kind="original" if existing is None else "restatement",
                source_sha256=sha256,
                card_snapshot=card_snapshot_payload(card),
                evidence_ref=evidence_ref.as_string(),
                recorded_at=now,
            )
            await self._stamp_staging(contract_id, sha256)
            result = await self.catalog.upsert(
                card,
                expected_revision=existing.revision if existing else None,
                version=version,
            )
        except (CatalogError, DuplicateSourceError) as exc:
            await self.staging.discard(contract_id)
            return IngestResult(outcome="error", reason=str(exc), source_uri=uri)
        except Exception as exc:  # noqa: BLE001 - never leave staging behind
            logger.exception("Ingestion failed for %s", contract_id)
            await self.staging.discard(contract_id)
            return IngestResult(outcome="error", reason=f"ingestion failed: {exc}", source_uri=uri)

        try:
            await self.staging.promote(contract_id)
        except EvidenceError as exc:  # pragma: no cover - filesystem failure
            logger.error("Promotion failed for %s: %s", contract_id, exc)
            return IngestResult(outcome="error", reason=f"promotion failed: {exc}", source_uri=uri)

        stored = await self.catalog.get(contract_id) or card
        if self.relate_on_ingest:
            # Judgement at explicit ingest time only — never at retrieval.
            relate_report = await self.relate_contracts([contract_id])
            if relate_report.errors:
                logger.warning("Relation judgement issues for %s: %s", contract_id, relate_report.errors)
        return IngestResult(
            card=stored,
            outcome="added" if result.created else "updated",
            reason="",
            source_uri=uri,
            publication_state="pending" if result.queued else None,
        )

    @staticmethod
    def _page_map(toc: Sequence[Any], page_hints: dict[int, int]) -> dict[str, int]:
        """Map node ids to physical pages from page-anchored section titles."""
        pages: dict[str, int] = {}
        for index, entry in enumerate(toc, start=1):
            match = _PAGE_TITLE_RE.match((entry.title or "").strip())
            if match:
                pages[entry.node_id] = int(match.group(1))
            elif entry.start_page:
                pages[entry.node_id] = int(entry.start_page)
            elif index in page_hints:
                pages[entry.node_id] = page_hints[index]
        return pages

    async def _alias_map(self) -> dict[str, str]:
        """Build ``normalized alias -> canonical party_id`` from the catalog."""
        aliases = await self.catalog.all_party_aliases()
        return {alias: party_id for party_id, values in aliases.items() for alias in values}

    async def _stamp_staging(self, contract_id: str, sha256: str) -> None:
        """Bind a staged tree to the catalog hash before committing the card."""

        def stamp() -> None:
            path = self.staging.staged_tree(contract_id)
            tree = json.loads(path.read_text())
            tree["_contracts_source_sha256"] = sha256
            path.write_text(json.dumps(tree, ensure_ascii=False))

        await asyncio.to_thread(stamp)

    async def _recover_promotion(self, card: ContractCard) -> None:
        """Retry a committed tree promotion, never an uncommitted candidate."""

        def staged_hash() -> Optional[str]:
            path = self.staging.staged_tree(card.contract_id)
            if not path.exists():
                return None
            return json.loads(path.read_text()).get("_contracts_source_sha256")

        if await asyncio.to_thread(staged_hash) == card.source_sha256:
            await self.staging.promote(card.contract_id)

    async def load_section(self, contract_id: str, node_id: str, *, source_sha256: str) -> Optional[str]:
        """Read current source evidence, including trees published before hash markers.

        The immutable archive also stays available if tree promotion failed.
        Its catalog reference binds the body to the requested source version.
        """
        history = sorted(
            await self.catalog.versions(contract_id), key=lambda version: (version.n, version.revision), reverse=True
        )
        for version in history:
            if version.source_sha256 != source_sha256 or not version.evidence_ref:
                continue
            ref = EvidenceRef.parse(version.evidence_ref)
            if (
                ref.tenant_id != self.catalog.tenant_id
                or ref.contract_id != contract_id
                or not source_sha256.startswith(ref.source_sha256)
            ):
                raise EvidenceError("section archive reference does not match the requested source")
            return await self.evidence.load_body(ref, node_id)
        return None

    def published_loader(
        self, contract_id: str, *, source_sha256: Optional[str] = None
    ) -> Callable[[str], Optional[str]]:
        """Return a node-body loader over the *published* tree."""
        if source_sha256 is not None:
            path = self.staging.published_tree(contract_id)
            if not path.exists():
                return lambda node_id: None
            tree = json.loads(path.read_text())
            if tree.get("_contracts_source_sha256") != source_sha256:
                return lambda node_id: None
        store = self._content_store_factory(self.staging.published_root)
        return store.loader_for(contract_id)

    def evidence_reference(
        self,
        contract_id: str,
        *,
        version_n: int,
        revision: int,
        source_sha256: str,
    ) -> EvidenceRef:
        """Build a tenant-bound evidence reference for this library."""
        return self.evidence.reference(
            contract_id,
            version_n=version_n,
            revision=revision,
            source_sha256=source_sha256,
        )


def _default_indexer_factory(storage_dir: Path, adapter: Any) -> TreeIndexer:
    """Build a real :class:`PageIndexToolkit` over ``storage_dir``."""
    from ..pageindex.toolkit import PageIndexToolkit  # noqa: PLC0415 - heavy import

    return PageIndexToolkit(adapter=adapter, storage_dir=storage_dir)
