"""LinkedSurfaceService — the ONE persistence/refresh entry point for linked surfaces (FEAT-598 S1/S2/S11).

Every save path (REST pin/save, PublishSurfaceTool, InfographicAuthoringMixin.publish_surface) and the refresh
lane delegate here. Unlike RecipeRunner (fail-open on a falsy pctx), this service FAILS CLOSED: a linked
envelope is never validated, snapshotted or refreshed without a configured data-plane guard. Note: the guard
itself fails open when navigator-auth is not installed (DataPlanePolicyGuard.authorize_source) — deployments
exposing linked surfaces must ship navigator-auth.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import BaseModel, Field

from parrot.auth.exceptions import AuthorizationRequired
from parrot.outputs.a2ui.linked import has_data_sources
from parrot.outputs.a2ui.linked.models import LinkedDataSource, LinkedSources
from parrot.outputs.a2ui.models import CreateSurface

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.permission import PermissionContext
    from parrot.outputs.a2ui.linked.executor import ExecutionOutcome

_EXT_KEY = "parrot_data_sources"


class LinkedGuardRequired(Exception):
    """A linked envelope reached persistence/refresh with no data-plane guard configured (→ HTTP 403)."""


class SnapshotError(Exception):
    """Save-time snapshot failed; nothing may be persisted. Carries the HTTP status + stable code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"linked snapshot failed: {code}")
        self.status = status
        self.code = code


class RefreshOutcome(BaseModel):
    """Result of LinkedSurfaceService.refresh — the caller persists `envelope` conditionally (S11)."""

    envelope: dict[str, Any]
    snapshot_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    error_status: int | None = None  # set only when EVERY source failed
    error_code: str | None = None


def _sources(envelope: CreateSurface | dict[str, Any]) -> dict[str, LinkedDataSource]:
    """Parse metadata.extensions.parrot_data_sources (dict or model envelope) into LinkedDataSource objects."""
    if isinstance(envelope, Mapping):
        metadata = envelope.get("metadata")
        extensions: Any = metadata.get("extensions") if isinstance(metadata, Mapping) else None
    else:
        metadata = envelope.metadata
        extensions = metadata.extensions if metadata is not None else None
        extensions = getattr(extensions, "root", extensions)
    raw = extensions.get(_EXT_KEY) if isinstance(extensions, Mapping) else None
    return LinkedSources.model_validate(raw or {}).root


class LinkedSurfaceService:
    """Validate, snapshot and refresh linked surfaces with owner context and a mandatory guard (spec §3 M5).

    Owner authorization gates every ``(tenant, slug)`` descriptor as an opaque data-plane source: resource
    identity is ``source_type="query_slug"``, ``source_id=f"{tenant or 'public'}:{slug}"`` (PBAC policies key
    on ``query_slug:<tenant|public>:<slug>`` under the existing ``source:read`` gate — confirmed by the owner,
    see TASK-3781's Codebase Contract; not ``dataset:<slug>``, no new ``slug:execute`` action).
    """

    def __init__(self, *, guard: Any | None, max_fetch_rows: int = 5000, max_snapshot_rows: int = 500) -> None:
        self.guard = guard
        self.max_fetch_rows = max_fetch_rows
        self.max_snapshot_rows = max_snapshot_rows
        self.logger = logging.getLogger(__name__)

    def _require_guard(self) -> Any:
        if self.guard is None:
            raise LinkedGuardRequired("linked surfaces require a configured data-plane guard")
        return self.guard

    async def _assert_sources_allowed(
        self, sources: Mapping[str, LinkedDataSource], owner_pctx: "PermissionContext"
    ) -> None:
        """Owner must be allowed to execute every (tenant, slug) — raises AuthorizationRequired on denial (S2)."""
        from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

        guard = self._require_guard()
        seen: set[tuple[str | None, str]] = set()
        for key, src in sources.items():
            pair = (src.tenant, src.slug)
            if pair in seen:
                continue
            seen.add(pair)
            source_id = f"{src.tenant or 'public'}:{src.slug}"
            try:
                await guard.authorize_source(
                    owner_pctx, PhysicalResources(source_type="query_slug", source_id=source_id)
                )
            except AuthorizationRequired:
                self.logger.warning("linked source %r (slug=%s, tenant=%s) denied for owner", key, src.slug, src.tenant)
                raise

    async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx: "PermissionContext") -> None:
        """No-op for baked envelopes (AC11); for linked ones: TOOL-origin validation + guard + owner check (AC14)."""
        # function-local: linked/ must never import catalog/ at module import time (spec §7 one-way rule)
        from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope

        if not has_data_sources(envelope):
            return
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)  # raises CatalogValidationError (→ 422 at caller)
        await self._assert_sources_allowed(_sources(envelope), owner_pctx)

    async def ensure_snapshot(self, envelope: dict[str, Any], *, owner_pctx: "PermissionContext") -> dict[str, Any]:
        """Execute once (owner ctx) when any target lacks rows/snapshot_at; raise SnapshotError on any failure."""
        from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources

        if not has_data_sources(envelope):
            return envelope
        sources = _sources(envelope)
        self._require_guard()
        await self._assert_sources_allowed(sources, owner_pctx)

        data_model = envelope.get("dataModel") or {}

        def _has_snapshot(key: str, src: LinkedDataSource) -> bool:
            root = data_model.get(key)
            rows = root.get("rows") if isinstance(root, Mapping) else None
            return src.snapshot_at is not None and isinstance(rows, list)

        if sources and all(_has_snapshot(key, src) for key, src in sources.items()):
            return envelope

        outcome = await execute_sources(
            sources,
            pctx=owner_pctx,
            guard=self.guard,
            max_snapshot_rows=self.max_snapshot_rows,
            max_fetch_rows=self.max_fetch_rows,
        )
        for key in sources:
            result = outcome.outcomes.get(key)
            if result is not None and result.error is not None:
                raise SnapshotError(ERROR_STATUS.get(result.error, 502), result.error)
        return _patch(copy.deepcopy(envelope), outcome)

    async def refresh(
        self, envelope: dict[str, Any], *, params: Mapping[str, Any], owner_pctx: "PermissionContext"
    ) -> RefreshOutcome:
        """Re-authorise, execute with overrides, patch successful sources; never persists (S11)."""
        from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources

        sources = _sources(envelope)
        await self._assert_sources_allowed(sources, owner_pctx)

        # `params` is the flat RefreshSurfaceRequest.params dict: a key naming a source with a mapping value is
        # that source's overrides; every other key (and any mapping-valued key that does NOT name a source) is
        # broadcast to every source (execute_sources ignores names a source does not declare / has locked).
        broadcast: dict[str, Any] = {}
        per_source: dict[str, dict[str, Any]] = {key: {} for key in sources}
        for name, value in params.items():
            if name in sources and isinstance(value, Mapping):
                per_source[name].update(value)
            else:
                broadcast[name] = value
        param_overrides = {key: {**broadcast, **per_source[key]} for key in sources}

        outcome = await execute_sources(
            sources,
            param_overrides=param_overrides,
            pctx=owner_pctx,
            guard=self.guard,
            max_snapshot_rows=self.max_snapshot_rows,
            max_fetch_rows=self.max_fetch_rows,
        )

        patched = _patch(copy.deepcopy(envelope), outcome)

        warnings: list[str] = []
        for key, result in outcome.outcomes.items():
            if result.error is not None:
                warnings.append(f"source {key}: {result.error}")
            if result.ignored_params:
                warnings.append(f"source {key}: ignored params {sorted(result.ignored_params)}")

        error_status: int | None = None
        error_code: str | None = None
        if sources and all(result.error is not None for result in outcome.outcomes.values()):
            first_key = next(iter(sources))
            first_result = outcome.outcomes[first_key]
            error_code = first_result.error
            error_status = ERROR_STATUS.get(error_code, 502)

        stamps = [result.snapshot_at for result in outcome.outcomes.values() if result.snapshot_at is not None]
        snapshot_at = max(stamps) if stamps else None

        return RefreshOutcome(
            envelope=patched,
            snapshot_at=snapshot_at,
            warnings=warnings,
            error_status=error_status,
            error_code=error_code,
        )


def _patch(envelope: dict[str, Any], outcome: "ExecutionOutcome") -> dict[str, Any]:
    """Write rows into dataModel[<root>] and stamp snapshot_at/snapshot_truncated on each successful source."""
    data_model = envelope.setdefault("dataModel", {})
    for key, patch in outcome.data_model_patch().items():
        existing = data_model.get(key)
        if isinstance(existing, Mapping):
            data_model[key] = {**existing, **patch}
        else:
            data_model[key] = patch

    metadata = envelope.get("metadata")
    extensions = metadata.get("extensions") if isinstance(metadata, Mapping) else None
    sources = extensions.get(_EXT_KEY) if isinstance(extensions, Mapping) else None
    if isinstance(sources, Mapping):
        for key, result in outcome.outcomes.items():
            if result.error is None and key in sources:
                sources[key]["snapshot_at"] = result.snapshot_at.isoformat() if result.snapshot_at else None
                sources[key]["snapshot_truncated"] = result.truncated
    return envelope
