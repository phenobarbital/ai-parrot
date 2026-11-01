# TASK-5091: Teams connections use `ConnectionAuthorizer` — one request-less policy surface

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5063, TASK-5073, TASK-5076
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:3a7ee22eb09a`
**Discovered-from**: `issue:6a7d92155439`

---

## Context

After FEAT-775 was reconciled with FEAT-777 (merged on dev), `IntegrationsService._authorize` carried two
request-less authorization models: Teams passed a `PermissionContext` evaluated by the URI-parity
`pdp_permission_evaluator` (`/api/v1/connections…`, `uri:read/write/delete`, roles/groups always empty), while
Slack/CLI passed a `Principal` evaluated by `ConnectionAuthorizer` / `NavigatorConnectionAuthorizer`
(`integration` resource actions, trusted roles/groups/tenant from the auth DB). Policies written for one did not
apply to the other, and Teams users could not be granted access by group (issue:3a7ee22eb09a). It is also the
leftover of the duplicated PBAC hook recorded in issue:6a7d92155439.

**Owner decision (2026-11-01, /sdd-fix):** `ConnectionAuthorizer` is the single non-web policy surface. This
supersedes the 2026-10-31 "FEAT-775's `permission_evaluator` is authoritative" decision, which predates FEAT-777's
`authorizer=` landing on dev. The fix lands on the FEAT-775 branch so PR #1911 merges with one model.

## Scope

- `IntegrationsService`: remove `permission_evaluator=`, `PermissionEvaluator`, `_CONNECTION_ROUTES`,
  `pdp_permission_evaluator`, `_check_context_pbac` and the `operation=` plumbing. Keep `permission_context=` on
  the public methods purely as the `_context_matches` identity check; a context call is then authorized by the
  injected `ConnectionAuthorizer` (principal required, `principal.user_id == user_id`) and never falls back to
  request PBAC.
- `_channel_service_factory` (integrations manager): build Teams services with
  `authorizer=app.get("connection_authorizer")`, read per call (the server installs it at startup).
- Update the Teams permission docs (`docs/integrations/msteams-connections.md`) and `docs/auth/connections.md`.
- Update the tests that exercised the evaluator.

**NOT in scope**: `NavigatorConnectionAuthorizer` itself, the web request PBAC path, Slack/CLI wiring.

## Files to Modify

- `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
- `packages/ai-parrot/tests/auth/test_connections_permission_context.py`
- `packages/ai-parrot/tests/auth/test_oauth2_scope_propagation.py`
- `packages/ai-parrot-server/tests/test_teams_connections_wiring.py`
- `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py`
- `docs/integrations/msteams-connections.md`
- `docs/auth/connections.md`

## Codebase Contract

### Verified Imports
- `from parrot.auth.oauth2.authorization import ConnectionAuthorizer` (core Protocol, FEAT-777)
- `from parrot.services.connection_authorization import NavigatorConnectionAuthorizer` (server)

### Existing Signatures
- `ConnectionAuthorizer.authorize(principal, action, provider_id, scopes) -> bool`
- `BotManager._setup_channel_links(app)` installs `app["connection_authorizer"]` (ai-parrot-server `manager/manager.py`)
- `IntegrationsService._context_matches(user_id, principal, context, channel=None)`

### Does NOT Exist (after this task)
- `parrot.auth.oauth2.service.pdp_permission_evaluator`, `PermissionEvaluator`, `IntegrationsService(permission_evaluator=...)`

## Acceptance Criteria

- [x] Teams list/status/connect/disconnect call `ConnectionAuthorizer.authorize` with `integration:list|connect|disconnect`.
- [x] Identity mismatch between target, principal and `PermissionContext` denies before the authorizer runs.
- [x] Missing authorizer, missing principal, authorizer error or non-`True` decision denies closed.
- [x] A context call with an aiohttp request present never falls back to request PBAC.
- [x] No `permission_evaluator` / URI-parity references remain in source, tests or docs.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src \
  pytest -q packages/ai-parrot/tests/auth/test_connections_permission_context.py \
  packages/ai-parrot/tests/auth/test_oauth2_scope_propagation.py \
  packages/ai-parrot-server/tests/test_teams_connections_wiring.py \
  packages/ai-parrot-server/tests/unit/test_connection_authorization.py \
  packages/ai-parrot-integrations/tests/integrations/msteams/ \
  packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py
```

## Completion Note

_(filled on close)_
