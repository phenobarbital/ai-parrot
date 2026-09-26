"""QuerysourceToolkit — tenant-scoped QuerySource tools for agents (spec FEAT-558 §3 M5/M6).

Generated tool names (tool_prefix 'qs'): qs_get_dialect_reference, qs_list_slugs, qs_describe_slug, qs_execute_slug,
qs_list_components, qs_validate_pipeline, qs_run_multiquery and — only when allow_write=True — qs_save_multiquery.
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import asdict
from typing import Any

from parrot.tools.config_schema import ConfigOption
from parrot.tools.toolkit import AbstractToolkit  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:206

from parrot_tools.querysource import _qs
from parrot_tools.querysource.catalog import (
    NormalizedPipeline,
    SlugCatalog,
    SlugRecord,
    TenantGuard,
    normalize_pipeline,
)
from parrot_tools.querysource.config import QuerysourceToolkitConfig
from parrot_tools.querysource.dialect import (
    DIALECT_REFERENCE,
    build_conditions,
    check_version_compatibility,
    load_variables,
    validate_filter,
    validate_placeholders,
)
from parrot_tools.querysource.errors import (
    QuerysourceToolkitError,
    RawSqlForbiddenError,
    SlugNotFoundError,
    TenantDeniedError,
    WriteDisabledError,
)
from parrot_tools.querysource.models import (
    ComponentDoc,
    DialectReference,
    ExecutionResult,
    FilterValue,
    MultiQueryResult,
    PipelineIssue,
    PipelineValidation,
    PlaceholderInfo,
    SavedSlug,
    SlugDetail,
    SlugSummary,
)
from parrot_tools.querysource.results import frame_to_result, multi_to_result


class QuerysourceToolkit(AbstractToolkit):
    """Explain, list, describe and execute QuerySource query-slugs and MultiQuery pipelines, scoped to tenants."""

    #: FEAT-593 — Agent Studio configuration surface.
    config_model = QuerysourceToolkitConfig
    options_params = frozenset({"programs"})
    secret_params = frozenset({"dsn"})

    tool_prefix: str | None = "qs"  # toolkit.py:257
    exclude_tools: tuple[str, ...] = ("open", "close")  # toolkit.py:243
    confirming_tools: frozenset[str] = frozenset({"save_multiquery"})  # toolkit.py:275
    auto_open: bool = True  # toolkit.py:319

    def __init__(
        self,
        programs: list[str] | None = None,
        allow_write: bool = False,
        allow_raw_sql: bool = False,
        allow_external_sources: bool = True,
        include_sql: bool = True,
        max_rows: int = 200,
        forced_conditions: dict[str, Any] | None = None,
        dsn: str | None = None,
        multiquery_timeout: float = 600.0,
        **kwargs: Any,
    ) -> None:
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

    async def config_options(self, param: str) -> list[ConfigOption]:
        """Dynamic choices for Agent Studio (FEAT-593): catalog program slugs for ``programs``."""
        if param != "programs":
            return await super().config_options(param)
        await self._open()
        return [ConfigOption(value=program, label=program) for program in await self._catalog.list_programs()]

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Pydantic → dict for the LLM (pattern: databasequery/toolkit.py:180-199)."""
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, list):
            return [r.model_dump() if hasattr(r, "model_dump") else r for r in result]
        return result

    def _summary(self, rec: SlugRecord) -> SlugSummary:
        return SlugSummary(
            slug=rec.slug,
            description=rec.description,
            program_slug=rec.program_slug,
            provider=rec.provider,
            is_multiquery=rec.is_multiquery,
            placeholders=rec.placeholder_names,
        )

    async def get_dialect_reference(self) -> DialectReference:
        """Return the QuerySource conditions dialect: which keys are options, which become placeholders, which
        become WHERE filters, the WHERE value grammar with examples, and the '@variables' this deployment
        accepts as values (e.g. '@today'). Call this before building conditions."""
        return DIALECT_REFERENCE.model_copy(update={"variables": load_variables()})

    async def list_slugs(
        self, search: str | None = None, program: str | None = None, limit: int = 50, tenant: str | None = None
    ) -> list[SlugSummary]:
        """List query-slugs visible to this toolkit (allowlist-filtered). `search` matches slug or description.
        `tenant` selects a QuerySource tenant store schema; omit it for public/legacy slugs. Routing, not security."""
        await self._open()
        records = await self._catalog.list(
            search=search, program=program, limit=max(1, min(int(limit), 500)), tenant=tenant
        )
        return [self._summary(r) for r in records]

    def _placeholders_detail(self, rec: SlugRecord) -> tuple[list[PlaceholderInfo], bool]:
        """Build placeholder detail using QuerySource's canonical describe semantics."""
        try:
            describe = _qs.get_describe()
        except (ImportError, OSError):
            return self._legacy_placeholders_detail(rec, supported=True, keyword_types=())
        out = describe.build_variables(rec.query_raw, rec.conditions, rec.cond_definition)
        variables = out.get("variables")
        supported = bool(out.get("variables_supported", False))
        if variables is None:
            return self._legacy_placeholders_detail(rec, supported=supported, keyword_types=describe.KEYWORD_TYPES)
        return (
            [
                PlaceholderInfo(**{key: value for key, value in var.model_dump().items() if key in PlaceholderInfo.model_fields})
                for var in variables
            ],
            supported,
        )

    @staticmethod
    def _legacy_placeholders_detail(
        rec: SlugRecord, *, supported: bool, keyword_types: Any
    ) -> tuple[list[PlaceholderInfo], bool]:
        """Build legacy placeholder detail when QuerySource describe data is unavailable."""
        return (
            [
                PlaceholderInfo(
                    name=name,
                    type=rec.cond_definition.get(name),
                    default=rec.conditions.get(name),
                    required=False,
                    accepts_keywords=rec.cond_definition.get(name) in keyword_types
                    or rec.cond_definition.get(name) is None,
                )
                for name in rec.placeholder_names
            ],
            supported,
        )

    async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail:
        """Explain a slug: placeholders and types, stored defaults, filtering/fields/ordering/grouping, provider,
        program, and — when the toolkit is configured with include_sql — the SQL or pipeline JSON. dry_run=True also
        returns the rendered query via QS.dry_run() (this performs provider setup, not a pure catalog read). `tenant`
        selects a QuerySource tenant store schema; omit it for public/legacy slugs. Routing, not security. Each
        placeholder reports `required` and `accepts_keywords`."""
        await self._open()
        rec = await self._catalog.get_allowed(slug, tenant=tenant)
        placeholders_detail, variables_supported = self._placeholders_detail(rec)
        detail = SlugDetail(
            **self._summary(rec).model_dump(),
            placeholders_detail=placeholders_detail,
            variables_supported=variables_supported,
            filtering=rec.filtering,
            fields=rec.fields,
            ordering=rec.ordering,
            grouping=rec.grouping,
            is_cached=rec.is_cached,
            cache_timeout=rec.cache_timeout,
            sql=rec.query_raw if (self.include_sql and not rec.is_multiquery) else None,
            pipeline=rec.pipeline if self.include_sql else None,
        )
        if dry_run and not rec.is_multiquery:
            qs = _qs.get_qs()(slug=slug, tenant=tenant)  # qs.py:56-68
            try:
                result, error = await qs.dry_run()  # qs.py:529
                detail.rendered_query = str(result) if result is not None else f"dry_run error: {error}"
            finally:
                await qs.close()  # qs.py:519
        return detail

    async def execute_slug(
        self,
        slug: str,
        placeholders: dict[str, Any] | None = None,
        filter: dict[str, FilterValue] | None = None,
        fields: list[str] | None = None,
        ordering: list[str] | None = None,
        grouping: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        refresh: bool = False,
        tenant: str | None = None,
    ) -> ExecutionResult:
        """Run a query-slug. `placeholders` fill the slug's declared conditions (see qs_describe_slug);
        `filter` adds WHERE clauses in the dialect grammar (see qs_get_dialect_reference); `fields`, `ordering`,
        `grouping` override the stored projection; `limit` is capped at the toolkit's max_rows; `refresh` bypasses
        the QuerySource cache. `tenant` selects a QuerySource tenant store schema; omit it for public/legacy slugs.
        Routing, not security. Returns bounded rows plus returned_rows/total_rows/truncated."""
        started = time.monotonic()
        await self._open()
        rec = await self._catalog.get_allowed(slug, tenant=tenant)  # tenant check first (spec §2)
        placeholders = dict(placeholders or {})
        validate_placeholders(placeholders, set(rec.placeholder_names))
        rejected = validate_filter(dict(filter or {}))  # raises when strict (default)
        conditions = build_conditions(
            placeholders=placeholders,
            filter=filter,
            fields=fields,
            ordering=ordering,
            grouping=grouping,
            limit=limit,
            offset=offset,
            refresh=refresh,
            max_rows=self.max_rows,
            forced=self.forced_conditions,
        )
        self.logger.info("qs_execute_slug %s querylimit=%s", slug, conditions.get("querylimit"))
        exc_mod = _qs.get_exceptions()
        if rec.is_multiquery:
            return await self._execute_multi(
                slug, conditions=conditions, tenant=tenant, rejected=rejected, started=started, exc_mod=exc_mod
            )
        qs = _qs.get_qs()(slug=slug, conditions=conditions, tenant=tenant)  # qs.py:56-68
        try:
            result, error = await qs.query(output_format="pandas")  # qs.py:363
            if error:
                raise QuerysourceToolkitError(f"query '{slug}' failed: {error}")
        except exc_mod.DataNotFound:
            return frame_to_result(
                None, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started
            )
        except exc_mod.SlugNotFound as exc:
            raise SlugNotFoundError(f"slug '{slug}' not found") from exc
        except exc_mod.QueryException as exc:
            raise QuerysourceToolkitError(str(exc)) from exc
        finally:
            await qs.close()  # qs.py:519
        return frame_to_result(
            result, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started
        )

    async def _execute_multi(
        self,
        slug: str,
        *,
        conditions: dict[str, Any],
        tenant: str | None,
        rejected: list[str],
        started: float,
        exc_mod: Any,
    ) -> ExecutionResult:
        """Run a stored MultiQuery slug and normalise its output to one frame."""
        mq = _qs.get_multiqs()(slug=slug, conditions=dict(conditions), tenant=tenant)
        try:
            result, _options = await asyncio.wait_for(mq.query(), timeout=self.multiquery_timeout)
        except exc_mod.DataNotFound:
            return frame_to_result(
                None, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started
            )
        except asyncio.TimeoutError as exc:
            raise QuerysourceToolkitError(f"multiquery timed out after {self.multiquery_timeout}s") from exc
        except exc_mod.QueryException as exc:
            raise QuerysourceToolkitError(str(exc)) from exc
        if isinstance(result, dict):
            if "result" in result:
                frame = result["result"]
            elif len(result) == 1:
                frame = next(iter(result.values()))
            else:
                raise QuerysourceToolkitError(
                    f"stored multiquery '{slug}' returned multiple frames {sorted(map(str, result))}; use qs_run_multiquery"
                )
        else:
            frame = result
        return frame_to_result(
            frame, slug=slug, max_rows=self.max_rows, applied=conditions, rejected=rejected, started=started
        )

    async def _get_catalog(self) -> list[Any]:
        """ComponentRegistry.get_catalog() via to_thread, cached per instance (handlers/components.py:50)."""
        if self._components_cache is None:
            registry = _qs.get_component_registry()
            self._components_cache = await asyncio.to_thread(registry.get_catalog)  # registry.py:187
        return self._components_cache

    async def _destination_names(self) -> set[str]:
        return {c.name for c in await self._get_catalog() if c.category == "Destinations"}

    async def list_components(self, category: str | None = None) -> list[ComponentDoc]:
        """List MultiQuery pipeline components (Operators, Transformations, Sources, Destinations) with their JSON
        schema and a usage example — the same catalog as GET /api/v3/qs/components. Optional `category` filter."""
        catalog = await self._get_catalog()
        if category:
            catalog = [c for c in catalog if c.category == category]
        return [ComponentDoc(**asdict(c)) for c in catalog]

    async def _policy_check(self, pipeline: dict[str, Any], *, tenant: str | None = None) -> PipelineValidation:
        """Toolkit policy over normalize_pipeline(): tenancy per slug node, raw nodes, external sources, destinations."""
        norm: NormalizedPipeline = normalize_pipeline(pipeline)
        issues: list[PipelineIssue] = []
        await self._open()
        for node, slug in norm.slug_nodes.items():
            try:
                await self._catalog.get_allowed(slug, tenant=tenant)
            except (TenantDeniedError, SlugNotFoundError) as exc:
                issues.append(PipelineIssue(step=node, field="slug", message=str(exc)))
        destinations = sorted(set(norm.output_steps) & await self._destination_names())
        if norm.raw_nodes and (self.restricted or not self.allow_raw_sql):
            for node in norm.raw_nodes:
                issues.append(
                    PipelineIssue(
                        step=node,
                        field="query",
                        message="inline query/raw_query nodes are not allowed for this instance",
                    )
                )
        if norm.has_files and not self.allow_external_sources:
            issues.append(
                PipelineIssue(
                    step="files", field="files", message="external files are disabled (allow_external_sources=False)"
                )
            )
        if norm.has_sources and not self.allow_external_sources:
            issues.append(
                PipelineIssue(
                    step="sources",
                    field="sources",
                    message="external sources are disabled (allow_external_sources=False)",
                )
            )
        if destinations and not self.allow_write:
            for step in destinations:
                issues.append(
                    PipelineIssue(step=step, field="Output", message="destination steps require allow_write=True")
                )
        return PipelineValidation(
            valid=not issues,
            issues=issues,
            referenced_slugs=sorted(set(norm.slug_nodes.values())),
            has_raw_nodes=bool(norm.raw_nodes),
            has_external_sources=norm.has_files or norm.has_sources,
            destination_steps=destinations,
        )

    async def validate_pipeline(self, pipeline: dict[str, Any]) -> PipelineValidation:
        """Validate a MultiQuery pipeline without running it: structural rules (known step names, ≥1 source, Join/Merge
        arity) plus this toolkit's policy — every queries[*] slug must be one this instance may execute; raw SQL nodes,
        external sources and destination (write) steps are reported when the configuration forbids them."""
        result = await self._policy_check(pipeline)
        registry = _qs.get_component_registry()
        structural = await asyncio.to_thread(registry.validate_pipeline, dict(pipeline))  # registry.py:332
        for err in getattr(structural, "errors", []):
            result.issues.append(PipelineIssue(step=err.step, field=err.field, message=err.message))
        result.valid = not result.issues
        return result

    def _raise_for_issues(self, validation: PipelineValidation) -> None:
        """Map policy issues to the toolkit error hierarchy (raw -> RawSqlForbiddenError, Output -> WriteDisabledError,
        slug -> TenantDeniedError as a defense-in-depth fallback). In the normal call path a denied nested
        `queries[*]` slug is already raised with its real type by `_assert_pipeline_slugs_allowed` before this
        runs (spec §5 AC5); this branch only guards against a future caller that skips that pre-check."""
        if validation.valid:
            return
        fields = {i.field for i in validation.issues}
        msg = "; ".join(f"{i.step}.{i.field}: {i.message}" for i in validation.issues)
        if "slug" in fields:
            raise TenantDeniedError(f"pipeline rejected: {msg}")
        if "query" in fields:
            raise RawSqlForbiddenError(f"pipeline rejected: {msg}")
        if "Output" in fields:
            raise WriteDisabledError(f"pipeline rejected: {msg}")
        raise QuerysourceToolkitError(f"pipeline rejected: {msg}")

    async def _assert_pipeline_slugs_allowed(self, pipeline: dict[str, Any], *, tenant: str | None = None) -> None:
        """Re-verify every queries[*] slug node directly against the tenant guard, letting `TenantDeniedError`
        / `SlugNotFoundError` propagate with their real type — `_policy_check` collapses both into a single
        `PipelineIssue(field="slug")` for `validate_pipeline`'s report-only contract, which would otherwise
        surface a generic `QuerysourceToolkitError` from `run_multiquery`/`save_multiquery` (spec §5 AC5:
        a foreign slug must raise `TenantDeniedError`, the same as the top-level `slug=` argument)."""
        for referenced_slug in set(normalize_pipeline(pipeline).slug_nodes.values()):
            await self._catalog.get_allowed(referenced_slug, tenant=tenant)

    async def run_multiquery(
        self,
        pipeline: dict[str, Any] | None = None,
        slug: str | None = None,
        conditions: dict[str, Any] | None = None,
        tenant: str | None = None,
    ) -> MultiQueryResult:
        """Run a MultiQuery pipeline inline (`pipeline`, the JSON with queries/Join/Concat/…/Output) or a saved
        multi-query slug (`slug`). Every referenced slug must be executable by this toolkit; raw SQL nodes, external
        sources and destination steps follow the instance configuration (see qs_validate_pipeline). `tenant` selects a
        QuerySource tenant store schema; omit it for public/legacy slugs. Routing, not security. Results are bounded
        per frame."""
        started = time.monotonic()
        if (pipeline is None) == (slug is None):
            raise QuerysourceToolkitError("pass exactly one of `pipeline` or `slug`")
        await self._open()
        if slug is not None:
            rec = await self._catalog.get_allowed(slug, tenant=tenant)
            if rec.is_multiquery:
                await self._assert_pipeline_slugs_allowed(rec.pipeline, tenant=tenant)
                self._raise_for_issues(await self._policy_check(rec.pipeline, tenant=tenant))
            mq = _qs.get_multiqs()(slug=slug, conditions=dict(conditions or {}), tenant=tenant)  # multi/__init__.py:106-121
        else:
            await self._assert_pipeline_slugs_allowed(pipeline, tenant=tenant)
            self._raise_for_issues(await self._policy_check(pipeline, tenant=tenant))
            mq = _qs.get_multiqs()(
                query=copy.deepcopy(pipeline), conditions=dict(conditions or {}), tenant=tenant
            )  # deepcopy: __init__ pops keys (:95-97)
        exc_mod = _qs.get_exceptions()
        self.logger.info("qs_run_multiquery slug=%s inline=%s", slug, pipeline is not None)
        try:
            result, _options = await asyncio.wait_for(
                mq.query(), timeout=self.multiquery_timeout
            )  # :166 ; §8 Q3 option a
        except exc_mod.DataNotFound:
            return multi_to_result(None, max_rows=self.max_rows, started=started)
        except asyncio.TimeoutError as exc:
            raise QuerysourceToolkitError(f"multiquery timed out after {self.multiquery_timeout}s") from exc
        except exc_mod.QueryException as exc:
            raise QuerysourceToolkitError(str(exc)) from exc
        return multi_to_result(result, max_rows=self.max_rows, started=started)

    async def save_multiquery(
        self, slug: str, pipeline: dict[str, Any], description: str, program: str | None = None, overwrite: bool = False
    ) -> SavedSlug:
        """Persist a validated MultiQuery pipeline as a query-slug owned by `program` (forced to the single allowed
        program when this toolkit is tenant-restricted). Requires operator opt-in (allow_write) and user confirmation.
        Refuses to overwrite a slug owned by another program; set overwrite=True to update your own."""
        if not self.allow_write:
            raise WriteDisabledError("save_multiquery is disabled for this toolkit (allow_write=False)")
        program_slug = self.guard.resolve_write_program(program)
        await self._open()
        await self._assert_pipeline_slugs_allowed(pipeline)
        validation = await self.validate_pipeline(pipeline)
        self._raise_for_issues(validation)
        return await self._catalog.upsert(
            slug=slug, description=description, pipeline=pipeline, program_slug=program_slug, overwrite=overwrite
        )

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Defence in depth: block the write tool even if it were exposed (toolkit.py:455 hook)."""
        if tool_name.endswith("save_multiquery") and not self.allow_write:
            raise WriteDisabledError("save_multiquery is disabled for this toolkit (allow_write=False)")
