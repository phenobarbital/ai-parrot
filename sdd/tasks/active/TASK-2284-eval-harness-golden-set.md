# TASK-2284: Golden set + eval harness + routing regression gate + head-to-head vs FEAT-217

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL
**Depends-on**: TASK-2278, TASK-2281
**Assigned-to**: unassigned
**Spec task ref**: T13 (spec §10)

---

## Context

Spec §7. "Routing decisions are worthless without measurement. Ship the
harness with the feature, not after."

This task carries more weight than a normal test task, because three deferred
decisions are explicitly gated on its output:
- **T6b** (durable pgvector/HNSW) ships only if `FlatL2` misses the latency
  target (OQ-9).
- **T7b** (speculation) ships only on a p95 win that justifies the extra
  expansion cost (§4.4).
- **Deprecating FEAT-217** is decided by the head-to-head, not assumed (OQ-8 /
  §5.0).

§7 is also explicit about *how* to measure: **reference-based, not
LLM-judged.** LLM-as-judge evaluation in this literature suffers documented
position, length, and trial biases severe enough to flip reported win rates;
narrow margins from such judging are not evidence.

---

## Scope

- **Golden set**: ≥150 queries over ai-parrot (+ Fieldsync where available),
  hand-labelled with `QueryClass` and a reference answer node set. Must cover
  all seven rules R1–R7 and both languages (ES/EN). Stored as a committed data
  file with a `version` field.
- **Routing metrics**: per-class precision/recall of the decision list;
  escalation rate; **wasted-work ratio** (cost of escalated path ÷ cost of
  correct-first-time path).
- **Retrieval metrics**: node-set recall@k against the reference. Reference-based
  only.
- **Latency**: p50/p95/p99 per `QueryClass`, plus the headline number — the
  **fraction of traffic answered without any traversal or LLM call**. That
  number is the §4.4 hypothesis under test.
- **Regression gate**: a routing-rule change that improves one class must not
  degrade another beyond a set tolerance. Wire it as a runnable check, not a
  manual ritual.
- **Head-to-head (OQ-8)**: same golden set through
  `GraphExpandedRetriever.search()` and through this layer; report both. Treat
  a narrow margin as inconclusive rather than a win.
- Report the measured p50s against §5.1's `< 15 ms` and §5.2's `< 120 ms`
  **provisional** targets, and state plainly whether T6b is warranted.

**NOT in scope**:

- **No LLM-as-judge scoring.** §7 rules it out with reasons. Reference-based
  node-set recall only.
- Do not gate CI on the latency numbers. They are provisional (spec §13
  explicitly excludes them from acceptance criteria); the gate is the routing
  regression tolerance.
- Do not modify FEAT-217 to make the comparison easier. Read-only (§5.0).
- Do not implement T6b/T7b/T8 based on the results. Report; the decision is the
  user's.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/eval/__init__.py`, `packages/ai-parrot/src/parrot/knowledge/retrieval/eval/harness.py`,
  `packages/ai-parrot/src/parrot/knowledge/retrieval/eval/metrics.py` — new.
- `packages/ai-parrot/src/parrot/knowledge/retrieval/eval/golden_set.json` (or `.yaml`) — new, versioned.
- `packages/ai-parrot/tests/knowledge/retrieval/test_eval_harness.py` — new.
- `artifacts/logs/feat-435-eval-<date>.md` — the measured report (project
  convention: save evidence to `artifacts/logs/`).

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.classifier import QueryClassifier, QueryClass
from parrot.knowledge.retrieval.policies.vector_seed import VectorSeedPolicy
# head-to-head baseline — READ-ONLY, do not modify
from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
```

### Existing Signatures to Use

```python
# parrot/knowledge/graphindex/retriever.py — the FEAT-217 baseline (untouched)
class GraphExpandedRetriever:
    def __init__(self, graph, nodes, embedder, hybrid_search,
                 signal_config, communities): ...
    async def search(self, query, seed_top_k, expansion, budget
                     ) -> GraphRetrievalResult: ...
class ExpansionConfig(BaseModel):
    max_hops: int = 2; decay_base: float = 0.7
    min_signal_threshold: float = 0.1; max_expanded_nodes: int = 50
    include_community_centroids: bool = False
    allowed_edge_kinds: Optional[list[str]] = None
class BudgetConfig(BaseModel):
    max_tokens: int = 8000; tokens_per_node_estimate: int = 200
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
- **No existing eval harness for GraphIndex retrieval.** `parrot/scripts/
  benchmark_reranker.py` computes MRR for *rerankers* (`:126`) — different
  target, but read it for the metric-computation style.
- **No golden set exists.** You are creating it. It is data, and it must be
  committed and versioned, not generated at runtime.
- **`GraphStats` may be a minimal local model** (TASK-2278) rather than
  something from `graphindex/analytics.py`. Use whatever TASK-2278 defined.

---

## Implementation Notes

### Pattern to Follow

Build the harness so a single command produces the whole report, and so the
golden set is loadable independently of the harness — a labelled query set is
the durable asset here and will outlive this implementation.

Be scrupulous about the head-to-head being fair: same pinned workspace, same
`seed_top_k`, same token budget, both retrievers cold. And report the
wasted-work ratio even when it is unflattering — §7 exists precisely so the
routing hypothesis can be falsified.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- The golden set's ≥150 queries must be genuinely hand-labelled. A generated or
  self-labelled set measures the classifier against itself and is worthless as
  a gate.
- Save the measured report under `artifacts/logs/` per project workflow.

### References in Codebase

- Spec §7 (the whole section — metrics, the anti-LLM-judge rule, the
  regression gate), §4.4 (expected effect, stated as a hypothesis), §5.0
  (head-to-head), §9 OQ-8/OQ-9, §13.

---

## Acceptance Criteria

- [ ] Golden set has ≥150 queries, covers R1–R7 and both ES and EN, is
      committed and carries a `version`.
- [ ] Per-class precision/recall, escalation rate, and wasted-work ratio are
      all computed and reported.
- [ ] Node-set recall@k is reference-based; **no LLM-as-judge anywhere** —
      asserted by a test that no client/LLM import exists in `eval/`.
- [ ] p50/p95/p99 reported per `QueryClass`, plus the traversal-free/LLM-free
      traffic fraction.
- [ ] Regression gate runs as a command and fails on a cross-class degradation
      beyond tolerance.
- [ ] Head-to-head vs `GraphExpandedRetriever` reported, with a narrow margin
      declared inconclusive rather than a win.
- [ ] The report states whether T6b is warranted by the measured p50.
- [ ] FEAT-217 files are unmodified (`git diff` proves it).
- [ ] Report saved to `artifacts/logs/`.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_eval_harness.py
def test_golden_set_has_150_plus_and_covers_all_rules(): ...
def test_golden_set_covers_both_languages(): ...
def test_no_llm_import_in_eval_package(): ...
def test_wasted_work_ratio_computation(): ...
def test_recall_at_k_against_reference(): ...
def test_regression_gate_fails_on_cross_class_degradation(): ...
async def test_head_to_head_runs_both_retrievers(): ...
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
