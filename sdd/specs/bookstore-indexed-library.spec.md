---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Bookstore — Indexed Book Library for Claude Code

**Feature ID**: _(documentation spec — implemented directly, no FEAT id reserved)_
**Date**: 2026-09-05
**Author**: Jesus Lara
**Status**: implemented
**Branch**: `claude/biblioteca-indexada-claude-code-gaam3p`
**Extended by**: FEAT-533 (`wikitoolkit-bookstore-conceptual-relations.spec.md`)
— adds a book relation graph, communities, three agent tools, and
`export-wiki`; see §3-§6 below and `docs/bookstore-graph.md`.

---

## 1. Motivation

PageIndex indexes one document as a hierarchical chapter/page tree
without the complexity of a knowledge graph — ideal for books. What was
missing is a **library** on top of it: many books, each with a
consultable catalog card ("ficha hemeroteca") so a research agent can
first decide *which book to open for which topic*, and a delivery
mechanism (MCP + skill) so Claude Code uses it efficiently.

## 2. Scope

New core package `parrot.knowledge.bookstore`
(`packages/ai-parrot/src/parrot/knowledge/bookstore/`):

| Module | Responsibility |
|---|---|
| `models.py` | `BookCard` (the ficha), `TocEntry`, `CardDraft` |
| `config.py` | Location precedence: `PARROT_LIBRARY_DIR` → `<git root>/.parrot/library` → `~/.parrot/library` (`PARROT_HOME`-relocatable); dedupe; `require_exists` for the read-only MCP |
| `catalog.py` | `CatalogStore`: SQLite `library.db` (WAL, additive migrations) + plain FTS5 `books_fts` (DELETE+INSERT upserts, sanitized MATCH, LIKE fallback without FTS5); `merged_cards`/`merged_search` combine scopes, project wins |
| `carding.py` | `slugify`/`unique_slug`, `derive_toc(tree)` → structured ToC + text digest, LLM carding (`ask_structured` → `CardDraft`) with deterministic no-LLM fallback |
| `library.py` | `Bookstore` manager: per-scope `CatalogStore` + `PageIndexToolkit` (storage under `<scope>/library/trees/`); ingestion + read surface; `_NullAdapter` degraded mode |
| `toolkit.py` | `BookstoreToolkit(AbstractToolkit)`, `tool_prefix="bookstore"` — read-only agent surface |
| `cli.py` | `bookstore` console script (also `parrot bookstore` via LazyGroup) |
| `mcp_server.py` | `bookstore mcp` — `StdioMCPServer`, wikitoolkit stdout-purity discipline |

Delivery to Claude Code:

- `.mcp.json.example` — `bookstore` stdio server entry.
- `.agent/skills/bookstore/SKILL.md` — the research funnel skill.
- `.claude/commands/bookstore.md` — `/bookstore <question>` slash command.

## 3. The ficha (BookCard)

`book_id` (slug == PageIndex `tree_name`), `title`, `authors[]`,
`year`, `language`, `topics[]`, `summary` (librarian paragraph),
`toc_digest` (rendered "1.2 Title (pp. 34-58)" lines, FTS-indexed),
`toc[]` (structured, JSON column), `scope`, `source_path`,
`source_sha256` (dedupe), `source_format` (`pdf|md|txt|epub|docx`),
`page_count`, `chapter_count`, `added_at`,
`card_origin` (`llm|fallback|manual`).

**FEAT-533** added five more fields, filled by the same carding LLM
call at zero extra cost (or left at their defaults with no LLM):
`genre` (closed classification), `traditions[]` (free text,
slug-normalised), `period` (free text era label),
`community_id`/`community_label` (written back by `bookstore relate`,
never by carding — see `docs/bookstore-graph.md`).

## 4. Agent tool surface (read-only, 10 tools)

| Tool | LLM? | Purpose |
|---|---|---|
| `bookstore_catalog_search` | no | which book covers X (FTS over fichas) |
| `bookstore_list_books` | no | merged inventory |
| `bookstore_get_card` | no | full ficha |
| `bookstore_get_toc` | no | chapter tree with node ids + pages |
| `bookstore_search_book` | optional | hybrid in-book search |
| `bookstore_read_section` | no | sidecar markdown of one section |
| `bookstore_related_books` (FEAT-533) | no | books related through the graph (same author, shares topic, LLM-judged conceptual relations, ...) |
| `bookstore_communities` (FEAT-533) | no | every detected community, member briefs |
| `bookstore_get_community` (FEAT-533) | no | full community detail incl. inter-community relations |
| `bookstore_search` | optional | catalog shortlist → scoped tree-walk (`search_documents_scoped`, ≤ `max_books`); `expand_related` (FEAT-533) widens the shortlist with depth-1 related books, no extra LLM call |

Ingestion (`add`/`remove`/`card --refresh`) is CLI-only: indexing is a
minutes-long LLM batch, the wrong shape for a stdio tool call, and the
MCP surface stays non-destructive. **FEAT-533** extends this rule to
the relation graph: computing relations/communities (`bookstore
relate`) and exporting to wikitoolkit (`bookstore export-wiki`) are
also CLI-only — see `docs/bookstore-graph.md`.

## 5. Ingestion (`bookstore add <file>`)

sha256 dedupe (skip / `--force` reindex) → unique slug → per-format
import: PDF native (`import_pdf`), Markdown (`insert_markdown`),
plain text (`insert_content`, requires LLM), EPUB via **lazy**
`parrot_loaders.EpubLoader` import, DOCX via **lazy**
`parrot_loaders.MSWordLoader.docx_to_markdown` (core never
hard-depends on the loaders distribution; legacy `.doc` is excluded —
python-docx cannot read it) → `derive_toc` → LLM carding or fallback
(filename title + chapter topics) → catalog upsert. Failed imports
delete the partial tree.

**FEAT-533**: an opt-in `--relate` flag runs `bookstore relate` for
just the new book (Stage 1-2 only, no communities) right after
cataloguing it — plain `add`/`add-folder` never call the relation LLM
implicitly.

**Bulk ingest** — `bookstore add-folder <dir> [--recursive] [--dry-run]
[--relate]` (`Bookstore.iter_folder_files` + `add_folder`): sequential
loop over every supported file, per-file progress, continues past
failures (recorded as `failed` in the summary), sha256 dedupe makes
re-runs idempotent; exit code is non-zero only when every file failed.
With `--relate`, each new book is related as it's ingested, then one
communities-only pass runs once at the end over the whole library.

## 6. Degradation matrix

| Configuration | catalog/toc/read | search_book / search | relations (FEAT-533) |
|---|---|---|---|
| LLM (`PARROT_BOOKSTORE_LLM`) | full | hybrid BM25 + LLM tree-walk | full — Stage 1 deterministic + Stage 2 LLM conceptual relations + Stage 3 communities with LLM labels |
| no LLM, `bm25s` installed | full | BM25-only | Stage 1 + Stage 3 (deterministic/title community labels); Stage 2 skipped with an explanatory note |
| no LLM, no `bm25s` | full | explanatory error | same as above — relations don't depend on `bm25s` |

Cross-book `search` falls back to searching all books (capped) when the
catalog shortlist is empty (thin fallback cards). See
`docs/bookstore-graph.md` for the full FEAT-533 relations/communities
design, the `relate` cost model, and the `export-wiki` degradation
(CLI-only regardless of row; fails with an explanatory error when the
wiki/graphindex packages aren't installed).

## 7. Acceptance criteria (all verified)

- [x] 60 tests in `packages/ai-parrot/tests/knowledge/bookstore/`
      (models/config/catalog/library/toolkit/cli/mcp) pass, including
      regression tests for the adversarial-review findings (CLI
      invocation-CWD anchoring, cross-scope slug collisions, toolkit
      parameter clamps).
- [x] Existing pageindex toolkit suite still green (47 passed).
- [x] CLI smoke: `add --no-llm` / `toc` / `search --book` on a temp
      library via `PARROT_LIBRARY_DIR`.
- [x] MCP smoke: `initialize` + `tools/list` over stdin return valid
      JSON-RPC with zero non-protocol bytes on stdout.
