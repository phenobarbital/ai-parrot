"""Agent-level PBAC guard for bot resolution.

This module provides the building blocks for enforcing PBAC policies at the
bot-resolution entry points (``BotManager.get_bot`` and
``AgentRegistry.get_instance``).

Public API:
    - ``AgentAccessDenied``: Exception raised when a caller is denied resolution.
    - ``parse_bot_permissions``: Validate and parse the JSONB shape stored in
      ``navigator.ai_bots.permissions``.
    - ``enforce_agent_access``: Async helper that raises ``AgentAccessDenied``
      when the evaluator denies access.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiohttp import web

from parrot.auth.models import PolicyRuleConfig

logger = logging.getLogger("parrot.auth.agent_guard")


class AgentAccessDenied(PermissionError):
    """Raised by ``enforce_agent_access`` when PBAC denies bot resolution.

    Attributes:
        bot_name: Name of the bot that was denied.
        user_id: User/subject identifier extracted from the request session.
        matched_policy: Name of the policy rule that triggered the denial
            (may be ``None`` if the evaluator did not report one).
        reason: Human-readable denial reason from the evaluator (may be ``None``).

    Example::

        try:
            await enforce_agent_access(evaluator, "finance_bot", request)
        except AgentAccessDenied as exc:
            # 403 response
            return web.Response(status=403, text=str(exc))
    """

    def __init__(
        self,
        bot_name: str,
        user_id: Optional[str] = None,
        matched_policy: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Initialize ``AgentAccessDenied``.

        Args:
            bot_name: Name of the bot whose resolution was denied.
            user_id: Subject identifier from the request session.
            matched_policy: Policy name that triggered the denial, if any.
            reason: Human-readable denial reason, if any.
        """
        self.bot_name = bot_name
        self.user_id = user_id
        self.matched_policy = matched_policy
        self.reason = reason
        msg = (
            f"Access denied to bot '{bot_name}'"
            + (f" for user '{user_id}'" if user_id else "")
            + (f": {reason}" if reason else "")
        )
        super().__init__(msg)


def parse_bot_permissions(
    value: dict | list | None,
) -> list[PolicyRuleConfig]:
    """Validate and parse the JSONB shape stored in ``ai_bots.permissions``.

    Accepted shapes (all treated as **public** — any authenticated user allowed):
      - ``None``
      - ``{}``
      - ``{"permissions": []}``

    Accepted shape (deny-by-default with explicit rules):
      - ``{"permissions": [<PolicyRuleConfig dict>, ...]}``

    Forgiving fallback (bare list coerced to canonical shape):
      - ``[<rule dict>, ...]``

    Any other shape raises ``ValueError`` so that malformed rows fail loudly
    at load time rather than being silently treated as public.

    Args:
        value: Raw value read from ``navigator.ai_bots.permissions``.

    Returns:
        List of ``PolicyRuleConfig`` instances. Empty list means public.

    Raises:
        ValueError: When ``value`` has an unrecognised shape or contains
            invalid rule dicts (e.g., missing required ``action`` field).

    Examples::

        >>> parse_bot_permissions(None)
        []
        >>> parse_bot_permissions({})
        []
        >>> parse_bot_permissions({"permissions": []})
        []
        >>> rules = parse_bot_permissions(
        ...     {"permissions": [{"action": "agent:resolve", "effect": "allow",
        ...                       "groups": ["engineering"]}]}
        ... )
        >>> len(rules)
        1
    """
    # None / empty dict → public
    if value is None:
        return []
    if isinstance(value, dict):
        if not value:
            # {} → public
            return []
        if "permissions" not in value:
            raise ValueError(
                f"Invalid bot permissions shape: dict must have 'permissions' key, "
                f"got keys {list(value.keys())!r}"
            )
        rules_raw = value["permissions"]
        if not isinstance(rules_raw, list):
            raise ValueError(
                f"Invalid bot permissions shape: 'permissions' must be a list, "
                f"got {type(rules_raw).__name__!r}"
            )
    elif isinstance(value, list):
        # Forgiving bare-list fallback
        rules_raw = value
    else:
        raise ValueError(
            f"Invalid bot permissions shape: expected dict or list, "
            f"got {type(value).__name__!r}"
        )

    if not rules_raw:
        return []

    parsed: list[PolicyRuleConfig] = []
    for idx, rule_data in enumerate(rules_raw):
        if not isinstance(rule_data, dict):
            raise ValueError(
                f"Invalid rule at index {idx}: expected dict, "
                f"got {type(rule_data).__name__!r}"
            )
        try:
            parsed.append(PolicyRuleConfig(**rule_data))
        except Exception as exc:
            raise ValueError(
                f"Invalid rule at index {idx} for bot permissions: {exc}"
            ) from exc

    return parsed


async def _build_eval_context_from_request(request: web.Request) -> object:
    """Build a navigator-auth ``EvalContext`` from an aiohttp request.

    Reads the authenticated session from ``request.session`` (populated by
    Guardian middleware) and constructs a minimal ``EvalContext`` suitable
    for ``PolicyEvaluator.check_access()``.

    This mirrors the pattern in ``parrot/handlers/bots.py:_build_eval_context``.

    Args:
        request: The incoming aiohttp request with a Guardian-populated session.

    Returns:
        An ``EvalContext`` instance, or ``None`` if the session is unavailable.

    Raises:
        ImportError: If navigator-auth is not installed (caller handles this).
    """
    from navigator_auth.abac.context import EvalContext  # noqa: PLC0415
    try:
        from navigator_auth.conf import AUTH_SESSION_OBJECT as _AUTH_SESSION  # noqa: PLC0415
    except ImportError:
        _AUTH_SESSION = "userinfo"

    session = getattr(request, "session", None)
    if session is None:
        try:
            from navigator_session import get_session  # noqa: PLC0415
            session = await get_session(request)
        except Exception:  # pylint: disable=broad-except
            return None

    userinfo = session.get(_AUTH_SESSION, {}) if session else {}
    return EvalContext(
        username=userinfo.get("username", ""),
        groups=set(userinfo.get("groups", [])),
        roles=set(userinfo.get("roles", [])),
        programs=userinfo.get("programs", []),
    )


async def enforce_agent_access(
    evaluator: object | None,
    bot_name: str,
    request: Optional[web.Request],
) -> None:
    """Raise ``AgentAccessDenied`` if the request's subject cannot resolve ``bot_name``.

    Allow-paths (no exception raised):
      - ``evaluator is None`` — PBAC not initialized; backwards-compatible allow.
      - ``request is None`` — programmatic Python invocation (script, CLI, internal
        crew composition, tests). PBAC enforcement is HTTP-scoped: no request,
        no check. (Resolved §8 Q1.)
      - No policies are registered for ``agent:<bot_name>`` — bot is public.
      - ``PolicyEvaluator.check_access(...)`` returns ``allowed=True``.

    Deny-path (``AgentAccessDenied`` raised):
      - ``request is not None`` AND policies are registered AND
        ``PolicyEvaluator.check_access(...)`` returns ``allowed=False``.

    Logs a WARNING on denials, mirroring the ``PBACPermissionResolver`` pattern.

    Args:
        evaluator: Shared ``PolicyEvaluator`` instance (from
            ``AgentRegistry._evaluator``), or ``None`` when PBAC is disabled.
        bot_name: Base name of the bot being resolved (used as ``resource_name``).
        request: The incoming aiohttp request, or ``None`` for programmatic calls.

    Raises:
        AgentAccessDenied: When the evaluator denies the request's subject.

    Example::

        await enforce_agent_access(self.registry._evaluator, name, request)
    """
    if evaluator is None:
        # PBAC not initialized — fail open for backwards compat.
        return
    if request is None:
        # Programmatic Python invocation — enforcement is HTTP-scoped.
        return

    # Lazy navigator-auth import — mirror resolver.py:312-317.
    # If navigator-auth is absent, fail open.
    try:
        from navigator_auth.abac.policies.resources import ResourceType  # noqa: PLC0415
        from navigator_auth.abac.policies.environment import Environment  # noqa: PLC0415
    except ImportError:
        return

    # Build an EvalContext from the request session.
    try:
        eval_ctx = await _build_eval_context_from_request(request)
    except Exception:  # pylint: disable=broad-except
        # Cannot build context → fail open (session unavailable).
        return

    if eval_ctx is None:
        return

    env = Environment()
    result = evaluator.check_access(
        ctx=eval_ctx,
        resource_type=ResourceType.AGENT,
        resource_name=bot_name,
        action="agent:resolve",
        env=env,
    )

    if not result.allowed:
        user_id = getattr(eval_ctx, "username", None) or getattr(eval_ctx, "user", None)
        matched_policy = getattr(result, "matched_policy", None)
        reason = getattr(result, "reason", None)

        logger.warning(
            "PBAC AGENT DENY: bot=%s user=%s policy=%s reason=%s",
            bot_name,
            user_id,
            matched_policy,
            reason,
        )
        raise AgentAccessDenied(
            bot_name=bot_name,
            user_id=user_id,
            matched_policy=matched_policy,
            reason=reason,
        )
