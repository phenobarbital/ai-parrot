# TASK-5080: Spec AC-11 — agentd trusted-server pin, off by default, read-only peer store

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (<1h)
**Depends-on**: TASK-4979
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:08e55d4b23ca`

## Context

Review fix c252e73ea6 (`issue:3658ef66a9a7`) changed the agentd login-file step: it is off until
`AGENTD_LOGIN_FILE_SERVER_URL` pins a trusted Navigator server, a record naming another server is ignored,
requests always go to the pinned URL, and the peer store is read-only. Code
(`agentd/server.py::_login_file_identity`, `agentd/config.py::ServiceIdentityConfig`) and
`docs/cli/parrot-login-and-connections.md` already describe this; the spec still described the original
file-checks-only step.

## Scope

Spec text only — amend G7, the §2 agentd (M9) data-flow paragraph, §3 Module 9 (responsibility + skeleton),
the §4 M9 test rows, and AC-11.

**NOT in scope**: any code, test or docs change (already aligned).

## Files to Create / Modify

- `sdd/specs/connections-cli-local-mcp.spec.md` (modify)

## Acceptance Criteria

- [x] AC-11 states the trusted-server requirement, the off-by-default behaviour and read-only access.
- [x] Module 9 lists `login_file_server_url` / `login_file_enabled` and the read-only store.
- [x] Every test name added to the §4 table exists in
      `packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py`.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src pytest packages/ai-parrot-integrations/tests/agentd/test_login_file_identity.py -q
```

## Completion Note

Spec-only amendment, filed post-`/sdd-done` on the FEAT-774 PR branch (#1900) by `/sdd-fix`.
The cited tests pass against the branch code unchanged.
