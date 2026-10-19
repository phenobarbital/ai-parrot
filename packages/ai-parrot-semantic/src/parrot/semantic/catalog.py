"""Role-filtered catalog, member-right checks and saved-query expansion (spec §3 Module 7)."""

from __future__ import annotations

import difflib
import logging

from .errors import SemanticAccessError, SemanticValidationError
from .loader import LoadedModel
from .models import FilterGroup, FilterLeaf, ModelMember, SemanticQuery


class RoleCatalog:
    """Role-filtered view of loaded semantic models.

    Args:
        models: Loaded models keyed by model name.
    """

    def __init__(self, models: dict[str, LoadedModel]) -> None:
        """Initialize the catalog over ``models``."""
        self.models = models
        self.logger = logging.getLogger(__name__)

    def _model(self, model: str) -> LoadedModel:
        """Return a loaded model or raise a validation error for an unknown name."""
        loaded = self.models.get(model)
        if loaded is None:
            raise SemanticValidationError("unknown_model", details={"model": model})
        return loaded

    @staticmethod
    def _projection_hidden(loaded: LoadedModel, roles: frozenset[str]) -> set[str]:
        """Return member names whose mask forbids projection for ``roles``."""
        hidden: set[str] = set()
        for column in loaded.policy.masks:
            if loaded.policy.mask_for(roles, column) is not None:
                hidden.add(column.rpartition(".")[2])
        return hidden

    def _allowed_names(self, loaded: LoadedModel, roles: frozenset[str]) -> set[str]:
        """Return the member names ``roles`` may reference in ``loaded``."""
        if not loaded.policy.governed:
            return {member.name for member in loaded.members}
        allowed = loaded.policy.allowed_members(roles, loaded.members)
        return allowed - self._projection_hidden(loaded, roles)

    def visible_members(self, model: str, roles: frozenset[str], *, authorized: bool) -> list[ModelMember]:
        """Allowed members only; a governed model with authorized=False exposes nothing (not even names).

        Args:
            model: Model name.
            roles: Subject roles.
            authorized: Whether the subject passed the PBAC manifest check.

        Returns:
            Members the subject may see, in model order.
        """
        loaded = self._model(model)
        if not loaded.policy.governed:
            return list(loaded.members)
        if not authorized:
            return []
        allowed = self._allowed_names(loaded, roles)
        return [member for member in loaded.members if member.name in allowed]

    def check_query_rights(self, query: SemanticQuery, roles: frozenset[str]) -> None:
        """Every metric/dimension/time-dimension/filter/order member must be allowed.

        Raises:
            SemanticAccessError: ``member_not_granted`` with up to three suggestions among allowed members.
        """
        loaded = self._model(query.model)
        allowed = self._allowed_names(loaded, roles)
        referenced = [*query.metrics, *query.dimensions]
        referenced.extend(item.name for item in query.time_dimensions)
        if query.filters is not None:
            referenced.extend(_walk_filters(query.filters))
        referenced.extend(item.member for item in query.order_by)
        for name in referenced:
            if name not in allowed:
                raise SemanticAccessError(
                    "member_not_granted",
                    details={"member": name, "suggestions": self._suggest(name, sorted(allowed))},
                )

    def expand_saved_query(self, query: SemanticQuery) -> SemanticQuery:
        """Replace `saved_query` with the stored query (same model); unknown name -> SemanticValidationError."""
        if not query.saved_query:
            return query
        loaded = self._model(query.model)
        for saved in loaded.policy.saved_queries:
            if saved.name == query.saved_query:
                stored = saved.query
                if stored.model != query.model:
                    raise SemanticValidationError("unknown_saved_query", details={"saved_query": query.saved_query})
                updates: dict[str, object] = {}
                if query.limit is not None:
                    updates["limit"] = query.limit
                if query.offset:
                    updates["offset"] = query.offset
                expanded = stored.model_copy(update=updates, deep=True)
                if expanded.offset > 0 and not expanded.order_by:
                    raise SemanticValidationError("offset_requires_order_by")
                return expanded
        raise SemanticValidationError("unknown_saved_query", details={"saved_query": query.saved_query})

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
        needle = text.lower()
        names = [model] if model is not None else sorted(self.models)
        hits: list[tuple[float, dict]] = []
        for name in names:
            if name not in self.models:
                continue
            for member in self.visible_members(name, roles, authorized=authorized.get(name, False)):
                haystack = f"{member.name} {member.description}".lower()
                ratio = difflib.SequenceMatcher(None, needle, member.name.lower()).ratio()
                if needle in haystack or ratio >= 0.6:
                    score = ratio + (1.0 if needle in haystack else 0.0)
                    hits.append(
                        (
                            score,
                            {
                                "model": name,
                                "name": member.name,
                                "kind": member.kind,
                                "description": member.description,
                            },
                        )
                    )
        hits.sort(key=lambda hit: hit[0], reverse=True)
        return [hit for _, hit in hits]

    @staticmethod
    def _suggest(name: str, allowed: list[str]) -> list[str]:
        """Return the top three allowed names by difflib similarity to ``name``."""
        ranked = sorted(allowed, key=lambda a: difflib.SequenceMatcher(None, name, a).ratio(), reverse=True)
        return ranked[:3]


def _walk_filters(group: FilterGroup) -> list[str]:
    """Collect member names from a recursive filter group."""
    names: list[str] = []
    for item in group.items:
        if isinstance(item, FilterLeaf):
            names.append(item.member)
        else:
            names.extend(_walk_filters(item))
    return names
