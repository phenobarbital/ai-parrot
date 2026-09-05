---
name: bookstore
description: Research topics in the personal indexed book library via the bookstore MCP tools (bookstore_*) or the bookstore CLI. Use when the user asks what a book says about a topic, which book covers a topic, or wants cited passages from their library.
triggers:
  - "which book covers"
  - "what does the book say about"
  - "search my library"
  - "biblioteca"
  - "bookstore"
allowed-tools: Bash(bookstore:*)
---

# Bookstore — researching the indexed library

The bookstore is a personal library of books indexed as PageIndex
chapter trees, each with a catalog card ("ficha"): title, authors,
topics, a librarian summary, and a table of contents with page ranges.
Seven read-only MCP tools expose it. **Never** read a book wholesale —
follow the funnel below; it is cheap-to-expensive by design.

## The research funnel (mandatory order)

1. **`bookstore_catalog_search(query)`** — ALWAYS start here. Lexical
   search over the fichas answers "which book covers X?" with zero LLM
   cost. Pick 1–3 candidate books from the results. Use
   `bookstore_list_books()` only when you need the full inventory.
2. **`bookstore_get_toc(book_id)`** — orient inside a chosen book: the
   chapter tree with `node_id`s and page ranges. `bookstore_get_card`
   adds the summary/topics when you need to compare candidates.
3. **`bookstore_search_book(book_id, query)`** — targeted search inside
   one book. Returns ranked sections with `node_id`s.
4. **`bookstore_read_section(book_id, node_id)`** — read ONLY the
   sections that matter. Do not call this before searching.

Cross-book questions ("what do my books say about X?"): one call to
**`bookstore_search(query)`** — it shortlists via the catalog and
searches up to 3 books' trees (`max_books` caps LLM cost; keep it ≤3
unless the user insists).

## Citation format

Cite findings as: *Book Title*, "Section Title", pp. start–end. The
page data comes from `bookstore_get_toc` / `bookstore_read_section`
(`start_page` / `end_page`). Markdown-only books have no page numbers —
cite book + section instead.

## Degraded modes

- **No LLM configured** (server description says "lexical search
  only"): `search_book`/`search` are BM25-only — still useful, but rely
  more on the ToC to navigate. `catalog_search`, `get_toc`,
  `read_section` are always fully functional.
- **MCP server not connected**: the same operations exist as CLI
  commands via Bash — `bookstore search "<query>" --catalog-only`,
  `bookstore toc <book_id>`, `bookstore search "<query>" --book <id>`,
  `bookstore show <book_id>`.

## Managing the library (CLI only — not exposed over MCP)

Indexing is a minutes-long LLM batch job, so it lives in the CLI:

```bash
bookstore add path/to/book.pdf            # index into .parrot/library
bookstore add book.epub --global          # index into ~/.parrot/library
bookstore add notes.md --no-llm           # deterministic carding
bookstore add-folder ./libros --recursive # bulk: every pdf/md/txt/epub/docx
bookstore add-folder ./libros --dry-run   # preview what would be indexed
bookstore card <book_id> --refresh        # re-card after enabling an LLM
bookstore remove <book_id>
bookstore locations                       # show resolved library dirs
```

`add-folder` processes files sequentially, continues past failures, and
skips files already indexed (sha256 dedupe) — safe to re-run on the
same folder after dropping new books into it.

The LLM is configured with `PARROT_BOOKSTORE_LLM="provider:model"`
(optional `PARROT_BOOKSTORE_LLM_LIGHT` for cheap helper calls, same
provider). Project scope (`.parrot/library`) wins id collisions over
the global scope (`~/.parrot/library`); `PARROT_LIBRARY_DIR` overrides
the project location.
