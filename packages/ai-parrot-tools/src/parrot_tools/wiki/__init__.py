"""Agent-facing wiki tools and toolkits (moved from parrot.knowledge.wiki — FEAT-540 M3)."""

from typing import Any

_EXPORTS: dict[str, str] = {
    "LLMWikiToolkit": "parrot_tools.wiki.toolkit",
    "create_wiki_tools": "parrot_tools.wiki.tools",
    "create_bulk_tools": "parrot_tools.wiki.bulk",
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
    "CodeStructuralToolkit": "parrot_tools.wiki.structural",
    "create_structural_tools": "parrot_tools.wiki.structural",
    "DecisionToolkit": "parrot_tools.wiki.decisions",
    "create_decision_tools": "parrot_tools.wiki.decisions",
    "SchemaPlaneToolkit": "parrot_tools.wiki.schema",
    "create_schema_tools": "parrot_tools.wiki.schema",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve an agent-facing tool lazily."""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
