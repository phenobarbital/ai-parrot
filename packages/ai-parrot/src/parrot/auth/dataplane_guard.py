"""DataPlanePolicyGuard for FEAT-228 Data-Plane Authorization.

A sibling of :class:`~parrot.auth.dataset_guard.DatasetPolicyGuard` that
evaluates **physical-resource** PBAC policies: ``driver:connect``,
``table:read``, and ``source:read`` actions against the shared
``PolicyEvaluator``.

Architecture mirrors ``DatasetPolicyGuard`` exactly:
- Same lazy-import pattern for ``navigator-auth`` types (fail-open on
  ``ImportError``).
- Same ``to_eval_context`` bridge from ``PermissionContext`` to
  ``EvalContext``.
- Same WARNING-on-deny log format for operator visibility.
- Fail-open when no ``PermissionContext`` is available (FEAT-151 parity).
- Fail-closed on evaluator errors for guarded resources.

Resource naming (Spec §2):
    ``driver:<driver>``                  action: ``driver:connect``
    ``table:<driver>:<schema>.<table>``  action: ``table:read``
    ``source:<type>:<identifier>``       action: ``source:read``

Usage::

    guard = DataPlanePolicyGuard(
        evaluator=evaluator,
        rls_registry=registry,
        sensitive_drivers=frozenset({"bigquery_finance"}),
    )
    await guard.authorize_source(ctx, resources)  # raises AuthorizationRequired on denial
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from .permission import PermissionContext, to_eval_context
from .exceptions import AuthorizationRequired

if TYPE_CHECKING:
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator
    from parrot.auth.rls_registry import RlsRegistry, RlsPredicate
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


class DataPlanePolicyGuard:
    """Data-plane authorization guard for driver / table / source resources.

    Sibling of :class:`~parrot.auth.dataset_guard.DatasetPolicyGuard`.
    Evaluates three resource dimensions:
    - ``driver`` → action ``driver:connect``
    - ``table``  → action ``table:read``
    - ``source`` → action ``source:read``

    Failure semantics:
    - ``ctx is None`` → fail-open (no enforcement; FEAT-151 parity).
    - ``ImportError`` for ``navigator-auth`` → fail-open.
    - Any other evaluator exception → fail-closed (DENY) + WARNING log.
    - ``sensitive_drivers`` pre-check rejects non-slug sources before
      any PBAC evaluation.

    Args:
        evaluator: Shared ``PolicyEvaluator`` instance (same as
            ``DatasetPolicyGuard``).
        rls_registry: :class:`~parrot.auth.rls_registry.RlsRegistry` for RLS
            predicate lookup.
        sensitive_drivers: Set of driver names that require ``QuerySlugSource``
            (slug-only enforcement mode).
        logger: Optional logger; defaults to module-level logger.
    """

    def __init__(
        self,
        evaluator: "PolicyEvaluator",
        rls_registry: "RlsRegistry",
        sensitive_drivers: frozenset[str] = frozenset(),
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._evaluator = evaluator
        self._rls_registry = rls_registry
        self._sensitive_drivers = sensitive_drivers
        self._logger = logger or logging.getLogger(__name__)

    # ──────────────────────────────────────────────────────────────────────
    # Driver mode helpers
    # ──────────────────────────────────────────────────────────────────────

    def is_sensitive_driver(self, driver: str) -> bool:
        """Return True if this driver is classed as 'sensitive' (slug-only).

        Args:
            driver: Canonical driver name.

        Returns:
            True when the driver requires ``QuerySlugSource`` access.
        """
        return driver in self._sensitive_drivers

    # ──────────────────────────────────────────────────────────────────────
    # PBAC evaluation helpers
    # ──────────────────────────────────────────────────────────────────────

    def _get_user_id(self, context: PermissionContext) -> Optional[str]:
        """Safely extract user_id from context."""
        session = getattr(context, "session", None)
        if session is None:
            return None
        return getattr(session, "user_id", None)

    # ──────────────────────────────────────────────────────────────────────
    # Public async interface
    # ──────────────────────────────────────────────────────────────────────

    async def can_connect_driver(
        self,
        ctx: PermissionContext,
        driver: str,
    ) -> bool:
        """Check whether the subject may connect to the given driver.

        Evaluates ``driver:connect`` on resource ``driver:<driver>``.

        Args:
            ctx: Current :class:`~parrot.auth.permission.PermissionContext`.
            driver: Canonical driver name.

        Returns:
            True if allowed, False if denied.  Returns True (fail-open) when
            ``navigator-auth`` is not installed.
        """
        try:
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return True  # fail-open

        eval_ctx = to_eval_context(ctx)
        env = Environment()
        try:
            result = self._evaluator.check_access(
                eval_ctx, "driver", driver, "driver:connect", env
            )
            return bool(result.allowed)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "DataPlanePolicyGuard: evaluator error on driver:connect for '%s': %s",
                driver,
                exc,
            )
            return False  # fail-closed

    async def filter_tables(
        self,
        ctx: PermissionContext,
        driver: str,
        tables: list[str],
    ) -> set[str]:
        """Return the subset of tables the subject may read.

        Evaluates ``table:read`` on each ``table:<driver>:<table>`` resource
        using a batch ``filter_resources`` call.

        Args:
            ctx: Current permission context.
            driver: Canonical driver name (for resource prefixing).
            tables: List of table resource strings (``"driver:schema.table"``
                form, as produced by the resolver).

        Returns:
            Set of allowed table resource strings.
        """
        if not tables:
            return set()

        try:
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return set(tables)

        eval_ctx = to_eval_context(ctx)
        env = Environment()
        try:
            result = self._evaluator.filter_resources(
                eval_ctx, "table", tables, "table:read", env
            )
            return set(result.allowed)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "DataPlanePolicyGuard: evaluator error on table:read for driver '%s': %s",
                driver,
                exc,
            )
            return set()  # fail-closed — deny all tables

    async def authorize_source(
        self,
        ctx: Optional[PermissionContext],
        resources: "PhysicalResources",
    ) -> None:
        """Run the full authorization chain for a physical resource set.

        Chain (Spec §2 enforcement chain, steps 1–4):
        1. ``ctx is None`` → fail-open (return without checking).
        2. Gate ``driver:connect`` on ``resources.driver``.
        3. Gate ``table:read`` on each table in ``resources.tables``.
           OR gate ``source:read`` on ``resources.source_type/source_id``.
        4. Raise :class:`~parrot.auth.exceptions.AuthorizationRequired` if
           any gate denies.

        Args:
            ctx: Current permission context.  ``None`` → fail-open.
            resources: Resolved physical resources from the resolver.

        Raises:
            AuthorizationRequired: When any resource gate denies the request.
        """
        # Step 1: fail-open when no context
        if ctx is None:
            return

        try:
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return  # fail-open

        eval_ctx = to_eval_context(ctx)
        env = Environment()
        user_id = self._get_user_id(ctx)

        # Step 2: driver:connect gate
        if resources.driver:
            try:
                result = self._evaluator.check_access(
                    eval_ctx, "driver", resources.driver, "driver:connect", env
                )
                if not result.allowed:
                    self._logger.warning(
                        "DataPlanePolicyGuard DENY driver:connect user=%s driver=%s",
                        user_id,
                        resources.driver,
                    )
                    raise AuthorizationRequired(
                        tool_name="dataplane_authz",
                        message=f"Access to driver '{resources.driver}' denied for user '{user_id}'",
                    )
            except AuthorizationRequired:
                raise
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "DataPlanePolicyGuard: evaluator error on driver:connect for '%s': %s",
                    resources.driver,
                    exc,
                )
                raise AuthorizationRequired(
                    tool_name="dataplane_authz",
                    message=f"Authorization error on driver '{resources.driver}'",
                ) from exc

        # Step 3a: table:read gate (SQL sources)
        if resources.tables:
            try:
                result = self._evaluator.filter_resources(
                    eval_ctx, "table", list(resources.tables), "table:read", env
                )
                allowed = set(result.allowed)
                denied = resources.tables - allowed
                if denied:
                    self._logger.warning(
                        "DataPlanePolicyGuard DENY table:read user=%s denied=%s",
                        user_id,
                        denied,
                    )
                    raise AuthorizationRequired(
                        tool_name="dataplane_authz",
                        message=f"Access to tables {denied} denied for user '{user_id}'",
                    )
            except AuthorizationRequired:
                raise
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "DataPlanePolicyGuard: evaluator error on table:read: %s", exc
                )
                raise AuthorizationRequired(
                    tool_name="dataplane_authz",
                    message="Authorization error on table access",
                ) from exc

        # Step 3b: source:read gate (opaque sources)
        if resources.source_type and resources.source_id:
            resource_name = f"{resources.source_type}:{resources.source_id}"
            try:
                result = self._evaluator.check_access(
                    eval_ctx, "source", resource_name, "source:read", env
                )
                if not result.allowed:
                    self._logger.warning(
                        "DataPlanePolicyGuard DENY source:read user=%s source=%s",
                        user_id,
                        resource_name,
                    )
                    raise AuthorizationRequired(
                        tool_name="dataplane_authz",
                        message=f"Access to source '{resource_name}' denied for user '{user_id}'",
                    )
            except AuthorizationRequired:
                raise
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "DataPlanePolicyGuard: evaluator error on source:read for '%s': %s",
                    resource_name,
                    exc,
                )
                raise AuthorizationRequired(
                    tool_name="dataplane_authz",
                    message=f"Authorization error on source '{resource_name}'",
                ) from exc

    async def rls_predicates(
        self,
        ctx: PermissionContext,
        resources: "PhysicalResources",
    ) -> "list[RlsPredicate]":
        """Collect RLS predicates for the given resources from the registry.

        Looks up matching :class:`~parrot.auth.rls_registry.RlsRule` objects
        from the :class:`~parrot.auth.rls_registry.RlsRegistry` and renders
        them with the subject's attributes.

        Args:
            ctx: Current permission context.
            resources: Resolved physical resources (driver + tables).

        Returns:
            List of rendered :class:`~parrot.auth.rls_registry.RlsPredicate`
            objects ready for injection.  Empty list when no rules match.
        """
        if not resources.driver or not resources.tables:
            return []

        rules = self._rls_registry.lookup(resources.driver, resources.tables)
        predicates = []
        for rule in rules:
            try:
                pred = self._rls_registry.render(rule, ctx)
                predicates.append(pred)
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "DataPlanePolicyGuard: failed to render RLS predicate for "
                    "(%s, %s): %s",
                    resources.driver,
                    rule.table,
                    exc,
                )
        return predicates
