"""Slug catalog over public.queries with explicit tenant checks (spec §3 M4)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any

from asyncdb import AsyncDB  # verified: parrot_tools/querytoolkit.py:18
from asyncdb.exceptions import NoDataFound  # verified: real "no such row" signal from QueryModel.get/filter

from parrot_tools.querysource import _qs
from parrot_tools.querysource.errors import (
    InvalidConditionsError,
    QuerysourceToolkitError,
    SlugNotFoundError,
    TenantDeniedError,
)
from parrot_tools.querysource.models import SavedSlug

logger = logging.getLogger(__name__)
_PIPELINE_KEYS = ("queries", "files", "sources")  # multi/__init__.py:182-183


def _not_found_exception_types() -> tuple[type[BaseException], ...]:
    """Real "no such row" signals only: asyncdb's NoDataFound, plus querysource's SlugNotFound when the
    optional dependency is importable. Never widen this to a bare Exception — a connection drop, auth
    failure or driver bug must propagate as itself, not be misreported to the agent as a missing slug."""
    types: list[type[BaseException]] = [NoDataFound]
    try:
        types.append(_qs.get_exceptions().SlugNotFound)
    except ImportError:
        pass
    return tuple(types)


def _tenant_error_to_toolkit(exc: Any, *, slug: str, tenant: str) -> QuerysourceToolkitError:
    """Map querysource TenantError.error_code to the toolkit hierarchy (messages written for the LLM)."""
    code = getattr(exc, "error_code", None)
    if code in ("query_not_found", "tenant_not_available"):
        return SlugNotFoundError(f"slug '{slug}' not found for tenant '{tenant}'")
    if code == "invalid_tenant":
        return InvalidConditionsError(f"invalid tenant request for '{tenant}': {exc}")
    return QuerysourceToolkitError(f"tenant '{tenant}' store error ({code}): {exc}")


def _store_record(row: Any, store: Any) -> "SlugRecord":
    """Build a SlugRecord from a runtime QueryModel or a DefinitionPage Mapping row of ``store``."""
    if isinstance(row, Mapping):
        row = SimpleNamespace(**dict(row))
    record = SlugRecord.from_row(row)
    if getattr(store, "contract", None) == "tenant":
        record = replace(record, program_slug=store.schema)
    return record


@dataclass(frozen=True)
class SlugRecord:
    """Redacted view of one public.queries row (never source/params/attributes/dwh_*/cache_options)."""

    slug: str
    program_slug: str
    description: str | None
    provider: str
    is_cached: bool
    cache_timeout: int
    conditions: dict[str, Any] = field(default_factory=dict)
    cond_definition: dict[str, Any] = field(default_factory=dict)
    filtering: dict[str, Any] = field(default_factory=dict)
    fields: list[str] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    grouping: list[str] = field(default_factory=list)
    query_raw: str | None = None
    pipeline: dict[str, Any] | None = None

    @property
    def is_multiquery(self) -> bool:
        """True when query_raw parsed to a dict holding queries|files|sources."""
        return self.pipeline is not None

    @property
    def placeholder_names(self) -> list[str]:
        """keys(cond_definition) ∪ keys(conditions), sorted."""
        return sorted(set(self.cond_definition) | set(self.conditions))

    @classmethod
    def from_row(cls, row: Any) -> "SlugRecord":
        """Build from a QueryModel instance (attribute access; columns verified models.py:49-81)."""
        raw = getattr(row, "query_raw", None)
        pipeline = None
        if isinstance(raw, str) and raw.lstrip().startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and any(k in parsed for k in _PIPELINE_KEYS):
                    pipeline = parsed
            except ValueError:
                pipeline = None
        return cls(
            slug=row.query_slug,
            program_slug=getattr(row, "program_slug", "default"),
            description=getattr(row, "description", None),
            provider=getattr(row, "provider", "db"),
            is_cached=bool(getattr(row, "is_cached", True)),
            cache_timeout=int(getattr(row, "cache_timeout", 3600) or 0),
            conditions=dict(getattr(row, "conditions", None) or {}),
            cond_definition=dict(getattr(row, "cond_definition", None) or {}),
            filtering=dict(getattr(row, "filtering", None) or {}),
            fields=list(getattr(row, "fields", None) or []),
            ordering=list(getattr(row, "ordering", None) or []),
            grouping=list(getattr(row, "grouping", None) or []),
            query_raw=raw,
            pipeline=pipeline,
        )


class TenantGuard:
    """Allowlist of program_slug values; None means unrestricted (proposal U4)."""

    def __init__(self, programs: list[str] | None) -> None:
        self.programs: tuple[str, ...] | None = tuple(programs) if programs is not None else None

    @property
    def restricted(self) -> bool:
        return self.programs is not None

    def assert_allowed(self, record: SlugRecord) -> None:
        """Raise TenantDeniedError when restricted and record.program_slug ∉ programs."""
        if self.restricted and record.program_slug not in self.programs:
            raise TenantDeniedError(f"slug '{record.slug}' is not available for programs {list(self.programs)}")

    def resolve_write_program(self, requested: str | None) -> str:
        """Program a save must use (S5): explicit ∈ allowlist; single-program default; else error."""
        if self.restricted:
            if requested is not None:
                if requested not in self.programs:
                    raise QuerysourceToolkitError(
                        f"program '{requested}' is not in the allowed programs {list(self.programs)}"
                    )
                return requested
            if len(self.programs) == 1:
                return self.programs[0]
            raise QuerysourceToolkitError(
                f"program is required: this toolkit is restricted to multiple programs {list(self.programs)}"
            )
        if requested is not None:
            return requested
        raise QuerysourceToolkitError("program is required when the toolkit is unrestricted")


class SlugCatalog:
    """Reads/writes public.queries through QueryModel with a per-call connection (S1); no auth cache (S2)."""

    def __init__(self, dsn: str, guard: TenantGuard) -> None:
        self._dsn = dsn
        self.guard = guard
        self._db: AsyncDB | None = None

    async def open(self) -> None:
        """Create the AsyncDB('pg') factory lazily (pattern: connections.py:113-130)."""
        if self._db is None:
            self._db = AsyncDB("pg", dsn=self._dsn)

    async def close(self) -> None:
        if self._db is not None and hasattr(self._db, "close"):
            await self._db.close()
        self._db = None

    async def get(self, slug: str, *, tenant: str | None = None) -> SlugRecord:
        """Load one definition; SlugNotFoundError when absent. Always hits the store (S2).

        ``tenant=None`` reads ``public.queries`` through QueryModel (FEAT-558 path, unchanged).
        A set ``tenant`` resolves through QuerySource's DefinitionRepository exactly like
        ``TenantQueryHandler._prepare`` (querysource handlers/tenant.py:198-212) and never falls back to public.
        """
        if tenant is not None:
            return await self._get_tenant(slug, tenant)
        await self.open()
        model = _qs.get_query_model()
        logger.debug("catalog.get %s", slug)
        async with await self._db.connection() as conn:  # connections.py:459
            try:
                row = await model.get(query_slug=slug, _connection=conn)  # connections.py:463
            except _not_found_exception_types() as exc:  # asyncdb NoDataFound / querysource SlugNotFound only
                raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        return SlugRecord.from_row(row)

    async def _get_tenant(self, slug: str, tenant: str) -> SlugRecord:
        """repo.registry.resolve(tenant) → repo.get(QueryIdentity(store, slug)) → SlugRecord (program_slug == schema)."""
        tenants = _qs.get_tenants()
        repo = await _qs.get_definition_repository()
        logger.debug("catalog.get %s tenant=%s", slug, tenant)
        try:
            store = repo.registry.resolve(tenant)
            definition = await repo.get(tenants.QueryIdentity(store=store, slug=slug))
        except tenants.TenantError as exc:
            raise _tenant_error_to_toolkit(exc, slug=slug, tenant=tenant) from exc
        return _store_record(definition.runtime, store)

    async def get_allowed(self, slug: str, *, tenant: str | None = None) -> SlugRecord:
        """get() then guard.assert_allowed() — unchanged rule, now tenant-aware."""
        record = await self.get(slug, tenant=tenant)
        self.guard.assert_allowed(record)
        return record

    async def list(
        self, *, search: str | None, program: str | None, limit: int, tenant: str | None = None
    ) -> list[SlugRecord]:
        """tenant=None: existing QueryModel path over public.queries; tenant set: repo.list(store, params)."""
        if tenant is not None:
            return await self._list_tenant(search=search, program=program, limit=limit, tenant=tenant)
        await self.open()
        model = _qs.get_query_model()
        async with await self._db.connection() as conn:
            if program is not None:
                if self.guard.restricted and program not in self.guard.programs:
                    raise TenantDeniedError(
                        f"program '{program}' is not in the allowed programs {list(self.guard.programs)}"
                    )
                programs: list[str] | None = [program]
            elif self.guard.restricted:
                programs = list(self.guard.programs)
            else:
                programs = None
            rows: list[Any] = []
            if programs is None:
                rows = list(await model.all(_connection=conn))
            else:
                for prog in programs:
                    rows.extend(await model.filter(program_slug=prog, _connection=conn))
        records = [SlugRecord.from_row(r) for r in rows]
        if search:
            needle = search.lower()
            records = [r for r in records if needle in r.slug.lower() or needle in (r.description or "").lower()]
        return sorted(records, key=lambda r: r.slug)[:limit]

    async def _list_tenant(
        self, *, search: str | None, program: str | None, limit: int, tenant: str
    ) -> list[SlugRecord]:
        """List one tenant store's definitions; program filter/allowlist evaluated against program_slug == schema."""
        tenants = _qs.get_tenants()
        repo = await _qs.get_definition_repository()
        try:
            store = repo.registry.resolve(tenant)
            page = await repo.list(store, {"page": 1, "page_size": 200})  # _MAX_PAGE_SIZE (definitions.py:34)
        except tenants.TenantError as exc:
            raise _tenant_error_to_toolkit(exc, slug="*", tenant=tenant) from exc
        records = [_store_record(row, store) for row in page.rows]
        if program is not None:
            if self.guard.restricted and program not in self.guard.programs:
                raise TenantDeniedError(
                    f"program '{program}' is not in the allowed programs {list(self.guard.programs)}"
                )
            records = [r for r in records if r.program_slug == program]
        elif self.guard.restricted:
            records = [r for r in records if r.program_slug in self.guard.programs]
        if search:
            needle = search.lower()
            records = [r for r in records if needle in r.slug.lower() or needle in (r.description or "").lower()]
        return sorted(records, key=lambda r: r.slug)[:limit]

    async def list_programs(self) -> list[str]:
        """Distinct ``program_slug`` values across the catalog, sorted (FEAT-593).

        Not filtered by ``TenantGuard``: the operator is choosing the scope itself.
        """
        await self.open()
        model = _qs.get_query_model()
        async with await self._db.connection() as conn:
            rows = await model.all(_connection=conn)
        return sorted({row.program_slug for row in rows})

    async def upsert(
        self, *, slug: str, description: str, pipeline: dict[str, Any], program_slug: str, overwrite: bool
    ) -> SavedSlug:
        """Insert or (guarded) update a multi-query row: query_raw=json, is_cached=False (S5 ownership check)."""
        await self.open()
        model = _qs.get_query_model()
        async with await self._db.connection() as conn:
            try:
                existing = await model.get(query_slug=slug, _connection=conn)
            except _not_found_exception_types():  # asyncdb NoDataFound / querysource SlugNotFound → "insert"
                existing = None
            if existing is not None:
                if not overwrite:
                    raise QuerysourceToolkitError(f"slug '{slug}' already exists; pass overwrite=True to replace it")
                existing_program = getattr(existing, "program_slug", None)
                if existing_program != program_slug:
                    raise QuerysourceToolkitError(
                        f"slug '{slug}' is owned by program '{existing_program}', not '{program_slug}'"
                    )
                existing.query_raw = json.dumps(pipeline)
                existing.description = description
                await existing.update(_connection=conn)
                action = "updated"
            else:
                row = model(
                    query_slug=slug,
                    description=description,
                    query_raw=json.dumps(pipeline),
                    program_slug=program_slug,
                    is_cached=False,
                )
                await row.insert(_connection=conn)
                action = "inserted"
        logger.info("catalog.upsert %s (%s) program=%s", slug, action, program_slug)
        return SavedSlug(slug=slug, program_slug=program_slug, action=action)


_SECTION_KEYS = ("queries", "files", "sources", "Output")
_RAW_NODE_KEYS = ("query", "raw_query")


@dataclass
class NormalizedPipeline:
    """Flat view of a MultiQS pipeline dict (design research S6)."""

    slug_nodes: dict[str, str]  # node name → slug
    raw_nodes: list[str]  # node names carrying query/raw_query
    has_files: bool
    has_sources: bool
    step_names: list[str]  # top-level keys other than queries/files/sources/Output
    output_steps: list[str]  # step names inside Output (transformations + destinations)


def normalize_pipeline(pipeline: dict[str, Any]) -> NormalizedPipeline:
    """Walk the MultiQS shape (multi/__init__.py:95-97,443; obj.py:49-63); raise InvalidConditionsError when malformed."""
    if not isinstance(pipeline, dict):
        raise InvalidConditionsError("pipeline must be a JSON object")
    queries = pipeline.get("queries", {})
    if not isinstance(queries, dict):
        raise InvalidConditionsError("'queries' must be a mapping of node name → {slug | query}")
    slug_nodes: dict[str, str] = {}
    raw_nodes: list[str] = []
    for name, node in queries.items():
        if not isinstance(node, dict):
            raise InvalidConditionsError(f"query node '{name}' must be an object")
        # A node with any raw key is treated as raw even alongside 'slug' (fail closed against tenancy bypass).
        if any(key in node for key in _RAW_NODE_KEYS):
            raw_nodes.append(name)
        else:
            slug_nodes[name] = node.get("slug", name)  # ThreadQuery.slug default (sources/query.py:62)
    files = pipeline.get("files") or {}
    sources = pipeline.get("sources") or []
    output = pipeline.get("Output") or []
    if not isinstance(output, list) or any(not isinstance(step, dict) or len(step) != 1 for step in output):
        raise InvalidConditionsError("'Output' must be a list of single-key step objects")
    return NormalizedPipeline(
        slug_nodes=slug_nodes,
        raw_nodes=raw_nodes,
        has_files=bool(files),
        has_sources=bool(sources),
        step_names=[k for k in pipeline if k not in _SECTION_KEYS],
        output_steps=[next(iter(step)) for step in output],
    )
