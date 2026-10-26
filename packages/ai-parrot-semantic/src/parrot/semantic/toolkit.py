"""Governed semantic tools with trusted host-bound request identity."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from parrot.auth import RlsRegistry
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit

from .audit import SemanticAuditEntry, SemanticAuditLedger
from .cache import CompileCache
from .catalog import RoleCatalog
from .context import current_identity, current_pctx, require_identity
from .engines import compile as compile_query_sql
from .errors import SemanticAccessError, SemanticError, SemanticPolicyError
from .execution import ConnectionResolver, Executor
from .governance.pbac import PbacGate
from .governance.pipeline import GovernancePipeline
from .governance.rls import RlsPushdown
from .loader import LoadedModel, SemanticModelLoader
from .models import GovernedQuery, SemanticQuery, SemanticQueryResult
from .results import ResultHandle, ResultHandleStore


class SemanticLayerToolkit(AbstractToolkit):
    """Catalog, compile and metric query surface over one governance pipeline."""

    tool_prefix = "sl"
    exclude_tools = ("reload", "run_sql", "save_result_as_dataset")

    def __init__(self, **kwargs: Any) -> None:
        """Construct governed collaborators without retaining request identity.

        Raises:
            SemanticPolicyError: If static identity is supplied or a governed
                model has no host-provided data-plane guard.
        """
        models_dir = Path(kwargs.pop("models_dir"))
        dialect = str(kwargs.pop("dialect"))
        dataplane_guard = kwargs.pop("dataplane_guard", None)
        rls_registry = kwargs.pop("rls_registry", None)
        database_toolkit = kwargs.pop("database_toolkit", None)
        signer = kwargs.pop("signer", None)
        audit_storage = kwargs.pop("audit_storage", None)
        static_subject = kwargs.pop("static_subject", None)
        result_ttl_s = int(kwargs.pop("result_ttl_s", 900))
        result_store_max = int(kwargs.pop("result_store_max", 256))
        allowed_functions = frozenset(kwargs.pop("allowed_functions", ()) or ())
        audit_required = kwargs.pop("audit_required", None)
        kwargs.pop("allow_raw_sql", None)
        kwargs.pop("dataset_manager_factory", None)
        if static_subject is not None:
            raise SemanticPolicyError("static_subject_forbidden", "Static identity requires the local bootstrap toolkit")

        super().__init__(**kwargs)
        self._dialect = dialect
        self._loader = SemanticModelLoader(models_dir, driver=dialect)
        self._models = self._loader.load()
        if any(model.policy.governed for model in self._models.values()) and dataplane_guard is None:
            raise SemanticPolicyError("guard_required", "Governed semantic models require a data-plane guard")

        self._rls_registry = rls_registry or RlsRegistry()
        for model in self._models.values():
            for rule in model.policy.rls:
                self._rls_registry.register(rule)
        self._pbac = PbacGate(dataplane_guard)
        self._pipeline = GovernancePipeline(
            pbac=self._pbac,
            rls=RlsPushdown(self._rls_registry),
            allowed_functions=allowed_functions,
        )
        self._catalog = RoleCatalog(self._models)
        self._ledger = SemanticAuditLedger(signer=signer, storage=audit_storage)
        self._audit_required = self._ledger.durable if audit_required is None else bool(audit_required)
        self.logger.info("semantic audit_required=%s (durable sink=%s)", self._audit_required, self._ledger.durable)
        self._cache = CompileCache()
        self._handles = ResultHandleStore(ttl_s=result_ttl_s, max_entries=result_store_max)
        self._executor = Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver())

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Validate that the core context agrees with the externally bound context."""
        del tool_name
        supplied = kwargs.get("_permission_context")
        bound = current_pctx()
        if supplied is None or bound is None or supplied != bound:
            raise SemanticAccessError("context_required", "A matching trusted semantic context is required")

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Serialize Pydantic results without resetting request-scoped context."""
        del tool_name, kwargs
        return result.model_dump(mode="json") if isinstance(result, BaseModel) else result

    async def list_models(self) -> list[dict]:
        """List models whose manifests are authorized for the current subject."""
        context = self._context()
        roles = frozenset(context.roles)
        visible: list[dict] = []
        for name, model in sorted(self._models.items()):
            try:
                await self._pbac.authorize_manifest(context, model)
            except SemanticAccessError:
                continue
            members = self._catalog.visible_members(name, roles, authorized=True)
            if members:
                visible.append({"name": name, "members": len(members)})
        return visible

    async def list_metrics(self, model: str) -> list[dict]:
        """Describe allowed metrics of an authorized model."""
        loaded, roles = await self._authorized_model(model)
        return [member.model_dump() for member in self._catalog.visible_members(loaded.name, roles, authorized=True) if member.kind == "metric"]

    async def get_dimensions(self, model: str, metrics: list[str] | None = None) -> list[dict]:
        """Describe allowed dimensions compatible with requested metrics."""
        loaded, roles = await self._authorized_model(model)
        if metrics:
            self._catalog.check_query_rights(SemanticQuery(model=model, metrics=metrics), roles)
        return [
            member.model_dump()
            for member in self._catalog.visible_members(loaded.name, roles, authorized=True)
            if member.kind in {"dimension", "time_dimension"}
        ]

    async def get_dimension_values(
        self, model: str, dimension: str, metrics: list[str] | None = None, limit: int = 50
    ) -> SemanticQueryResult:
        """Query authorized dimension values through the complete governance path."""
        query = SemanticQuery(model=model, metrics=metrics or [], dimensions=[dimension], limit=limit)
        return await self._run_governed(query, execute=True)

    async def search_data_model(self, text: str, model: str | None = None) -> list[dict]:
        """Search only members from models authorized for the current subject."""
        context = self._context()
        roles = frozenset(context.roles)
        names = [model] if model is not None else sorted(self._models)
        authorized: dict[str, bool] = {}
        for name in names:
            loaded = self._models.get(name)
            if loaded is None:
                continue
            try:
                await self._pbac.authorize_manifest(context, loaded)
            except SemanticAccessError:
                authorized[name] = False
            else:
                authorized[name] = True
        return self._catalog.search(text, roles, model, authorized=authorized)

    async def list_saved_queries(self, model: str) -> list[dict]:
        """List saved queries whose referenced members are all authorized."""
        loaded, roles = await self._authorized_model(model)
        result: list[dict] = []
        for saved in loaded.policy.saved_queries:
            try:
                self._catalog.check_query_rights(saved.query, roles)
            except SemanticAccessError:
                continue
            result.append({"name": saved.name, "description": saved.description})
        return result

    async def compile_query(self, query: SemanticQuery) -> dict:
        """Return audited governed SQL without database execution."""
        result = await self._run_governed(query, execute=False)
        return result

    async def query_metrics(self, query: SemanticQuery) -> SemanticQueryResult:
        """Authorize, compile, govern, execute and audit before returning rows."""
        result = await self._run_governed(query, execute=True)
        assert isinstance(result, SemanticQueryResult)
        return result

    def reload(self) -> None:
        """Reload complete model snapshots and invalidate their compilation cache entries."""
        previous = self._models
        if not self._loader.reload_if_changed():
            return
        self._models = self._loader.load()
        for model in previous.values():
            self._cache.invalidate_model(model.model_digest)
        for model in self._models.values():
            for rule in model.policy.rls:
                self._rls_registry.register(rule)
        self._catalog = RoleCatalog(self._models)

    def _context(self) -> Any:
        """Return the current trusted context or fail closed."""
        context = current_pctx()
        if context is None:
            raise SemanticAccessError("context_required", "A trusted semantic context is required")
        return context

    async def _authorized_model(self, model: str) -> tuple[LoadedModel, frozenset[str]]:
        """Resolve one model and authorize its full manifest before catalog access."""
        loaded = self._models.get(model)
        if loaded is None:
            raise SemanticAccessError("model_not_found", "Unknown or inaccessible model")
        context = self._context()
        await self._pbac.authorize_manifest(context, loaded)
        return loaded, frozenset(context.roles)

    async def _run_governed(self, query: SemanticQuery, *, execute: bool) -> SemanticQueryResult | dict:
        """Run the shared manifest-authorize, compile, govern, audit pipeline."""
        started = perf_counter()
        loaded = self._models.get(query.model)
        compiled_sql: str | None = None
        governed: GovernedQuery | None = None
        rows: list[dict] = []
        columns: list[str] = []
        truncated = False
        try:
            context = self._context()
            if loaded is None:
                raise SemanticAccessError("model_not_found", "Unknown or inaccessible model")
            roles = frozenset(context.roles)
            await self._pbac.authorize_manifest(context, loaded)
            expanded = self._catalog.expand_saved_query(query)
            self._catalog.check_query_rights(expanded, roles)
            compiled = await compile_query_sql(expanded, loaded, self._dialect, cache=self._cache)
            compiled_sql = compiled.sql
            governed = await self._pipeline.govern(compiled.sql, model=loaded, ctx=context, roles=roles)
            if not execute:
                audit_id = await self._audit(loaded, expanded, governed, compiled_sql, "ok", None, started)
                return {"sql": governed.sql, "audit_id": audit_id, "members": list(governed.members)}
            rows, row_count, truncated, duration_ms, columns = await self._executor.run_with_columns(
                governed, connection=loaded.policy.connection
            )
            audit_id = await self._audit(loaded, expanded, governed, compiled_sql, "ok", None, started, row_count)
            result_id = self._retain(loaded, governed, columns, rows, audit_id)
            return SemanticQueryResult(
                columns=columns,
                rows=rows,
                row_count=row_count,
                truncated=truncated,
                duration_ms=duration_ms,
                compiled_sql=governed.sql,
                audit_id=audit_id,
                result_id=result_id,
            )
        except SemanticError as error:
            if loaded is not None:
                outcome = "denied" if isinstance(error, SemanticAccessError) else "validation_error"
                if error.code in {"execution_failed", "no_credentials", "no_source", "audit_unavailable"}:
                    outcome = "execution_error"
                await self._audit(loaded, query, governed, compiled_sql, outcome, error.code, started)
            raise

    async def _audit(
        self,
        loaded: LoadedModel,
        query: SemanticQuery,
        governed: GovernedQuery | None,
        compiled_sql: str | None,
        outcome: str,
        error_code: str | None,
        started: float,
        row_count: int | None = None,
    ) -> str:
        """Append one audit record, withholding results when durable audit is required."""
        context = current_pctx()
        if context is None:
            raise SemanticAccessError("context_required", "A trusted semantic context is required")
        entry = SemanticAuditEntry(
            entry_id=str(uuid4()), created_at=datetime.now(timezone.utc), user_id=context.user_id,
            tenant_id=context.tenant_id, channel="agent", agent_id=current_identity().agent_id if current_identity() else None,
            subject_digest=governed.subject_digest if governed else "unavailable", roles=sorted(context.roles),
            static_subject=False, model=loaded.name, model_digest=loaded.model_digest, policy_digest=loaded.policy_digest,
            tool="query_metrics", structured_query=query.model_dump(mode="json"), raw_sql=False,
            compiled_sql=compiled_sql, governed_sql=governed.sql if governed else None, dialect=self._dialect,
            driver=loaded.schema.driver, rls_applied=list(governed.rls_applied) if governed else [],
            masked_columns=list(governed.masked_columns) if governed else [],
            pbac="allow" if governed else "deny", outcome=outcome, error_code=error_code, row_count=row_count,
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return (await self._ledger.append(entry, required=self._audit_required)).entry_id

    def _retain(
        self, loaded: LoadedModel, governed: GovernedQuery, columns: list[str], rows: list[dict], audit_id: str
    ) -> str | None:
        """Store a result only when a complete host-bound identity is present."""
        identity = current_identity()
        if identity is None:
            return None
        identity = require_identity()
        handle = ResultHandle(
            result_id="pending", agent_id=identity.agent_id, user_id=identity.ctx.user_id,
            tenant_id=identity.ctx.tenant_id, session_id=identity.session_id, subject_digest=governed.subject_digest,
            model=loaded.name, model_digest=loaded.model_digest, policy_digest=loaded.policy_digest,
            expires_at=datetime.now(timezone.utc), members=governed.members, physical_columns=governed.physical_columns,
            physical_tables=governed.tables, columns=columns, rows=rows, audit_id=audit_id, governed_sql=governed.sql,
        )
        return self._handles.put(handle)
