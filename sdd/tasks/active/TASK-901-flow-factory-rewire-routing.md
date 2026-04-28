# TASK-901: Rewire `build_dev_loop_flow` for kind-based routing

**Feature**: FEAT-132 — feat-129-upgrades
**Spec**: `sdd/specs/feat-129-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-898, TASK-899, TASK-900
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Insert `IntentClassifierNode` at the head of the
flow and replace the linear `bug_intake → research` edge with a
branching topology driven by `result.kind`:

- `kind == "bug"` → `bug_intake` → `research`
- `kind ∈ {"enhancement", "new_feature"}` → `research` directly
  (skipping `bug_intake`).

This is the integration point where the previous tasks' deliverables
(IntentClassifierNode, scoped-down BugIntakeNode, kind-aware
ResearchNode) become a coherent flow.

---

## Scope

- In `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py`:
  - Construct an `IntentClassifierNode` and add it to
    `nodes_in_order`.
  - Replace the existing `flow.task_flow(bug_intake.name,
    research.name)` edge with two `on_condition` predicates from
    `intent_classifier.name` to `bug_intake.name` (`kind == "bug"`)
    and to `research.name` (`kind != "bug"`).
  - Keep `flow.task_flow(bug_intake.name, research.name)` so the bug
    path still flows through Research.
  - Register the global error transition for the new node too
    (`flow.on_error(intent_classifier.name, failure.name)`).
- Extend `tests/flows/dev_loop/test_flow.py` with three routing
  tests: bug-routes-through-bug-intake,
  enhancement-skips-bug-intake, new-feature-skips-bug-intake.

**NOT in scope**:
- Predicate ordering optimisations beyond "register `bug` first" —
  spec §7 R7 already calls this out.
- Renaming the entry-point node away from `intent_classifier`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | Adapter set + branching topology. |
| `packages/ai-parrot/tests/flows/dev_loop/test_flow.py` | MODIFY | New routing tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.flow import AgentsFlow                      # __init__.py:22
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.intent_classifier import (
    IntentClassifierNode,                                    # post-TASK-898
)
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode
```

### Existing Signatures to Use

```python
# parrot.bots.flow.AgentsFlow
class AgentsFlow:
    def add_agent(self, ref): ...                            # fsm.py:397
    def task_flow(self, src, dst): ...                       # fsm.py:505
    def on_condition(self, src: str, dst: str, *, predicate): ...  # fsm.py:659
    def on_error(self, src: str, dst: str): ...              # fsm.py:645

# Current build_dev_loop_flow (post FEAT-129):
def build_dev_loop_flow(
    *,
    dispatcher: ClaudeCodeDispatcher,
    jira_toolkit: Any,
    log_toolkits: Dict[str, Any],
    redis_url: str,
    name: str = "dev-loop",
) -> AgentsFlow: ...                                         # flow.py:118

# Existing routing pattern for QA branch (template for the new branch):
flow.on_condition(qa.name, handoff.name, predicate=_qa_passed)
flow.on_condition(qa.name, failure.name, predicate=_qa_failed)
```

### Does NOT Exist

- ~~`flow.task_flow_if(...)`~~ — branching is via `on_condition`,
  not a conditional `task_flow` variant.
- ~~`AgentsFlow.add_branch`~~ — fictional; use `on_condition`.
- ~~A "default" predicate for `on_condition`~~ — write an explicit
  lambda (`lambda r: getattr(r, "kind", "bug") != "bug"`) so absent
  attributes route to bug for back-compat (paranoia: should never
  happen because IntentClassifierNode returns a WorkBrief with kind).

---

## Implementation Notes

### Pattern to Follow

```python
# flow.py — inside build_dev_loop_flow, after the existing nodes:
intent_classifier = IntentClassifierNode(redis_url=redis_url)
bug_intake = BugIntakeNode(redis_url=redis_url)
research = ResearchNode(...)
development = DevelopmentNode(...)
qa = QANode(...)
handoff = DeploymentHandoffNode(...)
failure = FailureHandlerNode(...)

nodes_in_order = [
    intent_classifier,
    bug_intake,
    research,
    development,
    qa,
    handoff,
    failure,
]

# Branching at the head:
def _is_bug(result: Any) -> bool:
    return getattr(result, "kind", "bug") == "bug"

def _is_not_bug(result: Any) -> bool:
    kind = getattr(result, "kind", "bug")
    return kind != "bug"

flow.on_condition(intent_classifier.name, bug_intake.name, predicate=_is_bug)
flow.on_condition(intent_classifier.name, research.name, predicate=_is_not_bug)

# Bug path keeps the linear edge to Research:
flow.task_flow(bug_intake.name, research.name)

# Existing edges unchanged:
flow.task_flow(research.name, development.name)
flow.task_flow(development.name, qa.name)
flow.on_condition(qa.name, handoff.name, predicate=_qa_passed)
flow.on_condition(qa.name, failure.name, predicate=_qa_failed)

# Error routing — add intent_classifier alongside the existing nodes:
for source in (intent_classifier, research, development, qa, handoff):
    flow.on_error(source.name, failure.name)
```

### Key Constraints

- Register the `bug` predicate FIRST so that, in case AgentsFlow's
  predicate evaluation order matters, the most common path wins
  immediately (spec §7 R7).
- Do NOT remove `flow.task_flow(bug_intake.name, research.name)` —
  the bug path still needs a static edge to Research.
- The test must drive predicates via the actual returned object's
  `kind` attribute (not a synthesized bool), to confirm the routing
  logic reads `WorkBrief.kind`.

### References in Codebase

- `parrot/flows/dev_loop/flow.py` (FEAT-129 post-merge) — the QA
  branch is the closest existing template.

---

## Acceptance Criteria

- [ ] `build_dev_loop_flow(...)` constructs `IntentClassifierNode` and
  registers it with `flow.add_agent`.
- [ ] Two `on_condition` edges from `intent_classifier` route bug to
  `bug_intake` and non-bug to `research`.
- [ ] `flow.task_flow(bug_intake.name, research.name)` still wires
  the bug path's continuation.
- [ ] `flow.on_error(intent_classifier.name, failure.name)` is
  registered.
- [ ] Three routing tests pass:
  `test_flow_routes_bug_through_bug_intake`,
  `test_flow_routes_enhancement_to_research_directly`,
  `test_flow_routes_new_feature_to_research_directly`.
- [ ] Full dev_loop suite stays green.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_flow.py — additions

class TestKindRouting:
    """Verifies the IntentClassifier-driven routing."""

    @pytest.mark.parametrize("kind", ["bug"])
    async def test_routes_bug_through_bug_intake(
        self, dummy_dispatcher, dummy_jira, monkeypatch, kind
    ):
        # Build a flow; instrument the bug_intake adapter to record
        # whether it ran. Drive the flow with a kind="bug" brief and
        # assert the recorder fired.
        ...

    @pytest.mark.parametrize("kind", ["enhancement", "new_feature"])
    async def test_routes_non_bug_skips_bug_intake(
        self, dummy_dispatcher, dummy_jira, monkeypatch, kind
    ):
        ...
```

The exact instrumentation (recorder pattern) should mirror the
existing tests in `test_flow.py`. If the file uses
`monkeypatch.setattr` on `_NodeAgentAdapter` instances or fakes the
underlying nodes, copy that pattern.

---

## Agent Instructions

1. Confirm TASK-898/TASK-899/TASK-900 are merged (their imports +
   behaviours are required for these wiring changes to be testable).
2. Edit `flow.py`; mirror the existing QA branching pattern.
3. Add the routing tests in `test_flow.py`.
4. Run `pytest packages/ai-parrot/tests/flows/dev_loop/test_flow.py -v`
   then the full dev_loop suite.
5. Commit; move file; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
