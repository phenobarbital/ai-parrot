# TASK-1915: Graph memory seams — research context, run write-back, grounded findings

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1914
**Assigned-to**: unassigned

---

## Context

Module 4 wiring (spec §3, G2 seams 2-4). With the `DevLoopGraphMemory`
facade in place (TASK-1914), wire it into the four node touchpoints so each
run reads graph context before triage, writes its outcome back at the end,
and filters hallucinated review findings — the Extract → … → **Repeat**
stage: each run makes the next run's research cheaper.

---

## Scope

- **Injection point**: extend the dev-loop construction path
  (`factories.py` / `flow.py` / `runner.py` — follow how other shared
  dependencies like the Jira client reach nodes) so an optional
  `DevLoopGraphMemory` instance (from `DevLoopGraphMemory.from_config()`)
  is available to research, close, failure and QA nodes. `None` → all seams
  no-op.
- **Seam 2 — research context** (`nodes/research.py`): before dispatch,
  `await memory.build_research_context(brief)`; when non-empty, prepend the
  context block (clearly delimited, e.g. `## Graph memory context\n...`) to
  the research dispatch prompt.
- **Seam 3 — run write-back** (`nodes/close.py`, `nodes/failure_handler.py`):
  after their existing Jira work, `await memory.publish_run_outcome(...)` —
  close publishes `outcome="succeeded"` with the QA report; failure_handler
  publishes `outcome="failed"` with the failure reason. Warning-only on
  error (the facade already guarantees this — still assert it in tests).
- **Seam 4 — grounded findings** (`nodes/qa.py`): where
  `code_review_findings` feed the gate decision, pass them through
  `memory.ground_findings(...)`; findings dropped by grounding are demoted
  into `QAReport.notes` (prefix `"[ungrounded] "`), NOT counted as
  gate-failing.
- Integration tests:
  - `test_graph_memory_disabled_noop`: unset path → node behavior
    byte-identical to today.
  - `test_graph_memory_round_trip`: run 1 writes back → run 2's research
    context contains run 1's RUN/CLAIM content.

**NOT in scope**: the facade internals (TASK-1914); prompt file changes
(TASK-1906); Arango.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | seam 2 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py` | MODIFY | seam 3 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py` | MODIFY | seam 3 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | seam 4 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` (and/or `flow.py`, `runner.py`) | MODIFY | dependency injection |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_graph_memory_seams.py` | CREATE | noop + round-trip |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory  # created by TASK-1914
```

### Existing Signatures to Use
```python
# Facade (TASK-1914):
#   await DevLoopGraphMemory.from_config(...) -> Optional[DevLoopGraphMemory]
#   await memory.build_research_context(brief: WorkBrief) -> Optional[str]
#   await memory.publish_run_outcome(run_id, report, outcome, summary) -> Optional[CommitReceipt]
#   await memory.ground_findings(findings: list[str]) -> list[str]

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
# ResearchNode.execute() ~924 lines; dispatch profile allowed_tools at ~250-252:
#   "Read, Grep, Glob, Bash, Write, SlashCommand" — do NOT add graph tools; the
#   context is INJECTED as text, the subagent gets no live graph access.

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py — DevLoopCloseNode
#   (~143 lines; Jira summary comment + transition via
#   transition_issue_with_candidates at close.py:78)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/failure_handler.py —
#   FailureHandlerNode (~178 lines; escalation comment + transition)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py —
#   code_review gate: QAReport.code_review_passed / code_review_findings
#   (models.py:487-511); review runs around lines 187-196 (autofix re-run)

# packages/ai-parrot/src/parrot/flows/dev_loop/factories.py —
#   build_dev_loop_node_factories: binds live deps into declarative nodes
#   (FEAT-250) — this is the injection pattern to follow.
```

### Does NOT Exist
- ~~any graphindex import in dev_loop nodes~~ — TASK-1914's facade is the ONLY one; nodes import the facade, never graphindex directly
- ~~graph tools in subagent `allowed_tools`~~ — context is injected text; do not grant tools
- ~~a criteria store for revisions~~ — if wiring criteria into run write-back enables TASK-1908's future source, note it; do not build extra plumbing

### Contract resolution (found during implementation, 2026-07-26)
- `WorkBrief`/`BugBrief` has no dedicated "context injection" field either
  — mirrored TASK-1911's own precedent (reusing `ResearchOutput
  .log_excerpts` for repair-loop feedback) by reusing `WorkBrief
  .description` ("Long-form incident details... embedded in the Jira
  ticket description; never forwarded to `summary`") for the graph
  context, on a LOCAL dispatch-only copy (`brief.model_copy(...)`) built
  AFTER the Jira ticket description is already constructed from the
  original `brief` — so the graph context never leaks into the Jira
  ticket text, only into the LLM dispatch prompt.
- `build_dev_loop_revision_flow`/`DevLoopRunner.__init__` (`runner.py`)
  also call `build_dev_loop_node_factories` directly (for the revision
  graph's `qa`/`close`/`failure_handler` nodes) — both needed the same
  `graph_memory` parameter threaded through, even though neither is
  explicitly named in this task's Scope prose (only inferred from "and/or
  flow.py, runner.py" in the Files table). The revision graph has no
  `research` node, so seam 2 does not apply there.
- The construction call site (`DevLoopGraphMemory.from_config()`) was
  intentionally NOT wired into `cli/devloop/bootstrap.py` (not in this
  task's — or any FEAT-377 task's — file list): `build_dev_loop_flow`/
  `build_dev_loop_node_factories`/`DevLoopRunner` all accept
  `graph_memory` as an externally-supplied optional instance, exactly
  like `dispatcher`/`jira_toolkit` — activating it in the CLI bootstrap
  is a follow-up, not required by any acceptance criterion here (all of
  which test the four nodes + factories, not the CLI).

---

## Implementation Notes

### Key Constraints
- Every seam is a strict no-op when the facade is `None` — the
  disabled-noop integration test must assert identical node outputs.
- Research context is prepended, budget-capped by the facade — the node
  does not re-truncate.
- Demotion in seam 4 must keep `code_review_passed` consistent: a report
  whose only failures were ungrounded findings passes the review gate.
- Follow FEAT-250's factory injection pattern rather than adding globals.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` — dependency binding pattern
- `packages/ai-parrot/tests/flows/dev_loop/integration/test_pool_e2e.py` — integration harness style

---

## Acceptance Criteria

- [ ] `DEV_LOOP_GRAPH_MEMORY_PATH` unset → all four nodes behave exactly as today (test-asserted)
- [ ] Set → research brief contains the graph context block
- [ ] Close and failure nodes each publish one commit per run; publish failure never fails the node
- [ ] Ungrounded review findings demoted to notes; grounded ones still gate
- [ ] `test_graph_memory_round_trip` passes (run 2 sees run 1's memory)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
async def test_graph_memory_disabled_noop(stub_flow): ...
async def test_research_brief_contains_graph_context(stub_flow, tmp_graph_memory): ...
async def test_close_publishes_run_outcome(stub_flow, tmp_graph_memory): ...
async def test_publish_failure_does_not_fail_close(stub_flow, broken_memory, caplog): ...
async def test_ungrounded_findings_demoted(stub_flow, tmp_graph_memory): ...
async def test_graph_memory_round_trip(stub_flow, tmp_graph_memory): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1914 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `factories.py`: `build_dev_loop_node_factories(..., graph_memory=None)`
  forwarded into `research_factory`/`qa_factory`/`close_factory`/
  `failure_factory` (`DeploymentHandoffNode`/`DevelopmentNode`/
  `RevisionHandoffNode` untouched — no seam there).
- `flow.py`: `build_dev_loop_flow(..., graph_memory=None)` forwarded to
  `build_dev_loop_node_factories`.
- `runner.py`: `build_dev_loop_revision_flow(..., graph_memory=None)`
  forwarded the same way; `DevLoopRunner.__init__` gained
  `graph_memory=None` (stored `self._graph_memory`), forwarded into the
  lazily-built revision flow inside `run_revision`.
- `nodes/research.py` (seam 2): `graph_memory` ctor param; in `execute()`,
  builds a LOCAL `dispatch_brief` (never touching the original `brief`
  used for the Jira ticket description) with
  `f"{brief.description}\n\n## Graph memory context\n{context}"` when
  `build_research_context` returns non-empty — dispatches with
  `dispatch_brief`, not `brief`.
- `nodes/qa.py` (seam 4): `graph_memory` ctor param; right after
  `_run_code_review` (before the `cr_skipped` check, so the infra-degrade
  skip marker is never sent through grounding), grounds `cr_findings`,
  demotes dropped findings to `"[ungrounded] {finding}"` notes, and — per
  the Implementation Notes constraint — forces `cr_passed = True` when
  grounding drops EVERY finding (a report whose only failures were
  ungrounded findings must pass the review gate).
- `nodes/close.py` / `nodes/failure_handler.py` (seam 3): `graph_memory`
  ctor param; each calls `publish_run_outcome(run_id, qa_report, outcome,
  body)` — `outcome="succeeded"` (close) / `"failed"` (failure_handler) —
  right before their own terminal success return (never inside the
  Jira-call `try/except`, so a Jira failure and a graph-publish failure
  are independently handled, each already degrading on its own).
- `integration/test_graph_memory_seams.py` (new, 7 tests, all driving the
  REAL `DevLoopRunner.run()`/`build_dev_loop_flow()` stack against a real
  tmp-path SQLite plane — no mocking of the graph store):
  `test_graph_memory_disabled_noop`, `test_research_brief_contains_graph_context`
  (seeds a plane via a real `publish_run_outcome`, re-opens it with a
  FRESH facade instance — proving on-disk persistence, not just in-memory
  state — then asserts the seeded content surfaces in a new run's
  dispatch brief), `test_close_publishes_run_outcome` +
  `test_failure_handler_publishes_run_outcome` (assert exactly one commit
  each via `publisher.list_commits(run_id=...)`),
  `test_publish_failure_does_not_fail_close` (broken publisher, close
  still returns `"closed"`), `test_ungrounded_findings_demoted` (a real
  `ClaudeCodeReviewDispatcher` wrapping the stub dispatcher, a grounding
  evaluator forced to return `"revise"` for everything — asserts
  `code_review_passed is True`, `code_review_findings == []`, and the
  `"[ungrounded] ..."` note), and `test_graph_memory_round_trip` (run 1 →
  close write-back → run 2, with a fresh facade instance, sees run 1's
  content in its research brief).
- `pytest packages/ai-parrot/tests/flows/dev_loop/
  packages/ai-parrot/tests/knowledge/graphindex/ -m "not live"` (minus the
  pre-existing `hypothesis`-missing file): 1315 passed, 1 skipped, same
  one pre-existing unrelated failure noted in every prior task this
  session. Explicitly re-verified `test_close_node.py`/
  `test_failure_handler.py`/`test_qa.py`/`test_declarative_flow.py`
  (constructors changed) pass unchanged — all existing callers use
  keyword args, so the new `graph_memory` params (placed keyword-only or
  defaulted) introduced zero positional-argument ambiguity.
- `ruff check` clean on every touched file.

**Deviations from spec**: none beyond the two documented, non-behavioral
resolutions above (the `description`-field reuse for context injection,
mirroring TASK-1911's `log_excerpts` precedent; and threading
`graph_memory` through `runner.py`'s revision-flow path, inferred from
"and/or flow.py, runner.py" rather than spelled out).
