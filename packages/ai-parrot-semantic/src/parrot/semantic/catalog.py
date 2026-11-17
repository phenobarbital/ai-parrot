"""Role-filtered catalog, member-right checks and saved-query expansion (spec §3 Module 7)."""

from __future__ import annotations

import ast
import difflib
import logging
from typing import Any

from .errors import SemanticAccessError, SemanticValidationError
from .loader import LoadedModel
from .models import FilterGroup, FilterLeaf, ModelMember, SemanticQuery


class RoleCatalog:
    """Expose only the semantic members a subject's roles are granted.

    Args:
        models: Loaded model snapshot keyed by model name.
    """

    def __init__(self, models: dict[str, LoadedModel]) -> None:
        self.models = models
        self.logger = logging.getLogger(__name__)

    def visible_members(self, model: str, roles: frozenset[str], *, authorized: bool) -> list[ModelMember]:
        """Allowed members only; a governed model with authorized=False exposes nothing (not even names).

        Masked members stay visible: masking is applied to projected values downstream,
        never by hiding the member from a role that was granted it.

        Args:
            model: Model name.
            roles: Trusted subject roles.
            authorized: Whether the subject is an authenticated, authorized principal.

        Raises:
            SemanticAccessError: If the model is unknown.
        """
        loaded = self.models.get(model)
        if loaded is None:
            raise SemanticAccessError("model_not_found", "Unknown or inaccessible model", details={"model": model})
        if not loaded.policy.governed:
            return list(loaded.members)
        if not authorized:
            return []
        allowed = loaded.policy.allowed_members(roles, loaded.members)
        return [member for member in loaded.members if member.name in allowed]

    def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None:
        """Every metric/dimension/time-dimension/filter/order member must be allowed.

        Derived metric dependencies and metric filter members are checked as well.

        Raises:
            SemanticAccessError: ``member_not_granted`` for the first disallowed member, with
                suggestions drawn only from allowed members.
        """
        loaded = self.models.get(query.model)
        if loaded is None:
            raise SemanticAccessError(
                "model_not_found", "Unknown or inaccessible model", details={"model": query.model}
            )
        if not loaded.policy.governed:
            return
        allowed = loaded.policy.allowed_members(roles, loaded.members)
        for name in self._referenced_members(query, loaded):
            if name not in allowed:
                raise SemanticAccessError(
                    "member_not_granted",
                    "Query references a member that is not granted",
                    details={"member": name, "suggestions": self._suggest(name, sorted(allowed))},
                )

    def expand_saved_query(self, query: SemanticQuery) -> SemanticQuery:
        """Replace `saved_query` with the stored query (same model); unknown name -> SemanticValidationError."""
        if query.saved_query is None:
            return query
        loaded = self.models.get(query.model)
        saved = None
        if loaded is not None:
            saved = next((item for item in loaded.policy.saved_queries if item.name == query.saved_query), None)
        if saved is None:
            raise SemanticValidationError(
                "unknown_saved_query",
                "Unknown saved query for this model",
                details={"model": query.model, "saved_query": query.saved_query},
            )
        update: dict[str, Any] = {"model": query.model}
        if "limit" in query.model_fields_set and query.limit is not None:
            update["limit"] = query.limit
        if "offset" in query.model_fields_set and query.offset:
            update["offset"] = query.offset
        expanded = saved.query.model_copy(update=update, deep=True)
        return SemanticQuery.model_validate(expanded.model_dump())

    def search(
        self,
        text: str,
        roles: frozenset[str],
        model: str | None = None,
        *,
        authorized: dict[str, bool] | None = None,
    ) -> list[dict]:
        """Case-insensitive substring + difflib ranking over visible members and descriptions."""
        authorized = authorized or {}
        needle = text.strip().lower()
        names = [model] if model is not None else sorted(self.models)
        hits: list[tuple[float, str, str, dict]] = []
        for name in names:
            if name not in self.models:
                continue
            members = self.visible_members(name, roles, authorized=bool(authorized.get(name, False)))
            for member in members:
                haystack = f"{member.name} {member.description}".lower()
                ratio = difflib.SequenceMatcher(None, needle, member.name.lower()).ratio()
                if needle and needle in haystack:
                    score = 1.0 + ratio
                elif ratio >= 0.6:
                    score = ratio
                else:
                    continue
                hits.append(
                    (
                        score,
                        name,
                        member.name,
                        {"model": name, "member": member.name, "kind": member.kind, "description": member.description},
                    )
                )
        hits.sort(key=lambda hit: (-hit[0], hit[1], hit[2]))
        return [hit[3] for hit in hits]

    @staticmethod
    def _referenced_members(query: SemanticQuery, loaded: LoadedModel) -> list[str]:
        """Return all referenced members plus derived dependencies, in deterministic order."""
        ordered: list[str] = []

        def add(name: str) -> None:
            if name not in ordered:
                ordered.append(name)

        def walk(group: FilterGroup | None) -> None:
            if group is None:
                return
            for item in group.items:
                if isinstance(item, FilterLeaf):
                    add(item.member)
                else:
                    walk(item)

        metrics = {metric.name: metric for metric in loaded.model.metrics}
        prefix = f"{loaded.model.name}."

        def add_metric(name: str, seen: set[str]) -> None:
            add(name)
            metric = metrics.get(name)
            if metric is None or name in seen:
                return
            seen.add(name)
            walk(metric.filter)
            if metric.sql is not None:
                for token in _qualified_refs(metric.sql):
                    if token.startswith(prefix):
                        add_metric(token[len(prefix) :], seen)
                    else:
                        add(token)

        for name in query.metrics:
            add_metric(name, set())
        for name in query.dimensions:
            add(name)
        for dimension in query.time_dimensions:
            add(dimension.name)
        walk(query.filters)
        for order in query.order_by:
            if order.member in metrics:
                add_metric(order.member, set())
            else:
                add(order.member)
        return ordered

    @staticmethod
    def _suggest(name: str, allowed: list[str]) -> list[str]:
        ranked = sorted(allowed, key=lambda a: difflib.SequenceMatcher(None, name, a).ratio(), reverse=True)
        return ranked[:3]


def _qualified_refs(expression: str) -> list[str]:
    """Return ``model.metric`` references in a validated derived-metric expression."""

    refs: list[str] = []
    for node in ast.walk(ast.parse(expression, mode="eval")):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            refs.append(f"{node.value.id}.{node.attr}")
    return sorted(refs)
