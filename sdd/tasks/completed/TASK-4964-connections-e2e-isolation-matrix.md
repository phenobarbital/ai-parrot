# TASK-4964: End-to-end connection flows and the S11 isolation matrix

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4949, TASK-4958, TASK-4959, TASK-4957
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and AC-17 (S11 isolation matrix). The three existing e2e files still exercise
`confirm_enable`, `enabled_on_agent`, `jira_oauth_callback` and channel-scoped keys. They are rewritten for the
principal-keyed flow, and a new isolation-matrix file covers: cross-principal read denied, unlinked-user rejection,
legacy deletion, concurrent refresh single flight, notifier-failure isolation, durable-write-required callback,
`CredentialRequired` serialization, cross-channel reuse (telegram → web → a2a).

---

## Scope

- Rewrite `test_e2e_web_connect.py` (`test_e2e_web_connect_principal_keyed`), `test_e2e_telegram_regression.py`
  (`test_e2e_telegram_jira_parity`), `test_e2e_auth_envelope.py` (`test_authorization_required_roundtrip_both_signals`).
- New `test_connections_isolation_matrix.py`: `test_cross_channel_reuse`, `test_isolation_between_principals`,
  `test_callback_fails_without_durable_write`, plus the AC-17 rows not already covered by unit tests.
- Use `_oauth2_fakes`-style doubles (no fakeredis); real HTTP via aiohttp test client.

**NOT in scope**: production code changes — if a test exposes a bug, fix it only inside the owning task's file set via a follow-up note (or open a ledger issue), never silently here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/oauth2/test_e2e_web_connect.py` | MODIFY | principal-keyed web flow |
| `tests/integration/oauth2/test_e2e_telegram_regression.py` | MODIFY | Telegram parity via adapters |
| `tests/integration/oauth2/test_e2e_auth_envelope.py` | MODIFY | both signals through AgentTalk |
| `tests/integration/oauth2/test_connections_isolation_matrix.py` | CREATE | S11 matrix |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2.service import IntegrationsService          # verified: service.py:74
from parrot.auth.oauth2_routes import make_oauth2_callback          # verified: oauth2_routes.py:200
from parrot.auth.credentials import OAuthCredentialResolver, CredentialRequired   # verified: credentials.py:184, :113
from parrot.auth.principal import Principal, set_principal_resolver               # TASK-4937
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher   # TASK-4938
```

### Existing Signatures to Use
```python
# Final APIs (from the dependency tasks): IntegrationsService.start_connect(user_id, provider_id, return_origin=None, *,
#   channel="web", principal=None, scopes=None, request=None, extra_state=None); list_for_principal(user_id, request=None);
#   AbstractOAuth2Manager.get_valid_token(channel, user_id, *, channel_user_id=None); handle_callback(code, state);
#   OAuthCredentialResolver.resolve(channel, user_id); ToolManager.execute_tool(..., return_tool_result=True)
```

### Does NOT Exist
- ~~`confirm_enable`~~, ~~`enabled_on_agent`~~, ~~`jira_oauth_callback`~~, ~~`user_agent_toolkits`~~ — gone; remove their use from the e2e files.
- ~~`fakeredis`~~ — not installed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "tests/integration/oauth2/test_e2e_web_connect.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/integration/oauth2/test_e2e_telegram_regression.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/integration/oauth2/test_e2e_auth_envelope.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/integration/oauth2/test_connections_isolation_matrix.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Each test must assert behaviour, not mocks of the code under test: drive the real manager/service/callback with fake
  IdP endpoints (aiohttp test server) and in-memory Redis/store doubles.
- PBAC: patch the `abac` object the service uses (allow) for the happy paths; one test with deny.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Rewrite the three e2e files — *why*: they encode removed APIs.
2. Write the isolation matrix — *why*: AC-17.
3. Run the whole Validation Contract (feature tier) and record results.

### `tests/integration/oauth2/test_connections_isolation_matrix.py` (CREATE)
```python
"""S11 isolation matrix for FEAT-773 (AC-17)."""
import pytest

@pytest.mark.asyncio
async def test_cross_channel_reuse(): ...                     # FILL IN: connect as telegram principal 1042 → resolve on web (1042) and a2a (<email> → 1042)
@pytest.mark.asyncio
async def test_isolation_between_principals(): ...            # FILL IN: principal A's token never returned for B on any channel
@pytest.mark.asyncio
async def test_unlinked_user_rejected(): ...                  # FILL IN: unresolved telegram id → None / AuthorizationRequired, no channel-keyed fallback
@pytest.mark.asyncio
async def test_callback_fails_without_durable_write(): ...   # FILL IN: store raises → error page, no Redis key, no event
@pytest.mark.asyncio
async def test_notifier_failure_does_not_fail_callback(): ... # FILL IN
@pytest.mark.asyncio
async def test_credential_required_serialization(): ...      # FILL IN: through ToolManager → same metadata as AuthorizationRequired
```
### The three e2e files (MODIFY)
FILL IN: replace `confirm_enable`/`enabled_on_agent`/`jira_oauth_callback` usage with the generic callback +
`list_for_principal`; keep each file's scenario intent (web connect, Telegram regression, auth envelope).

### FILL IN checklist
- [ ] three e2e rewrites
- [ ] isolation matrix bodies
- [ ] full Validation Contract run recorded in the Completion Note

---

## Acceptance Criteria

- [ ] AC-17: isolation matrix passes (cross-principal denied, unlinked rejected, legacy deleted, single-flight refresh, notifier isolation, durable-write-required callback, CredentialRequired serialization)
- [ ] AC-3/AC-9: cross-channel reuse and Telegram parity proven end to end
- [ ] AC-16: the spec's Validation Contract passes

---

## Validation Commands

- `pytest tests/integration/oauth2/test_connections_isolation_matrix.py -q`
- `pytest tests/integration/oauth2/test_e2e_web_connect.py -q`
- `pytest tests/integration/oauth2/test_e2e_telegram_regression.py -q`
- `pytest tests/integration/oauth2/test_e2e_auth_envelope.py -q`

---

## Test Specification

```python
# see blueprint — tests ARE this task's deliverable
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-luna (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Feature-tier validation: all green except pre-existing env-dependent test_conf DevLoopSettings defaults (issue:2e80caa0aa09).
