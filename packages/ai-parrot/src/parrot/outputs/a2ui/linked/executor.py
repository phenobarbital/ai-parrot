"""Python reference executor for linked A2UI surfaces (FEAT-598 spec §3 M5).

Fetches every ``parrot_data_sources`` entry through ``QuerySlugSource`` (tenant-aware, optional FEAT-150
principal), applies the declarative DSL off the event loop and returns per-source outcomes. Never raises
for data errors: a failing source yields ``SourceOutcome(error=<stable code>)``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import BaseModel, Field

from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import Join, LinkedDataSource, Union_

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd
    from parrot.auth.permission import PermissionContext

logger = logging.getLogger(__name__)

ERROR_STATUS: dict[str, int] = {
    "query_not_found": 404,
    "tenant_not_available": 404,
    "tenant_store_unavailable": 503,
    "data_stage": 502,
}

#: TenantError.error_code -> (http_status, code); anything else -> (502, "data_stage") (spec §3 M5 table).
_TENANT_CODE_MAP: dict[str, tuple[int, str]] = {
    "tenant_not_available": (404, "tenant_not_available"),
    "query_not_found": (404, "query_not_found"),
    "tenant_store_unavailable": (503, "tenant_store_unavailable"),
}

#: Bounded walk of exc -> __cause__ -> __context__ (TASK-3779 chains errors as RuntimeError(...) from error).
_MAX_CAUSE_DEPTH = 5


class SourceOutcome(BaseModel):
    """Result of executing one linked source."""

    key: str
    rows: list[dict[str, Any]] | None = None
    snapshot_at: datetime | None = None
    truncated: bool = False
    error: str | None = None          # stable code from map_query_error (a key of ERROR_STATUS)
    ignored_params: list[str] = Field(default_factory=list)


class ExecutionOutcome(BaseModel):
    """Outcomes of every source of one surface, keyed by dataModel root key."""

    outcomes: dict[str, SourceOutcome]
    frames: dict[str, Any] = Field(default_factory=dict, exclude=True)  # key -> transformed pd.DataFrame (in-process only,
    #                                                                     never serialised); TASK-3785 hands these to
    #                                                                     build_linked_surface for dtype-aware axis checks

    def data_model_patch(self) -> dict[str, Any]:
        """``{root_key: {"rows": [...]}}`` for successful sources only (failed sources keep their old snapshot)."""
        return {key: {"rows": o.rows} for key, o in self.outcomes.items() if o.error is None and o.rows is not None}


def map_query_error(exc: BaseException) -> tuple[int, str]:
    """Map a fetch exception to ``(http_status, code)`` (spec §3 M5 table; walks __cause__/__context__)."""
    try:
        from querysource.exceptions import QueryAccessDenied
        from querysource.tenants import TenantError
    except ImportError:  # querysource absent → generic data-stage failure
        return 502, "data_stage"

    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < _MAX_CAUSE_DEPTH and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, QueryAccessDenied):
            # FEAT-150: a "missing" or "denied" principal both collapse to the same not-found code.
            return 404, "query_not_found"
        if isinstance(current, TenantError):
            mapped = _TENANT_CODE_MAP.get(current.error_code)
            if mapped is not None:
                return mapped
            return 502, "data_stage"
        current = current.__cause__ or current.__context__
        depth += 1
    return 502, "data_stage"


def _execution_order(sources: Mapping[str, LinkedDataSource]) -> tuple[list[str], dict[str, str]]:
    """Topological order (join.with / union.sources first). Returns (order, failed{key: code})."""
    deps: dict[str, list[str]] = {}
    for key, src in sources.items():
        refs: list[str] = []
        if src.transform is not None and src.transform.ops:
            for op in src.transform.ops:
                if isinstance(op, Join):
                    refs.append(op.with_)
                elif isinstance(op, Union_):
                    refs.extend(op.sources)
        deps[key] = refs

    failed: dict[str, str] = {}
    for key, refs in deps.items():
        if any(ref not in sources for ref in refs):
            failed[key] = "data_stage"

    # Propagate failure to any (transitive) dependent of an already-failed sibling.
    changed = True
    while changed:
        changed = False
        for key, refs in deps.items():
            if key in failed:
                continue
            if any(ref in failed for ref in refs):
                failed[key] = "data_stage"
                changed = True

    # Kahn's algorithm (stable insertion order) over the remaining, non-failed sources.
    pending = [key for key in sources if key not in failed]
    indegree = {key: sum(1 for ref in deps[key] if ref not in failed) for key in pending}
    dependents: dict[str, list[str]] = {key: [] for key in pending}
    for key in pending:
        for ref in deps[key]:
            if ref in dependents:
                dependents[ref].append(key)

    order: list[str] = []
    ready = [key for key in pending if indegree[key] == 0]
    while ready:
        ready.sort(key=pending.index)  # stable: earliest-inserted ready key first
        key = ready.pop(0)
        order.append(key)
        for dep in dependents[key]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)

    for key in pending:
        if key not in order:
            failed[key] = "data_stage"  # part of a cycle

    return order, failed


def _conditions_for(src: LinkedDataSource, overrides: Mapping[str, Any], *,
                    max_fetch_rows: int) -> tuple[dict[str, Any], list[str]]:
    """derive_conditions(request, locked) with non-locked overrides + {'querylimit': min(request.limit or cap, cap)}.

    ``derive_conditions`` never emits ``limit`` (TASK-3770: ``build_conditions`` folds it into the lane-time ``querylimit``),
    so the executor re-applies ``request.limit`` here, bounded by ``max_fetch_rows`` (S8/AC17).
    """
    locked_values = {k: src.conditions[k] for k in src.locked if k in src.conditions}
    ignored = sorted(k for k in overrides if k in src.locked)
    allowed = {k: v for k, v in overrides.items() if k not in src.locked}
    # Conditions are always DERIVED from request (S5): fold declared, non-locked overrides into
    # request.placeholders; names not declared in src.params are ALSO ignored (never hand-merged in).
    declared = {k: v for k, v in allowed.items() if k in src.params}
    not_declared = [k for k in allowed if k not in src.params]
    if not_declared:
        ignored = sorted(set(ignored) | set(not_declared))
    request = (
        src.request.model_copy(update={"placeholders": {**src.request.placeholders, **declared}})
        if declared
        else src.request
    )
    conditions = derive_conditions(request, locked=locked_values)
    conditions["querylimit"] = min(request.limit or max_fetch_rows, max_fetch_rows)  # S8: QuerySource caps the fetch
    return conditions, ignored


async def execute_sources(
    sources: Mapping[str, LinkedDataSource],
    *,
    param_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pctx: "PermissionContext | None" = None,
    guard: Any | None = None,
    max_snapshot_rows: int | None = None,
    max_fetch_rows: int = 5000,
) -> ExecutionOutcome:
    """Fetch + transform every source (siblings first); per-source failure isolation (spec §3 M5)."""
    from parrot.outputs.a2ui.linked.dsl import apply_transform
    from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
    from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, to_qs_principal

    principal = to_qs_principal(pctx, channel="ui_surfaces") if pctx is not None else None  # mapped ONCE
    order, failed = _execution_order(sources)
    frames: dict[str, "pd.DataFrame"] = {}
    outcomes: dict[str, SourceOutcome] = {k: SourceOutcome(key=k, error=code) for k, code in failed.items()}
    for key in order:
        src = sources[key]
        conditions, ignored = _conditions_for(src, (param_overrides or {}).get(key, {}), max_fetch_rows=max_fetch_rows)
        inner = QuerySlugSource(src.slug, prefetch_schema_enabled=False, tenant=src.tenant,
                                is_multiquery=src.is_multiquery, multi_output=src.multi_output, principal=principal)
        source = AuthorizingDataSource(inner, guard, pctx_provider=lambda: pctx) if guard is not None else inner
        try:
            frame = await source.fetch(**conditions)
            if src.transform is not None and src.transform.ref is not None:
                logger.warning("linked source %r: ref transform %s skipped in Python", key, src.transform.ref.name)
            elif src.transform is not None:
                frame = await asyncio.to_thread(apply_transform, frame, src.transform, frames=dict(frames))
        except Exception as exc:  # noqa: BLE001 — data errors never fail siblings
            status, code = map_query_error(exc)
            logger.warning("linked source %r (%s, tenant=%s) failed: %s → %s", key, src.slug, src.tenant, exc, status)
            outcomes[key] = SourceOutcome(key=key, error=code, ignored_params=ignored)
            continue
        frames[key] = frame
        rows = json.loads(frame.to_json(orient="records", date_format="iso"))
        truncated = False
        if max_snapshot_rows is not None and len(rows) > max_snapshot_rows:
            rows = rows[:max_snapshot_rows]
            truncated = True
        outcomes[key] = SourceOutcome(
            key=key,
            rows=rows,
            snapshot_at=datetime.now(timezone.utc),
            truncated=truncated,
            ignored_params=ignored,
        )
    return ExecutionOutcome(outcomes=outcomes, frames=frames)
