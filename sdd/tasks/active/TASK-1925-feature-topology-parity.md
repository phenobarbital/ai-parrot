# TASK-1925: Feature-mode topology — definition, imperative flow, factories, routing, parity

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1921, TASK-1922, TASK-1923, TASK-1924
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (topology slice). Assembles the four new nodes into the
third dev_loop topology, in BOTH declarative and imperative forms (parity is
a hard constraint — `from_definition` is AND-join, flow.py:301-307), routes
`kind == "feature"` from the classifier, and extends the runner.

---

## Scope

- `definition.py`: add feature-mode to `build_dev_loop_definition` (extend
  the existing `revision: bool` precedent with a `mode` parameter or
  equivalent — pick the shape that keeps the two existing topologies
  byte-identical; document the choice). New node-id constants + edges per
  spec diagram; new CEL predicates `_CEL_IS_FEATURE` and the feedback-router
  routing predicates (retry/escalate/accept).
- `factories.py`: +4 factories (`dev_loop.planner`, `dev_loop.synthesis`,
  `dev_loop.feedback_router`, `dev_loop.feature_handoff`).
- `flow.py`/`runner.py`: `build_dev_loop_feature_flow(...)` (imperative
  wiring re-declaring ALL feature edges — precedent
  `build_dev_loop_revision_flow`, runner.py:101); `DevLoopRunner.run()`
  accepts `FeatureBrief` (union dispatch by `kind`).
- `nodes/intent_classifier.py`: validate + route `FeatureBrief`
  (document_path readable, doc_kind coherent → `shared["feature_brief"]`,
  return kind); invalid → ValueError before any dispatch.
- Retry edge: conditional `feedback_router → development` ONLY under the
  FEAT-377/A mechanism (see contract). If FEAT-377/A is absent at
  implementation time, wire the topology WITHOUT the retry edge and mark it
  clearly (spec §7 documented degradation).
- Tests: extend the existing declarative/parity suite
  (`tests/flows/dev_loop/test_declarative_flow.py`) for feature-mode; add
  `test_bug_topology_unchanged` (bug + revision topologies identical to
  pre-feature snapshot); integration tests
  `test_feature_flow_happy_path`, `test_feature_flow_escalation` (stubbed
  dispatchers, no Jira), and `test_feature_flow_feedback_retry` (skip-marked
  if FEAT-377/A absent).

**NOT in scope**: node internals (TASK-1921..1924), CLI loader (TASK-1926),
conf keys (owned by 1920/1924).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` | MODIFY | Feature topology (declarative) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` | MODIFY | +4 factories |
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | Shared wiring if needed |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `build_dev_loop_feature_flow` + runner union |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py` | MODIFY | FeatureBrief validation + route |
| `packages/ai-parrot/tests/flows/dev_loop/test_declarative_flow.py` | MODIFY | Parity + unchanged-topology tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_feature_flow.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.flow import build_dev_loop_flow                     # verified 2026-07-27
from parrot.flows.dev_loop.runner import DevLoopRunner, build_dev_loop_revision_flow  # verified
from parrot.flows.dev_loop.models import FeatureBrief, parse_brief             # TASK-1918
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/definition.py:61  (verified 2026-07-27)
def build_dev_loop_definition(*, revision: bool = False) -> FlowDefinition: ...
# Node-id constants :36-44; CEL predicates :47-50
# (_CEL_IS_BUG, _CEL_IS_NOT_BUG, _CEL_QA_PASSED, _CEL_QA_FAILED)

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py:189
def build_dev_loop_flow(*, dispatcher, jira_toolkit, log_toolkits, redis_url, ...,
    codereview_dispatcher=None, require_deployment_approval=False) -> AgentsFlow: ...
# ⚠ from_definition is AND-JOIN (flow.py:301-307); conditional edges MUST be
#   re-declared imperatively (:332-360). Feature topology has an OR-join at
#   development (planner-entry + retry re-entry) — imperative wiring is load-bearing.

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:101
def build_dev_loop_revision_flow(*, dispatcher, jira_toolkit, git_toolkit,
    redis_url, codereview_dispatcher=None, name="dev-loop-revision",
    publish_flow_events=True) -> AgentsFlow: ...   # ← the precedent to mirror
class DevLoopRunner:                                # :156
    async def run(self, brief: WorkBrief, *, run_id=None, initial_task="",
                  extra_shared=None) -> FlowResult: ...  # :522

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/intent_classifier.py:33
class IntentClassifierNode(DevLoopNode):
    def __init__(self, *, redis_url: str, name: str = "intent_classifier"): ...  # :48
    # NO LLM classification — validates and propagates brief.kind (:62,:111,:142)

# packages/ai-parrot/tests/flows/dev_loop/test_declarative_flow.py  — existing
# declarative/parity suite to extend (located 2026-07-27; read before editing)
```

### Does NOT Exist
- ~~`build_dev_loop_definition(mode=...)` / feature topology / `_CEL_IS_FEATURE`~~ — this task creates them.
- ~~`_CEL_QA_RETRY` / `qa → development` edge / `qa_attempts` / `DEV_LOOP_QA_MAX_RETRIES`~~ —
  FEAT-377 TASK-1910/1911 (branch `feat-377-graphindex-as-engineering-devloop`),
  NOT on dev as of 2026-07-27. **Check merge status at task start** — if
  merged, the feature retry edge composes with the landed mechanism (reuse
  its CEL/attempt counter; do NOT duplicate); if not, wire without retry and
  skip-mark the retry integration test.
- ~~LLM classification in the classifier~~ — keep validate-and-propagate only.
- ~~`WorkKind` value `"feature"`~~ — `FeatureBrief.kind` is its own Literal (TASK-1918).

---

## Implementation Notes

### Pattern to Follow
`build_dev_loop_revision_flow` (runner.py:101) end-to-end: same factories,
imperative `add_edge` for every conditional, shared FlowEventPublisher/
lifecycle options. For the definition, mirror how `revision=True` swaps the
node/edge sets without touching the default path.

### Key Constraints
- Parity test must enumerate nodes AND edges (with predicates) of the
  declarative definition vs the imperative wiring and assert equality for
  ALL THREE topologies.
- `test_bug_topology_unchanged`: snapshot bug + revision definitions before
  your change (git show) and assert identity after.
- Runner union dispatch: `isinstance`/`kind` switch; `WorkBrief` path
  untouched.
- Classifier failure = clean `failed` run BEFORE any agent dispatch (spec §7).

### References in Codebase
- Spec §2 Component Diagram + Internal Behavior item 1; §4 test matrix; §5 parity criterion

---

## Acceptance Criteria

- [ ] Feature topology in definition AND imperative wiring; parity test green for all three topologies
- [ ] Bug + revision topologies byte-identical to pre-change (test)
- [ ] `kind: feature` routes classifier → planner; invalid FeatureBrief fails before dispatch
- [ ] `DevLoopRunner.run()` accepts both brief types; WorkBrief behavior unchanged
- [ ] Retry edge composes with FEAT-377/A when present; documented degradation when absent
- [ ] Integration tests pass (happy path, escalation; retry test per FEAT-377 availability)
- [ ] Full dev_loop test suite green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` clean on all modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_feature_flow.py
def test_definition_parity_feature_mode(): ...
def test_bug_topology_unchanged(): ...
def test_classifier_routes_feature(): ...
def test_classifier_invalid_document_fails_early(): ...
async def test_feature_flow_happy_path(): ...       # stubbed dispatchers, no Jira
async def test_feature_flow_escalation(): ...
@pytest.mark.skipif(FEAT_377A_ABSENT, reason="retry edge requires FEAT-377/A")
async def test_feature_flow_feedback_retry(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 diagram + item 8 parity note, §5, §7)
2. **Check dependencies** — TASK-1921..1924 completed
3. **Verify the Codebase Contract** — FIRST check FEAT-377 merge status (it
   edits definition.py/flow.py/session_state.py — expect shifted anchors and
   possibly a landed retry edge to compose with); read
   `test_declarative_flow.py` before extending
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
