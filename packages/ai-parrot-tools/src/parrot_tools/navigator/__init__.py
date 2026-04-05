"""
Navigator Toolkit for AI-Parrot.

Manages Programs, Modules, Dashboards and Widgets
for the Navigator platform via an AI agent.

Uses PageIndex (vectorless, LLM-driven RAG) for widget documentation:
- Layer 1: Tree context in system prompt (compact node summaries)
- Layer 2: search_widget_docs() for detailed retrieval per query
- Layer 3: get_widget_schema() for exact DB lookups

Usage:
    from parrot_tools.navigator import NavigatorToolkit, NavigatorPageIndex

    page_index = NavigatorPageIndex()
    await page_index.build(adapter)

    toolkit = NavigatorToolkit(
        connection_params={...},
        user_id=123,
        page_index=page_index,
    )
    tools = toolkit.get_tools()
"""
from .toolkit import NavigatorToolkit


def __getattr__(name: str):
    """Lazy imports for prompt-related symbols to avoid heavy import chains."""
    _prompt_exports = {
        "NavigatorPageIndex",
        "get_navigator_layers",
        "NAVIGATOR_OPERATIONS_LAYER",
    }
    if name in _prompt_exports:
        from . import prompt
        return getattr(prompt, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "NavigatorToolkit",
    "NavigatorPageIndex",
    "get_navigator_layers",
    "NAVIGATOR_OPERATIONS_LAYER",
]
