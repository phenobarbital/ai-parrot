"""navigator-auth PDP adapter for request-independent connection operations (FEAT-777 M2, AC-14).

Implements :class:`parrot.auth.oauth2.authorization.ConnectionAuthorizer` for channels without an HTTP
request (Slack). Uses ``PDP._get_tenant_evaluator`` (private navigator-auth 0.28.9 API) exactly as
``PDP.is_allowed`` selects evaluators.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from parrot.auth.oauth2.authorization import ConnectionAuthorizer
from parrot.auth.permission import PermissionContext, UserSession, to_eval_context
from parrot.auth.principal import Principal, resolve_principal

_RESOURCE_TYPE = "integration"

_TRUSTED_USER_SQL = """
SELECT
    u.user_id,
    u.email,
    u.is_active,
    u.user_role,
    COALESCE(
        array_agg(DISTINCT g.group_name) FILTER (WHERE g.group_name IS NOT NULL),
        ARRAY[]::text[]
    ) AS groups,
    COALESCE(
        jsonb_agg(DISTINCT jsonb_build_object('org_id', ou.org_id, 'client_id', oc.client_id))
            FILTER (WHERE ou.org_id IS NOT NULL AND oc.client_id IS NOT NULL),
        '[]'::jsonb
    ) AS tenant_pairs
FROM {schema}.{users_view} u
LEFT JOIN {schema}.user_groups ug ON ug.user_id = u.user_id
LEFT JOIN {schema}.groups g ON g.group_id = ug.group_id AND g.is_active IS TRUE
LEFT JOIN {schema}.organization_users ou ON ou.user_id = u.user_id
LEFT JOIN {schema}.organization_clients oc ON oc.org_id = ou.org_id
WHERE u.user_id = $1
GROUP BY u.user_id, u.email, u.is_active, u.user_role
"""


class NavigatorConnectionAuthorizer(ConnectionAuthorizer):
    """Evaluate ``integration:*`` actions for a principal through the configured PDP."""

    def __init__(self, app: Mapping[str, Any]) -> None:
        """Store the app mapping without resolving startup-time resources."""
        self._app = app
        self.logger = logging.getLogger(__name__)

    async def authorize(
        self,
        principal: Principal,
        action: str,
        provider_id: Optional[str],
        scopes: List[str],
    ) -> bool:
        """Return ``True`` only for an explicit ALLOW; every other outcome denies."""
        try:
            pdp = self._app.get("abac")
            if pdp is None:
                self.logger.debug("No PDP configured; denying action=%s", action)
                return False
            user = await self._load_trusted_user(principal.user_id)
            if user is None or user.get("is_active") is not True:
                return False
            if not await self._binding_is_current(principal):
                return False
            org_id, client_id = self._tenant_pair(user)
            evaluator = await self._select_evaluator(pdp, org_id, client_id)
            if evaluator is None:
                return False
            ctx = self._eval_context(principal, user, org_id, client_id, provider_id, scopes)
            result = evaluator.check_access(
                ctx,
                _RESOURCE_TYPE,
                provider_id or "*",
                action,
                org_id=org_id,
                client_id=client_id,
            )
            allowed = self._is_explicit_allow(result)
            self.logger.debug("Connection authorization action=%s provider=%s allowed=%s", action, provider_id, allowed)
            return allowed
        except Exception:  # noqa: BLE001 - storage and evaluator failures must fail closed
            self.logger.exception("Connection authorization failed for action=%s provider=%s", action, provider_id)
            return False

    async def _load_trusted_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load one enabled user, groups, roles, and one tenant pair from auth storage."""
        from navigator_auth.conf import AUTH_DB_SCHEMA, AUTH_USERS_VIEW

        pool = self._app.get("authdb")
        if pool is None or not str(user_id).isdigit():
            return None
        sql = _TRUSTED_USER_SQL.format(schema=AUTH_DB_SCHEMA, users_view=AUTH_USERS_VIEW)
        async with await pool.acquire() as conn:
            rows = await conn.fetch_all(sql, int(user_id))
        if len(rows) != 1:
            return None
        row = dict(rows[0])
        if row.get("is_active") is not True:
            return None
        pairs = row.pop("tenant_pairs", []) or []
        if len(pairs) == 1:
            row.update(pairs[0])
        else:
            row["org_id"] = None
            row["client_id"] = None
        role = row.get("user_role")
        row["roles"] = [str(role)] if role else []
        return row

    async def _binding_is_current(self, principal: Principal) -> bool:
        """Require non-web principals to retain their exclusive Navigator binding."""
        if principal.channel == "web":
            return True
        current = await resolve_principal(principal.channel, principal.channel_user_id)
        return current is not None and str(current.user_id) == str(principal.user_id)

    @staticmethod
    def _tenant_pair(user: Mapping[str, Any]) -> tuple[Optional[int], Optional[int]]:
        """Return the trusted tenant pair, or ``(None, None)`` when invalid."""
        try:
            return int(user["org_id"]), int(user["client_id"])
        except (KeyError, TypeError, ValueError):
            return None, None

    async def _select_evaluator(self, pdp: Any, org_id: Optional[int], client_id: Optional[int]) -> Any:
        """Mirror PDP selection while refusing its tenant-error global fallback."""
        from navigator_auth.conf import ABAC_TENANT_SQL_FILTERING

        if not ABAC_TENANT_SQL_FILTERING:
            return pdp.evaluator
        if org_id is None or client_id is None:
            return None
        evaluator = await pdp._get_tenant_evaluator(org_id, client_id)  # noqa: SLF001 - mirrors PDP.is_allowed
        # navigator-auth falls back to the global evaluator on tenant DB errors; AC-14 requires denial instead.
        if (org_id, client_id) != (1, 1) and evaluator is pdp.evaluator:
            self.logger.warning("Tenant evaluator unavailable for (%s, %s); denying", org_id, client_id)
            return None
        return evaluator

    def _eval_context(
        self,
        principal: Principal,
        user: Mapping[str, Any],
        org_id: Optional[int],
        client_id: Optional[int],
        provider_id: Optional[str],
        scopes: List[str],
    ) -> Any:
        """Build the PDP context without fabricating an HTTP request."""
        session = UserSession(
            user_id=str(principal.user_id),
            tenant_id=str(principal.tenant_id or ""),
            roles=frozenset(user.get("roles") or ()),
            metadata={"groups": list(user.get("groups") or ())},
        )
        ctx = to_eval_context(PermissionContext(session=session, channel=principal.channel))
        ctx.store["userinfo"].update({"email": user.get("email"), "org_id": org_id, "client_id": client_id})
        ctx.store.update(
            {
                "org_id": org_id,
                "client_id": client_id,
                "channel": principal.channel,
                "provider": provider_id,
                "scopes": list(scopes),
            }
        )
        ctx._columns = list(ctx.store.keys())
        return ctx

    @staticmethod
    def _is_explicit_allow(result: Any) -> bool:
        """Accept only the evaluator's literal ALLOW result."""
        from navigator_auth.abac.policies.abstract import PolicyEffect

        return getattr(result, "allowed", None) is True and getattr(result, "effect", None) is PolicyEffect.ALLOW
