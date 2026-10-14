"""Wiki AbstractTool wrappers (FEAT-403 Module 5).

Six `AbstractTool` subclasses that expose the wiki retrieval/authoring
surface (`BaseWikiStore`) as native tools, so they can be registered with
a `StdioMCPServer` (core) and appear as first-class MCP tools at
tool-selection time — equal standing with Grep/Read instead of competing
via a Bash-invoked CLI.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Union


from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper  # noqa: F401 -- tests patch tools.WikiBookkeeper
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.knowledge.wiki.ledger.operations import (  # noqa: F401 -- re-exported: the ledger schemas moved
    LedgerClaimInput,
    LedgerCloseInput,
    LedgerContextInput,
    LedgerOpenInput,
    LedgerReadyInput,
    op_ledger_claim,
    op_ledger_close,
    op_ledger_context,
    op_ledger_open,
    op_ledger_ready,
)
from parrot.knowledge.wiki.operations import (  # noqa: F401 -- re-exported for structural/decisions tools and the CLI
    HASHES_MAX_IDS,
    INGEST_MAX_BYTES,
    INGEST_MAX_SLICES,
    SYNC_PULL_MAX,
    IngestBatchInput,
    IngestBatchReport,
    PageHashesInput,
    SourceSlicePayload,
    SyncPagesInput,
    _INGEST_LOCK,
    op_ingest_batch,
    op_page_hashes,
    op_sync_pull,
    op_sync_push,
    op_vault_ingest,
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
        params = VaultIngestInput(vault_path=vault_path, force=force)
        return _to_tool_result(await op_vault_ingest(self._store, params, root=self._root, config=self._config))


# ------------------------------------------------------------------
# Ledger MCP Tools (FEAT-566 Module 8)
# ------------------------------------------------------------------

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.service import LedgerService
    from parrot.knowledge.wiki.project import WikiProjectConfig


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
        params = LedgerOpenInput.model_construct(
            title=title, body=body, discovered_from=discovered_from, kind=kind, severity=severity, about=about
        )
        return _to_tool_result(await op_ledger_open(self._ledger_service, params))


class LedgerReadyTool(AbstractTool):
    """Get ready (unclaimed) work from the SDD ledger."""

    name = "ledger_ready"
    description = "Get ready (unclaimed) work from the SDD ledger."
    args_schema = LedgerReadyInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, kind: IssueKind | None = None) -> ToolResult:
        return _to_tool_result(await op_ledger_ready(self._ledger_service, LedgerReadyInput.model_construct(kind=kind)))


class LedgerClaimTool(AbstractTool):
    """Claim an issue from the SDD ledger."""

    name = "ledger_claim"
    description = "Claim an issue from the SDD ledger."
    args_schema = LedgerClaimInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, issue_id: str, actor: str | None = None) -> ToolResult:
        params = LedgerClaimInput.model_construct(issue_id=issue_id, actor=actor)
        return _to_tool_result(await op_ledger_claim(self._ledger_service, params))


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
        params = LedgerCloseInput.model_construct(
            issue_id=issue_id, reason=reason, resolved_by=resolved_by, actor=actor
        )
        return _to_tool_result(await op_ledger_close(self._ledger_service, params))


class LedgerContextTool(AbstractTool):
    """Get context from the SDD ledger for specific files."""

    name = "ledger_context"
    description = "Get context from the SDD ledger for specific files."
    args_schema = LedgerContextInput

    def __init__(self, ledger_service: "LedgerService"):
        super().__init__(name=self.name, description=self.description)
        self._ledger_service = ledger_service

    async def _execute(self, file_paths: list[str], max_tokens: int = 3000) -> ToolResult:
        params = LedgerContextInput.model_construct(file_paths=file_paths, max_tokens=max_tokens)
        return _to_tool_result(await op_ledger_context(self._ledger_service, params))


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
        return _to_tool_result(
            await op_page_hashes(self._store, PageHashesInput.model_construct(concept_ids=concept_ids))
        )


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
        params = IngestBatchInput(
            slices=[
                s if isinstance(s, SourceSlicePayload) else SourceSlicePayload.model_validate(s) for s in slices or []
            ],
            deleted_source_ids=deleted_source_ids or [],
            batch_id=batch_id,
        )
        return _to_tool_result(await op_ingest_batch(self._store, params, root=self._root, config=self._config))


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
        params = SyncPagesInput(
            pages=[page if isinstance(page, WikiPageRecord) else WikiPageRecord.model_validate(page) for page in pages],
            edges=edges or [],
        )
        return _to_tool_result(await op_sync_push(self._store, params, wiki_name=self._wiki_name))


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
        # model_construct: the op clamps ``limit`` itself (the original tool never rejected out-of-range values).
        params = SyncPagesInput.model_construct(
            pages=[], edges=[], since=since, skip_asserted_by=skip_asserted_by, limit=limit, cursor=cursor
        )
        return _to_tool_result(await op_sync_pull(self._store, params))


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
