"""One place where a SaaS route asks the policy engine for a decision.

Authorization in this repository is **explicit and in the handler**:
``abac_middleware`` authorizes nothing on its own, so a route that does not
call the policy decision point is simply not authorized. This module is that
call, shared by every SaaS view so the posture is stated once rather than
copied.

``ResourceType`` is a closed enum with no member for these resources, so the
policies use a custom string type (``saas:secrets``, ``saas:reviews``) — a case
``ResourcePolicy.covers_resource`` supports explicitly.
"""
from __future__ import annotations

from typing import Optional

from aiohttp import web
from navconfig.logging import logging

logger = logging.getLogger("parrot_saas.handlers.authz")

#: Resource type every SaaS policy is written against.
PBAC_RESOURCE_TYPE = "saas"


def _json_error(status: int, code: str, message: str) -> web.Response:
    """Build a JSON error response.

    Defined here rather than imported so this module has no dependency on the
    view modules that import it.
    """
    return web.json_response({"error": code, "message": message}, status=status)


async def check_policy(
    request: web.Request,
    action: str,
    resource_name: str,
    *,
    subject: str = "",
) -> Optional[web.Response]:
    """Ask the policy engine whether this request may perform ``action``.

    Enforced whenever a policy decision point is configured. When none is —
    ``setup_pbac`` returns nothing at all if its policy directory is missing —
    this logs and allows, matching the convention used by the agent handlers.
    That is defensible here specifically because authorization is not the
    isolation boundary: without a PDP the degradation is "any authenticated
    user of this tenant" rather than "only its admin", never access to another
    tenant, whose separation the resolution middleware enforces independently.

    A failed *evaluation*, on the other hand, denies. An evaluator that raises
    must not become an open door.

    Args:
        request: The in-flight request.
        action: Policy action, e.g. ``"saas:review:simulate"``.
        resource_name: Policy resource under the ``saas`` type, e.g.
            ``"reviews"``.
        subject: Optional identifier used only in the denial log line.

    Returns:
        ``None`` when allowed, or a 403 response.
    """
    pdp = request.app.get("abac")
    evaluator = getattr(pdp, "_evaluator", None) if pdp is not None else None
    if evaluator is None:
        logger.warning(
            "no PBAC policy engine configured; serving %s without an "
            "authorization decision",
            action,
        )
        return None

    try:
        from navigator_auth.abac.context import EvalContext
        from navigator_auth.abac.policies.environment import Environment

        session = request.get("session") or {}
        try:
            from navigator_auth.conf import AUTH_SESSION_OBJECT

            userinfo = session.get(AUTH_SESSION_OBJECT, {}) or {}
        except ImportError:  # pragma: no cover - navigator-auth optional
            userinfo = {}
        result = evaluator.check_access(
            ctx=EvalContext(
                request,
                user=request.get("user"),
                userinfo=userinfo,
                session=session,
            ),
            resource_type=PBAC_RESOURCE_TYPE,
            resource_name=resource_name,
            action=action,
            env=Environment(),
        )
    except Exception as exc:  # noqa: BLE001 - denied, never swallowed
        logger.error("PBAC evaluation failed for %s: %s", action, exc)
        return _json_error(
            403, "forbidden", "the authorization decision could not be made"
        )

    if not result.allowed:
        logger.warning(
            "PBAC denied %s on %s for %s (policy=%s)",
            action,
            resource_name,
            subject or "an unnamed subject",
            getattr(result, "matched_policy", None),
        )
        return _json_error(
            403,
            "forbidden",
            getattr(result, "reason", None) or f"{action} is not permitted",
        )
    return None


__all__ = ("PBAC_RESOURCE_TYPE", "check_policy")
