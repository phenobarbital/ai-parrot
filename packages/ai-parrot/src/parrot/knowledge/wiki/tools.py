"""Lazy compatibility exports for moved wiki AbstractTools."""

from typing import Any

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
