"""PBACToolCallGuardrail — policy-driven tool-call denial (FEAT-406).

Evaluates the shared ``PolicyEvaluator`` (from ``setup_pbac()``, the same
instance used by Guardian's Layer-1 filtering and ``PBACPermissionResolver``'s
Layer-2 safety net) at the ``GuardrailStage.TOOL_CALL`` pre-execution stage,
translating an ALLOW/DENY decision into a ``GuardrailResult`` the TOOL_CALL
pipeline understands. See ``sdd/specs/pbac-guardrails.spec.md`` §3 Module 2.

Guard-chain position (resolved spec review Q8): this guardrail runs FIRST in
``ToolManager.execute_tool()``, before ``GrantGuard``/``ConfirmationGuard`` —
a policy-doomed call should never interrupt a human for confirmation or
consume a grant.
"""
import logging
from typing import Any, ClassVar

from pydantic import BaseModel

from parrot.auth.permission import PermissionContext, to_eval_context

from ..base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)

logger = logging.getLogger(__name__)


class PolicyDenialReport(BaseModel):
    """Structured denial detail attached to a BLOCK ``GuardrailResult.report``.

    Never carries raw policy YAML, other users' data, or rule internals
    beyond the operator-authored message.

    Attributes:
        rule: The deciding policy's name (``EvaluationResult.matched_policy``),
            or a fail-mode category label (e.g. ``"policy_engine_unavailable"``)
            when the evaluator itself failed.
        message: Operator-authored (or fail-mode) human-readable explanation.
        tool_name: Name of the tool call that was evaluated.
        retry_hint: Optional guidance for the user (e.g. availability window).
    """
    rule: str
    message: str
    tool_name: str
    retry_hint: str | None = None


class PBACToolCallGuardrail(Guardrail):
    """TOOL_CALL guardrail evaluating PBAC policy per tool invocation.

    Constructed by bot wiring with the shared ``PolicyEvaluator`` instance
    (resolved spec Q7) — never via the named registry's kwargs-only factory,
    since the evaluator cannot be expressed as a policy kwarg. The ``"pbac"``
    registry name (see ``registry.py``) exists for discoverability only.

    Attributes:
        _evaluator: Shared ``PolicyEvaluator`` (from ``setup_pbac()``).
        logger: Standard Python logger for denial/error audit events.
    """
    name = "pbac"
    stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
    priority = 10  # sanitizer band — policy check runs before other TOOL_CALL guardrails
    on_error = "fail_closed"  # security control default (resolved Q3)

    def __init__(self, evaluator: "Any", *, logger: logging.Logger | None = None) -> None:
        """Initialize the guardrail with the shared PolicyEvaluator.

        Args:
            evaluator: Shared ``PolicyEvaluator`` instance (same one wired
                into Guardian and ``PBACPermissionResolver`` by ``setup_pbac()``).
            logger: Optional logger; defaults to ``logging.getLogger(__name__)``.
        """
        self._evaluator = evaluator
        self.logger = logger or logging.getLogger(__name__)

    def _policy_enforcement(self, tool_name: str) -> str | None:
        """Best-effort lookup of the ``enforcement`` attribute for a tool's policy.

        Used only to resolve the per-policy ``enforcement: fail_open``
        fail-mode override (resolved Q3) when the evaluator raises and no
        normal ``EvaluationResult`` is available to identify the deciding
        policy. ``PolicyEvaluator`` exposes no public accessor for a single
        policy's ``attributes`` by resource, so this reaches into the
        evaluator's private ``_index`` (``PolicyIndex``) — best-effort only;
        any failure here is swallowed and treated as "no override" (safe
        fail-closed fallback).

        Args:
            tool_name: The tool resource name being evaluated.

        Returns:
            The matching policy's ``attributes.get("enforcement")`` value,
            or ``None`` if no covering policy was found or the lookup failed.
        """
        try:
            from navigator_auth.abac.policies.resources import (
                ResourceType,
            )

            index = getattr(self._evaluator, "_index", None)
            if index is None:
                return None
            for policy in index.get_for_resource_type(ResourceType.TOOL):
                if policy.covers_resource(ResourceType.TOOL, tool_name):
                    attributes = getattr(policy, "attributes", None) or {}
                    enforcement = attributes.get("enforcement")
                    if enforcement is not None:
                        return enforcement
        except Exception:
            self.logger.debug(
                "pbac: enforcement lookup failed for tool=%s (best-effort)",
                tool_name, exc_info=True,
            )
            return None
        return None

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        """Evaluate the shared PolicyEvaluator for this tool call.

        Args:
            content: Compact serialized representation of the call
                (telemetry only — the structured payload lives in
                ``ctx.extras``).
            ctx: Call context. ``ctx.tool_name`` is the resource being
                evaluated; ``ctx.extras["permission_context"]`` carries the
                ``PermissionContext`` used to build the ``EvalContext``.

        Returns:
            ``GuardrailResult(action=PASS)`` on ALLOW (or when enforcement
            is session-scoped and no ``permission_context`` is available);
            ``GuardrailResult(action=BLOCK, ...)`` on DENY or engine failure
            (unless the deciding policy opts into ``enforcement: fail_open``).
        """
        permission_context: PermissionContext | None = ctx.extras.get("permission_context")
        if permission_context is None:
            # Programmatic/test invocation with no session — enforcement is
            # session-scoped, mirroring `enforce_agent_access()` (resolved Q6/§8).
            return GuardrailResult(action=GuardrailAction.PASS)

        tool_name = ctx.tool_name or ""

        try:
            from navigator_auth.abac.policies.environment import (
                Environment,
            )
            from navigator_auth.abac.policies.resources import (
                ResourceType,
            )
        except ImportError:
            # navigator-auth not installed — fail open to preserve backward compat
            # (mirrors PBACPermissionResolver.can_execute / enforce_agent_access).
            return GuardrailResult(action=GuardrailAction.PASS)

        try:
            eval_ctx = to_eval_context(permission_context)
            env = Environment()
            result = self._evaluator.check_access(
                ctx=eval_ctx,
                resource_type=ResourceType.TOOL,
                resource_name=tool_name,
                action="tool:execute",
                env=env,
            )
        except Exception as exc:  # noqa: BLE001 - fail-mode contract, see class docstring
            self.logger.error(
                "PBAC TOOL_CALL evaluation failed for tool=%s: %s", tool_name, exc,
            )
            enforcement = self._policy_enforcement(tool_name)
            if enforcement == "fail_open":
                return GuardrailResult(action=GuardrailAction.PASS)
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="policy_engine_unavailable",
                report=PolicyDenialReport(
                    rule="policy_engine_unavailable",
                    message="Policy engine is temporarily unavailable.",
                    tool_name=tool_name,
                ).model_dump(),
            )

        if result.allowed:
            return GuardrailResult(action=GuardrailAction.PASS)

        rule = result.matched_policy or "unknown"
        self.logger.warning(
            "PBAC TOOL_CALL DENY: tool=%s user=%s policy=%s reason=%s",
            tool_name,
            getattr(permission_context, "user_id", None),
            rule,
            result.reason,
        )
        return GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason=f"policy:{rule}",
            report=PolicyDenialReport(
                rule=rule,
                message=result.reason or f"Access denied by policy '{rule}'.",
                tool_name=tool_name,
            ).model_dump(),
        )
