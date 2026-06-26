---
id: F011
query_id: Q011
type: read
intent: Deep dive into bot integration wiring pattern for toolkits
executed_at: 2026-06-26T00:00:00Z
duration_ms: 3800
parent_id: F005
depth: 1
---

# F011 — Bot Integration: _capture_knowledge_toolkit Pattern

## Summary

Toolkit integration follows a documented pattern: (1) AbstractBot declares _pageindex_toolkit/_graphindex_toolkit as Optional[Any] attributes (abstract.py:349-356), (2) _capture_knowledge_toolkit() (interfaces/tools.py:147-163) detects toolkit class by name string (avoids circular imports from satellite packages) and stashes instances, (3) agents return toolkit tools from agent_tools() override (called in constructor before configure()), (4) ToolManager.register_toolkit() calls get_tools_sync() and registers each tool, (5) has_pageindex_tools/has_graphindex_tools properties check both stashed instance and tool_manager name prefix scan, (6) REST handler accesses toolkit via agent.pageindex_toolkit property for direct method calls (not tool invocations). Two-phase registration: Phase 1 (constructor) via agent_tools(), Phase 2 (configure) via register_toolkit().

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/tools.py`
  lines: 147-163
  symbol: `_capture_knowledge_toolkit`
  excerpt: |
    def _capture_knowledge_toolkit(self, toolkit):
        cls_name = type(toolkit).__name__
        if cls_name == "PageIndexToolkit" and ..._pageindex_toolkit is None:
            self._pageindex_toolkit = toolkit
        elif cls_name == "GraphIndexToolkit" and ..._graphindex_toolkit is None:
            self._graphindex_toolkit = toolkit

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 349-356
  symbol: `__init__`
  excerpt: |
    self._pageindex_toolkit: Optional[Any] = None
    self._graphindex_toolkit: Optional[Any] = None

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 305-307
  symbol: `agent_tools`

- path: `agents/oddie.py`
  lines: 223-265
  symbol: `agent_tools`

## Notes

For LLMWikiToolkit, follow the exact same pattern: (1) Add _llmwiki_toolkit: Optional[Any] = None to AbstractBot.__init__, (2) Add "LLMWikiToolkit" case to _capture_knowledge_toolkit(), (3) Add llmwiki_toolkit property and has_llmwiki_tools to interfaces/tools.py, (4) Agents instantiate LLMWikiToolkit in agent_tools() and return its get_tools(). The toolkit composes PageIndexToolkit + GraphIndexToolkit + OKFToolkit as private attributes.
