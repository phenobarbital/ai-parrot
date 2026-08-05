# TASK-2122: Gate model extension — `open_questions` kind + structured answers

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (gate half) + §2 "The Open-Questions HITL round-trip".
Today `ApprovalGate` only supports approve/reject + free-text comment; the
Open-Questions HITL needs ONE gate per round carrying ALL questions
(structured) and structured answers on resolution. This touches SHARED
`dev_loop` infrastructure — the extension must be strictly additive and
backward-compatible (old persisted envelopes must re-validate).

---

## Scope

- `session_state.py`:
  - `GateKind` += `"open_questions"` (Literal at :172).
  - `ApprovalGate` += `questions: List[str] = []`,
    `answers: Dict[str, str] = {}` (additive, defaulted).
  - `GateResolved` += `answers: Dict[str, str] = {}`.
  - `SessionHost.open_gate(...)` gains `questions: Optional[List[str]] = None`
    passthrough; `SessionHost.resolve_gate(...)` gains
    `answers: Optional[Dict[str, str]] = None`.
  - Host-side validation: approving an `open_questions` gate with empty
    `answers` raises `ValueError` (reject needs none).
  - Reducer: fold `answers` into the gate state exactly like `comment`.
- `commands.py`: `ResolveGateRequest` += `answers: Dict[str, str] = {}`;
  `resolve_gate_handler` passes it through (empty-answers approval of an
  `open_questions` gate → 400).
- `runner.py`: `DevLoopRunner.resolve_gate(...)` (:713) gains the
  `answers` passthrough parameter (defaulted).
- Tests: new `packages/ai-parrot/tests/flows/dev_loop/test_open_questions_gate.py`
  + assert the FULL existing dev_loop suite still passes unmodified.

**NOT in scope**: the `IdeationNode` that opens these gates (TASK-2126),
the server route mounting (TASK-2129), the plan-gate per-run override
(TASK-2123), UI (TASK-2130).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | GateKind + additive fields + host passthrough + reducer |
| `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` | MODIFY | `ResolveGateRequest.answers` + handler passthrough |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `resolve_gate` answers passthrough |
| `packages/ai-parrot/tests/flows/dev_loop/test_open_questions_gate.py` | CREATE | Unit tests incl. backward-compat |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import (   # verified 2026-08-05
    ApprovalGate, GateKind, GateOpened, GateResolved, GateExpired,
    GateNotFoundError, GateAlreadyResolvedError,
)
from parrot.flows.dev_loop.commands import (
    ResolveGateRequest, resolve_gate_handler, register_command_routes,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
GateKind = Literal["manual_criterion", "deployment_approval",
                   "revision_approval", "plan_approval",
                   "review_escalation"]                          # :172-178
GateStatus = Literal["pending", "approved", "rejected", "expired"]  # :180
class ApprovalGate(_Frozen):                                     # :225
    gate_id: str; kind: GateKind; node_id: NodeId
    status: GateStatus = "pending"
    on_expiry: Literal["fail", "approve"] = "fail"               # :237
    title: str = ""; instructions: str = ""; payload_ref: str = ""
    opened_at: float = 0.0; expires_at: Optional[float] = None
    resolved_by: str = ""; resolved_at: Optional[float] = None
    comment: str = ""                                            # :251
class GateOpened(_ActionBase):                                   # :440
class GateResolved(_ActionBase):                                 # :445
class GateExpired(_ActionBase):                                  # :455
class SessionHost:
    def resolve_gate(self, gate_id,
                     resolution: Literal["approved","rejected"],
                     resolved_by, comment="", origin=None
                     ) -> ActionEnvelope                          # :1034
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str,
                  instructions="", payload_ref="", ttl_seconds=None,
                  on_expiry: Literal["fail","approve"]="fail",
                  ) -> Tuple[str, ActionEnvelope]                 # :1079
    def expire_due_gates(self, now=None) -> List[ActionEnvelope]  # :1116
    async def wait_gate(self, gate_id: str) -> ApprovalGate       # :1149

# packages/ai-parrot/src/parrot/flows/dev_loop/commands.py
class ResolveGateRequest(BaseModel):   # frozen, extra="forbid"
    resolution: Literal["approved", "rejected"]                   # :51
    resolved_by: str  # min_length=1                              # :52
    comment: str = ""; client_seq: int = 0                        # :53-54
async def resolve_gate_handler(request) -> web.Response           # :70
#   calls runner.resolve_gate(run_id, gate_id, body.resolution,
#          body.resolved_by, body.comment, origin=origin)         # :103-106

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    async def resolve_gate(self, run_id, gate_id, resolution,
                           resolved_by, comment, origin) -> ...    # :713
```

### Does NOT Exist
- ~~`GateKind "open_questions"`~~, ~~`ApprovalGate.questions`~~,
  ~~`ApprovalGate.answers`~~, ~~`GateResolved.answers`~~,
  ~~`ResolveGateRequest.answers`~~ — this task creates them.
- ~~a per-question gate model~~ — spec decision: ONE gate carries ALL
  questions of a round.

### ⚠️ Contract correction (discovered 2026-08-05 during implementation)

The task/spec contract omitted `NodeId`, which is a **closed Literal** in the
same file (`session_state.py:140-155`) and does NOT contain the dev-flow's
two new node ids:

```python
NodeId = Literal[
    "intent_classifier", "bug_intake", "research", "development", "qa",
    "deployment_handoff", "revision_handoff", "failure_handler", "close",
    # -- feature-mode topology (FEAT-378) --
    "planner", "synthesis", "feedback_router", "feature_handoff",
]
```

`ApprovalGate.node_id` is typed `NodeId`, so the spec's own normative call —
`host.open_gate(kind="open_questions", node_id="ideation", ...)` (spec §2
"The Open-Questions HITL round-trip", step 2) — raises a
`ValidationError` until `NodeId` gains `"dev_intake"` and `"ideation"`.

**Resolution**: extend `NodeId` additively with the two dev-flow node ids,
exactly as FEAT-378 did for its four feature-mode ids (same file, same
comment convention). Strictly additive — no existing value changes, so all
persisted envelopes and existing call sites are unaffected. Done here rather
than in TASK-2126 because `session_state.py` is already in this task's
scope and TASK-2125/2126 would otherwise be blocked on it.

---

## Implementation Notes

### Key Constraints
- **Strictly additive**: `_Frozen` state models are persisted in Redis
  streams (`flow:{run_id}:actions`); every new field MUST default so
  historical envelopes re-validate (spec §7 "Additive frozen models").
  Follow the DispatchState precedent (session_state.py:200-208 — optional
  TASK-1927 fields).
- The expiry sweep (`expire_due_gates` :1116) needs NO changes — an
  `open_questions` gate uses `on_expiry="fail"` (fail-closed, spec §2
  round-trip step 5).
- `except GateNotFoundError` MUST stay before `except KeyError` in the
  handler (commands.py:107-109 comment).

### References in Codebase
- `session_state.py:1034-1147` — gate command paths to extend
- `tests/flows/dev_loop/` — existing session-state test style (TASK-1848)

---

## Acceptance Criteria

- [ ] `open_gate(kind="open_questions", questions=[...])` stores questions; snapshot round-trips them
- [ ] `resolve_gate(..., answers={...})` folds answers into gate state; audit fields intact
- [ ] Approving an `open_questions` gate with empty answers → `ValueError` (host) / 400 (REST)
- [ ] Pre-FEAT-412 envelopes (no questions/answers) still validate and reduce
- [ ] Full existing dev_loop suite passes unmodified: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_open_questions_gate.py
def test_gate_open_questions_kind(): ...
def test_gate_resolve_with_answers(): ...
def test_gate_resolve_answers_required(): ...      # approve w/o answers fails
def test_gate_reject_needs_no_answers(): ...
def test_gate_backward_compat(): ...               # old envelope re-validates
async def test_rest_resolve_with_answers(aiohttp_client): ...
def test_open_questions_expiry_fail_closed(): ...  # GateExpired emitted
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

Strictly additive extension of the shared gate model:

- `session_state.py` — `GateKind += "open_questions"`;
  `ApprovalGate.questions: List[str] = []` / `answers: Dict[str, str] = {}`;
  `GateResolved.answers`; `open_gate(questions=...)` and
  `resolve_gate(answers=...)` passthrough; reducer folds `answers` alongside
  `comment`. Host-side validation raises `ValueError` when an
  `open_questions` gate is **approved** with no answers — before sequencing,
  so no action is emitted and the gate stays pending (asserted in
  `test_gate_resolve_answers_required`). Rejection needs no answers.
- `commands.py` — `ResolveGateRequest.answers` (defaulted, so pre-FEAT-412
  bodies still satisfy the frozen `extra="forbid"` model) + a dedicated
  `except ValueError` → **400 `answers_required`**. Placed deliberately:
  `GateNotFoundError` is a `KeyError` and `GateAlreadyResolvedError` is a
  `RuntimeError`, so the new clause cannot shadow the existing 404/409 paths
  (the module's ordering caveat is preserved).
- `runner.py` — `DevLoopRunner.resolve_gate(answers=...)` passthrough.

Backward compatibility is covered explicitly: `test_gate_backward_compat`
validates a hand-written pre-FEAT-412 `ApprovalGate` dict, a `gate/opened`
and a `gate/resolved` envelope with **no** `questions`/`answers` keys, then
reduces the pair and asserts the old semantics; plus a REST test with a
legacy body. 17 new tests, all passing.

**Regression net**: full `dev_loop` suite → **1033 passed, 6 skipped, 1
failed**. The single failure,
`test_qa_codereview.py::test_review_brief_carries_deterministic_qa_results`
(`review_brief.qa_criterion_results == []`), is **pre-existing on `dev`** and
unrelated to gates — verified by running that test against the unmodified
main checkout at `dev` HEAD, where it fails identically. Not touched (out of
scope, Cardinal Rule 5).

`ruff`: `commands.py` and the new test file are at **0** findings; the
`session_state.py`/`runner.py`/`conf.py` counts are unchanged from `dev`
apart from the new lines following each file's own `Dict`/`List`/`Optional`
house style. (Note: the repo ships no ruff config and CI's
"Lint & Registry Check" job does not run ruff, so these files carry 63/62
default-ruleset findings on `dev` already; "clean on modified files" is
interpreted as "adds no new findings".)

**Deviations from spec**: two, both forced and strictly additive.

1. **`NodeId` extended** with `"dev_intake"` and `"ideation"`
   (`session_state.py:150-159`). Not in the task/spec contract, but
   `ApprovalGate.node_id` is typed `NodeId` — a **closed** Literal — so the
   spec's own normative call `open_gate(kind="open_questions",
   node_id="ideation", ...)` (§2 round-trip step 2) raised a
   `ValidationError`. Extended exactly as FEAT-378 did for its four
   feature-mode ids. Full detail recorded in the *Contract correction*
   section above.
2. **`packages/ai-parrot/src/parrot/conf.py` modified** (not in this task's
   file table) to add `DEV_FLOW_GATE_TTL_QUESTIONS` (int, default 86400 —
   24h, fail-closed), plus its `_GATE_TTL_CONF_ATTR` entry in `runner.py`.
   Forced by `test_runner_host.py::test_gate_ttl_for_covers_every_gate_kind`,
   a deliberate regression guard asserting **every** `GateKind` resolves a
   TTL — extending `GateKind` (this task's core scope) breaks it otherwise,
   which would violate this task's own "full existing dev_loop suite passes"
   criterion. The key, its name and its default are exactly as specified in
   spec §2 Configuration.
   **Hand-off**: `conf.py` and both `DEV_FLOW_*` keys are listed under
   TASK-2126, which should now add only the remaining
   `DEV_FLOW_IDEATION_MAX_ROUNDS` key.
