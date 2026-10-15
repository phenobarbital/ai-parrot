"""Lazy compatibility exports for moved wiki AbstractTools."""

from typing import Any

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper  # noqa: F401 -- tests patch tools.WikiBookkeeper
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
from parrot.knowledge.wiki.operations import (  # noqa: F401 -- re-exported for structural/decisions tools, the CLI and existing tests
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

_EXPORTS: dict[str, str] = {
    "WikiQueryTool": "parrot_tools.wiki.tools",
    "WikiPageTool": "parrot_tools.wiki.tools",
    "WikiRelatedTool": "parrot_tools.wiki.tools",
    "WikiRememberTool": "parrot_tools.wiki.tools",
    "WikiNoteTool": "parrot_tools.wiki.tools",
    "WikiStatusTool": "parrot_tools.wiki.tools",
    "WikiLintTool": "parrot_tools.wiki.tools",
    "WikiStandupTool": "parrot_tools.wiki.tools",
    "VaultIngestTool": "parrot_tools.wiki.tools",
    "LedgerOpenTool": "parrot_tools.wiki.ledger",
    "LedgerReadyTool": "parrot_tools.wiki.ledger",
    "LedgerClaimTool": "parrot_tools.wiki.ledger",
    "LedgerCloseTool": "parrot_tools.wiki.ledger",
    "LedgerContextTool": "parrot_tools.wiki.ledger",
    "WikiPageHashesTool": "parrot_tools.wiki.bulk",
    "WikiIngestBatchTool": "parrot_tools.wiki.bulk",
    "WikiSyncPushTool": "parrot_tools.wiki.bulk",
    "WikiSyncPullTool": "parrot_tools.wiki.bulk",
    "create_wiki_tools": "parrot_tools.wiki.tools",
    "create_bulk_tools": "parrot_tools.wiki.bulk",
}

__all__ = [*list(_EXPORTS), *[name for name in globals() if not name.startswith("__")]]


def __getattr__(name: str) -> Any:
    """Resolve moved framework wrappers only when requested."""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
