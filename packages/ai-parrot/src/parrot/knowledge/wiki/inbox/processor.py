"""Crash-safe autonomous inbox processing with one asynchronous lock owner."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
import logging
from pathlib import Path
import re
import time

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.charter import Charter
from parrot.knowledge.wiki.documents import (
    AcquiredDocument,
    DocumentAcquirer,
    DocumentAcquisitionError,
    DocumentRef,
    resolve_sources,
)
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
from parrot.knowledge.wiki.inbox.archive import archive_destination, archive_original, repoint_source
from parrot.knowledge.wiki.inbox.classify import InboxClassifier, slugify_doc_id
from parrot.knowledge.wiki.inbox.links import LinkProposer
from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport
from parrot.knowledge.wiki.inbox.pages import DocPageWriter
from parrot.knowledge.wiki.inbox.projection import write_doc_markdown, write_inbox_index
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiConfigError, WikiProjectConfig, validate_inbox_paths, wiki_write_lock
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.triage import IngestTriageRouter

_FIREFLIES_RE = re.compile(r"\bfireflies(?:[_-]?id)?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)", re.IGNORECASE)
_LOCK_POLL_SECONDS = 0.05


class InboxRuntime(BaseModel):
    """Frozen service bindings for a single processing run."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    root: Path
    config: WikiProjectConfig
    wiki_config: WikiConfig
    charter: Charter
    store: BaseWikiStore
    sources: SourceCollectionManager
    bookkeeper: WikiBookkeeper
    acquirer: DocumentAcquirer
    router: IngestTriageRouter
    orchestrator: WikiIngestOrchestrator
    light_adapter: PageIndexLLMAdapter
    heavy_adapter: PageIndexLLMAdapter
    search: WikiCombinedSearch
    models: dict[str, str]


class InboxLockBusy(RuntimeError):
    """The whole-run writer lock could not be acquired before its deadline."""


async def _close_lock(context: object, exc_type: object = None, exc: object = None, tb: object = None) -> None:
    """Close a synchronous lock context without blocking the event loop."""
    await asyncio.shield(asyncio.to_thread(context.__exit__, exc_type, exc, tb))  # type: ignore[attr-defined]


@asynccontextmanager
async def _inbox_write_lock(storage_path: Path, timeout: float) -> AsyncIterator[None]:
    """Acquire a nonblocking writer lock and retain it for the caller's run.

    Each synchronous lock attempt is performed off-loop.  In particular, a
    cancellation that races a successful attempt waits for the attempt and
    releases the descriptor before cancellation is propagated.
    """
    deadline = time.monotonic() + max(timeout, 0.0)
    acquired_context: object | None = None
    while True:
        context = wiki_write_lock(storage_path, timeout=0)
        enter_task = asyncio.create_task(asyncio.to_thread(context.__enter__))
        try:
            acquired = await asyncio.shield(enter_task)
        except asyncio.CancelledError:
            try:
                entered = await enter_task
                if entered:
                    await _close_lock(context, asyncio.CancelledError, None, None)
                else:
                    await _close_lock(context)
            except BaseException:
                # Cleanup must not hide the original cancellation.
                pass
            raise
        if acquired:
            acquired_context = context
            break
        await _close_lock(context)
        if timeout <= 0 or time.monotonic() >= deadline:
            raise InboxLockBusy(f"Inbox write lock is busy: {storage_path}")
        await asyncio.sleep(min(_LOCK_POLL_SECONDS, max(0.0, deadline - time.monotonic())))

    try:
        yield
    finally:
        if acquired_context is not None:
            close_task = asyncio.create_task(_close_lock(acquired_context))
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                await close_task
                raise


def detect_fireflies_id(acquired: AcquiredDocument) -> str | None:
    """Find a ``fireflies:<id>`` external identity in metadata or text."""
    values = [acquired.text]
    for key, value in acquired.metadata.extra.items():
        values.append(f"{key}:{value}")
        if str(key).lower() in {"fireflies", "fireflies_id", "fireflies-id"} and str(value).strip():
            return f"fireflies:{str(value).strip()}"
    for value in values:
        match = _FIREFLIES_RE.search(str(value))
        if match:
            return f"fireflies:{match.group(1)}"
    return None


class InboxProcessor:
    """Compose the ordered per-document pipeline under one whole-run lock."""

    def __init__(self, runtime: InboxRuntime, *, today: date | None = None) -> None:
        """Bind runtime and validate resolved directories before writes."""
        self.runtime = runtime
        self.today = today or date.today()
        self.logger = logging.getLogger(__name__)
        self.storage_path = runtime.config.storage_path(runtime.root)
        self.inbox_dir = runtime.config.inbox_path(runtime.root)
        self.archive_dir = runtime.config.archive_path(runtime.root)
        self.markdown_dir = runtime.config.inbox_markdown_path(runtime.root)
        validate_inbox_paths(runtime.root, self.inbox_dir, self.archive_dir, self.markdown_dir)
        self.classifier = InboxClassifier(runtime.light_adapter, runtime.charter.taxonomy)
        self.links = LinkProposer(
            runtime.store, runtime.search, runtime.heavy_adapter, max_candidates=runtime.config.inbox.max_candidates
        )
        self.pages = DocPageWriter(runtime.store, runtime.sources, runtime.bookkeeper, self.storage_path)
        self._discovery_results: list[InboxDocResult] = []

    def discover(self, *, limit: int | None) -> list[DocumentRef]:
        """Discover safe originals, record skips, sort and apply the limit."""
        if limit is not None and limit < 0:
            raise ValueError("limit must be nonnegative")
        discovered: list[tuple[float, str, DocumentRef]] = []
        self._discovery_results = []
        if not self.inbox_dir.exists():
            return []
        root = self.runtime.root.resolve()
        for entry in self.inbox_dir.iterdir():
            if entry.name.startswith("."):
                continue
            try:
                resolved = entry.resolve(strict=True)
                if (
                    entry.is_symlink()
                    or not resolved.is_relative_to(self.inbox_dir.resolve())
                    or not resolved.is_relative_to(root)
                ):
                    raise ValueError("unsafe inbox path")
                if not resolved.is_file():
                    continue
                refs = resolve_sources(str(entry), recursive=False)
                for ref in refs:
                    discovered.append((resolved.stat().st_mtime, resolved.name, ref))
            except (OSError, ValueError) as exc:
                self._discovery_results.append(
                    InboxDocResult(source_uri=str(entry), status="skipped", error=f"unsafe source: {exc}")
                )
        discovered.sort(key=lambda item: (item[0], item[1]))
        refs = [item[2] for item in discovered]
        return refs if limit is None else refs[:limit]

    async def run(
        self, *, dry_run: bool = False, limit: int | None = None, force: bool = False, archive: bool = True
    ) -> InboxRunReport:
        """Hold the sole writer lock while processing isolated document outcomes."""
        async with _inbox_write_lock(self.storage_path, self.runtime.config.inbox.lock_timeout):
            refs = await asyncio.to_thread(self.discover, limit=limit)
            results = list(self._discovery_results)
            for ref in refs:
                try:
                    results.append(await self.process_one(ref, dry_run=dry_run, force=force, archive=archive))
                except asyncio.CancelledError:
                    raise
                except DocumentAcquisitionError as exc:
                    results.append(InboxDocResult(source_uri=ref.uri, status="skipped", error=str(exc)))
                except Exception as exc:  # noqa: BLE001 - isolate document failures
                    self.logger.exception("Inbox processing failed for %s", ref.uri)
                    results.append(InboxDocResult(source_uri=ref.uri, status="failed", error=str(exc)))
            if not dry_run:
                await asyncio.to_thread(
                    self.runtime.bookkeeper.log_operation,
                    self.storage_path,
                    "INBOX_RUN",
                    f"processed {len(results)} documents",
                )
            counts: dict[str, int] = {}
            for result in results:
                counts[result.status] = counts.get(result.status, 0) + 1
            return InboxRunReport(
                inbox_dir=str(self.inbox_dir),
                charter_version=self.runtime.charter.version,
                charter_fingerprint=self.runtime.charter.fingerprint,
                models=dict(self.runtime.models),
                dry_run=dry_run,
                counts=counts,
                documents=results,
            )

    async def _existing_doc_id(self, source_uri: str, external_id: str | None) -> tuple[str | None, str | None]:
        """Recover source and authored document identities before generating a slug."""
        entry = await asyncio.to_thread(self.runtime.sources.find_by_external_id, external_id) if external_id else None
        if entry is None:
            source_id = await asyncio.to_thread(self.runtime.sources.find_by_uri, source_uri)
            entry = await asyncio.to_thread(self.runtime.sources.get_source, source_id) if source_id else None
        if entry is not None:
            extra = (entry.doc_metadata or {}).get("extra") or {}
            if isinstance(extra, dict) and isinstance(extra.get("inbox_doc_id"), str):
                return entry.source_id, extra["inbox_doc_id"]
            source_id = entry.source_id
        else:
            source_id = None
        for page in await self.runtime.store.dump_pages():
            if page.get("origin") != "authored":
                continue
            body = str(page.get("body") or "")
            if source_uri in body or (source_id and source_id in body):
                return source_id, str(page.get("concept_id") or "") or None
        return source_id, None

    async def process_one(self, ref: DocumentRef, *, dry_run: bool, force: bool, archive: bool) -> InboxDocResult:
        """Run acquire/triage/classify/link/persist/project/verify/archive in order."""
        original = Path(ref.uri)
        acquired = await self.runtime.acquirer.acquire(ref)
        fireflies_id = detect_fireflies_id(acquired)
        known_source_id, existing_doc_id = await self._existing_doc_id(str(original.resolve()), fireflies_id)
        if known_source_id and fireflies_id and not dry_run:
            await asyncio.to_thread(repoint_source, self.runtime.sources, known_source_id, original)
        triage = await self.runtime.router.triage(original, acquired.text, skip_duplicate_check=force)
        if triage.decision_source != "heuristic":
            triage = triage.model_copy(update={"decision": triage.proposed_action, "decision_source": "auto"})
        decision = triage.decision or triage.proposed_action
        base = dict(
            source_uri=ref.uri,
            decision=decision,
            composite=triage.composite,
            decision_source=triage.decision_source,
            fireflies_match=fireflies_id,
        )
        if dry_run:
            if decision != "discard":
                classification = await self.classifier.classify(acquired, triage)
                doc_id = existing_doc_id or slugify_doc_id(classification.title, triage.file_hash)
                source = (
                    await asyncio.to_thread(self.runtime.sources.get_source, known_source_id)
                    if known_source_id
                    else None
                )
                children = list(source.pages_generated) if source else []
                candidates = await self.links.candidates(
                    acquired.text, classification, triage.claims, {doc_id, *children}
                )
                links = await self.links.select(acquired.text, classification, candidates)
                base.update(
                    kind=classification.kind,
                    category=classification.category,
                    tags=classification.tags,
                    links=links,
                    doc_page_id=doc_id,
                )
            await asyncio.to_thread(self.runtime.bookkeeper.log_operation, self.storage_path, "DRY_RUN", ref.uri)
            return InboxDocResult(status="dry_run", **base)

        report = await self.runtime.orchestrator.ingest(
            ref.uri,
            self.runtime.wiki_config,
            triage=triage,
            charter_version=self.runtime.charter.version,
            acquired=acquired,
        )
        if report.status != "ok":
            raise RuntimeError(report.error or "ingest failed")
        source = await asyncio.to_thread(self.runtime.sources.get_source, report.source_id)
        if source is None:
            raise RuntimeError("ingest did not persist a source manifest")
        if decision == "discard":
            problems = (
                [] if source.destination == "discard" and source.status == "rejected" else ["discard manifest missing"]
            )
            if archive and not problems:
                await self._archive(original, report.source_id, source, rejected=True)
            return InboxDocResult(status="rejected", verified=False, **base, error="; ".join(problems) or None)

        classification = await self.classifier.classify(acquired, triage)
        doc_id = (
            existing_doc_id
            or await self._doc_id_from_source(source)
            or slugify_doc_id(classification.title, triage.file_hash)
        )
        candidates = await self.links.candidates(
            acquired.text, classification, triage.claims, {doc_id, *source.pages_generated}
        )
        links = await self.links.select(acquired.text, classification, candidates)
        await self.pages.write_doc_page(
            doc_id,
            report.source_id,
            classification,
            acquired,
            triage,
            self.runtime.charter.version,
            links,
            decision == "archive",
        )
        page = await self.runtime.store.get_page(doc_id)
        if page is None:
            raise RuntimeError("document page was not persisted")
        markdown = await asyncio.to_thread(
            write_doc_markdown, self.markdown_dir, page, [link.model_dump() for link in links], classification.tags
        )
        authored = [row for row in await self.runtime.store.dump_pages() if row.get("origin") == "authored"]
        await asyncio.to_thread(write_inbox_index, self.markdown_dir, authored)
        adr_id, adr_reused = await self.pages.emit_adr_candidate(
            doc_id, classification, acquired, str(markdown.relative_to(self.runtime.root)), self.runtime.config
        )
        await self._persist_doc_id(report.source_id, acquired, doc_id)
        problems = await self.verify_persisted(report.source_id, doc_id, markdown, decision)
        if problems:
            return InboxDocResult(
                status="failed",
                verified=False,
                **base,
                kind=classification.kind,
                category=classification.category,
                error="; ".join(problems),
            )
        archived_to = None
        if archive:
            archived_to = await self._archive(original, report.source_id, source, rejected=False)
        return InboxDocResult(
            status="archived_category" if decision == "archive" else "admitted",
            verified=True,
            **base,
            kind=classification.kind,
            category=classification.category,
            tags=classification.tags,
            links=links,
            doc_page_id=doc_id,
            markdown_path=str(markdown),
            archived_to=archived_to,
            adr_candidate_id=adr_id,
            adr_candidate_reused=adr_reused,
        )

    async def _doc_id_from_source(self, source: object) -> str | None:
        """Read a persisted inbox document identity from manifest metadata."""
        metadata = getattr(source, "doc_metadata", None) or {}
        extra = metadata.get("extra") if isinstance(metadata, dict) else None
        return (
            extra.get("inbox_doc_id")
            if isinstance(extra, dict) and isinstance(extra.get("inbox_doc_id"), str)
            else None
        )

    async def _persist_doc_id(self, source_id: str, acquired: AcquiredDocument, doc_id: str) -> None:
        """Merge the inbox identity into source metadata after ingestion replaced it."""
        source = await asyncio.to_thread(self.runtime.sources.get_source, source_id)
        metadata = dict(source.doc_metadata or {}) if source else acquired.metadata.model_dump()
        extra = dict(metadata.get("extra") or {})
        extra["inbox_doc_id"] = doc_id
        metadata["extra"] = extra
        await asyncio.to_thread(
            self.runtime.sources.record_document_metadata,
            source_id,
            doc_metadata=metadata,
            content_type=acquired.metadata.content_type,
            loader=acquired.metadata.loader,
        )

    async def _archive(self, original: Path, source_id: str, source: object, *, rejected: bool) -> str:
        """Recheck containment, archive an original and merge archive provenance."""
        resolved = original.resolve(strict=True)
        if not resolved.is_relative_to(self.inbox_dir.resolve()):
            raise WikiConfigError(f"inbox source escaped before archive: {original}")
        destination = await asyncio.to_thread(
            archive_destination,
            self.archive_dir,
            original,
            rejected=rejected,
            rejected_subdir=self.runtime.config.inbox.rejected_subdir,
            date_format=self.runtime.config.inbox.date_format,
            today=self.today,
        )
        result = await asyncio.to_thread(
            archive_original, self.runtime.root, original, destination, stage_git=self.runtime.config.inbox.stage_git
        )
        await asyncio.to_thread(repoint_source, self.runtime.sources, source_id, result.destination)
        current = await asyncio.to_thread(self.runtime.sources.get_source, source_id)
        metadata = dict(getattr(current, "doc_metadata", None) or {})
        extra = dict(metadata.get("extra") or {})
        extra.update({"archived_to": str(result.destination), "archived_at": self.today.isoformat()})
        metadata["extra"] = extra
        await asyncio.to_thread(
            self.runtime.sources.record_document_metadata,
            source_id,
            doc_metadata=metadata,
            content_type=metadata.get("content_type"),
            loader=metadata.get("loader"),
        )
        await asyncio.to_thread(
            self.runtime.bookkeeper.log_operation, self.storage_path, "INBOX_ARCHIVE", str(result.destination)
        )
        return str(result.destination)

    async def verify_persisted(
        self, source_id: str, doc_id: str, markdown_path: Path, expected_decision: str
    ) -> list[str]:
        """Re-read manifest, children, document and markdown, returning every problem."""
        problems: list[str] = []
        source = await asyncio.to_thread(self.runtime.sources.get_source, source_id)
        destination = "wiki" if expected_decision == "admit" else expected_decision
        if source is None:
            problems.append("missing source manifest")
            return problems
        if source.destination != destination:
            problems.append(f"manifest destination is {source.destination!r}, expected {destination!r}")
        for child_id in source.pages_generated:
            if await self.runtime.store.get_page(child_id, include_body=False) is None:
                problems.append(f"missing claimed child {child_id}")
        if await self.runtime.store.get_page(doc_id, include_body=False) is None:
            problems.append(f"missing document page {doc_id}")
        if not await asyncio.to_thread(markdown_path.is_file):
            problems.append(f"missing markdown projection {markdown_path}")
        return problems
