# TASK-1938: Documentation — toolkit guide + migration note

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1936, TASK-1937
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 9. The clean break (old `MultiStoreSearchTool`
removed) and the four-origin toolkit need user-facing documentation:
configuration for each origin family, the response payload shape, and the
score-comparability caveat.

---

## Scope

- Create `docs/multistoresearch-toolkit.md` covering:
  - What the toolkit is; the four tools and when the LLM uses each.
  - Configuration examples for all four origin families (vector store,
    PageIndex with the three modes + default `hybrid`, GraphIndex with/without
    the SQLite reader FTS leg, ParrotWiki with/without embedder).
  - The `MultiSearchResponse` payload: grouped sections (native ranking,
    origin descriptions, status/notes) + `merged_top_k` (BM25, deduped).
  - Caveats: origin scores not comparable; per-origin 30 s default timeout;
    `llm` PageIndex mode spends tokens; FTS capability matrix
    (wiki ✓, arango ✓, graphindex ✓-with-reader, pgvector ✗, faiss ✗).
  - Migration note: `MultiStoreSearchTool` removed (clean break), registry
    name change, `StoreRouter` FAN_OUT now takes any `MultiSearch`-satisfying
    object.
- Follow the structure/tone of an existing doc (e.g. `docs/pageindex.md`).
- Cross-link from any doc index if the repo maintains one (check `docs/`).

**NOT in scope**: code changes of any kind; docstrings (owned by their tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/multistoresearch-toolkit.md` | CREATE | Guide + migration note |
| `docs/` index file (if one exists) | MODIFY | Cross-link |

---

## Codebase Contract (Anti-Hallucination)

### Verified references (document ONLY what these expose)
```python
from parrot_tools.multistoresearch import MultiStoreSearchToolkit           # TASK-1936
from parrot_tools.multistoresearch.origins import (VectorStoreOrigin,
    PageIndexOrigin, GraphIndexOrigin, ParrotWikiOrigin)                    # TASK-1932..1935
from parrot.models import (SearchOriginKind, OriginHit, OriginSection,
                           MultiSearchResponse, MultiSearch)                # TASK-1930
```
Every code snippet in the doc MUST be validated against the implemented
signatures (read `toolkit.py` and `origins/*.py` as built — constructor
parameters may have evolved slightly from the spec sketch).

### Does NOT Exist
- ~~`MultiStoreSearchTool`~~ — removed by TASK-1937; docs must present it as removed, not deprecated.
- ~~Postgres FTS~~ — out of scope; the FTS capability matrix must show pgvector ✗.

---

## Implementation Notes

- Reference doc style: `docs/pageindex.md`, `docs/llm-wiki.md`.
- Keep examples runnable-shaped (imports + construction + one tool call), but
  they are documentation, not tests.

---

## Acceptance Criteria

- [ ] `docs/multistoresearch-toolkit.md` exists and covers all Scope bullets.
- [ ] Every import/constructor/method in doc snippets matches the implemented code (verify by reading the final sources).
- [ ] Migration note explicitly states the clean break and the registry rename.
- [ ] Markdown renders cleanly (no broken code fences / tables).

---

## Test Specification

Documentation task — no pytest. Verification = reading the implemented
modules and cross-checking every snippet against them.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1936 and TASK-1937 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read the FINAL implemented signatures before writing snippets
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-07-27
**Notes**: Created `docs/multistoresearch-toolkit.md` following the
`docs/pageindex.md` style (TOC, Quick Start, sections, API Reference).
Covers: the four tools table, per-origin adapter configuration examples
for all four families (vector, PageIndex's three modes with `hybrid`
default, GraphIndex with/without reader, ParrotWiki with/without
embedder), the `MultiSearchResponse`/`OriginSection`/`OriginHit` payload
shapes, the FTS capability matrix (pgvector ✗, faiss ✗, arango ✓,
graphindex ✓-with-reader, wiki ✓ always, pageindex ✗ always), caveats
(score non-comparability, 30s default timeout, `llm` mode token cost),
and a migration note with a before/after table plus a concrete
old→new construction snippet. Cross-linked from
`docs/chapters/tools-rag.md`'s "Read next" section (no separate `docs/`
index file exists beyond the chapter system). Every import, constructor
signature, and attribute referenced in the doc was cross-checked against
the actual implemented source files (`toolkit.py`, `origins/*.py`) via
grep, not the spec sketch. Markdown fence count verified even (18,
balanced).

**Deviations from spec**: none
