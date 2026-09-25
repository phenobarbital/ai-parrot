"""ManualLibrary: staged ingest of assembly manuals into cards (FEAT-601 M8)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from ..bookstore.carding import derive_toc, slugify, unique_slug
from ..common.provenance import FieldProvenance
from ..common.validation import load_bodies
from ..pageindex.content_store import NodeContentStore
from ..pageindex.pdf_to_markdown import extract_markdown_per_page
from .carding import SourceInfo, assemble_card, draft_manual
from .catalog import CatalogError, ManualCatalogStore, UnknownManualError, queue_entries_for
from .figures import (CaptioningUnavailable, FigureCandidate, caption_figures, extract_figures, map_callouts,
                      resolve_callout_mapper, resolve_captioner, unpaired_references, upload_figures)
from .graph_loader import ManualGraphLoader
from .models import ManualCard, ManualVersion, MediaRef, SourceFormat, manual_snapshot_payload
from .video import AlignmentReport, JudgementLog, align_video

logger = logging.getLogger(__name__)

#: Suffix used when a page's own text can't supply a preview title.
_PDF_HEADING_PREVIEW_LEN = 60

#: Suffix -> SourceFormat mapping, bounded by the SourceFormat literal (TASK-3699).
_SOURCE_FORMAT_BY_SUFFIX: dict[str, SourceFormat] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImageOnlyManual(ValueError):
    """The PDF has no extractable text (scanned); OCR is out of scope in v1."""


class TreeIndexer(Protocol):
    """The PageIndex surface the library depends on (PageIndexToolkit or a test double)."""

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]: ...
    async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None,
                              doc_name: Optional[str] = None) -> dict[str, Any]: ...
    async def get_tree(self, tree_name: str) -> dict[str, Any]: ...
    async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...


def _default_indexer_factory(storage_dir: Path, adapter: Any) -> TreeIndexer:
    """Build a real PageIndexToolkit over ``storage_dir`` (heavy import kept lazy)."""
    from ..pageindex.toolkit import PageIndexToolkit  # noqa: PLC0415

    return PageIndexToolkit(adapter=adapter, storage_dir=storage_dir)


class IngestResult(BaseModel):
    """Outcome of one ingest/refresh; counts feed the CLI summary and spikes."""

    card: Optional[ManualCard] = None
    status: Literal["created", "updated", "unchanged", "refused"]
    procedures: int = 0
    steps: int = 0
    figures_paired: int = 0
    figures_unpaired: int = 0
    hazards: int = 0
    tips_relinked: int = 0
    tips_orphaned: int = 0
    queue_entries: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _source_format(path: Path) -> SourceFormat:
    """Map the suffix to SourceFormat; unsupported ⇒ ValueError."""
    fmt = _SOURCE_FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"unsupported manual source format: {path.suffix or '(none)'}")
    return fmt


class ManualLibrary:
    """Ingest manuals into the tenant catalog, then publish to the graph."""

    def __init__(self, *, catalog: ManualCatalogStore, storage_root: str | Path, evidence_root: str | Path,
                 adapter: Any = None, file_manager: Any, vision_client: Any | None = None,
                 indexer_factory: Optional[Callable[[Path, Any], TreeIndexer]] = None,
                 graph_loader: Optional[ManualGraphLoader] = None, max_procedure_sections: int = 20,
                 now: Callable[[], datetime] = _utcnow) -> None:
        self.catalog = catalog
        self.storage_root = Path(storage_root)
        self.evidence_root = Path(evidence_root)
        self.adapter = adapter
        self.file_manager = file_manager
        self.vision_client = vision_client
        self.graph_loader = graph_loader
        self.max_procedure_sections = max_procedure_sections
        self._indexer_factory = indexer_factory or _default_indexer_factory
        self._now = now
        self.logger = logging.getLogger(__name__)

    async def add_manual(self, source: str | Path, *, equipment: Sequence[str], revision: str,
                         source_uri: Optional[str] = None, force: bool = False) -> IngestResult:
        """sha dedup → markdown → staged tree → carding → figures → assemble → upsert → publish."""
        path = Path(source)
        if not await asyncio.to_thread(path.is_file):
            return IngestResult(status="refused", warnings=[f"source not found: {path}"])
        payload = await asyncio.to_thread(path.read_bytes)
        sha256 = hashlib.sha256(payload).hexdigest()

        existing: Optional[ManualCard] = None
        if source_uri:
            existing = await self.catalog.find_by_source_uri(source_uri)
        if existing is None:
            existing = await self.catalog.find_by_sha(sha256)
        if existing is not None and existing.source_sha256 == sha256 and not force:
            return IngestResult(card=existing, status="unchanged")

        if existing is not None:
            manual_id = existing.manual_id
        else:
            if not equipment:
                raise ValueError("equipment is required to allocate a manual_id")
            base = slugify(f"{equipment[0]} {revision}")
            if not base or base == "book":
                raise ValueError(
                    "equipment/revision produced an empty slug (non-Latin title collapses); "
                    "pass an explicit slug"
                )
            taken = {card.manual_id for card in await self.catalog.list_cards(active_only=False)}
            manual_id = unique_slug(base, taken)

        return await self._ingest(
            path,
            manual_id=manual_id,
            equipment=equipment,
            revision=revision,
            source_uri=source_uri,
            sha256=sha256,
            previous=existing,
        )

    async def add_folder(self, folder: str | Path, *, recursive: bool = False, force: bool = False) -> list[IngestResult]:
        """Ingest every supported file; equipment/revision come from a sidecar `<file>.manual.json`."""
        base = Path(folder)
        if not await asyncio.to_thread(base.is_dir):
            return [IngestResult(status="refused", warnings=[f"not a folder: {base}"])]

        def _walk() -> list[Path]:
            pattern = "**/*" if recursive else "*"
            return sorted(
                candidate
                for candidate in base.glob(pattern)
                if candidate.is_file() and candidate.suffix.lower() in _SOURCE_FORMAT_BY_SUFFIX
            )

        paths = await asyncio.to_thread(_walk)
        results: list[IngestResult] = []
        for candidate in paths:
            sidecar = candidate.with_suffix(f"{candidate.suffix}.manual.json")
            if not sidecar.is_file():
                results.append(IngestResult(status="refused", warnings=[f"missing sidecar metadata: {sidecar.name}"]))
                continue
            try:
                raw = await asyncio.to_thread(sidecar.read_text, "utf-8")
                payload = json.loads(raw)
                equipment = [str(value) for value in payload["equipment"]]
                revision = str(payload["revision"])
            except Exception as exc:  # noqa: BLE001 - a bad sidecar is a per-file refusal, not fatal
                results.append(IngestResult(status="refused", warnings=[f"invalid sidecar metadata: {exc}"]))
                continue
            results.append(await self.add_manual(candidate, equipment=equipment, revision=revision, force=force))
        return results

    async def add_video(self, manual_id: str, *, uri: str, transcript: Mapping[str, Any] | None = None,
                        local_path: Optional[Path] = None, force: bool = False) -> AlignmentReport:
        """align_video over the stored card; persist segments with expected_revision; judgement log under storage_root."""
        del local_path  # v1: automatic transcription is not wired (see Completion Note deviation)
        card = await self.catalog.get(manual_id)
        if card is None:
            raise UnknownManualError(manual_id)
        if transcript is None:
            raise RuntimeError(
                "add_video requires an explicit transcript in v1; automatic transcription via "
                "parrot_loaders is not wired up yet"
            )
        judgement_log = JudgementLog(self.storage_root / "_video_judgements" / f"{manual_id}.json")
        media_refs, media_links, report = await align_video(
            card,
            uri=uri,
            transcript=transcript,
            adapter=self.adapter,
            judgement_log=judgement_log,
            force=force,
        )
        steps_by_id = {step.identity.step_id: step for procedure in card.procedures for step in procedure.steps}
        procedure_ids = {procedure.procedure_id for procedure in card.procedures}
        for ref, link in zip(media_refs, media_links, strict=True):
            step = steps_by_id.get(ref.label) if ref.label else None
            if step is not None:
                step.media.append(link)
            elif ref.label not in procedure_ids:
                self.logger.warning(
                    "add_video: media %s references an unknown step or procedure %r", ref.media_id, ref.label
                )
            card.figures.append(ref)
        await self.catalog.upsert(card, expected_revision=None)
        return report

    async def refresh(self, manual_id: str, source: str | Path, *, revision: str) -> IngestResult:
        """New revision: append ManualVersion, carry forward step identities, publish, relink."""
        previous = await self.catalog.get(manual_id)
        if previous is None:
            raise UnknownManualError(manual_id)
        path = Path(source)
        if not await asyncio.to_thread(path.is_file):
            return IngestResult(status="refused", warnings=[f"source not found: {path}"])
        payload = await asyncio.to_thread(path.read_bytes)
        sha256 = hashlib.sha256(payload).hexdigest()
        equipment = [reference.model for reference in previous.equipment] or [revision]
        return await self._ingest(
            path,
            manual_id=manual_id,
            equipment=equipment,
            revision=revision,
            source_uri=previous.source_uri,
            sha256=sha256,
            previous=previous,
        )

    async def verify_procedure(self, manual_id: str, procedure_id: str, *, user: str,
                               expected_revision: Optional[int] = None) -> ManualCard:
        """Flip verification → verified (verified_by/at) and freeze the current ManualVersion."""
        card = await self.catalog.get(manual_id)
        if card is None:
            raise UnknownManualError(manual_id)
        procedure = next((item for item in card.procedures if item.procedure_id == procedure_id), None)
        if procedure is None:
            raise ValueError(f"unknown procedure {procedure_id!r} on manual {manual_id!r}")

        now = self._now()
        updated_procedure = procedure.model_copy(update={"verification": "verified"})
        procedures = [updated_procedure if item.procedure_id == procedure_id else item for item in card.procedures]
        provenance = dict(card.field_provenance)
        provenance[f"procedures.{procedure.slug}.verification"] = FieldProvenance(
            origin="manual",
            verification="verified",
            verified_by=user,
            verified_at=now,
        )
        card = card.model_copy(
            update={"procedures": procedures, "field_provenance": provenance, "verification": "verified"}
        )
        await self.catalog.upsert(card, expected_revision=expected_revision)
        return await self.catalog.get(manual_id) or card

    async def load_section(self, manual_id: str, node_id: str, *, version_n: int) -> Optional[str]:
        """Body of ``node_id`` in the archived snapshot of ``version_n`` (read by ProcedureVerifier)."""
        path = self.evidence_root / self.catalog.tenant_id / manual_id / f"v{version_n}" / "sections.json"

        def _read() -> Optional[str]:
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            value = payload.get(node_id) if isinstance(payload, dict) else None
            return value if isinstance(value, str) else None

        return await asyncio.to_thread(_read)

    async def _ingest(self, path: Path, *, manual_id: str, equipment: Sequence[str], revision: str,
                      source_uri: Optional[str], sha256: str, previous: Optional[ManualCard]) -> IngestResult:
        """Shared pipeline; deletes the staged tree and returns 'refused' on any failure."""
        try:
            source_format = _source_format(path)
        except ValueError as exc:
            return IngestResult(status="refused", warnings=[str(exc)])

        work_dir = self.storage_root / "_work" / manual_id
        images_dir = work_dir / "markdown_images"
        figures_dir = work_dir / "figures"

        try:
            markdown, page_hints = await self._to_markdown(path, source_format, images_dir=images_dir)
        except ImageOnlyManual as exc:
            return IngestResult(status="refused", warnings=[str(exc)])
        except Exception as exc:  # noqa: BLE001 - conversion failures are data errors, not bugs
            self.logger.warning("Conversion failed for %s: %s", path, exc)
            return IngestResult(status="refused", warnings=[f"conversion failed: {exc}"])

        if not markdown.strip():
            return IngestResult(status="refused", warnings=["document has no readable content"])

        indexer = self._indexer_factory(self.storage_root, self.adapter)
        try:
            await indexer.create_tree(manual_id, doc_name=path.name)
        except Exception as exc:  # noqa: BLE001 - staging failures are reported, never raised
            return IngestResult(status="refused", warnings=[f"tree creation failed: {exc}"])

        warnings: list[str] = []
        try:
            await indexer.insert_markdown(manual_id, markdown, doc_name=path.name)
            tree = await indexer.get_tree(manual_id)
            toc, toc_digest = derive_toc(tree)

            content_store = NodeContentStore(self.storage_root)
            loader = content_store.loader_for(manual_id)
            bodies = await load_bodies(loader, [entry.node_id for entry in toc])
            page_map = {
                entry.node_id: page_hints[index] for index, entry in enumerate(toc, start=1) if index in page_hints
            }

            draft = await draft_manual(
                self.adapter,
                filename=path.name,
                toc=toc,
                toc_digest=toc_digest,
                loader=loader,
                max_procedure_sections=self.max_procedure_sections,
            )
            warnings.extend(draft.warnings)
            all_step_drafts = [step for procedure in draft.procedures for step in procedure.steps]

            figure_candidates: list[FigureCandidate] = []
            if source_format == "pdf":
                pages = await asyncio.to_thread(extract_markdown_per_page, path, images_dir=images_dir)
                page_texts = dict(pages)
                figure_candidates = await asyncio.to_thread(
                    extract_figures, path, figures_dir, page_texts=page_texts
                )

            if figure_candidates:
                try:
                    captioner = resolve_captioner(self.vision_client)
                except CaptioningUnavailable as exc:
                    warnings.append(f"captioning unavailable: {exc}")
                else:
                    figure_candidates = await caption_figures(figure_candidates, captioner)

            media_refs: list[MediaRef] = []
            if figure_candidates:
                media_refs = await upload_figures(figure_candidates, self.file_manager, prefix=f"manuals/{manual_id}")

                callout_mapper = None
                try:
                    callout_mapper = resolve_callout_mapper(self.vision_client)
                except CaptioningUnavailable:
                    callout_mapper = None
                if callout_mapper is not None:
                    for index, (candidate, ref) in enumerate(zip(figure_candidates, media_refs, strict=True)):
                        # One structured call per exploded view (map_callouts gates on
                        # PARROT_MANUALS_CALLOUTS internally); global_parts only exist after
                        # assemble_card, so v1 resolves callouts against an empty part pool —
                        # any recognized callout is queued unresolved rather than guessed
                        # (documented deviation, AC21 remains off by default).
                        links, unresolved = await map_callouts(
                            [candidate],
                            callout_mapper,
                            parts=[],
                            steps=all_step_drafts,
                            media_ids={candidate.image.sha256: ref.media_id},
                        )
                        if links or unresolved:
                            media_refs[index] = ref.model_copy(update={"callouts": links, "unresolved_callouts": unresolved})

            source_info = SourceInfo(
                source_uri=source_uri,
                source_sha256=sha256,
                source_format=source_format,
                revision=revision,
                equipment=list(equipment),
                toc=toc,
                toc_digest=toc_digest,
                page_count=len(page_hints),
                figure_candidates=figure_candidates,
                previous_card=previous,
            )
            card = assemble_card(
                draft,
                manual_id=manual_id,
                source=source_info,
                figures=media_refs,
                page_map=page_map,
                now=self._now(),
            )
        except Exception as exc:  # noqa: BLE001 - never leave a staged tree behind
            self.logger.exception("Ingestion failed for %s", manual_id)
            await indexer.delete_tree(manual_id)
            return IngestResult(status="refused", warnings=[f"ingestion failed: {exc}"])

        history = await self.catalog.versions(manual_id)
        version_n = (max((version.n for version in history), default=0)) + 1
        today = self._now().date()
        evidence_ref = await asyncio.to_thread(self._write_evidence, manual_id, version_n, bodies, path)
        version = ManualVersion(
            n=version_n,
            revision=revision,
            valid_from=today,
            valid_to=None,
            source_sha256=sha256,
            card_snapshot=manual_snapshot_payload(card),
            recorded_at=self._now(),
            evidence_ref=evidence_ref,
        )
        try:
            await self.catalog.upsert(card, version=version)
        except CatalogError as exc:
            await indexer.delete_tree(manual_id)
            return IngestResult(status="refused", warnings=[str(exc)])

        stored = await self.catalog.get(manual_id) or card

        tips_relinked = tips_orphaned = 0
        if self.graph_loader is not None:
            publish_report = await self.graph_loader.publish(stored)
            warnings.extend(publish_report.errors)
            if publish_report.tip_relink is not None:
                tips_relinked = len(publish_report.tip_relink.relinked)
                tips_orphaned = len(publish_report.tip_relink.orphaned)

        # unpaired_references() normalizes both sides of the label comparison (pair_figures'
        # own rule); queue_entries_for() compares a step's raw citation text ("Fig. 1") against
        # the card's normalized figure labels ("1") and would otherwise over-report unpaired
        # figures that were, in fact, successfully linked.
        figures_unpaired = len(unpaired_references(all_step_drafts, figure_candidates))
        queue_entries = [f"{entry.reason}:{item}" for entry in queue_entries_for(stored) for item in entry.items]

        return IngestResult(
            card=stored,
            status="created" if previous is None else "updated",
            procedures=len(stored.procedures),
            steps=sum(len(procedure.steps) for procedure in stored.procedures),
            figures_paired=sum(len(step.media) for procedure in stored.procedures for step in procedure.steps),
            figures_unpaired=figures_unpaired,
            hazards=len(stored.global_hazards),
            tips_relinked=tips_relinked,
            tips_orphaned=tips_orphaned,
            queue_entries=queue_entries,
            warnings=warnings,
        )

    async def _to_markdown(self, path: Path, source_format: SourceFormat, *, images_dir: Path) -> tuple[str, dict[int, int]]:
        """PDF via extract_markdown_per_page(images_dir=…) as '## Page N'; DOCX via docx_to_markdown; image-only ⇒ ImageOnlyManual."""
        if source_format == "pdf":
            all_empty = await asyncio.to_thread(self._pdf_all_pages_textless, path)
            if all_empty:
                raise ImageOnlyManual(f"{path.name}: no extractable text (scanned PDF; OCR is out of scope)")
            pages = await asyncio.to_thread(extract_markdown_per_page, path, images_dir=images_dir)
            sections: list[str] = []
            hints: dict[int, int] = {}
            index = 0
            for page_number, text in pages:
                if not (text or "").strip():
                    continue
                index += 1
                hints[index] = page_number
                heading = self._page_heading(page_number, text)
                sections.append(f"{heading}\n\n{text}\n")
            return ("\n\n".join(sections), hints)

        if source_format == "docx":
            from ..bookstore.library import docx_to_markdown  # noqa: PLC0415 - avoid a hard bookstore dependency

            markdown = await docx_to_markdown(path)
            return (markdown, {})

        text = await asyncio.to_thread(path.read_text, "utf-8")
        return (text, {})

    @staticmethod
    def _page_heading(page_number: int, text: str) -> str:
        """Build a per-page heading carrying a content preview so ToC titles are meaningful."""
        for line in text.splitlines():
            candidate = line.strip()
            if candidate:
                preview = candidate[:_PDF_HEADING_PREVIEW_LEN].strip()
                return f"## Page {page_number}: {preview}"
        return f"## Page {page_number}"

    @staticmethod
    def _pdf_all_pages_textless(path: Path) -> bool:
        """Return whether every physical page has no extractable text (F013, scanned-PDF refusal).

        Mirrors ``parrot_loaders.pdf.PDFLoader.is_image_only``'s text check, but is decided over
        the whole document rather than per page: a manual with at least one readable page is
        never refused, even when other pages are pure raster scans.
        """
        import pymupdf  # noqa: PLC0415 - optional dependency, mirrors parrot_loaders.pdf.is_image_only

        document = pymupdf.open(str(path))
        try:
            return all(not page.get_text().strip() for page in document)
        finally:
            document.close()

    def _write_evidence(self, manual_id: str, version_n: int, bodies: Mapping[str, str], source: Path) -> str:
        """Write <evidence_root>/<tenant>/<manual_id>/v<n>/sections.json + source copy; return the evidence_ref path."""
        directory = self.evidence_root / self.catalog.tenant_id / manual_id / f"v{version_n}"
        directory.mkdir(parents=True, exist_ok=True)
        sections_path = directory / "sections.json"
        sections_path.write_text(json.dumps(dict(bodies), ensure_ascii=False, indent=2), encoding="utf-8")
        destination = directory / f"source{source.suffix}"
        shutil.copy2(source, destination)
        return str(sections_path)
