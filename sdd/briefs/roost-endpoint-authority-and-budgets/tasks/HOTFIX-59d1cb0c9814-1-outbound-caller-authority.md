# HOTFIX-59d1cb0c9814-1: Stamp the caller PermissionContext on every outbound Roost message

**Feature**: BRIEF-59d1cb0c9814 — Roost endpoint: caller authority, grant enforcement and runtime budget gates
**Spec**: `sdd/briefs/roost-endpoint-authority-and-budgets.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`RoostMessage` carries `permission_context` and `auth_token`, the codec and bus
carrier serialize them, and the serving side already reads them through
`squawk_bridge.resolve_authority(msg)` (`endpoint.py:180`). Nothing ever
**writes** them, so every inbound Roost request reaches
`ToolManager.execute_tool(permission_context=None)` and `PBACToolCallGuardrail`
passes unconditionally (`pbac.py:251`) — the serving tool runs unguarded.

This task closes the producer half of `issue:59d1cb0c9814` part (1) and
implements the brief's Decision 1: resolve the caller context from an optional
constructor argument, else the shared `_pctx_var` ContextVar.

This task changes **no enforcement**; it only puts authority on the wire.
Enforcement is HOTFIX-59d1cb0c9814-2, which depends on it.

---

## Scope

- Add an optional `permission_context: Optional["PermissionContext"] = None`
  keyword argument to `RoostEndpoint.__init__`, stored as
  `self._permission_context`.
- Add a private resolver `RoostEndpoint._caller_authority()` returning
  `self._permission_context` when set, otherwise `parrot.auth.context._pctx_var.get()`.
  Import `_pctx_var` lazily inside the method body (module-level import of
  `parrot.auth` from `roost/` would widen `roost`'s import surface — `roost/`
  currently imports only `parrot.core.events.lifecycle`, `parrot.registry` and
  `parrot.tools.manager`, all under `TYPE_CHECKING` or inside functions).
- Stamp the resolved context onto every message this endpoint originates:
  the `RoostMessage(...)` built in `send()` (`endpoint.py:263`), the `opener`
  in `request()` (`endpoint.py:334`) and the `opener` in `query()`
  (`endpoint.py:389`).
- Pass `auth_token` through when the caller supplied one: add an optional
  `auth_token: Optional[str] = None` keyword to `RoostEndpoint.__init__` and
  stamp it the same way. Do NOT mint tokens (Assumption A4).
- Write tests proving the context reaches `execute_tool` on the serving side
  of an in-process request and of a query.

**NOT in scope**:
- Refusing when no authority resolved — that is HOTFIX-59d1cb0c9814-2.
- Changing `squawk_bridge.resolve_authority` (already correct).
- Changing `RoostMessage.reply()` (already propagates both fields,
  `messages.py:117-118`).
- Touching `_run_tool`'s tool-name handling or the grant checks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | MODIFY | constructor args, `_caller_authority()`, stamp 3 message builds |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | MODIFY | `make_endpoint` gains `permission_context=`; new propagation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the tree at `origin/dev` (`7e6741f13`).
> Use these exact names. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.auth.context import _pctx_var  # verified: packages/ai-parrot/src/parrot/auth/context.py:33
from parrot.auth.permission import PermissionContext  # verified: packages/ai-parrot/src/parrot/auth/permission.py:81
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/context.py:33
_pctx_var: contextvars.ContextVar["PermissionContext | None"] = (
    contextvars.ContextVar("dataset_manager_pctx", default=None)
)

# packages/ai-parrot/src/parrot/roost/messages.py:58
class RoostMessage(BaseModel):
    permission_context: Any = None   # line 75
    auth_token: Optional[str] = None # line 76
    hops: int = 0                    # line 77
    tokens: int = 0                  # line 78

# packages/ai-parrot/src/parrot/roost/endpoint.py:41
class RoostEndpoint:
    def __init__(self, *, agent_name: str, config: Optional[RoostAgentConfig],
                 engine: ProtocolEngine, dispatcher: GatingDispatcher,
                 carriers: Mapping[CarrierKind, Carrier], tool_manager: "ToolManager",
                 blackboard: Optional[Blackboard] = None, ledger: Optional[RoostAuditLedger] = None,
                 working_memory: Optional["WorkingMemoryToolkit"] = None,
                 wake: Optional[WakeCallback] = None, registry: Optional["AgentRegistry"] = None,
                 grant: Optional[GrantPolicy] = None, sweep_interval: float = 0.25) -> None:  # line 41

    async def send(self, performative: Performative, *, receivers: Sequence[AgentAddress] = (),
                   capability_filter: Optional[str] = None, content: Any = None,
                   protocol: Optional[InteractionProtocol] = None, conversation_id: Optional[str] = None,
                   in_reply_to: Optional[str] = None, body: Optional[str] = None,
                   envelope: Any = None, hops: int = 0) -> RoostMessage:  # line 245

    async def request(self, cap_id: str, args: Mapping[str, Any], *, timeout: Optional[float] = None,
                      receiver: Optional[AgentAddress] = None, hops: int = 0) -> Any:  # line 297

    async def query(self, question: Any, *, receiver: AgentAddress, timeout: Optional[float] = None,
                    expected_schema: Optional[dict] = None, hops: int = 0) -> Any:  # line 372

# packages/ai-parrot/src/parrot/roost/squawk_bridge.py:155
def resolve_authority(msg: RoostMessage) -> Any: ...
```

### Does NOT Exist
- ~~`parrot.auth.context.current_permission_context()`~~ — there is no getter helper; use `_pctx_var.get()`
- ~~`parrot.auth.context.bind_permission_context()`~~ — no binder helper exists; callers use `_pctx_var.set(...)` / `.reset(token)` directly (see `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py:172`)
- ~~`RoostEndpoint.permission_context`~~ — no such attribute today
- ~~`RoostMessage.caller_context`~~ — the field is `permission_context`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/endpoint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_endpoint.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.send",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.request",
    "sym:packages/ai-parrot/src/parrot/roost/endpoint.py#RoostEndpoint.query",
    "sym:packages/ai-parrot/src/parrot/roost/messages.py#RoostMessage",
    "sym:packages/ai-parrot/src/parrot/roost/squawk_bridge.py#resolve_authority"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `roost/` deliberately keeps its import surface narrow. Import `_pctx_var`
  **inside** `_caller_authority()`, mirroring how `squawk_bridge` keeps every
  satellite import in a function body.
- Resolution happens at **send time**, not construction time: a shared endpoint
  instance serves concurrent requests, and the ContextVar is what keeps them
  from bleeding into each other (that is exactly the reason
  `auth/context.py:26-32` gives for using a ContextVar).
- `send()` is also the path `_send_reply()` uses for replies that were NOT built
  by `RoostMessage.reply()`. Replies built by `reply()` already carry the
  inbound authority and must not be overwritten — `_deliver_outbound` must stay
  untouched; stamp only in the three constructors listed.
- Google-style docstrings, strict type hints, 120 columns, `self.logger`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py:172` — `_pctx_var.set(resolved)` after principal resolution
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:379,459` — set/reset token discipline
- `packages/ai-parrot/src/parrot/roost/squawk_bridge.py:155-166` — the consumer

---

## Implementation Blueprint

### Steps (in order)
1. Add `permission_context` and `auth_token` keyword arguments to `__init__` — *why*: Decision 1's explicit override for endpoints with no request scope.
2. Add `_caller_authority()` returning `(permission_context, auth_token)` — *why*: one resolution point for all three call sites.
3. Stamp both fields in `send()`, the `request()` opener and the `query()` opener — *why*: these are the only messages Roost originates from scratch.
4. Extend `make_endpoint` and add propagation tests — *why*: the current suite asserts the bug.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'grant: Optional\[GrantPolicy\] = None,' packages/ai-parrot/src/parrot/roost/endpoint.py)
# AFTER — insert below `        grant: Optional[GrantPolicy] = None,` (verified: endpoint.py:55)
        permission_context: Any = None,
        auth_token: Optional[str] = None,
```
```python
# occurrences: 1 (verified: grep -c 'self.grant = grant or GrantPolicy()' packages/ai-parrot/src/parrot/roost/endpoint.py)
# AFTER — insert below `        self.grant = grant or GrantPolicy()` (verified: endpoint.py:63)
        self._permission_context, self._auth_token = permission_context, auth_token
```
```python
# NEW METHOD — add after `def address(self)` (verified: endpoint.py:70-73)
    def _caller_authority(self) -> tuple[Any, Optional[str]]:
        """Return the caller authority to stamp on an outbound message.

        The constructor override wins; otherwise the request-scoped
        ``PermissionContext`` published on ``parrot.auth.context._pctx_var``
        is used, so a shared endpoint never mixes two callers' identities.

        Returns:
            The resolved ``(permission_context, auth_token)`` pair; either may be ``None``.
        """
        if self._permission_context is not None:
            return self._permission_context, self._auth_token
        # FILL IN: import _pctx_var lazily here and return (_pctx_var.get(), self._auth_token)
        raise NotImplementedError
```
```python
# occurrences: 3 — DISAMBIGUATE. Stamp each of the three originating builds by
# adding `permission_context=<ctx>, auth_token=<tok>` to its RoostMessage(...) call,
# where `<ctx>, <tok> = self._caller_authority()` is resolved immediately above it:
#   - endpoint.py:263  `msg = RoostMessage(`            inside send()
#   - endpoint.py:334  `opener = RoostMessage(`         inside request()   (preceded by `self.engine.open(opener)`)
#   - endpoint.py:389  `opener = RoostMessage(`         inside query()     (preceded by `self.engine.open(opener)`)
# Note request()'s wire message is sent via self.send() (endpoint.py:349) and is
# therefore stamped by the send() change; the opener is the engine's local copy.
```
**Why this shape**: the three builds are the only places Roost mints a message
that is not a `reply()`. Stamping in `_deliver_outbound` instead would overwrite
the inbound authority that `reply()` correctly carries forward, which would let a
serving agent silently re-sign a caller's message with its own identity.

### FILL IN checklist
- [ ] `endpoint.py::RoostEndpoint._caller_authority` — the lazy `_pctx_var` import and fallback return; bounded by Decision 1

---

## Acceptance Criteria

- [ ] `RoostEndpoint(..., permission_context=ctx)` stamps `ctx` on messages from `send()`, `request()` and `query()`
- [ ] With no constructor override, a `PermissionContext` bound on `_pctx_var` is stamped instead
- [ ] With neither, the fields stay `None` (no crash, no behaviour change — enforcement arrives in task 2)
- [ ] A serving endpoint's `execute_tool` receives the caller's context, not `None`, for an in-process request
- [ ] `parrot.auth` is NOT imported at module level in `endpoint.py`
- [ ] `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`
- `pytest packages/ai-parrot/tests/roost/test_squawk_bridge.py -q`
- `pytest packages/ai-parrot/tests/roost/test_salary_flow_end_to_end.py -q`
- `pytest packages/ai-parrot/tests/roost/test_codec_bus.py -q`

Run from the worktree root with `PYTHONPATH=packages/ai-parrot/src`.

---

## Test Specification

```python
# packages/ai-parrot/tests/roost/test_endpoint.py (extend the existing module)
import pytest

from parrot.auth.context import _pctx_var
from parrot.auth.permission import PermissionContext, UserSession
from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import RoostAgentConfig
from parrot.roost.messages import AgentAddress


def _pctx() -> PermissionContext:
    return PermissionContext(session=UserSession(user_id="u-1", tenant_id="acme", roles=frozenset({"admin"})))


@pytest.mark.asyncio
async def test_request_carries_constructor_permission_context() -> None:
    """An endpoint built with an explicit context stamps it on its request."""
    # FILL IN: build caller with permission_context=_pctx(), serve with a deterministic hr endpoint,
    # await caller.request(...), assert hr.tool_manager.execute_tool.await_args.kwargs["permission_context"]
    # is the same object.


@pytest.mark.asyncio
async def test_request_falls_back_to_pctx_var() -> None:
    """With no constructor override the bound ContextVar supplies the authority."""
    # FILL IN: token = _pctx_var.set(ctx) ... try/finally _pctx_var.reset(token)


@pytest.mark.asyncio
async def test_query_carries_authority() -> None:
    """A query opener is stamped the same way as a request."""
    # FILL IN
```

Note: `packages/ai-parrot/tests/roost/test_endpoint.py:77` currently asserts
`permission_context is None` for exactly this flow. That assertion encodes the
bug — update it to assert the propagated context.

---

## Agent Instructions

1. **Work in the brief worktree** `.claude/worktrees/fix-59d1cb0c9814-roost-endpoint-authority-and-budgets` — never on `dev`.
2. **Read the brief** at `sdd/briefs/roost-endpoint-authority-and-budgets.brief.md`, especially "Already fixed on dev — do not re-fix".
3. **Verify the Codebase Contract** before writing code; fix the contract first if anything moved.
4. **Update status** in `sdd/briefs/roost-endpoint-authority-and-budgets.index.json` → `"in-progress"` with `started_at`, and commit only that file.
5. **Implement** from the blueprint; complete every `# FILL IN:`.
6. **Run the Validation Commands**, then `ruff check --fix` the touched files.
7. **Commit only this task's files** (never `git add .` / `-A`): `fix(roost): HOTFIX-59d1cb0c9814-1 — stamp caller authority on outbound messages`.
8. **Mark the task `done`** in the per-brief index and fill in the Completion Note below, then commit the SDD state.

---

## Completion Note

**Completed by**: ai-parrot-75 (session 9c6edc), after a partial `sdd-worker` run
**Date**: 2026-10-29
**Notes**: `RoostEndpoint.__init__` gained `permission_context` / `auth_token`; `_caller_authority()` returns the constructor value when set, else `parrot.auth.context._pctx_var.get()` (imported inside the method so `roost/` keeps its narrow import surface). Both fields are stamped on the `RoostMessage` built in `send()` and on the `request()` / `query()` openers. `reply()` was left alone — it already propagates inbound authority. `make_endpoint` in test_endpoint.py now defaults to a `CALLER_CTX` stand-in and the old `permission_context is None` assertion is replaced.

**Validation**: `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/roost/ -q` => **119 passed**; `ruff check` on the four touched files => All checks passed.

**Code commit**: `572db7599` — the three tasks share ONE code commit (deviation from "one task = one commit"): their edits interleave in `endpoint.py` and could not be split non-interactively.

**Process note**: the `sdd-worker` run that produced the code could execute no Bash (headless permission denial), so validation, fixtures, the two missing tests, commits and closure were completed by the parent session.

**Deviations from spec**: see Notes above.
