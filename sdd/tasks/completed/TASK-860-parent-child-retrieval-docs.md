# TASK-860: Documentation — `docs/parent-child-retrieval.md`

**Feature**: FEAT-128 — Parent-Child Retrieval with Composable Parent Searcher
**Spec**: `sdd/specs/parent-child-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-858
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-128. Operators and bot authors need a single page that
explains: when to enable `expand_to_parent`, how the 3-level hierarchy
works, how it composes with the FEAT-126 cross-encoder reranker, and the
migration warning for collections ingested before this feature.

This task can run in parallel with TASK-859 (integration tests) — they
touch disjoint files. Mark `parallel: true`.

Reference: spec §3 (Module 6), §5 acceptance criterion "Documentation
page in `docs/parent-child-retrieval.md` covers enabling, hierarchy
threshold, FEAT-126 composition, and the migration warning".

---

## Scope

Write `docs/parent-child-retrieval.md` covering:

1. **What it is** — one-paragraph elevator pitch (small-to-big retrieval).
2. **When to enable it** — handbook/policy/training corpora where the
   answer spans multiple chunks; not useful for FAQ-style precise
   lookups. Recommend a smaller `context_search_limit` (e.g., 5)
   when enabling expansion to mitigate token-explosion risk
   (spec §7 Risk #1).
3. **How to enable** — code samples for both paths:
   - Constructor injection: `Bot(parent_searcher=..., expand_to_parent=True)`.
   - DB-driven config: setting `expand_to_parent=true` on the bot row.
   - Per-call override: `await bot.ask(q, expand_to_parent=False)`.
4. **The 3-level hierarchy** — explain `parent_chunk_threshold_tokens`
   (default **16000**), `parent_chunk_size_tokens` (default 4000),
   `parent_chunk_overlap_tokens` (default 200). Include a diagram
   showing the doc → parent_chunks → child_chunks split.
5. **Composition with FEAT-126 reranker** — order is reranker first,
   then parent expansion on the top-K reranked children. Note that
   dedupe collapses multiple high-scored siblings into one parent,
   resulting in fewer effective documents in the LLM context — by
   design (spec §7 Risk #4).
6. **Migration warning** — collections ingested before this feature
   may not have universal `is_chunk: True` markers. The default
   `similarity_search` filter has a backward-compat clause that keeps
   legacy chunks returnable, but operators should re-ingest where
   possible. The `include_parents=True` kwarg restores legacy
   behaviour for tooling that needs it.
7. **Limitations** — postgres only in v1; other stores (milvus, faiss,
   bigquery, arango) need their own `<Store>ParentSearcher` impl
   (spec §7 Risk #7). DB-driven `parent_searcher` selection is
   deferred (spec §8).

**NOT in scope**:
- Code changes (this is a docs-only task).
- Updating CLAUDE.md, README, or `.agent/CONTEXT.md` — those are owned
  separately and the SDD spec doesn't request changes there.
- Spanish translation (spec doesn't require it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/parent-child-retrieval.md` | CREATE | The new doc page. |

---

## Codebase Contract (Anti-Hallucination)

> The doc references CODE in the codebase. All cited symbols must
> actually exist after TASK-855…TASK-858 land.

### Verified Symbols (post-implementation)

```python
# Will exist once TASK-855 lands
from parrot.stores.parents import AbstractParentSearcher, InTableParentSearcher

# Will exist once TASK-858 lands
AbstractBot.parent_searcher       # attribute
AbstractBot.expand_to_parent      # attribute, default False

# Will exist once TASK-857 lands
LateChunkingProcessor.process_document_three_level
# _chunk_with_late_chunking accepts:
#   parent_chunk_threshold_tokens: int = 16000
#   parent_chunk_size_tokens: int = 4000
#   parent_chunk_overlap_tokens: int = 200
```

### Does NOT Exist (do NOT mention in docs)

- ~~A `ParentSearcher` registry / yaml-by-name selection~~ — deferred,
  not for v1.
- ~~A `parent_searcher` field in DB-driven config~~ — only
  `expand_to_parent` flag is exposed. Parent searcher is constructor
  injection only.
- ~~`SearchResult.parent` attribute~~ — does not exist; parents are
  linked via `metadata['parent_document_id']`.
- ~~Implementations for non-postgres stores~~ — postgres only in v1.

---

## Implementation Notes

### Tone & length

- Match the tone of existing `docs/*.md` pages in the project. Inspect
  one or two to mirror the heading hierarchy and code-fence style.
- Aim for ~150–250 lines. Concise; this is operator-facing reference,
  not a tutorial.
- Use Mermaid for the hierarchy diagram if existing docs use Mermaid;
  otherwise an ASCII diagram (mirror the one in spec §2).

### Cross-references

- Link to the spec (`sdd/specs/parent-child-retrieval.spec.md`) at the
  top so future operators can find the design rationale.
- Link to FEAT-126's docs page (when it exists) in the composition
  section. If FEAT-126 hasn't shipped yet, refer to it by Feature ID
  with a TODO note.

### Key Constraints

- No emojis (per project convention; emojis only on user request).
- Include working, copy-pasteable code blocks. Do NOT invent
  variable names not in the codebase.
- The migration warning must mention BOTH the legacy-compat predicate
  in `similarity_search` AND the `include_parents=True` escape hatch.

### References in Codebase

- `sdd/specs/parent-child-retrieval.spec.md` — the spec itself.
- `parrot/stores/utils/chunking.py:LateChunkingProcessor` — for the
  3-level hierarchy section.
- `parrot/bots/abstract.py` — for the `expand_to_parent` /
  `parent_searcher` attributes.
- Check whether `docs/` has an index file (e.g., `docs/README.md` or
  similar) that lists doc pages; if so, add an entry for this page.

---

## Acceptance Criteria

- [ ] `docs/parent-child-retrieval.md` exists.
- [ ] All seven sections from the Scope are present.
- [ ] All cited code symbols exist in the codebase post-TASK-858.
- [ ] All code blocks parse / are copy-pasteable (no pseudo-code).
- [ ] The migration warning mentions both the legacy-compat predicate
      and `include_parents=True`.
- [ ] If `docs/` has an index, it links to the new page.
- [ ] Markdown lints cleanly (no broken links, consistent heading
      levels). Use whatever existing markdown lint config the project
      has, or skip if none.

---

## Test Specification

> Documentation task — no programmatic tests. Manual verification:
> render the page in a Markdown previewer; check all internal links
> resolve; copy each code block into a Python REPL or test script and
> ensure it parses (no `from parrot.foo import nonexistent`).

---

## Agent Instructions

When you pick up this task:

1. **Confirm dependency**: TASK-858 must be in `sdd/tasks/completed/`
   so all referenced symbols exist.
2. **Read the spec** end-to-end (it's not long); pull the diagram from
   §2 and the risk text from §7.
3. **Inspect existing `docs/` pages** for tone, heading style, and any
   index file you should update.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Write** the doc.
6. **Verify** every code symbol cited in the doc exists by `grep`.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
