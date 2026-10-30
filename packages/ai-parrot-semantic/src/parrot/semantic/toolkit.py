"""Governed semantic tools with trusted host-bound request identity."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from parrot.auth import RlsRegistry, RlsRule
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.toolkit import AbstractToolkit

from .audit import SemanticAuditEntry, SemanticAuditLedger
from .cache import CompileCache
from .catalog import RoleCatalog
from .context import SemanticRequestIdentity, current_identity, current_pctx, require_identity
from .engines import compile as compile_query_sql
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

from .errors import SemanticAccessError, SemanticError, SemanticPolicyError, SemanticResultError
from .execution import ConnectionResolver, Executor
from .handoff import GovernedDatasetSink, GovernedSinkRegistry, build_read_authorizer
from .governance.pbac import PbacGate
from .governance.pipeline import GovernancePipeline, subject_digest
from .governance.rls import RlsPushdown
from .loader import LoadedModel, SemanticModelLoader
from .models import GovernedQuery, SemanticQuery, SemanticQueryResult
from .results import ResultHandle, ResultHandleStore


class SemanticLayerToolkit(AbstractToolkit):
    """Catalog, compile and metric query surface over one governance pipeline."""

    tool_prefix = "sl"
    exclude_tools = ("reload",)

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
        allow_raw_sql = kwargs.pop("allow_raw_sql", False)
        dataset_manager_factory = kwargs.pop("dataset_manager_factory", None)
        if static_subject is not None:
            raise SemanticPolicyError(
                "static_subject_forbidden", "Static identity requires the local bootstrap toolkit"
            )
        if not isinstance(allow_raw_sql, bool):
            raise SemanticPolicyError("invalid_allow_raw_sql", "allow_raw_sql must be a boolean host setting")
        if dataset_manager_factory is not None and not callable(dataset_manager_factory):
            raise SemanticPolicyError("invalid_sink_factory", "dataset_manager_factory must be callable")

        super().__init__(**kwargs)
        self._dialect = dialect
        self._loader = SemanticModelLoader(models_dir, driver=dialect)
        self._models = self._loader.load()
        if any(model.policy.governed for model in self._models.values()) and dataplane_guard is None:
            raise SemanticPolicyError("guard_required", "Governed semantic models require a data-plane guard")

        self._rls_registry = rls_registry or RlsRegistry()
        self._owned_rls: dict[tuple[str, str], RlsRule] = {}
        self._sync_rls(self._models)
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
        self._allow_raw_sql: bool = allow_raw_sql
        self._sink_factory: Callable[[SemanticRequestIdentity], Awaitable[GovernedDatasetSink]] | None = (
            dataset_manager_factory
        )
        self._sinks = GovernedSinkRegistry()
        # Per-instance exposure: host configuration only, never a caller/LLM flag.
        excluded = tuple(self.exclude_tools)
        if not self._allow_raw_sql:
            excluded += ("run_sql",)
        if self._sink_factory is None:
            excluded += ("save_result_as_dataset",)
        self.exclude_tools = excluded

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
        return [
            member.model_dump()
            for member in self._catalog.visible_members(loaded.name, roles, authorized=True)
            if member.kind == "metric"
        ]

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
        """Return audited pre-RLS compiled SQL without database execution; governed SQL stays in the audit."""
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
        models = self._loader.load()
        # Validate RLS ownership before swapping the snapshot so a conflicting
        # policy file leaves the previous models and rules in force.
        self._sync_rls(models)
        self._models = models
        for model in previous.values():
            self._cache.invalidate_model(model.model_digest)
        self._catalog = RoleCatalog(self._models)

    def _sync_rls(self, models: dict[str, LoadedModel]) -> None:
        """Register policy-file RLS rules without overriding rules this toolkit does not own.

        The shared :class:`RlsRegistry` is keyed by ``(driver, table)`` with
        last-write-wins semantics, so a policy file could silently replace a
        host-registered rule.  Every key is therefore checked first: a key
        already held by a different rule that this toolkit did not register
        fails loudly, as do two models declaring different rules for one key.
        Nothing is registered unless the whole set is conflict-free.

        ``RlsRegistry`` exposes no unregister API, so a rule removed from a
        policy file on reload stays registered (fail-safe: it only narrows
        rows) and stays owned by this toolkit; a warning names it.

        Args:
            models: Complete model snapshot whose policy rules to register.

        Raises:
            SemanticPolicyError: ``rls_conflict`` when a rule would override a
                foreign rule or two models disagree on the same key.
        """
        desired: dict[tuple[str, str], RlsRule] = {}
        for model in models.values():
            for rule in model.policy.rls:
                key = (rule.driver, rule.table)
                if key in desired and desired[key] != rule:
                    raise SemanticPolicyError(
                        "rls_conflict", f"Conflicting RLS rules for {rule.driver}:{rule.table} across semantic models"
                    )
                desired[key] = rule
        for key, rule in desired.items():
            if key in self._owned_rls:
                continue
            existing = self._rls_registry.lookup(key[0], {key[1]})
            if existing and existing[0] != rule:
                raise SemanticPolicyError(
                    "rls_conflict",
                    f"RLS rule for {key[0]}:{key[1]} is already registered by the host; refusing to override it",
                )
        for key, rule in desired.items():
            owned = key in self._owned_rls
            if not owned and self._rls_registry.lookup(key[0], {key[1]}):
                continue  # identical rule already registered by its owner; do not claim it
            self._rls_registry.register(rule)
            self._owned_rls[key] = rule
        for key in sorted(set(self._owned_rls) - set(desired)):
            self.logger.warning(
                "RLS rule for %s:%s was removed from its policy file but RlsRegistry has no unregister API; "
                "it stays in force until restart",
                key[0],
                key[1],
            )

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
                # Callers see the pre-RLS compiled SQL; governed SQL (RLS literals, hidden
                # physical columns) is recorded only in the audit entry.
                return {"sql": compiled_sql, "audit_id": audit_id, "members": list(governed.members)}
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
                compiled_sql=compiled_sql,
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
        except Exception as exc:
            self.logger.error("Semantic query failed unexpectedly: %s", type(exc).__name__)
            if loaded is not None:
                await self._audit(loaded, query, governed, compiled_sql, "execution_error", _UNEXPECTED, started)
            raise _unexpected() from exc

    async def _audit(
        self,
        loaded: LoadedModel,
        query: SemanticQuery | None,
        governed: GovernedQuery | None,
        compiled_sql: str | None,
        outcome: str,
        error_code: str | None,
        started: float,
        row_count: int | None = None,
        *,
        tool: str = "query_metrics",
        raw_sql: bool = False,
        handle: ResultHandle | None = None,
        structured: dict | None = None,
    ) -> str:
        """Append one audit record, withholding results when durable audit is required.

        Args:
            loaded: Model snapshot the call ran against.
            query: Structured query, or ``None`` for raw SQL and hand-off calls.
            governed: Governed query when governance completed.
            compiled_sql: Compiled or caller-supplied SQL text.
            outcome: Audit outcome literal.
            error_code: Stable error code on failure.
            started: ``perf_counter`` value at call start.
            row_count: Rows returned or published.
            tool: Tool name recorded in the entry.
            raw_sql: Whether the SQL came from the caller.
            handle: Claimed result handle for hand-off audit records.
            structured: Explicit structured payload overriding ``query``.

        Returns:
            The audit entry identifier.
        """
        context, channel, agent_id, static_subject = self._audit_identity()
        entry = SemanticAuditEntry(
            entry_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            channel=channel,
            agent_id=agent_id,
            subject_digest=(
                governed.subject_digest if governed else handle.subject_digest if handle else "unavailable"
            ),
            roles=sorted(context.roles),
            static_subject=static_subject,
            model=loaded.name,
            model_digest=loaded.model_digest,
            policy_digest=loaded.policy_digest,
            tool=tool,
            structured_query=structured if structured is not None else query.model_dump(mode="json") if query else None,
            raw_sql=raw_sql,
            compiled_sql=compiled_sql,
            governed_sql=governed.sql if governed else handle.governed_sql if handle else None,
            dialect=self._dialect,
            driver=loaded.schema.driver,
            rls_applied=list(governed.rls_applied) if governed else [],
            masked_columns=list(governed.masked_columns) if governed else [],
            pbac=_pbac_outcome(loaded, governed, handle, outcome, error_code),
            outcome=outcome,
            error_code=error_code,
            row_count=row_count,
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return (await self._ledger.append(entry, required=self._audit_required)).entry_id

    def _audit_identity(self) -> tuple[Any, str, str | None, bool]:
        """Return ``(context, channel, agent_id, static_subject)`` for an audit entry.

        Raises:
            SemanticAccessError: When no trusted context is bound.
        """
        context = current_pctx()
        if context is None:
            raise SemanticAccessError("context_required", "A trusted semantic context is required")
        identity = current_identity()
        return context, "agent", identity.agent_id if identity else None, False

    def _retain(
        self, loaded: LoadedModel, governed: GovernedQuery, columns: list[str], rows: list[dict], audit_id: str
    ) -> str | None:
        """Store a result only when a complete host-bound identity is present."""
        identity = current_identity()
        if identity is None:
            return None
        identity = require_identity()
        handle = ResultHandle(
            result_id="pending",
            agent_id=identity.agent_id,
            user_id=identity.ctx.user_id,
            tenant_id=identity.ctx.tenant_id,
            session_id=identity.session_id,
            subject_digest=governed.subject_digest,
            model=loaded.name,
            model_digest=loaded.model_digest,
            policy_digest=loaded.policy_digest,
            expires_at=datetime.now(timezone.utc),
            members=governed.members,
            physical_columns=governed.physical_columns,
            physical_tables=governed.tables,
            columns=columns,
            rows=rows,
            audit_id=audit_id,
            governed_sql=governed.sql,
        )
        return self._handles.put(handle)

    async def run_sql(self, model: str, sql: str) -> SemanticQueryResult:
        """Run opt-in SQL through identical governance, provenance and audit checks.

        The SQL is authorized against the model manifest, governed by the same
        pipeline as structured queries (validation, lineage, usage rights, RLS,
        masking, positive guard, PBAC), every resolved semantic member must be
        granted, and the call is audited before rows are returned.

        Args:
            model: Semantic model whose physical schema the SQL addresses.
            sql: Caller-supplied read-only SQL.

        Returns:
            Governed rows, with a retained handle carrying exact physical provenance.

        Raises:
            SemanticAccessError: When raw SQL is disabled or any governance check denies.
        """
        if not self._allow_raw_sql:
            raise SemanticAccessError("raw_sql_disabled", "Raw SQL execution is not enabled")
        started = perf_counter()
        loaded = self._models.get(model)
        governed: GovernedQuery | None = None
        structured = {"model": model}
        try:
            context = self._context()
            if loaded is None:
                raise SemanticAccessError("model_not_found", "Unknown or inaccessible model")
            roles = frozenset(context.roles)
            await self._pbac.authorize_manifest(context, loaded)
            governed = await self._pipeline.govern(sql, model=loaded, ctx=context, roles=roles)
            self._check_members(loaded, governed.members, roles)
            await self._check_raw_projection(loaded, sql, governed, roles)
            rows, row_count, truncated, duration_ms, columns = await self._executor.run_with_columns(
                governed, connection=loaded.policy.connection
            )
            audit_id = await self._audit(
                loaded,
                None,
                governed,
                sql,
                "ok",
                None,
                started,
                row_count,
                tool="run_sql",
                raw_sql=True,
                structured=structured,
            )
            result_id = self._retain(loaded, governed, columns, rows, audit_id)
            return SemanticQueryResult(
                columns=columns,
                rows=rows,
                row_count=row_count,
                truncated=truncated,
                duration_ms=duration_ms,
                compiled_sql=sql,
                audit_id=audit_id,
                result_id=result_id,
            )
        except SemanticError as error:
            if loaded is not None:
                outcome = "denied" if isinstance(error, SemanticAccessError) else "validation_error"
                if error.code in {"execution_failed", "no_credentials", "no_source", "audit_unavailable"}:
                    outcome = "execution_error"
                await self._audit(
                    loaded,
                    None,
                    governed,
                    sql,
                    outcome,
                    error.code,
                    started,
                    tool="run_sql",
                    raw_sql=True,
                    structured=structured,
                )
            raise
        except Exception as exc:
            self.logger.error("Semantic raw SQL failed unexpectedly: %s", type(exc).__name__)
            if loaded is not None:
                await self._audit(
                    loaded,
                    None,
                    governed,
                    sql,
                    "execution_error",
                    _UNEXPECTED,
                    started,
                    tool="run_sql",
                    raw_sql=True,
                    structured=structured,
                )
            raise _unexpected() from exc

    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict:
        """Publish an owned result only through a conforming guarded host sink.

        The handle is claimed with the trusted identity and the current subject,
        model and policy versions; every retained member, physical column and
        table is re-authorized (catalog grants, usage grants, PBAC) before the
        registered guarded sink publishes it with a read authorizer that rechecks
        everything again on every downstream exposure.

        Args:
            result_id: Opaque handle returned by a previous governed query.
            name: Dataset name inside the caller's private sink scope.
            description: Optional human description recorded with the publication.

        Returns:
            Publication metadata from the sink plus the audit identifier.

        Raises:
            SemanticResultError: When hand-off is unavailable, the handle cannot be
                claimed, the sink is rejected, or any re-authorization fails.
        """
        if self._sink_factory is None:
            raise SemanticResultError("handoff_unavailable", "Dataset hand-off is not configured")
        if not isinstance(name, str) or not name.strip():
            raise SemanticResultError("invalid_dataset_name", "Dataset name must not be blank")
        started = perf_counter()
        identity = require_identity()
        context = self._context()
        structured = {"dataset_name": name, "description": description}
        try:
            handle, loaded = self._claim(result_id, identity, context)
        except Exception as exc:
            await self._audit_claim_failure(result_id, exc, started, structured)
            if isinstance(exc, SemanticError):
                raise
            raise _unexpected() from exc
        try:
            roles = frozenset(context.roles)
            await self._recheck_handle(handle, loaded, context, roles)
            sink = await self._dataset_manager_for(identity)
            authorize_read = build_read_authorizer(
                handle,
                models=lambda: self._models,
                catalog=lambda: self._catalog,
                pbac=self._pbac,
            )
            published = await self._sinks.publish(sink, name, handle, authorize_read, identity=identity)
            # Reject reload races: the version snapshot must still be current before returning.
            current = self._models.get(handle.model)
            if (
                current is None
                or current.model_digest != handle.model_digest
                or current.policy_digest != handle.policy_digest
            ):
                raise SemanticResultError("result_unavailable", "Result is unavailable")
            audit_id = await self._audit(
                loaded,
                None,
                None,
                None,
                "ok",
                None,
                started,
                len(handle.rows),
                tool="save_result_as_dataset",
                handle=handle,
                structured=structured,
            )
        except SemanticError as error:
            outcome = "denied" if isinstance(error, (SemanticAccessError, SemanticResultError)) else "validation_error"
            await self._audit(
                loaded,
                None,
                None,
                None,
                outcome,
                error.code,
                started,
                tool="save_result_as_dataset",
                handle=handle,
                structured=structured,
            )
            raise
        except Exception as exc:
            self.logger.error("Semantic dataset hand-off failed unexpectedly: %s", type(exc).__name__)
            await self._audit(
                loaded,
                None,
                None,
                None,
                "execution_error",
                _UNEXPECTED,
                started,
                tool="save_result_as_dataset",
                handle=handle,
                structured=structured,
            )
            raise _unexpected() from exc
        return {**published, "audit_id": audit_id}

    async def _audit_claim_failure(self, result_id: str, error: Exception, started: float, structured: dict) -> None:
        """Audit a failed handle claim against the handle's model, or the first loaded model."""
        stored = self._handles._data.get(result_id) if isinstance(result_id, str) else None
        loaded = self._models.get(stored.model) if stored is not None else None
        if loaded is None and self._models:
            loaded = self._models[sorted(self._models)[0]]
        if loaded is None:
            return
        if isinstance(error, SemanticError):
            outcome, code = "denied", error.code
        else:
            self.logger.error("Semantic handle claim failed unexpectedly: %s", type(error).__name__)
            outcome, code = "execution_error", _UNEXPECTED
        await self._audit(
            loaded,
            None,
            None,
            None,
            outcome,
            code,
            started,
            tool="save_result_as_dataset",
            structured=structured,
        )

    def _claim(
        self, result_id: str, identity: SemanticRequestIdentity, context: Any
    ) -> tuple[ResultHandle, LoadedModel]:
        """Claim a handle for the exact owner, subject and current model/policy versions."""
        if not isinstance(result_id, str) or not result_id.strip():
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        if handle_owner_of(identity) != (
            identity.agent_id,
            context.user_id,
            context.tenant_id,
            identity.session_id,
        ):
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        digest = subject_digest(context)
        for loaded in self._models.values():
            try:
                handle = self._handles.claim(
                    result_id,
                    identity=identity,
                    subject_digest=digest,
                    model_digest=loaded.model_digest,
                    policy_digest=loaded.policy_digest,
                )
            except SemanticResultError:
                continue
            if handle.model == loaded.name:
                return handle, loaded
        raise SemanticResultError("result_unavailable", "Result is unavailable")

    def _check_members(self, loaded: LoadedModel, members: tuple[str, ...], roles: frozenset[str]) -> None:
        """Require every member to be granted; one visible member never covers another."""
        if not loaded.policy.governed:
            return
        visible = {member.name for member in self._catalog.visible_members(loaded.name, roles, authorized=True)}
        hidden = [member for member in members if member not in visible]
        if hidden:
            raise SemanticAccessError("member_not_granted", "Result references a member that is not granted")

    def _granted_member_columns(self, loaded: LoadedModel, roles: frozenset[str]) -> set[str]:
        """Return root-table physical columns backing members granted to the roles."""
        root = loaded.model
        granted = {member.name for member in self._catalog.visible_members(loaded.name, roles, authorized=True)}
        return {
            f"{root.table}.{item.column}"
            for item in (*root.dimensions, *root.metrics)
            if item.name in granted and getattr(item, "column", None)
        }

    async def _check_raw_projection(
        self, loaded: LoadedModel, sql: str, governed: GovernedQuery, roles: frozenset[str]
    ) -> None:
        """Bind raw SQL to the root model's table and its granted members.

        Every table must be the root model's own table (other models' tables are
        governed by their own policies and are never reachable through raw SQL).
        Every projected physical column must back a granted member of the root
        model; non-projection uses must back a granted member or carry usage rights.

        Raises:
            SemanticAccessError: When a table or column is not covered.
        """
        if not loaded.policy.governed:
            return
        root_table = loaded.model.table
        if any(table != root_table for table in governed.tables):
            raise SemanticAccessError("outside_model", "Raw SQL references a table outside the model")
        prepared = await asyncio.to_thread(self._pipeline._prepare, sql, loaded, self._dialect)
        member_columns = self._granted_member_columns(loaded, roles)
        for use in prepared.uses:
            column = f"{use.table}.{use.column}"
            if use.table != root_table:
                raise SemanticAccessError("outside_model", "Raw SQL references a table outside the model")
            if column in member_columns:
                continue
            if use.context == "projection" or not loaded.policy.usage_allowed(roles, column):
                raise SemanticAccessError("member_not_granted", "Raw SQL uses a column that is not granted")

    async def _recheck_handle(
        self, handle: ResultHandle, loaded: LoadedModel, context: Any, roles: frozenset[str]
    ) -> None:
        """Re-authorize every retained member, physical column/table and PBAC before publish."""
        if handle.expires_at <= datetime.now(timezone.utc):
            raise SemanticResultError("result_unavailable", "Result is unavailable")
        manifest = await self._pbac.authorize_manifest(context, loaded)
        if not loaded.policy.governed:
            return
        self._check_members(loaded, handle.members, roles)
        tables = set(handle.physical_tables)
        if not tables.issubset(loaded.schema.tables):
            raise SemanticAccessError("outside_manifest", "Result uses resources outside the model manifest")
        member_columns = self._granted_member_columns(loaded, roles)
        for column in handle.physical_columns:
            table, _, physical = column.rpartition(".")
            if table not in tables or physical not in loaded.schema.tables.get(table, {}):
                raise SemanticAccessError("outside_manifest", "Result column is outside its recorded tables")
            if column not in member_columns and not loaded.policy.usage_allowed(roles, column):
                raise SemanticAccessError("usage_not_granted", "Result uses a column that is not granted")
        driver = loaded.schema.driver
        resources = PhysicalResources(driver=driver, tables={f"{driver}:{table}" for table in tables})
        await self._pbac.authorize(context, resources, governed=True, manifest=manifest)

    async def _dataset_manager_for(self, identity: SemanticRequestIdentity) -> GovernedDatasetSink:
        """Require the M9H guarded sink capability and exact owner tuple; reject raw/shared managers."""
        if self._sink_factory is None:
            raise SemanticResultError("handoff_unavailable", "Dataset hand-off is not configured")
        produced = self._sink_factory(identity)
        sink = await produced if inspect.isawaitable(produced) else produced
        if getattr(sink, "owner", None) != handle_owner_of(identity):
            raise SemanticResultError("sink_rejected", "Sink owner does not match the trusted identity")
        self._sinks.register(sink)
        return sink


_UNEXPECTED = "internal_error"


def _pbac_outcome(
    loaded: LoadedModel,
    governed: GovernedQuery | None,
    handle: ResultHandle | None,
    outcome: str,
    error_code: str | None,
) -> str:
    """Classify the PBAC decision recorded in an audit entry.

    Returns:
        ``not_governed`` for opted-out models, ``unavailable`` when the PBAC
        evaluator could not decide, ``allow`` once governance (or a hand-off)
        succeeded, otherwise ``deny``.
    """
    if not loaded.policy.governed:
        return "not_governed"
    if error_code == "pbac_unavailable":
        return "unavailable"
    if governed is not None or (handle is not None and outcome == "ok"):
        return "allow"
    return "deny"


def _unexpected() -> SemanticError:
    """Build the opaque error raised for unexpected (non-semantic) failures."""
    return SemanticError(_UNEXPECTED, "The semantic request failed")


def handle_owner_of(identity: SemanticRequestIdentity) -> tuple[str, str, str, str]:
    """Return the (agent, user, tenant, session) owner tuple of a trusted identity."""
    return (identity.agent_id, identity.ctx.user_id, identity.ctx.tenant_id, identity.session_id)
