# TASK-5081: FEAT-774 review fixes — origin-bound login bearer, fail-closed identity, AC-9 completion check, PBAC on device poll / complete

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4978, TASK-4976, TASK-4977, TASK-4971
**Assigned-to**: unassigned
**Discovered-from**: `issue:91d35526d51d`

---

## Context

The FEAT-774 code review deferred six IMPORTANT findings into ledger issue `issue:91d35526d51d`.
This task fixes the six numbered findings. The issue's trailing "Suggestions" list (non-loopback
`http://` warning, discovery-origin check, `ConnectionCache._read_sync` file checks, unclosed client
sessions, `Cache-Control: no-store`, AC-4 adapter behaviour) is out of scope and filed as a separate
minor ledger issue.

## Scope

1. **Login bearer bound to its origin** (`cli/agent_repl.py`). The login access token (and the
   one-shot 401 refresh via `login_store`) is the implicit `--server` bearer **only** when the
   `--server` origin (scheme, host, effective port) equals `login.server_url`'s origin. Otherwise no
   implicit bearer is sent, `login_store` is not passed, and a one-line notice tells the user to pass
   `--token` / `PARROT_SERVER_TOKEN`. An explicit `--token` is always honoured.
2. **Fail-closed identity.**
   - `cli/agent_repl.py`: standalone + a login whose principal cannot be resolved exits 2 (no silent
     fallback to `cli-user`).
   - `mcp/toolkit_server.py` `_bind_identity`: when a login exists but is unsafe/unreadable or the
     principal cannot be resolved, tools that declare a `credential_provider` return an MCP
     authorization-required error instead of running anonymously. Tools without a provider are
     unchanged; no login keeps today's behaviour. Implemented through a new optional
     `identity_error` field on `mcp/adapter.py` `ToolExecutionContext`.
3. **AC-9 completion check** (`cli/connect.py` `_completed_after`): completion requires
   `status == "connected"` **and** `connected_at >= started_at`; `updated_at` no longer counts, so a
   refresh of an already-connected row is not mistaken for completion. Naive ISO timestamps are read
   as UTC; unparseable timestamps are not completion.
   *Spec erratum*: AC-9 says `status == "active"`; `"active"` is the internal `UsersIntegrationRow`
   value — the connections API descriptor reports `"connected"` / `"needs_reconnect"` /
   `"disconnected"` (`IntegrationsService._descriptor`). The check uses the API vocabulary.
   Trade-off: a same-account reconnect keeps the old `connected_at` server-side
   (`persist_credential`), so polling does not detect it and the command falls back to the paste
   prompt at expiry.
4. **Tests for AC-3 / AC-14** at the `parrot agent` entry point: `--user` with a login exits 2;
   standalone `user_id` == Navigator id with `PermissionContext` channel `cli`; no principal resolved
   and `REPLConfig.user_id is None` in `--server` mode; bearer only for the login's origin.
5. **Test isolation**: an autouse fixture in `tests/cli/conftest.py` points `PARROT_LOGIN_FILE` at a
   per-test temp path so no CLI test reads the developer's real `~/.parrot/login.json`.
6. **Server PBAC + corrupt record** (`auth/oauth2/service.py`): `device_poll` and `complete_connect`
   check PBAC `integration:connect` (fail closed → `PermissionError`, 403); `device_poll` returns
   `{"status": "failed", "reason": ...}` for an undecodable device record instead of a 500.

**NOT in scope**: the "Suggestions" list above; any change to `persist_credential` or the server
descriptor; spec text edits beyond this task's erratum note.

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/cli/agent_repl.py` — MODIFY
- `packages/ai-parrot/src/parrot/cli/connect.py` — MODIFY
- `packages/ai-parrot/src/parrot/mcp/adapter.py` — MODIFY
- `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` — MODIFY
- `packages/ai-parrot/src/parrot/auth/oauth2/service.py` — MODIFY
- `packages/ai-parrot/tests/cli/conftest.py` — MODIFY
- `packages/ai-parrot/tests/cli/test_repl_identity_matrix.py` — MODIFY
- `packages/ai-parrot/tests/cli/test_connect.py` — MODIFY
- `packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py` — MODIFY
- `packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py` — MODIFY
- `tests/mcp/test_toolkit_server_login.py` — MODIFY

## Codebase Contract

### Verified Imports
- `from parrot.cli.login import LoginFileError, LoginStore, LoginRecord` — `cli/login.py`
- `from parrot.mcp.adapter import ToolExecutionContext, auth_required_result` — `mcp/adapter.py`
- `from parrot.auth.credentials import AuthRequiredPayload` — `auth/credentials.py:114`

### Existing Signatures
- `IntegrationsService._check_pbac(self, request, action, provider_id=None, scopes=None) -> bool` — fails closed.
- `IntegrationsService.device_poll(self, user_id, provider_id, *, handle, request=None) -> Dict[str, Any]`
- `IntegrationsService.complete_connect(self, user_id, provider_id, *, code, state, channel, request=None)`
- `ServerAgentProxy(server_url, timeout=30, *, token=None, login_store=None)` — `cli/loaders.py`
- `_completed_after(status: Dict[str, Any], started_at: float) -> bool` — `cli/connect.py`

### Does NOT Exist
- A `"active"` status in the connections API descriptor.

## Acceptance Criteria

- [ ] A login for host A never sends its token to `--server` host B; same origin still does.
- [ ] Standalone REPL with an unresolvable login principal exits 2.
- [ ] `mcp-local` with an unusable login returns an auth-required error from credential tools.
- [ ] `_completed_after` ignores `updated_at`; stale-row test passes.
- [ ] AC-3 / AC-14 entry-point tests exist and pass.
- [ ] CLI tests never read the real login file.
- [ ] `device_poll` / `complete_connect` deny without PBAC; corrupt device record → `failed`.

## Validation Commands

```bash
pytest packages/ai-parrot/tests/cli/test_repl_identity_matrix.py packages/ai-parrot/tests/cli/test_agent_command.py packages/ai-parrot/tests/cli/test_connect.py packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py tests/mcp/test_toolkit_server_login.py packages/ai-parrot/tests/mcp/test_adapter_execution_context.py -q
```

## Completion Note

*(filled in on close)*
