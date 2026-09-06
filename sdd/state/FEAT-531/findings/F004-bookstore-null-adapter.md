---
id: F004
query_id: Q006
type: read
intent: Read the Bookstore/_NullAdapter degraded-mode design to understand the philosophy being changed
executed_at: 2026-09-06T03:10:20Z
duration_ms: 260
parent_id: null
depth: 0
---

# F004 — `_NullAdapter` is the concrete "no LLM" stand-in; raises only when structured output is required

## Summary

`Bookstore.__init__` accepts `adapter: Optional[Any] = None`; when `None`, callers get a
`_NullAdapter` whose `ask()` degrades to `""` (silent, non-fatal) but whose `ask_structured()`
raises `RuntimeError("No LLM configured for the bookstore")` — this is the exact string the
requester saw, surfaced indirectly through `pageindex/builder.py:171`'s
`_probe_pages_for_toc`, which catches per-page exceptions and logs them as
`"TOC detector failed on page %d: %s"` rather than failing the whole ingest.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
  lines: 59-78
  symbol: `_NullAdapter`
  excerpt: |
    class _NullAdapter:
        """Adapter stand-in when no LLM is configured. ...ask_structured() raises
        because its callers ... cannot proceed without a model..."""
        async def ask(self, *args, **kwargs) -> str:
            return ""
        async def ask_structured(self, *args, **kwargs) -> Any:
            raise RuntimeError("No LLM configured for the bookstore")
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py`
  lines: 165-175
  symbol: `_probe_pages_for_toc`
  excerpt: |
    for idx, result in zip(indices, results):
        if isinstance(result, Exception):
            logger.warning("TOC detector failed on page %d: %s", idx, result)
            detected[idx] = "no"

## Notes

Any fix must thread the new default through `resolve_adapter()` so `Bookstore` receives a real
adapter instead of `_NullAdapter` — no changes needed inside `library.py` itself.
