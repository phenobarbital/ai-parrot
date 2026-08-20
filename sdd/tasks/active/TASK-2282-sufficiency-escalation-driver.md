# TASK-2282: `SufficiencyCheck` + sequential escalation driver

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2280, TASK-2281
**Assigned-to**: unassigned
**Spec task ref**: T7 (spec §10)

---

## Context

Spec §4.4. "Route optimistically, escalate on measured insufficiency" — the
alternative to pessimistic routing, and where the latency saving actually
comes from.

The ladder: `DIRECT_SYMBOL → LOCAL_FACT → RELATIONAL → GLOBAL_SUMMARY`. In the
v1 cut only the first two rungs have implemented policies, so escalation beyond
`LOCAL_FACT` must degrade honestly rather than pretend.

The third insufficiency trigger is the interesting one: `dangling` — a returned
unit references symbols not present in the bundle. §4.4 calls it "a structural
signal only a code graph can give us, and the strongest escalation trigger."
It is also the only one that needs the symbol index.

---

## Scope

- `SufficiencyCheck` with the three deterministic triggers from §4.4:
  - `coverage` — fewer than `min_units` units survived pruning.
  - `margin` — seed score distribution is flat (top-1 / top-k ratio below
    `margin_threshold`); nothing stood out.
  - `dangling` — a returned unit references symbols absent from the bundle
    (resolve via TASK-2276's index).
- `EscalationMode(StrEnum)`: `SEQUENTIAL` (default), `SPECULATIVE`, `OFF`.
  Implement `SEQUENTIAL` and `OFF`; `SPECULATIVE` must **raise
  `NotImplementedError`** — it is T7b, deferred (§10).
- `EscalationStep`: the trigger that fired, elapsed cost, policy attempted,
  whether it was used. Recorded in `RetrievalRoutingDecision.escalations`
  (§4.4) so wasted-work ratio (§7) stays measurable.
- Sequential driver: run the routed policy, evaluate sufficiency, escalate one
  rung, **decrementing the budget across steps**, stopping at `deadline_ms`.
- When the next rung's policy is not in the v1 cut, record the attempted
  escalation and stop — never silently report the unavailable policy as run.
- Admission guard for the deferred speculative mode, per §4.4 and RQ-3:
  speculation requires `budget.max_llm_calls == 0` **and**
  `len(workspace.pins) == 1`. Enforce both now so T7b inherits a decided
  contract.

**NOT in scope**:

- **`SPECULATIVE` execution — T7b, deferred to v1.1** (spec §10: "an
  optimisation with no baseline to justify it yet. Needs T13 data first").
  Define the enum member and the admission rules; raise on use.
- `PersonalizedPageRankPolicy` (T8) and `AncestrySummaryPolicy` (T10) — not in
  the v1 cut. The ladder references them; it must handle their absence.
- `SpeculationGroup` — T7b.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/escalation.py` — new.
- `packages/ai-parrot/tests/knowledge/retrieval/test_escalation.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.policies.direct_symbol import DirectSymbolPolicy
from parrot.knowledge.retrieval.policies.vector_seed import VectorSeedPolicy
from parrot.knowledge.retrieval.classifier import (
    QueryClass, RetrievalRoutingDecision,
)
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex
```

### Existing Signatures to Use

```python
# parrot/knowledge/retrieval/policies/base.py  (TASK-2280)
class RetrievalPolicyProtocol(Protocol):
    async def seed(self, req, graph) -> tuple[Seed, ...]: ...
    async def expand(self, seeds, graph, budget) -> Subgraph: ...
    async def prune(self, subgraph, budget) -> Subgraph: ...
    async def assemble(self, subgraph, budget) -> ContextBundle: ...
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
- **`PersonalizedPageRankPolicy` does not exist.** T8 is not in the v1 cut. The
  `RELATIONAL` rung has no implementation — handle its absence explicitly.
- **`AncestrySummaryPolicy` does not exist.** T10, deferred. Same for the
  `GLOBAL_SUMMARY` rung.
- **`SpeculationGroup` does not exist and must not be built here.**
- **`asyncio.timeout` vs `wait_for`:** on Python 3.11 `asyncio.timeout()` is
  available; use it for the deadline rather than hand-rolling a timer.

---

## Implementation Notes

### Pattern to Follow

§4.4 says "the loser is cancelled on `SufficiencyCheck` resolution, not
awaited" — that is a speculative-mode requirement, so it does not apply here,
but write the sequential driver so cancellation semantics are already correct
(`asyncio.timeout` + proper task cleanup). That way T7b is a genuine addition
rather than a rewrite.

Budget decrementing across steps is easy to get subtly wrong: subtract elapsed
wall-time from `deadline_ms` before the next rung, and assert in a test that
three escalations cannot collectively exceed the original deadline.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- **INV-5:** the driver must return the best partial result within
  `deadline_ms`, flagged `truncated=True`, rather than overrun. This is the
  task where INV-5 is most likely to be violated.

### References in Codebase

- Spec §4.4 (ladder, triggers, escalation modes, admission rules), §9 OQ-4,
  §9.1 RQ-3, INV-5, §7 (wasted-work ratio).

---

## Acceptance Criteria

- [ ] Each trigger (`coverage`, `margin`, `dangling`) fires in isolation, with
      a fixture per trigger.
- [ ] `dangling` uses the symbol index to detect a missing call target.
- [ ] Escalation stops at `deadline_ms` and sets `truncated=True`.
- [ ] Budget decrements across steps: N escalations cannot exceed the original
      deadline in aggregate.
- [ ] Every escalation is recorded in `escalations` with trigger, cost, and
      whether it was used.
- [ ] Escalating to an unimplemented rung records the attempt and stops — it
      does NOT report the unavailable policy as having run.
- [ ] `EscalationMode.SPECULATIVE` raises `NotImplementedError`.
- [ ] Speculation admission rejects `max_llm_calls > 0` **and** rejects
      `len(pins) > 1` (RQ-3).
- [ ] `EscalationMode.OFF` runs exactly one policy.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_escalation.py
async def test_coverage_trigger_in_isolation(): ...
async def test_margin_trigger_flat_distribution(): ...
async def test_dangling_trigger_uses_symbol_index(): ...
async def test_escalation_stops_at_deadline_and_flags_truncated(): ...
async def test_budget_decrements_across_steps(): ...
async def test_escalations_recorded_with_trigger_and_cost(): ...
async def test_unimplemented_rung_records_attempt_not_success(): ...
def test_speculative_mode_raises_not_implemented(): ...
def test_speculation_admission_rejects_llm_calls_and_multipin(): ...
async def test_mode_off_runs_single_policy(): ...
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
