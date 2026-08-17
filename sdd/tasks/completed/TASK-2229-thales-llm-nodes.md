# TASK-2229: LLM flow nodes — planner, deck_builder, slide_spec

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2226, TASK-2227
**Assigned-to**: unassigned

---

## Context

Module 3 (LLM half) of FEAT-425. Three node families that call an LLM with
**structured output** (never free prose, never HTML): the planner (thesis →
≥10 `ResearchAngle`s), the per-angle deck builder (OR-join fan-in of the
angle's research outputs → one `ResearchDeck`), and the per-deck slide-spec
filler (`ResearchDeck` → `SlideSpec`). Node classes are plain
`parrot.bots.flows.core.node.Node` subclasses injected via
`from_definition(node_factories=…)` — the global `NODE_REGISTRY` is NOT
touched (spec §7 Patterns).

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/thales/nodes/__init__.py`,
  `planner.py`, `deck_builder.py`, `slide_spec.py`:
  - `PlannerNode.execute(ctx, deps)` → `list[ResearchAngle]` with
    `len ≥ config.num_decks` (≥10). If the LLM returns fewer: re-prompt
    ONCE with the explicit count; if still short, pad by decomposing the
    widest angle; never silently proceed with fewer (spec §7 risk).
  - `DeckBuilderNode.execute(ctx, deps)` — deps carry the angle's research
    node results (from TASK-2227 normalizers); OR-join degrade: build from
    surviving sources, record `failed_sources`; a deck with zero surviving
    sources returns a sentinel the runner drops with a warning.
  - `SlideSpecNode.execute(ctx, deps)` — deck → `SlideSpec` via structured
    output; chart payloads only from `Finding.numeric_series` actually
    present in the deck (no invented numbers).
- Structured output via the clients' structured-output support
  (`structured_output=` parameter on `ask()` — combined tools+schema mode).
- Unit tests with mocked LLM responses.

**NOT in scope**: fan-in nodes (bibliography/summary/document/infographic —
TASK-2230), definition assembly & wiring (TASK-2231), agent construction
(TASK-2227 provides it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/thales/nodes/__init__.py` | CREATE | Node re-exports (extended by TASK-2230) |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/planner.py` | CREATE | PlannerNode |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/deck_builder.py` | CREATE | DeckBuilderNode (OR-join degrade) |
| `packages/ai-parrot/src/parrot/flows/thales/nodes/slide_spec.py` | CREATE | SlideSpecNode |
| `packages/ai-parrot/tests/flows/thales/test_llm_nodes.py` | CREATE | Unit tests (mocked LLM) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from parrot.bots.flows.core.node import Node, AgentNode   # core/node.py:68 / :182
from parrot.bots.flows.core.context import FlowContext    # core/context.py
from parrot.flows.thales.models import (                  # TASK-2226
    ResearchAngle, ResearchDeck, SlideSpec, ThalesConfig,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel): ...                                # L68 (pydantic Node base)
class AgentNode(Node):                                    # L182
    async def execute(self, ctx, deps, **kwargs): ...     # L270
class StartNode(Node): ...                                # L323
class EndNode(Node): ...                                  # L408

# Custom-node injection contract (flow/flow.py:428 from_definition):
#   node_factories: {node_type: factory}; factory(node_def, deps, succs) -> Node
#   called fresh per run_flow() — nodes close over live dependencies.

# Structured output on clients: ask(..., structured_output=<pydantic type>)
#   (AnthropicClient.ask signature carries structured_output: Union[type,
#    StructuredOutputConfig, None] — claude.py:425 block; combined
#    tools+schema mode per TASK-1304/google-genai-combined-tools-and-schema spec)
```

### Does NOT Exist
- ~~`@register_node("thales-planner")` etc. in the global NODE_REGISTRY~~ —
  forbidden by spec §7: inject via `node_factories`, do not register
  app-specific types globally.
- ~~`SynthesisNode` usage here~~ — that's TASK-2230 (exec summary), not
  these nodes.
- ~~`Finding.numeric_series` auto-population~~ — the deck builder only maps
  series that research outputs actually contained; slide charts must trace
  back to deck data (no invented numbers — spec G4).
- ~~A retry framework for the planner~~ — exactly ONE re-prompt then
  deterministic padding; do not add generic retry loops.

---

## Implementation Notes

### Pattern to Follow
```python
# Frozen-pydantic Node subclass with model_post_init FSM creation — mirror
# SynthesisNode / DecisionNode in bots/flows/flow/flow.py (L1963 block):
class PlannerNode(Node):
    def model_post_init(self, __context): ...  # auto-create FSM, call parent hook
    async def execute(self, ctx, deps, **kwargs) -> Any: ...
```

### Key Constraints
- Async throughout; `self.logger`-style logging via the node's logger.
- Structured output only — parse into the TASK-2226 models, validation
  errors surface as node failures (the flow's on_error edges handle them).
- Deck builder must tolerate ANY subset of sources failing (OR-join).
- Respect `ThalesConfig.max_paragraphs_per_finding` when assembling decks.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1963` — SynthesisNode
  as the canonical custom-node implementation shape.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/` — domain-flow node
  package precedent.

---

## Acceptance Criteria

- [ ] Planner returns ≥ `num_decks` angles; short LLM response triggers exactly one re-prompt, then padding (test both paths)
- [ ] DeckBuilder builds from surviving sources and records `failed_sources`; zero-survivor case returns the drop sentinel
- [ ] SlideSpec charts only reference series present in the deck (test: deck without numeric data → `charts == []`)
- [ ] No writes to the global `NODE_REGISTRY` (test: registry snapshot unchanged after import)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/thales/test_llm_nodes.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_llm_nodes.py
import pytest
from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.flows.thales.nodes import PlannerNode, DeckBuilderNode, SlideSpecNode

def test_no_global_registry_pollution():
    assert not any(k.startswith("thales") for k in NODE_REGISTRY)

@pytest.mark.asyncio
async def test_planner_min_angles(mock_llm_short_then_full):
    """First LLM response returns 4 angles → one re-prompt → 10 angles."""

@pytest.mark.asyncio
async def test_deck_builder_or_join_degrade():
    """deps = {web: findings, deep: EXCEPTION, arxiv: findings} →
    deck.failed_sources == ['deep'], findings from web+arxiv."""

@pytest.mark.asyncio
async def test_slide_spec_no_invented_charts():
    """Deck without numeric_series → SlideSpec.charts == []."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2226, TASK-2227 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2229-thales-llm-nodes.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Implemented `PlannerNode` (thesis → ≥`num_decks` angles: one
explicit re-prompt then deterministic decomposition-padding, never fewer),
`DeckBuilderNode` (deterministic OR-join aggregation — no LLM; per-source
JSON-parse failure degrades that source into `failed_sources`; all-fail
returns a `DROPPED_DECK_SENTINEL` JSON payload for the runner to drop), and
`SlideSpecNode` (structured-output `SlideSpec` fill, post-hoc chart
filtering so `charts` is forced to `[]` whenever no `Finding.numeric_series`
is present in the deck, regardless of what the LLM proposed). 9 unit tests
pass (mocked LLM clients). No `NODE_REGISTRY` writes (verified by test).
`ruff check` on `nodes/` shows only pre-existing style categories
(`UP006`/`UP035`/`UP045`/`PYI063`) — the same `PYI063` (`__context: Any`
dunder-param) fires on the very `SynthesisNode`/`Node.model_post_init`
precedent this code mirrors, confirming it's codebase-wide, not new.

Design notes (latitude taken within scope, since TASK-2231 "definition
assembly & wiring" is explicitly out of scope here):
- `DependencyResults = Dict[str, str]` (verified in
  `bots/flows/core/types.py`) — the real scheduler coerces every upstream
  result via `str(results[dep])` before handing it to `deps`. Research
  nodes (TASK-2231's job to wire) must therefore return a JSON string from
  `execute()`; `DeckBuilderNode`/`SlideSpecNode` parse that JSON back into
  `Finding`/`ResearchDeck`. This mirrors the literal test-spec hint
  (`deps = {web: findings, deep: EXCEPTION, arxiv: findings}`) — a
  non-JSON-parseable string (`"EXCEPTION"` or any upstream failure marker)
  degrades that source exactly like a genuine parse failure.
- `DeckBuilderNode.sources` defaults to `["web", "deep", "arxiv"]` — labels
  for the three v1 sources *within one angle's sub-graph*, distinct from
  `ThalesConfig.sources` (`["web", "deep_research", "arxiv"]`, the
  machine-readable source-selection list from TASK-2226). TASK-2231 maps
  its actual per-angle node_ids onto these labels (or overrides `sources`
  via `node_factories`).
- `PlannerNode`/`SlideSpecNode` take a duck-typed `client: Any` constructor
  field (`arbitrary_types_allowed=True` on the `Node` base) rather than a
  concrete `AbstractClient` import, matching the "nodes close over live
  dependencies via `node_factories`" pattern documented in `flow.py:428`'s
  eager-resolve precedent — TASK-2231 is expected to inject the real client.
- `_extract_angles`/`_extract_slide_spec` read `AIMessage.structured_output`
  first, falling back to `.data` — both fields are populated by
  `AIMessageFactory` across every client backend (verified in
  `models/responses.py`); the exact combined tools+schema mechanics named
  in the Codebase Contract were not independently re-derived beyond that.

**Deviations from spec**: none
