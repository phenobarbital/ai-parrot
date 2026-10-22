"""PBAC (fail-open) mixin of :class:`StudioBaseView` — ``astudio:<area>`` resource checks."""

from __future__ import annotations

# PBAC (Policy-Based Access Control) — optional, fail-open if absent.
# Mirrors handlers/bots.py `_PBACHandlerMixin` exactly.
try:
    from navigator_auth.abac.policies.resources import ResourceType as _ResourceType

    _PBAC_AVAILABLE = True
except ImportError:
    _ResourceType = None
    _PBAC_AVAILABLE = False

# Canonical PBAC EvalContext builder (FEAT-446) — single source of truth.
from parrot.auth.eval_context import build_eval_context as _core_build_eval_context


class _StudioPbacMixin:
    """Fail-open PBAC checks under the ``astudio:<area>`` resource namespace."""

    def _get_pbac_evaluator(self):
        """Return the PDP evaluator from ``app['abac']``, or ``None`` (fail-open).

        Returns:
            ``PolicyEvaluator`` instance when PBAC is configured, ``None``
            otherwise.
        """
        if not _PBAC_AVAILABLE:
            return None
        pdp = self.request.app.get("abac")
        return getattr(pdp, "_evaluator", None) if pdp is not None else None

    async def _build_eval_context(self):
        """Build the navigator-auth ``EvalContext`` for the current request.

        Returns:
            ``EvalContext`` instance, or ``None`` if unavailable
            (fail-open — callers must handle ``None``).
        """
        if not _PBAC_AVAILABLE:
            return None
        return await _core_build_eval_context(self.request)

    async def _pbac_allowed(self, resource: str, action: str) -> bool:
        """Fail-open PBAC check for a Studio resource id.

        Args:
            resource: Studio area, e.g. ``"agents"`` — namespaced
                internally to ``astudio:<resource>`` (spec §2: PBAC ids
                are ``astudio:<area>``, e.g. ``astudio:agents``,
                ``astudio:skills``, ``astudio:keys``).
            action: The action string, e.g. ``"astudio:agents:create"``.

        Returns:
            ``True`` when access is allowed OR when no PDP is configured
            (fail-open — same posture as ``_PBACHandlerMixin``); ``False``
            only on an explicit deny from a configured evaluator.
        """
        evaluator = self._get_pbac_evaluator()
        if evaluator is None:
            return True
        ctx = await self._build_eval_context()
        if ctx is None:
            return True
        resource_name = f"astudio:{resource}"
        try:
            result = evaluator.check_access(ctx, _ResourceType.URI, resource_name, action)
            return bool(getattr(result, "allowed", True))
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio PBAC: evaluator error for resource=%s action=%s, " "failing open: %s",
                resource_name,
                action,
                exc,
            )
            return True

    async def _pbac_gate(self, resource: str, action: str):
        """Enforce a PBAC check; return a 403 response on deny, else ``None``.

        Adversarial-review fix: ``_pbac_allowed`` was implemented (and
        unit-tested) but never CALLED by any concrete handler — a
        configured PDP denying ``astudio:*`` had zero effect. Every
        mutating Studio verb now opens with::

            if (denied := await self._pbac_gate("agents", "astudio:agents:create")) is not None:
                return denied

        Still fail-open by design: with no PDP configured (or on
        evaluator errors) ``_pbac_allowed`` returns ``True`` and this
        returns ``None``.

        Args:
            resource: Studio area (``"agents"``, ``"skills"``, ...) —
                namespaced to ``astudio:<resource>`` downstream.
            action: The action string, e.g. ``"astudio:agents:create"``.

        Returns:
            An aiohttp 403 JSON response on an explicit deny; ``None``
            when access is allowed.
        """
        if await self._pbac_allowed(resource, action):
            return None
        from ..models import StudioError  # local import — keeps _base dependency-light

        return self.json_response(
            StudioError(message=f"Access denied by policy for '{action}'.", code="pbac_denied").model_dump(),
            status=403,
        )

