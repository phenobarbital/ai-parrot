"""Slug catalog over public.queries with explicit tenant checks (spec §3 M4)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from asyncdb import AsyncDB  # verified: parrot_tools/querytoolkit.py:18

from parrot_tools.querysource import _qs
from parrot_tools.querysource.errors import QuerysourceToolkitError, SlugNotFoundError, TenantDeniedError
from parrot_tools.querysource.models import SavedSlug

logger = logging.getLogger(__name__)
_PIPELINE_KEYS = ("queries", "files", "sources")  # multi/__init__.py:182-183


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

    async def get(self, slug: str) -> SlugRecord:
        """Load one row; SlugNotFoundError when absent. Always hits the DB (S2)."""
        await self.open()
        model = _qs.get_query_model()
        logger.debug("catalog.get %s", slug)
        async with await self._db.connection() as conn:  # connections.py:459
            try:
                row = await model.get(query_slug=slug, _connection=conn)  # connections.py:463
            except Exception as exc:  # asyncdb NoDataFound / querysource SlugNotFound / any not-found signal
                raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        return SlugRecord.from_row(row)

    async def get_allowed(self, slug: str) -> SlugRecord:
        """get() then guard.assert_allowed()."""
        record = await self.get(slug)
        self.guard.assert_allowed(record)
        return record

    async def list(self, *, search: str | None, program: str | None, limit: int) -> list[SlugRecord]:
        """QueryModel.filter(program_slug=p) per allowed program (or all() when unrestricted and program is None)."""
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

    async def upsert(self, *, slug: str, description: str, pipeline: dict[str, Any], program_slug: str,
                     overwrite: bool) -> SavedSlug:
        """Insert or (guarded) update a multi-query row: query_raw=json, is_cached=False (S5 ownership check)."""
        await self.open()
        model = _qs.get_query_model()
        async with await self._db.connection() as conn:
            try:
                existing = await model.get(query_slug=slug, _connection=conn)
            except Exception:  # noqa: BLE001 — absent slug: any not-found signal means "insert"
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
                row = model(query_slug=slug, description=description, query_raw=json.dumps(pipeline),
                           program_slug=program_slug, is_cached=False)
                await row.insert(_connection=conn)
                action = "inserted"
        logger.info("catalog.upsert %s (%s) program=%s", slug, action, program_slug)
        return SavedSlug(slug=slug, program_slug=program_slug, action=action)
