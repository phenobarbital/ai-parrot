# TASK-1928: RunBundle model + builder + markdown closing-report renderer

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1927
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (v0.2 amendment), step 3. Everything a "run bundle"
needs is already captured — `SessionHost` keeps the full event-sourced
envelope log, the terminal `Snapshot` holds per-node/dispatch/gate state,
and the flow's shared state carries the rich results (`ResearchOutput`,
`QAReport`, deployment/revision dicts). What is missing is the assembly:
one exportable object plus a human-readable markdown closing report.
This task builds the pure module; TASK-1929 wires it into the runner.

---

## Scope

Create `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py` —
**pure** (no filesystem, no Redis, no network):

- **Models** (Pydantic, frozen like session_state's `_Frozen` style):
  - `NodeReport` — node_id, status, started/finished/duration_seconds,
    error, dispatcher, message_count, tool_use_count, telemetry
    (tokens/cost/turns/duration from TASK-1927's `DispatchState` fields),
    summary dict.
  - `GateReport` — kind, node_id, title, status, opened/resolved
    timestamps, resolved_by, comment.
  - `DevelopedWork` — jira_issue_key, pr_url, pr_number, feature_id,
    spec_path, worktree_path, branch, task ids/titles when available,
    qa_passed, lint_passed, code_review_passed, criteria results
    (name/passed/duration), code_review_findings, docs_artifact path
    (feature mode, when present).
  - `RunTotals` — wall-clock duration_seconds, nodes_completed/failed/
    skipped, dispatch_count, message_count, tool_use_count, aggregated
    input/output tokens and total_cost_usd (sum of available values;
    `None` when nothing was reported).
  - `RunBundle` — run_id, mode (initial/revision), work_kind, summary,
    outcome (`RunPhase` terminal value), created_at/finished_at, totals,
    nodes: List[NodeReport], gates: List[GateReport],
    developed: DevelopedWork, action_count (len of envelope log),
    generated_at.
- **Builder**: `build_run_bundle(snapshot: Snapshot,
  envelopes: Sequence[ActionEnvelope], shared: Mapping) -> RunBundle`
  - Node/gate/link data comes from `snapshot.state`; envelope log
    supplies `action_count` and anything not projected in state.
  - `shared` is read defensively (`.get`, duck-typed): `research_output`,
    `qa_report`, `deployment_result`, `revision_result`, `mode`, plus
    feature-mode keys (synthesis report, docs artifact) when they exist.
    A bundle MUST build from a failed/cancelled run where most keys are
    absent.
- **Renderer**: `render_markdown(bundle: RunBundle) -> str` — the closing
  report: header (run id, kind, outcome, duration, Jira/PR links),
  agents table (node | status | duration | dispatcher | msgs | tools |
  tokens | cost), gate audit section, "What was developed" section
  (spec/tasks/worktree/branch, QA criteria, review findings), footer
  with generated_at. Omit empty sections; never render `None` as text.

**NOT in scope**: writing files or hooking the runner (TASK-1929),
harvesting telemetry (TASK-1927), package `__init__` exports (TASK-1929).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py` | CREATE | Models + `build_run_bundle` + `render_markdown` |
| `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Anchors (2026-07-27)
```python
# session_state.py
class DispatchState(_Frozen): ...     # :177 — counters + (post TASK-1927) telemetry
class NodeState(_Frozen): ...         # :196 — status/started_at/finished_at/error/dispatch/summary
class ApprovalGate(_Frozen): ...      # :210 — full audit fields incl. resolved_by/comment
class DevLoopSessionState(_Frozen): ...  # :239 — nodes/gates/jira_issue_key/pr_url/phase/timestamps
class ActionEnvelope(_Frozen): ...    # :433 — channel/server_seq/action
class Snapshot(_Frozen): ...          # :443 — state + from_seq
# models.py
class ResearchOutput(BaseModel): ...  # :312 — jira_issue_key/spec(path)/feature_id/worktree_path/branch aliases
class CriterionResult(BaseModel): ... # :475 — duration_seconds :481, passed :484
class QAReport(BaseModel): ...        # :487 — passed/lint_passed/code_review_passed/code_review_findings
```

### Does NOT Exist
- ~~`parrot/flows/dev_loop/run_bundle.py`~~ — this task creates it.
- ~~A guaranteed `shared` schema~~ — every key is optional; failed runs
  may only have `mode`. Build defensively.
- ~~`SynthesisReport` / docs-artifact keys on dev~~ — created by
  TASK-1922/1924 (may or may not have landed); read duck-typed, never
  import their symbols as hard dependencies.

---

## Implementation Notes

- Follow session_state's `_Frozen` config (`frozen=True, extra="forbid"`)
  for the new models; Google-style docstrings + strict type hints.
- Keep the module import-light: `session_state` and `models` only from
  the dev_loop package; no `conf`, no I/O — testable in isolation.
- Markdown: plain tables + `##` sections; the report must be readable as
  a standalone file (it becomes `{run_id}.report.md` in TASK-1929).
- Duration formatting helper (e.g. `1h 04m 12s`) lives here, private.

---

## Acceptance Criteria

- [ ] `build_run_bundle` produces a valid `RunBundle` from: (a) a full
      successful bug-mode run, (b) a failed run with empty shared state,
      (c) a run with gates resolved and expired
- [ ] Totals aggregate telemetry only from nodes that reported it;
      all-absent telemetry → `None`, not 0-as-fake-data
- [ ] `render_markdown` output contains run metadata, agents table, gate
      audit and developed-work sections; empty sections omitted
- [ ] Module performs no I/O (import-level and call-level)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_run_bundle.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle.py
def test_build_bundle_successful_run(): ...
def test_build_bundle_failed_run_minimal_shared(): ...
def test_build_bundle_gate_audit(): ...
def test_totals_aggregate_partial_telemetry(): ...
def test_totals_none_when_no_telemetry(): ...
def test_render_markdown_full(): ...
def test_render_markdown_omits_empty_sections(): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 8, §6, §7 Patterns)
2. **Check dependencies** — TASK-1927 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep the line anchors
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
