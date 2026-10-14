"""Wiki AbstractTool wrappers (FEAT-403 Module 5).

Six `AbstractTool` subclasses that expose the wiki retrieval/authoring
surface (`BaseWikiStore`) as native tools, so they can be registered with
a `StdioMCPServer` (core) and appear as first-class MCP tools at
tool-selection time — equal standing with Grep/Read instead of competing
via a Bash-invoked CLI.
"""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.actor import current_actor, scoped_actor
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity
from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, WikiStoreBusy
from parrot.knowledge.wiki.symbols import SymbolRecord
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.knowledge.wiki.operations import (  # noqa: F401 -- re-exported for structural/decisions tools and the CLI
    _LEDGER_KIND_PREFIXES,
    _NAMESPACE_DESC,
    _QUERY_FETCH_LIMIT,
    OperationResult,
    VaultIngestInput,
    WikiLintInput,
    WikiNoteInput,
    WikiPageInput,
    WikiQueryInput,
    WikiRelatedInput,
    WikiRememberInput,
    WikiStandupInput,
    WikiStatusInput,
    _qualify_ledger_target,
    _reject_foreign_id,
    _reject_managed_page,
    _scoped_store,
    _StorageDirConfig,
    _unknown_namespace_error,
    op_lint,
    op_note,
    op_page,
    op_query,
    op_related,
    op_remember,
    op_standup,
    op_status,
)


def _to_tool_result(result: OperationResult) -> ToolResult:
    """Map a transport-neutral :class:`OperationResult` onto a framework ``ToolResult``."""
    if result.is_error:
        return ToolResult(success=False, status="error", result=None, error=result.text)
    return ToolResult(result=result.data if result.data is not None else result.text)


class WikiQueryTool(AbstractTool):
    """Search the codebase knowledge graph for files, modules, symbols, or
    concepts. Returns ranked page stubs with IDs for drill-down. Use
    BEFORE grep/find/Read on large repos."""

    name = "wiki_query"
    description = (
        "Search the codebase knowledge graph for files, modules, symbols, "
        "or concepts. Returns ranked page stubs with IDs for drill-down. "
        "Use BEFORE grep/find/Read on large repos. When federated "
        "namespaces are configured this searches all of them and foreign "
        "page IDs come back prefixed (ns::file:a.py); pass `namespace` to "
        "search just one."
    )
    args_schema = WikiQueryInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(
        self,
        question: str,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        namespace: str | None = None,
        include_symbols: bool = False,
    ) -> str:
        params = WikiQueryInput(
            question=question, budget_tokens=budget_tokens, namespace=namespace, include_symbols=include_symbols
        )
        return (await op_query(self._store, params)).text


class WikiPageTool(AbstractTool):
    """Read a full wiki page by ID — file summaries, API outlines, content.
    Use IDs returned by wiki_query."""

    name = "wiki_page"
    description = (
        "Read a full wiki page by ID — file summaries, API outlines, "
        "content. Use IDs returned by wiki_query, including namespaced "
        "ones (ns::file:a.py)."
    )
    args_schema = WikiPageInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self, page_id: str, namespace: str | None = None) -> ToolResult:
        return _to_tool_result(await op_page(self._store, WikiPageInput(page_id=page_id, namespace=namespace)))


class WikiRelatedTool(AbstractTool):
    """Follow typed edges (contains, references) from a wiki page to
    discover connected files and modules."""

    name = "wiki_related"
    description = (
        "Follow typed edges (contains, references) from a wiki page to "
        "discover connected files and modules. Accepts namespaced page "
        "IDs (ns::dir:pkg) and returns neighbours from the same plane."
    )
    args_schema = WikiRelatedInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self, page_id: str, namespace: str | None = None) -> ToolResult:
        return _to_tool_result(await op_related(self._store, WikiRelatedInput(page_id=page_id, namespace=namespace)))


class WikiRememberTool(AbstractTool):
    """Save durable knowledge to the knowledge graph — decisions, gotchas,
    cross-file relationships. Survives across sessions."""

    name = "wiki_remember"
    description = (
        "Save durable knowledge to the knowledge graph — decisions, "
        "gotchas, cross-file relationships. Survives across sessions."
    )
    args_schema = WikiRememberInput

    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._storage_dir = storage_dir

    async def _execute(
        self,
        fact: str,
        category: str = "note",
        title: str | None = None,
        link_page_id: str | None = None,
        rel: str | None = "references",
        derived_from: str | None = None,
        about: list[str] | None = None,
    ) -> ToolResult:
        params = WikiRememberInput(
            fact=fact,
            category=category,
            title=title,
            link_page_id=link_page_id,
            rel=rel,
            derived_from=derived_from,
            about=about,
        )
        return _to_tool_result(await op_remember(self._store, params, storage_dir=self._storage_dir))


class WikiNoteTool(AbstractTool):
    """Append a dated note to an existing wiki page."""

    name = "wiki_note"
    description = "Append a dated note to an existing wiki page."
    args_schema = WikiNoteInput

    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._storage_dir = storage_dir

    async def _execute(self, page_id: str, text: str) -> ToolResult:
        return _to_tool_result(
            await op_note(self._store, WikiNoteInput(page_id=page_id, text=text), storage_dir=self._storage_dir)
        )


class WikiStatusTool(AbstractTool):
    """Check knowledge graph health: page count, staleness, last build time."""

    name = "wiki_status"
    description = "Check knowledge graph health: page count, staleness, last build time."
    args_schema = WikiStatusInput

    def __init__(self, store: BaseWikiStore):
        super().__init__(name=self.name, description=self.description)
        self._store = store

    async def _execute(self) -> ToolResult:
        return _to_tool_result(await op_status(self._store))


class WikiLintTool(AbstractTool):
    """Lint the wiki knowledge graph and report integrity findings."""

    name = "wiki_lint"
    description = (
        "Lint the wiki knowledge graph: broken links, duplicate slugs, stale memories, "
        "ADR conflicts; fix=true applies safe fixes."
    )
    args_schema = WikiLintInput

    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._storage_dir = storage_dir

    async def _execute(
        self,
        rules: list[str] | None = None,
        skip: list[str] | None = None,
        fix: bool = False,
        llm: bool = False,
    ) -> ToolResult:
        """Run lint and return a compact, machine-readable summary."""
        params = WikiLintInput(rules=rules, skip=skip or [], fix=fix, llm=llm)
        return _to_tool_result(await op_lint(self._store, params, storage_dir=self._storage_dir))


class WikiStandupTool(AbstractTool):
    """Render a wiki brief; write only when explicitly requested, to local storage."""

    name = "wiki_standup"
    description = "Render a daily, weekly or monthly wiki brief. Read-only unless writes are explicitly enabled."
    args_schema = WikiStandupInput

    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None:
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._root = root
        self._config = config

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Run the shared pipeline and return Markdown with write receipts."""
        return _to_tool_result(await op_standup(self._store, kwargs, root=self._root, config=self._config))


class VaultIngestTool(AbstractTool):
    """(Re)build the wiki retrieval plane from an Obsidian vault."""

    name = "vault_ingest"
    description = (
        "Ingest (or refresh) an Obsidian vault into the wiki knowledge "
        "base: one page per note, wikilink/embed/tag edges, FTS-searchable "
        "via wiki_query. Incremental — unchanged notes are skipped unless "
        "force=true. No LLM calls."
    )
    args_schema = VaultIngestInput

    def __init__(
        self,
        store: BaseWikiStore,
        root: Path,
        config: WikiProjectConfig,
    ):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._root = root
        self._config = config

    async def _execute(
        self,
        vault_path: str | None = None,
        force: bool = False,
        **kwargs,
    ) -> ToolResult:
        # Lazy imports: cli pulls click + scanners; keep the MCP server's
        # module import light and stdout-clean.
        from parrot.knowledge.wiki.cli import (
            _ingest_files,
            _open_sources,
            _prune_removed,
        )
        from parrot.knowledge.wiki.project import (
            resolve_vault_dir,
            wiki_write_lock,
        )
        from parrot.knowledge.wiki.vault_scan import scan_vault

        vault = resolve_vault_dir(self._root, self._config, override=vault_path)
        if vault is None:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=(
                    "No Obsidian vault found: pass vault_path, set "
                    "'vault_dir' in .parrot/wiki.json, or run inside a "
                    "vault (.obsidian/ directory)."
                ),
            )

        storage = self._config.storage_path(self._root)
        with wiki_write_lock(storage) as acquired:
            if not acquired:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=("Another wiki writer (build/upsert) is in progress " "— retry once it finishes."),
                )
            scan, stats = await asyncio.to_thread(
                scan_vault,
                vault,
                self._config.body_max_chars,
                self._config.max_file_kb * 1024,
            )
            sources = _open_sources(self._root, self._config, store=self._store)
            counts = await _ingest_files(self._store, sources, vault, scan, force=force)
            await self._store.upsert_pages(scan.dir_records)
            await self._store.add_edges(scan.dir_edges)
            # scope="root": this plane may also hold the repo's own
            # codebase pages — prune only what lives under the vault
            # (FEAT-450, D4.4).
            removed = await _prune_removed(self._store, sources, vault, scan, scope="root")
            store_stats = await self._store.stats()

        try:
            WikiBookkeeper().log_operation(
                storage,
                "VAULT_INGEST",
                f"vault: {vault}, notes: {stats.notes}, tags: {stats.tags}, "
                f"ingested: {counts.get('written', 0)}, removed: {removed}, "
                f"by: {current_actor()}",
            )
        except OSError as exc:
            self.logger.warning("Failed to log VAULT_INGEST to wiki audit trail: %s", exc)

        return ToolResult(
            result={
                "vault": str(vault),
                "notes": stats.notes,
                "tags": stats.tags,
                "wikilink_edges": stats.wikilink_edges,
                "embed_edges": stats.embed_edges,
                "unresolved_links": len(stats.unresolved_links),
                "ingested": counts.get("written", 0),
                "unchanged": counts.get("unchanged", 0),
                "removed": removed,
                "skipped": len(scan.skipped),
                "pages_total": store_stats.get("pages", 0),
                "edges_total": store_stats.get("edges", 0),
            }
        )


# ------------------------------------------------------------------
# Ledger MCP Tools (FEAT-566 Module 8)
# ------------------------------------------------------------------

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.service import LedgerService


# The ledger tool schemas mirror the `wikitoolkit ledger` CLI options one for
# one — same choices, same required fields — so an agent filing through MCP
# cannot persist a kind or severity the CLI would have rejected.


class LedgerOpenInput(BaseModel):
    title: str = Field(..., description="One-line issue title")
    body: str = Field(..., description="What is wrong, where (file + symbol), why it matters, suggested fix")
    kind: IssueKind = Field(default="bug", description="Issue kind: bug|tech_debt|feature_gap|vulnerability")
    severity: IssueSeverity = Field(default="minor", description="Issue severity: critical|major|minor|low")
    discovered_from: str = Field(
        ..., min_length=1, description="Source: spec:<FEAT-ID>, task:<TASK-ID> or review:<TASK-ID>"
    )
    about: list[str] | None = Field(
        default=None, description="Affected symbols/files, repo-relative, e.g. sym:pkg/mod.py#Func"
    )


class LedgerReadyInput(BaseModel):
    kind: IssueKind | None = Field(
        default=None, description="Filter by issue kind: bug|tech_debt|feature_gap|vulnerability"
    )


class LedgerClaimInput(BaseModel):
    issue_id: str = Field(..., description="Issue ID to claim")
    actor: str | None = Field(
        default=None, description="Actor claiming the issue, e.g. agent:sdd-fix (default: the request actor)"
    )


class LedgerCloseInput(BaseModel):
    issue_id: str = Field(..., description="Issue ID to close")
    reason: str = Field(..., description="Reason for closing")
    actor: str | None = Field(
        default=None, description="Actor closing the issue, e.g. agent:sdd-fix (default: the request actor)"
    )
    resolved_by: str | None = Field(
        default=None, description="Evidence that resolved the issue, e.g. commit:<sha> or task:TASK-<NNN> (FEAT-572 S4)"
    )


class LedgerContextInput(BaseModel):
    file_paths: list[str] = Field(..., description="File paths to scope context to")
    max_tokens: int = Field(default=3000, description="Maximum tokens in response")


class LedgerOpenTool(AbstractTool):
    """Open a new issue in the SDD work ledger."""

    name = "ledger_open"
    description = "Open a new issue in the SDD work ledger."
    args_schema = LedgerOpenInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(
        self,
        title: str,
        body: str,
        discovered_from: str,
        kind: IssueKind = "bug",
        severity: IssueSeverity = "minor",
        about: list[str] | None = None,
    ) -> ToolResult:
        try:
            issue_id = await self._ledger_service.open_issue(
                title=title,
                body=body,
                kind=kind,
                severity=severity,
                discovered_from=discovered_from,
                about=about,
                actor=current_actor(),
            )
            return ToolResult(result={"issue_id": issue_id})
        except Exception as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


class LedgerReadyTool(AbstractTool):
    """Get ready (unclaimed) work from the SDD ledger."""

    name = "ledger_ready"
    description = "Get ready (unclaimed) work from the SDD ledger."
    args_schema = LedgerReadyInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, kind: IssueKind | None = None) -> ToolResult:
        try:
            # IssueKind is a typing.Literal: the schema already validated the
            # value, and calling the Literal would raise TypeError.
            issues = await self._ledger_service.ready_work(kind)
            return ToolResult(result={"issues": issues})
        except Exception as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


class LedgerClaimTool(AbstractTool):
    """Claim an issue from the SDD ledger."""

    name = "ledger_claim"
    description = "Claim an issue from the SDD ledger."
    args_schema = LedgerClaimInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, issue_id: str, actor: str | None = None) -> ToolResult:
        try:
            success = await self._ledger_service.claim(issue_id, scoped_actor() or actor or current_actor())
            return ToolResult(result={"success": success})
        except Exception as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


class LedgerCloseTool(AbstractTool):
    """Close an issue in the SDD ledger."""

    name = "ledger_close"
    description = "Close an issue in the SDD ledger."
    args_schema = LedgerCloseInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(
        self, issue_id: str, reason: str, resolved_by: str | None = None, actor: str | None = None
    ) -> ToolResult:
        """Close a ledger issue, carrying the evidence reference and actor through."""
        try:
            kwargs = {"resolved_by": resolved_by} if resolved_by is not None else {}
            success = await self._ledger_service.close_issue(
                issue_id, reason, scoped_actor() or actor or current_actor(), **kwargs
            )
            return ToolResult(result={"success": success})
        except Exception as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


class LedgerContextTool(AbstractTool):
    """Get context from the SDD ledger for specific files."""

    name = "ledger_context"
    description = "Get context from the SDD ledger for specific files."
    args_schema = LedgerContextInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, file_paths: list[str], max_tokens: int = 3000) -> ToolResult:
        try:
            context = await self._ledger_service.get_context(file_paths, max_tokens)
            return ToolResult(result={"context": context})
        except Exception as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


INGEST_MAX_SLICES = 200
INGEST_MAX_BYTES = 1_048_576
_INGEST_LOCK = asyncio.Lock()
HASHES_MAX_IDS = 2000


class SourceSlicePayload(BaseModel):
    """One `replace_source_slice` unit crossing the wire (FEAT-569)."""

    source_id: str
    pages: list[WikiPageRecord] = Field(default_factory=list)
    edges: list[tuple[str, str, str]] = Field(default_factory=list)
    symbols: list[SymbolRecord] = Field(default_factory=list)


class IngestBatchInput(BaseModel):
    """Arguments of `wiki_ingest_batch`."""

    slices: list[SourceSlicePayload] = Field(default_factory=list)
    deleted_source_ids: list[str] = Field(default_factory=list)
    batch_id: str | None = None


class PageHashesInput(BaseModel):
    """Arguments of `wiki_page_hashes`."""

    concept_ids: list[str] = Field(default_factory=list)


class IngestBatchReport(BaseModel):
    """Outcome of one `wiki_ingest_batch` call."""

    slices_applied: int = 0
    slices_deleted: int = 0
    pages_written: int = 0
    edges_written: int = 0
    symbols_written: int = 0
    symbols_dropped: int = 0
    rejected: list[str] = Field(default_factory=list)


SYNC_PULL_MAX = 2000


class SyncPagesInput(BaseModel):
    """Authored knowledge crossing the wire (push payload / pull result)."""

    pages: list[WikiPageRecord] = Field(default_factory=list)
    edges: list[tuple[str, str, str, str]] = Field(default_factory=list)
    since: str | None = None
    skip_asserted_by: str | None = None
    limit: int = Field(default=500, ge=1, le=SYNC_PULL_MAX)
    cursor: str | None = None


class WikiPageHashesTool(AbstractTool):
    """Return stored content hashes for up to 2000 page ids.

    Delta oracle for the `wikitoolkit` CLI build push; not meant for agents.
    """

    name = "wiki_page_hashes"
    args_schema = PageHashesInput

    def __init__(self, store: BaseWikiStore):
        super().__init__()
        self._store = store

    async def _execute(self, concept_ids: list[str]) -> ToolResult:
        if len(concept_ids) > HASHES_MAX_IDS:
            return ToolResult(
                success=False, status="error", result=None, error=f"at most {HASHES_MAX_IDS} ids per call"
            )
        return ToolResult(result={"hashes": await self._store.page_hashes(concept_ids)})


class WikiIngestBatchTool(AbstractTool):
    """Apply source slices pushed by `wikitoolkit build/upsert/ingest` in remote mode.

    At most 200 slices and 1 MiB per call. For the CLI build push, not for agents.
    """

    name = "wiki_ingest_batch"
    args_schema = IngestBatchInput

    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig):
        super().__init__()
        self._store, self._root, self._config = store, root, config

    @staticmethod
    def _error(message: str) -> ToolResult:
        return ToolResult(success=False, status="error", result=None, error=message)

    async def _execute(
        self,
        slices: list[SourceSlicePayload] | None = None,
        deleted_source_ids: list[str] | None = None,
        batch_id: str | None = None,
    ) -> ToolResult:
        slices = [
            s if isinstance(s, SourceSlicePayload) else SourceSlicePayload.model_validate(s) for s in slices or []
        ]
        deleted_source_ids = deleted_source_ids or []
        # Validate everything BEFORE taking the lock or writing anything.
        if len(slices) > INGEST_MAX_SLICES or len(deleted_source_ids) > INGEST_MAX_SLICES:
            return self._error(f"at most {INGEST_MAX_SLICES} slices per call")
        if len(json.dumps([s.model_dump(mode="json") for s in slices]).encode()) > INGEST_MAX_BYTES:
            return self._error("payload too large (max 1 MiB)")
        report = IngestBatchReport()
        try:
            # In-process callers queue on an asyncio lock; the cross-process flock
            # (which polls with time.sleep) is entered/left in a worker thread so
            # it can never stall the serving event loop.
            async with _INGEST_LOCK:
                cm = wiki_write_lock(self._config.storage_path(self._root), timeout=self._config.sqlite_busy_timeout)
                acquired = await asyncio.to_thread(cm.__enter__)
                try:
                    if not acquired:
                        return self._error("busy: wiki writer lock is held by another process")
                    await self._apply(slices, deleted_source_ids, batch_id, report)
                finally:
                    await asyncio.to_thread(cm.__exit__, None, None, None)
        except WikiStoreBusy as exc:
            return self._error(f"busy: {exc}")
        return ToolResult(result=report.model_dump())

    async def _apply(
        self,
        slices: list[SourceSlicePayload],
        deleted_source_ids: list[str],
        batch_id: str | None,
        report: IngestBatchReport,
    ) -> None:
        """Write the validated slices and deletions; the caller holds the writer lock."""
        for s in slices:
            result = await self._store.replace_source_slice(s.source_id, s.pages, s.edges)
            report.pages_written += int(result.get("pages_written", 0))
            report.edges_written += int(result.get("edges_written", 0))
            count = await self._store.upsert_symbols(s.symbols, source_id=s.source_id)
            report.symbols_written += count
            if s.symbols and count == 0:
                report.symbols_dropped += len(s.symbols)
            report.slices_applied += 1
            self.logger.info("ingest_batch %s applied %s", batch_id, s.source_id)
        for sid in deleted_source_ids:
            await self._store.replace_source_slice(sid, [], [])
            report.slices_deleted += 1
            self.logger.info("ingest_batch %s deleted %s", batch_id, sid)


class WikiSyncPushTool(AbstractTool):
    """Merge remote sync data used by `wikitoolkit sync` in remote mode; not for agents."""

    name = "wiki_sync_push"
    args_schema = SyncPagesInput

    def __init__(self, store: BaseWikiStore, wiki_name: str):
        super().__init__()
        self._store, self._wiki_name = store, wiki_name

    async def _execute(
        self,
        pages: list[WikiPageRecord],
        edges: list[tuple[str, str, str, str]] | None = None,
        **_unused: Any,
    ) -> ToolResult:
        """Merge a client memory slice into the server wiki plane."""
        from parrot.knowledge.wiki.sync import SyncReport, _merge_body, _record_from

        pages = [page if isinstance(page, WikiPageRecord) else WikiPageRecord.model_validate(page) for page in pages]
        # Apply last-writer-wins directly against the server store. A staging
        # store is not used: it would re-stamp ``updated_at`` with "now" and
        # defeat the comparison against the caller's own timestamps.
        report = SyncReport(direction="push", env=self._wiki_name, dry_run=False)
        concept_ids: set[str] = set()
        for record in pages:
            if record.origin != "memory":
                continue
            page = record.model_dump()
            concept_id = record.concept_id
            concept_ids.add(concept_id)
            existing = await self._store.get_page(concept_id, include_body=True)
            if existing is None:
                report.created += 1
                report.details.append(f"created: {concept_id}")
                await self._store.upsert_pages([_record_from(page, record.body)])
                continue
            if (record.updated_at or "") <= (existing.get("updated_at") or ""):
                report.skipped_older += 1
                report.details.append(f"skipped_older: {concept_id}")
                continue
            report.updated += 1
            report.details.append(f"updated: {concept_id}")
            merged_body = _merge_body(record.body, existing.get("body", ""))
            await self._store.upsert_pages([_record_from(page, merged_body)])
        to_write = [
            (edge[0], edge[1], edge[2], "asserted")
            for edge in (edges or [])
            if edge[0] in concept_ids or edge[1] in concept_ids
        ]
        if to_write:
            await self._store.add_edges(to_write)
        return ToolResult(result=report.model_dump())


class WikiSyncPullTool(AbstractTool):
    """Return remote sync data used by `wikitoolkit sync` in remote mode; not for agents."""

    name = "wiki_sync_pull"
    args_schema = SyncPagesInput

    def __init__(self, store: BaseWikiStore):
        super().__init__()
        self._store = store

    async def _execute(
        self,
        since: str | None = None,
        skip_asserted_by: str | None = None,
        limit: int = 500,
        cursor: str | None = None,
        **_unused: Any,
    ) -> ToolResult:
        """Return a deterministic page of server-authored memory records."""
        from parrot.knowledge.wiki.sync import _synced_memory_pages

        limit = max(1, min(limit, SYNC_PULL_MAX))
        pages = await _synced_memory_pages(self._store)
        pages = [
            page
            for page in pages
            if (since is None or (page.get("updated_at") or "") > since)
            and (skip_asserted_by is None or page.get("asserted_by") != skip_asserted_by)
        ]
        pages.sort(key=lambda page: (page.get("updated_at") or "", page["concept_id"]))
        if cursor is not None:
            cursor_updated_at, _, cursor_concept_id = cursor.partition("|")
            pages = [
                page
                for page in pages
                if (page.get("updated_at") or "", page["concept_id"]) > (cursor_updated_at, cursor_concept_id)
            ]

        selected = pages[:limit]
        concept_ids = {page["concept_id"] for page in selected}
        edges = [
            (edge["src"], edge["dst"], edge["rel"], "asserted")
            for edge in await self._store.dump_edges()
            if edge["src"] in concept_ids or edge["dst"] in concept_ids
        ]
        next_cursor = None
        if len(pages) > limit:
            last = selected[-1]
            next_cursor = f"{last.get('updated_at') or ''}|{last['concept_id']}"
        return ToolResult(
            result={
                "pages": [WikiPageRecord.model_validate(page).model_dump(mode="json") for page in selected],
                "edges": edges,
                "next_cursor": next_cursor,
            }
        )


def create_bulk_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]:
    """Server-only page hash, ingest, and remote sync tools for the CLI."""
    return [
        WikiPageHashesTool(store),
        WikiIngestBatchTool(store, root, config),
        WikiSyncPushTool(store, config.wiki_name),
        WikiSyncPullTool(store),
    ]


def create_wiki_tools(
    store: BaseWikiStore,
    root: Path | None = None,
    config: WikiProjectConfig | None = None,
    ledger_service: Union["LedgerService", None] = None,
) -> list[AbstractTool]:
    """Create the wiki tools bound to ``store``, plus ledger tools when ``ledger_service`` is provided.

    Args:
        store: Wiki retrieval-plane backend the tools call directly.
        root: Wiki project root. When given together with ``config``,
            ``wiki_remember``/``wiki_note`` also append an entry to the
            wiki's ``log.md`` audit trail (via `WikiBookkeeper`), matching
            the equivalent CLI commands (`cli.py:remember`/`note`).
        config: Wiki project config — see ``root``.
        ledger_service: Optional ledger service for ledger tools.

    Returns:
        The six `AbstractTool` instances: wiki_query, wiki_page,
        wiki_related, wiki_remember, wiki_note, wiki_status, plus
        ledger tools when ledger_service is provided.
    """
    storage_dir = config.storage_path(root) if root is not None and config is not None else None
    tools = [
        WikiQueryTool(store),
        WikiPageTool(store),
        WikiRelatedTool(store),
        WikiRememberTool(store, storage_dir=storage_dir),
        WikiNoteTool(store, storage_dir=storage_dir),
        WikiStatusTool(store),
        WikiLintTool(store, storage_dir=storage_dir),
    ]

    # wiki_standup needs the project root + config to resolve the true local plane for opt-in writes;
    # context-free callers (no root/config) deliberately get no standup tool.
    if root is not None and config is not None:
        tools.append(WikiStandupTool(store, root, config))

    # Add ledger tools when ledger_service is provided
    if ledger_service is not None:
        tools.extend(
            [
                LedgerOpenTool(ledger_service),
                LedgerReadyTool(ledger_service),
                LedgerClaimTool(ledger_service),
                LedgerCloseTool(ledger_service),
                LedgerContextTool(ledger_service),
            ]
        )

    return tools
