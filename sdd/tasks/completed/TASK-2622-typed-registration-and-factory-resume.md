# TASK-2622: Typed Checkpoint Registration and Factory-Based Resume

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. `FlowStateSerializer` currently pre-registers only
`AIMessage`, so typed dev-loop results (`ResearchOutput`, `DevelopmentOutput`,
…) degrade on round-trip. `AgentsFlow.resume()` rebuilds graphs via
`from_definition()` (`flow.py:1419`), which cannot reproduce the dev flows'
callable predicates, OR joins, and live node dependencies. This task adds
process-wide type registration and a factory-based resume path that seeds a
caller-created live context. Precedent exists in non-ancestor commit
`8d7657b23` — review its full diff and adapt; do NOT cherry-pick blindly.

---

## Scope

- Implement `register_checkpoint_type(model_cls, tag=None) -> str`: a
  process-wide registry read by every `FlowStateSerializer` instance at
  construction, exported from `parrot.bots.flows.core.checkpoint`.
- Extend `AgentsFlow.resume()` with keyword-only `flow_factory:
  Callable[[FlowDefinition], AgentsFlow] | None` and `seed_context:
  FlowContext | None`. When `flow_factory` is given, resume calls it with the
  checkpoint's definition instead of `from_definition()`.
- Validate the rebuilt graph: every completed node ID recorded in the
  checkpoint must exist in the factory-built graph; a missing node raises
  instead of silently dropping recovery state.
- Seed `seed_context` (when provided) with the checkpoint's completed node IDs
  and deserialized typed results; the caller's live objects in that context
  are never overwritten by checkpoint data.
- Unit tests for registration round-trip, factory-preserved explicit routing,
  and missing-node rejection.

**NOT in scope**: fingerprint metadata and `expected_input` validation
(TASK-2623), required-write barrier (TASK-2624), any `parrot/flows/dev_*`
change (TASK-2625+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py` | MODIFY | Process-wide type registry consumed in `__init__` |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py` | MODIFY | Export `register_checkpoint_type` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `resume(flow_factory=..., seed_context=...)`, completed-node validation, context seeding |
| `packages/ai-parrot/tests/flows/checkpoint/test_factory_resume.py` | CREATE | Unit tests (path: follow existing checkpoint test module layout) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows import AgentsFlow, FlowContext
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py (re-exports from .flow / .core)

from parrot.bots.flows.core.checkpoint import (
    CheckpointNotFoundError,
    CheckpointStore,
    FlowCheckpoint,
    FlowCheckpointer,
    FlowStateSerializer,
    get_checkpoint_store,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:209
class AgentsFlow(PersistenceMixin):
    def __init__(self, name, *, definition=None, agent_registry=None,
                 on_node_event=None, checkpoint=False, checkpoint_retention=None,
                 checkpoint_history=None, checkpoint_include_responses=False,
                 durable=False, checkpoint_store=None, durable_store=None,
                 flow_id=None, **kwargs) -> None: ...  # line 258

    @classmethod
    async def resume(cls, flow_id, checkpoint_id=None, *, agent_registry,
                     store=None, durable_store=None) -> "AgentsFlow": ...  # line 1332
    # resume currently rebuilds via:
    #   flow = cls.from_definition(checkpoint.definition, agent_registry=...)  # line 1419

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py:61
class FlowStateSerializer:
    def __init__(self) -> None: ...   # only AIMessage pre-registered today

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py:89
class FlowCheckpoint(BaseModel): ...

# packages/ai-parrot/src/parrot/bots/flows/core/context.py:177
class FlowContext:
    def mark_completed(self, ...) -> ...: ...
```

### Does NOT Exist
- ~~`AgentsFlow.resume(flow_factory=...)`~~ — being added by THIS task; only
  precedent is non-ancestor commit `8d7657b23` (review with `git show 8d7657b23`).
- ~~`register_checkpoint_type()`~~ — being added by THIS task.
- ~~`FlowStateSerializer.register_global()`~~ or similar — no global registry
  API exists yet; today serializers only pre-register `AIMessage`.

---

## Implementation Notes

### Pattern to Follow
- Study `git show 8d7657b23` (tested `flow_factory` resume + checkpoint type
  registration for another custom explicit-edge flow). Adapt to current `dev`
  code — the surrounding `flow.py` has changed.
- Registry: module-level dict `{tag: model_cls}` + idempotent registration
  (same class/tag re-registration is a no-op; conflicting re-use of a tag
  raises `ValueError`).

### Key Constraints
- Async throughout; `self.logger`, no prints; Google-style docstrings + type
  hints (Pydantic where structured).
- Existing `resume()` call shape must keep working (new params keyword-only
  with defaults).
- Restoration must preserve Pydantic types — a registered type that fails to
  round-trip is an error, not a silent string fallback.

---

## Acceptance Criteria

- [ ] `register_checkpoint_type` exported from `parrot.bots.flows.core.checkpoint`
- [ ] `resume(flow_factory=...)` rebuilds via the factory, not `from_definition()`
- [ ] Rebuilt graph missing a checkpointed completed node raises
- [ ] `seed_context` receives completed IDs + typed results; live objects untouched
- [ ] Spec tests `test_resume_flow_factory_preserves_explicit_graph`,
  `test_resume_factory_rejects_missing_completed_node`,
  `test_registered_dev_models_round_trip` (core part) pass
- [ ] Existing checkpoint/flow suites still pass: `pytest packages/ai-parrot/tests -k "checkpoint or flow" -x -q`
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
async def test_resume_flow_factory_preserves_explicit_graph(checkpoint_store):
    """Callable predicates / OR joins / back-edges survive factory resume."""
    # build explicit-edge flow, run to partial completion, resume with factory,
    # assert routing behavior identical and completed nodes skipped.

async def test_resume_factory_rejects_missing_completed_node(checkpoint_store):
    with pytest.raises(Exception):  # narrow to the error type you introduce
        await AgentsFlow.resume(..., flow_factory=factory_missing_node)

def test_register_checkpoint_type_round_trip():
    register_checkpoint_type(MyModel)
    s = FlowStateSerializer()
    assert isinstance(s.loads(s.dumps(MyModel(...))), MyModel)
```

Use execution counters — assert the pre-resume node actually ran once and does
not run again (no vacuous cache assertions).

---

## Agent Instructions

1. Read spec §2, §3 Module 1, §6, §7. 2. Verify contract anchors with grep
before coding. 3. Review `git show 8d7657b23` in full. 4. Update per-spec index
`sdd/tasks/index/dev-flow-node-caching.json` → `in-progress`. 5. Implement,
test, then move this file to `sdd/tasks/completed/` and set index `done`.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-31
**Notes**: Reviewed `git show 8d7657b23` in full (non-ancestor precedent) and
adapted it to current `dev` `flow.py`/`serializer.py`. Added a process-wide
`_DEFAULT_TYPES` registry + `register_checkpoint_type()` (idempotent for the
same class/tag, raises `ValueError` on a conflicting re-registration of an
already-claimed tag — stricter than the precedent, matches spec's emphasis on
never silently degrading a routed result). `FlowStateSerializer._registry` is
now a `ChainMap({}, _DEFAULT_TYPES)` so registration order doesn't matter.
`AgentsFlow.resume()` gained keyword-only `flow_factory` (rebuilds via the
caller's builder instead of `from_definition()`, validates every checkpointed
completed node exists in the rebuilt graph, raises `ValueError` listing
missing node ids otherwise) and `seed_context` (seeds a caller-supplied live
`FlowContext` in place via `mark_completed()` only — which never touches
`shared_data`/`agent_registry`/`synthesis_client`/`trace_context` — instead of
constructing a fresh internal context, so the caller's live objects for the
new process are never overwritten by checkpoint data). `flow_factory=None`
and `seed_context=None` preserve the historical behavior exactly (verified by
test + explicit code path).

10 new tests in `test_factory_resume.py` covering: flow_factory preserving
explicit routing (predicates/OR-join), missing-node rejection, backward
compatibility with `flow_factory=None`, no-re-execution of completed nodes on
resume, `seed_context` receiving completed ids/results, `seed_context` live
objects surviving untouched, `seed_context` continuing from a partial
frontier, `register_checkpoint_type` round-trip, order-independence (a
serializer built *before* registration still sees it via the `ChainMap`), and
conflicting-tag rejection. Full `packages/ai-parrot/tests/flows/checkpoint`
suite passes (80 passed, 2 pre-existing postgres-integration failures
unrelated to this change — confirmed by running the same tests against a
clean stash of this worktree). `ruff check` clean on all 4 touched files
(fixed a pre-existing `__all__` sort issue in `checkpoint/__init__.py` while
touching that list). Note: this environment's `.venv` editable install points
at the main repo path rather than this worktree, and `parrot.utils.types`
required a one-time local Cython build (`python setup.py build_ext --inplace`
in `packages/ai-parrot/`, gitignored build artifacts) to import `parrot` at
all — both pre-existing environment conditions, unrelated to this feature,
worth flagging for whoever runs CI/other tasks in this worktree next.

**Deviations from spec**: none
