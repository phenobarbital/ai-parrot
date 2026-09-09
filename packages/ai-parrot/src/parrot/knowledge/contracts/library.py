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
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from ..bookstore.carding import derive_toc
from ..bookstore.library import docx_to_markdown
from ..pageindex.content_store import NodeContentStore
from .carding import (
    DEFAULT_MAX_OBLIGATION_SECTIONS,
    assemble_card,
    draft_contract,
    slugify,
    unique_slug,
)
from .catalog import CatalogError, ContractCatalogStore, DuplicateSourceError
from .evidence import EvidenceArchive, EvidenceError, EvidenceRef, StagingArea
from .models import (
    ContractCard,
    ContractVersion,
    IngestItemReport,
    IngestReport,
    IngestResult,
    SourceFormat,
    card_snapshot_payload,
)

__all__ = (
    "SUPPORTED_FORMATS",
    "TreeIndexer",
    "OwnerRule",
    "ContractLibrary",
    "deterministic_sections",
    "pdf_markdown",
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


class TreeIndexer(Protocol):
    """The PageIndex surface the library depends on.

    Satisfied by :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit`
    and by test doubles.
    """

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]:
        ...

    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: Optional[str] = None,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]:
        ...

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        ...

    async def delete_tree(self, tree_name: str) -> dict[str, Any]:
        ...


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
        f"## {title_prefix} {index + 1}\n\n" + "\n\n".join(block)
        for index, block in enumerate(sections)
        if block
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
        f"## Page {number}\n\n{text.strip()}"
        for number, text in enumerate(pages, start=1)
        if (text or "").strip()
    ]
    return "\n\n".join(chunks)


def _utcnow() -> datetime:
    """Current UTC time (injectable for frozen-clock tests)."""
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    """Current UTC date (injectable for frozen-clock tests)."""
    return datetime.now(tz=timezone.utc).date()


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
        now: Callable[[], datetime] = _utcnow,
        today: Callable[[], date] = _today,
    ) -> None:
        self.catalog = catalog
        self.adapter = adapter
        self.staging = StagingArea(storage_root, tenant_id=catalog.tenant_id)
        self.evidence = EvidenceArchive(evidence_root, tenant_id=catalog.tenant_id)
        self.owner_rules = sorted(owner_rules, key=lambda rule: -len(rule.path_prefix))
        self.max_obligation_sections = max_obligation_sections
        self._indexer_factory = indexer_factory or _default_indexer_factory
        self._content_store_factory = content_store_factory or NodeContentStore
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
            return IngestResult(
                outcome="error", reason=f"source not found: {path}", source_uri=uri
            )

        try:
            payload = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            return IngestResult(
                outcome="error", reason=f"unreadable source: {exc}", source_uri=uri
            )
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
            return (await docx_to_markdown(path), {})
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
            return IngestResult(
                outcome="error", reason=f"indexing failed: {exc}", source_uri=uri
            )

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
            candidates = [
                card for card in await self.catalog.list_cards() if card.contract_id != contract_id
            ]
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
            return IngestResult(
                outcome="error", reason=f"ingestion failed: {exc}", source_uri=uri
            )

        try:
            await self.staging.promote(contract_id)
        except EvidenceError as exc:  # pragma: no cover - filesystem failure
            logger.error("Promotion failed for %s: %s", contract_id, exc)
            return IngestResult(
                outcome="error", reason=f"promotion failed: {exc}", source_uri=uri
            )

        stored = await self.catalog.get(contract_id) or card
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
        return {
            alias: party_id for party_id, values in aliases.items() for alias in values
        }

    def published_loader(self, contract_id: str) -> Callable[[str], Optional[str]]:
        """Return a node-body loader over the *published* tree."""
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
