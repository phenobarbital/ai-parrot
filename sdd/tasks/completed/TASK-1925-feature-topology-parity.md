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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: Confirmed FEAT-377 (retry edge/attempt counter, definition.py/
flow.py/session_state.py conflicts) still NOT on `dev` — no landed
mechanism to compose with; wired the topology WITHOUT the retry edge
per the documented degradation.

`definition.py`: extended `build_dev_loop_definition(*, revision=False,
feature=False)` — a second boolean flag mirroring the existing
`revision` precedent exactly (chosen over a `mode` enum specifically so
the bug/revision bodies gained ONLY a new early-return branch, nothing
inside them changed — verified via `test_bug_topology_unchanged`, a
literal node+edge snapshot of the pre-FEAT-378 bug/revision graphs).
`_build_feature_definition()` adds the 9-node/16-edge feature graph
(spec §2 diagram) with `_CEL_IS_FEATURE`/`_CEL_FEEDBACK_ESCALATE`/
`_CEL_FEEDBACK_ACCEPT` predicates; a `_CEL_FEEDBACK_RETRY`-shaped edge is
deliberately NOT defined (documented inline: `FeedbackRouterNode.
_retry_allowed()` unconditionally returns `False` today, so it would be
permanently dead code).

`flow.py`: added `_is_feature`/`_feedback_escalate`/`_feedback_accept`
Python predicate callables alongside the existing `_is_bug`/`_qa_passed`
family (same module, same un-exported convention).

`factories.py`: +4 factories (`dev_loop.planner`/`synthesis`/
`feedback_router`/`feature_handoff`) plus a new `wiki_toolkit` passthrough
param for `feature_handoff_factory`.

`runner.py`: `build_dev_loop_feature_flow()` mirrors
`build_dev_loop_revision_flow` verbatim (declarative-materialize-then-
explicit-wire pattern); `DevLoopRunner.run()` now accepts `Union[WorkBrief,
FeatureBrief]` and dispatches a `FeatureBrief` to a new `_run_feature()`
method (mirrors `run_revision`'s lazy-build-and-reuse `_feature_flow`
lifecycle) — the `WorkBrief` body is byte-unchanged, only wrapped by an
`isinstance` guard at the top. Fixed a real generalization gap in
`_close_host`'s PR-url extraction (`result.responses.get(
"deployment_handoff")`) to also check `"feature_handoff"` — required for
`RunClosed.pr_url` to populate correctly on the feature-mode path.
Documented a genuine, unavoidable modeling gap: `RunCreated.work_kind`'s
closed `Literal["bug","enhancement","new_feature"]` (TASK-1918
deliberately did not extend it) has no "feature" value — `_run_feature`
passes the structural placeholder `"bug"`, commented as never
semantically read on this path (no Jira-issuetype selection happens in
feature-mode).

`intent_classifier.py`: `_load_brief` now routes through `parse_brief`
(TASK-1918) instead of `WorkBrief.model_validate(_json)` directly, adding
`ctx["feature_brief"]` as a third resolution-order key; a validated
`FeatureBrief` is returned as-is (no allowlist/path-traversal checks —
those are `WorkBrief`-specific) and published to `shared["feature_brief"]`.
Invalid `FeatureBrief`s fail via Pydantic's own `_document_path_must_be_
readable` validator (a `ValidationError`, which subclasses `ValueError`)
inside `_load_brief` — always before any node dispatch, satisfying "fails
before dispatch" without new validation logic.

Tests: split feature-mode coverage across `test_declarative_flow.py`
(declarative definition/parity/CEL suite — `test_definition_feature_graph`,
`test_bug_topology_unchanged`, CEL semantics) and a new
`test_feature_flow.py` (integration — `test_definition_parity_feature_mode`
comparing the declarative definition's node/edge set against the real
`build_dev_loop_feature_flow`'s imperative wiring; classifier routing;
3 end-to-end `flow.run_flow()` runs with stubbed node `execute()`s
covering happy-path/escalate/accept_with_notes; `test_feature_flow_
feedback_retry` skip-marked pending FEAT-377/A). Added 3 tests to
`test_runner.py` covering `run()`'s `Union` dispatch (WorkBrief path
unchanged, FeatureBrief routes to `_run_feature`, missing-deps raises).
Discovered and worked around a pre-existing `monkeypatch.setattr("dotted.
string.path", ...)` fragility (`test_lazy_import.py`'s aggressive
`sys.modules` purge/restore leaves the dotted-string resolver's
`__import__` fast-path pointing at a stale module in specific
orderings) twice — fixed by patching already-imported module/class
objects directly instead of dotted strings, not by touching
`test_lazy_import.py` itself (out of scope, pre-existing, and the same
class of flake — `test_models_module_is_pure` — reproduces identically
on the pre-TASK-1925 tree).

Full dev_loop suite: 729 passed, 1 skipped (FEAT-377/A retry test),
1 pre-existing unrelated failure (`test_models_module_is_pure`,
test-order flake, reproduced before this task's changes too).
`ruff check` clean on every modified/created file.

**Deviations from spec**: none — the retry-edge omission is the spec's
own documented degradation for FEAT-377/A's absence, not a deviation.
