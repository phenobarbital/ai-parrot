# TASK-1855: REST command endpoints — resolve gate & cancel run

**Feature**: FEAT-322 — AHP-style Session State, Host & HITL Approval Gates for dev-loop
**Spec**: `sdd/specs/agent-host-protocol-session-state.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1851
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (goal G5, write side; resolved proposal U3: WS for reads,
REST for commands). Operators (nav-admin) resolve gates and cancel runs via
HTTP; the endpoints are thin adapters over the runner's command methods,
translating arbitration exceptions into status codes with a full audit body.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py`:
  - Pydantic request models (`frozen=True, extra="forbid"`):
    `ResolveGateRequest {resolution: Literal["approved","rejected"],
    resolved_by: str, comment: str = "", client_seq: int = 0}`;
    `CancelRunRequest {requested_by: str}`.
  - `async def resolve_gate_handler(request: web.Request) -> web.Response`
    — path params `run_id`, `gate_id`; body → `ResolveGateRequest`;
    builds `ActionOrigin(client_id=<resolved_by>, client_seq=<client_seq>)`
    and calls `runner.resolve_gate(...)`.
    - 200: `{"envelope": <ActionEnvelope dump>}`
    - 404: unknown run (runner KeyError) or `GateNotFoundError`
    - 409: `GateAlreadyResolvedError` → body
      `{"error": "already_resolved", "status": <gate.status>,
      "resolved_by": ..., "resolved_at": ...}` (read the gate from
      `runner.get_host(run_id).state.gates[gate_id]`)
    - 400: body validation errors
  - `async def cancel_run_handler(...)` — 200 envelope | 404 unknown run.
  - `def register_command_routes(app: web.Application, runner: DevLoopRunner) -> None`
    — `app.router.add_post("/runs/{run_id}/gates/{gate_id}/resolve", ...)`,
    `add_post("/runs/{run_id}/cancel", ...)`; runner injected via closure or
    `app["dev_loop_runner"]`.
  - Export `register_command_routes` from `parrot/flows/dev_loop/__init__.py`.
- Tests with `aiohttp.test_utils` (`AioHTTPTestCase` or the
  `aiohttp_client` pytest fixture style already used in repo WS tests):
  full status-code contract, 409 carries resolver identity, origin recorded
  on the envelope, cancel is terminal-sticky (second cancel → still 200
  no-op envelope OR 409 — pick 200-with-noop per reducer semantics and
  assert it).

**NOT in scope**: authentication/authorization (existing app-level auth
applies; note in module docstring); WS command messages (non-goal);
nav-admin client changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` | CREATE | REST handlers + route registration |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | export `register_command_routes` |
| `packages/ai-parrot/tests/flows/dev_loop/test_commands.py` | CREATE | endpoint contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                   # in-tree (streaming.py:37, webhook.py)
from parrot.flows.dev_loop.session_state import (         # TASK-1848/1849
    ActionEnvelope, ActionOrigin, GateAlreadyResolvedError, GateNotFoundError,
)
from parrot.flows.dev_loop.runner import DevLoopRunner    # dev_loop/__init__.py:26
```

### Existing Signatures to Use
```python
# DevLoopRunner command surface (TASK-1851):
async def resolve_gate(self, run_id, gate_id, resolution, resolved_by,
                       comment="") -> ActionEnvelope: ...
    # NOTE: verify whether TASK-1851 exposed an `origin` parameter on
    # runner.resolve_gate; if not, pass origin via host.apply through the
    # runner or extend the runner signature (additive) — do NOT bypass the
    # runner and call the host directly from the handler.
async def cancel_run(self, run_id: str, requested_by: str) -> ActionEnvelope: ...
def get_host(self, run_id: str) -> Optional[SessionHost]: ...

# Registration pattern precedent (module-level function taking the app):
# packages/ai-parrot/src/parrot/flows/dev_loop/webhook.py:292
#   register_pull_request_webhook(...) — mirrors "register_*" naming

# ApprovalGate audit fields (session_state): status, resolved_by,
#   resolved_at, comment — used to build the 409 body.
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.commands`~~ — THIS task creates it
- ~~any existing REST surface for runs/gates~~ — webhook.py only handles
  GitHub PR webhooks via the AutonomousOrchestrator listener; these routes
  are plain aiohttp routes on the hosting app
- ~~auth middleware in this module~~ — out of scope; hosting app's auth applies
- ~~`runner.resolve_gate` with origin param before TASK-1851's final shape~~ —
  verify the actual signature first (see note above)

---

## Implementation Notes

### Key Constraints
- Handlers are THIN: validate → delegate → map exceptions. No business
  logic, no direct host mutation beyond the read for the 409 body.
- JSON responses via `web.json_response`; envelope serialization via
  `envelope.model_dump(mode="json")`.
- 409 is the product-facing "already approved by X" experience (spec §1
  user-facing behavior) — the body MUST name the resolver and timestamp.
- Log every command at INFO with run_id/gate_id/actor (audit trail
  complements the in-state audit).

---

## Acceptance Criteria

- [ ] POST resolve: 200 envelope | 400 invalid body | 404 unknown run/gate | 409 with resolver identity + timestamp
- [ ] POST cancel: 200 envelope; run phase becomes `cancelled` (terminal-sticky)
- [ ] `ActionOrigin` recorded on resolve envelopes (`client_id` = resolved_by)
- [ ] `register_command_routes` exported and wires both routes
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_commands.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_commands.py
async def test_resolve_gate_200_envelope(aiohttp_client): ...
async def test_resolve_gate_404_unknown_run(...): ...
async def test_resolve_gate_404_unknown_gate(...): ...
async def test_resolve_gate_409_names_first_resolver(...): ...
async def test_resolve_gate_400_bad_resolution(...): ...
async def test_cancel_run_200_terminal(...): ...
```

---

## Agent Instructions

1. Read spec §2 (client surface) + §3 M7. Verify TASK-1851 completed.
2. Verify the runner command signatures as implemented (may differ in the
   origin plumbing — contract note above).
3. Implement; run tests; move to completed; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
