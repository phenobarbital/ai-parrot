"""Row-Level Security (RLS) Registry for FEAT-228 Data-Plane Authorization.

Maps ``(driver, table)`` pairs to predicate templates with subject-attribute
placeholders.  At query time the registry renders a :class:`RlsPredicate` that
the injection layer (:mod:`parrot.tools.dataset_manager.sources.rls`) injects
into the outbound query.

Design constraints (see spec §2 and §4):
- Predicates are *never* string-interpolated.  Values are always returned as
  bound parameters (``bound_params`` dict) for the driver to bind safely.
- Empty attribute lists (e.g. no programs on the subject) produce a deny-all
  predicate (``1=0``) rather than an open predicate.
- The registry is in-memory and loaded from config at startup (config loading
  is outside this module's responsibility).

Usage::

    from parrot.auth.rls_registry import RlsRegistry, RlsRule, RlsPredicate

    registry = RlsRegistry()
    registry.register(RlsRule(
        driver="pg",
        table="sales.orders",
        predicate_template="region IN (:subject.programs)",
        subject_attribute="programs",
        description="Regional managers see only their region",
    ))

    # At query time:
    predicates = registry.lookup("pg", {"pg:sales.orders"})
    rendered = registry.render(predicates[0], pctx)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.auth.permission import PermissionContext

_logger = logging.getLogger(__name__)

# Placeholder pattern: :subject.<attr>
_PLACEHOLDER_RE = re.compile(r":subject\.(\w+)")


class RlsRule(BaseModel):
    """Registry entry: template predicate keyed by ``(driver, table)``.

    Attributes:
        driver: Canonical ai-parrot driver name (output of ``normalize_driver``).
        table: Fully-qualified table name in ``schema.table`` form.
        predicate_template: SQL WHERE fragment with ``:subject.<attr>``
            placeholders, e.g. ``"region IN (:subject.programs)"``.
        subject_attribute: Name of the ``UserSession.metadata`` key whose
            values are bound as parameters, e.g. ``"programs"`` or
            ``"groups"``.
        description: Human-readable description of the rule.
    """

    driver: str
    table: str
    predicate_template: str
    subject_attribute: str
    description: str = ""


class RlsPredicate(BaseModel):
    """A rendered RLS predicate ready for injection.

    Attributes:
        table: The physical table this predicate applies to.
        sql_predicate: SQL WHERE clause fragment with parameter placeholders
            (e.g. ``"region IN (:p0, :p1)"``).  Subject values are *never*
            interpolated into this string — they live in ``bound_params``.
        bound_params: Mapping from placeholder name to list of string values
            to bind (e.g. ``{"p0": ["northeast"], "p1": ["southeast"]}``).
    """

    table: str
    sql_predicate: str
    bound_params: dict[str, list[str]] = Field(default_factory=dict)


class RlsRegistry:
    """In-memory registry mapping ``(driver, table)`` to predicate templates.

    Rules are keyed by ``(driver, table)``.  The ``lookup`` method strips the
    ``driver:`` prefix from table resource strings (``"pg:sales.orders"`` →
    looks up ``("pg", "sales.orders")``).

    Example::

        registry = RlsRegistry()
        registry.register(RlsRule(
            driver="pg",
            table="sales.orders",
            predicate_template="region IN (:subject.programs)",
            subject_attribute="programs",
        ))
        rules = registry.lookup("pg", {"pg:sales.orders"})
        assert len(rules) == 1
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._rules: dict[tuple[str, str], RlsRule] = {}
        self._logger = logging.getLogger(__name__)

    def register(self, rule: RlsRule) -> None:
        """Add a predicate template rule to the registry.

        Args:
            rule: The :class:`RlsRule` to register.  If a rule for the same
                ``(driver, table)`` already exists it is replaced.
        """
        key = (rule.driver, rule.table)
        self._rules[key] = rule
        self._logger.debug(
            "RlsRegistry: registered rule for (%s, %s)", rule.driver, rule.table
        )

    def lookup(self, driver: str, tables: set[str]) -> list[RlsRule]:
        """Return matching rules for the given driver and table resource strings.

        Args:
            driver: Canonical driver name (e.g. ``"pg"``).
            tables: Set of table resource strings in ``"driver:schema.table"``
                form (as produced by the physical-resource resolver).

        Returns:
            List of :class:`RlsRule` objects whose ``(driver, table)`` pair
            matches any of the supplied table resources.
        """
        matched: list[RlsRule] = []
        for resource in tables:
            # Resource format: "driver:schema.table"  or  "schema.table"
            if ":" in resource:
                _res_driver, _, table_name = resource.partition(":")
            else:
                table_name = resource
            key = (driver, table_name)
            rule = self._rules.get(key)
            if rule is not None:
                matched.append(rule)
        return matched

    def render(self, rule: RlsRule, ctx: PermissionContext) -> RlsPredicate:
        """Render a rule into a bound :class:`RlsPredicate`.

        Subject attribute values are read from
        ``ctx.session.metadata[rule.subject_attribute]``.  Values are never
        interpolated into the SQL string — they are placed in ``bound_params``
        for safe parameterised binding.

        If the subject has no values for the required attribute (empty list),
        the predicate is set to ``1=0`` (deny-all tautology) to prevent
        data exposure when a required restriction cannot be established.

        Args:
            rule: The :class:`RlsRule` template to render.
            ctx: The current :class:`PermissionContext` from which subject
                attribute values are extracted.

        Returns:
            A :class:`RlsPredicate` with parameter placeholders in
            ``sql_predicate`` and actual values in ``bound_params``.
        """
        metadata: dict[str, Any] = ctx.session.metadata or {}
        values: list[str] = [
            str(v) for v in metadata.get(rule.subject_attribute, [])
        ]

        if not values:
            # Deny-all: empty attribute list → no row should be visible.
            self._logger.debug(
                "RlsRegistry.render: empty attribute '%s' for user '%s' → deny-all predicate",
                rule.subject_attribute,
                ctx.session.user_id,
            )
            return RlsPredicate(
                table=rule.table,
                sql_predicate="1=0",
                bound_params={},
            )

        # Build positional parameter placeholders (:p0, :p1, …)
        params: dict[str, list[str]] = {}
        placeholders: list[str] = []
        for i, val in enumerate(values):
            param_name = f"p{i}"
            params[param_name] = [val]
            placeholders.append(f":{param_name}")

        # Replace `:subject.<attr>` with the generated placeholders joined
        # by commas (for IN-list style predicates).
        placeholder_list = ", ".join(placeholders)
        sql_predicate = _PLACEHOLDER_RE.sub(
            lambda _m: placeholder_list, rule.predicate_template
        )

        return RlsPredicate(
            table=rule.table,
            sql_predicate=sql_predicate,
            bound_params=params,
        )
