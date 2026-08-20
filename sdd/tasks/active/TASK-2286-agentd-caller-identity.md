# TASK-2286: agentd caller identity — SO_PEERCRED + service-identity fallback

**Feature**: FEAT-434 — Claude Agent Tool Bridge
**Spec**: `sdd/specs/claude-agent-tool-bridge.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. Bridged tool calls run through
`ToolManager.execute_tool()`, whose `ConfirmationGuard` keys its approval window
on `(owner_id, tool_name, args_hash)` and falls back to the literal
`"anonymous"` when no `PermissionContext` is supplied. agentd captures **no
caller identity at all** today, so every bridged confirmation would collapse
onto one anonymous owner.

Decision (spec §8, resolved): identity comes from the environment — the OS user
of the connecting UDS peer, with an env-configured service identity as fallback.
That fallback **never holds a confirmation window**.

---

## Scope

- In the agentd UDS server's connection handler, read the peer's credentials via
  `SO_PEERCRED` and resolve the uid to a username with `pwd`.
- Store the resolved identity on the `Session` so downstream handlers can reach it.
- Build a `PermissionContext` (wrapping a `UserSession`) from that identity and
  make it available to tool execution.
- Add `ServiceIdentityConfig` populated from environment variables with defaults
  (display name along the lines of `"parrot agent server"`, `user_id` default
  `"1001"`), used when peer credentials are unavailable (non-UDS transport,
  unresolvable uid, non-Linux).
- Guarantee the service identity's effective confirmation window is `0`
  regardless of deployment configuration.
- Log which identity was resolved, and by which path, so an operator can tell
  confirmations apart.
- Write unit tests.

**NOT in scope**: the bridge module, the HITL channel override (TASK-2290), any
`claude_agent.py` change, changing `ConfirmationGuard` itself (FEAT-235 is
read-only for this feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` | MODIFY | read `SO_PEERCRED` in the connection handler; carry identity on `Session` |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | MODIFY | add `ServiceIdentityConfig` (env-driven, with defaults) |
| `packages/ai-parrot-integrations/tests/agentd/test_caller_identity.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import PermissionContext, UserSession   # verified: parrot/auth/permission.py:81, :21
from parrot.auth import ConfirmationGuard                           # verified: parrot/auth/__init__.py:77
from parrot.auth.confirmation import ConfirmationConfig             # verified: parrot/auth/confirmation.py:66
# stdlib
import socket, struct, pwd
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass
class UserSession:                                             # line 21
    user_id: str; tenant_id: str; roles: frozenset[str]
@dataclass
class PermissionContext:                                       # line 81
    session: UserSession                                       # line 123
    request_id: Optional[str] = None                           # line 124
    channel: Optional[str] = None                              # line 125
    trace_context: "Optional[TraceContext]" = None             # line 126
    extra: dict[str, Any] = field(default_factory=dict)        # line 127
    @property
    def user_id(self) -> str: ...                              # line 130

# packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationConfig(BaseModel):                           # line 66
    window_seconds: int = Field(0, ge=0)   # 0 == "always re-ask"   # line 83
    approval_timeout: float = Field(120.0, gt=0)               # line 84
    default_channel: str = "telegram"                          # line 85
# Window store key = (owner_id, tool_name, args_hash)          # line 116
# owner_id derives from permission_context.user_id; "anonymous" when None.

# packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py
class Session:
    def __init__(self, session_id: str, writer: asyncio.StreamWriter) -> None: ...  # line 93
    async def send(self, message) -> None: ...                 # line 101
    async def notify(self, method: str, params: dict) -> None: ...  # line 111
# server class:
    async def start(self) -> None: ...                         # line 200
    async def _handle_connection(self, ...) -> ...: ...        # line 267   <- the hook
    async def _run_handler(self, session: Session, request) -> None: ...    # line 317
    async def _disconnect(self, session: Session) -> None: ...  # line 359
```

### Verified mechanism (probe ran successfully on this machine)
```python
# Linux 6.11, Python 3.12, asyncio UDS server
sock = writer.get_extra_info("socket")
raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
pid, uid, gid = struct.unpack("3i", raw)
user = pwd.getpwuid(uid).pw_name
# observed: {'pid': 882139, 'uid': 1000, 'gid': 1000, 'user': 'jesuslara'}
# uid == os.getuid() -> True
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
- **agentd captures no caller identity today.** No `SO_PEERCRED`, `getsockopt`,
  `getpeername` or `ucred` anywhere under
  `packages/ai-parrot-integrations/src/parrot/integrations/agentd/` (grep: 0
  hits), and `server.py` has no `user_id` / `permission_context` /
  `PermissionContext`. This is new work, not a wiring change.
- ~~`Session.identity`~~ / ~~`Session.user_id`~~ / ~~`Session.permission_context`~~
  — none exist; this task adds whichever it needs.
- ~~`ServiceIdentityConfig`~~ — does not exist anywhere; this task creates it.
- ~~`ConfirmationConfig.confirm_window_seconds`~~ — the real field is
  **`window_seconds`**; `confirm_window_seconds` appears only in the
  `ConfirmationGuard` class docstring and is **stale**. Do not code against it.
- ~~`AgentServiceConfig.identity`~~ — not a field today (existing fields: `name`,
  `agent`, `socket`, `scheduler`, `exposed_methods`, `log_level`,
  `max_line_bytes`, `shutdown_grace`).

---

## Implementation Notes

### Key Constraints
- `SO_PEERCRED` is **Linux-specific** and only meaningful on a Unix-domain
  socket. Guard the read: wrap in try/except and fall back to the service
  identity on `AttributeError` (no `SO_PEERCRED` on the platform), `OSError`
  (not a UDS), or `KeyError` (uid has no `pwd` entry).
- The struct format is `"3i"` (pid, uid, gid) on Linux — use
  `struct.calcsize("3i")` for the `getsockopt` buffer length, do not hardcode 12.
- The service identity's `window_seconds` must be pinned to `0` and NOT be
  configurable. Its `owner_id` is shared by construction, so a non-zero window
  would let one human's approval clear a later destructive call made for
  somebody else.
- `AgentServiceConfig` already supports env-var expansion in YAML values
  (`expand_env_vars`, `${VAR}` and a bare-name shorthand) — reuse that mechanism
  for the service-identity fields rather than reading `os.environ` ad hoc where
  a config field would do.
- async throughout; Pydantic for `ServiceIdentityConfig`; `self.logger`.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py:267` — `_handle_connection`, the hook
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` — `AgentServiceConfig`, `expand_env_vars`
- `packages/ai-parrot/src/parrot/auth/confirmation.py:417` — `ConfirmationGuard.confirm()`, the consumer of `permission_context`

---

## Acceptance Criteria

- [ ] A UDS connection resolves the peer's OS username via `SO_PEERCRED` → uid → `pwd`
- [ ] The resolved identity is reachable from the request handler path
- [ ] A `PermissionContext` wrapping a `UserSession` is built from it
- [ ] `"anonymous"` never appears as the owner on this path
- [ ] Unresolvable uid / non-UDS / non-Linux falls back to the service identity
- [ ] `ServiceIdentityConfig` reads from environment variables and has defaults
- [ ] The service identity's effective `window_seconds` is `0` even when a
      deployment configures a larger value — asserted by test
- [ ] The resolved identity and its resolution path are logged
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/ -v`
- [ ] No new `ruff check` findings in the touched files

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_caller_identity.py
import pytest


class TestPeerCredentials:
    async def test_peercred_resolves_os_user(self, uds_peer): ...
    async def test_unresolvable_uid_falls_back_to_service_identity(self): ...
    async def test_non_uds_transport_falls_back(self): ...

class TestServiceIdentity:
    def test_read_from_environment(self, monkeypatch): ...
    def test_defaults_when_env_unset(self): ...
    def test_window_seconds_pinned_to_zero(self): ...
    def test_window_seconds_zero_even_when_deployment_raises_it(self): ...

class TestPermissionContextPropagation:
    async def test_permission_context_reaches_execute_tool(self): ...
    async def test_owner_is_never_anonymous(self): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
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
