"""DatasetManager source backed by one governed semantic model (FEAT-880)."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from parrot.auth import PermissionContext
from parrot.auth.context import _pctx_var
from parrot.tools.dataset_manager.sources.base import DataSource

from .context import bind_semantic_context, current_pctx
from .errors import SemanticAccessError, SemanticPolicyError, SemanticValidationError
from .governance.pipeline import subject_digest
from .models import SemanticQuery
from .toolkit import SemanticLayerToolkit

QUERY_FIELDS: frozenset[str] = frozenset(
    {"metrics", "dimensions", "time_dimensions", "filters", "order_by", "limit", "offset", "saved_query"}
)


class SemanticDataSource(DataSource):
    """Dataset source backed by one governed semantic model."""

    def __init__(self, *, name: str, toolkit: SemanticLayerToolkit, model: str,
                 default_query: dict[str, Any] | None = None, description: str | None = None,
                 routing_meta: dict | None = None) -> None:
        """Bind ``model`` of ``toolkit``.

        Raises:
            SemanticPolicyError: ``model_not_found`` / ``invalid_default_query``.
        """
        super().__init__(routing_meta=routing_meta)
        if model not in toolkit._models:
            raise SemanticPolicyError("model_not_found", "Unknown semantic model", details={"model": model})
        if default_query and set(default_query) - QUERY_FIELDS:
            raise SemanticPolicyError("invalid_default_query", "default_query has unsupported keys")
        self.name = name
        self.toolkit = toolkit
        self.model = model
        self.default_query = dict(default_query or {})
        self.description = description

    @classmethod
    def from_models_dir(cls, *, name: str, model: str, models_dir: Path, dialect: str,
                        default_query: dict[str, Any] | None = None, description: str | None = None,
                        **toolkit_kwargs: Any) -> "SemanticDataSource":
        """Build a SemanticLayerToolkit and bind ``model``; toolkit errors propagate unchanged."""
        toolkit = SemanticLayerToolkit(models_dir=Path(models_dir), dialect=dialect, **toolkit_kwargs)
        return cls(name=name, toolkit=toolkit, model=model, default_query=default_query, description=description)

    @property
    def self_governed(self) -> bool:
        """Always True: the semantic layer governs access itself."""
        return True

    @property
    def has_builtin_cache(self) -> bool:
        """Always True: DatasetManager must not cache these rows."""
        return True

    @property
    def cache_key(self) -> str:
        """Identifier only; never a cache key for rows."""
        return f"semantic:{self.toolkit._dialect}:{self.model}:{self.name}"

    def describe(self) -> str:
        """Return static text describing how to query this source."""
        return (
            f"Governed semantic model '{self.model}'. Pass the query through fetch_dataset `conditions` "
            f"using the fields: {', '.join(sorted(QUERY_FIELDS))}. Discover the available metrics and "
            "dimensions with the semantic catalog tools; visibility depends on the caller's role."
        )

    async def prefetch_schema(self) -> dict[str, str]:
        """Return ``{}``: visible members depend on the caller's role."""
        return {}

    def _resolve_context(self) -> tuple[PermissionContext, bool]:
        """Return (context, bridged) or raise SemanticAccessError('context_required')."""
        semantic = current_pctx()
        core = _pctx_var.get(None)
        if semantic is not None and core is not None:
            if semantic != core:
                raise SemanticAccessError("context_required", "Semantic and core contexts disagree")
            return semantic, False
        if semantic is not None:
            return semantic, False
        if core is not None and isinstance(core, PermissionContext):
            return core, True
        raise SemanticAccessError("context_required", "A trusted permission context is required")

    def current_owner(self) -> str | None:
        """Return the subject digest of the resolved context, or None; never raises."""
        try:
            context, _ = self._resolve_context()
        except SemanticAccessError:
            return None
        return subject_digest(context)

    async def fetch(self, **params: Any) -> pd.DataFrame:
        """Run one governed semantic query and return its rows (see spec §3 M4 for errors)."""
        params.pop("force_refresh", None)
        context, bridged = self._resolve_context()
        if "model" in params or set(params) - QUERY_FIELDS:
            raise SemanticValidationError("invalid_params", "Unsupported query parameters")
        query_params = params or self.default_query
        if not query_params:
            raise SemanticValidationError("query_required", "A semantic query is required")
        try:
            query = SemanticQuery(model=self.model, **query_params)
        except ValidationError as exc:
            raise SemanticValidationError("invalid_query", "Invalid semantic query") from exc
        scope = bind_semantic_context(context) if bridged else contextlib.nullcontext()
        async with scope:
            result = await self.toolkit.query_metrics(query)
        frame = pd.DataFrame(result.rows, columns=result.columns)
        frame.attrs["semantic"] = {"model": self.model, "audit_id": result.audit_id,
                                   "truncated": result.truncated, "row_count": result.row_count}
        return frame
