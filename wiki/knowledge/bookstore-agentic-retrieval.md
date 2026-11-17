---
title: Bookstore Agentic Retrieval
summary: Per-book cited retrieval, multi-origin excerpts, safe re-indexing and the measured default budgets.
---

# Bookstore Agentic Retrieval

## Purpose

`Bookstore.agentic_retrieve` answers a question about one indexed book by delegating to the
PageIndex agentic loop (`PageIndexToolkit.agentic_retrieve`) and returns a validated evidence
bundle: book identity, exact-range citations, rendered citation labels and a `stopped` reason.
The loop uses the model's own tool loop through the Bookstore LLM adapter; no provider SDK is
called directly. Use it when a caller needs evidence it can quote and check.

## Public API

- `Bookstore.agentic_retrieve` (`parrot.knowledge.bookstore.library`) — stage-1 search plus the bounded reading loop.
- `Bookstore.read_segments(..., expected_revision=None)` — segment reads with an optional revision guard.
- `Bookstore.doctor` — report and repair drift between trees and catalog cards.
- `BookstoreToolkit.agentic_retrieve` (`parrot.knowledge.bookstore.toolkit`) — the LLM-facing tool, exposed over MCP as `bookstore_agentic_retrieve`. It stays visible without an LLM and returns a configuration error.
- `BookstoreOrigin` (`parrot_tools.multistoresearch.origins.bookstore`) — a multi-store search origin returning exact single-segment excerpts.
- CLI: `bookstore ask` and `bookstore doctor`.

## Parameters

### `agentic_retrieve`

| Argument | Default | Effect |
|---|---|---|
| `book_id` | required | Book to research |
| `query` | required | Research question |
| `top_k` | `5` | Stage-1 candidates considered |
| `draft_answer` | `True` | When `False`, no answer is drafted and `answer` is `null` |
| `budget_chars` | `None` | Total characters the reads may deliver; `None` uses the PageIndex default (40000) |
| `max_reads` | `None` | Reads recorded per request; `None` uses the PageIndex default (12) |
| `timeout_s` | `None` | One wall-clock deadline per request; `None` uses the PageIndex default (120 s) |

PageIndex also caps tool invocations at 20 per request. Bookstore adds no defaults of its own: the
host evaluation below found no setting better than these PageIndex defaults.

### `Bookstore` constructor

`Bookstore(locations, adapter=None, lightweight_model=None, *, reindex_lock_timeout_s=5.0)`.
`reindex_lock_timeout_s` bounds how long an operation waits for a book's lock; a timeout raises
`BookstoreError`.

### `BookstoreOrigin` constructor

`BookstoreOrigin(bookstore, *, scope=None, book_ids=None, max_books=3, top_k=5, excerpt_chars=600, name="bookstore", description=None, timeout=None)`.
`max_books` is capped at 10, `top_k` at 50. `scope` is `project`, `global` or `None`.

### `read_segments(expected_revision=...)`

The guard compares the revision of the result actually returned, not a preflight lookup. A
mismatch raises `RevisionMismatchError` before any text is released; a cursor from another revision
raises the same error. The guarantee is that the returned snapshot matches, not that it stays live.

## Usage

```bash
bookstore ask amor-y-pedagogia-unamuno-miguel \
  "¿Qué pretende conseguir Avito con la educación de su hijo?" \
  --llm google:gemini-3.5-flash-lite --json
```

`--json` prints exactly the serialized bundle on stdout; the resolved provider and model are written
to stderr only.

```python
bundle = await bookstore.agentic_retrieve(
    "amor-y-pedagogia-unamuno-miguel",
    "¿Qué pretende conseguir Avito con la educación de su hijo?",
)
if bundle["grounded"]:
    print(bundle["answer"], bundle["rendered_citations"])
else:
    print("no citation survived:", bundle["stopped"])
```

Recovery and drift:

```bash
bookstore doctor                          # report drift, orphans and unjudged books
bookstore doctor --repair                 # repair cards whose TOC drifted
bookstore doctor --relate --no-llm        # build missing deterministic judgements
```

The report holds `reserved`, `books`, `unjudged_book_ids`, `errors` and an optional
`relate_summary`. Book statuses are `ok`, `drift`, `orphan_card`, `busy` and `error`.

## Gotchas

- **No LLM.** Without a configured model (`PARROT_BOOKSTORE_LLM` or `--llm`), `agentic_retrieve` raises `BookstoreError` explaining that an LLM is required. Invalid numeric arguments raise `ValueError`.
- **Stop reasons.** `stopped` is one of `answered`, `budget`, `max_tool_calls`, `timeout`, `no_tool_calls`, `parse_error`, `provider_error`. There is no `stale` value.
- **Ungrounded answers.** When no citation survives validation, `grounded` is false and `answer` may be `null`; this is a result, not an error.
- **Citation decoration.** Chapter and section paths are added only when the tree snapshot matches the generation the retrieval used; otherwise the citation keeps its stored section and omits the chapter.
- **Identical-TOC drift.** `doctor` detects drift by comparing the live TOC with the card's TOC digest. A crash that swaps different text under an identical TOC cannot be detected this way; full transactional catalog publication is out of scope.
- **EPUB books have no pages.** Page-based reads fail on segment-only documents; see ledger `issue:7e09c516a2d3`.

## Host evaluation

Run on 2026-11-09 with `google:gemini-3.5-flash-lite`, seed 858, over seven books: 56 questions
(21 handwritten, 35 generated) and 140 planned rows, all completed. On the 21 handwritten questions the
baseline (40000 chars, 12 reads) grounded 16 and hit gold on 8; the four sweeps grounded 13-17 and
hit gold on 9-10. No sweep beat the baseline strictly on median characters read and median wall time,
so the recommendation is `retain_baseline` and the defaults are unchanged. Gold hits are low
overall (8 of 21 handwritten, 5 of 35 generated) and median characters read was 12000 in every setting.

- Report sha256: `1a62ca75295dfeb96e9f3e3fa88dc7a6d488eb91fed20007a9ecc82d28b72f56`
- Fixture sha256: `393e8facd6bcb427790ccb96d39b9466e40376642805c2028790b5ddf2bc86d5`

## Related

- [PageIndex Agentic Retrieval and Citations](pageindex-agentic-retrieval.md) — the underlying loop and citation contract
- [Bookstore in Codex](bookstore-codex.md) — Codex installer and session guide
- [Bookstore Conceptual Relations](bookstore-graph.md) — relation types, communities and the `relate` cost model
