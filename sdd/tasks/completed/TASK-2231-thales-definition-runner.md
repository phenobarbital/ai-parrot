# TASK-2231: FlowDefinition assembly + ThalesRunner (persistence, manifest, checkpointing)

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2229, TASK-2230
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-425 — the piece that turns the parts into a product.
Two-phase execution (spec §2): phase 1 runs the planner; phase 2 assembles
the run's `FlowDefinition` with a **pure function** and executes it via
`AgentsFlow.from_definition(..., node_factories=..., checkpoint=True)`
(FEAT-399 checkpointing for long Deep Research runs). `ThalesRunner` is the
public Python API and owns persistence: every artifact through
`ArtifactStore`, mirrored to `output_dir`, indexed in `manifest.json`, and
aggregated into `ThalesResult`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/thales/definition.py`:
  - `build_thales_definition(angles: list[ResearchAngle], config:
    ThalesConfig) -> FlowDefinition` — PURE function. Emits: start → per
    angle i: M research nodes (from `config.sources`) → `deck_builder[i]`
    (OR-join: edges `on_success` from each source AND `on_error`
    continuation so a failed source doesn't block the join) →
    `slide_spec[i]` → `slide_render[i]`; global fan-ins `bibliography`,
    `exec_summary`; then `final_document`, `infographic` → end.
  - `build_node_factories(deps) -> dict[str, factory]` — closes over live
    dependencies (ArtifactStore, TemplateEngine/renderer, InfographicToolkit,
    clients, ThalesConfig) and returns `{node_type: factory(node_def, deps,
    succs) -> Node}` for every custom node type.
- Create `packages/ai-parrot/src/parrot/flows/thales/runner.py`:
  - `ThalesRunner(thesis, *, num_decks=10, sources=None, output_dir=None,
    artifact_store=None, llm=None, **kwargs)`; `async def run() ->
    ThalesResult`.
  - Phase 1 planner call; phase 2 `AgentsFlow.from_definition(...,
    agent_registry=<ephemeral from TASK-2227>, node_factories=...,
    checkpoint=True)` then `run_flow(ctx)`.
  - Per-node timeout from `config.per_node_timeout`; projected research-call
    count (`len(angles) × len(sources)`) logged BEFORE the research phase
    starts (spec §7 cost-visibility risk).
  - Persistence/manifest: deck JSONs, slide HTMLs, final doc (+ optional
    pdf), infographic refs → `ArtifactStore` + `output_dir` mirror +
    `manifest.json`; drop-with-warning handling for zero-survivor decks;
    abort only when ALL decks drop.
  - `add_progress_listener(cb)` — forwards AgentsFlow `on_node_event`.
- Update `parrot/flows/thales/__init__.py` to export `ThalesRunner`.
- Unit tests: definition shape (node/edge counts for N×M), runner manifest
  with fully mocked nodes/store.

**NOT in scope**: HTTP handler (TASK-2232); e2e integration tests
(TASK-2233); node internals (TASK-2229/2230).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/thales/definition.py` | CREATE | Pure FlowDefinition builder + node factories |
| `packages/ai-parrot/src/parrot/flows/thales/runner.py` | CREATE | ThalesRunner public API |
| `packages/ai-parrot/src/parrot/flows/thales/__init__.py` | MODIFY | Export ThalesRunner |
| `packages/ai-parrot/tests/flows/thales/test_definition.py` | CREATE | Definition-shape tests |
| `packages/ai-parrot/tests/flows/thales/test_runner.py` | CREATE | Runner/manifest tests (mocked) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from parrot.bots.flows.flow.flow import AgentsFlow               # flow/flow.py:173
from parrot.bots.flows.flow.definition import (                  # flow/definition.py
    FlowDefinition, NodeDefinition, EdgeDefinition,
)
from parrot.registry.registry import AgentRegistry               # registry/registry.py
from parrot.storage.artifacts import ArtifactStore               # storage/artifacts.py:27
from parrot.flows.thales.models import ThalesConfig, ThalesResult, ArtifactRef
from parrot.flows.thales.factories import build_agent_registry   # TASK-2227
from parrot.flows.thales.nodes import (                          # TASK-2229/2230
    PlannerNode, DeckBuilderNode, SlideSpecNode,
    BibliographyNode, ExecSummaryNode, FinalDocumentNode, InfographicNode,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                       # L173
    @classmethod
    def from_definition(cls, definition: FlowDefinition, *,   # L428
        agent_registry=None,
        node_factories: dict[str, Callable[[NodeDefinition, set, set], Node]] | None = None,
        checkpoint: bool | None = None, checkpoint_retention=None,
        checkpoint_history=None, checkpoint_include_responses=None,
        durable=None, checkpoint_store=None, durable_store=None,
        flow_id=None) -> "AgentsFlow": ...
    #   raises ValueError when agent_registry is None
    #   node types must be in NODE_REGISTRY *unless* provided via node_factories
    #   → VERIFY at implementation time how _materialize_nodes resolves
    #     factory-typed nodes vs NODE_REGISTRY (flow.py, _materialize_nodes);
    #     factories are called as factory(node_def, deps, succs) fresh per run.
    async def run_flow(self, ctx) -> FlowResult: ...      # L912 (ctx: FlowContext | str)
    def add_node_event_listener(self, callback): ...      # L373
    # on_node_event events: flow_started | node_started | node_completed |
    #   node_failed | node_skipped | flow_completed (info carries duration_ms, error, …)

# EdgeDefinition uses "from"/"to" keys (alias) — see flow.py to_definition:
#   EdgeDefinition(**{"from": ..., "to": ..., "condition": ..., "predicate": ...})
# Edge conditions: ("always", "on_success", "on_error", "on_timeout", "on_condition")
```

### Does NOT Exist
- ~~Registering thales node types in the global `NODE_REGISTRY`~~ —
  forbidden; use `node_factories` exclusively.
- ~~`AgentsFlow.run()`~~ — the method is `run_flow(ctx)`.
- ~~A global/default `AgentRegistry` singleton fallback in
  `from_definition`~~ — passing `agent_registry` is mandatory (raises
  ValueError otherwise).
- ~~`FlowDefinition(name=...)`~~ — the field is `flow` (flow name), see
  `flow.py` `to_definition` (`FlowDefinition(flow=self.name, ...)`).
- ~~A manifest/`manifest.json` helper anywhere in parrot~~ — this task
  writes it (plain `json.dumps` of `ThalesResult.model_dump()` subsets).

---

## Implementation Notes

### Pattern to Follow
```python
# Domain-flow runner precedent: parrot/flows/dev_loop/runner.py (structure
# only — dev_loop is much bigger; keep ThalesRunner lean).
# Definition building is PURE: no I/O, no clients — exhaustively testable:
def build_thales_definition(angles, config) -> FlowDefinition:
    nodes, edges = [NodeDefinition(id="start", type="start")], []
    ...
```

### Key Constraints
- `build_thales_definition` must be deterministic and side-effect free.
- `checkpoint=True` on `from_definition` (FEAT-399); pass a stable
  `flow_id` derived from the run id so resume works.
- Log projected research-call count before phase 2 (≥10 angles × M sources).
- Abort only when ALL decks drop; otherwise degrade with manifest warnings.
- `output_dir` mirroring must not assume the ArtifactStore succeeded —
  each surface persists independently; failures become warnings.

### References in Codebase
- `packages/ai-parrot/tests/flows/checkpoint/test_flow_export.py` —
  FlowDefinition round-trip expectations.
- `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` — domain
  definition-module precedent.

---

## Acceptance Criteria

- [ ] `build_thales_definition(10 angles, 3 sources)` → expected node count (1 start + 30 research + 10 deck + 10 slide_spec + 10 slide_render + bibliography + exec_summary + final_document + infographic + 1 end) and consistent edges; validates as a `FlowDefinition`
- [ ] Definition builder is pure (no I/O; property-style test with varying N/M)
- [ ] Runner logs projected research-call count before executing phase 2
- [ ] `checkpoint=True` and stable `flow_id` passed to `from_definition`
- [ ] `ThalesResult` + `manifest.json` include every artifact ref; zero-survivor decks produce warnings, not aborts (all-drop → raises)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/thales/test_definition.py packages/ai-parrot/tests/flows/thales/test_runner.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_definition.py
from parrot.flows.thales.definition import build_thales_definition
from parrot.flows.thales.models import ResearchAngle, ThalesConfig

def _angles(n):
    return [ResearchAngle(angle_id=f"a{i}", title=f"t{i}", question="q",
                          rationale="r") for i in range(n)]

def test_build_definition_shape():
    cfg = ThalesConfig(thesis="t", num_decks=10)
    d = build_thales_definition(_angles(10), cfg)
    research = [n for n in d.nodes if n.id.startswith("research-")]
    assert len(research) == 30                     # 10 angles × 3 sources
    assert any(n.id == "bibliography" for n in d.nodes)
    assert d.nodes[0].type == "start"

def test_build_definition_deterministic():
    cfg = ThalesConfig(thesis="t")
    a = build_thales_definition(_angles(10), cfg)
    b = build_thales_definition(_angles(10), cfg)
    assert a.model_dump() == b.model_dump()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2229, TASK-2230 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code (especially
   how `_materialize_nodes` resolves factory-provided node types)
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2231-thales-definition-runner.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Two significant, user-approved architecture corrections were
required (both discovered via direct verification against `dev`, not
assumption — the second only surfaced by actually running the assembled
flow end-to-end through the real `AgentsFlow` scheduler):

1. **`FlowDefinition`/`from_definition(node_factories=…)` abandoned.**
   Verified: `from_definition()` requires every node type — including
   `node_factories`-injected ones — to already be in `NODE_REGISTRY`;
   `node_factories` only overrides *construction*, never registration
   (confirmed against FEAT-250 TASK-001, the feature that introduced it).
   **User decision: Option B** — build the `AgentsFlow` programmatically
   (`add_node`/`add_edge`, "explicit-edge mode"), which also naturally
   provides the OR-join + skip-propagation semantics `DeckBuilderNode`
   needs.
2. **Programmatic mode alone didn't fully avoid `NODE_REGISTRY` either.**
   Running the built flow end-to-end surfaced `FlowNotExportableError`:
   `checkpoint=True` unconditionally calls `to_definition()` as a
   fail-fast export check (`_ensure_checkpointer`), which requires
   `NODE_REGISTRY` membership regardless of assembly mode, and also
   rejects Python-callable edge predicates (CEL strings only).
   **User decision: Option C** — register every Thales node type
   idempotently (`nodes/registry.py`, mirroring
   `parrot.flows.dev_loop.nodes.base.register_dev_loop_node`), and
   convert the one predicate-gated edge (`deck -> slide_spec`, "don't
   render a dropped deck") to a CEL string
   (`!result.contains("_thales_dropped_deck")`, verified against
   `celpy`'s actual string-extension support).

Implemented `build_thales_nodes_and_edges`/`assemble_thales_flow`
(`definition.py`) — 1 start + N×M research + N deck_builder + N slide_spec
+ N slide_render + bibliography + exec_summary + final_document +
infographic + 1 end, wired with `on_success`+`on_error` edges into each
deck_builder (OR-join) — and `ThalesRunner` (`runner.py`): phase-1
standalone `PlannerNode.execute()` call (its angle count shapes phase-2's
graph, per spec's two-phase design), projected-call-count logging,
phase-2 `assemble_thales_flow(..., checkpoint=True, flow_id=run_id)` +
`run_flow()`, then result aggregation + persistence (deck JSON + slide
HTML + final doc/pdf artifacts via `ArtifactStore`, `output_dir`
mirroring, `manifest.json`), warnings for per-angle dropped decks, and a
hard `RuntimeError` when every angle's deck was dropped. Also introduced
two node types the spec's Component Diagram names but no prior task file
covers building (`_ResearchNode` for web/deep/arxiv, `_SlideRenderNode`
wrapping TASK-2228's `render_slide`) — both private, living in this
task's own `definition.py`.

18 new unit tests pass (`test_definition.py`: 9, `test_runner.py`: 5, plus
2 registration tests + itself replacing TASK-2229's now-incorrect
`test_no_global_registry_pollution` in `test_llm_nodes.py`); full
`packages/ai-parrot/tests/flows/thales/` suite: **73 passed**. Verified
the real fix end-to-end with a throwaway (never committed) smoke script
run through pytest: the assembled flow executes via the genuine
`AgentsFlow` scheduler, `to_definition()` succeeds, and it only stops
short at a real Redis connection for the checkpoint store (expected —
no Redis in this sandbox; not a code defect). `ruff check` on every
touched file shows only pre-existing style categories
(`UP006`/`UP017`/`UP035`/`UP045`/`PYI063`). `grep -r matplotlib` empty.

**Cross-task correction**: applied the `@register_thales_node(...)`
decorator + import to TASK-2229's `PlannerNode`/`DeckBuilderNode`/
`SlideSpecNode` and TASK-2230's `BibliographyNode`/`ExecSummaryNode`/
`FinalDocumentNode`/`InfographicNode` (no `execute()` logic changed), and
replaced TASK-2229's `test_no_global_registry_pollution` (asserted the
opposite of the corrected, verified behavior). Committed separately
(`fix(agentcrew-tales-research): register all Thales node types`) from
this task's own deliverables for a clean audit trail. Spec bumped to
rev 0.2 documenting both corrections in §7.

**Deviations from spec**: See the two corrections above (both
user-approved, both required by verified `AgentsFlow` behavior, both
documented in spec rev 0.2 §7 and in `definition.py`'s module docstring).
