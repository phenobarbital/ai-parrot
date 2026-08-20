# TASK-2290: Bridged HITL wiring — real confirmation through the daemon channel

**Feature**: FEAT-434 — Claude Agent Tool Bridge
**Spec**: `sdd/specs/claude-agent-tool-bridge.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2286, TASK-2287, TASK-2288
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. A confirming tool called by the sub-agent must ask a
real human, not let the sub-agent grant itself permission. The `confirm: boolean`
shim is already stripped from the schema (TASK-2287) and the caller identity is
resolved (TASK-2286); this task makes the `ConfirmationGuard` actually reachable
and correctly configured on the bridged path.

Two traps documented in the spec make this non-trivial:
`ConfirmationConfig.default_channel` is `"telegram"`, so without an override the
approval request leaves the daemon and the operator in `parrot attach` never sees
it — the HITL would "work" and be invisible. And `ConfirmationGuard` **fails
closed** when `human_manager is None`, denying with status `"cancelled"`.

---

## Scope

- Ensure the daemon's `ToolManager` has a `ConfirmationGuard` configured with a
  `human_manager` reachable from the agentd console, so bridged confirming tools
  park until a human answers.
- Override the HITL channel away from the `"telegram"` default for this path.
- Thread the `PermissionContext` from TASK-2286 into the bridge handler's
  `execute_tool()` call so the window is keyed on the real caller.
- Pin the service identity's effective `window_seconds` to `0` at the point of
  use (belt and braces with TASK-2286).
- Ensure a denial or an `approval_timeout` expiry surfaces as a **recoverable**
  MCP error result, consistent with TASK-2287's failure mapping.
- Wire the reference integration in `parrot.agents.claude_code` so
  `parrot serve` exercises this path.
- Write unit tests.

**NOT in scope**: modifying `parrot/auth/confirmation.py` — FEAT-235 territory is
read-only here (fixing the stale `confirm_window_seconds` docstring is allowed
and encouraged, but no behaviour change); the bridge's conversion (TASK-2287);
caller-identity resolution itself (TASK-2286).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/claude_code.py` | MODIFY | configure the guard + channel for the daemon target |
| `packages/ai-parrot/src/parrot/clients/claude_agent_bridge.py` | MODIFY | forward the `PermissionContext`; map denial/timeout |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | MODIFY | expose the human channel to the agent's `ToolManager` |
| `tests/clients/test_bridged_hitl.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth import ConfirmationGuard                      # verified: parrot/auth/__init__.py:77
from parrot.auth.confirmation import (
    ConfirmationConfig,           # verified: parrot/auth/confirmation.py:66
    ConfirmationDecision,         # verified: parrot/auth/confirmation.py:88
    InMemoryConfirmationWindowStore,  # verified: parrot/auth/confirmation.py:167
)
from parrot.auth.permission import PermissionContext, UserSession  # verified: permission.py:81, :21
from parrot.tools.manager import ToolManager                    # verified
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationConfig(BaseModel):                           # line 66
    window_seconds: int = Field(0, ge=0)                       # line 83  <- REAL field name
    approval_timeout: float = Field(120.0, gt=0)               # line 84
    default_channel: str = "telegram"                          # line 85  <- MUST be overridden
    max_edit_retries: int = Field(1, ge=0)                     # line 86
class ConfirmationGuard:                                       # line 378
    def __init__(self, store: ConfirmationWindowStore,
                 human_manager: Optional["HumanInteractionManager"] = None,
                 config: Optional[ConfirmationConfig] = None) -> None: ...  # line 399
    async def confirm(self, *, tool: "AbstractTool", parameters: dict,
                      permission_context: Optional["PermissionContext"] = None,
                      ) -> ConfirmationDecision: ...           # line 417
    # Documented lifecycle (docstring at :378):
    #   1. non-confirmation tool -> allow ("not_required")
    #   2. within window for same args_hash -> allow
    #   3. NO human_manager -> DENY, fail-closed, status "cancelled"
    #   4. build briefing -> ask HITL (APPROVAL or FORM x BLOCK or SUSPEND)
    #   5. map result -> confirm / cancel / timeout
class ConfirmationWindowStore(ABC):                            # line 111
    # Key = (owner_id, tool_name, args_hash)                   # line 116
    async def is_confirmed(self, owner_id, tool_name, args_hash, ...): ...  # line 121
    async def record(self, owner_id, tool_name, args_hash, ...): ...        # line 140
def compute_args_hash(parameters: dict) -> str: ...            # line 46
def render_briefing(tool: "AbstractTool", parameters: dict) -> str: ...  # line 251
def build_form_schema(tool: "AbstractTool", parameters: dict) -> dict: ...  # line 291
def revalidate_edit(tool: "AbstractTool", edited: dict) -> dict: ...       # line 352

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def set_confirmation_guard(self, guard: "ConfirmationGuard") -> None: ...  # line 496
    @property
    def confirmation_guard(self) -> Optional["ConfirmationGuard"]: ...         # line 514
    async def execute_tool(self, tool_name, parameters,
                           permission_context=None) -> Any: ...               # line 1431

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    confirming_tools: frozenset = frozenset()                  # line 285
    # line 681: those methods get routing_meta["requires_confirmation"] = True
```

### ⚠ Two test trees — migration residue, check before you write

`ai-parrot` was a single package with its tests at the repo root, then became a
uv monorepo; many tests were **copied or moved** into `packages/*/tests/` and the
originals were left in place. So a given module can exist in BOTH trees, and
**which copy is authoritative differs per file** — the monorepo path is not
automatically the current one.

For this feature specifically:

| Path | Status |
|---|---|
| `tests/clients/test_claude_agent.py` | **Canonical.** 15 test functions / 20 cases, `test_claude_agent_live_smoke` at line 378, last touched 2026-08-20. Extend this one. |
| `packages/ai-parrot/tests/clients/test_claude_agent.py` | Separate, older module (2026-04-27, 8 tests): `TestExtendedRunOptions`, `TestBuildOptionsForwardsExtensions`. Still tracked, still runs. Do not break it. |
| `packages/ai-parrot/tests/test_toolmanager_*.py` | Where `ToolManager` tests live (flat, not under `tests/tools/`) — e.g. `test_toolmanager_confirmation.py`, `test_toolmanager_load_tool.py`. |
| `packages/ai-parrot-integrations/tests/agentd/` | Where agentd tests live. Unambiguous — no root duplicate. |
| `tests/integration/` | Root integration tree; exists and is where the live tests go. |

**Before creating or editing a test file**, check whether a same-named module
exists in the other tree (`git ls-files | grep <name>`) and compare mtimes /
content. Editing the stale copy leaves the real suite untouched and the task
looks green while nothing was verified.

### Does NOT Exist
- ~~`ConfirmationConfig.confirm_window_seconds`~~ — the real field is
  **`window_seconds`** (confirmation.py:83). `confirm_window_seconds` appears
  only in the `ConfirmationGuard` class docstring and is **stale**. Do not code
  against it.
- ~~a default HITL channel pointing at agentd~~ — `default_channel` is
  `"telegram"`. Without an explicit override the approval request goes to
  Telegram and the operator in `parrot attach` never sees it.
- ~~`ConfirmationGuard` allows when `human_manager is None`~~ — it **denies**
  (fail-closed, status `"cancelled"`). A missing human manager is not an
  "allow all".
- ~~`agentd` exposes a `HumanInteractionManager` today~~ — verify before
  assuming; if absent, wiring one is part of this task's scope.
- ~~`parrot.agents.claude_code.make_agent(confirmation_guard=...)`~~ — not a
  parameter today. Existing signature:
  `make_agent(force_cc_auth: bool | None = None, **kwargs) -> Agent`, plus
  `sanitize_claude_environment(force_cc_auth: bool = True) -> dict[str, list[str]]`.

---

## Implementation Notes

### Key Constraints
- Do NOT change `parrot/auth/confirmation.py` behaviour. FEAT-235 is consumed,
  not modified. Correcting the stale `confirm_window_seconds` docstring is the
  one welcome edit there.
- A parked HITL holds the turn open. `approval_timeout` (default 120 s) bounds
  it; make sure the bridge's `tool_timeout` (TASK-2288) does not fire first and
  cancel a confirmation a human is actively answering — document the interaction
  or make the HITL wait exempt from the tool timeout.
- Denial and timeout are **recoverable**: an MCP error result the sub-agent can
  explain to the user, never an aborted turn.
- The service identity's window stays `0` — assert it at the point of use too.

### References in Codebase
- `packages/ai-parrot/examples/workday_checkin.py` — the existing HITL demo (FEAT-235)
- `docs/hitl-confirmation.md` — the documented behaviour to extend
- `packages/ai-parrot/src/parrot/tools/manager.py:1544` — where `execute_tool` consults the guard

---

## Acceptance Criteria

- [ ] A bridged confirming tool triggers `ConfirmationGuard.confirm()`
- [ ] The approval request reaches the agentd console, NOT the `"telegram"` default
- [ ] The `PermissionContext` from TASK-2286 is forwarded to `execute_tool()`
- [ ] The window is keyed on the real caller's `user_id`, never `"anonymous"`
- [ ] The service identity's effective `window_seconds` is `0` at the point of use
- [ ] Approval → the tool executes and its result reaches the sub-agent
- [ ] Denial → recoverable MCP error result, turn continues
- [ ] `approval_timeout` expiry → recoverable MCP error result, turn continues
- [ ] `human_manager is None` → fail-closed denial, surfaced as a recoverable error
- [ ] `parrot/auth/confirmation.py` behaviour is unchanged (docstring fix aside)
- [ ] All tests pass: `pytest tests/clients/test_bridged_hitl.py -v`
- [ ] No new `ruff check` findings

---

## Test Specification

```python
# tests/clients/test_bridged_hitl.py
class TestBridgedConfirmation:
    async def test_confirming_tool_invokes_guard(self): ...
    async def test_channel_is_not_telegram_default(self): ...
    async def test_permission_context_forwarded_to_execute_tool(self): ...
    async def test_owner_is_never_anonymous(self): ...
    async def test_service_identity_window_is_zero_at_use(self): ...

class TestOutcomes:
    async def test_approval_executes_tool(self): ...
    async def test_denial_returns_recoverable_error(self): ...
    async def test_timeout_returns_recoverable_error(self): ...
    async def test_missing_human_manager_fails_closed(self): ...
    async def test_tool_timeout_does_not_cancel_active_hitl_wait(self): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2286, TASK-2287, TASK-2288 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/claude-agent-tool-bridge.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
