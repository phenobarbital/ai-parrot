---
id: F004
query_id: Q004
type: read
intent: Conversational recording fabricates success in a wrapper
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F004 — Conversational recording fabricates success in a wrapper

## Summary

The precise hardcoded SUCCESS/3 write is in _safe_record_ask, scheduled by _record_post_ask after trivial-query filtering. Correct that path without equating a returned answer with verified task success. The unified manager also records through record_tool_episode and must be covered by outcome-policy tests before claiming all agent paths are fixed.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/episodic/mixin.py`
  lines: 423-487
  symbol: `EpisodicMemoryMixin._record_post_ask / _safe_record_ask`
  excerpt: |
        async def _record_post_ask(
            self,
            query: str,
            response: Any | None = None,

- path: `packages/ai-parrot/src/parrot/memory/unified/manager.py`
  lines: 368-400
  symbol: `UnifiedMemoryManager._record_episodic`
  excerpt: |
        async def _record_episodic(
            self,
            query: str,
            response: Any,

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
