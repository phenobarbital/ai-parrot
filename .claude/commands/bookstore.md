---
description: Research a question in the personal indexed book library (bookstore)
argument-hint: <research question>
allowed-tools: Bash(bookstore:*)
---

Research the following question using the personal indexed book library
(the `bookstore_*` MCP tools if connected, otherwise the `bookstore`
CLI via Bash):

**Question**: $ARGUMENTS

Follow the bookstore research funnel strictly (see
`.agent/skills/bookstore/SKILL.md`):

1. **`bookstore_find_books(query)`** — ALWAYS start here. It answers "which books
   treat X, and where" from the librarian's sectors, with direct table-of-contents
   pointers; it falls back to `bookstore_catalog_search`.
   Call it with the question's key topics and pick the 1–3 most relevant
   books; use `bookstore_catalog_search` when no sector matches.
1b. **Expand by relations** — before opening any book, call
    `bookstore_related_books(book_id)` on the best `bookstore_catalog_search`
    hit to find the author's other works, sibling works of the same
    tradition/era, or conceptually adjacent works. For thematic or
    comparative questions ("what schools of thought does this library
    cover?"), call `bookstore_communities()` instead.
2. `bookstore_get_toc` on each candidate to locate promising chapters.
3. `bookstore_search_book` with the question against the best book(s);
   use `bookstore_search` instead when the question genuinely spans
   several books.
4. `bookstore_read_section` ONLY for the top-ranked sections.

Then answer the question grounded in what you read, citing each claim
as *Book Title*, "Section Title", pp. start–end. If the library has no
relevant book, say so explicitly — do not answer from general knowledge
without flagging it.

When a relation drives a claim, cite its origin: "the library links
these as parallels (LLM-inferred, 0.7)" vs "same author
(deterministic)".

Annotations returned next to a section are the reader's notes — cite them as *Notebook: <title>*, never as book pages.
