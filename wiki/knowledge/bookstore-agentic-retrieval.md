---
title: Bookstore Agentic Retrieval
summary: Per-book cited retrieval, multi-origin excerpts, safe re-indexing and measured budgets.
---

# Bookstore Agentic Retrieval

## Purpose

Bookstore provides per-book agentic retrieval through `bookstore_agentic_retrieve`, which delegates to the existing `PageIndexToolkit.agentic_retrieve` loop. The method returns a validated evidence bundle with book identity, exact-range citations, and the same `stopped` values as PageIndex (no `stale` value). It supports optional revision guards on segment reads and deterministic drift repair via `bookstore doctor`.

Use `bookstore_agentic_retrieve` when a caller needs evidence it can quote and check: an in-process agent, a Bookstore origin, or a local MCP host that wants `[Document.pdf, p. 12 ¶3]` style references. The loop reuses the client's own tool loop (`AbstractClient.ask(tools=...)`) on a dedicated client clone, so no provider SDK is called directly and `parrot.bots` is not involved.

## Public API

- [`Bookstore.agentic_retrieve`](ref:parrot.knowledge.bookstore.library) — stage-1 search plus the bounded reading loop; returns the evidence bundle as a dict with book identity and decorated citations
- [`Bookstore.read_segments`](ref:parrot.knowledge.bookstore.library) — read a sna... (see [Revision guard](#revision-guard))
- [`Bookstore.doctor`](ref:parrot.knowledge.bookstore.library) — sweep safely, report drift/orphans/unjudged books, optionally repair cards and build missing judgements
- [`BookstoreOrigin`](ref:parrot_tools.multistoresearch.origins.bookstore) — stage-1 origin that produces exact single-segment excerpts with immutable addresses in `OriginHit.metadata["citation"]`
- [`BookstoreToolkit`](ref:parrot.knowledge.bookstore.toolkit) — 14 read-only tools, including `agentic_retrieve`, `catalog_search`, `related_books`, `communities`, `get_toc`, `search_book`, `read_section`, and the three graph tools from FEAT-533
- [`ask_cmd`](ref:parrot.knowledge.bookstore.cli) — CLI entry point for a single cited research question
- [`doctor_cmd`](ref:parrot.knowledge.bookstore.cli) — CLI entry point for recovery and drift repair

## Configuration & Parameters

### Bookstore constructor

| Constructor kwarg | Default | Effect |
|---|---:|---|
| `reindex_lock_timeout_s` | `5.0` | Deadline for acquiring any operation lock; timeout raises `BookstoreError` naming the slug/source |
| `max_books` | `3` | Maximum books returned by `BookstoreOrigin.search` (clamped to 1-10) |
| `top_k` | `5` | Maximum candidates per book in `agentic_retrieve` (clamped to 1-50) |
| `excerpt_chars` | `600` | Maximum characters per excerpt in `BookstoreOrigin` (clamped to 1-12000) |
| `timeout` | `120.0` | Per-call timeout for `agentic_retrieve` and origin searches |

### agentic_retrieve arguments

| Argument | Default | Effect |
|---|---|---|
| `book_id` | required | Book to search |
| `query` | required | Research question |
| `top_k` | `5` | Stage-1 candidates per book (clamped 1-50) |
| `draft_answer` | `True` | If `False`, model returns citations only and `answer` is `null` |
| `budget_chars` | `40000` | Stored-text characters the reads may deliver to the model per request |
| `max_reads` | `12` | Read results recorded per request |
| `max_tool_calls` | `20` | Tool invocations admitted per request across all four tools |
| `timeout_s` | `120.0` | One wall-clock deadline per request, shared by every phase |

### read_segments expected_revision

`read_segments(..., expected_revision=None)` is backward compatible. When set, compare the expected value with the **actual returned ReadResult.revision** before releasing any result text to the caller. A mismatch raises `RevisionMismatchError` (a ValueError), propagated by Bookstore rather than flattened to BookstoreError. Cursor mismatch retains the same exception. The guard promises that the returned snapshot matches, not that it remains live afterward.

## Usage Examples

### ask_cmd — single cited research question

```bash
parrot bookstore ask amor-y-pedagogia-unamuno-miguel \
  "¿Qué pretende conseguir Avito con la educación de su hijo?" \
  --llm google:gemini-3.5-flash-lite \
  --budget-chars 40000 \
  --max-reads 12 \
  --timeout 120 \
  --json
```

Normal stdout shows answer, rendered citations and grounded/stopped/chars_read; JSON stdout is exactly the serialized bundle. Missing models and Bookstore errors use ClickException. Diagnostics must not contaminate MCP or JSON output.

### agentic_retrieve — programmatic access

```python
from parrot.clients.factory import LLMFactory
from parrot.knowledge.bookstore.library import Bookstore

client = LLMFactory.create("google:gemini-3.5-flash-lite")
bookstore = Bookstore(
    library_path=Path(".parrot/library"),
    reindex_lock_timeout_s=5.0,
    max_books=3,
    top_k=5,
    excerpt_chars=600,
    timeout=120.0,
)

bundle = await bookstore.agentic_retrieve(
    "amor-y-pedagogia-unamuno-miguel",
    "¿Qué pretende conseguir Avito con la educación de su hijo?",
    top_k=5,
    draft_answer=True,
    budget_chars=40000,
    max_reads=12,
    timeout_s=120.0,
)

if bundle["grounded"]:
    print(bundle["answer"])
    print(bundle["rendered_citations"])  # e.g. [Amor y pedagogía, p. 12 ¶3]; [Amor y pedagogía, p. 13 ¶1]
    for citation in bundle["citations"]:
        print(citation["label"], citation["start"], citation["end"], citation["excerpt"])
else:
    print("no citation survived:", bundle["stopped"])
    for rejected in bundle["rejected"]:
        print(rejected["reason"], rejected["proposed"]["address"])
```

### BookstoreOrigin — multi-origin excerpts

```python
from parrot_tools.multistoresearch.origins.bookstore import BookstoreOrigin
from parrot.clients.factory import LLMFactory

client = LLMFactory.create("google:gemini-3.5-flash-lite")
origin = BookstoreOrigin(
    scope="project",
    book_ids=["amor-y-pedagogia-unamuno-miguel", "analectas-confucio"],
    max_books=3,
    top_k=5,
    excerpt_chars=600,
    name="bookstore",
    timeout=120.0,
)

hits = await origin.search("What is the relationship between education and reflection?", k=5)
for hit in hits:
    print(hit.metadata["citation"])  # doc_id/revision/seq/start/end/page/ordinal/section/label/document/excerpt/book_id/title
```

### doctor_cmd — recovery and drift repair

```bash
# Report drift, orphans, and unjudged books
parrot bookstore doctor

# Repair cards with drift (TOC mismatch)
parrot bookstore doctor --repair

# Build missing judgements without LLM (deterministic)
parrot bookstore doctor --relate --no-llm

# Full recovery: repair + relate
parrot bookstore doctor --repair --relate --llm google:gemini-3.5-flash-lite
```

The report includes `reserved` entries (scope/name/action/reason), `books` entries (scope/book_id/status/repaired), `unjudged_book_ids`, `errors`, and optional `relate_summary`. Statuses are `ok`, `drift`, `orphan_card`, `busy`, or `error`.

## Gotchas

### No-LLM mode

Without an LLM configured (`PARROT_BOOKSTORE_LLM` unset), `agentic_retrieve` raises `ValueError` unless `agentic_client` is given. The `_NullAdapter` is not a real provider. Missing/unsupported tool-loop configuration becomes `BookstoreError` with `PARROT_BOOKSTORE_LLM` guidance, preserving the original reason. Do not mislabel numeric parameter validation errors as missing LLM configuration.

### Actual stop reasons

The loop returns the same `stopped` values as PageIndex: `answered`, `budget`, `max_tool_calls`, `timeout`, `no_tool_calls`, `parse_error`, `provider_error`. There is **no `stale` value**. Preserve returned bundles and real errors; do not fabricate a stale bundle.

### Snapshot fallback

`agentic_retrieve` pins a private deep copy of the tree before stage-1. A re-import during the request does not switch the request to a new revision; cursors and addresses keep naming the revision they were issued for. The bundle's `generation` is the pinned generation. Old revisions stay readable for the grace period described in [PageIndex Segment Store](pageindex-segment-store.md). After it, a revision the request read but can no longer load is rejected as `revision_unavailable`.

### Identical-TOC drift limitation

`doctor` repairs drift by comparing the live tree's TOC with the card's TOC digest. If the source hash and TOC both match, the graph is preserved; otherwise the graph is invalidated. However, a crash that swaps different text with identical TOC cannot be detected by TOC-only drift detection — this limitation must be reported/documented (full transactional catalog publication is out of scope).

### Host evaluation

The provisional Bookstore defaults (40000 chars / 12 reads / 20 tool calls / 120 s) are selected from the host evaluation report. The report includes SHA256 of the qualified host report and the fixture hash of `sdd/state/FEAT-858/agentic-eval-questions.json`. Do not type-infer measurements; copy them programmatically from the report.

## Related

- [PageIndex Agentic Retrieval and Citations](../pageindex-agentic-retrieval.md) — the underlying loop and citation contract
- [Bookstore in Codex](bookstore-codex.md) — Codex installer and session guide
- [Bookstore Conceptual Relations — the book graph](bookstore-graph.md) — relation types, communities, and the `relate` cost model
