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
from pydantic import BaseModel, Field, PrivateAttr
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
    _column_members: dict[str, str] = PrivateAttr(default_factory=dict)
    _mask_columns: dict[str, str] = PrivateAttr(default_factory=dict)

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

    def bind_physical_columns(self, member_columns: dict[str, set[str]], table_names: dict[str, set[str]]) -> None:
        """Bind member-keyed masks and grants to the physical columns that back them (fail closed).

        Mask keys are ``<table>.<member>`` but governance sees physical ``<schema>.<table>.<column>`` names,
        and a member's ``sql`` may differ from its name (``email`` -> ``email_address``). Every mask key must
        resolve to at least one physical column of a table whose model name, full name or bare name equals
        ``<table>``; otherwise the policy is rejected so a mistyped mask can never silently mask nothing.

        Args:
            member_columns: Member name -> physical ``<schema>.<table>.<column>`` names backing it.
            table_names: Physical ``<schema>.<table>`` -> names it may be referred to by in a mask key.

        Raises:
            SemanticPolicyError: ``unknown_member`` when a mask key resolves to no physical column.
        """
        column_members: dict[str, str] = {}
        for member, columns in member_columns.items():
            for column in columns:
                column_members.setdefault(column, member)
        mask_columns: dict[str, str] = {}
        for key in self.masks:
            table_part, _, member = key.rpartition(".")
            resolved = {
                column
                for column in member_columns.get(member, set())
                if table_part in table_names.get(column.rpartition(".")[0], set())
            }
            if not resolved:
                raise SemanticPolicyError("unknown_member", details={"mask": key})
            for column in resolved:
                mask_columns[column] = key
        self._column_members = column_members
        self._mask_columns = mask_columns

    def member_for(self, column: str) -> str:
        """Return the member name backing a physical column (its last segment when unbound)."""
        return self._column_members.get(column) or column.rpartition(".")[2]

    def mask_rule(self, column: str) -> MaskRule | None:
        """Return the mask governing ``column`` regardless of roles (``None`` when unmasked)."""
        return self._mask_rule(column)

    def _mask_rule(self, column: str) -> MaskRule | None:
        """Find the mask governing ``column``.

        Bound policies (loaded through ``SemanticModelLoader``) resolve physical columns through the binding
        built by :meth:`bind_physical_columns`. Unbound policies fall back to an exact or dotted-suffix match.
        """
        rule = self.masks.get(column)
        if rule is not None:
            return rule
        key = self._mask_columns.get(column)
        if key is not None:
            return self.masks[key]
        if self._mask_columns:
            return None
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
        names = {column.rpartition(".")[2], self.member_for(column)}
        for role in roles:
            grant = self.roles.get(role)
            if grant is not None and (grant.usage == "*" or column in grant.usage or names & set(grant.usage)):
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
