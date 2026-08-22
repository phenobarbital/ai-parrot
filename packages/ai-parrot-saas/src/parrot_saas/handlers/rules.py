"""HTTP surface for a tenant's coupon eligibility rules.

Rules are configuration a tenant writes, and a bad one does not fail the
request that stored it — it fails the flow for *every review that tenant
receives afterwards*, because ``RuleSet.evaluate_sync()`` raises on a
non-declarative set. So every write is validated by constructing the rule, and
an invalid rule is a 400 naming the offending field rather than a 500 three
days later.

The dry-run endpoint is the other half of that bargain. A tenant can post a
hypothetical guest and see which rule wins, with the per-rule trail behind the
decision — which turns "my rule doesn't work" from a support ticket into
something they diagnose themselves.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from pydantic import ValidationError

from ..rules.builder import (
    DEFAULT_RULESET,
    RuleValidationError,
    build_ruleset,
    validate_rule,
)
from ..rules.context import build_environment, build_eval_context, describe_vocabulary
from ..rules.models import RuleCreate, RuleUpdate
from ..rules.repository import RuleAlreadyExists
from ..tenancy.middleware import current_tenant
from .authz import check_policy
from .tenants import APP_TENANT_RUNTIMES, json_error

#: Key under which ``setup_saas_api`` publishes the rule repository.
APP_RULE_REPOSITORY = "saas_rules"

#: PBAC resource these routes are gated by, under the shared ``saas`` type.
PBAC_RESOURCE_NAME = "rules"

logger = logging.getLogger("parrot_saas.handlers.rules")


class _RuleViewBase(BaseView):
    """Shared plumbing for the rule routes."""

    def _tenant(self):
        """Return the tenant resolved by the middleware."""
        return current_tenant(self.request)

    def _repository(self) -> Optional[Any]:
        """Return the rule repository published on the app."""
        return self.request.app.get(APP_RULE_REPOSITORY)

    async def _authorize(self, action: str) -> Optional[web.Response]:
        """Check the policy for one action."""
        return await check_policy(
            self.request,
            action,
            PBAC_RESOURCE_NAME,
            subject=self._tenant().tenant_id,
        )

    async def _body(self) -> tuple[Optional[dict], Optional[web.Response]]:
        """Parse the JSON body, distinguishing absent from malformed."""
        raw = (await self.request.text()).strip()
        if not raw:
            return {}, None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, json_error(
                400, "invalid_json", f"request body is not valid JSON: {exc}"
            )
        if not isinstance(payload, dict):
            return None, json_error(
                400, "invalid_json", "request body must be a JSON object"
            )
        return payload, None

    @staticmethod
    def _validation_error(exc: ValidationError) -> web.Response:
        """Render a Pydantic validation failure as a 400."""
        return json_error(
            400,
            "validation_error",
            "the request payload is not valid",
            details=[
                {"field": ".".join(str(p) for p in err["loc"]), "error": err["msg"]}
                for err in exc.errors()
            ],
        )

    @staticmethod
    def _rule_error(exc: RuleValidationError) -> web.Response:
        """Render an engine-level rejection as a 400 that names the field."""
        payload: dict[str, Any] = {"field": exc.field} if exc.field else {}
        return json_error(400, "invalid_rule", str(exc), **payload)

    async def _invalidate_runtime(self, tenant_id: str) -> None:
        """Drop the tenant's cached runtime after a rule change.

        A live runtime holds the ruleset compiled from the previous rules, so
        without this an edit would appear to do nothing until the cache TTL
        expired. Full eviction, the same mechanism the secrets API uses: rules
        are configuration and change rarely, and one invalidation path that is
        exercised everywhere beats two that are each exercised half as much.
        """
        runtimes = self.request.app.get(APP_TENANT_RUNTIMES)
        if runtimes is not None:
            await runtimes.invalidate(tenant_id)


class RuleCollectionView(_RuleViewBase):
    """List and create eligibility rules."""

    _logger_name: str = "parrot_saas.RuleCollectionView"

    async def get(self) -> web.Response:
        """List this tenant's rules in evaluation order.

        Disabled rules are included: a rule a tenant switched off is still a
        rule they want to see, and hiding it makes "why is nothing matching?"
        much harder to answer.
        """
        denied = await self._authorize("saas:rule:read")
        if denied is not None:
            return denied
        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "rules are not configured")

        args = self.get_arguments(self.request)
        ruleset = args.get("ruleset") or DEFAULT_RULESET
        rules = await repository.list_rules(
            self._tenant().tenant_id, ruleset=ruleset
        )
        return web.json_response(
            {
                "rules": [r.model_dump(mode="json") for r in rules],
                "count": len(rules),
                "ruleset": ruleset,
                # Shipped with the listing so a client never hard-codes the
                # vocabulary and then drifts from it.
                "vocabulary": describe_vocabulary(),
            }
        )

    async def post(self) -> web.Response:
        """Create a rule, refusing one the engine could not evaluate."""
        denied = await self._authorize("saas:rule:write")
        if denied is not None:
            return denied
        payload, error = await self._body()
        if error is not None:
            return error
        try:
            create = RuleCreate(**payload)
        except ValidationError as exc:
            return self._validation_error(exc)
        try:
            validate_rule(create.model_dump())
        except RuleValidationError as exc:
            return self._rule_error(exc)

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "rules are not configured")
        tenant = self._tenant()
        try:
            rule = await repository.create(tenant.tenant_id, create)
        except RuleAlreadyExists:
            # 409 emitted directly: BaseView.error() would degrade it to 400.
            return json_error(
                409,
                "rule_exists",
                f"a rule named {create.name!r} already exists in ruleset "
                f"{create.ruleset!r}",
            )

        await self._invalidate_runtime(tenant.tenant_id)
        logger.info(
            "tenant %s created rule %s (priority=%d)",
            tenant.tenant_id,
            rule.name,
            rule.priority,
        )
        return web.json_response(rule.model_dump(mode="json"), status=201)


class RuleItemView(_RuleViewBase):
    """Amend or remove one rule."""

    _logger_name: str = "parrot_saas.RuleItemView"

    def _rule_id(self) -> str:
        """Return the rule id from the path."""
        return self.request.match_info.get("rule_id", "")

    async def patch(self) -> web.Response:
        """Apply a partial amendment, re-validating the result."""
        denied = await self._authorize("saas:rule:write")
        if denied is not None:
            return denied
        payload, error = await self._body()
        if error is not None:
            return error
        try:
            patch = RuleUpdate(**payload)
        except ValidationError as exc:
            return self._validation_error(exc)

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "rules are not configured")
        tenant = self._tenant()
        rule_id = self._rule_id()

        existing = await repository.get(tenant.tenant_id, rule_id)
        if existing is None:
            return json_error(404, "unknown_rule", f"no such rule: {rule_id!r}")

        # Validate the *merged* rule, not the patch: changing only the priority
        # is fine, but changing only the conditions must still leave something
        # the engine can evaluate.
        merged = {**existing.to_spec(), **patch.changes()}
        try:
            validate_rule(merged)
        except RuleValidationError as exc:
            return self._rule_error(exc)

        rule = await repository.update(tenant.tenant_id, rule_id, patch)
        if rule is None:  # pragma: no cover - lost to a concurrent delete
            return json_error(404, "unknown_rule", f"no such rule: {rule_id!r}")

        await self._invalidate_runtime(tenant.tenant_id)
        return web.json_response(rule.model_dump(mode="json"))

    async def delete(self) -> web.Response:
        """Remove a rule."""
        denied = await self._authorize("saas:rule:delete")
        if denied is not None:
            return denied
        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "rules are not configured")

        tenant = self._tenant()
        rule_id = self._rule_id()
        if not await repository.delete(tenant.tenant_id, rule_id):
            return json_error(404, "unknown_rule", f"no such rule: {rule_id!r}")

        await self._invalidate_runtime(tenant.tenant_id)
        logger.info("tenant %s deleted rule %s", tenant.tenant_id, rule_id)
        return web.Response(status=204)


class RuleEvaluateView(_RuleViewBase):
    """Dry-run the tenant's ruleset against a hypothetical guest."""

    _logger_name: str = "parrot_saas.RuleEvaluateView"

    async def post(self) -> web.Response:
        """Evaluate a supplied context and explain the outcome.

        Read-only in every sense: no coupon is issued, nothing is stored, and
        the ruleset is compiled fresh from the current rows rather than taken
        from the cached runtime — so a tenant testing an edit sees the edit.
        """
        denied = await self._authorize("saas:rule:read")
        if denied is not None:
            return denied
        payload, error = await self._body()
        if error is not None:
            return error

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "rules are not configured")

        tenant = self._tenant()
        ruleset_name = str(payload.get("ruleset") or DEFAULT_RULESET)
        supplied = payload.get("context")
        if supplied is not None and not isinstance(supplied, dict):
            return json_error(
                400, "invalid_context", "'context' must be a JSON object"
            )

        rules = await repository.list_rules(
            tenant.tenant_id, ruleset=ruleset_name, enabled_only=True
        )
        # The Python backend on purpose: the native matcher reports only the
        # winning index and, on a miss, no inspected rules at all — which is
        # precisely the case a tenant is debugging. A dry-run is a rare,
        # human-triggered call, so the explanation is worth far more than the
        # microseconds.
        ruleset = build_ruleset(
            (r.to_spec() for r in rules), backend="python"
        )

        shared = {
            "timezone": tenant.timezone,
            "eligibility_ctx": supplied or {},
        }
        if payload.get("now"):
            from datetime import datetime

            try:
                shared["now"] = datetime.fromisoformat(
                    str(payload["now"]).replace("Z", "+00:00")
                )
            except ValueError:
                return json_error(
                    400, "invalid_context", "'now' must be an ISO-8601 timestamp"
                )

        eval_ctx = build_eval_context(shared)
        env = build_environment(shared)
        outcome = ruleset.evaluate_sync(eval_ctx, env)
        winner = outcome.rule

        return web.json_response(
            {
                "matched": outcome.matched,
                "offer": outcome.value,
                "rule": getattr(winner, "name", None),
                # The trail is the point: under FIRST_MATCH only the rules
                # actually inspected appear, which is itself the explanation
                # for why a lower-priority rule never got a look in.
                "inspected": [
                    {
                        "rule": getattr(r.rule, "name", ""),
                        "priority": getattr(r.rule, "priority", 0),
                        "matched": r.matched,
                    }
                    for r in outcome.results
                ],
                "evaluated_context": {
                    k: v
                    for k, v in eval_ctx.flatten(env).items()
                    if k.startswith("ctx.")
                },
                "rules_considered": len(ruleset),
            }
        )


def setup_rule_routes(
    app: web.Application, *, base: str = "/api/v1/saas/rules"
) -> None:
    """Register the rule routes.

    ``evaluate`` goes in before the ``{rule_id}`` pattern: aiohttp resolves
    resources in registration order, so the dynamic route would swallow it.

    Args:
        app: The aiohttp application.
        base: Base path for the collection.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(base, RuleCollectionView)
    _app.router.add_view(f"{base}/evaluate", RuleEvaluateView)
    _app.router.add_view(f"{base}/{{rule_id}}", RuleItemView)


__all__ = (
    "APP_RULE_REPOSITORY",
    "RuleCollectionView",
    "RuleEvaluateView",
    "RuleItemView",
    "setup_rule_routes",
)
