# TASK-4974: CliPrincipalResolver, build_cli_permission_context and `parrot whoami`

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4968, TASK-4972
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (G2, S3, S7, AC-3): a FEAT-773 `PrincipalResolver` for `channel in {"cli", "agentd"}` backed by the
login file + `GET /api/v1/connections/me`. Its output feeds the stdio server (TASK-4976), the REPL (TASK-4978) and agentd
(TASK-4979). The `O365_PRINCIPAL` bootstrap removal in `cli/identity.py` is done by TASK-4978 (it must change together
with its only caller, `agent_repl.py`).

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/principal.py`: `CLI_CHANNELS`, `CliPrincipalResolver` (`resolve`,
  `resolve_with_roles`), `build_cli_permission_context(principal, *, roles)`.
- `parrot/cli/login.py`: add the `whoami` click command; after `store.save(record)` in `login`, best-effort fill
  `roles`/`tenant_id` from `/me` and save again.
- Tests.

**NOT in scope**: editing `cli/identity.py` or `agent_repl.py` (TASK-4978); registering the resolver process-wide with `set_principal_resolver` (no CLI surface needs the global seam); agentd (TASK-4979).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/principal.py` | CREATE | CliPrincipalResolver + permission context |
| `packages/ai-parrot/src/parrot/cli/login.py` | MODIFY | whoami command + roles fill after login |
| `packages/ai-parrot/tests/cli/test_cli_principal.py` | CREATE | resolver + whoami tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.auth.principal import Principal                               # principal.py:18 (PrincipalResolver Protocol :37)
from parrot.auth.permission import PermissionContext, build_principal_context   # permission.py:81, :166
from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient   # TASK-4972
from parrot.cli.login import LoginExpired, LoginFileError, LoginStore      # TASK-4968
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/principal.py
class Principal(BaseModel): user_id: str; canonical_identity: Optional[str]=None; tenant_id: Optional[str]=None; channel: str; channel_user_id: str   # :18
class PrincipalResolver(Protocol): async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]   # :37
# packages/ai-parrot/src/parrot/auth/permission.py
def build_principal_context(principal: str, *, channel: str, tenant_id: Optional[str] = None,
                            roles: Optional[frozenset[str]] = None) -> PermissionContext   # :166 — tenant_id or principal (:202) !
# TASK-4972: ServerConnectionsClient(store).me() -> WhoAmI(user_id, tenant_id, canonical_identity, email, roles, scopes)
#            raises NotLoggedIn / LoginExpired / RuntimeError ; refreshes the bearer once on 401 itself
# TASK-4968 parrot/cli/login.py — anchor written by that task inside `login()`:
#     store.save(record)
#     # roles/tenant are filled from GET /api/v1/connections/me by TASK-4974
```

### Does NOT Exist
- ~~`parrot.cli.principal` / `CliPrincipalResolver`~~ — created here.
- ~~`build_cli_permission_context(principal, roles=...)` in `cli/identity.py`~~ — the old one there takes `user_id`;
  TASK-4978 turns identity.py into a re-export of this one. Do not edit identity.py here.
- ~~`CanonicalIdentityMapper.to_canonical(str)`~~ — takes a dict; S-4 never calls it (identity comes from `/me`).
- ~~`set_principal_resolver(CliPrincipalResolver(...))`~~ — not needed; callers use the resolver directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/cli/principal.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/login.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_cli_principal.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#Principal",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context"
  ]
}
```

---

## Implementation Notes

- **Tenant (spec §7 principal_guard discipline):** `build_principal_context` falls back to `tenant_id or principal`
  (`permission.py:202`). Never let that happen: if `principal.tenant_id` is falsy pass the literal `"default"` (the same
  default `ServiceIdentityConfig.tenant_id` uses, `agentd/config.py:165`) and log a debug line.
- `resolve_with_roles`: channel not in `CLI_CHANNELS` → `None`; no login → `None`; `LoginFileError`, `NotLoggedIn`,
  `LoginExpired`, network/HTTP errors → `self.logger.warning(...)` and `None` (callers then fall back exactly as today,
  AC-4). Roles = `frozenset(who.roles) | frozenset(who.scopes)` (S7).
- `Principal(user_id=who.user_id, canonical_identity=who.canonical_identity or who.email, tenant_id=who.tenant_id,
  channel=channel, channel_user_id=channel_user_id)`.
- `whoami`: prints user id, email, tenant, roles (stdout is fine — not a stdio server); not logged in → message +
  exit 1. Close the client (`async with`).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `principal.py` — *why*: one resolver for cli + agentd (S3).
2. Add `whoami` and the post-login `/me` fill to `login.py` — *why*: §3 M1/M2 split; roles are server-issued (S7).
3. Write tests with a stub `ServerConnectionsClient`; run the validation commands.

### `packages/ai-parrot/src/parrot/cli/principal.py` (CREATE)
```python
"""Navigator principal for CLI surfaces (FEAT-774 M2): login file + GET /api/v1/connections/me."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient
from parrot.auth.permission import PermissionContext, build_principal_context
from parrot.auth.principal import Principal
from parrot.cli.login import LoginExpired, LoginFileError, LoginStore

logger = logging.getLogger(__name__)
CLI_CHANNELS = frozenset({"cli", "agentd"})
_FALLBACK_TENANT = "default"


class CliPrincipalResolver:
    """Satisfies FEAT-773 ``PrincipalResolver`` for ``cli`` / ``agentd``."""

    def __init__(self, store: LoginStore, client: ServerConnectionsClient) -> None:
        self.store = store
        self.client = client
        self.logger = logger

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        resolved = await self.resolve_with_roles(channel, channel_user_id)
        return resolved[0] if resolved else None

    async def resolve_with_roles(
        self, channel: str, channel_user_id: str,
    ) -> Optional[Tuple[Principal, frozenset[str]]]:
        """Principal + server-issued roles ∪ scopes (S7); ``None`` → caller keeps today's behaviour."""
        if channel not in CLI_CHANNELS:
            return None
        # FILL IN: record = await asyncio.to_thread(self.store.load_optional) (LoginFileError → warning, None); None → None;
        #          who = await self.client.me() (NotLoggedIn/LoginExpired/RuntimeError/aiohttp.ClientError → warning, None);
        #          return Principal(...), frozenset(who.roles) | frozenset(who.scopes) — AC-3, AC-4
        raise NotImplementedError


def build_cli_permission_context(principal: Principal, *, roles: frozenset[str] = frozenset()) -> PermissionContext:
    """``build_principal_context`` with the server's tenant — never the principal as tenant (spec §7)."""
    tenant = principal.tenant_id or _FALLBACK_TENANT
    return build_principal_context(principal.user_id, channel=principal.channel, tenant_id=tenant, roles=roles)
```

### `packages/ai-parrot/src/parrot/cli/login.py` (MODIFY — roles fill)
```python
# occurrences: 1 (verified: grep -c '# roles/tenant are filled from GET /api/v1/connections/me by TASK-4974' cli/login.py)
# REPLACE that comment line (inside login(), right after `store.save(record)`) with:
    record = asyncio.run(_fill_from_me(store, record))
```

### `packages/ai-parrot/src/parrot/cli/login.py` (MODIFY — append at end of file)
```python
async def _fill_from_me(store: LoginStore, record: LoginRecord) -> LoginRecord:
    """Best effort: copy roles/tenant from GET /api/v1/connections/me into the login file."""
    from parrot.auth.oauth2.remote_client import ServerConnectionsClient  # lazy: remote_client imports this module

    try:
        async with ServerConnectionsClient(store) as client:
            who = await client.me()
    except Exception as exc:  # noqa: BLE001 — the login itself already succeeded
        logger.warning("Could not read /api/v1/connections/me after login: %s", type(exc).__name__)
        return record
    updated = record.model_copy(update={"roles": list(who.roles), "tenant_id": who.tenant_id or record.tenant_id})
    store.save(updated)
    return updated


@click.command("whoami")
def whoami() -> None:
    """Print the Navigator identity behind the current login."""
    from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient  # lazy (import cycle)

    # FILL IN: asyncio.run(async with ServerConnectionsClient(LoginStore()) → me()); print user_id, email, tenant_id, roles;
    #          NotLoggedIn → "Not logged in — run `parrot login`" + sys.exit(1); LoginExpired → same hint + exit 1
    raise NotImplementedError
```
**Why**: `remote_client` imports `parrot.cli.login` at module level, so `login.py` may only import it lazily inside
functions (top-level import → circular import).

### `packages/ai-parrot/tests/cli/test_cli_principal.py` (CREATE)
```python
"""CliPrincipalResolver (FEAT-774 M2)."""
import pytest

from parrot.auth.oauth2.models import WhoAmI
from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context


async def test_cli_principal_resolver_channels(tmp_path):
    # FILL IN: stub client.me() → WhoAmI(user_id="1042", tenant_id="troc", email=...); "cli"/"agentd" → Principal with
    #          Navigator id, tenant, canonical_identity=email; "telegram" → None; no login file → None
    ...

async def test_cli_principal_roles_from_server(tmp_path):
    # FILL IN: roles ∪ scopes; build_cli_permission_context(...).session.tenant_id == "troc" and != user_id;
    #          tenant None → "default", never the user id
    ...

async def test_resolver_returns_none_on_network_error(tmp_path):
    ...

def test_whoami_not_logged_in_exit_1(tmp_path, monkeypatch):
    ...
```

### FILL IN checklist
- [ ] `CliPrincipalResolver.resolve_with_roles` — load, /me, error → None; bounded by AC-3/AC-4
- [ ] `whoami` — output + exit codes
- [ ] tests — stub client, tenant discipline

---

## Acceptance Criteria

- [ ] `cli`/`agentd` resolve to a `Principal` with the Navigator id, tenant and email; other channels and no login → `None`
- [ ] `build_cli_permission_context` carries roles ∪ scopes and the server tenant — never the principal as tenant (AC-3)
- [ ] `parrot whoami` prints the identity; without a login it exits 1 with a hint
- [ ] After `parrot login`, `login.json` holds the server-issued roles (best effort)
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_cli_principal.py -q`
- `pytest packages/ai-parrot/tests/unit/test_permission_context_channel.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/cli/test_cli_principal.py block in the blueprint
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

**Completed by**: gpt-5.6-sol (codex) (1 attempt), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Implemented as specified; task tests green. Merge-tier: only tests/cli/test_session.py::test_stream_closed_in_turn_task_after_final_message fails (sandbox read-only ~/.parrot/cli, environmental).
