# TASK-2611: Attach FlowLifecycleAdapter in all four flow builders

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1, fixing spec §1 Finding 1.

`FlowLifecycleAdapter` translates `AgentsFlow` node events into typed FEAT-176
lifecycle events, which is how OTel spans and `NodeFailedEvent` reach the
global registry. It is attached in **exactly one** of the four flow graph
builders. The other three look cloned from a pre-adapter template.

Consequence today: **dev-flow emits zero lifecycle events.** No spans, no
failure events, no observer visibility at all. This task alone ends that
blind spot and is independently valuable — it does not depend on the rest
of the feature.

---

## Scope

- Add a `lifecycle_events: bool = True` keyword parameter to
  `build_dev_loop_revision_flow`, `build_dev_loop_feature_flow` and
  `build_dev_flow`.
- In each, after the `AgentsFlow(...)` construction, attach a
  `FlowLifecycleAdapter` when the flag is True and assign
  `flow._lifecycle_adapter` (adapter instance or `None`) — mirroring
  `build_dev_loop_flow` exactly.
- Write the two unit tests below.

**NOT in scope**: the `RunLedgerRecorder`, the per-run registry (TASK-2616),
any change to `FlowLifecycleAdapter` itself, and any change to
`build_dev_loop_flow` (already correct — use it as the reference).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | Add flag + attachment to both builders |
| `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py` | MODIFY | Add flag + attachment to `build_dev_flow` |
| `packages/ai-parrot/tests/flows/test_builder_lifecycle_parity.py` | CREATE | The parity regression guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/telemetry.py:48
from parrot.bots.flows.flow.telemetry import FlowLifecycleAdapter
# also exported here — verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:82,147
from parrot.bots.flows import FlowLifecycleAdapter
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
def build_dev_loop_flow(                       # line 285
    ...,
    publish_flow_events: bool = True,          # line 293
    lifecycle_events: bool = True,             # line 294  <-- the flag to copy
): ...

# THE REFERENCE IMPLEMENTATION — copy this shape verbatim (flow.py:431-449):
flow = AgentsFlow(name=name, on_node_event=publisher)          # line 431
flow._run_id_holder = run_id_holder    # type: ignore[attr-defined]
flow._event_publisher = publisher      # type: ignore[attr-defined]
flow._dev_loop_definition = definition # type: ignore[attr-defined]

lifecycle_adapter = None                                        # line 442
if lifecycle_events:
    from parrot.bots.flows.flow.telemetry import (  # noqa: PLC0415
        FlowLifecycleAdapter,
    )

    lifecycle_adapter = FlowLifecycleAdapter()
    flow.add_node_event_listener(lifecycle_adapter)
flow._lifecycle_adapter = lifecycle_adapter  # type: ignore[attr-defined]

# THE THREE BUILDERS TO FIX (each currently ends at _dev_loop_definition):
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
def build_dev_loop_revision_flow(              # line 132
    ..., publish_flow_events: bool = True,     # line 141
): ...
    flow = AgentsFlow(name=name, on_node_event=publisher)   # line 177

def build_dev_loop_feature_flow(               # line 195
    ..., publish_flow_events: bool = True,     # line 209
): ...
    flow = AgentsFlow(name=name, on_node_event=publisher)   # line 292

# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py
def build_dev_flow(                            # line 68
    ..., publish_flow_events: bool = True,     # line 84
): ...
    flow = AgentsFlow(name=name, on_node_event=publisher)   # line 148

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow:
    def add_node_event_listener(self, callback) -> None: ...  # line 400
        # accepts a sync OR async callable (event, node_id, info)
```

### Does NOT Exist

- ~~`AgentsFlow.add_lifecycle_adapter()`~~ — no such method. Use
  `add_node_event_listener`.
- ~~`AgentsFlow.lifecycle_adapter`~~ (public attribute) — the convention is the
  private `flow._lifecycle_adapter`, set by the builder with a
  `# type: ignore[attr-defined]` comment.
- ~~A shared helper that already does this attachment~~ — there is none; the
  block is inline in `build_dev_loop_flow`. Extracting a helper is
  acceptable and arguably better, but then **all four** builders must use it.

---

## Implementation Notes

### Pattern to Follow

Copy `flows/dev_loop/flow.py:442-449` into each of the three builders,
immediately after the existing `flow._dev_loop_definition = definition` line.
Keep the function-local import with its `# noqa: PLC0415` — that is the
existing convention here and avoids an import cycle.

### Key Constraints

- Default `lifecycle_events=True`, so existing callers gain telemetry with no
  change at their call sites.
- Always set `flow._lifecycle_adapter`, even when `None`. The parity test
  reads it, and leaving the attribute unset would raise `AttributeError`.
- Do not reorder the existing `_run_id_holder` / `_event_publisher` /
  `_dev_loop_definition` assignments; `build_dev_loop_flow` documents why
  `_definition` is deliberately NOT bound (it would switch the scheduler to
  AND-join mode and break OR-join routing).
- If you extract a shared helper instead of copy-pasting, update
  `build_dev_loop_flow` to use it too — four call sites, one implementation.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:431-449` — reference implementation
- `packages/ai-parrot/src/parrot/bots/flows/flow/telemetry.py:48` — the adapter

---

## Acceptance Criteria

- [ ] All three builders accept `lifecycle_events: bool = True`.
- [ ] All four builders set `flow._lifecycle_adapter` to a
      `FlowLifecycleAdapter` by default, and to `None` when the flag is False.
- [ ] `pytest packages/ai-parrot/tests/flows/test_builder_lifecycle_parity.py -v` passes.
- [ ] Existing flow tests still pass:
      `pytest packages/ai-parrot/tests/flows/ -v`
- [ ] `ruff check` clean on both modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/test_builder_lifecycle_parity.py
import pytest

from parrot.bots.flows.flow.telemetry import FlowLifecycleAdapter


def _builders():
    """All four builder callables, so a newly-added builder that forgets the
    adapter fails here rather than silently going dark in production."""
    from parrot.flows.dev_flow.flow import build_dev_flow
    from parrot.flows.dev_loop.flow import build_dev_loop_flow
    from parrot.flows.dev_loop.runner import (
        build_dev_loop_feature_flow,
        build_dev_loop_revision_flow,
    )
    return [
        build_dev_loop_flow,
        build_dev_loop_revision_flow,
        build_dev_loop_feature_flow,
        build_dev_flow,
    ]


@pytest.mark.parametrize("builder", _builders(), ids=lambda b: b.__name__)
def test_all_builders_attach_lifecycle_adapter(builder, fake_dispatcher):
    """Regression guard for FEAT-479 Finding 1: the adapter was attached in
    only 1 of 4 builders, so dev-flow emitted zero lifecycle events."""
    flow = builder(dispatcher=fake_dispatcher, publish_flow_events=False)
    assert isinstance(
        getattr(flow, "_lifecycle_adapter", None), FlowLifecycleAdapter
    ), f"{builder.__name__} did not attach a FlowLifecycleAdapter"


@pytest.mark.parametrize("builder", _builders(), ids=lambda b: b.__name__)
def test_builders_honour_lifecycle_events_false(builder, fake_dispatcher):
    """Opting out must be honoured, and the attribute must still exist."""
    flow = builder(
        dispatcher=fake_dispatcher,
        publish_flow_events=False,
        lifecycle_events=False,
    )
    assert getattr(flow, "_lifecycle_adapter", "MISSING") is None
```

**Fixture note**: each builder has its own required arguments. Inspect each
signature (`build_dev_loop_flow` line 285, `build_dev_loop_revision_flow`
line 132, `build_dev_loop_feature_flow` line 195, `build_dev_flow` line 68)
and reuse whatever dispatcher fixture the existing tests under
`packages/ai-parrot/tests/flows/` already provide, rather than inventing one.
Pass `publish_flow_events=False` so no Redis connection is attempted.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm the four builder line numbers
   and the reference block before editing; the file churns
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2611-attach-lifecycle-adapter-all-builders.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Added `lifecycle_events: bool = True` to `build_dev_loop_revision_flow`
and `build_dev_loop_feature_flow` (`runner.py`) and to `build_dev_flow`
(`dev_flow/flow.py`), copying the `build_dev_loop_flow` reference block
(`flow.py:440-448`) verbatim into each, immediately after the existing
`flow._dev_loop_definition = definition` assignment. All four builders now
set `flow._lifecycle_adapter` (a `FlowLifecycleAdapter` instance, or `None`
when the flag is False). Added the parametrized regression test
`test_builder_lifecycle_parity.py` covering all four builders and both the
default-True and opt-out-False cases (8 tests, all passing). Full
`packages/ai-parrot/tests/flows/` suite: 1459 passed, 3 pre-existing
failures unrelated to this change (verified failing identically on the
pre-change tree — `test_qa_codereview.py`, `test_secondopinion_brief.py`,
`test_subagent_parity.py`), 10 skipped. `ruff check` on the diff introduces
no new findings (confirmed against the unchanged file's pre-existing 70
findings, including the same `RUF100`-on-`noqa:PLC0415` pattern already
present in the reference implementation this task copies from).

**Deviations from spec**: none.
