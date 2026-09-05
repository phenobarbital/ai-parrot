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
`source_sha256` (dedupe), `source_format` (`pdf|md|txt|epub`),
`page_count`, `chapter_count`, `added_at`,
`card_origin` (`llm|fallback|manual`).

## 4. Agent tool surface (read-only, 7 tools)

| Tool | LLM? | Purpose |
|---|---|---|
| `bookstore_catalog_search` | no | which book covers X (FTS over fichas) |
| `bookstore_list_books` | no | merged inventory |
| `bookstore_get_card` | no | full ficha |
| `bookstore_get_toc` | no | chapter tree with node ids + pages |
| `bookstore_search_book` | optional | hybrid in-book search |
| `bookstore_read_section` | no | sidecar markdown of one section |
| `bookstore_search` | optional | catalog shortlist → scoped tree-walk (`search_documents_scoped`, ≤ `max_books`) |

Ingestion (`add`/`remove`/`card --refresh`) is CLI-only: indexing is a
minutes-long LLM batch, the wrong shape for a stdio tool call, and the
MCP surface stays non-destructive.

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

**Bulk ingest** — `bookstore add-folder <dir> [--recursive] [--dry-run]`
(`Bookstore.iter_folder_files` + `add_folder`): sequential loop over
every supported file, per-file progress, continues past failures
(recorded as `failed` in the summary), sha256 dedupe makes re-runs
idempotent; exit code is non-zero only when every file failed.

## 6. Degradation matrix

| Configuration | catalog/toc/read | search_book / search |
|---|---|---|
| LLM (`PARROT_BOOKSTORE_LLM`) | full | hybrid BM25 + LLM tree-walk |
| no LLM, `bm25s` installed | full | BM25-only |
| no LLM, no `bm25s` | full | explanatory error |

Cross-book `search` falls back to searching all books (capped) when the
catalog shortlist is empty (thin fallback cards).

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
