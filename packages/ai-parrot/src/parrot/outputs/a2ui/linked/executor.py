"""Python reference executor for linked A2UI surfaces (FEAT-598 spec §3 M5).

Fetches every ``parrot_data_sources`` entry through ``QuerySlugSource`` (tenant-aware, optional FEAT-150
principal), applies the declarative DSL off the event loop and returns per-source outcomes. Never raises
for data errors: a failing source yields ``SourceOutcome(error=<stable code>)``.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Collection, Mapping

from pydantic import BaseModel, Field

from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import DerivedDataSource, Join, LinkedDataSource, LinkedSource, Pivot, Union_

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

#: ``querylimit`` of a probe execution: one row is enough to learn a source's columns and dtypes.
PROBE_FETCH_ROWS = 1


class SourceOutcome(BaseModel):
    """Result of executing one linked source."""

    key: str
    rows: list[dict[str, Any]] | None = None
    snapshot_at: datetime | None = None
    truncated: bool = False
    error: str | None = None  # stable code from map_query_error (a key of ERROR_STATUS)
    ignored_params: list[str] = Field(default_factory=list)


class ExecutionOutcome(BaseModel):
    """Outcomes of every source of one surface, keyed by dataModel root key."""

    outcomes: dict[str, SourceOutcome]
    frames: dict[str, Any] = Field(
        default_factory=dict, exclude=True
    )  # key -> transformed pd.DataFrame (in-process only,
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


def dependencies_of(src: LinkedSource) -> list[str]:
    """Sibling keys ``src`` needs before it can run: ``from`` (derived) plus ``join.with`` / ``union.sources``."""
    refs: list[str] = []
    if isinstance(src, DerivedDataSource):
        refs.append(src.from_)
    if src.transform is not None and src.transform.ops:
        for op in src.transform.ops:
            if isinstance(op, Join):
                refs.append(op.with_)
            elif isinstance(op, Union_):
                refs.extend(op.sources)
    return refs


def execution_order(sources: Mapping[str, LinkedSource]) -> tuple[list[str], dict[str, str]]:
    """Topological order (dependencies first). Returns (order, failed{key: code}).

    ``failed`` holds every key that can never run: a missing sibling reference, a (transitive) dependency on a
    failed key, or membership in a dependency cycle — each mapped to the stable ``data_stage`` code.
    """
    deps: dict[str, list[str]] = {key: dependencies_of(src) for key, src in sources.items()}

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


_execution_order = execution_order  # backward-compatible private alias (tests / TS twin docs reference it)


def _conditions_for(
    src: LinkedDataSource, overrides: Mapping[str, Any], *, max_fetch_rows: int
) -> tuple[dict[str, Any], list[str]]:
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


#: Exception class names QuerySource / asyncdb raise for a query that ran fine but matched no row.
_EMPTY_RESULT_NAMES = frozenset({"DataNotFound", "NoDataFound"})


def is_empty_result(exc: BaseException) -> bool:
    """True when ``exc`` (or a cause within ``_MAX_CAUSE_DEPTH``) is QuerySource's "no rows" signal."""
    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < _MAX_CAUSE_DEPTH and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in _EMPTY_RESULT_NAMES:
            return True
        current = current.__cause__ or current.__context__
        depth += 1
    return False


def _full_fetch_keys(sources: Mapping[str, LinkedSource]) -> set[str]:
    """Keys a probe cannot stand in for: ``pivot`` output columns depend on the data.

    A pivoting query_slug source needs its own full fetch; a pivoting ``derived`` view needs its parent's (walked up
    the ``from`` chain to the query_slug source that is actually fetched).
    """
    full: set[str] = set()
    for key, src in sources.items():
        if src.transform is None or not any(isinstance(op, Pivot) for op in src.transform.ops or []):
            continue
        current: str | None = key
        while current is not None and current in sources and current not in full:
            full.add(current)
            node = sources[current]
            current = node.from_ if isinstance(node, DerivedDataSource) else None
    return full


async def _run_source(
    key: str,
    src: LinkedSource,
    overrides: Mapping[str, Any],
    frames: Mapping[str, "pd.DataFrame"],
    *,
    sources: Mapping[str, LinkedSource],
    principal: Any,
    pctx: "PermissionContext | None",
    guard: Any | None,
    max_fetch_rows: int,
    probed: Collection[str] = (),
) -> "pd.DataFrame":
    """Produce ``key``'s frame: fetch + transform (query_slug) or transform the parent's frame (derived).

    ``overrides`` are the already-derived QuerySource conditions for a query_slug source (see
    :func:`_conditions_for`) and are unused for a derived one. ``probed`` names the sources fetched with the
    one-row probe cap: a derived view over one of them is only being validated, so the fetch-cap warning is moot.
    """
    from parrot.outputs.a2ui.linked.dsl import apply_transform

    if isinstance(src, DerivedDataSource):
        # Its base is the parent's FULL fetched frame (bounded by max_fetch_rows), never the parent's ≤500-row snapshot.
        base = frames[src.from_]
        parent = sources.get(src.from_)
        if isinstance(parent, LinkedDataSource) and src.from_ not in probed:
            cap = min(parent.request.limit or max_fetch_rows, max_fetch_rows)
            if len(base) >= cap:
                logger.warning(
                    "derived source %r aggregates a parent (%r) frame that hit its fetch cap (%d rows): the result "
                    "may be partial — aggregate in the parent's request instead",
                    key,
                    src.from_,
                    cap,
                )
        return await asyncio.to_thread(apply_transform, base, src.transform, frames=dict(frames))

    from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
    from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

    conditions = overrides
    inner = QuerySlugSource(
        src.slug,
        prefetch_schema_enabled=False,
        tenant=src.tenant,
        is_multiquery=src.is_multiquery,
        multi_output=src.multi_output,
        principal=principal,
    )
    source = AuthorizingDataSource(inner, guard, pctx_provider=lambda: pctx) if guard is not None else inner
    # Deep copy: conditions share nested filter dicts with src.request, and a data source may mutate
    # them (querysource's parsers popitem()'d operator dicts), which emptied the envelope's filter.
    frame = await source.fetch(**copy.deepcopy(conditions))
    if src.transform is not None and src.transform.ref is not None:
        logger.warning("linked source %r: ref transform %s skipped in Python", key, src.transform.ref.name)
    elif src.transform is not None:
        frame = await asyncio.to_thread(apply_transform, frame, src.transform, frames=dict(frames))
    return frame


def _describe(src: LinkedSource) -> str:
    """Short log label for a source: ``slug (tenant=…)`` or ``derived from <key>``."""
    if isinstance(src, DerivedDataSource):
        return f"derived from {src.from_!r}"
    return f"{src.slug}, tenant={src.tenant}"


async def execute_sources(
    sources: Mapping[str, LinkedSource],
    *,
    param_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pctx: "PermissionContext | None" = None,
    guard: Any | None = None,
    max_snapshot_rows: int | None = None,
    max_fetch_rows: int = 5000,
    probe: bool = False,
) -> ExecutionOutcome:
    """Fetch + transform every source (dependencies first); per-source failure isolation (spec §3 M5).

    A ``derived`` source is never fetched: it is computed from its parent's frame once the parent has run, and a
    parent failure propagates to it through :func:`execution_order` (``data_stage``).

    ``probe=True`` is the definition-only mode used by the surface builders: every query_slug source runs with
    ``querylimit=PROBE_FETCH_ROWS`` (one row) so its columns and dtypes can be validated, the transformed
    frame is kept in ``frames`` for that validation, and the outcome carries ``rows=None`` — a probe is never
    a snapshot (``data_model_patch`` skips it). ``join``/``union`` on one-row sibling frames and a derived view
    over a one-row parent keep the column set and dtypes, which is all axis validation reads; a ``pivot`` derives
    its columns from the data, so a pivoting source (or the parent of a pivoting derived view) falls back to the
    full fetch. ``ref`` transforms are skipped in Python either way. A probe that matches no row (QuerySource
    raises ``DataNotFound``, the HTTP lanes see a 204) is NOT a failure: the source — and any derived view over
    it — gets an empty, column-less frame and its axes go unvalidated (the renderer treats it as zero rows).
    """
    import pandas as pd

    from parrot.outputs.a2ui.linked.dsl import frame_to_records
    from parrot.tools.dataset_manager.sources.query_slug import to_qs_principal

    principal = to_qs_principal(pctx, channel="ui_surfaces") if pctx is not None else None  # mapped ONCE
    order, failed = execution_order(sources)
    full = _full_fetch_keys(sources) if probe else set()
    # Query-slug sources fetched with the one-row probe cap; `unvalidated` are probes that matched no row.
    probed = {k for k, v in sources.items() if probe and isinstance(v, LinkedDataSource) and k not in full}
    unvalidated: set[str] = set()
    frames: dict[str, "pd.DataFrame"] = {}
    outcomes: dict[str, SourceOutcome] = {k: SourceOutcome(key=k, error=code) for k, code in failed.items()}
    for key in order:
        src = sources[key]
        overrides = (param_overrides or {}).get(key, {})
        if isinstance(src, DerivedDataSource):
            # A derived view takes no params: every override is ignored (reported, never applied).
            conditions: dict[str, Any] = {}
            ignored = sorted(overrides)
        else:
            cap = PROBE_FETCH_ROWS if key in probed else max_fetch_rows
            conditions, ignored = _conditions_for(src, overrides, max_fetch_rows=cap)
        broken = [ref for ref in dependencies_of(src) if ref not in frames]
        if broken:
            # A dependency that was in `order` but failed at run time (fetch/transform error): never run this one,
            # and carry the dependency's own error code so the caller sees the root cause (404/503, not data_stage).
            code = next((outcomes[ref].error for ref in broken if outcomes.get(ref) and outcomes[ref].error), None)
            outcomes[key] = SourceOutcome(key=key, error=code or "data_stage", ignored_params=ignored)
            continue
        if isinstance(src, DerivedDataSource) and src.from_ in unvalidated:
            # Its parent's probe matched no row: there are no columns to transform, so it stays unvalidated too.
            unvalidated.add(key)
            frames[key] = pd.DataFrame()
            outcomes[key] = SourceOutcome(key=key, ignored_params=ignored)
            continue
        try:
            frame = await _run_source(
                key,
                src,
                conditions,
                frames,
                sources=sources,
                principal=principal,
                pctx=pctx,
                guard=guard,
                max_fetch_rows=max_fetch_rows,
                probed=probed,
            )
        except Exception as exc:  # noqa: BLE001 — data errors never fail siblings
            if probe and is_empty_result(exc):
                logger.warning(
                    "linked source %r (%s): probe matched no row; columns left unvalidated", key, _describe(src)
                )
                unvalidated.add(key)
                frames[key] = pd.DataFrame()
                outcomes[key] = SourceOutcome(key=key, ignored_params=ignored)
                continue
            status, code = map_query_error(exc)
            logger.warning("linked source %r (%s) failed: %s → %s", key, _describe(src), exc, status)
            outcomes[key] = SourceOutcome(key=key, error=code, ignored_params=ignored)
            continue
        frames[key] = frame
        if probe:
            outcomes[key] = SourceOutcome(key=key, ignored_params=ignored)
            continue
        rows = frame_to_records(frame)
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
