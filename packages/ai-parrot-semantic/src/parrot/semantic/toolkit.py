"""SemanticLayerToolkit — governed metric queries for agents (spec §3 Module 10)."""

from __future__ import annotations

import uuid
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import pandas as pd
from pydantic import BaseModel, Field

from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
from parrot.auth.context import _pctx_var
from parrot.security import AbstractKMSSigner
from parrot.tools.dataset_manager import DatasetManager
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit

from .audit import SemanticAuditEntry, SemanticAuditLedger
from .cache import CompileCache
from .catalog import RoleCatalog
from .context import _semantic_pctx_var, _static_subject_var, current_pctx
from .engines import compile as compile_query_sql
from .errors import (
    SemanticAccessError,
    SemanticError,
    SemanticExecutionError,
    SemanticPolicyError,
    SemanticResultError,
    SemanticValidationError,
)
from .execution import ConnectionResolver, Executor
from .governance.pbac import PbacGate
from .governance.pipeline import GovernancePipeline, subject_digest
from .governance.rls import RlsPushdown
from .loader import LoadedModel, SemanticModelLoader
from .models import GovernedQuery, SemanticQuery, SemanticQueryResult
from .results import ResultHandle, ResultHandleStore


class StaticSubject(BaseModel):
    """Fixed operator identity for the local MCP surface."""

    user_id: str
    tenant_id: str
    roles: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticLayerToolkit(AbstractToolkit):
    """Governed semantic-layer tools: catalog, compile and metric queries."""

    tool_prefix = "sl"
    exclude_tools = ("reload", "run_sql", "save_result_as_dataset")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the semantic-layer orchestration dependencies.

        Args:
            **kwargs: ``models_dir``, ``dialect``, ``dataplane_guard``, ``rls_registry``,
                ``database_toolkit``, ``signer``, ``audit_storage``, ``static_subject``,
                result-store limits, compiler function overrides, and base toolkit options.

        Raises:
            SemanticPolicyError: If a governed model has no data-plane policy guard.
        """
        models_dir = kwargs.pop("models_dir")
        dialect = kwargs.pop("dialect")
        dataplane_guard: DataPlanePolicyGuard | None = kwargs.pop("dataplane_guard", None)
        rls_registry: RlsRegistry | None = kwargs.pop("rls_registry", None)
        database_toolkit: DatabaseQueryToolkit | None = kwargs.pop("database_toolkit", None)
        signer: AbstractKMSSigner | None = kwargs.pop("signer", None)
        audit_storage: Callable[[str], Awaitable[None]] | None = kwargs.pop("audit_storage", None)
        static_subject = kwargs.pop("static_subject", None)
        result_ttl_s = int(kwargs.pop("result_ttl_s", 900))
        result_store_max = int(kwargs.pop("result_store_max", 256))
        allowed_functions = frozenset(str(item).upper() for item in (kwargs.pop("allowed_functions", None) or ()))
        audit_required = kwargs.pop("audit_required", None)
        allow_raw_sql = bool(kwargs.pop("allow_raw_sql", False))
        dataset_manager_factory: Callable[[PermissionContext], DatasetManager] | None = kwargs.pop(
            "dataset_manager_factory", None
        )
        super().__init__(**kwargs)

        self._models_dir = Path(models_dir)
        self._dialect = str(dialect)
        self._loader = SemanticModelLoader(self._models_dir, driver=self._dialect)
        self._models = self._loader.load()
        if any(model.policy.governed for model in self._models.values()) and dataplane_guard is None:
            raise SemanticPolicyError("guard_required")

        registry = rls_registry or RlsRegistry()
        for model in self._models.values():
            for rule in model.policy.rls:
                registry.register(rule)

        self._pbac = PbacGate(dataplane_guard)
        self._pipeline = GovernancePipeline(
            pbac=self._pbac,
            rls=RlsPushdown(registry),
            allowed_functions=allowed_functions,
        )
        self._rls_registry = registry
        self._catalog = RoleCatalog(self._models)
        self._ledger = SemanticAuditLedger(signer=signer, storage=audit_storage)
        self._cache = CompileCache()
        self._handles = ResultHandleStore(ttl_s=result_ttl_s, max_entries=result_store_max)
        self._executor = Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver())
        self._static_subject = StaticSubject.model_validate(static_subject) if static_subject is not None else None
        self._audit_required = self._ledger.durable if audit_required is None else bool(audit_required)
        self._dataset_manager_factory = dataset_manager_factory
        self._dataset_manager_subjects: weakref.WeakKeyDictionary[DatasetManager, str] = weakref.WeakKeyDictionary()
        if allow_raw_sql:
            self.exclude_tools = tuple(name for name in self.exclude_tools if name != "run_sql")
        if dataset_manager_factory is not None:
            self.exclude_tools = tuple(name for name in self.exclude_tools if name != "save_result_as_dataset")
        self.logger.info("semantic audit_required=%s (durable sink=%s)", self._audit_required, self._ledger.durable)

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Set both ContextVars from the call context or configured static subject."""
        pctx = kwargs.get("_permission_context")
        is_static = False
        if pctx is None and self._static_subject is not None:
            subject = self._static_subject
            pctx = PermissionContext(
                session=UserSession(
                    user_id=subject.user_id,
                    tenant_id=subject.tenant_id,
                    roles=frozenset(subject.roles),
                    metadata=dict(subject.metadata),
                ),
                channel="mcp-local",
            )
            is_static = True
            self.logger.warning("static_subject %s used for %s", subject.user_id, tool_name)
        _static_subject_var.set(is_static)
        _semantic_pctx_var.set(pctx)
        _pctx_var.set(pctx)

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Serialize Pydantic results to plain dictionaries for the LLM."""
        return result.model_dump(mode="json") if isinstance(result, BaseModel) else result

    async def list_models(self) -> list[dict]:
        """List models whose declared resource manifests the current subject may access."""
        visible: list[dict] = []
        first_model = next(iter(self._models.values()), None)
        try:
            for model in self._models.values():
                if await self._is_authorized(model):
                    visible.append(
                        {"name": model.name, "governed": model.policy.governed, "engine": model.policy.engine}
                    )
            await self._audit_catalog("list_models", first_model, outcome="ok")
            return visible
        except SemanticError as error:
            return await self._catalog_error("list_models", first_model, error)  # type: ignore[return-value]

    async def list_metrics(self, model: str) -> list[dict]:
        """List role-visible metrics for an authorized model."""
        return await self._list_members(model, {"metric"}, "list_metrics")

    async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]:
        """List role-visible dimensions, validating any metrics used to constrain them."""
        try:
            loaded = self._model(model)
            roles = self._roles()
            authorized = await self._is_authorized(loaded)
            if metrics:
                self._catalog.check_query_rights(SemanticQuery(model=model, metrics=metrics), roles)
            members = self._catalog.visible_members(model, roles, authorized=authorized)
            result = [item.model_dump(mode="json") for item in members if item.kind in {"dimension", "time_dimension"}]
            await self._audit_catalog("get_dimensions", loaded, outcome="ok")
            return result
        except SemanticError as error:
            return await self._catalog_error("get_dimensions", self._models.get(model), error)  # type: ignore[return-value]

    async def get_dimension_values(
        self,
        model: str,
        dimension: str,
        metrics: list[str] | None = None,
        limit: int = 50,
    ) -> SemanticQueryResult:
        """Return governed values for a role-visible dimension."""
        try:
            loaded = self._model(model)
            roles = self._roles()
            authorized = await self._is_authorized(loaded)
            visible = self._catalog.visible_members(model, roles, authorized=authorized)
            visible_metrics = [item.name for item in visible if item.kind == "metric"]
            selected_metrics = metrics or visible_metrics[:1]
            if not selected_metrics:
                raise SemanticValidationError("metric_required")
            query = SemanticQuery(model=model, metrics=selected_metrics, dimensions=[dimension], limit=limit)
            return await self._run_governed(query, execute=True)
        except SemanticError as error:
            return await self._catalog_error("get_dimension_values", self._models.get(model), error)  # type: ignore[return-value]

    async def search_data_model(self, text: str, model: str | None = None) -> list[dict]:
        """Search names and descriptions across role-visible authorized model members."""
        try:
            loaded = self._model(model) if model is not None else next(iter(self._models.values()), None)
            authorized = {
                name: await self._is_authorized(candidate)
                for name, candidate in self._models.items()
                if model is None or name == model
            }
            result = self._catalog.search(text, self._roles(), model, authorized=authorized)
            await self._audit_catalog("search_data_model", loaded, outcome="ok")
            return result
        except SemanticError as error:
            return await self._catalog_error(
                "search_data_model", self._models.get(model) if model is not None else None, error
            )  # type: ignore[return-value]

    async def list_saved_queries(self, model: str) -> list[dict]:
        """List reviewed saved queries that the current subject may execute."""
        try:
            loaded = self._model(model)
            if not await self._is_authorized(loaded):
                return []
            visible: list[dict] = []
            for saved in loaded.policy.saved_queries:
                try:
                    self._catalog.check_query_rights(saved.query, self._roles())
                except SemanticError:
                    continue
                visible.append(saved.model_dump(mode="json", exclude={"query"}))
            await self._audit_catalog("list_saved_queries", loaded, outcome="ok")
            return visible
        except SemanticError as error:
            return await self._catalog_error("list_saved_queries", self._models.get(model), error)  # type: ignore[return-value]

    async def compile_query(self, query: SemanticQuery) -> dict:
        """Compile and govern a metric query without executing it."""
        return await self._run_governed(query, execute=False)

    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult | dict:
        """Compile, govern, execute and audit a structured metric query."""
        return await self._run_governed(query, execute=True)

    async def run_sql(self, model: str, sql: str) -> SemanticQueryResult | dict:
        """Run free read-only SQL through PBAC, lineage, RLS, masking, guard, and audit."""
        ctx = current_pctx()
        roles = self._roles()
        loaded = self._models.get(model)
        governed: GovernedQuery | None = None
        entry_id = str(uuid.uuid4())
        try:
            if loaded is None:
                raise SemanticValidationError("unknown_model", details={"model": model})
            governed = await self._pipeline.govern(sql, model=loaded, ctx=ctx, roles=roles)
            rows, row_count, truncated, duration_ms = await self._executor.run(
                governed, connection=loaded.policy.connection or ""
            )
            await self._ledger.append(
                self._audit_entry(
                    entry_id,
                    "run_sql",
                    loaded,
                    None,
                    sql,
                    governed,
                    outcome="ok",
                    raw_sql=True,
                    row_count=row_count,
                    duration_ms=duration_ms,
                ),
                required=self._audit_required,
            )
            columns = list(rows[0]) if rows else []
            result_id = self._handles.put(
                ResultHandle(
                    agent_id=ctx.extra.get("agent_id") if ctx else None,
                    user_id=ctx.user_id if ctx else "",
                    tenant_id=ctx.tenant_id if ctx else "",
                    session_id=ctx.extra.get("session_id") if ctx else None,
                    subject_digest=governed.subject_digest,
                    model=loaded.name,
                    model_digest=loaded.model_digest,
                    policy_digest=loaded.policy_digest,
                    expires_at=datetime.now(timezone.utc),
                    columns=columns,
                    rows=rows,
                    audit_id=entry_id,
                    governed_sql=governed.sql,
                )
            )
            return SemanticQueryResult(
                columns=columns,
                rows=rows,
                row_count=row_count,
                truncated=truncated,
                duration_ms=duration_ms,
                compiled_sql=governed.sql,
                audit_id=entry_id,
                result_id=result_id,
            )
        except SemanticError as error:
            if error.code == "audit_unavailable":
                return self._error_payload(error)
            try:
                await self._ledger.append(
                    self._audit_entry(
                        entry_id,
                        "run_sql",
                        loaded,
                        None,
                        sql,
                        governed,
                        outcome=self._error_outcome(error),
                        error=error,
                        raw_sql=True,
                    ),
                    required=self._audit_required,
                )
            except SemanticExecutionError as audit_error:
                return self._error_payload(audit_error)
            return self._error_payload(error)

    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict:
        """Save a prior governed result in the current subject's DatasetManager."""
        ctx = current_pctx()
        if ctx is None:
            return self._error_payload(SemanticAccessError("no_subject"))
        digest = subject_digest(ctx)
        handle: ResultHandle | None = None
        loaded: LoadedModel | None = None
        for candidate in self._models.values():
            try:
                handle = self._handles.claim(
                    result_id,
                    ctx=ctx,
                    subject_digest=digest,
                    model_digest=candidate.model_digest,
                    policy_digest=candidate.policy_digest,
                )
                loaded = candidate
                break
            except SemanticResultError:
                continue
        if handle is None or loaded is None:
            return self._error_payload(SemanticResultError("result_unavailable"))
        try:
            authorized = await self._is_authorized(loaded)
            if not self._catalog.visible_members(loaded.name, self._roles(), authorized=authorized):
                raise SemanticAccessError("member_not_granted")
            manager = await self._dataset_manager_for(ctx)
            dataset_id = manager.add_dataframe(
                name,
                pd.DataFrame(handle.rows, columns=handle.columns),
                description=description,
                metadata={"semantic_audit_id": handle.audit_id, "model": handle.model},
            )
            await self._audit_catalog("save_result_as_dataset", loaded, outcome="ok")
            return {"dataset_id": dataset_id, "name": name}
        except SemanticError as error:
            return await self._catalog_error("save_result_as_dataset", loaded, error)

    async def _dataset_manager_for(self, ctx: PermissionContext) -> DatasetManager:
        """Return the subject-scoped host manager, rejecting a shared manager instance."""
        if self._dataset_manager_factory is None:
            raise SemanticResultError("dataset_manager_unavailable")
        manager = self._dataset_manager_factory(ctx)
        if not isinstance(manager, DatasetManager):
            raise SemanticResultError("dataset_manager_unavailable")
        digest = subject_digest(ctx)
        previous_digest = self._dataset_manager_subjects.get(manager)
        if previous_digest is not None and previous_digest != digest:
            raise SemanticResultError("shared_dataset_manager")
        self._dataset_manager_subjects[manager] = digest
        return manager

    async def _run_governed(self, query: SemanticQuery, *, execute: bool) -> Any:
        """Run the single catalog, compile, govern, execute and audit path."""
        ctx = current_pctx()
        roles = self._roles()
        loaded = self._models.get(query.model)
        compiled_sql: str | None = None
        governed: GovernedQuery | None = None
        entry_id = str(uuid.uuid4())
        tool_name = "query_metrics" if execute else "compile_query"
        try:
            if loaded is None:
                raise SemanticValidationError("unknown_model", details={"model": query.model})
            query = self._catalog.expand_saved_query(query)
            if loaded.policy.governed:
                await self._pbac.authorize_manifest(ctx, loaded)
            self._catalog.check_query_rights(query, roles)
            compiled = await compile_query_sql(query, loaded, self._dialect, cache=self._cache)
            compiled_sql = compiled.sql
            governed = await self._pipeline.govern(
                compiled.sql,
                model=loaded,
                ctx=ctx,
                roles=roles,
                requested_limit=query.limit,
            )
            if not execute:
                await self._ledger.append(
                    self._audit_entry(
                        entry_id,
                        tool_name,
                        loaded,
                        query,
                        compiled_sql,
                        governed,
                        outcome="ok",
                    ),
                    required=self._audit_required,
                )
                return {
                    "sql": governed.sql,
                    "compiled_sql": compiled.sql,
                    "dialect": governed.dialect,
                    "tables": list(governed.tables),
                    "rls_applied": list(governed.rls_applied),
                    "masked_columns": list(governed.masked_columns),
                    "audit_id": entry_id,
                }

            rows, row_count, truncated, duration_ms = await self._executor.run(
                governed, connection=loaded.policy.connection or ""
            )
            await self._ledger.append(
                self._audit_entry(
                    entry_id,
                    tool_name,
                    loaded,
                    query,
                    compiled_sql,
                    governed,
                    outcome="ok",
                    row_count=row_count,
                    duration_ms=duration_ms,
                ),
                required=self._audit_required,
            )
            columns = list(rows[0]) if rows else []
            result_id = self._handles.put(
                ResultHandle(
                    agent_id=ctx.extra.get("agent_id") if ctx else None,
                    user_id=ctx.user_id if ctx else "",
                    tenant_id=ctx.tenant_id if ctx else "",
                    session_id=ctx.extra.get("session_id") if ctx else None,
                    subject_digest=governed.subject_digest,
                    model=loaded.name,
                    model_digest=loaded.model_digest,
                    policy_digest=loaded.policy_digest,
                    expires_at=datetime.now(timezone.utc),
                    columns=columns,
                    rows=rows,
                    audit_id=entry_id,
                    governed_sql=governed.sql,
                )
            )
            return SemanticQueryResult(
                columns=columns,
                rows=rows,
                row_count=row_count,
                truncated=truncated,
                duration_ms=duration_ms,
                compiled_sql=governed.sql,
                audit_id=entry_id,
                result_id=result_id,
            )
        except SemanticError as error:
            if error.code == "audit_unavailable":
                return self._error_payload(error)
            outcome = self._error_outcome(error)
            try:
                await self._ledger.append(
                    self._audit_entry(
                        entry_id,
                        tool_name,
                        loaded,
                        query,
                        compiled_sql,
                        governed,
                        outcome=outcome,
                        error=error,
                    ),
                    required=self._audit_required,
                )
            except SemanticExecutionError as audit_error:
                return self._error_payload(audit_error)
            return self._error_payload(error)

    def reload(self) -> None:
        """Re-run the model loader and invalidate compiled-query cache entries."""
        old_digests = {model.model_digest for model in self._models.values()}
        self._models = self._loader.load()
        for digest in old_digests:
            self._cache.invalidate_model(digest)
        self._cache = CompileCache()
        for model in self._models.values():
            for rule in model.policy.rls:
                self._rls_registry.register(rule)
        self._catalog = RoleCatalog(self._models)

    async def _list_members(self, model: str, kinds: set[str], tool_name: str) -> list[dict]:
        """Return authorized, role-visible members of selected kinds."""
        try:
            loaded = self._model(model)
            authorized = await self._is_authorized(loaded)
            members = self._catalog.visible_members(model, self._roles(), authorized=authorized)
            result = [item.model_dump(mode="json") for item in members if item.kind in kinds]
            await self._audit_catalog(tool_name, loaded, outcome="ok")
            return result
        except SemanticError as error:
            return await self._catalog_error(tool_name, self._models.get(model), error)  # type: ignore[return-value]

    async def _is_authorized(self, model: LoadedModel) -> bool:
        """Authorize a model manifest, returning True for an accessible model."""
        if not model.policy.governed:
            return True
        await self._pbac.authorize_manifest(current_pctx(), model)
        return True

    def _model(self, name: str) -> LoadedModel:
        """Return a loaded model or raise a stable validation error."""
        model = self._models.get(name)
        if model is None:
            raise SemanticValidationError("unknown_model", details={"model": name})
        return model

    def _roles(self) -> frozenset[str]:
        """Return roles from the current per-call subject."""
        ctx = current_pctx()
        return frozenset(ctx.session.roles) if ctx is not None else frozenset()

    async def _audit_catalog(
        self,
        tool_name: str,
        model: LoadedModel | None,
        *,
        outcome: str | None = None,
        error: SemanticError | None = None,
    ) -> None:
        """Append an audit event for a catalog operation."""
        entry = self._audit_entry(
            str(uuid.uuid4()),
            tool_name,
            model,
            None,
            None,
            None,
            outcome=outcome or self._error_outcome(error),
            error=error,
        )
        await self._ledger.append(entry, required=self._audit_required)

    async def _catalog_error(
        self,
        tool_name: str,
        model: LoadedModel | None,
        error: SemanticError,
    ) -> dict[str, Any]:
        """Audit a catalog failure and prefer a required-audit failure in the response."""
        if error.code != "audit_unavailable":
            try:
                await self._audit_catalog(tool_name, model, error=error)
            except SemanticExecutionError as audit_error:
                error = audit_error
        return self._error_payload(error)

    def _audit_entry(
        self,
        entry_id: str,
        tool_name: str,
        model: LoadedModel | None,
        query: SemanticQuery | None,
        compiled_sql: str | None,
        governed: GovernedQuery | None,
        *,
        outcome: str,
        error: SemanticError | None = None,
        raw_sql: bool = False,
        row_count: int | None = None,
        duration_ms: int | None = None,
    ) -> SemanticAuditEntry:
        """Build one audit entry without leaking SQL through errors."""
        ctx = current_pctx()
        roles = sorted(ctx.session.roles) if ctx else []
        governed_model = bool(model and model.policy.governed)
        return SemanticAuditEntry(
            entry_id=entry_id,
            created_at=datetime.now(timezone.utc),
            user_id=ctx.user_id if ctx else "",
            tenant_id=ctx.tenant_id if ctx else "",
            channel=(ctx.channel or "unknown") if ctx else "unknown",
            agent_id=ctx.extra.get("agent_id") if ctx else None,
            subject_digest=subject_digest(ctx),
            roles=roles,
            static_subject=_static_subject_var.get(),
            model=model.name if model else (query.model if query else ""),
            model_digest=model.model_digest if model else "",
            policy_digest=model.policy_digest if model else "",
            engine=model.policy.engine if model else "unknown",
            tool=tool_name,
            structured_query=query.model_dump(mode="json") if query else None,
            raw_sql=raw_sql,
            compiled_sql=compiled_sql,
            governed_sql=governed.sql if governed else None,
            dialect=governed.dialect if governed else self._dialect,
            driver=governed.driver if governed else (model.schema.driver if model else self._dialect),
            rls_applied=list(governed.rls_applied) if governed else [],
            masked_columns=list(governed.masked_columns) if governed else [],
            pbac=self._pbac_outcome(governed_model, outcome, error),
            outcome=outcome,
            error_code=error.code if error else None,
            row_count=row_count,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _error_outcome(error: SemanticError | None) -> str:
        """Map a stable semantic error to the audit outcome taxonomy."""
        if error is None:
            return "ok"
        if error.code in {"no_subject", "pbac_unavailable", "pbac_denied", "outside_manifest", "member_not_granted"}:
            return "denied"
        if isinstance(error, SemanticValidationError) or isinstance(error, SemanticPolicyError):
            return "validation_error"
        return "execution_error"

    @staticmethod
    def _pbac_outcome(governed: bool, outcome: str, error: SemanticError | None) -> str:
        """Map authorization state to the audit PBAC taxonomy."""
        if not governed:
            return "not_governed"
        if error is not None and error.code == "pbac_unavailable":
            return "unavailable"
        if outcome == "denied":
            return "deny"
        return "allow"

    @staticmethod
    def _error_payload(error: SemanticError) -> dict[str, Any]:
        """Return the stable public error envelope."""
        return {"error": error.code, "message": str(error), "details": error.details}
