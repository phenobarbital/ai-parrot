# TASK-1914: DevLoopGraphMemory facade — opt-in GraphIndex access for dev_loop

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1909
**Assigned-to**: unassigned

---

## Context

Module 4 core (spec §3, G2). dev_loop and GraphIndex have zero coupling
today. This task builds the single integration surface — a facade module —
so node changes (TASK-1915) stay thin. **Decided (spec §8)**: write-back
targets the SQLite plane only in v1; no dual publish to Arango.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py`:
  ```python
  class DevLoopGraphMemory:
      @classmethod
      async def from_config(cls, ...) -> Optional["DevLoopGraphMemory"]:
          """None unless DEV_LOOP_GRAPH_MEMORY_PATH is configured."""
      async def build_research_context(self, brief: WorkBrief) -> Optional[str]: ...
      async def publish_run_outcome(self, run_id: str, report: QAReport | None,
                                    outcome: str, summary: str) -> Optional[CommitReceipt]: ...
      async def ground_findings(self, findings: list[str]) -> list[str]: ...
  ```
- `from_config`: reads `DEV_LOOP_GRAPH_MEMORY_PATH` (new key, unset →
  `None`); builds `SQLitePersistence` + `GraphPublisher` +
  `GraphExpandedRetriever` + `GraphContextBuilder` + `GroundingEvaluator`
  the same way `build_graph_memory_toolkit` does internally (read
  `factory.py:203-236` and mirror its construction; do NOT depend on
  `parrot_tools` — the facade needs the components, not the agent toolkit).
- `build_research_context`: `GraphContextBuilder.build(task=<brief summary>)`
  → return `GraphContext.text` (or `None` when empty); budget via
  `ContextBuildConfig(max_tokens=...)`.
- `publish_run_outcome`: construct a `GraphUpdate` with one `RUN` node, one
  `CLAIM` node per verified criterion (from `report.criterion_results` where
  `passed`), edges `PRODUCED` (run→claims), `ABOUT` (run→brief entities),
  `SUPPORTED_BY` (claim→evidence where available); `agent_id="dev-loop"`,
  `run_id=run_id`, `asserted_by=<node id>`. Call `GraphPublisher.publish()`.
  ALL exceptions caught → `logger.warning`, return `None` (degrade-never-fail).
- `ground_findings`: for each finding string, `ground_claim(...)`; keep
  findings whose `decision == "grounded"`, return the kept list (callers
  demote the rest — TASK-1915).
- Unit tests with `tmp_path` SQLite store, including the disabled-noop path.

**NOT in scope**: node wiring (TASK-1915); Arango publish; prompt changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py` | CREATE | the facade |
| `packages/ai-parrot/tests/flows/dev_loop/test_graph_memory.py` | CREATE | facade unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# ALL from the graphindex package (PEP 562 lazy exports, __init__.py:63-133):
from parrot.knowledge.graphindex import (
    GraphPublisher,              # publish.py:37
    GraphUpdate, CommitReceipt,  # schema.py:226, 262 — NOT in publish.py
    GraphContextBuilder, ContextBuildConfig, GraphContext,  # context_builder.py:93,45,70
    GroundingEvaluator, GroundingResult,  # grounding.py:96,53
    NodeKind, EdgeKind, AssertionMeta, UniversalNode, UniversalEdge,
    SQLitePersistence, stable_edge_id,
)
# WRONG: from parrot.knowledge import GraphPublisher  ← knowledge/__init__.py re-exports NOTHING
```

### Existing Signatures to Use
```python
# publish.py:47,90,140
class GraphPublisher:
    def __init__(self, persistence: Any, ctx: TenantContext) -> None: ...
    async def publish(self, update: GraphUpdate) -> CommitReceipt: ...
    async def revert_commit(self, commit_id: str) -> dict[str, Any]: ...

# schema.py:250-259 — GraphUpdate fields:
#   nodes: list[UniversalNode]; edges: list[UniversalEdge]
#   removed_edges: list[tuple[str,str,str]]; removed_nodes: list[str]
#   agent_id: str (REQUIRED); run_id: Optional[str]; asserted_by: str (REQUIRED)
#   source: Optional[str]; reason: Optional[str]; op: str = "publish"

# context_builder.py:104-108, 251-255
class GraphContextBuilder:
    def __init__(self, retriever: GraphExpandedRetriever,
                 entity_resolver: Optional[object] = None) -> None: ...
    async def build(self, task: str,
                    config: Optional[ContextBuildConfig] = None) -> GraphContext: ...
# GraphContext.text / .truncated / .cited_edge_ids  (line 70)

# grounding.py:108-113, 204
class GroundingEvaluator:
    def __init__(self, retriever: GraphExpandedRetriever,
                 client: Optional[Any] = None, max_hops: int = 2) -> None: ...
    async def ground_claim(self, claim: str) -> GroundingResult: ...
# GroundingResult.decision: Literal["grounded", "revise"]  (line 74)

# factory.py:203-236 — construction recipe to MIRROR (not import the toolkit):
async def build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent",
    run_id=None, embedder=None, client=None, dimension=DEFAULT_DIMENSION) -> "GraphIndexToolkit":
# also available: make_stub_tenant_context(tenant_id) (factory.py:45),
#                 HashingGraphEmbedder(dimension) (factory.py:118)

# dev_loop models:
# QAReport (models.py:487-511), CriterionResult (475), WorkBrief (138)
```

### Does NOT Exist
- ~~`GraphPublisher.commit()`~~ — the method is `publish(update)`
- ~~`from parrot.knowledge import <anything>`~~ — package `__init__` is docstring-only
- ~~`DEV_LOOP_GRAPH_MEMORY_PATH`~~ — this task declares it (unset → facade disabled)
- ~~`parrot/flows/dev_loop/graph_memory.py`~~ — this task creates it; nothing imports graphindex from dev_loop today
- ~~`GraphExpandedRetriever` import path~~ — *(unverified — it is referenced by constructor signatures but was not in the harvested `__all__` list; check `graphindex/retriever.py` and the package exports before importing; use whatever `factory.py` uses)*

### Contract resolution (found during implementation, 2026-07-26)
- `GraphExpandedRetriever` import path confirmed: `parrot.knowledge.graphindex.retriever`
  — NOT re-exported via the package `__init__`'s lazy attrs (confirmed by
  grep), matching `mixin.py:183-195`'s own direct-module import, which
  this facade mirrors exactly (retriever built from raw `graph`/`nodes`/
  `embedder`, no `GraphIndexToolkit`).
- `factory.py`'s `build_graph_memory_toolkit` construction recipe does
  NOT itself build a `GraphExpandedRetriever`/`GraphContextBuilder`/
  `GroundingEvaluator` — those are composed by `mixin.py`'s
  `_build_graph_context` (lines 158-204), the actual pattern to mirror
  for the retriever/context-builder half. `SQLitePersistence` imports
  from `persist_sqlite.py` (not `persist.py`, which is the Arango-facing
  module) and its constructor takes a DIRECTORY (`Path(db_dir)`), one
  `<tenant_id>.db` file per tenant — `DEV_LOOP_GRAPH_MEMORY_PATH` is
  therefore a directory path, matching the existing convention.
- `GraphPublisher._stamp()` (verified by reading `publish.py:52-85`)
  auto-fills `AssertionMeta` on every node/edge lacking one, from the
  `GraphUpdate`'s own `asserted_by`/`agent_id`/`run_id`/`source` fields —
  so `publish_run_outcome` does NOT need to construct `AssertionMeta`
  per-node/edge manually; setting them on the `GraphUpdate` itself is
  sufficient (confirmed via a live publish+revert smoke test showing the
  assertion metadata was correctly attributed).
- `GraphContext.text` is NEVER empty — it always carries a header
  template (`"## Graph context\n\nTask: ...\n\n### Knowledge\n"`) even
  against a freshly-created, zero-node graph. The task's "return
  `GraphContext.text` (or `None` when empty)" therefore checks
  `context.node_ids` (empty list ⇒ nothing found), not `context.text` —
  the exact same check `GraphMemoryMixin._build_graph_context` uses
  (`if not context.node_ids: return None`). Discovered by a failing test
  before the fix.
- `publish_run_outcome`'s frozen signature (`run_id, report, outcome,
  summary` — no `brief`/entities) cannot construct the spec's literal
  "ABOUT (run→brief entities)" edge as worded (no entity data available
  at this call). Resolved by pointing ABOUT (and SUPPORTED_BY) from each
  CLAIM back to the RUN node itself — "this claim concerns/was
  evidenced by this run" — which satisfies the acceptance criterion
  ("PRODUCED/ABOUT edges present") using only data this signature
  actually receives. `asserted_by` (also not a parameter) defaults to
  `f"dev_loop:{outcome}"`.

---

## Implementation Notes

### Key Constraints
- IMPORT CYCLE HAZARD: `agent_pool.py`'s note warns that importing the
  `parrot.flows.dev_loop` package mid-init raises; if `graph_memory.py` is
  imported by nodes, import graphindex lazily INSIDE methods or at module
  level from the graphindex package only (never back into dev_loop's own
  package `__init__`).
- Degrade-never-fail: `publish_run_outcome` and `ground_findings` must never
  raise into the caller — warning + `None`/passthrough respectively.
- `TenantContext`: use `make_stub_tenant_context("default")` unless config
  provides a tenant (follow `factory.py`).
- Async throughout; Pydantic for any new config model; `self.logger`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` — the construction recipe
- `packages/ai-parrot/src/parrot/knowledge/graphindex/mixin.py` — `GraphMemoryMixin` shows the same components composed for bots (context injection pattern at `_build_graph_context`, line 158)

---

## Acceptance Criteria

- [ ] `DEV_LOOP_GRAPH_MEMORY_PATH` unset → `from_config` returns `None`
- [ ] `publish_run_outcome` writes a revertable commit (verify via `revert_commit` round-trip on tmp SQLite)
- [ ] RUN + CLAIM nodes and PRODUCED/ABOUT edges present in the persisted update
- [ ] Publish failure (e.g. closed store) → warning, returns `None`, no raise
- [ ] `ground_findings` keeps "grounded", drops "revise"
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_graph_memory.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
@pytest.fixture
def tmp_graph_memory(tmp_path):
    """SQLitePersistence-backed DevLoopGraphMemory at tmp_path/'graph.db'."""

async def test_from_config_disabled_returns_none(monkeypatch): ...
async def test_publish_run_outcome_commit_and_revert(tmp_graph_memory): ...
async def test_publish_failure_degrades_to_warning(tmp_graph_memory, caplog): ...
async def test_ground_findings_filters_revise(tmp_graph_memory): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1909 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code (especially the *(unverified)* retriever import)
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `conf.py`: added `DEV_LOOP_GRAPH_MEMORY_PATH: str = config.get(...,
  fallback="")` (not in this task's file list, but required — the facade
  reads it; same pattern as `DEV_LOOP_QA_MAX_RETRIES` in TASK-1910).
- `graph_memory.py`: `DevLoopGraphMemory` with `from_config`,
  `build_research_context`, `publish_run_outcome`, `ground_findings` —
  exact signatures per the task's Scope code block.
  - `from_config`: disabled (returns `None`) when
    `DEV_LOOP_GRAPH_MEMORY_PATH` is unset or whitespace-only; otherwise
    opens `SQLitePersistence(Path(db_dir))`, loads the graph, assembles
    it (`GraphAssembler`), embeds nodes (`HashingGraphEmbedder`), and
    composes `GraphExpandedRetriever` + `GraphContextBuilder` +
    `GroundingEvaluator` around it — no `parrot_tools`/`GraphIndexToolkit`
    dependency anywhere (verified by grep after writing).
  - `build_research_context`: budget-capped via
    `ContextBuildConfig(max_tokens=4000)`; returns `None` on empty
    results (`context.node_ids`, not `.text` — see Codebase Contract
    resolution) or on any internal exception.
  - `publish_run_outcome`: 1 RUN node + 1 CLAIM node per `passed`
    criterion; PRODUCED (run→claim), ABOUT + SUPPORTED_BY (claim→run —
    see Codebase Contract resolution for why not "brief entities").
    Handles `report=None` (still publishes the RUN node alone — a run
    that never reached QA still gets recorded). Wraps the whole body in
    `try/except Exception` → `logger.warning` + `return None`.
  - `ground_findings`: per-finding `ground_claim`, keeps `"grounded"`,
    drops `"revise"`; an evaluation error KEEPS the finding (documented
    fail-open choice — dropping a finding on an infra error would be a
    silent concession, worse than a possibly-unfounded finding surviving
    to human review).
- `test_graph_memory.py`: 12 tests against a REAL tmp_path SQLite plane
  (no mocking of the graph store itself) — disabled contract (unset,
  whitespace, enabled), publish+revert round-trip with node/edge
  assertions, only-verified-criteria-become-claims, `report=None` still
  publishes the RUN node, publish-failure degradation (asserts the
  warning log line), research-context failure degradation AND the
  empty-graph-returns-None case (which caught the `.text` vs `.node_ids`
  bug above), and 3 grounding tests (keep/drop, keep-on-error, empty list).
- Manual smoke test before writing the formal suite: a live
  publish → inspect receipt → revert_commit round-trip against a real
  tmp SQLite file, confirming commit ids, node ids, and edge tuples all
  resolve exactly as designed (kept as scratch, not committed).
- `pytest packages/ai-parrot/tests/flows/dev_loop/
  packages/ai-parrot/tests/knowledge/graphindex/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 1308 passed, 1 skipped,
  same one pre-existing unrelated failure noted in every prior task.
- `ruff check` clean on `graph_memory.py` and the new test file (the one
  `conf.py` finding is the same pre-existing, unrelated `E402` noted in
  TASK-1910/1912).

**Deviations from spec**: none beyond the two documented, evidence-based
resolutions above (ABOUT/SUPPORTED_BY targets, and the `.text` vs
`.node_ids` empty-context check) — both forced by the frozen method
signature and the graphindex component's actual behavior, not design
choices made without justification.
