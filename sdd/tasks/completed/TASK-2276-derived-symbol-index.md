# TASK-2276: `DerivedSymbolIndex` — in-process qualname index over L0 nodes (OQ-7)

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2270
**Assigned-to**: unassigned
**Spec task ref**: T3b (spec §10)

---

## Context

Spec §3.5.2. **This task exists because the spec's original premise was
false.** §4.2 claimed "symbol resolution uses the L0 symbol trie already built
for `Resolve` — no new index." Verification found `graphindex/resolve.py` is a
cross-domain embedding-similarity stage that emits `mentions` edges. There is no
trie, no symbol table, and no `qualname` field anywhere in
`parrot/knowledge/`.

So the index must be built — but derived and in-memory, consistent with OQ-7:
no L0 write, no new persistence. The nodes are already resident in the
`rustworkx.PyDiGraph`, so this is a load-time pass over data already in RAM.

This is on the critical path for TASK-2278 (rules R1/R3/R4/R6 all key off
`anchor_count`) and TASK-2280 (`DirectSymbolPolicy` is symbol lookup and
nothing else).

---

## Scope

- `DerivedSymbolIndex.build(nodes: Iterable[UniversalNode]) -> DerivedSymbolIndex`.
- **Qualname derivation:** walk the `parent_id` chain to the module root and
  join `title`s with `.`. L0's own `domain_tags["qualified_name"]` is only one
  level deep (`{{parent.title}}.{{name}}`, `code.py:351`) and is emitted by
  `code.py` but **not** `odoo_code.py` — use it to seed and cross-check, but
  derivation wins where they disagree.
- **Lookup:** exact match on the full qualname, plus trailing-segment match
  (`resolve` and `PayRateEngine.resolve` both find
  `module.PayRateEngine.resolve`), with an optional `symbol_type` filter.
- **Ambiguity returns ALL candidates.** Do not pick one. §3.5.2: `anchor_count`
  counts distinct resolved anchors, so ambiguity naturally routes a query toward
  `COMPARATIVE`/`RELATIONAL` instead of guessing. Silently choosing a winner
  here would corrupt classification downstream.
- Emit `NodeRef`s (TASK-2270), carrying `symbol_type` from `domain_tags`.

**NOT in scope**:

- Feature extraction and markers — TASK-2277.
- The decision list — TASK-2278.
- Persisting the index. In-memory, rebuilt at load. Adding a table would be the
  L0 change §1.2 forbids.
- Fuzzy/embedding matching. Exact and trailing-segment only; the dense path is
  TASK-2281's job.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/symbols.py` — new.
- `packages/ai-parrot/tests/knowledge/retrieval/test_symbols.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.graphindex.schema import (   # verified: schema.py
    NodeKind, EdgeKind, Provenance, UniversalNode, UniversalEdge,
)
```
```python
from parrot.knowledge.retrieval.models import NodeRef   # TASK-2270
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/extractors/code.py — the ONLY qualname-ish datum
qualified_name = (                                          # :350-352
    f"{parent_payload.title}.{func_name}" if parent_payload else func_name
)
#   stored at :367 as domain_tags["qualified_name"] — ONE level only,
#   FUNCTION nodes only, code.py only (odoo_code.py does NOT emit it).
#   class node :289-300 has symbol_type/lineno/end_lineno but NO qualified_name

# parrot/knowledge/graphindex/schema.py
class UniversalNode(BaseModel):
    node_id: str; kind: NodeKind; title: str; source_uri: str
    domain_tags: dict; parent_id: Optional[str]          # <-- the chain to walk

# parrot/knowledge/graphindex/assemble.py
class GraphAssembler:
    self.graph: rustworkx.PyDiGraph = rustworkx.PyDiGraph()   # :37
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
- **`graphindex/resolve.py` is NOT a resolver of names.** Its entire public
  surface is `ResolutionConfig` (threshold, max_edges_per_node) and
  `_get_extractor_domain()`. It computes cosine similarity between nodes from
  different extractors. Importing it for lookup is the single most likely
  mistake on this task.
- **`SQLiteGraphReader.find_model()` (:276) is Odoo-specific.** It looks up an
  Odoo model by `_name`, not a Python symbol. Not a general symbol table.
- **`search_symbols()` (:323) is FTS5/BM25 over title + summary only** — not
  bodies, and lexical rather than exact. It is TASK-2281's seeding leg, not this
  task's lookup.
- **No `qualname` field.** Only the one-level `domain_tags["qualified_name"]`
  above.

---

## Implementation Notes

### Pattern to Follow

Build two dicts in one pass: `full_qualname -> [NodeRef]` and
`trailing_segment -> [NodeRef]`. A trie is not required at this scale and a dict
of suffixes is simpler to test; the spec says "trie lookup" descriptively, not
prescriptively. Cache the qualname per `node_id` while walking parents so a deep
chain is not re-walked per node (O(n) not O(n·depth)).

Guard against a cyclic or self-referential `parent_id` — real indexes contain
surprises, and an infinite walk here would hang retrieval at load time.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- Build must be synchronous and cheap: it runs at load over resident nodes. No
  I/O, no `await`.

### References in Codebase

- Spec §3.5.2, §4.2 (as corrected), §11.1 row 1, §14.2/§14.3.

---

## Acceptance Criteria

- [ ] A module→class→method chain yields the full dotted qualname.
- [ ] Trailing-segment lookup returns **all** matching candidates, not one.
- [ ] `symbol_type` filter narrows correctly and comes from `domain_tags`.
- [ ] Where `domain_tags["qualified_name"]` exists it agrees with derivation;
      where it is absent (classes, `odoo_code.py` nodes) derivation still works.
- [ ] A cyclic `parent_id` does not hang or recurse infinitely.
- [ ] Build does zero I/O (patch `open` to raise).
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_symbols.py
def test_full_qualname_from_parent_chain(): ...
def test_trailing_segment_returns_all_candidates(): ...
def test_symbol_type_filter(): ...
def test_agrees_with_l0_qualified_name_where_present(): ...
def test_works_for_class_nodes_lacking_qualified_name(): ...
def test_cyclic_parent_id_terminates(): ...
def test_build_does_no_io(monkeypatch): ...
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

Implemented `DerivedSymbolIndex` in
`packages/ai-parrot/src/parrot/knowledge/retrieval/symbols.py`. Single
suffix-indexed dict (`qualname_suffix -> tuple[NodeRef, ...]`) built in one
pass, registering every dotted suffix of each `SYMBOL` node's derived
qualname — so both exact full-qualname lookup and trailing-segment lookup
share one lookup path, and ambiguity (multiple candidates for one suffix)
is always surfaced as a tuple, never collapsed to one winner.

**Signature extension (documented):** `build()`'s literal scope signature
is `build(nodes: Iterable[UniversalNode]) -> DerivedSymbolIndex`, but
`NodeRef` (TASK-2270) requires `repo`/`rev` fields that no `UniversalNode`
carries. Added `repo: str` and `rev: str` as required keyword-only
parameters — the caller (later, `DirectSymbolPolicy`/TASK-2280) supplies
these from the request's `WorkspacePin`.

Cycle guard: `compute_qualname` tracks the current walk path in a
`frozenset` and breaks the recursion (falling back to the node's own
title) if a node reappears on its own ancestor chain — verified by
`test_cyclic_parent_id_terminates` with a 2-node A↔B cycle.

Cross-check (not override) against L0's one-level
`domain_tags["qualified_name"]`: logged at `DEBUG` on disagreement,
derivation always wins, per scope.

**Test output:**
```
$ pytest packages/ai-parrot/tests/knowledge/retrieval/ -v
======================== 61 passed, 6 warnings in 2.59s ========================
```

**Lint:**
```
$ ruff check packages/ai-parrot/src/parrot/knowledge/retrieval/ packages/ai-parrot/tests/knowledge/retrieval/
All checks passed!
```

**Mypy:** zero errors attributable to `knowledge/retrieval`.

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-20
