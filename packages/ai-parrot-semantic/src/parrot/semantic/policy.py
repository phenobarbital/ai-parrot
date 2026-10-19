"""`<model>.policy.yaml` side-file: grants, masks, RLS, and saved queries."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

import sqlglot
import yaml
from pydantic import BaseModel, Field
from sqlglot import exp

from parrot.auth import RlsRule

from .errors import SemanticPolicyError
from .models import Limits, ModelMember, SemanticQuery

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUBJECT_PLACEHOLDER = re.compile(r":subject\.([A-Za-z_][A-Za-z0-9_]*)")


class RoleGrant(BaseModel):
    """Semantic members granted to one role."""

    metrics: list[str] | Literal["*"] = Field(default_factory=list)
    dimensions: list[str] | Literal["*"] = Field(default_factory=list)
    usage: list[str] | Literal["*"] = Field(default_factory=list)


class MaskRule(BaseModel):
    """Masking strategy and roles permitted to bypass it."""

    strategy: Literal["null", "hash", "partial"]
    projection_roles: list[str] = Field(default_factory=list)
    usage_roles: list[str] = Field(default_factory=list)


class SavedQuery(BaseModel):
    """A reviewed semantic query exposed by the role catalog."""

    name: str
    query: SemanticQuery
    verified_by: str
    verified_at: date
    description: str = ""


class ModelPolicy(BaseModel):
    """Policy data governing one semantic model."""

    governed: bool = True
    engine: Literal["sidemantic", "native"] = "sidemantic"
    connection: str | None = None
    limits: Limits = Field(default_factory=Limits)
    roles: dict[str, RoleGrant] = Field(default_factory=dict)
    masks: dict[str, MaskRule] = Field(default_factory=dict)
    rls: list[RlsRule] = Field(default_factory=list)
    saved_queries: list[SavedQuery] = Field(default_factory=list)
    allowed_functions: list[str] = Field(default_factory=list)

    def digest(self) -> str:
        """Return the canonical policy SHA-256 digest."""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def allowed_members(self, roles: frozenset[str], members: list[ModelMember]) -> set[str]:
        """Return the union of semantic members granted to ``roles``.

        Metrics are controlled by ``metrics`` grants; dimensions and time dimensions are
        controlled by ``dimensions`` grants. Entity members are intentionally not granted
        by either policy field.
        """
        metric_names = {member.name for member in members if member.kind == "metric"}
        dimension_names = {member.name for member in members if member.kind in {"dimension", "time_dimension"}}
        allowed: set[str] = set()
        for role in roles:
            grant = self.roles.get(role)
            if grant is None:
                continue
            allowed.update(metric_names if grant.metrics == "*" else grant.metrics)
            allowed.update(dimension_names if grant.dimensions == "*" else grant.dimensions)
        return allowed

    def _mask_rule(self, column: str) -> MaskRule | None:
        """Find the mask governing ``column``.

        Mask keys are ``<table>.<member>`` while governance passes physical ``<schema>.<table>.<column>``
        names, so a key matches the column exactly or as a dotted suffix. Never a partial-segment match.
        """
        rule = self.masks.get(column)
        if rule is not None:
            return rule
        for key, candidate in self.masks.items():
            if column.endswith(f".{key}"):
                return candidate
        return None

    def usage_allowed(self, roles: frozenset[str], column: str) -> bool:
        """Return whether ``roles`` may use ``column`` in an expression or predicate.

        ``column`` may be a bare member name or a physical ``<schema>.<table>.<column>``; usage grants list
        bare member names, so they match the column's last segment. Masked columns need ``usage_roles``.
        """
        mask = self._mask_rule(column)
        if mask is not None:
            return bool(roles.intersection(mask.usage_roles))
        name = column.rpartition(".")[2]
        for role in roles:
            grant = self.roles.get(role)
            if grant is not None and (grant.usage == "*" or column in grant.usage or name in grant.usage):
                return True
        return False

    def mask_for(self, roles: frozenset[str], column: str) -> MaskRule | None:
        """Return a projection mask unless a role is permitted to see ``column`` unmasked."""
        rule = self._mask_rule(column)
        if rule is not None and not roles.intersection(rule.projection_roles):
            return rule
        return None


def load_policy(path: Path, members: list[ModelMember], tables: set[str]) -> ModelPolicy:
    """Parse and validate a policy YAML side-file.

    Args:
        path: Policy YAML file path.
        members: Semantic members declared by the companion model.
        tables: Fully qualified physical tables declared by the companion model.

    Raises:
        SemanticPolicyError: If policy data or an RLS predicate is invalid.
    """
    try:
        with path.open(encoding="utf-8") as policy_file:
            data = yaml.safe_load(policy_file)
    except (OSError, yaml.YAMLError) as error:
        raise SemanticPolicyError("invalid_policy") from error

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise SemanticPolicyError("invalid_policy")

    try:
        policy = ModelPolicy.model_validate(data)
    except ValueError as error:
        raise SemanticPolicyError("invalid_policy") from error

    if policy.governed and not policy.connection:
        raise SemanticPolicyError("missing_connection")

    member_names = {member.name for member in members}
    _validate_member_grants(policy, member_names)
    _validate_masks(policy, member_names)
    _validate_saved_queries(policy, member_names)
    _validate_functions(policy)
    _validate_rls(policy, tables)
    return policy


def _validate_member_grants(policy: ModelPolicy, member_names: set[str]) -> None:
    """Reject grant references to semantic members absent from the model."""
    for grant in policy.roles.values():
        for names in (grant.metrics, grant.dimensions, grant.usage):
            if names != "*" and not set(names).issubset(member_names):
                raise SemanticPolicyError("unknown_member")


def _validate_masks(policy: ModelPolicy, member_names: set[str]) -> None:
    """Reject malformed masks and masks targeting unknown semantic members."""
    for column in policy.masks:
        table, separator, member = column.rpartition(".")
        if not separator or not table or not member or not _IDENT.fullmatch(member):
            raise SemanticPolicyError("unknown_member")
        if member not in member_names:
            raise SemanticPolicyError("unknown_member")


def _validate_saved_queries(policy: ModelPolicy, member_names: set[str]) -> None:
    """Reject saved queries that reference absent semantic members."""
    for saved_query in policy.saved_queries:
        query = saved_query.query
        referenced = [*query.metrics, *query.dimensions]
        referenced.extend(item.name for item in query.time_dimensions)
        referenced.extend(item.member for item in query.order_by)
        if query.filters is not None:
            referenced.extend(_filter_members(query.filters))
        if not set(referenced).issubset(member_names):
            raise SemanticPolicyError("unknown_member")


def _filter_members(group: object) -> list[str]:
    """Collect member names from a validated ``SemanticQuery`` filter tree."""
    items = getattr(group, "items", [])
    members: list[str] = []
    for item in items:
        member = getattr(item, "member", None)
        if isinstance(member, str):
            members.append(member)
        else:
            members.extend(_filter_members(item))
    return members


def _validate_functions(policy: ModelPolicy) -> None:
    """Normalize additive function names and reject non-identifiers."""
    if any(_IDENT.fullmatch(function) is None for function in policy.allowed_functions):
        raise SemanticPolicyError("invalid_function")
    policy.allowed_functions = [function.upper() for function in policy.allowed_functions]


def _validate_rls(policy: ModelPolicy, tables: set[str]) -> None:
    """Reject unknown-table or non-predicate RLS templates before runtime use."""
    for rule in policy.rls:
        if rule.table not in tables:
            raise SemanticPolicyError("unknown_table")
        _validate_predicate_template(rule.predicate_template)


def _validate_predicate_template(template: str) -> None:
    """Validate one RLS predicate after replacing subject values with SQL literals."""
    predicate = _SUBJECT_PLACEHOLDER.sub("'subject'", template)
    try:
        statements = sqlglot.parse(predicate)
        if len(statements) != 1:
            raise ValueError("multiple statements")
        expression = sqlglot.parse_one(f"SELECT 1 WHERE {predicate}")
    except (ValueError, sqlglot.errors.ParseError) as error:
        raise SemanticPolicyError("invalid_rls_predicate") from error

    where = expression.args.get("where")
    condition = where.this if where is not None else None
    if condition is None or not isinstance(condition, exp.Condition):
        raise SemanticPolicyError("invalid_rls_predicate")
    if not any(isinstance(node, exp.Column) for node in condition.walk()):
        raise SemanticPolicyError("invalid_rls_predicate")
    prohibited = (exp.Command, exp.Subquery, exp.Select, exp.Table)
    if any(isinstance(node, prohibited) for node in condition.walk()):
        raise SemanticPolicyError("invalid_rls_predicate")
