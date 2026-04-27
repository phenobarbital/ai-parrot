# TASK-869: Documentation page `docs/contextual-embedding.md`

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-863
**Assigned-to**: unassigned

---

## Context

Module 6 of the spec. Ships the user-facing documentation page so
operators / agent developers know:

- how to enable the feature per store,
- what the default template renders,
- how to override the template (string vs callable),
- the precedence rule with `LateChunkingProcessor`,
- the migration warning for existing collections (TASK-868 script reference),
- the dependency on `ai-parrot-loaders-metadata-standarization`.

This task can run in parallel with TASK-864/865/866/867/868 because it
only edits a new doc file.

Spec sections: §3 Module 6, §5 Acceptance Criteria items 9 & 10, §7
Known Risks, §8 Open Questions (decisions are now closed).

---

## Scope

- Create `docs/contextual-embedding.md` (top-level docs/, NOT
  `packages/ai-parrot/docs/`).
- Required sections (use these exact H2 headings for grep-ability):
  - `## What it does` — the problem and the deterministic, LLM-free fix.
  - `## Enabling it` — show the kwarg on PgVectorStore, Milvus, Faiss,
    Arango.
  - `## The default template` — show the template string and a worked
    example with full / partial / empty `document_meta`.
  - `## Customising the template` — string and callable forms; include a
    Spanish-example template (per spec §7 risk #4) since the user's
    market includes Spanish corpora.
  - `## What gets stored` — clarify that `page_content` is RAW and the
    header lives in `metadata['contextual_header']`.
  - `## Precedence with late chunking` — metadata-header wins. Quote
    spec §8 Q3.
  - `## Migrating existing collections` — point at
    `scripts/recompute_contextual_embeddings.py` (TASK-868).
  - `## Dependency` — note the `ai-parrot-loaders-metadata-standarization`
    dependency and the graceful-passthrough behaviour.
- Cross-link from the existing docs index if one exists (check
  `docs/README.md` or `docs/index.md`).

**NOT in scope**:

- Code changes.
- Architecture diagrams beyond what the spec already provides (link
  back to spec for the diagram).
- Benchmark numbers — those are a follow-up after FEAT-126 reranker
  benchmarks land.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/contextual-embedding.md` | CREATE | User-facing documentation. |
| `docs/README.md` or `docs/index.md` | MODIFY (if exists) | Add a link to the new page. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Facts to Cite

- `parrot.stores.utils.contextual.DEFAULT_TEMPLATE` (TASK-861):
  ```python
  "Title: {title} | Section: {section} | Category: {category}\n\n{content}"
  ```
- Three constructor kwargs added to `AbstractStore` (TASK-862):
  `contextual_embedding`, `contextual_template`,
  `contextual_max_header_tokens`. All default to off / sensible values.
- Wired stores in v1: `PgVectorStore` (TASK-863), `MilvusStore` (TASK-864),
  `FaissStore` (TASK-865), `ArangoStore` (TASK-866).
- Migration script: `scripts/recompute_contextual_embeddings.py` (TASK-868).
- Header is whitespace-tokenised and capped at
  `contextual_max_header_tokens` (default 100).
- `contextual_header` is surfaced in `SearchResult.metadata` (TASK-867).
- Documentation page itself is this task (TASK-869).

### Does NOT Exist

- ~~An LLM-based header generator~~ — explicitly rejected.
- ~~A loader-side header builder~~ — augmentation is store-side only.
- ~~A `Document.contextual_header` top-level field~~ — header lives in
  `metadata['contextual_header']`.

---

## Implementation Notes

### Doc Voice

Match the voice of existing docs (`docs/sdd/WORKFLOW.md` is a good
sample): short paragraphs, code blocks for every claim, no marketing
fluff. Assume the reader is a developer who already uses
`PgVectorStore`.

### Worked Examples

For "What gets stored" include before/after JSON of a row:

```json
{
  "document": "You will receive it on the 15th of every month.",
  "cmetadata": {
    "document_meta": {"title": "Employee Handbook", "section": "Compensation", "category": "HR Policy"},
    "contextual_header": "Title: Employee Handbook | Section: Compensation | Category: HR Policy"
  }
}
```

For "Enabling it" — minimum copy-paste example per store:

```python
store = PgVectorStore(
    dsn=...,
    table="my_collection",
    contextual_embedding=True,
)
await store.add_documents(documents)
```

### Key Constraints

- Do NOT promise quality numbers. The spec deliberately calls the smoke
  test in §4 "not a hard quality gate".
- Be explicit that flipping the flag on an existing collection without
  re-embedding produces inconsistent retrieval — point to TASK-868's
  script as the remedy.

---

## Acceptance Criteria

- [ ] `docs/contextual-embedding.md` exists.
- [ ] All eight required H2 sections are present (see Scope).
- [ ] At least one Python code example per store wired in v1.
- [ ] At least one custom-template example (string AND callable forms).
- [ ] Migration warning explicitly references the script path.
- [ ] No invented APIs (every code example uses signatures from the
      verified facts above).
- [ ] If `docs/README.md` or `docs/index.md` exists, it links to the new
      page.

---

## Test Specification

This is a docs task — no automated tests. Manual verification:

```bash
# Render the markdown file with mdformat or just open in an editor.
mdformat --check docs/contextual-embedding.md
# Confirm every code example is copy-pasteable (run the imports in a REPL).
```

---

## Agent Instructions

1. Read the spec end-to-end — your job is to translate it for users.
2. Verify TASK-861..863 are completed (the API surface must match what
   you document).
3. Update status to in-progress.
4. Write the page; cross-link the docs index.
5. Move to completed; update index.

---

## Completion Note

**Completed by**: sdd-worker agent (Claude claude-sonnet-4-5)
**Date**: 2026-04-27
**Notes**: Created `docs/contextual-embedding.md` with all 8 required H2
sections: What it does, Enabling it, The default template, Customising the
template, What gets stored, Precedence with late chunking, Migrating existing
collections, Dependency. Includes copy-paste examples for all four stores
(PgVectorStore, MilvusStore, FAISSStore, ArangoDBStore), string and callable
template forms, a Spanish-corpus template example, the before/after JSON row
illustration, migration script CLI reference, and `SearchResult.metadata`
usage. Verified `docs/README.md` does not exist (no cross-link needed).
All code examples use verified API signatures from TASK-861/862/863.
**Deviations from spec**: none
