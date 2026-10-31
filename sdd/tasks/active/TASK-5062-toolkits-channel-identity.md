# TASK-5062: Jira and O365 toolkits look up OAuth credentials by the explicit channel identity

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5061
**Assigned-to**: unassigned

---

## Context

Spec §2 "Principal (M1)", §6 "Additional review-fix edit sites", AC-13. Both toolkits' `_pre_execute` read
`perm_ctx.user_id` as the channel identity. On a Teams turn that is the Navigator id, so FEAT-773's resolver
(`(channel="msteams", id)` → principal) would look up the wrong id. Switch both OAuth resolver operations
(`resolve` and `get_auth_url`) to `credential_channel_user_id(perm_ctx)`. A Teams context without an AAD oid
yields `None` and therefore the existing "cannot resolve without a user_id" needs-auth branch — no resolver call.

---

## Scope

- `JiraToolkit._pre_execute` (non-local branch only): obtain `user_id` via `credential_channel_user_id(perm_ctx)`.
  The `_local_single_user` / CLI branch is untouched.
- `Office365Toolkit._pre_execute`: same change.
- Tests in `packages/ai-parrot-tools/tests/test_teams_oauth_identity.py` (`test_teams_oauth_identity_is_explicit`).

**NOT in scope**: the resolver (`OAuthCredentialResolver`), the Teams wrapper, token key changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | identity selection in `_pre_execute` |
| `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py` | MODIFY | identity selection in `_pre_execute` |
| `packages/ai-parrot-tools/tests/test_teams_oauth_identity.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import credential_channel_user_id   # created by TASK-5061
from parrot.auth.exceptions import AuthorizationRequired         # verified: jiratoolkit.py:62; o365/oauth_toolkit.py:23
from parrot.auth.principal import resolve_principal              # verified: jiratoolkit.py:63
from parrot.auth.permission import PermissionContext, UserSession   # verified: auth/permission.py:81, :21 (tests)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:          # :1319
        perm_ctx = kwargs.get("_permission_context")
        if self._local_single_user: ...  channel = "cli"; user_id = "local"     # keep as is
        else:
            ...
            user_id = getattr(perm_ctx, "user_id", None)                         # :1368  ← replace
            channel = getattr(perm_ctx, "channel", None) or "unknown"            # :1369
            if not user_id: raise AuthorizationRequired(... "Cannot resolve Jira credentials without a user_id." ...)
            principal = await resolve_principal(channel, str(user_id))
            ... self.credential_resolver.get_auth_url(channel, user_id) / .resolve(channel, user_id)

# packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py
    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:     # :102
        user_id = getattr(perm_ctx, "user_id", None)                             # :123  ← replace
        channel = getattr(perm_ctx, "channel", None) or "unknown"
        if not user_id: raise AuthorizationRequired(... "Cannot resolve Office365 credentials without a user_id." ...)
        token_set = await self.credential_resolver.resolve(channel, user_id)
        ... self.credential_resolver.get_auth_url(channel, user_id)
```

### Does NOT Exist
- ~~a numeric-id heuristic~~ (e.g. `user_id.isdigit()`) — forbidden (AC-13).
- ~~an AAD-keyed token fallback~~ — tokens stay keyed by the Navigator principal.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_teams_oauth_identity.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit._pre_execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py#Office365Toolkit._pre_execute"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the import to both modules next to the existing `AuthorizationRequired` import.
2. Replace the single `user_id = getattr(perm_ctx, "user_id", None)` line in each — *why*: one choke point
   feeds both `resolve` and `get_auth_url` below it.
3. Tests; Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# REPLACE `            user_id = getattr(perm_ctx, "user_id", None)` (verified: jiratoolkit.py:1368)
# occurrences: 1 (verified: grep -cxF '            user_id = getattr(perm_ctx, "user_id", None)' jiratoolkit.py)
            user_id = credential_channel_user_id(perm_ctx)
```
Import below `from parrot.auth.exceptions import AuthorizationRequired` (jiratoolkit.py:62):
`from parrot.auth.credentials import credential_channel_user_id`.

### `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py` (MODIFY)
```python
# REPLACE `        user_id = getattr(perm_ctx, "user_id", None)` (verified: o365/oauth_toolkit.py:123)
# occurrences: 1 (verified: grep -cxF '        user_id = getattr(perm_ctx, "user_id", None)' o365/oauth_toolkit.py)
        user_id = credential_channel_user_id(perm_ctx)
```
Import below `from parrot.auth.exceptions import AuthorizationRequired` (oauth_toolkit.py:23).
**Why**: non-Teams channels get `context.user_id` back from the helper, so their behavior is identical.

### `packages/ai-parrot-tools/tests/test_teams_oauth_identity.py` (CREATE)
```python
"""FEAT-775 AC-13: Teams OAuth lookup uses the AAD oid; PBAC keeps the Navigator id."""
import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import PermissionContext, UserSession


def _teams_ctx(channel_user_id):
    return PermissionContext(
        session=UserSession(user_id="42", tenant_id="t-1", roles=frozenset()),
        channel="msteams",
        channel_user_id=channel_user_id,
    )


@pytest.mark.asyncio
async def test_teams_oauth_identity_is_explicit(monkeypatch):
    # FILL IN: build each toolkit in OAuth mode with a recording fake credential_resolver (resolve/get_auth_url
    # record their (channel, user_id) args); patch jiratoolkit.resolve_principal to record its args.
    # Assert: lookup + URL creation receive "aad-1", never "42"; numeric-looking oid "12345" is passed through
    # verbatim as the channel id — bounded by AC-13
    ...


@pytest.mark.asyncio
async def test_teams_missing_oid_fails_closed():
    # FILL IN: channel_user_id=None → AuthorizationRequired and the fake resolver was never called — bounded by AC-13
    ...


@pytest.mark.asyncio
async def test_non_teams_and_local_cli_unchanged():
    # FILL IN: telegram ctx → resolver gets context.user_id; Jira local single-user branch still uses ("cli","local")
    ...
```

### FILL IN checklist
- [ ] Toolkit construction in OAuth mode for tests (read each `__init__` for the minimal kwargs)
- [ ] three test bodies

---

## Acceptance Criteria

- [ ] Teams lookup and URL creation use the AAD oid; missing oid → needs-auth with no resolver call (AC-13).
- [ ] Non-Teams channels and the Jira local CLI branch behave exactly as before.
- [ ] `ruff check` clean on touched files.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/test_teams_oauth_identity.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_teams_oauth_identity_is_explicit` | oid reaches resolver; Navigator id never does; no numeric inference |
| `test_teams_missing_oid_fails_closed` | needs-auth, resolver untouched |
| `test_non_teams_and_local_cli_unchanged` | regression guard |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

