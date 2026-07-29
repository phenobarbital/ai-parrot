---
type: Wiki Summary
title: parrot.knowledge.wiki.bookkeeper
id: mod:parrot.knowledge.wiki.bookkeeper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wiki bookkeeper — index.md and log.md lifecycle management (FEAT-260).
relates_to:
- concept: class:parrot.knowledge.wiki.bookkeeper.WikiBookkeeper
  rel: defines
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
---

# `parrot.knowledge.wiki.bookkeeper`

Wiki bookkeeper — index.md and log.md lifecycle management (FEAT-260).

Implements the bookkeeping layer of the LLM Wiki:

- **index.md** — extends OKF's ``generate_index_md()`` output with a
  wiki-specific header that includes source counts, category breakdown,
  and a last-updated timestamp.
- **log.md** — append-only operation chronicle.  Every entry is prefixed
  with a parseable ISO-8601 UTC timestamp and an operation tag so that
  tools can grep the log without parsing free-form text.

Log entry format::

    [2026-06-26T15:42:00Z] [INGEST] source: article.md, pages: 3
    [2026-06-26T15:43:12Z] [QUERY] question: "what is a neural network"
    [2026-06-26T15:50:00Z] [LINT] issues: 0

The bookkeeper does *not* hold any persistent state — all state lives on
disk in the wiki directory passed to each method call.  This keeps the
class stateless and safe to construct cheaply.

## Classes

- **`WikiBookkeeper`** — Manages index.md and log.md bookkeeping files for a wiki.
