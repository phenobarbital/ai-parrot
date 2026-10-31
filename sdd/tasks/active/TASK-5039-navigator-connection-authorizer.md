# TASK-5039: Server `NavigatorConnectionAuthorizer` over the navigator-auth PDP

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5038
**Assigned-to**: unassigned

---

## Context

Spec Module 2, "Request-independent authorization contract", and AC-14. TASK-5038 adds the core
`ConnectionAuthorizer` Protocol. This task implements it in the server against the installed
navigator-auth PDP (`app["abac"]`) without an HTTP request:

1. Reload the Navigator user from trusted auth storage (enabled user, groups/roles, tenant pair) — never from
   Slack text, `extra_state` or an HTTP body.
2. Re-verify the principal's current exclusive channel binding (`resolve_principal(channel, channel_user_id)`
   must return the same `user_id`; TASK-5037 makes that lookup fail closed on ambiguity).
3. Evaluate `integration:list|connect|disconnect` on resource `integration:<provider_id>` (`integration:*` for
   list) with `PolicyEvaluator.check_access`, using the tenant evaluator the PDP itself would select.
4. Grant only on an explicit ALLOW (`result.allowed is True and result.effect is PolicyEffect.ALLOW`).

App wiring (`app["connection_authorizer"]`) is done by TASK-5041 — not here.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/services/connection_authorization.py` with
  `class NavigatorConnectionAuthorizer` implementing `ConnectionAuthorizer.authorize`.
- Constructor: `__init__(self, app: Mapping[str, Any]) -> None` — reads `app["abac"]` (PDP) and
  `app["authdb"]` (auth DB pool) lazily at call time, so it can be built before startup finishes.
- Build a request-independent `EvalContext` by the existing bypass pattern in
  `parrot.auth.permission.to_eval_context` (permission.py:209-249), adding `org_id`, `client_id`, `channel`,
  `provider`, `scopes` to `ctx.store`.
- Tests against a REAL `PolicyEvaluator` (rs_pep is installed: verified `PolicyEvaluator()` constructs) with
  allowed and denied tenants, plus fail-closed cases.

**NOT in scope**: app wiring (TASK-5041); Slack commands (TASK-5044); the resolver's exclusive-owner lookup
(TASK-5037); changing navigator-auth or adding dependencies (spec: "no dependency change is authorized").

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/connection_authorization.py` | CREATE | PDP adapter |
| `packages/ai-parrot-server/tests/unit/test_connection_authorization.py` | CREATE | real-evaluator + fail-closed tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.authorization import ConnectionAuthorizer   # created by TASK-5038 (parrot/auth/oauth2/authorization.py)
from parrot.auth.principal import Principal, resolve_principal       # verified: auth/principal.py:18, :73
from parrot.auth.permission import PermissionContext, UserSession, to_eval_context  # verified: auth/permission.py:81, :21, :209
from navigator_auth.abac.policies.abstract import PolicyEffect       # verified: .venv navigator_auth/abac/policies/abstract.py:11
from navigator_auth.abac.policies.evaluator import PolicyEvaluator   # verified: .venv .../policies/evaluator.py:194
from navigator_auth.abac.policies.resource_policy import ResourcePolicy  # verified: .../resource_policy.py (ctor :27); used in packages/ai-parrot/tests/integration/test_pbac_guardrails_e2e.py:25
from navigator_auth.conf import ABAC_TENANT_SQL_FILTERING, AUTH_DB_SCHEMA, AUTH_USERS_VIEW  # verified: navigator_auth/conf.py:736, :33, :35
```

### Existing Signatures to Use
```python
# navigator_auth/abac/pdp.py (installed)
class PDP:                                                          # :68
    @property
    def evaluator(self) -> PolicyEvaluator: ...                      # :96-98 — the shared (global) evaluator
    async def _get_tenant_evaluator(self, org_id: int, client_id: int) -> PolicyEvaluator  # :156 — PRIVATE;
        # (1,1) → shared; on DB error FALLS BACK to the shared evaluator (:179-186) — see constraint below
    async def is_allowed(self, request, session=None, user=None, org_id=None, client_id=None, **kwargs)  # :549
        # selects: ABAC_TENANT_SQL_FILTERING → await self._get_tenant_evaluator(ctx.org_id, ctx.client_id) else self._evaluator (:592-596)
        # calls evaluator.check_access(ctx, rtype, rname, action, owner_reports_to=..., org_id=ctx.org_id, client_id=ctx.client_id) (:599-602)
        # custom resource types: "integration:jira" → rtype="integration" (str) when not a ResourceType member (:577-582)

# navigator_auth/abac/policies/evaluator.py
class EvaluationResult:   # :63 — allowed: bool; effect: PolicyEffect; matched_policy: Optional[str]; reason: str; __bool__ → allowed
class PolicyEvaluator:    # :194
    def __init__(self, cache_size: int = 1024, cache_ttl_seconds: int = 300)    # :218 (raises RuntimeError without rs_pep)
    def load_policies(self, policies: List[ResourcePolicy]) -> None             # :240
    def check_access(self, ctx: EvalContext, resource_type: ResourceType, resource_name: str, action: str,
                     env: Environment = None, owner_reports_to: str = None, org_id: int = 1, client_id: int = 1) -> EvaluationResult  # :410

# navigator_auth/abac/policies/abstract.py:11
class PolicyEffect(Enum): ALLOW = 1, 'allow'; DENY = 0, 'deny'

# navigator_auth/abac/policies/resource_policy.py:27
ResourcePolicy(name, effect=PolicyEffect.ALLOW, description=None, resources=None, actions=None,
               subjects=None, conditions=None, environment=None, priority=0, enforcing=False, org_id=1, client_id=1, **kwargs)  # :39-40

# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen) class UserSession: user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict  # :21-49
@dataclass class PermissionContext: session; request_id=None; channel=None; trace_context=None; extra=dict  # :81-106
def to_eval_context(context: PermissionContext) -> EvalContext   # :209 — EvalContext.__new__ bypass; store keys:
    # request=None, user=<user_id>, userinfo={username,user_id,tenant_id,groups,roles,programs}, session=None
    # (it does NOT set org_id/client_id — this task adds them to ctx.store and passes them to check_access)

# packages/ai-parrot/src/parrot/auth/resolver.py:322 — existing real check_access call to mirror:
#   result = self._evaluator.check_access(ctx=eval_ctx, resource_type=ResourceType.TOOL, resource_name=tool_name, action="tool:execute", env=env)

# Auth DB access idiom (navigator_auth/identity/store.py:105-133):
#   async with await pool.acquire() as conn: rows = await conn.fetch_all(sql, *params)
# Server pool: app["authdb"] (verified: packages/ai-parrot-server/src/parrot/manager/manager.py:2818, :2852)
# PDP on the app: app["abac"] (verified: handlers/agent.py:185, handlers/bots.py:58)
```

### Does NOT Exist
- ~~`ResourceType.INTEGRATION`~~ — `ResourceType` has tool/kb/vector/agent/mcp/uri/dataset/widget/card/slug/datasource/driver/raw_query only (resources.py:15-30); pass the string `"integration"` exactly as `PDP.is_allowed` does for custom types.
- ~~`EvalContext.from_userinfo()`~~ — not in navigator-auth (see the TODO in permission.py:243); use `to_eval_context`.
- ~~A public `PDP.get_tenant_evaluator`~~ — only the private `_get_tenant_evaluator` exists.
- ~~Any `integration:*` policy file in the repo~~ — none ships; `docs/auth/connections.md:80-93` shows a sample shape only.
- ~~`IdentityStore` user/group/tenant loader~~ — `IdentityStore` covers `user_identities` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/services/connection_authorization.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/unit/test_connection_authorization.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#to_eval_context",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#UserSession",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#resolve_principal",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#Principal"
  ]
}
```

---

## Implementation Notes

### Key Constraints (each is an AC-14 requirement)
- **Explicit ALLOW only**: `result.allowed is True and result.effect is PolicyEffect.ALLOW`. Never `bool(result)`.
- **Fail closed** on: no `app["abac"]`, no `app["authdb"]`, user missing or `is_active` false, binding re-check
  mismatch, missing tenant pair while `ABAC_TENANT_SQL_FILTERING` is true, any exception, DENY.
- **Tenant selection mirrors the PDP**: `ABAC_TENANT_SQL_FILTERING` → `await pdp._get_tenant_evaluator(org, client)`;
  else `pdp.evaluator`. Because `_get_tenant_evaluator` silently falls back to the shared evaluator on a DB error,
  and spec says "never evaluate only a global policy set when tenant SQL filtering is enabled": when filtering is on
  and `(org, client) != (1, 1)`, deny if the returned evaluator `is pdp.evaluator`. Document this in a comment.
- **Request-dependent attributes**: the context has `request=None`; a policy that reads request attributes simply
  does not match → default effect. Never fabricate a request object (spec).
- Private-API dependency (`_get_tenant_evaluator`) — add a module docstring note naming it and the installed
  navigator-auth version it was verified against (`uv pip show navigator-auth`).
- Use `self.logger = logging.getLogger(__name__)`; log decisions at debug, errors with `exception`, never log tokens.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/resolver.py:247-340` — real `check_access` usage and denial logging.
- `packages/ai-parrot/tests/integration/test_pbac_guardrails_e2e.py:79-90, :177-187` — building a real evaluator.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with `_load_trusted_user` (auth DB), `_binding_is_current`, `_select_evaluator`, `authorize` — *why*: each fail-closed reason isolated and testable.
2. Verify the `vw_users` columns you rely on BEFORE coding (`\d auth.vw_users` on a dev DB, or the navigator-auth `User` model fields `user_id`, `email`, `is_active` — models.py:39). If `org_id`/`client_id`/groups are not columns of the view, load them as the login backend does and record the choice in the Completion Note — *why*: the tenant pair must come from trusted storage (spec).
3. Write real-evaluator tests: one ALLOW policy for tenant (2, 5) on `integration:jira` / `integration:connect`, assert tenant (2, 5) allowed and tenant (3, 7) denied — *why*: AC-14 "Real-evaluator tests cover allowed and denied tenants".

### `packages/ai-parrot-server/src/parrot/services/connection_authorization.py` (CREATE)
```python
"""navigator-auth PDP adapter for request-independent connection operations (FEAT-777 M2, AC-14).

Implements :class:`parrot.auth.oauth2.authorization.ConnectionAuthorizer` for channels without an HTTP
request (Slack). Uses ``PDP._get_tenant_evaluator`` (private navigator-auth API; verified against the
installed navigator-auth) exactly as ``PDP.is_allowed`` selects evaluators.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from parrot.auth.permission import PermissionContext, UserSession, to_eval_context
from parrot.auth.principal import Principal, resolve_principal

_RESOURCE_TYPE = "integration"


class NavigatorConnectionAuthorizer:
    """Evaluate ``integration:*`` actions for a principal through the configured PDP."""

    def __init__(self, app: Mapping[str, Any]) -> None:
        self._app = app
        self.logger = logging.getLogger(__name__)

    async def authorize(self, principal: Principal, action: str, provider_id: Optional[str], scopes: List[str]) -> bool:
        """Return ``True`` only for an explicit ALLOW; every other outcome denies."""
        try:
            pdp = self._app.get("abac")
            if pdp is None:
                self.logger.debug("No PDP configured — denying %s", action)
                return False
            user = await self._load_trusted_user(principal.user_id)
            if user is None:
                return False
            if not await self._binding_is_current(principal):
                return False
            org_id, client_id = self._tenant_pair(user)
            evaluator = await self._select_evaluator(pdp, org_id, client_id)
            if evaluator is None:
                return False
            ctx = self._eval_context(principal, user, org_id, client_id, provider_id, scopes)
            resource_name = provider_id or "*"
            result = evaluator.check_access(
                ctx, _RESOURCE_TYPE, resource_name, action, org_id=org_id, client_id=client_id
            )
            return self._is_explicit_allow(result)
        except Exception:  # noqa: BLE001 — evaluator/storage errors fail closed
            self.logger.exception("Connection authorization failed for action=%s provider=%s", action, provider_id)
            return False

    async def _load_trusted_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Enabled user + groups/roles + tenant pair from the auth DB, or ``None``."""
        pool = self._app.get("authdb")
        if pool is None or not str(user_id).isdigit():
            return None
        # FILL IN: query {AUTH_DB_SCHEMA}.{AUTH_USERS_VIEW} (navigator_auth.conf) by user_id with
        # `async with await pool.acquire() as conn: await conn.fetch_all(sql, int(user_id))`; return None unless
        # exactly one row with is_active true; collect group names (auth.user_groups ⋈ auth.groups, is_active) —
        # bounded by spec M2 "reloads enabled Navigator user, roles and tenant membership from trusted auth storage"
        raise NotImplementedError

    async def _binding_is_current(self, principal: Principal) -> bool:
        """Non-web principals must still resolve to the same Navigator user (exclusive binding)."""
        if principal.channel == "web":
            return True
        current = await resolve_principal(principal.channel, principal.channel_user_id)
        return current is not None and str(current.user_id) == str(principal.user_id)

    @staticmethod
    def _tenant_pair(user: Mapping[str, Any]) -> tuple[Optional[int], Optional[int]]:
        # FILL IN: return (int(org_id), int(client_id)) from the trusted row, (None, None) when absent —
        # bounded by "Missing identity/PDP/tenant context ... fail closed"
        raise NotImplementedError

    async def _select_evaluator(self, pdp: Any, org_id: Optional[int], client_id: Optional[int]) -> Any:
        """Mirror PDP.is_allowed's evaluator choice; deny rather than silently use only global policies."""
        from navigator_auth.conf import ABAC_TENANT_SQL_FILTERING

        if not ABAC_TENANT_SQL_FILTERING:
            return pdp.evaluator
        if org_id is None or client_id is None:
            return None
        evaluator = await pdp._get_tenant_evaluator(org_id, client_id)  # noqa: SLF001 — mirrors PDP.is_allowed
        if (org_id, client_id) != (1, 1) and evaluator is pdp.evaluator:
            self.logger.warning("Tenant evaluator unavailable for (%s, %s) — denying", org_id, client_id)
            return None
        return evaluator

    def _eval_context(self, principal: Principal, user: Mapping[str, Any], org_id: Any, client_id: Any,
                      provider_id: Optional[str], scopes: List[str]) -> Any:
        session = UserSession(
            user_id=str(principal.user_id),
            tenant_id=str(principal.tenant_id or ""),
            roles=frozenset(user.get("roles") or ()),
            metadata={"groups": list(user.get("groups") or ())},
        )
        ctx = to_eval_context(PermissionContext(session=session, channel=principal.channel))
        ctx.store.update(
            {"org_id": org_id, "client_id": client_id, "channel": principal.channel,
             "provider": provider_id, "scopes": list(scopes)}
        )
        # FILL IN: confirm ctx.store["userinfo"] also carries org_id/client_id and the trusted e-mail
        # if your policies use them; keep ctx._columns in sync (list(ctx.store.keys())) — bounded by spec M2
        return ctx

    @staticmethod
    def _is_explicit_allow(result: Any) -> bool:
        from navigator_auth.abac.policies.abstract import PolicyEffect

        return getattr(result, "allowed", None) is True and getattr(result, "effect", None) is PolicyEffect.ALLOW
```
**Why this shape**: every AC-14 fail-closed reason is a separate early `False`; the evaluator choice mirrors
`PDP.is_allowed` (pdp.py:592-602) so web and Slack decisions use the same policy set.

### `packages/ai-parrot-server/tests/unit/test_connection_authorization.py` (CREATE)
```python
"""NavigatorConnectionAuthorizer against a real PolicyEvaluator (FEAT-777 AC-14)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from navigator_auth.abac.policies.abstract import PolicyEffect
from navigator_auth.abac.policies.evaluator import PolicyEvaluator
from navigator_auth.abac.policies.resource_policy import ResourcePolicy
from parrot.auth.principal import Principal
from parrot.services.connection_authorization import NavigatorConnectionAuthorizer


class FakePDP:
    """Holds a shared evaluator plus per-tenant evaluators, like PDP."""

    def __init__(self, shared: PolicyEvaluator, tenants: Dict[tuple, PolicyEvaluator]) -> None:
        self.evaluator = shared
        self._tenants = tenants

    async def _get_tenant_evaluator(self, org_id: int, client_id: int) -> PolicyEvaluator:
        return self._tenants.get((org_id, client_id), self.evaluator)


@pytest.fixture
def principal() -> Principal:
    return Principal(user_id="1042", channel="slack", channel_user_id="T01:U02")


def _allow_connect(org_id: int, client_id: int) -> PolicyEvaluator:
    evaluator = PolicyEvaluator(cache_size=8, cache_ttl_seconds=1)
    # FILL IN: ResourcePolicy(name=..., effect=PolicyEffect.ALLOW, resources=["integration:jira"],
    # actions=["integration:connect"], subjects={"groups": ["*"]}, org_id=org_id, client_id=client_id)
    # — ResourcePolicy accepts org_id=/client_id= (verified resource_policy.py:39-40) — bounded by AC-14
    return evaluator


async def test_allowed_tenant(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: monkeypatch _load_trusted_user → {"user_id": 1042, "is_active": True, "org_id": 2, "client_id": 5,
    # "groups": ["staff"]}, _binding_is_current → True, ABAC_TENANT_SQL_FILTERING → True;
    # app={"abac": FakePDP(PolicyEvaluator(), {(2, 5): _allow_connect(2, 5)}), "authdb": object()};
    # assert await authorize(principal, "integration:connect", "jira", ["read:jira-work"]) is True
    ...


async def test_denied_other_tenant(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: same policy, trusted user in tenant (3, 7) → False (shared-evaluator fallback also denies)
    ...


@pytest.mark.parametrize("case", ["no_pdp", "no_user", "inactive", "stale_binding", "no_tenant", "error", "deny"])
async def test_fail_closed(case: str, principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: one setup per case; every case returns False and never raises — bounded by AC-14
    ...


def test_truthy_result_object_is_not_allow() -> None:
    class Truthy:
        allowed = 1
        effect = PolicyEffect.ALLOW

    assert NavigatorConnectionAuthorizer._is_explicit_allow(Truthy()) is False
```

### FILL IN checklist
- [ ] `_load_trusted_user` — trusted SQL (user, active, groups, tenant); spec M2.
- [ ] `_tenant_pair` — from trusted row only; AC-14.
- [ ] `_eval_context` — userinfo keys policies need; spec M2.
- [ ] `_allow_connect` — real `ResourcePolicy` with tenant scoping; AC-14.
- [ ] `test_allowed_tenant`, `test_denied_other_tenant`, `test_fail_closed` bodies.

---

## Acceptance Criteria

- [ ] Real `PolicyEvaluator` test: allowed tenant → `True`, other tenant → `False` (AC-14).
- [ ] Missing PDP, missing/disabled user, stale binding, missing tenant (with SQL filtering), evaluator errors and DENY → `False`, no exception.
- [ ] A truthy non-ALLOW result never grants.
- [ ] No navigator-auth or dependency change; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_connection_authorization.py -q`

---

## Test Specification

See the CREATE block for `test_connection_authorization.py` above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (Module 2, "Request-independent authorization contract"; AC-14)
3. **Check dependencies** — TASK-5038 must be `"done"`
4. **Verify the Codebase Contract** against the installed navigator-auth (`.venv/lib/python3.12/site-packages/navigator_auth/abac/`)
5. **Update status** → `"in-progress"`; commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit** only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5039 connections-web-slack verified`
10. **Completion Note** — record the trusted-user SQL source you chose and the navigator-auth version

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
