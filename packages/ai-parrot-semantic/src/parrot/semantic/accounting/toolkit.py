"""Finance tools over the accounting metrics layer (FEAT-713 M8).

Governance posture: metric visibility through DatasetPolicyGuard; with no guard or no permission context every
metric is allowed (as DatasetManager). The ``sl_*`` tools of this package fail closed instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from pydantic import ValidationError

from parrot.auth.context import _pctx_var
from parrot.auth.exceptions import AuthorizationRequired
from parrot.interfaces.duckdb_engine import DuckDBEngine
from parrot.semantic.audit import SemanticAuditLedger
from parrot.semantic.cache import CompileCache
from parrot.semantic.execution import ConnectionResolver, Executor
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit

from .audit import AuditMode, append_entry, audit_mode_from_env, build_entry, subject_digest
from .catalog import ModelCatalog, SnapshotProvider
from .compiler import canonical_request, compile_assertion, compile_metric
from .errors import AccountingError, AccountingExecutionError, ModelValidationError, RequestValidationError
from .grammar import BinOp, Expr, Neg, Num, Ref, Sum, parse_assertion, parse_expr, references
from .models import (
    AccountingModel,
    AccountingModelSpec,
    AssertionRequest,
    AssertionResult,
    ChartSnapshot,
    CompiledMetricQuery,
    MetricRequest,
    Period,
    RuntimeResult,
)
from .runtime.database import DatabaseRuntime
from .runtime.duckdb import DuckDBRuntime, FrameProvider
from .snapshot import snapshot_from_manifest


def _render(expr: Expr, metrics: Mapping[str, Any], *, inline: bool, parent_bp: int = 0) -> str:
    """Render a parsed expression back to text, optionally inlining metric references.

    Args:
        expr: Parsed metric expression.
        metrics: Metric definitions of the model (``name -> MetricDef``).
        inline: Replace each metric reference by its own (recursively inlined) formula.
        parent_bp: Binding power of the enclosing operator, for minimal parenthesisation.

    Returns:
        The expression text.
    """
    if isinstance(expr, Sum):
        return f"sum({expr.set_name})"
    if isinstance(expr, Num):
        return str(expr.value)
    if isinstance(expr, Ref):
        if not inline or expr.metric not in metrics:
            return expr.metric
        inner = _render(parse_expr(metrics[expr.metric].expr), metrics, inline=True)
        return f"({inner})"
    if isinstance(expr, Neg):
        return f"-{_render(expr.operand, metrics, inline=inline, parent_bp=30)}"
    if isinstance(expr, BinOp):
        bp = 20 if expr.op in ("*", "/") else 10
        left = _render(expr.left, metrics, inline=inline, parent_bp=bp)
        right = _render(expr.right, metrics, inline=inline, parent_bp=bp + 1)
        text = f"{left} {expr.op} {right}"
        return f"({text})" if bp < parent_bp else text
    raise RequestValidationError(f"unsupported expression node {type(expr).__name__}")


def _metric_closure(metrics: Mapping[str, Any], names: frozenset[str]) -> frozenset[str]:
    """*names* plus every metric they reference, transitively (unknown names are dropped)."""
    closure: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in closure or name not in metrics:
            continue
        closure.add(name)
        pending.extend(references(parse_expr(metrics[name].expr))[1])
    return frozenset(closure)


def _json_value(value: Any) -> Any:
    """Serialise one result cell: Decimals as exact strings, dates as ISO strings, everything else unchanged."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _validation_message(exc: ValidationError) -> str:
    """Compact, location-qualified summary of a pydantic validation error."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or '<request>'}: {err['msg']}" for err in exc.errors()
    )


class AccountingToolkit(AbstractToolkit):
    """Finance tools: the LLM picks metric + grain + filters + period; the compiler writes the SQL."""

    tool_prefix = "finance"

    def __init__(
        self,
        *,
        models_dir: Path | str | None = None,
        snapshot_provider: SnapshotProvider | None = None,
        snapshot_manifests: Mapping[str, Mapping[str, Path | str]] | None = None,
        database_toolkit: DatabaseQueryToolkit | None = None,
        frame_provider: FrameProvider | None = None,
        engine: Any = None,
        policy_guard: Any = None,
        signer: Any = None,
        audit_storage: Callable[[str], Awaitable[None]] | None = None,
        audit_mode: AuditMode | None = None,
        default_tenant: str | None = None,
        duckdb_threads: int = 4,
        require_context: bool = False,
        result_limit: int = 10_000,
        **kwargs: Any,
    ) -> None:
        """Wire catalog, runtimes, ledger and cache; never touches a snapshot or a journal.

        Args:
            models_dir: Root of ``<tenant>/<model>.yaml`` specs; defaults to ``FINANCE_MODELS_DIR`` or ``./models``.
            snapshot_provider: Async ``(tenant, model, spec) -> ChartSnapshot``; exclusive with ``snapshot_manifests``.
            snapshot_manifests: ``{tenant: {model: manifest_path}}``; exclusive with ``snapshot_provider``.
            database_toolkit: Toolkit used by the database runtime; a default one is created when omitted.
            frame_provider: Async ``name -> frame`` resolver for dataframe-backed journals.
            engine: DuckDB engine; created lazily on first dataframe query when omitted.
            policy_guard: ``DatasetPolicyGuard`` controlling metric visibility; ``None`` allows everything.
            signer: Audit signer for the shared ledger.
            audit_storage: Durable async audit sink.
            audit_mode: ``required`` or ``best_effort``; defaults to ``FINANCE_AUDIT_MODE``.
            default_tenant: Tenant used when neither the argument nor the permission context names one.
            duckdb_threads: Thread count for a lazily created DuckDB engine.
            require_context: With a ``policy_guard``, refuse calls that carry no permission context instead of
                allowing them (default ``False``: no guard or no context allows everything, per spec AC13).
            result_limit: Maximum result rows per query.
            **kwargs: Forwarded to ``AbstractToolkit``.

        Raises:
            ValueError: Neither or both of ``snapshot_provider`` / ``snapshot_manifests`` are configured.
        """
        super().__init__(**kwargs)
        if (snapshot_provider is None) == (snapshot_manifests is None):
            raise ValueError("configure exactly one of snapshot_provider or snapshot_manifests")
        self._catalog = ModelCatalog(Path(models_dir or os.environ.get("FINANCE_MODELS_DIR", "./models")))
        self._snapshot_provider: SnapshotProvider = snapshot_provider or self._manifest_provider(
            snapshot_manifests or {}
        )
        self._frame_provider = frame_provider
        self._engine = engine
        self._duckdb_threads = duckdb_threads
        self._policy_guard = policy_guard
        self._ledger = SemanticAuditLedger(signer=signer, storage=audit_storage)
        self._audit_mode: AuditMode = audit_mode or audit_mode_from_env()
        self._cache = CompileCache()
        self._database = DatabaseRuntime(
            Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver()), result_limit=result_limit
        )
        self._default_tenant = default_tenant
        self._require_context = require_context
        self._load_lock = asyncio.Lock()

    @staticmethod
    def _manifest_provider(manifests: Mapping[str, Mapping[str, Path | str]]) -> SnapshotProvider:
        """Adapt ``{tenant: {model: manifest_path}}`` into a provider that re-reads the file on every call."""
        table = {
            str(tenant): {str(model): Path(path) for model, path in models.items()}
            for tenant, models in manifests.items()
        }

        async def provider(tenant: str, model: str, spec: AccountingModelSpec) -> ChartSnapshot:
            path = table.get(tenant, {}).get(model)
            if path is None:
                raise AccountingExecutionError(f"no snapshot manifest configured for {tenant!r}/{model!r}")
            return await asyncio.to_thread(snapshot_from_manifest, path)

        return provider

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Per-call PBAC hook (hook verified: toolkit.py:491; pattern: dataset_manager/tool.py:2846)."""
        _pctx_var.set(kwargs.get("_permission_context"))

    def _resolve_tenant(self, tenant: str | None) -> str:
        """Tenant from the argument, else the permission context, else the toolkit default.

        Raises:
            RequestValidationError: No tenant can be resolved.
        """
        if tenant:
            return tenant
        pctx = _pctx_var.get()
        if pctx is not None:
            try:
                context_tenant = pctx.tenant_id
            except AttributeError:
                context_tenant = None
            if context_tenant:
                return str(context_tenant)
        if self._default_tenant:
            return self._default_tenant
        raise RequestValidationError("no tenant: pass 'tenant' or configure a default tenant")

    @staticmethod
    def _resource(tenant: str, model: str, metric: str) -> str:
        """Bare policy resource name (the guard adds the ``dataset:`` prefix)."""
        return f"accounting:{tenant}:{model}:{metric}"

    def _guarded_context(self) -> Any:
        """The permission context when both a guard and a context are present, else ``None`` (allow-all).

        Raises:
            AuthorizationRequired: A guard is configured, ``require_context`` is set and no context was propagated.
        """
        pctx = _pctx_var.get()
        if self._policy_guard is None:
            return None
        if not pctx:
            if self._require_context:
                raise AuthorizationRequired(
                    tool_name="finance", message="a permission context is required when a policy guard is configured"
                )
            return None
        return pctx

    async def _authorize(self, tool_name: str, names: list[str]) -> None:
        """Every name must be readable; no guard or no context ⇒ allowed."""
        pctx = self._guarded_context()
        if pctx is None:
            return
        for name in names:
            if not await self._policy_guard.can_read_dataset(pctx, name):
                raise AuthorizationRequired(tool_name=tool_name, message=f"access to {name!r} denied by policy")

    async def _authorize_metric(self, tool_name: str, tenant: str, model: str, metric: str) -> None:
        """Require read access to one metric resource."""
        await self._authorize(tool_name, [self._resource(tenant, model, metric)])

    async def _visible_names(self, names: list[str]) -> set[str]:
        """Subset of bare resource *names* the caller may read (all of them without guard or context)."""
        pctx = self._guarded_context()
        if pctx is None:
            return set(names)
        if not names:
            return set()
        return set(await self._policy_guard.filter_datasets(pctx, names))

    def _resolve_model(self, tenant: str, metric: str, model: str | None) -> str:
        """The model defining *metric* for *tenant*; from specs only.

        Raises:
            RequestValidationError: Unknown model/metric, or several models define the metric and none was named.
        """
        specs = self._catalog.specs()
        if model is not None:
            spec = specs.get((tenant, model))
            if spec is None:
                raise RequestValidationError(f"unknown model {model!r} for tenant {tenant!r}")
            if metric not in spec.metrics:
                raise RequestValidationError(f"unknown metric {metric!r} in model {model!r}")
            return model
        candidates = sorted(
            name for (spec_tenant, name), spec in specs.items() if spec_tenant == tenant and metric in spec.metrics
        )
        if not candidates:
            raise RequestValidationError(f"unknown metric {metric!r} for tenant {tenant!r}")
        if len(candidates) > 1:
            raise RequestValidationError(
                f"metric {metric!r} is defined by several models ({', '.join(candidates)}); pass 'model'"
            )
        return candidates[0]

    async def _ensure_loaded(self, tenant: str, model: str) -> AccountingModel:
        """Load (tenant, model) once under the lock; return the AccountingModel.

        Raises:
            RequestValidationError: The model is not in the catalog.
            AccountingExecutionError: Snapshot acquisition or journal metadata lookup failed (nothing is loaded).
            ModelValidationError: The model failed load-time validation (nothing is loaded).
        """
        if self._catalog.is_loaded(tenant, model):
            return self._catalog.get(tenant, model)
        async with self._load_lock:
            if self._catalog.is_loaded(tenant, model):
                return self._catalog.get(tenant, model)
            key = (tenant, model)
            spec = self._catalog.specs().get(key)
            if spec is None:
                raise RequestValidationError(f"unknown model {model!r} for tenant {tenant!r}")
            try:
                snapshot = await self._snapshot_provider(tenant, model, spec)
            except AccountingError:
                raise
            except Exception as exc:
                self.logger.warning("accounting snapshot provider failed: %s", type(exc).__name__)
                raise AccountingExecutionError(
                    f"chart snapshot unavailable for {tenant!r}/{model!r} ({type(exc).__name__})"
                ) from exc
            if not isinstance(snapshot, ChartSnapshot):
                raise AccountingExecutionError(f"snapshot provider returned no ChartSnapshot for {tenant!r}/{model!r}")
            columns: dict[tuple[str, str], Mapping[str, str]] | None = None
            source = spec.chart_of_accounts.source
            if source.table is not None:
                journal_columns = await self._database.fetch_columns(
                    connection=str(source.connection), driver=str(source.driver), table=source.table
                )
                columns = {key: journal_columns}
            self._catalog.load({key: snapshot}, columns)
            return self._catalog.get(tenant, model)

    async def list_metrics(self, tenant: str | None = None) -> list[dict]:
        """Catalog of metrics visible to the caller (PBAC-filtered).

        Args:
            tenant: Tenant whose metrics to list; defaults to the caller's tenant.

        Returns:
            One dict per visible metric: model, metric, description, unit, dimensions.
        """
        resolved = self._resolve_tenant(tenant)
        specs = self._catalog.specs()
        rows = self._catalog.metrics(resolved)
        visible = await self._visible_names([self._resource(resolved, model, name) for model, name, _ in rows])
        result: list[dict] = []
        for model, name, definition in rows:
            if self._resource(resolved, model, name) not in visible:
                continue
            dimensions = definition.dimensions
            if dimensions is None:
                dimensions = specs[(resolved, model)].chart_of_accounts.dimensions
            result.append(
                {
                    "model": model,
                    "metric": name,
                    "description": definition.description,
                    "unit": definition.unit,
                    "dimensions": list(dimensions),
                }
            )
        return result

    async def explain_metric(self, metric: str, model: str | None = None, tenant: str | None = None) -> str:
        """Formula, resolved accounts per set, and covering assertions, as plain text.

        Args:
            metric: Metric name.
            model: Model defining the metric; optional when exactly one model of the tenant defines it.
            tenant: Tenant; defaults to the caller's tenant.

        Returns:
            A plain-text explanation of the metric.
        """
        resolved_tenant = self._resolve_tenant(tenant)
        resolved_model = self._resolve_model(resolved_tenant, metric, model)
        await self._authorize_metric("finance_explain_metric", resolved_tenant, resolved_model, metric)
        loaded = await self._ensure_loaded(resolved_tenant, resolved_model)
        metrics = loaded.spec.metrics
        definition = metrics[metric]
        parsed = parse_expr(definition.expr)
        inlined_text = _render(parsed, metrics, inline=True)
        set_names = sorted(references(parse_expr(inlined_text))[0])
        related = _metric_closure(metrics, frozenset({metric}))
        covering: list[str] = []
        for assertion in loaded.spec.assertions:
            left, right = parse_assertion(assertion.expr)
            touched = _metric_closure(metrics, references(left)[1] | references(right)[1])
            if touched & related:
                covering.append(assertion.expr)

        lines = [f"Metric: {metric} (model {resolved_model}, tenant {resolved_tenant})"]
        if definition.description:
            lines.append(f"Description: {definition.description}")
        if definition.unit:
            lines.append(f"Unit: {definition.unit}")
        lines.append(f"Formula: {definition.expr}")
        lines.append(f"Inlined formula: {inlined_text}")
        lines.append("Account sets:")
        for name in set_names:
            resolved_set = loaded.sets.get(name)
            if resolved_set is None:
                continue
            window = ""
            if resolved_set.valid_from is not None or resolved_set.valid_to is not None:
                start = resolved_set.valid_from.isoformat() if resolved_set.valid_from else "-inf"
                end = resolved_set.valid_to.isoformat() if resolved_set.valid_to else "+inf"
                window = f" [valid {start} .. {end})"
            accounts = ", ".join(resolved_set.accounts) or "(none)"
            lines.append(f"  - {name}{window}: {accounts}")
        lines.append("Covering assertions:")
        lines.extend(f"  - {expr}" for expr in covering)
        if not covering:
            lines.append("  (none)")
        return "\n".join(lines)

    async def query_metric(
        self,
        metric: str,
        period_from: str,
        period_to: str,
        model: str | None = None,
        grain: str | None = None,
        dimensions: list[str] | None = None,
        filters: dict | None = None,
        cumulative: str | None = None,
        tenant: str | None = None,
    ) -> dict:
        """Compile → execute (database or duckdb) → audit → rows + lineage + sql_hash + audit_id + chart_drift.

        Args:
            metric: Metric name.
            period_from: First day of the period (ISO date, inclusive).
            period_to: Last day of the period (ISO date, inclusive).
            model: Model defining the metric; optional when exactly one model of the tenant defines it.
            grain: Time bucket: day, week, month, quarter or year; omit for a single total.
            dimensions: Dimensions to group by.
            filters: ``{dimension: value or [values]}`` equality filters.
            cumulative: Period-to-date mode: mtd, qtd or ytd (requires a compatible grain).
            tenant: Tenant; defaults to the caller's tenant.

        Returns:
            ``columns``, ``rows`` (amounts as exact decimal strings), ``row_count``, ``lineage``, ``sql_hash``,
            ``plan_hash``, ``audit_id``, ``chart_drift``, ``assertion_failed`` and ``duration_ms``.
        """
        started = time.monotonic()
        tool = "finance_query_metric"
        resolved_tenant = self._resolve_tenant(tenant)
        resolved_model = self._resolve_model(resolved_tenant, metric, model)
        await self._authorize_metric(tool, resolved_tenant, resolved_model, metric)
        request = self._metric_request(metric, period_from, period_to, grain, dimensions, filters, cumulative)
        loaded = await self._ensure_loaded(resolved_tenant, resolved_model)
        flags = self._catalog.flags(resolved_tenant, resolved_model)
        if flags is not None and flags.blocked:
            raise AccountingExecutionError(
                f"model {resolved_model!r} of tenant {resolved_tenant!r} is blocked by a failed live-validation "
                "assertion; queries are refused until validation passes"
            )
        runtime, dialect = self._runtime_for(loaded)
        compiled = await self._compile(loaded, request, dialect)
        result = await self._execute(runtime, compiled, loaded, tenant=resolved_tenant, tool=tool)
        entry = build_entry(
            context=self._audit_context(),
            tenant=resolved_tenant,
            model=loaded,
            compiled=compiled,
            target=result.target,
            tool=tool,
            outcome="ok",
            assertion_status="none",
            row_count=len(result.rows),
            duration_ms=result.duration_ms,
        )
        signed = await append_entry(self._ledger, entry, mode=self._audit_mode)
        return {
            "columns": list(result.columns),
            "rows": [{key: _json_value(value) for key, value in row.items()} for row in result.rows],
            "row_count": len(result.rows),
            "lineage": compiled.lineage.model_dump(mode="json"),
            "sql_hash": compiled.sql_hash,
            "plan_hash": compiled.plan_hash,
            "audit_id": signed.entry_id,
            "chart_drift": bool(flags is not None and flags.drift_accounts),
            "assertion_failed": bool(
                flags is not None and any(item.status == "failed" for item in flags.assertion_results)
            ),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    async def validate_model(self, model: str, tenant: str | None = None, live: bool = False) -> dict:
        """Require validation privilege and all metric reads; return only the selected model's results.
        With live=True refresh its snapshot and run last-closed-month assertions plus drift.

        Args:
            model: Model to validate.
            tenant: Tenant; defaults to the caller's tenant.
            live: Refresh the chart snapshot, detect drift and run every assertion over the last closed month.

        Returns:
            Structural: ``{"tenant", "model", "problems": [...]}``. Live: the model's live status.
        """
        tool = "finance_validate_model"
        resolved_tenant = self._resolve_tenant(tenant)
        spec = self._catalog.specs().get((resolved_tenant, model))
        if spec is None:
            raise RequestValidationError(f"unknown model {model!r} for tenant {resolved_tenant!r}")
        names = [self._resource(resolved_tenant, model, "__validate__")]
        names += [self._resource(resolved_tenant, model, metric) for metric in sorted(spec.metrics)]
        await self._authorize(tool, names)
        if live:
            from .live import _validate_one

            status = await _validate_one(self, resolved_tenant, model, today=datetime.now(timezone.utc).date())
            return status.model_dump(mode="json")
        problems: list[dict] = []
        try:
            await self._ensure_loaded(resolved_tenant, model)
        except ModelValidationError as exc:
            problems = [problem.model_dump(mode="json") for problem in exc.problems]
        return {"tenant": resolved_tenant, "model": model, "problems": problems}

    @staticmethod
    def _metric_request(
        metric: str,
        period_from: str,
        period_to: str,
        grain: str | None,
        dimensions: list[str] | None,
        filters: dict | None,
        cumulative: str | None,
    ) -> MetricRequest:
        """Build the MetricRequest from tool arguments.

        Raises:
            RequestValidationError: Malformed period, grain, dimensions, filters or cumulative mode.
        """
        normalised: dict[str, Any] = {}
        for key, value in (filters or {}).items():
            normalised[str(key)] = tuple(value) if isinstance(value, (list, tuple, set, frozenset)) else value
        try:
            return MetricRequest.model_validate(
                {
                    "metric": metric,
                    "grain": grain,
                    "dimensions": tuple(dimensions or ()),
                    "filters": normalised,
                    "period": {"from": period_from, "to": period_to, "cumulative": cumulative},
                }
            )
        except ValidationError as exc:
            raise RequestValidationError(f"invalid query request: {_validation_message(exc)}") from exc

    @staticmethod
    def _audit_context() -> Any:
        """The caller's permission context for audit entries, or ``None`` (anonymous / trusted host)."""
        return _pctx_var.get() or None

    def _runtime_for(self, model: AccountingModel) -> tuple[Any, str]:
        """(runtime, dialect): DuckDBRuntime for dataframe sources (engine created lazily), else DatabaseRuntime.

        Raises:
            AccountingExecutionError: A dataframe source without a frame provider, or an unusable database driver.
        """
        if model.spec.chart_of_accounts.source.dataframe is not None:
            if self._frame_provider is None:
                raise AccountingExecutionError("dataframe-backed model needs a frame_provider on the toolkit")
            if self._engine is None:
                self._engine = DuckDBEngine(threads=self._duckdb_threads)
            return DuckDBRuntime(self._engine, self._frame_provider), "duckdb"
        return self._database, self._database.dialect_for(model)

    async def _compile(
        self, model: AccountingModel, request: MetricRequest | AssertionRequest, dialect: str
    ) -> CompiledMetricQuery:
        """Cached compile in a worker thread; metric or assertion by request kind."""
        key = json.dumps([model.model_hash, canonical_request(request), dialect], separators=(",", ":"))
        cached = self._cache.get(key)
        if isinstance(cached, CompiledMetricQuery):
            return cached
        if isinstance(request, AssertionRequest):
            compiled = await asyncio.to_thread(compile_assertion, model, request, dialect)
        else:
            compiled = await asyncio.to_thread(compile_metric, model, request, dialect)
        self._cache.put(compiled)
        return compiled

    async def _execute(
        self, runtime: Any, compiled: CompiledMetricQuery, model: AccountingModel, *, tenant: str, tool: str
    ) -> RuntimeResult:
        """Run *compiled* on *runtime*; a failure is audited (best effort) as ``execution_error`` and re-raised."""
        started = time.monotonic()
        context = self._audit_context()
        try:
            if isinstance(runtime, DuckDBRuntime):
                return await runtime.execute(compiled, model)
            return await runtime.execute(compiled, model, subject_digest=subject_digest(context))
        except Exception as exc:
            audit_id: str | None = None
            try:
                entry = build_entry(
                    context=context,
                    tenant=tenant,
                    model=model,
                    compiled=compiled,
                    target="duckdb" if isinstance(runtime, DuckDBRuntime) else "database",
                    tool=tool,
                    outcome="execution_error",
                    assertion_status="none",
                    row_count=None,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                audit_id = (await append_entry(self._ledger, entry, mode="best_effort")).entry_id
            except Exception as audit_exc:  # noqa: BLE001 - best-effort audit of a failure
                self.logger.warning("accounting execution-error audit failed: %s", type(audit_exc).__name__)
            if isinstance(exc, AccountingExecutionError):
                exc.audit_id = audit_id
                raise
            if isinstance(exc, AccountingError):
                raise
            self.logger.warning("accounting execution failed: %s", type(exc).__name__)
            raise AccountingExecutionError(f"execution failed ({type(exc).__name__})", audit_id=audit_id) from exc

    async def _run_assertions(
        self, tenant: str, model: AccountingModel, period: Period, *, tool: str
    ) -> tuple[tuple[AssertionResult, ...], tuple[str, ...]]:
        """Compile, run and audit every assertion of *model* over *period*; one audit entry per assertion.

        A NULL side yields ``skipped``; otherwise the quantized sides pass when ``|lhs - rhs| <= tolerance``.

        Returns:
            The assertion results (in assertion-index order) and the audit entry ids.
        """
        runtime, dialect = self._runtime_for(model)
        results: list[AssertionResult] = []
        audit_ids: list[str] = []
        for index, assertion in enumerate(model.spec.assertions):
            request = AssertionRequest(assertion_index=index, period=period)
            compiled = await self._compile(model, request, dialect)
            result = await self._execute(runtime, compiled, model, tenant=tenant, tool=tool)
            row = result.rows[0] if result.rows else {}
            lhs, rhs = row.get("lhs"), row.get("rhs")
            if lhs is None or rhs is None:
                status = "skipped"
            elif abs(lhs - rhs) <= assertion.tolerance:
                status = "passed"
            else:
                status = "failed"
            results.append(
                AssertionResult(
                    expr=assertion.expr, status=status, lhs=lhs, rhs=rhs, tolerance=assertion.tolerance, period=period
                )
            )
            entry = build_entry(
                context=self._audit_context(),
                tenant=tenant,
                model=model,
                compiled=compiled,
                target=result.target,
                tool=tool,
                outcome="ok",
                assertion_status=status,
                row_count=len(result.rows),
                duration_ms=result.duration_ms,
            )
            audit_ids.append((await append_entry(self._ledger, entry, mode=self._audit_mode)).entry_id)
        return tuple(results), tuple(audit_ids)
