---
type: Wiki Summary
title: parrot.knowledge.wiki.context
id: mod:parrot.knowledge.wiki.context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Token-efficient context packing for wiki retrieval results.
relates_to:
- concept: class:parrot.knowledge.wiki.context.PackedContext
  rel: defines
- concept: func:parrot.knowledge.wiki.context.first_sentence
  rel: defines
- concept: func:parrot.knowledge.wiki.context.pack_results
  rel: defines
- concept: func:parrot.knowledge.wiki.context.stub_line
  rel: defines
- concept: func:parrot.knowledge.wiki.context.truncate_to_tokens
  rel: defines
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.context`

Token-efficient context packing for wiki retrieval results.

The wiki optimises for what the LLM actually pays for: tokens.  Instead
of dumping full page bodies (or raw model dumps) into context, search
results are packed as **compact stubs** — one line per page with its
identity, title, lead sentence, score, and token cost — under an
explicit token budget.  The model then *progressively discloses* only
what it needs via ``wiki_read`` (full body, optionally truncated) and
``wiki_expand`` (edge neighbours).

All token accounting uses the per-page ``token_count`` stored in the
WikiStore at ingest time plus :func:`estimate_tokens` for the stub
lines themselves — nothing is re-tokenised at query time.

## Classes

- **`PackedContext(BaseModel)`** — A budgeted, LLM-ready packing of wiki search results.

## Functions

- `def first_sentence(text: str, max_chars: int=_MAX_LEAD_CHARS) -> str` — Return the lead sentence of ``text``, hard-capped at ``max_chars``.
- `def stub_line(result: dict[str, Any]) -> str` — Render one search result as a compact single-line stub.
- `def pack_results(results: Iterable[Any], budget_tokens: int=DEFAULT_BUDGET_TOKENS) -> PackedContext` — Pack search results into a token-budgeted context block.
- `def truncate_to_tokens(text: str, max_tokens: Optional[int]) -> tuple[str, bool]` — Deterministically truncate ``text`` to approximately ``max_tokens``.
