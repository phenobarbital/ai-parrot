---
title: PageIndex Segment Store
summary: Immutable, addressable segments (paragraphs) under every imported PageIndex node — revisions, ownership, read tools with cursors, injection flags and prompt framing.
---

# PageIndex Segment Store

## Purpose

A PageIndex tree stops at the node. The segment store adds the layer below it:
every imported document (PDF, markdown, ebook, ingested text) is persisted as an
immutable **document revision** — an ordered list of **segments** (heading,
paragraph, list, table, code, caption) with stable addresses, verbatim text, token
counts, content hashes and injection flags. Agents can read pages or paragraphs,
cite them by address, and treat the text as quoted data.

Two version terms are kept apart. A **revision** is the segment content of one
imported document, identified by a content hash. A **generation** (see
[Generation Publication](pageindex-generation-publication.md)) is one published
snapshot of a tree. Editing or optimizing a tree publishes generations; only a
re-import creates a revision, so an address that names a revision survives every
later generation.

### Segments and addresses

`segment_pages` splits the per-page markdown of a PDF; `segment_text` splits the text
of one section of an unpaged source. Blocks are blank-line separated, ATX headings are
their own `heading` segments, fenced code and pipe tables stay whole, list runs stay
whole and image lines are `caption`s. Segment text is verbatim: every character offset
in the feature indexes it.

An address is `(doc_id, revision, seq)` plus either `page` and `ordinal` (paged
sources) or a frozen `section` path and `ordinal` (unpaged ones). Labels render as
`p. 12 ¶3` or `Setup > Install ¶2`. `revision` is the first 16 hex characters of a
SHA-256 over the segment texts, so a re-import of unchanged text yields the same
revision. `doc_id` is a slug of the source name, suffixed with six hex characters only
when the tree already holds a different document under that slug.

### Revision files

`SegmentStore` writes one immutable file per revision:

```text
<storage_dir>/<tree>/segments/<doc_id>.<revision>.json
```

Files are written atomically and read through a small LRU that never invalidates.
`WriteTransaction.set_revision` stages them; publication validates that every revision a
node names is staged or on disk, writes revisions before body blobs and both before the
tree JSON switch, then marks superseded revisions and sweeps them after the grace
period, exactly like body blobs. A reader on generation N keeps reading its revision
after a re-import published N+1; after the grace period a read reports
`revision unavailable` (`RevisionUnavailableError`).

### Ownership and view bodies

Each node of an imported subtree carries `doc_id`, `revision`, a `span` (half-open range
over `seq` covering its subtree) and `owned` ranges (the span minus its children's
spans). Owned ranges of one document partition the revision exactly once;
`validate_ownership` re-checks that. For PDFs the span starts at the first segment of
`start_index`, or at a heading segment on that page matching the node title. A node's
body blob is `render_body(...)`: its owned segments in document order with a
`<!-- continues in: <child title> -->` line where a child's span interrupts them.
Parents therefore no longer carry their children's text.

## Public API

- [`DocumentRevision`](ref:parrot.knowledge.pageindex.segments) — the immutable revision model
- [`Segment`](ref:parrot.knowledge.pageindex.segments) — one addressable block
- [`SegmentAddress`](ref:parrot.knowledge.pageindex.segments) — structured address with `label` and `key`
- [`ReadResult`](ref:parrot.knowledge.pageindex.segments) — what the read tools return
- [`SegmentStore`](ref:parrot.knowledge.pageindex.segment_store) — revision files, cache, sweep
- [`render_body`](ref:parrot.knowledge.pageindex.segments) / [`validate_ownership`](ref:parrot.knowledge.pageindex.segments) — views and the partition check
- [`scan_segments`](ref:parrot.knowledge.pageindex.injection_scan) — regex-first injection scoring
- [`frame_segments`](ref:parrot.knowledge.pageindex.framing) and `DATA_FRAMING_INSTRUCTION` — data framing for prompts
- [`get_injection_scoring_engine`](ref:parrot.security.prompt_injection) and `InjectionScoringEngine` — the public ML engine accessor
- `pageindex_list_documents`, `pageindex_outline`, `pageindex_read_pages`, `pageindex_read_segments` — read tools on `PageIndexToolkit`
- `pageindex_index_segments` — derive segments for a legacy subtree
- `bookstore_read_pages`, `bookstore_read_segments`, `bookstore_outline` — the same per book

## Configuration & Parameters

| Parameter | Default | Description |
|---|---:|---|
| `scan_injection` | `True` | Score every segment at import. |
| `injection_probability_threshold` | `0.98` | ML score at or above which a regex suspect is flagged. |
| `read_max_chars` | `12000` | Cap `max_chars` is clamped to (floor 500). |

`import_pdf`, `insert_markdown` and `insert_ebook` accept an optional `doc_id` override.

### Read tools, budgets and cursors

`read_pages(tree, doc_id, "5-7,12")` returns the segments of those pages in order;
`read_segments(tree, doc_id, start, end)` reads a half-open range over `seq`, or with
`node_id` a node's owned ranges. Each returns a `ReadResult`: the pinned `generation` and
`revision`, segments with `address`, `start`/`end` (half-open offsets into the stored
segment text), `truncated` and `flags`, a `next_cursor` and `framed` (the segments as
data via `frame_segments`). A segment longer than the remaining budget is returned as a
prefix with a cursor at its next offset. A cursor has the form
`<doc_id>@<revision>#<seq>+<offset>`; one naming another revision raises
`RevisionMismatchError`. Cursors are per revision and per request budget only — they are
not a read ledger. `outline` gives titles, node ids, page ranges and owned-segment counts
cheaply.

### Injection scoring and framing

At import the regex detector runs over every segment in one worker thread; the ML engine
runs only on regex suspects, each call off the event loop. With an engine a suspect is
flagged when `score >= threshold`; without one when its highest regex threat is `HIGH` or
`CRITICAL`. A flagged segment keeps its text, gets `flags: ["injection"]` and an
`injection` mark, and is never redacted; the revision records `scored_by`
(`onnx`, `pytector` or `regex`). Scoring never aborts an import.
`frame_segments` wraps reads in `<document_text>` / `<segment address=… [flagged=…]>`
tags, neutralising only sequences that could close a tag; put
`DATA_FRAMING_INSTRUCTION` in the system prompt.

## Usage Examples

```python
imported = await toolkit.import_pdf("handbook", "manual.pdf")
docs = await toolkit.list_documents("handbook")
page = await toolkit.read_pages("handbook", imported["doc_id"], "5-7", max_chars=4000)
while page["next_cursor"]:
    page = await toolkit.read_pages(
        "handbook", imported["doc_id"], "5-7", max_chars=4000, cursor=page["next_cursor"]
    )

# Trees imported before segments existed: explicit, never implicit.
await toolkit.index_segments("legacy-tree")
```

## Gotchas

- Parent bodies shrink: a parent's blob holds only its own text, so `retrieve`/BM25 see less for parents.
- A shared page without a heading match goes entirely to the later sibling until the layout builder supplies exact headings.
- `update_node_content` on a segment-backed node keeps `owned`; the body no longer equals the view but addresses stay valid.
- `delete_node` leaves an ownership gap that `validate_ownership` reports.
- `index_segments` on a legacy PDF duplicates children's text inside the parent's revision (section-path addresses only); re-import the PDF to avoid it.
- Bookstore books indexed before this feature have no segments until reindexed or `index_segments` runs.
- Thin sections dropped by `md_to_tree` are not in the revision.

## Related

- [PageIndex — Tree-Based RAG for Document Retrieval](pageindex.md) — tree construction and retrieval
- [PageIndex Generation Publication](pageindex-generation-publication.md) — generations, blobs and the sweep revisions share
