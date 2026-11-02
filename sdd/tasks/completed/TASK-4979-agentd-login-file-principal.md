# TASK-4979: agentd resolves the Navigator principal from the peer's login file

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4974
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (G7, U5, S11, AC-11, §8 Q3 per-user daemon): after SO_PEERCRED resolves the peer uid, agentd reads that
user's `~/.parrot/login.json` (regular file, owner == uid, mode 0600, `O_NOFOLLOW`, off the event loop) and resolves the
Navigator principal with `channel="agentd"`; `identity_source` becomes `"login_file"`. Any failure keeps today's
peercred / service-identity behaviour. `AGENTD_LOGIN_FILE_LOOKUP=0` disables the step.

---

## Scope

- `agentd/config.py`: `ServiceIdentityConfig.login_file_lookup: bool = True`, read from `AGENTD_LOGIN_FILE_LOOKUP` in
  `from_env`.
- `agentd/server.py`: the login-file step in `_resolve_identity` between peercred and its return.
- Tests including the daemon-level e2e (`agent.info` reports the Navigator id and `identity_source == "login_file"`).

**NOT in scope**: the UDS transport / SO_PEERCRED binding themselves; a shared-service-user daemon (§8 Q3: out of scope).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` | MODIFY | login-file step |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | MODIFY | login_file_lookup flag |
| `packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py` | CREATE | unit + daemon e2e |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.auth.permission import PermissionContext, build_principal_context   # agentd/server.py:28 (already)
from parrot.cli.login import LoginFileError, LoginStore                         # TASK-4968 — lazy inside the method
from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context   # TASK-4974 — lazy
from parrot.auth.oauth2.remote_client import ServerConnectionsClient            # TASK-4972 — lazy
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py
import pwd                                                                       # :20
def _read_peercred(sock) -> tuple[int, int, int]                                 # :62
def _uid_to_username(uid: int) -> str                                            # :77
class JsonRpcUnixServer:                                                         # :214
    def __init__(self, socket_path, dispatch, *, max_line_bytes=..., service_identity: ServiceIdentityConfig | None = None)   # :228-235 ; self.service_identity
    async def _resolve_identity(self, writer) -> tuple[PermissionContext, str]:  # :323-361
            _pid, uid, _gid = await asyncio.to_thread(_read_peercred, sock)     # :353
            username = await asyncio.to_thread(_uid_to_username, uid)           # :354
            return build_principal_context(username, channel="agentd"), "peercred"   # :355
        except (AttributeError, OSError, KeyError) as exc: ... "service_identity"    # :356-361
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py
class ServiceIdentityConfig(BaseModel): model_config = ConfigDict(extra="forbid"); display_name; user_id="1001";
    tenant_id="default"; roles: frozenset[str] = Field(default_factory=frozenset) (:166)   # :131
    @classmethod def from_env(cls) -> ServiceIdentityConfig   # :179 — env constants _ENV_SERVICE_IDENTITY_* near :37-40
# TASK-4968: LoginStore.for_uid(uid); load_optional(*, expected_uid) raises LoginFileError on symlink/mode/owner
# TASK-4974: CliPrincipalResolver(store, client).resolve_with_roles("agentd", username) -> Optional[(Principal, roles)]
```

### Does NOT Exist
- ~~`AGENTD_LOGIN_FILE_LOOKUP`, `ServiceIdentityConfig.login_file_lookup`~~ — added here.
- ~~agentd reading `~/.parrot` today~~ — `_resolve_identity` only does peercred → username.
- ~~`identity_source == "login_file"`~~ — new value added here (existing: `peercred`, `service_identity`).
- ~~`JsonRpcUnixServer.login_file_lookup`~~ — the flag lives on `self.service_identity` (the config object).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py#JsonRpcUnixServer",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py#ServiceIdentityConfig"
  ]
}
```

---

## Implementation Notes

- Insert the step after `username = ...` (:354) and before the peercred `return` (:355). Every blocking call goes
  through `asyncio.to_thread` (`LoginStore.for_uid` does a `pwd` lookup, `load_optional` does file I/O).
- `load_optional(expected_uid=uid)` enforces owner/mode/symlink; `LoginFileError` → `self.logger.warning(...)` and fall
  through to peercred. Resolver `None` → peercred. Network errors are swallowed by the resolver (TASK-4974).
- Close the `ServerConnectionsClient` (`async with`).
- `from_env`: `AGENTD_LOGIN_FILE_LOOKUP` in {"0", "false", "no", "off"} (case-insensitive) → False.
- Tests: owner/mode checks without root — create the file with mode 0600 under `tmp_path`, monkeypatch
  `LoginStore.for_uid` to point there; to simulate a wrong owner pass a different `expected_uid` (or monkeypatch
  `os.fstat`). For the daemon e2e reuse the fixtures/patterns of `tests/agentd/test_caller_identity.py`.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `login_file_lookup` + env parsing to `ServiceIdentityConfig` — *why*: AC-11 opt-out.
2. Insert the login-file step in `_resolve_identity` — *why*: U5/S11.
3. Write unit + daemon tests; run them plus the existing agentd tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    roles: frozenset\[str\] = Field(default_factory=frozenset)' agentd/config.py)
# AFTER — insert below that line (verified: config.py:166)
    login_file_lookup: bool = True  # FEAT-774: read the peer's ~/.parrot/login.json (AGENTD_LOGIN_FILE_LOOKUP=0 disables)
# FILL IN: in from_env (:179) read os.environ.get("AGENTD_LOGIN_FILE_LOOKUP"); falsy tokens → kwargs["login_file_lookup"] = False
```

### `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            return build_principal_context(username, channel="agentd"), "peercred"' agentd/server.py)
# BEFORE — insert above that line (verified: server.py:355), same indentation (inside the try):
            if self.service_identity.login_file_lookup:
                resolved = await self._login_file_identity(uid, username)
                if resolved is not None:
                    return resolved, "login_file"

# INSERT a new method on JsonRpcUnixServer right after _resolve_identity:
    async def _login_file_identity(self, uid: int, username: str) -> PermissionContext | None:
        """Navigator principal from the peer's own login file (S11); ``None`` keeps peercred."""
        from parrot.auth.oauth2.remote_client import ServerConnectionsClient
        from parrot.cli.login import LoginFileError, LoginStore
        from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context

        try:
            store = await asyncio.to_thread(LoginStore.for_uid, uid)
            record = await asyncio.to_thread(store.load_optional, expected_uid=uid)
        except (LoginFileError, KeyError, OSError) as exc:
            self.logger.warning("Ignoring login file for uid %s: %s", uid, type(exc).__name__)
            return None
        if record is None:
            return None
        # FILL IN: async with ServerConnectionsClient(store) as client → CliPrincipalResolver(store, client)
        #          .resolve_with_roles("agentd", username); None → None; else build_cli_permission_context(principal, roles=roles)
        raise NotImplementedError
```
Update the `_resolve_identity` docstring: `identity_source` is `"login_file"`, `"peercred"` or `"service_identity"`.

### `packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py` (CREATE)
```python
"""agentd login-file principal (FEAT-774 M9, AC-11)."""
import pytest


async def test_agentd_login_file_principal(tmp_path, monkeypatch):
    # FILL IN: valid 0600 login file for the peer uid + patched resolver → identity_source "login_file", Navigator id;
    #          symlink / 0644 / wrong owner → "peercred"
    ...

async def test_agentd_login_lookup_disabled(tmp_path, monkeypatch):
    # FILL IN: AGENTD_LOGIN_FILE_LOOKUP=0 → ServiceIdentityConfig.from_env().login_file_lookup is False → "peercred"
    ...

async def test_e2e_agentd_login_file(tmp_path, monkeypatch):
    # FILL IN: daemon on a tmp UDS (pattern: tests/agentd/test_caller_identity.py) → agent.info reports the Navigator id
    #          and identity_source == "login_file"
    ...
```

### FILL IN checklist
- [ ] `ServiceIdentityConfig.from_env` — AGENTD_LOGIN_FILE_LOOKUP parsing
- [ ] `_login_file_identity` — resolve + permission context; bounded by AC-11 (any failure → None → peercred)
- [ ] tests — file checks without root, daemon e2e

---

## Acceptance Criteria

- [ ] A valid peer login file (regular, owner == uid, 0600) yields the Navigator principal with `identity_source == "login_file"` (AC-11)
- [ ] Symlink, wrong mode, wrong owner, unreadable file or server failure → today's peercred / service identity (AC-11)
- [ ] `AGENTD_LOGIN_FILE_LOOKUP=0` disables the step
- [ ] Existing agentd tests green; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py -q`
- `pytest packages/ai-parrot-integrations/tests/agentd/test_caller_identity.py -q`
- `pytest packages/ai-parrot-integrations/tests/agentd/test_server.py -q`
- `pytest packages/ai-parrot-integrations/tests/agentd/test_mcp_proxy.py -q`

---

## Test Specification

```python
# see packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sonnet (native) (1 attempt), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Added login-file identity lookup with a cheap pre-check (_peer_login_file_exists) to avoid a 1.4s lazy import breaking test_caller_identity timing. Pre-existing failure test_e2e.py::test_no_aiohttp_without_server_pkg is unrelated. Merge-tier reds are pre-existing/environmental only (tests/mcp/test_toolkit_server.py, issue:203c75e0c1ac; sandbox read-only ~/.parrot/cli in test_session).
**Review fix** (c252e73ea6, issue:3658ef66a9a7): the login-file step is now off until `AGENTD_LOGIN_FILE_SERVER_URL` names a trusted Navigator server. Records naming any other server are ignored, and requests go to the pinned URL only. The peer store is read-only: no refresh, lock, temp file or rewrite, the owner is re-checked on every load, and a 401 falls back to peercred. The login lock file is opened with `O_NOFOLLOW`. This narrows AC-11, which the spec defines with file checks only; the spec text was not changed. Model feedback was NOT recorded, because the coder execution was already closed.
