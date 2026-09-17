"""QuerysourceToolkit — tenant-scoped QuerySource tools for agents (spec FEAT-558 §3 M5/M6).

Generated tool names (tool_prefix 'qs'): qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug,
qs_list_components, qs_validate_pipeline, qs_run_multiquery and — only when allow_write=True — qs_save_multiquery.
"""
from __future__ import annotations

import time
from typing import Any

from parrot.tools.toolkit import AbstractToolkit  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206

from parrot_tools.querysource import _qs
from parrot_tools.querysource.catalog import SlugCatalog, SlugRecord, TenantGuard
from parrot_tools.querysource.dialect import DIALECT_REFERENCE, build_conditions, check_version_compatibility, load_variables, validate_filter, validate_placeholders
from parrot_tools.querysource.errors import QuerysourceToolkitError, SlugNotFoundError
from parrot_tools.querysource.models import DialectReference, ExecutionResult, FilterValue, PlaceholderInfo, SlugDetail, SlugSummary
from parrot_tools.querysource.results import frame_to_result


class QuerysourceToolkit(AbstractToolkit):
    """Explain, list, describe and execute QuerySource query-slugs and MultiQuery pipelines, scoped to tenants."""

    tool_prefix: str | None = "qs"                                   # toolkit.py:257
    exclude_tools: tuple[str, ...] = ("open", "close")               # toolkit.py:243
    confirming_tools: frozenset[str] = frozenset({"save_multiquery"})  # toolkit.py:275
    auto_open: bool = True                                           # toolkit.py:319

    def __init__(self, programs: list[str] | None = None, allow_write: bool = False, allow_raw_sql: bool = False,
                 allow_external_sources: bool = True, include_sql: bool = True, max_rows: int = 200,
                 forced_conditions: dict[str, Any] | None = None, dsn: str | None = None,
                 multiquery_timeout: float = 600.0, **kwargs: Any) -> None:
        """Configure tenancy and gates; querysource itself is imported lazily on first use."""
        super().__init__(**kwargs)
        self.programs = list(programs) if programs is not None else None
        self.allow_write = allow_write
        self.allow_raw_sql = allow_raw_sql
        self.allow_external_sources = allow_external_sources
        self.include_sql = include_sql
        self.max_rows = int(max_rows)
        self.forced_conditions = dict(forced_conditions or {})
        self.multiquery_timeout = float(multiquery_timeout)
        self._dsn = dsn
        self.guard = TenantGuard(self.programs)
        self._catalog: SlugCatalog | None = None
        self._components_cache: list[Any] | None = None
        if not self.allow_write:
            self.exclude_tools = self.exclude_tools + ("save_multiquery",)  # pattern: databasequery/toolkit.py:167-170
        try:
            warning = check_version_compatibility(_qs.installed_version())
        except ImportError:
            warning = None
        if warning:
            self.logger.warning("%s", warning)

    @property
    def restricted(self) -> bool:
        return self.guard.restricted

    async def _open(self) -> None:
        """Build the catalog (AsyncDB over querysource's asyncpg_url unless dsn was given)."""
        if self._catalog is None:
            self._catalog = SlugCatalog(self._dsn or _qs.default_dsn(), self.guard)
        await self._catalog.open()

    async def _close(self) -> None:
        if self._catalog is not None:
            await self._catalog.close()

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Pydantic → dict for the LLM (pattern: databasequery/toolkit.py:180-199)."""
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, list):
            return [r.model_dump() if hasattr(r, "model_dump") else r for r in result]
        return result

    def _summary(self, rec: SlugRecord) -> SlugSummary:
        return SlugSummary(slug=rec.slug, description=rec.description, program_slug=rec.program_slug,
                           provider=rec.provider, is_multiquery=rec.is_multiquery, placeholders=rec.placeholder_names)

    async def get_dialect_reference(self) -> DialectReference:
        """Return the QuerySource conditions dialect: which keys are options, which become placeholders, which
        become WHERE filters, the WHERE value grammar with examples, and the '@variables' this deployment
        accepts as values (e.g. '@today'). Call this before building conditions."""
        return DIALECT_REFERENCE.model_copy(update={"variables": load_variables()})

    async def list_slugs(self, search: str | None = None, program: str | None = None, limit: int = 50) -> list[SlugSummary]:
        """List query-slugs visible to this toolkit (allowlist-filtered). `search` matches slug or description."""
        await self._open()
        records = await self._catalog.list(search=search, program=program, limit=max(1, min(int(limit), 500)))
        return [self._summary(r) for r in records]

    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail:
        """Explain a slug: placeholders and types, stored defaults, filtering/fields/ordering/grouping, provider,
        program, and — when the toolkit is configured with include_sql — the SQL or pipeline JSON. dry_run=True also
        returns the rendered query via QS.dry_run() (this performs provider setup, not a pure catalog read)."""
        await self._open()
        rec = await self._catalog.get_allowed(slug)
        detail = SlugDetail(
            **self._summary(rec).model_dump(),
            placeholders_detail=[PlaceholderInfo(name=n, type=rec.cond_definition.get(n), default=rec.conditions.get(n))
                                 for n in rec.placeholder_names],
            filtering=rec.filtering, fields=rec.fields, ordering=rec.ordering, grouping=rec.grouping,
            is_cached=rec.is_cached, cache_timeout=rec.cache_timeout,
            sql=rec.query_raw if (self.include_sql and not rec.is_multiquery) else None,
            pipeline=rec.pipeline if self.include_sql else None,
        )
        if dry_run and not rec.is_multiquery:
            qs = _qs.get_qs()(slug=slug)                    # qs.py:42
            try:
                result, error = await qs.dry_run()          # qs.py:529
                detail.rendered_query = str(result) if result is not None else f"dry_run error: {error}"
            finally:
                await qs.close()                            # qs.py:519
        return detail

    async def execute_slug(self, slug: str, placeholders: dict[str, Any] | None = None,
                           filter: dict[str, FilterValue] | None = None, fields: list[str] | None = None,
                           ordering: list[str] | None = None, grouping: list[str] | None = None,
                           limit: int | None = None, offset: int | None = None, refresh: bool = False) -> ExecutionResult:
        """Run a query-slug. `placeholders` fill the slug's declared conditions (see qs_describe_slug);
        `filter` adds WHERE clauses in the dialect grammar (see qs_get_dialect_reference); `fields`, `ordering`,
        `grouping` override the stored projection; `limit` is capped at the toolkit's max_rows; `refresh` bypasses
        the QuerySource cache. Returns bounded rows plus returned_rows/total_rows/truncated."""
        started = time.monotonic()
        await self._open()
        rec = await self._catalog.get_allowed(slug)                     # tenant check first (spec §2)
        placeholders = dict(placeholders or {})
        validate_placeholders(placeholders, set(rec.placeholder_names))
        rejected = validate_filter(dict(filter or {}))                   # raises when strict (default)
        conditions = build_conditions(placeholders=placeholders, filter=filter, fields=fields, ordering=ordering,
                                      grouping=grouping, limit=limit, offset=offset, refresh=refresh,
                                      max_rows=self.max_rows, forced=self.forced_conditions)
        self.logger.info("qs_execute_slug %s querylimit=%s", slug, conditions.get("querylimit"))
        exc_mod = _qs.get_exceptions()
        qs = _qs.get_qs()(slug=slug, conditions=conditions)              # qs.py:42
        try:
            result, error = await qs.query(output_format="pandas")      # qs.py:363
            if error:
                raise QuerysourceToolkitError(f"query '{slug}' failed: {error}")
        except exc_mod.DataNotFound:
            return frame_to_result(None, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started)
        except exc_mod.SlugNotFound as exc:
            raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        except exc_mod.QueryException as exc:
            raise QuerysourceToolkitError(str(exc)) from exc
        finally:
            await qs.close()                                             # qs.py:519
        return frame_to_result(result, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started)
