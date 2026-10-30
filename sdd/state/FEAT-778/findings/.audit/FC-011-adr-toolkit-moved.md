---
id: FC-011
query_id: Q030
type: read
intent: "ADR toolkit surface exposed to agents (consume/produce ADRs)."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-011 — The decisions toolkit moved to `parrot_tools.wiki.decisions` (ai-parrot-tools); core keeps a lazy compat shim

## Summary

`knowledge/wiki/decisions/toolkit.py` is a 38-line lazy re-export (FEAT-540 M3) targeting `parrot_tools.wiki.decisions`. The agent-facing ADR tools (and the MCP `wiki_decision_why` / `wiki_decisions_for_symbol`) therefore ship from the tools distribution, consistent with the tool-centric architecture rule.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py`
  lines: 1-36
  symbol: `__getattr__`
  excerpt: |
    """Lazy compatibility exports for the moved decisions plane toolkit (FEAT-540 M3)."""
    _TARGET = "parrot_tools.wiki.decisions"
    def __getattr__(name: str) -> Any: """Resolve a moved name from parrot_tools.wiki only when requested."""

## Notes

[cross-lane: type=wiki_page, intent=outline parrot_tools.wiki.decisions toolkit tools (read/propose/review ADR)]
