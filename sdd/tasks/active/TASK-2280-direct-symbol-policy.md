# TASK-2280: `DirectSymbolPolicy` — the no-traversal, no-LLM fast path

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2271, TASK-2276
**Assigned-to**: unassigned
**Spec task ref**: T5 (spec §10)

---

## Context

Spec §5.1. Symbol-table lookup → node body + immediate `Rationale` children.
No vector search, no traversal, no LLM.

This is the policy that makes the whole escalation argument work: §4.4's thesis
is that pessimistic routing (sending everything through traversal) is the
failure mode being avoided, and R1 short-circuiting to this policy is what
removes traversal from the majority of requests — *if* the traffic distribution
cooperates, which §7/T13 measures rather than assumes.

Also establishes the four-stage policy protocol every later policy implements.

---

## Scope

- `RetrievalPolicyProtocol` (§5) — `seed`, `expand`, `prune`, `assemble`, all
  async. Stages are individually skippable but **never reordered**.
- Supporting types: `Seed`, `Subgraph`.
- `DirectSymbolPolicy` with `kind: Literal["direct_symbol"]` as the union
  discriminator:
  - `seed`: `DerivedSymbolIndex` lookup only.
  - `expand`: immediate `RATIONALE` children via `EXPLAINS` edges — nothing
    else. Not depth-1 generally; specifically the rationale children.
  - `prune`: budget trim only.
  - `assemble`: `ContextUnit` per node with `origin=L0_SOURCE` (and
    `L1_RATIONALE` for rationale units), `digest` from TASK-2273, `line_span`
    from `domain_tags`.
- Content read at the pinned rev via TASK-2275's `read_at_rev`, so digests match
  the pin.
- `RATIONALE`-kind evidence carries `line_span=None` — expected and correct
  (§3.5.1 / RQ-4), not a bug to work around.

**NOT in scope**:

- Vector or FTS seeding — TASK-2281.
- Any graph traversal beyond immediate rationale children. §5.1 says no
  traversal; PPR is TASK-2282's successor task (T8, deferred).
- Escalation — TASK-2282. This policy reports its result; it does not decide to
  escalate.
- **The p50 < 15 ms target is NOT an acceptance criterion** (spec §13). Measure
  it in T13; do not build a benchmark gate here.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/policies/__init__.py`, `packages/ai-parrot/src/parrot/knowledge/retrieval/policies/base.py` — new (protocol,
  `Seed`, `Subgraph`).
- `packages/ai-parrot/src/parrot/knowledge/retrieval/policies/direct_symbol.py` — new.
- `packages/ai-parrot/tests/knowledge/retrieval/test_direct_symbol_policy.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.models import (
    ContextBundle, ContextUnit, Evidence, EvidenceOrigin, NodeRef,
    RetrievalBudget,
)
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex
from parrot.knowledge.retrieval.digest import derive_digest, DigestScope
from parrot.knowledge.retrieval.pin import read_at_rev
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/sqlite_reader.py — read-only L0 access
class SQLiteGraphReader:
    def get_node(self, node_id: str) -> Optional[dict]        # :180
    def children(self, ...)                                   # :203
    @staticmethod
    def _read_span(path, lineno, end) -> Optional[str]        # :404 (private)

# rationale linkage, from extractors/code.py:506-512
UniversalEdge(source_id=<rationale_id>, target_id=<nearest_symbol_id>,
              kind=EdgeKind.EXPLAINS)
#   NOTE the direction: rationale --EXPLAINS--> symbol.
#   To find a symbol's rationale children you traverse EXPLAINS *inbound*.
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
- **`RATIONALE` nodes have no `lineno`** (`code.py:500`), so `line_span` is
  `None` for them. Do not synthesize one, do not skip the unit.
- **The `EXPLAINS` edge points rationale → symbol, not symbol → rationale.**
  Getting the direction backwards yields an empty result on real data with no
  error. Verified at `extractors/code.py:506-512`.
- **No `GraphExpandedRetriever` reuse.** FEAT-217's retriever is untouched by
  design (spec §5.0). Do not import it "just for the seed stage".

---

## Implementation Notes

### Pattern to Follow

Define the protocol so all four stages are `async` even where this policy's
implementation is trivially synchronous — later policies genuinely need `await`,
and a protocol that changes shape later would force edits across every policy.
Keep `expand` honest: log and assert that it traverses only inbound `EXPLAINS`,
so a future refactor cannot quietly turn this into a depth-1 general expansion
and destroy the latency property that justifies R1.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).

### References in Codebase

- Spec §5.1, §5 (four-stage protocol), §3.5.1, §14.2/§14.3.

---

## Acceptance Criteria

- [ ] Performs **no** vector search and **no** FTS call — asserted with spies
      on the embedder and reader, not by inspection.
- [ ] Traverses only inbound `EXPLAINS` edges; a symbol with rationale children
      returns them, and no other neighbours appear.
- [ ] Units carry `origin=L0_SOURCE` / `L1_RATIONALE` correctly.
- [ ] `RATIONALE` units carry `line_span=None` without raising.
- [ ] Content comes from `read_at_rev`, and each unit's digest matches a
      recomputation over its own `text` (INV-2 closure by construction).
- [ ] Respects `deadline_ms`, setting `truncated=True` rather than overrunning
      (INV-5).
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_direct_symbol_policy.py
async def test_no_vector_or_fts_calls(spy_embedder, spy_reader): ...
async def test_expands_only_inbound_explains_edges(): ...
async def test_rationale_units_have_none_line_span(): ...
async def test_digest_matches_recomputation_over_served_text(): ...
async def test_respects_deadline_sets_truncated(): ...
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

*(Agent fills this in when done — include real command output, not claims.)*

**Completed by**:
**Date**:
