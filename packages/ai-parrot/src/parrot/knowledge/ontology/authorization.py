"""Intent-level authorization checker for the ontology pipeline (FEAT-158).

``AuthorizationChecker`` evaluates ``AuthorizationSpec`` rules **after** entity
resolution and **before** graph traversal. Rules are OR-combined: the first
matching rule grants access. When no rule matches and ``spec.default_deny=True``
(the default), access is denied with a human-readable reason.

**Default-deny is explicit and load-bearing.** Every ``AuthorizationSpec``
without a matching rule will deny unless explicitly overridden with
``default_deny=False``. This is documented here because pattern authors must
be aware: an empty ``rules: []`` spec with ``default_deny=True`` (the default)
will ALWAYS deny. That is the intended behavior for the paranoid default.

Supported rules (five declarative types):
- ``always``: unconditionally allow.
- ``target_is_self``: allow if the requesting user equals any resolved entity.
- ``target_in_management_chain``: AQL traversal (depth ≤ 10) along
  ``reports_to`` edges from the requesting user. Allow if any resolved entity
  is found within depth 10.
- ``has_role``: allow if ``rule.role`` is in ``user_context["roles"]``.
- ``same_department``: allow if the requesting user's department equals the
  resolved entity's department (fetched via a graph lookup).

Usage::

    checker = AuthorizationChecker(graph_store=graph_store)
    allowed, reason = await checker.check(
        spec=pattern.authorization,
        user_context={"user_id": "Emp/42", "roles": ["hr_manager"]},
        resolved_entities={"target_employee": "Emp/55"},
        tenant_id="acme",
    )
"""
from __future__ import annotations

import logging
from typing import Any

from .graph_store import OntologyGraphStore
from .schema import AuthorizationRule, AuthorizationSpec


class AuthorizationChecker:
    """Evaluates declarative authorization rules against resolved entities.

    Args:
        graph_store: ArangoDB wrapper used for management-chain and
            same-department AQL traversals.
        reports_to_collection: ArangoDB edge collection name for the
            ``reports_to`` relation. Defaults to ``"reports_to"``.
    """

    def __init__(
        self,
        graph_store: OntologyGraphStore,
        reports_to_collection: str = "reports_to",
    ) -> None:
        self._graph_store = graph_store
        self._reports_to = reports_to_collection
        self.logger = logging.getLogger(__name__)

    async def check(
        self,
        spec: AuthorizationSpec,
        user_context: dict[str, Any],
        resolved_entities: dict[str, str],
        tenant_id: str,
    ) -> tuple[bool, str | None]:
        """Evaluate ``spec.rules`` in order, returning on first match.

        OR semantics: iterates rules in declaration order; the first rule that
        grants access short-circuits the rest and returns ``(True, None)``.

        Default-deny: if no rule matches and ``spec.default_deny`` is True,
        returns ``(False, "no authorization rule matched")``. If
        ``default_deny=False``, returns ``(True, None)`` (intentional bypass
        for fully-trusted patterns such as internal service calls).

        Missing ``user_id`` in ``user_context`` causes all rules except
        ``always`` to deny immediately with a specific reason.

        Args:
            spec: Declarative authorization spec from the matched pattern.
            user_context: Session data. Must contain ``user_id`` for all
                non-``always`` rules.
            resolved_entities: Mapping from rule_name → graph ``_id`` produced
                by the entity resolver.
            tenant_id: Tenant identifier for scoping AQL traversals.

        Returns:
            ``(True, None)`` if access is granted.
            ``(False, denial_reason)`` if access is denied.
        """
        user_id = user_context.get("user_id")

        for rule in spec.rules:
            if rule.rule == "always":
                self.logger.info(
                    "auth check: allow rule=always user=%s", user_id
                )
                return True, None

            if not user_id:
                self.logger.warning(
                    "auth check: deny — missing user_id in user_context rule=%s",
                    rule.rule,
                )
                return False, "missing user_id in permission_context"

            allowed = await self._evaluate_rule(
                rule, user_id, user_context, resolved_entities, tenant_id
            )
            if allowed:
                self.logger.info(
                    "auth check: allow rule=%s user=%s", rule.rule, user_id
                )
                return True, None

        # No rule matched
        if not spec.default_deny:
            self.logger.info(
                "auth check: allow (default_deny=False, no rule matched) user=%s",
                user_id,
            )
            return True, None

        self.logger.info(
            "auth check: deny (default_deny) user=%s resolved=%s",
            user_id, resolved_entities,
        )
        return False, "no authorization rule matched"

    # ------------------------------------------------------------------
    # Rule dispatch
    # ------------------------------------------------------------------

    async def _evaluate_rule(
        self,
        rule: AuthorizationRule,
        user_id: str,
        user_context: dict[str, Any],
        resolved_entities: dict[str, str],
        tenant_id: str,
    ) -> bool:
        """Dispatch to the appropriate per-rule evaluator.

        Args:
            rule: The authorization rule to evaluate.
            user_id: Requesting user's graph ``_id``.
            user_context: Full session data.
            resolved_entities: Resolved entity ``_id``s from the resolver.
            tenant_id: Tenant identifier.

        Returns:
            ``True`` if the rule grants access, ``False`` otherwise.
        """
        if rule.rule == "target_is_self":
            return self._check_target_is_self(user_id, resolved_entities)

        if rule.rule == "target_in_management_chain":
            return await self._check_management_chain(
                user_id, resolved_entities, tenant_id
            )

        if rule.rule == "has_role":
            return self._check_has_role(rule.role or "", user_context)

        if rule.rule == "same_department":
            return await self._check_same_department(
                user_context, resolved_entities, tenant_id
            )

        # "always" is handled in the outer loop before reaching here
        return False  # pragma: no cover

    # ------------------------------------------------------------------
    # Individual rule evaluators
    # ------------------------------------------------------------------

    def _check_target_is_self(
        self,
        user_id: str,
        resolved_entities: dict[str, str],
    ) -> bool:
        """Allow if the requesting user equals ANY resolved entity ``_id``.

        Args:
            user_id: Requesting user's ``_id``.
            resolved_entities: Resolved entity ``_id``s.

        Returns:
            True if the user is one of the resolved entities.
        """
        return user_id in resolved_entities.values()

    async def _check_management_chain(
        self,
        user_id: str,
        resolved_entities: dict[str, str],
        tenant_id: str,
    ) -> bool:
        """Allow if ANY resolved entity is a subordinate (depth ≤ 10).

        Executes a bounded OUTBOUND traversal along ``reports_to`` edges from
        the requesting user. If a resolved entity ``_id`` appears in the
        traversal results, the user manages that entity (directly or
        transitively).

        AQL (depth ≤ 10):

        .. code-block:: aql

            FOR v IN 1..10 OUTBOUND @asker_id @@reports_to
              FILTER v._id == @target_id
              RETURN v._id

        Args:
            user_id: Requesting user's ``_id``.
            resolved_entities: Resolved entity ``_id``s to check.
            tenant_id: Tenant identifier.

        Returns:
            True if at least one resolved entity is in the management chain.
        """
        from .schema import MergedOntology, TenantContext
        from datetime import datetime, timezone

        # Build a minimal TenantContext for the AQL call.
        # The graph_store mock in tests does not use the ctx fields;
        # in production the mixin supplies a real ctx.
        mock_ontology = MergedOntology(
            name="auth_check",
            version="1.0",
            entities={},
            relations={},
            traversal_patterns={},
            layers=[],
            merge_timestamp=datetime.now(timezone.utc),
        )
        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=mock_ontology,
        )

        aql = (
            "FOR v IN 1..10 OUTBOUND @asker_id @@reports_to "
            "FILTER v._id == @target_id "
            "RETURN v._id"
        )
        collection_binds = {"@reports_to": self._reports_to}

        for target_id in resolved_entities.values():
            bind_vars = {"asker_id": user_id, "target_id": target_id}
            try:
                results = await self._graph_store.execute_traversal(
                    ctx=ctx,
                    aql=aql,
                    bind_vars=bind_vars,
                    collection_binds=collection_binds,
                )
                if results:
                    return True
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "management-chain traversal failed for user=%s target=%s: %s",
                    user_id, target_id, exc,
                )

        return False

    def _check_has_role(
        self,
        required_role: str,
        user_context: dict[str, Any],
    ) -> bool:
        """Allow if the requesting user holds ``required_role``.

        Reads ``user_context["roles"]`` — expected to be a list of role
        name strings.

        Args:
            required_role: Role name to check (from ``AuthorizationRule.role``).
            user_context: Session data with optional ``roles`` list.

        Returns:
            True if the role is in the user's role list.
        """
        roles = user_context.get("roles", [])
        return required_role in roles

    async def _check_same_department(
        self,
        user_context: dict[str, Any],
        resolved_entities: dict[str, str],
        tenant_id: str,
    ) -> bool:
        """Allow if the requesting user's department matches ANY resolved entity.

        Fetches the entity's ``department`` field via a DOCUMENT lookup.

        Args:
            user_context: Session data with optional ``department`` field.
            resolved_entities: Resolved entity ``_id``s.
            tenant_id: Tenant identifier.

        Returns:
            True if at least one resolved entity shares the user's department.
        """
        user_dept = user_context.get("department")
        if not user_dept:
            return False

        from .schema import MergedOntology, TenantContext
        from datetime import datetime, timezone

        mock_ontology = MergedOntology(
            name="auth_check",
            version="1.0",
            entities={},
            relations={},
            traversal_patterns={},
            layers=[],
            merge_timestamp=datetime.now(timezone.utc),
        )
        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=mock_ontology,
        )

        aql = "RETURN DOCUMENT(@target_id).department"

        for target_id in resolved_entities.values():
            bind_vars = {"target_id": target_id}
            try:
                results = await self._graph_store.execute_traversal(
                    ctx=ctx,
                    aql=aql,
                    bind_vars=bind_vars,
                )
                if results and results[0] == user_dept:
                    return True
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "same-department lookup failed for target=%s: %s",
                    target_id, exc,
                )

        return False
