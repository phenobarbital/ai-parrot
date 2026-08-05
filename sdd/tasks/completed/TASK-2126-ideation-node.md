# TASK-2126: IdeationNode — NL → SDD document with bounded HITL Open-Questions rounds

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: done
**Completed**: 2026-08-05
**Verification**: verified
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2121, TASK-2122, TASK-2124
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (ideation half) + §2 "The Open-Questions HITL round-trip
(normative)" — the heart of FEAT-412. Converts a `DevRequestBrief` into a
committed SDD document via the `sdd-ideation` subagent, resolving Open
Questions with the human through `open_questions` gates, then hands a
`FeatureBrief` to the (reused) `PlannerNode`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py`
  with `IdeationNode`, registered as `dev_flow.ideation`. Implement the
  normative round-trip (spec §2), exactly:
  1. Read `ctx["dev_brief"]` (`DevRequestBrief`); derive dispatch `mode`:
     `new_feature → "brainstorm"`, `enhancement → "proposal"`. Optional
     repo context via `DevLoopWikiSearch` when wired.
  2. Dispatch `sdd-ideation`; parse final JSON → `IdeationOutput`.
  3. If `open_questions` non-empty: `host.open_gate(kind="open_questions",
     node_id=self.name, title=f"Open questions — {output.document_path}",
     questions=[...], ttl_seconds=conf.DEV_FLOW_GATE_TTL_QUESTIONS,
     on_expiry="fail")` → `await host.wait_gate(gate_id)`.
     - approved → re-dispatch with `answers` (subagent marks `[x] …
       — *Resolved*: <answer>`); new questions may open a new gate, bounded
       by `conf.DEV_FLOW_IDEATION_MAX_ROUNDS` (default 2). Exhausted rounds:
       remaining `[ ]` stay in the doc; run continues.
     - rejected/expired → raise (on_error edge → failure_handler).
  4. Fail fast when `IdeationOutput.committed is False`.
  5. Terminal: build `FeatureBrief(document_path=output.document_path,
     document_kind=output.document_kind, jira_issue_key/dev_agents/
     judge_panel passthrough from the DevRequestBrief)` → publish to
     `ctx["feature_brief"]`, return it.
  - No `session_host` in shared state → log warning and run WITHOUT gates
    (autonomous mode; mirror development.py's no-host fallback).
- Add the two conf keys to `parrot/conf.py`:
  `DEV_FLOW_IDEATION_MAX_ROUNDS` (int, default 2),
  `DEV_FLOW_GATE_TTL_QUESTIONS` (int seconds, default 86400).
- Unit tests with a scripted fake dispatcher.

**NOT in scope**: the subagent prompt (TASK-2124), gate model (TASK-2122),
topology wiring (TASK-2127), UI (TASK-2130).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` | CREATE | IdeationNode |
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/__init__.py` | MODIFY | Export |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Two `DEV_FLOW_*` keys |
| `packages/ai-parrot/tests/flows/dev_flow/test_ideation_node.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import DevLoopNode, register_dev_loop_node  # :193/:174
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher
from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch
from parrot.flows.dev_loop.models import FeatureBrief          # models/base.py:725
from parrot.flows.dev_flow.models import IdeationOutput, DevRequestBrief  # TASK-2121
from parrot.flows.dev_flow._subagent_defs import load_subagent_definition  # TASK-2124
from parrot import conf
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class SessionHost:
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
                  instructions="", payload_ref="", ttl_seconds=None,
                  on_expiry: Literal["fail","approve"]="fail",
                  ) -> Tuple[str, ActionEnvelope]              # :1079
                  # + questions: Optional[List[str]] after TASK-2122
    async def wait_gate(self, gate_id: str) -> ApprovalGate    # :1149
    # ApprovalGate.status ∈ {"pending","approved","rejected","expired"}  # :180
    # ApprovalGate.answers: Dict[str,str] after TASK-2122

# Host access + gate-wait PATTERN (verified 2026-08-05):
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:255-288
#   host = shared.get("session_host")
#   if host is None: <warn + proceed without gate>
#   gate_id, _ = host.open_gate(kind=..., node_id=self.name, ...)
#   gate = await host.wait_gate(gate_id)
#   if gate.status != "approved": raise RuntimeError(...)
# also: deployment_handoff.py:274-283 (same shape)

# FeatureBrief eager validation (models/base.py:780): document_path MUST
# exist and be readable at construction — build the FeatureBrief only
# AFTER committed=True is confirmed.
```

### Does NOT Exist
- ~~`IdeationNode` / `dev_flow.ideation`~~ — this task creates them.
- ~~`conf.DEV_FLOW_IDEATION_MAX_ROUNDS` / `conf.DEV_FLOW_GATE_TTL_QUESTIONS`~~
  — added here; every other knob (`DEV_LOOP_QA_MAX_RETRIES`,
  `DEV_LOOP_GATE_PARK`, …) is reused from existing `DEV_LOOP_*` keys — do
  NOT fork them.
- ~~`gate_ttl_for("open_questions")`~~ — the runner TTL map
  (`runner.py:88`) covers dev_loop kinds; use
  `conf.DEV_FLOW_GATE_TTL_QUESTIONS` directly.
- ~~a resume API on the dispatcher~~ — "re-dispatch" means a NEW dispatch
  whose payload includes the prior `document_path` + `answers`; do not
  assume session continuity.

---

## Implementation Notes

### Key Constraints
- Gate expiry is FAIL-CLOSED (`on_expiry="fail"`) — spec §2 step 5; the
  expired gate surfaces via `wait_gate` with status `"expired"` → raise.
- Round bound: a `while` over rounds with the counter starting at the
  FIRST gate; re-dispatches after the last allowed round must NOT open new
  gates.
- Park/resume (`DEV_LOOP_GATE_PARK`) is runner-side and transparent to the
  node — nothing to implement here, but do not block the event loop while
  waiting (plain `await`).
- Node result must be the `FeatureBrief` (CEL/`on_success` edge to planner
  needs it); also publish `ctx["feature_brief"]`.
- Conf keys follow the existing conf.py style (env-driven with defaults).

### References in Codebase
- `dev_loop/nodes/development.py:245-290` — gate open/wait/raise shape
- `dev_loop/nodes/planner.py` — dispatch → parse-final-JSON pattern
  (`_PlannerBrief` local payload model precedent)

---

## Acceptance Criteria

- [ ] enhancement → mode "proposal" → `FeatureBrief.document_kind == "proposal"`; new_feature → "brainstorm"
- [ ] Open questions → ONE gate per round; approved answers reach the re-dispatch payload
- [ ] Rounds bounded by `DEV_FLOW_IDEATION_MAX_ROUNDS`; leftover `[ ]` questions do not block
- [ ] Rejected or expired gate → node raises (failure path)
- [ ] `committed=False` → node raises before building the FeatureBrief
- [ ] No session_host → warning + gateless run
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_ideation_node.py -v`; `ruff`/`mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_ideation_node.py
# fixture: fake_ideation_dispatcher — round 1 → 2 open questions;
#          round 2 (with answers) → none, committed=True
async def test_enhancement_emits_proposal(): ...
async def test_new_feature_emits_brainstorm(): ...
async def test_gate_roundtrip_answers_reach_redispatch(): ...
async def test_rounds_bounded(): ...
async def test_gate_rejected_raises(): ...
async def test_gate_expired_raises(): ...
async def test_uncommitted_output_raises(): ...
async def test_no_host_runs_gateless(): ...
async def test_resumed_existing_flag_passthrough(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2121, TASK-2122, TASK-2124 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

`IdeationNode` registered as `dev_flow.ideation`, implementing spec §2's
round-trip. 22 tests, all green on the first run; 73 across `dev_flow`.

**Round accounting.** `rounds_used` counts *gates opened*, and the loop
condition is `output.open_questions and host is not None and rounds_used <
max_rounds`. With the default 2 that yields at most 2 gates and 3 dispatches
(1 initial + 2 re-dispatches), and the re-dispatch after the last allowed
round cannot open a gate — the task's explicit requirement. Covered by
`test_rounds_bounded` (asserts exactly 2 gates / 3 dispatches),
`test_max_rounds_zero_opens_no_gate`, and
`test_max_rounds_reads_conf_when_not_overridden` (conf read at execute time,
so a monkeypatch takes effect per-case).

**Gate shape.** ONE gate per round carrying **all** questions, `node_id`
`"ideation"`, `on_expiry="fail"`, `ttl_seconds=conf.DEV_FLOW_GATE_TTL_QUESTIONS`
(read via `getattr` at call time). The resolved `document_path` goes in the
gate **title** — spec §7's mitigation for the slug-collision risk, so the user
can spot and reject an unintended resume. `instructions` carry
round N/M, the `resumed_existing` state, the summary, and a note that partial
answers are fine and rejection aborts. Asserted in
`test_gate_roundtrip_answers_reach_redispatch`.

**Two contract details worth flagging for review:**

1. **The subagent is dispatched via `system_prompt_override`, not
   `profile.subagent`.** `ClaudeCodeDispatchProfile.subagent` is a closed
   Literal without `"sdd-ideation"`, and — decisively —
   `dispatchers/claude.py:393` resolves a non-`None` `subagent` through
   **`dev_loop`'s** `load_subagent_definition`, which raises
   `ValueError: Unknown subagent name 'sdd-ideation'` by design (TASK-2124's
   contract forbids extending that loader; the dev_flow package owns its
   prompts). So extending the Literal would have produced a runtime failure.
   Passing the dev_flow-loaded body as `system_prompt_override` with
   `subagent=None` is the path the dispatcher already supports
   (`claude.py:414-415` → `ClaudeAgentRunOptions(system_prompt=...)`), and it
   touches **zero** shared `dev_loop` code — consistent with the spec's
   "reuse at the right altitude". Pinned by
   `test_dispatch_payload_and_profile`.
2. **`_resolve_document_path`.** `FeatureBrief` validates `document_path`
   readability eagerly, but the subagent reports a **repo-relative** path and
   the hosting process' CWD is not guaranteed to be the repo root. The helper
   tries the path as given, then anchored at `conf.PROJECT_ROOT`, and raises
   an actionable `RuntimeError` ("reported committed=True … but no readable
   document was found") if neither resolves — instead of letting a confusing
   pydantic `ValidationError` escape from deep inside the model. This also
   catches a subagent that lies about `committed`. Covered by
   `test_unreadable_document_raises`.

Dispatch `cwd` is `conf.PROJECT_ROOT` (the base checkout), **not**
`WORKTREE_BASE_PATH`: the document is committed to `base_branch` and the
feature worktree does not exist yet at ideation time — `sdd-planner` creates
it later.

Other behaviors pinned by tests: jira/dev_agents/judge_panel passthrough into
the `FeatureBrief`; `ideation_output` + `feature_brief` published to shared
state; partial answers accepted; rejection (`match="rejected by bob"`) and
fail-closed expiry both raise with no re-dispatch; `committed=False` raises
with `feature_brief` never set; a `FeatureBrief` arriving on `dev_brief`
raises (it must route to the planner instead); wiki context injected,
degraded to `""` on failure.

`ruff`: the whole `dev_flow` package and test package are at **0** findings.

**Deviations from spec**: one, scoped down rather than up.

- The task's scope says "Add the **two** conf keys". Only
  `DEV_FLOW_IDEATION_MAX_ROUNDS` was added here —
  `DEV_FLOW_GATE_TTL_QUESTIONS` was already added in **TASK-2122**, where the
  `GateKind` extension forced it (the `gate_ttl_for` exhaustiveness guard).
  Its name, type and 86400 default are exactly as this task specifies, and it
  is consumed here as planned. No duplication.
