---
id: F003
query_id: Q003
type: read
intent: Read the full shared LLM-resolution helper to confirm the exact degraded-mode contract and env vars
executed_at: 2026-09-06T03:09:42Z
duration_ms: 250
parent_id: null
depth: 0
---

# F003 — Degraded mode is a deliberate, documented contract; no default provider anywhere

## Summary

`resolve_adapter()` reads `PARROT_BOOKSTORE_LLM` / `PARROT_BOOKSTORE_LLM_LIGHT`; if
`PARROT_BOOKSTORE_LLM` is unset it logs a warning and returns `(None, None, None)` — no
provider is ever chosen implicitly. The module docstring explicitly documents "When nothing is
configured the bookstore runs degraded (BM25/catalog only) — that is a supported mode, not an
error." The `"google:gemini-2.5-flash"` string in the docstring is illustrative example syntax
only, never executed as a fallback.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
  lines: 1-19
  excerpt: |
    - ``PARROT_BOOKSTORE_LLM`` — heavy model, e.g. ``"google:gemini-2.5-flash"``
      or ``"anthropic:claude-sonnet-5"``.
    When nothing is configured the bookstore runs degraded (BM25/catalog only) —
    that is a supported mode, not an error.
- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py`
  lines: 52-59
  symbol: `resolve_adapter`
  excerpt: |
    spec = llm_spec or os.environ.get(ENV_LLM)
    ...
    if not spec:
        logger.warning(
            "No LLM configured (%s unset) — bookstore runs BM25/catalog only",
            ENV_LLM,
        )
        return None, None, None

## Notes

This directly falsifies the "default is Gemini" framing in the source request — the real gap
is "no fallback at all," which the requester's own follow-up message reframed correctly
("la filosofia cambia porque ahora busco la facilidad de uso con poca o ninguna
configuracion"). The proposal should state this plainly so it isn't re-litigated later.
