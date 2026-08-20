# TASK-2283: `WikiSection`/`WikiPage` + per-section invalidation + single-flight

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL
**Depends-on**: TASK-2270, TASK-2273
**Assigned-to**: unassigned
**Spec task ref**: T9 (spec §10)

---

## Context

Spec §6 + OQ-5 + RQ-2. T9 moved *into* the v1 cut while T10 stayed out,
because `SectionSelector` is on the retrieval path — the section model is a core
contract even though the policy consuming it is deferred (§10).

Splitting is a **retrieval-time selection over addressable sections**, not a
generation-time page-splitting heuristic. The unplanned upside §6.1 records:
because each section declares its own sources, a change to one method
invalidates the `CONTRACTS` section of its class page while `RATIONALE` and
`GOTCHAS` stay `FRESH`. Under the whole-page model any edit invalidated
everything.

**RQ-2 is resolved here:** mixed freshness within a page is acceptable and must
be *surfaced*, not prevented. Requiring all-fresh-or-none would re-impose the
whole-page invalidation this design removed and serialize the hottest pages
behind one lock.

---

## Scope

- `SectionKind` — import from TASK-2279, do not redefine.
- `WikiSection` (frozen): `kind`, `body: str` (markdown),
  `sources: tuple[SourceDigest, ...]` scoped to THIS section, `token_estimate`,
  `generated_at`, `generator: GeneratorInfo`,
  `state: Literal["FRESH", "STALE", "REGENERATING"]`, plus
  `coherence_group: str` (RQ-2) = digest of this section's `(node_id, digest)`
  multiset.
- `SourceDigest`: `node_id`, `digest`, `digest_scope` (TASK-2273).
- `WikiPage` (frozen): `page_id` (stable hash of `(repo, scope_uri)`),
  `scope: NodeRef`, `sections: Mapping[SectionKind, WikiSection]`.
- **Invalidation (§6.2):** on re-index, per **section**, if any
  `SourceDigest.digest` no longer matches → `FRESH → STALE`. **Never
  eager-regenerate** — a section regenerates only when a request selects it and
  `budget.max_llm_calls > 0`.
- Vertical scoping: invalidate the section on the node's class page and on every
  ancestor page, **not** siblings; cap with `max_ancestor_depth` and mark
  deeper ancestors `STALE` without cascading.
- Horizontal scoping: only sections whose declared sources actually moved.
- **Single-flight keyed on `(page_id, section_kind)`** — not `page_id` — so two
  requests needing different sections of one hot page do not serialize.
- `mixed_freshness` computation: set when selected sections do not share a
  `coherence_group`, surfaced on the bundle (RQ-2).
- Serving matrix from §6.3 — all four `(allow_stale, max_llm_calls)` cells.

**NOT in scope**:

- `AncestrySummaryPolicy` (T10) and `RationalePolicy` (T11) — deferred to v1.1.
  This task provides the store and the invalidation, not the policies.
- Actually calling an LLM to generate a section body. Wire the seam
  (`GeneratorInfo`, `REGENERATING`), leave generation to T10/T11.
- Migrating or touching FEAT-260's wiki. See "Does NOT Exist" — that is a
  different taxonomy and a different store.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/wiki_cache.py` — new (`WikiSection`, `WikiPage`, `SourceDigest`,
  `GeneratorInfo`, invalidation).
- `packages/ai-parrot/src/parrot/knowledge/retrieval/single_flight.py` — new (Redis single-flight).
- `packages/ai-parrot/tests/knowledge/retrieval/test_wiki_cache.py`, `packages/ai-parrot/tests/knowledge/retrieval/test_single_flight.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.models import NodeRef
from parrot.knowledge.retrieval.digest import derive_digest, DigestScope
from parrot.knowledge.retrieval.sections import SectionKind   # TASK-2279
```

### Existing Signatures to Use

```python
# Redis lock precedent to copy (there is NO lock in knowledge/ or eventbus)
# parrot/auth/oauth2_base.py:519
lock = self.redis.lock(...)
# parrot/auth/jira_oauth.py:523 — same pattern

# Unrelated, do not confuse: a FILE-based store lock, not Redis
# parrot/knowledge/wiki/project.py:47
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]
```

### Does NOT Exist

- **`parrot.knowledge.retrieval` does not exist yet.** You may be the task that
  creates it. There is nothing to extend, no base class waiting for you.
- **`RoutingDecision` EXISTS but is NOT ours.** It belongs to
  `parrot/bots/mixins/intent_router.py:378` (LLM intent routing). This feature's
  model is **`RetrievalRoutingDecision`**. Never import or extend the former.
- **`UniversalNode` has no `repo`, `rev`, `digest`, `line_span`, or `qualname`
  field.** Verified: `parrot/knowledge/graphindex/schema.py`. Do not write code
  that reads them. Line spans live in `domain_tags["lineno"/"end_lineno"]`;
  symbol kind lives in `domain_tags["symbol_type"]`.
- **There is no symbol trie or symbol table.** `graphindex/resolve.py` is a
  cross-domain *embedding-similarity* stage emitting `mentions` edges — it does
  NOT resolve names. Do not `from parrot.knowledge.graphindex.resolve import`
  anything expecting lookup.
- **`NodeKind` has no `Module`/`Class`/`Function` members.** The real set is
  `DOCUMENT SECTION SYMBOL CONCEPT RATIONALE SKILL WIKI_PAGE RUN CLAIM`.
- **`WikiPage` / `WikiSection` do not exist.** `parrot/knowledge/wiki/
  models.py` (FEAT-260) has `WikiPageCategory`, `WikiConfig`,
  `SourceManifestEntry`, `WikiSearchResult`, `WikiLintReport` — a **different
  taxonomy and a different store**. Do NOT extend, import, or migrate it. The
  two coexist (spec §14.3).
- **`SourceManifestEntry` is file-level, not node-level.** It holds
  `file_hash` (SHA-1 of the whole file) + `mtime`. It is NOT the
  section-scoped `(node_id, digest)` model this task needs.
- **There is no Redis single-flight lock to reuse.** None in `knowledge/`, none
  in the eventbus integration. Copy the redis-py `.lock()` pattern from
  `auth/oauth2_base.py:519`. This is in-scope new code (spec §6.3).
- **`wiki_write_lock()` is file-based and store-wide** — the wrong granularity
  and the wrong mechanism. Do not use it for section single-flight.

---

## Implementation Notes

### Pattern to Follow

Key the single-flight on `(page_id, section_kind)` from the very first commit.
It is one tuple versus one string, and §6.2 is explicit that keying on
`page_id` alone serializes different sections of a hot page — precisely the
thundering-herd-after-a-large-merge case the lock exists for.

For ancestor invalidation, walk `parent_id` upward with a depth cap and a
visited set. Uncapped ancestor cascade is the expensive direction §6.2 warns
about, and a cyclic parent chain in a real index would hang re-index.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- **Never eager-regenerate** (§6.2). A test must prove that marking a section
  `STALE` triggers no LLM call and no generation.
- Redis access must be async and optional: with no Redis configured, fall back
  to an in-process `asyncio.Lock` and log the degradation rather than failing.

### References in Codebase

- Spec §6.1 (page model, SectionSelector), §6.2 (invalidation, both axes),
  §6.3 (serving matrix), §6.4 (wiki is not authoritative), §9 OQ-5, §9.1 RQ-2,
  §14.3.

---

## Acceptance Criteria

- [ ] Editing one method marks that class page's `CONTRACTS` `STALE` while
      `RATIONALE` and `GOTCHAS` stay `FRESH`.
- [ ] Sibling sections and sibling pages are NOT invalidated.
- [ ] Ancestor invalidation respects `max_ancestor_depth`; a cyclic
      `parent_id` chain terminates.
- [ ] Marking `STALE` triggers **no** regeneration and no LLM call.
- [ ] Single-flight is keyed on `(page_id, section_kind)`: two different
      sections of one page regenerate concurrently; two requests for the SAME
      section serialize to one regeneration.
- [ ] `mixed_freshness` is set when selected sections disagree on
      `coherence_group`, and false when they agree (RQ-2).
- [ ] All four rows of the §6.3 serving matrix behave as tabulated.
- [ ] With no Redis configured, falls back to an in-process lock and logs it.
- [ ] No import from `parrot.knowledge.wiki` — asserted by test.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_wiki_cache.py
def test_method_edit_stales_only_contracts_section(): ...
def test_siblings_not_invalidated(): ...
def test_ancestor_depth_capped_and_cycle_safe(): ...
async def test_stale_does_not_eager_regenerate(spy_llm): ...
def test_mixed_freshness_flag(): ...
@pytest.mark.parametrize("allow_stale,max_llm_calls,expected", [...])
async def test_serving_matrix(allow_stale, max_llm_calls, expected): ...
def test_no_import_from_knowledge_wiki(): ...

# packages/ai-parrot/tests/knowledge/retrieval/test_single_flight.py
async def test_different_sections_same_page_do_not_serialize(): ...
async def test_same_section_serializes_to_one_regeneration(): ...
async def test_falls_back_to_in_process_lock_without_redis(caplog): ...
```

---

## Agent Instructions

1. Read the spec section(s) named in **Context** before writing code. The spec
   is the SSOT; this task file is a view onto it.
2. Write the tests first (see **Test Specification**), watch them fail, then
   implement. TDD is not optional here — every one of these tasks encodes an
   invariant.
3. Do NOT modify anything under `parrot/knowledge/graphindex/` or
   `parrot_tools/multistoresearch/`. L0 is consumed **read-only** (spec §1.2)
   and FEAT-217/FEAT-379 are untouched by design (spec §5.0). If you believe a
   change there is required, STOP and record it in the Completion Note instead.
4. Run `pytest packages/ai-parrot/tests/knowledge/retrieval/ -v`, then `ruff check` and `mypy` on the files you
   touched. Paste real output into the Completion Note — no claims without
   evidence.
5. Commit once, message: `feat(FEAT-435): <what> (TASK-<NNN>)`.
6. Fill in the Completion Note. If you hit an ambiguity, record it there rather
   than inventing a resolution.

---

## Completion Note

Implemented `SourceDigest`, `GeneratorInfo`, `WikiSection`, `WikiPage`,
`compute_coherence_group`, `compute_page_id`, `invalidate_section`,
`invalidate_page`, `invalidate_ancestors`, `compute_mixed_freshness`,
`ServingDecision`/`resolve_serving_decision` in `wiki_cache.py`, and
`SingleFlight` in `single_flight.py`.

**Single-flight design (true dedup, not just mutual exclusion):**
`SingleFlight.run_once()` tracks in-flight `asyncio.Future`s keyed on
`(page_id, section_kind)`; concurrent callers for the SAME key join the
SAME future (share the result/exception) rather than each acquiring a
lock and redundantly re-running the factory. An optional Redis lock layer
(copied pattern from `auth/oauth2_base.py:519`, not imported) adds
cross-process coordination when a redis client is configured; with none,
it degrades to in-process-only dedup and logs once at construction.
Verified `test_same_section_serializes_to_one_regeneration` asserts the
factory call count is exactly 1 across 3 concurrent callers (not just
that they don't overlap).

**`invalidate_ancestors` walk:** ancestor invalidation only ever follows
`parent_id` upward (never sideways to siblings), capped at
`max_ancestor_depth`, with a `visited` set that breaks a cyclic
`parent_id` chain rather than hanging — verified with a deliberate 2-node
cycle fixture (`test_cyclic_parent_chain_terminates`).

**RQ-2 (`mixed_freshness`):** `coherence_group` is a digest of a section's
own `(node_id, digest)` multiset, stamped at construction; two sections
sharing sources (even across different `SectionKind`s) share a group.
`compute_mixed_freshness` is a pure set-cardinality check over selected
sections' groups — no all-fresh-or-none gate anywhere.

**Test output:**
```
$ pytest packages/ai-parrot/tests/knowledge/retrieval/ -v
======================= 171 passed, 6 warnings in 6.37s ========================
```
(18 new tests across `test_wiki_cache.py` and `test_single_flight.py`.)

**Lint:**
```
$ ruff check packages/ai-parrot/src/parrot/knowledge/retrieval/ packages/ai-parrot/tests/knowledge/retrieval/
All checks passed!
```

**Mypy:** zero errors attributable to `knowledge/retrieval`.

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-20
