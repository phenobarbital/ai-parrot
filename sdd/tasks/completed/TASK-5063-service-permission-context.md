# TASK-5063: Request-less PBAC on `IntegrationsService` (`permission_context` + URI-parity PDP evaluator)

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5061
**Assigned-to**: unassigned

---

## Context

Spec §2 "Service authorization bridge (M3/M7)", "Parity gate resolved (2026-10-31)", §3 Module 3, AC-14.
Channel commands have no aiohttp request; today `_check_pbac` returns `False` when `request is None`
(service.py:492), so Teams/Telegram can never list, connect or disconnect. FEAT-775 is the **sole owner** of the
fix; FEAT-776 TASK-5018 verifies and consumes exactly the signatures below.

**Cross-feature warning (2026-10-31).** FEAT-777 TASK-5038/5039 plan a competing `ConnectionAuthorizer` /
`IntegrationsService(authorizer=...)` on the same constructor and `_check_pbac`. The owner decided FEAT-775's
API is authoritative. Before starting, `git fetch origin && git grep -n "authorizer\|permission_evaluator"
origin/dev -- packages/ai-parrot/src/parrot/auth/oauth2/service.py`. If FEAT-777's `authorizer` already merged,
STOP and report — do not stack a second hook; the specs must be reconciled first.

**PDP mapping (decided, spec §2).** The HTTP path's `abac.is_allowed(request, ctx)` really performs URI
authorization on `request.path` (navigator-auth pdp.py:393-444). The request-less evaluator mirrors it:

| Operation | Resource (`ResourceType.URI`) | Action |
|---|---|---|
| `list_for_principal` (gate + per-provider filter) | `/api/v1/connections` | `uri:read` |
| `status` | `/api/v1/connections/{provider}` | `uri:read` |
| `start_connect` | `/api/v1/connections/{provider}/start` | `uri:write` |
| `disconnect` | `/api/v1/connections/{provider}` | `uri:delete` |

---

## Scope

- `IntegrationsService.__init__(self, vault_token_sync=None, *, permission_evaluator=None)`.
- Keyword-only `permission_context=None` on `list_for_principal`, `status`, `start_connect`, `disconnect`;
  add `principal=None` to list/status/disconnect and `channel=_WEB_CHANNEL` to disconnect.
- `_check_pbac(self, request, action, provider_id=None, scopes=None, *, principal=None, permission_context=None)`
  — positional compatibility preserved. With a context: evaluator required, never falls back to HTTP.
  Without a context: the existing HTTP path, byte-for-byte.
- `_context_matches(...)` identity guard: `context.user_id == user_id == principal.user_id`, tenant and
  `channel_user_id` agree, and (connect/disconnect) `context.channel == channel`. Mismatch → deny, before any
  state/revoke/credential mutation.
- Channel-aware revoke: `manager.revoke(channel=channel, user_id=principal.user_id, channel_user_id=principal.channel_user_id)`.
- Module-level `pdp_permission_evaluator(pdp)` returning the async callable
  `(context, attributes) -> bool` implementing the URI-parity table with `to_eval_context(context)` and
  `pdp.evaluator.check_access(...)`; allow only when `result.allowed is True`.
- Tests: `test_connections_permission_context.py` (unit, fake evaluator) **and** real-policy parity cases
  `test_teams_service_pbac_allow_and_deny`, `test_http_service_authorization_unchanged`.

**NOT in scope**: per-call scope propagation into the consent URL (TASK-5064), manager wiring of the evaluator
(TASK-5073), any Teams code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | context API, identity guard, evaluator adapter, channel-aware revoke |
| `packages/ai-parrot/tests/auth/test_connections_permission_context.py` | CREATE | unit + real-policy parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2 import _WEB_CHANNEL                       # verified: service.py:25
from parrot.auth.principal import Principal                       # verified: service.py:26
from parrot.auth.permission import PermissionContext, to_eval_context, UserSession   # verified: permission.py:81, :209, :21
from navigator_auth.abac.policies.resources import ResourceType   # verified: navigator_auth 0.28.9 resources.py:15 (URI = "uri")
# import navigator_auth lazily inside the adapter (pbac.py:136 pattern) — it is optional at import time.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class IntegrationsService:                                                       # :65
    def __init__(self, vault_token_sync: Any = None) -> None:                    # :77
    async def list_for_principal(self, user_id: str, request: Any = None) -> List[IntegrationDescriptor]   # :81
        #   :101 self._check_pbac(request, "integration:list"); :113 per provider with provider.provider_id
    async def start_connect(self, user_id, provider_id, return_origin=None, *, channel=_WEB_CHANNEL,
                            principal=None, scopes=None, request=None, extra_state=None) -> ConnectInitResponse  # :288
    async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor     # :360
    async def disconnect(self, user_id: str, provider_id: str, request: Any = None) -> DisconnectResponse    # :371
        #   :393 await provider.manager.revoke(channel=_WEB_CHANNEL, user_id=user_id)
    async def _check_pbac(self, request, action, provider_id=None, scopes=None) -> bool                      # :471
        #   :492 if request is None: return False ; :509 result = await abac.is_allowed(request, ctx)

# packages/ai-parrot/src/parrot/auth/oauth2_base.py
    async def revoke(self, channel: str, user_id: str, *, channel_user_id: Optional[str] = None) -> None    # :743

# navigator_auth 0.28.9
PDP.evaluator -> PolicyEvaluator                                                 # abac/pdp.py:97
PolicyEvaluator.check_access(ctx, resource_type, resource_name, action, env=None, ...) -> EvaluationResult  # policies/evaluator.py:410 (.allowed)
```

### Does NOT Exist
- ~~`IntegrationsService(permission_evaluator=...)`~~, ~~`permission_context=`~~ — added here.
- ~~`ResourceType.INTEGRATION`~~ — not in navigator-auth 0.28.9; use `ResourceType.URI`.
- ~~`parrot.auth.oauth2.channel_pbac`~~, ~~`check_integration_access`~~, ~~`permission_app`~~ — forbidden names.
- ~~an `app["permission_evaluator"]` key~~ — do not invent one (spec M7).
- ~~a fake aiohttp request~~ to reuse `abac.is_allowed` — forbidden (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_connections_permission_context.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService._check_pbac",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService.disconnect",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#to_eval_context",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2Manager.revoke"
  ]
}
```

---

## Implementation Notes

- Denial semantics: list → `[]`; status/connect/disconnect → `PermissionError`; unknown provider → `ValueError`.
- Fail closed when: context given but no evaluator; identity mismatch; evaluator raises; evaluator returns
  anything other than `True`. A context denial never falls back to the request.
- Roles/groups come only from the context's verified session (`to_eval_context` reads `session.roles` and
  `metadata["groups"]`); never add roles here.
- Attributes passed to the evaluator keep FEAT-773's shape: `{"action", "provider"?, "scopes"}` — `scopes` is
  present even when empty, plus `"operation"` naming the table row. The URI decision ignores provider/scopes.
- HTTP path: keep lines 492-516 unchanged when `permission_context is None` — `test_http_service_authorization_unchanged` pins it.

---

## Implementation Blueprint

### Steps (in order)
1. Cross-feature check (Context). 2. Constructor keyword. 3. Adapter + route table (module level). 4. Identity
guard. 5. Thread `principal` / `permission_context` through the four operations. 6. Split `_check_pbac`.
7. Channel-aware revoke. 8. Tests.

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY) — constructor
```python
# REPLACE `    def __init__(self, vault_token_sync: Any = None) -> None:` (verified: service.py:77)
# occurrences: 1 (verified: grep -cxF '    def __init__(self, vault_token_sync: Any = None) -> None:' service.py)
    def __init__(self, vault_token_sync: Any = None, *, permission_evaluator: Optional[PermissionEvaluator] = None) -> None:
        self._vault_token_sync = vault_token_sync
        self._identity_store_instance: Any = None
        self._permission_evaluator = permission_evaluator
```

### Same file — module level, BEFORE `class IntegrationsService:` (verified: service.py:65, occurrences: 1)
```python
#: ``async (context, attributes) -> bool`` — request-less PBAC decision for channel callers.
PermissionEvaluator = Callable[["PermissionContext", Mapping[str, Any]], Awaitable[bool]]

#: URI-parity mapping (spec §2 "Parity gate resolved"): operation → (route template, navigator-auth action).
_CONNECTION_ROUTES: Dict[str, Tuple[str, str]] = {
    "list": ("/api/v1/connections", "uri:read"),
    "list_provider": ("/api/v1/connections/{provider}", "uri:read"),
    "status": ("/api/v1/connections/{provider}", "uri:read"),
    "connect": ("/api/v1/connections/{provider}/start", "uri:write"),
    "disconnect": ("/api/v1/connections/{provider}", "uri:delete"),
}


def pdp_permission_evaluator(pdp: Any) -> PermissionEvaluator:
    """Adapt the app PDP (``app["abac"]``) to the request-less evaluator contract.

    Mirrors the HTTP decision exactly: ``ResourceType.URI`` on the operation's route with the method action.

    Args:
        pdp: The navigator-auth ``PDP`` initialized by ``setup_pbac``.

    Returns:
        An async callable that allows only on an explicit ``EvaluationResult.allowed is True``.
    """

    async def _evaluate(context: "PermissionContext", attributes: Mapping[str, Any]) -> bool:
        from navigator_auth.abac.policies.resources import ResourceType

        from parrot.auth.permission import to_eval_context

        route = _CONNECTION_ROUTES.get(str(attributes.get("operation", "")))
        if route is None:
            return False
        # FILL IN: format the template with attributes["provider"] (reject a missing provider for provider routes),
        # build ctx = to_eval_context(context), call pdp.evaluator.check_access(ctx, ResourceType.URI, path, action),
        # return result.allowed is True; any exception → log with logger.exception and return False — bounded by AC-14
        ...

    return _evaluate
```
Extend the `typing` import with `Awaitable, Callable, Mapping, Tuple`; add `PermissionContext` under the
existing `if TYPE_CHECKING:` block (service.py:28).

### Same file — identity guard + `_check_pbac` split
```python
# REPLACE the `_check_pbac` signature block (verified: service.py:471-477, `    async def _check_pbac(`, occurrences: 1)
    async def _check_pbac(
        self,
        request: Any,
        action: str,
        provider_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        *,
        principal: Optional[Principal] = None,
        permission_context: Optional["PermissionContext"] = None,
        operation: Optional[str] = None,
    ) -> bool:
        # (docstring: add the context branch)
        if permission_context is not None:
            return await self._check_context_pbac(permission_context, action, provider_id, scopes, operation)
        # ... existing body from `if request is None:` (service.py:492) unchanged ...

    async def _check_context_pbac(self, context, action, provider_id, scopes, operation) -> bool:
        """Evaluate the injected evaluator; fail closed on absence, error or non-True result."""
        if self._permission_evaluator is None:
            return False
        attributes: Dict[str, Any] = {"action": action, "scopes": list(scopes or []), "operation": operation}
        if provider_id:
            attributes["provider"] = provider_id
        # FILL IN: await the evaluator in try/except (log + False); return result is True — bounded by AC-14

    @staticmethod
    def _context_matches(user_id: str, principal: Optional[Principal], context: "PermissionContext",
                         channel: Optional[str] = None) -> bool:
        """True only when context, target and principal name the same Navigator user/tenant/channel identity."""
        # FILL IN: context.user_id == user_id; principal is None or principal.user_id == user_id;
        # principal.tenant_id (when set) == context.tenant_id; principal.channel_user_id (when set) ==
        # context.channel_user_id; channel is None or context.channel == channel — bounded by spec §2 "Every operation validates"
```
`operation` is keyword-only and optional, so FEAT-776's positional/keyword calls keep working.

### Same file — operations (each: identity guard first, then `_check_pbac(..., permission_context=, operation=)`)
```python
# list_for_principal(self, user_id, request=None, *, principal=None, permission_context=None)
#   context given and not _context_matches(...) → return []           # operation="list" / "list_provider"
# status(self, user_id, provider_id, request=None, *, principal=None, permission_context=None)   # operation="status"
# start_connect(..., extra_state=None, permission_context=None)                                   # operation="connect", channel checked
# disconnect(self, user_id, provider_id, request=None, *, channel=_WEB_CHANNEL, principal=None, permission_context=None)
#   operation="disconnect", channel checked; then:
# REPLACE `        await provider.manager.revoke(channel=_WEB_CHANNEL, user_id=user_id)` (verified: service.py:393, occurrences: 1)
        revoke_principal = principal or Principal(user_id=user_id, channel=channel, channel_user_id=user_id)
        await provider.manager.revoke(
            channel=channel,
            user_id=revoke_principal.user_id,
            channel_user_id=revoke_principal.channel_user_id,
        )
```
**Why**: the identity guard runs before any state/revoke/credential mutation (`test_service_context_target_mismatch_denied`);
a web call with no principal keeps today's `revoke(channel="web", user_id=user_id)` effect.

### `packages/ai-parrot/tests/auth/test_connections_permission_context.py` (CREATE)
```python
"""FEAT-775 M3: request-less PBAC on IntegrationsService (AC-14)."""
import pytest

from parrot.auth.oauth2.service import IntegrationsService, pdp_permission_evaluator
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal

# FILL IN fixtures: a registered fake provider in OAuth2ProviderRegistry (reset it after each test), a fake manager
# recording create_authorization_url/revoke, a recording fake evaluator (allow / deny / raise).

# test_service_requestless_pbac_fails_closed — missing evaluator, evaluator raises, evaluator returns a truthy
#   non-True object, no context and no request → all denied
# test_service_context_target_mismatch_denied — context.user_id != user_id, principal mismatch, tenant mismatch,
#   channel_user_id mismatch, channel mismatch → denied; no create_authorization_url / revoke / delete call
# test_disconnect_revokes_on_channel — channel="msteams", principal → revoke(channel="msteams", user_id=nav,
#   channel_user_id=oid)
# test_evaluator_attributes_shape — action/provider/scopes (empty list kept)/operation reach the evaluator
# test_teams_service_pbac_allow_and_deny — REAL navigator-auth PolicyEvaluator loaded from a tmp YAML policy
#   (follow setup_pbac's PolicyLoader steps, pbac.py:69-140) allowing uri:read on /api/v1/connections* for one
#   group and denying uri:delete; drive list/status/connect/disconnect through pdp_permission_evaluator with a
#   minimal object exposing `.evaluator` — no mocked check_access
# test_http_service_authorization_unchanged — request with app["abac"] fake → is_allowed(request, ctx) still called;
#   a context denial never consults the request
```

### FILL IN checklist
- [ ] adapter body (`check_access` call, explicit-allow rule)
- [ ] `_check_context_pbac` evaluator call
- [ ] `_context_matches` comparisons
- [ ] guard + operation wiring in the four methods
- [ ] all six tests (real-policy parity case must not mock `check_access`)

---

## Acceptance Criteria

- [ ] Signatures exactly as in Scope (FEAT-776 TASK-5018 "Expected Signatures AFTER FEAT-775").
- [ ] Missing evaluator / identity mismatch / evaluator error / non-True result → deny; no HTTP fallback (AC-14).
- [ ] Real-policy allow and deny pass through `pdp_permission_evaluator` with the URI-parity table (AC-14).
- [ ] Without a context, HTTP behavior and web-channel defaults are unchanged.
- [ ] Teams/Telegram disconnect revokes on the supplied channel with the principal's channel identity.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/auth/test_connections_permission_context.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py -q`

---

## Test Specification

See the test list in the test-file block; every name there must exist and pass.

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

Implemented by gpt-5.6-sol (codex), 1 attempt, merged via sdd-worker; engine fidelity gate passed; merge-tier validation green (chunk 1). 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

