# TASK-5064: Per-call OAuth scope propagation (`create_authorization_url(..., scopes=)`)

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5063
**Assigned-to**: unassigned

---

## Context

Spec §2 "Wire-level prerequisite", AC-15. `IntegrationsService.start_connect` computes `requested_scopes`
(service.py:340) for PBAC and the response, but `create_authorization_url` (service.py:347) receives no scopes
and `AbstractOAuth2Manager.create_authorization_url` always sends the manager-level `self.scopes`
(oauth2_base.py:435). A response reporting requested scopes is therefore not proof that consent requested them.
The contract (spec §2): a **keyword-only per-call scope list**, a **request-local copy**, **precedence over
provider URL extra params**, and **unchanged default behavior when omitted**. Never mutate `self.scopes`
(the manager is shared across concurrent requests). Jira, O365 and `StandardOAuth2Manager` inherit the base
method (no overrides — verified: only `authorization_url_extra_params` is overridden, o365_oauth.py:104,
descriptor.py:175), so one edit covers all three.

Depends on TASK-5063 only because both edit `service.py` (serialize).

---

## Scope

- `AbstractOAuth2Manager.create_authorization_url(self, channel, user_id, extra_state=None, *, principal=None, scopes=None)`:
  `scope` param = `" ".join(list(scopes))` when `scopes` is not `None`, else `self.scopes`; applied **after**
  `params.update(extra_params)` so it wins over any provider `scope` extra param; record the requested scopes in
  the nonce state payload (`"requested_scopes"`).
- `IntegrationsService.start_connect`: pass `scopes=requested_scopes` to the manager call.
- Tests: concurrent-request scope isolation, default unchanged, precedence over extra params, service passes scopes.

**NOT in scope**: the callback's granted-scope handling, Teams code, FEAT-777 device-code changes to `oauth2_base.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | keyword-only `scopes` on `create_authorization_url` |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | pass `scopes=requested_scopes` |
| `packages/ai-parrot/tests/auth/test_oauth2_scope_propagation.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2_base import AbstractOAuth2Manager   # verified: oauth2_base.py (class owning create_authorization_url :398)
from parrot.auth.principal import Principal                 # verified: principal.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2_base.py
        self.scopes: List[str] = list(scopes) if scopes else list(self.default_scopes)   # :261
    async def create_authorization_url(                                               # :398
        self, channel: str, user_id: str, extra_state: Optional[Dict[str, Any]] = None, *,
        principal: Optional[Principal] = None,
    ) -> Tuple[str, str]:
        #   state_payload = {"channel", "user_id", "extra", "nav_user_id", "channel_user_id", "canonical_identity", "tenant_id"}
            "scope": " ".join(self.scopes),                                           # :435
        extra_params = self.authorization_url_extra_params()                          # :444
        if extra_params:
            params.update(extra_params)
    def authorization_url_extra_params(self) -> Dict[str, str]                        # :458

# packages/ai-parrot/src/parrot/auth/oauth2/service.py (start_connect)
        requested_scopes = list(scopes or provider.default_scopes)                    # :340
        auth_url, nonce = await provider.manager.create_authorization_url(            # :347
            channel=channel, user_id=user_id, extra_state=state, principal=principal,
        )
```

### Does NOT Exist
- ~~a `create_authorization_url` override in `JiraOAuthManager` / `O365OAuthManager` / `StandardOAuth2Manager`~~.
- ~~`self.scopes` reassignment per request~~ — forbidden (shared manager).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2_base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_oauth2_scope_propagation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.create_authorization_url",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.start_connect"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the keyword to the signature and docstring.
2. Compute a request-local `scope_list` and use it for `params["scope"]`; re-apply after extra params.
3. Store `requested_scopes` in `state_payload`.
4. Pass `scopes=requested_scopes` from the service. 5. Tests.

### `packages/ai-parrot/src/parrot/auth/oauth2_base.py` (MODIFY)
```python
# signature — after `        principal: Optional[Principal] = None,` inside create_authorization_url (verified: oauth2_base.py:404)
# occurrences: 1 (verified: grep -cxF '        principal: Optional[Principal] = None,' oauth2_base.py)
        scopes: Optional[List[str]] = None,

# body — REPLACE `            "scope": " ".join(self.scopes),` (verified: oauth2_base.py:435, occurrences: 1)
            "scope": " ".join(scope_list),
# and define, just above `        params: Dict[str, str] = {`:
        scope_list: List[str] = list(scopes) if scopes is not None else list(self.scopes)
        state_payload["requested_scopes"] = list(scope_list)

# AFTER the block `        if extra_params:` / `            params.update(extra_params)` (verified: :444-446, `        extra_params = self.authorization_url_extra_params()` occurrences: 1)
        if scopes is not None:
            # Per-call scopes win over any provider extra param (spec §2 scope contract).
            params["scope"] = " ".join(scope_list)
```
**Why**: `scope_list` is a fresh list per call, so concurrent calls cannot see each other's scopes; omitting the
keyword reproduces the old URL exactly.

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY)
```python
# inside the call opened by `        auth_url, nonce = await provider.manager.create_authorization_url(` (verified: service.py:347, occurrences: 1)
            principal=principal,
            scopes=requested_scopes,
```

### `packages/ai-parrot/tests/auth/test_oauth2_scope_propagation.py` (CREATE)
```python
"""FEAT-775 AC-15: per-call scopes reach the provider consent URL."""
import asyncio
from urllib.parse import parse_qs, urlparse

import pytest

from parrot.auth.principal import Principal

# FILL IN fixture: a minimal concrete AbstractOAuth2Manager subclass (or StandardOAuth2Manager from a test descriptor)
#   with an in-memory fake redis exposing async set/get, client_id, redirect_uri, authorization_url, scopes=["a"].

# test_default_scopes_unchanged — no keyword → scope == manager scopes; state has requested_scopes == ["a"]
# test_per_call_scopes_override_and_win_over_extra_params — extra param {"scope": "x"} + scopes=["b","c"] → "b c"
# test_concurrent_requests_isolated — asyncio.gather two calls with different scopes → each URL has its own; self.scopes unchanged
# test_service_start_connect_passes_requested_scopes — fake manager records the scopes kwarg == requested_scopes
```

### FILL IN checklist
- [ ] four tests

---

## Acceptance Criteria

- [ ] Per-call scopes reach the URL; default behavior unchanged; per-call wins over extra params (AC-15).
- [ ] Concurrent calls isolated; `self.scopes` never mutated.
- [ ] `start_connect` passes `requested_scopes`.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_oauth2_scope_propagation.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py -q`

---

## Test Specification

Four tests listed in the test-file block.

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

Implemented by gpt-5.6-terra (codex), 1 attempt, merged via sdd-worker; engine fidelity gate passed; merge-tier validation green (chunk 2). 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

