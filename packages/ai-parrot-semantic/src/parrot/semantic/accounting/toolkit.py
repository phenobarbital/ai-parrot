"""Finance tools over the accounting metrics layer (FEAT-713 M8).

Governance posture: metric visibility through DatasetPolicyGuard; with no guard or no permission context every
metric is allowed (as DatasetManager). The ``sl_*`` tools of this package fail closed instead.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from parrot.auth.context import _pctx_var
from parrot.auth.exceptions import AuthorizationRequired
from parrot.semantic.audit import SemanticAuditLedger
from parrot.semantic.cache import CompileCache
from parrot.semantic.execution import ConnectionResolver, Executor
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit

from .audit import AuditMode, audit_mode_from_env
from .catalog import ModelCatalog, SnapshotProvider
from .errors import AccountingError, AccountingExecutionError, RequestValidationError
from .grammar import BinOp, Expr, Neg, Num, Ref, Sum, parse_assertion, parse_expr, references
from .models import AccountingModel, AccountingModelSpec, ChartSnapshot
from .runtime.database import DatabaseRuntime
from .runtime.duckdb import FrameProvider
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
        self._load_lock = asyncio.Lock()

    @staticmethod
    def _manifest_provider(manifests: Mapping[str, Mapping[str, Path | str]]) -> SnapshotProvider:
        """Adapt ``{tenant: {model: manifest_path}}`` into a provider that re-reads the file on every call."""
        table = {str(tenant): {str(model): Path(path) for model, path in models.items()} for tenant, models in manifests.items()}

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
        """The permission context when both a guard and a context are present, else ``None`` (allow-all)."""
        pctx = _pctx_var.get()
        if self._policy_guard is None or not pctx:
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
        candidates = sorted(name for (spec_tenant, name), spec in specs.items() if spec_tenant == tenant and metric in spec.metrics)
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
