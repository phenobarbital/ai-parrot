"""Model policy side-file: grants, masks, RLS, and saved queries."""

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

from parrot.auth import RlsRule

from .errors import SemanticPolicyError
from .models import Limits, ModelMember, SemanticQuery

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUBJECT_PLACEHOLDER = re.compile(r":subject\.[A-Za-z_][A-Za-z0-9_]*")
_RLS_BOOLEAN_NODES = (sqlglot.exp.Predicate, sqlglot.exp.And, sqlglot.exp.Or, sqlglot.exp.Not)


class RoleGrant(BaseModel):
    """A role's semantic-member projection and physical-column usage grants."""

    model_config = {"extra": "forbid"}

    metrics: list[str] | Literal["*"] = Field(default_factory=list)
    dimensions: list[str] | Literal["*"] = Field(default_factory=list)
    usage: list[str] | Literal["*"] = Field(default_factory=list)


class MaskRule(BaseModel):
    """Projection masking and usage exemptions for a physical column."""

    model_config = {"extra": "forbid"}

    strategy: Literal["null", "hash", "partial"]
    projection_roles: list[str] = Field(default_factory=list)
    usage_roles: list[str] = Field(default_factory=list)


class SavedQuery(BaseModel):
    """A reviewed, model-local semantic query."""

    model_config = {"extra": "forbid"}

    name: str
    query: SemanticQuery
    verified_by: str
    verified_at: date
    description: str = ""


class ModelPolicy(BaseModel):
    """Governance policy associated with one semantic model."""

    model_config = {"extra": "forbid"}

    governed: bool = True
    connection: str = ""
    limits: Limits = Field(default_factory=Limits)
    roles: dict[str, RoleGrant] = Field(default_factory=dict)
    masks: dict[str, MaskRule] = Field(default_factory=dict)
    rls: list[RlsRule] = Field(default_factory=list)
    saved_queries: list[SavedQuery] = Field(default_factory=list)
    allowed_functions: list[str] = Field(default_factory=list)

    def digest(self) -> str:
        """Return the SHA-256 digest of canonical policy JSON."""
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def allowed_members(self, roles: frozenset[str], members: list[ModelMember]) -> set[str]:
        """Return the union of matching role projection grants.

        Args:
            roles: Trusted roles associated with the subject.
            members: Members exposed by the enclosing semantic model.
        """
        metrics = {member.name for member in members if member.kind == "metric"}
        dimensions = {member.name for member in members if member.kind in {"dimension", "time_dimension"}}
        allowed: set[str] = set()
        for role in roles:
            grant = self.roles.get(role)
            if grant is None:
                continue
            allowed.update(metrics if grant.metrics == "*" else grant.metrics)
            allowed.update(dimensions if grant.dimensions == "*" else grant.dimensions)
        return allowed

    def usage_allowed(self, roles: frozenset[str], column: str) -> bool:
        """Return whether roles may use a column outside projection.

        A mask's usage exemption is a separate, explicit permission and takes
        precedence for its protected column.
        """
        mask = self.masks.get(column)
        if mask is not None:
            return bool(roles.intersection(mask.usage_roles))
        return any(grant.usage == "*" or column in grant.usage for role, grant in self.roles.items() if role in roles)

    def mask_for(self, roles: frozenset[str], column: str) -> MaskRule | None:
        """Return the applicable projection mask, if the roles lack exemption."""
        rule = self.masks.get(column)
        if rule is None or roles.intersection(rule.projection_roles):
            return None
        return rule


def load_policy(path: Path, members: list[ModelMember], tables: set[str]) -> ModelPolicy:
    """Parse and validate a model policy file.

    Args:
        path: Path to the ``<model>.policy.yaml`` side-file.
        members: Semantic members available to the policy.
        tables: Physical tables available to RLS rules.

    Raises:
        SemanticPolicyError: If the policy has invalid schema, bindings, or RLS.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise SemanticPolicyError("invalid_policy", "Unable to parse policy file") from exc
    if not isinstance(raw, dict):
        raise SemanticPolicyError("invalid_policy", "Policy document must be a mapping")

    raw = dict(raw)
    _expand_saved_queries(raw, path)
    _validate_rls_schema(raw.get("rls", []))
    try:
        policy = ModelPolicy.model_validate(raw)
    except Exception as exc:
        raise SemanticPolicyError("invalid_policy", "Policy does not match the required schema") from exc

    if policy.governed and not policy.connection:
        raise SemanticPolicyError("invalid_policy", "Governed policies require a connection")

    member_names = {member.name for member in members}
    member_kinds = {member.name: member.kind for member in members}
    time_dimensions = {member.name for member in members if member.kind == "time_dimension"}
    _validate_roles(policy, member_kinds)
    _validate_masks(policy, member_names)
    _validate_saved_queries(policy, member_kinds, time_dimensions)
    _validate_functions(policy)
    _validate_rls(policy, tables)
    return policy


def _expand_saved_queries(raw: dict[str, object], path: Path) -> None:
    """Set each local saved query's model before Pydantic validates it."""
    saved_queries = raw.get("saved_queries", [])
    if not isinstance(saved_queries, list):
        return
    model_name = path.name.removesuffix(".policy.yaml")
    for saved_query in saved_queries:
        if not isinstance(saved_query, dict):
            continue
        query = saved_query.get("query")
        if not isinstance(query, dict):
            continue
        expanded_query = dict(query)
        expanded_query["model"] = model_name
        saved_query["query"] = expanded_query


def _validate_roles(policy: ModelPolicy, member_kinds: dict[str, str]) -> None:
    """Reject malformed role names and grants to unknown semantic members."""
    for role, grant in policy.roles.items():
        if not _IDENT.fullmatch(role):
            raise SemanticPolicyError("invalid_policy", "Role names must be identifiers")
        for grant_members in (grant.metrics, grant.dimensions):
            if grant_members == "*":
                continue
            unknown = sorted(set(grant_members).difference(member_kinds))
            if unknown:
                raise SemanticPolicyError(
                    "unknown_member", "Role grant references an unknown member", details={"members": unknown}
                )
        metric_members = set() if grant.metrics == "*" else set(grant.metrics)
        dimension_members = set() if grant.dimensions == "*" else set(grant.dimensions)
        invalid_metrics = sorted(member for member in metric_members if member_kinds[member] != "metric")
        if invalid_metrics:
            raise SemanticPolicyError("invalid_policy", "Only metrics may appear in a metrics grant")
        invalid_dimensions = sorted(
            member for member in dimension_members if member_kinds[member] not in {"dimension", "time_dimension"}
        )
        if invalid_dimensions:
            raise SemanticPolicyError("invalid_policy", "Only dimensions may appear in a dimensions grant")


def _validate_masks(policy: ModelPolicy, member_names: set[str]) -> None:
    """Validate physical mask keys and their member bindings."""
    for column, rule in policy.masks.items():
        table, separator, member = column.rpartition(".")
        if not separator or not table or not _IDENT.fullmatch(member):
            raise SemanticPolicyError("invalid_policy", "Mask keys must be table.column")
        if member not in member_names:
            raise SemanticPolicyError(
                "unknown_member", "Mask references an unknown member", details={"members": [member]}
            )
        for role in (*rule.projection_roles, *rule.usage_roles):
            if not _IDENT.fullmatch(role):
                raise SemanticPolicyError("invalid_policy", "Mask role names must be identifiers")


def _validate_saved_queries(policy: ModelPolicy, member_kinds: dict[str, str], time_dimensions: set[str]) -> None:
    """Validate fully expanded saved queries against enclosing members."""
    for saved_query in policy.saved_queries:
        try:
            saved_query.query.validate_against(member_kinds, time_dimensions)
        except Exception as exc:
            raise SemanticPolicyError("unknown_member", "Saved query references an unknown member") from exc


def _validate_functions(policy: ModelPolicy) -> None:
    """Normalize additive function names and reject unsafe identifiers."""
    normalized: list[str] = []
    for function in policy.allowed_functions:
        if not _IDENT.fullmatch(function):
            raise SemanticPolicyError("invalid_policy", "Allowed function names must be identifiers")
        normalized.append(function.upper())
    policy.allowed_functions = normalized


def _validate_rls_schema(raw_rules: object) -> None:
    """Reject unknown RLS keys before RlsRule can ignore them."""
    if not isinstance(raw_rules, list):
        return
    allowed = {"driver", "table", "predicate_template", "subject_attribute", "description"}
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict) or set(raw_rule).difference(allowed):
            raise SemanticPolicyError("invalid_policy", "RLS rules contain unknown or invalid fields")


def _validate_rls(policy: ModelPolicy, tables: set[str]) -> None:
    """Validate RLS table bindings and parse each predicate fail-closed."""
    for rule in policy.rls:
        if rule.table not in tables:
            raise SemanticPolicyError("unknown_table", "RLS references an unknown table", details={"table": rule.table})
        _validate_rls_template(rule)


def _validate_rls_template(rule: RlsRule) -> None:
    """Require one safe boolean predicate over columns of the rule's table."""
    template = _SUBJECT_PLACEHOLDER.sub("0", rule.predicate_template)
    try:
        statements = sqlglot.parse(f"SELECT 1 WHERE {template}")
        if len(statements) != 1:
            raise ValueError("expected one statement")
        where = statements[0].args.get("where")
        expression = where.this if where is not None else None
    except Exception as exc:
        raise SemanticPolicyError("invalid_policy", "RLS predicate is not valid SQL") from exc
    if (
        expression is None
        or not isinstance(expression, _RLS_BOOLEAN_NODES)
        or expression.find(sqlglot.exp.Subquery)
        or expression.find(sqlglot.exp.Command)
        or not list(expression.find_all(sqlglot.exp.Column))
    ):
        raise SemanticPolicyError("invalid_policy", "RLS predicate must be a boolean column expression")
    table_name = rule.table.rsplit(".", 1)[-1]
    for column in expression.find_all(sqlglot.exp.Column):
        if column.table and column.table != table_name:
            raise SemanticPolicyError("invalid_policy", "RLS predicate references another table")
