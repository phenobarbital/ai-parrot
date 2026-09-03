# TASK-2772: Wiki symbol surface (schema v2) on Postgres

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2768
**Assigned-to**: unassigned

---

## Context

Module 8 of FEAT-520. Wiki store schema v2 (TASK-2742..2751, merged ~Aug
2026) added a `symbols` table and symbol methods to the wiki backends. They
are deliberately NON-abstract on `BaseWikiStore` (`wiki/store.py:572` — the
Arango backend may skip them), but this backend implements them for full
parity with the SQLite plane. Reference semantics are the SQLite
implementations — treat them as living reference, not a frozen copy (the
surface is fresh and may still move).

---

## Scope

- Finalize the `graphindex.symbols` table columns in `pg_schema.py` to match
  the wiki SQLite `symbols` table **column-for-column** (READ the current
  `WIKI_SCHEMA_SQL` symbols DDL, `wiki/store.py:53`, at implementation time —
  do not trust this task's snapshot).
- Implement on `PostgresWikiStore`:
  - `upsert_symbols(...)` — match the SQLite signature at `wiki/store.py:577`
    (base non-abstract version defines the contract; SQLite overrides at
    `:1323` — read both).
  - `symbols_for(rel_path) -> list[SymbolRecord]` (`:597`)
  - `find_symbols(...) -> list[SymbolRecord]` (`:624`)
  - `search_symbols_fts(query, limit=20) -> list[SymbolRecord]` (`:672`) —
    use the `simple` regconfig + `pg_trgm` similarity for identifier-ish
    matching (D7: code/symbols never get language stemming).
  - `page_hashes(concept_ids) -> dict[str, Optional[str]]` (`:693`) if not
    already done in TASK-2768.
- Enable `pg_trgm` extension in `ensure_schema` (add to TASK-2764's
  extension list).
- Tests: symbol roundtrip + FTS behavior parity with the SQLite suite's
  symbol tests (find and port the relevant test file —
  `grep -rn "upsert_symbols" packages/ai-parrot/tests/` first).

**NOT in scope**: symbol EXTRACTION (ast-grep pipeline — exists upstream),
`sym:` page ingestion logic, StructuralService.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py` | MODIFY | symbol methods |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` | MODIFY | symbols DDL final columns + pg_trgm |
| `packages/ai-parrot/tests/knowledge/wiki/test_postgres_symbols.py` | CREATE | live-gated parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.symbols import SymbolRecord   # wiki/symbols.py:56
```

### Existing Signatures to Use
```python
# wiki/store.py — BaseWikiStore non-abstract symbol surface (:572 comment block):
async def upsert_symbols(...)        # :577  — read exact params at impl time
async def symbols_for(self, rel_path: str) -> list[SymbolRecord]      # :597
async def find_symbols(...)          # :624
async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]  # :672
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]        # :693
# SQLite overrides begin near :1323 (upsert_symbols) — the behavioral reference.
# symbols table DDL lives inside WIKI_SCHEMA_SQL (:53) — copy columns verbatim.
```

### Does NOT Exist
- ~~symbol methods on `ArangoDBWikiStore`~~ — Arango skips them; that
  precedent is why these are non-abstract. This backend opts IN.
- ~~a language-stemmed FTS for symbols~~ — `simple` + trigram only (D7).
- ~~`parrot.knowledge.wiki.symbols.sha1_of_text` needed here~~ — hashing
  happens at ingestion, not in the store (verify before importing).

---

## Implementation Notes

### Key Constraints
- `SymbolRecord` roundtrip must be lossless (model in/model out).
- This task may run in parallel with TASK-2766/2767 (different files), but
  it shares `pg_schema.py` with TASK-2769 — coordinate if concurrent.
- Freshness rule: verify every `wiki/store.py` line reference before use —
  the symbol surface merged weeks ago and moves.

### References in Codebase
- `packages/ai-parrot/tests/` symbol tests for SQLite (locate via grep) —
  the parity source.

---

## Acceptance Criteria

- [ ] Symbol upsert → `symbols_for`/`find_symbols` roundtrip lossless (test).
- [ ] `search_symbols_fts` finds identifier fragments (trigram) without
      language stemming artifacts (test).
- [ ] `page_hashes` parity with SQLite semantics (test).
- [ ] Ported SQLite symbol test scenarios green on Postgres (live-gated).
- [ ] `ruff check` clean; zero SQLAlchemy.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_postgres_symbols.py
async def test_symbol_roundtrip(pg_wiki_store): ...
async def test_find_symbols_filters(pg_wiki_store): ...
async def test_search_symbols_trigram(pg_wiki_store): ...
async def test_page_hashes(pg_wiki_store): ...
```

---

## Agent Instructions

1. FIRST re-read the current symbols DDL + method signatures in
   `wiki/store.py` (they may have moved since 2026-09-03) — update this
   contract if so.
2. Implement; update index status; completed + note when done.

---

## Completion Note

*(Agent fills this in when done)*
