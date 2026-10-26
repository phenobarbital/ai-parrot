"""Trusted stdio-only semantic toolkit bootstrap; never an HTTP identity fallback."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from parrot.auth import DataPlanePolicyGuard, PermissionContext, RlsRegistry, UserSession
from parrot.tools.toolkit import ToolkitTool
from pydantic import BaseModel, Field

from .audit import SemanticAuditEntry
from .context import SemanticRequestIdentity, bind_semantic_context, current_identity, current_pctx
from .errors import SemanticAccessError, SemanticPolicyError
from .loader import LoadedModel
from .models import GovernedQuery, SemanticQuery
from .results import ResultHandle
from .toolkit import SemanticLayerToolkit

_EVALUATOR_MODULES = (
    "navigator_auth.abac.policies.environment",
    "navigator_auth.abac.policies.evaluator",
)


class StaticSubject(BaseModel):
    """Trusted local operator identity, never accepted as a tool argument."""

    user_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    roles: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class LocalSemanticToolkitTool(ToolkitTool):
    """Bind the immutable local operator identity around one tool call."""

    def __init__(self, *args: Any, local_toolkit: "LocalSemanticLayerToolkit", **kwargs: Any) -> None:
        """Initialize the generated tool with its local-only toolkit owner."""
        self._local_toolkit = local_toolkit
        super().__init__(*args, **kwargs)

    async def _execute(self, **kwargs: Any) -> Any:
        """Execute with the configured identity regardless of caller arguments."""
        previous_context = getattr(self, "_current_pctx", None)
        self._current_pctx = self._local_toolkit._static_permission_context
        self._local_toolkit.logger.info(
            "semantic static subject call tool=%s user=%s agent=%s",
            self.name,
            self._local_toolkit._static_permission_context.user_id,
            self._local_toolkit._static_identity.agent_id,
        )
        try:
            async with bind_semantic_context(
                self._local_toolkit._static_permission_context,
                identity=self._local_toolkit._static_identity,
            ):
                return await super()._execute(**kwargs)
        finally:
            self._current_pctx = previous_context


class LocalSemanticLayerToolkit(SemanticLayerToolkit):
    """Stdio-local subclass that builds its configured PBAC guard at startup."""

    local_only = True

    def __init__(
        self,
        *,
        static_subject: StaticSubject | dict[str, Any],
        agent_id: str,
        guard_factory: str,
        guard_factory_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Resolve trusted factory, validate evaluator, create local process session.

        Args:
            static_subject: Trusted host configuration for the sole local operator.
            agent_id: Host-configured semantic agent identifier.
            guard_factory: Dotted host factory that creates a PBAC guard.
            guard_factory_kwargs: Non-secret host configuration for the factory.
            **kwargs: Ordinary :class:`SemanticLayerToolkit` constructor settings.

        Raises:
            SemanticPolicyError: If local identity or PBAC setup is invalid.
        """
        try:
            subject = StaticSubject.model_validate(static_subject)
        except Exception as exc:  # noqa: BLE001 - Pydantic reports malformed host configuration
            raise SemanticPolicyError("invalid_static_subject", "Invalid local static subject") from exc
        if not agent_id.strip():
            raise SemanticPolicyError("invalid_agent_id", "A non-empty local agent_id is required")
        if not isinstance(guard_factory, str) or not guard_factory.strip():
            raise SemanticPolicyError("guard_factory_required", "A configured guard_factory is required")
        if guard_factory_kwargs is not None and not isinstance(guard_factory_kwargs, dict):
            raise SemanticPolicyError("invalid_guard_factory_kwargs", "guard_factory_kwargs must be a mapping")

        self._require_evaluator_modules()
        rls_registry = RlsRegistry()
        guard = self._build_guard(guard_factory, rls_registry, guard_factory_kwargs or {})
        self._static_permission_context = PermissionContext(
            session=UserSession(
                user_id=subject.user_id,
                tenant_id=subject.tenant_id,
                roles=frozenset(subject.roles),
                metadata=dict(subject.metadata),
            ),
            channel="mcp-local",
        )
        self._static_identity = SemanticRequestIdentity(
            ctx=self._static_permission_context,
            channel="mcp-local",
            agent_id=agent_id,
            session_id=str(uuid4()),
        )
        super().__init__(dataplane_guard=guard, rls_registry=rls_registry, **kwargs)

    @staticmethod
    def _require_evaluator_modules() -> None:
        """Require the exact navigator-auth modules used by the PBAC gate."""
        try:
            evaluator_module, environment_module = (
                importlib.import_module(module) for module in reversed(_EVALUATOR_MODULES)
            )
            evaluator_module.PolicyEvaluator
            environment_module.Environment
        except (AttributeError, ImportError, ModuleNotFoundError) as exc:
            raise SemanticPolicyError("pbac_unavailable", "Required PBAC evaluator modules are unavailable") from exc

    @staticmethod
    def _build_guard(
        factory_path: str, rls_registry: RlsRegistry, factory_kwargs: dict[str, Any]
    ) -> DataPlanePolicyGuard:
        """Load and invoke a trusted host PBAC guard factory.

        Args:
            factory_path: Dotted callable path from host configuration.
            rls_registry: Registry shared with the semantic toolkit.
            factory_kwargs: Non-secret factory configuration.

        Returns:
            Configured data-plane guard.

        Raises:
            SemanticPolicyError: If the configured factory cannot provide a valid guard.
        """
        try:
            module_path, attribute = factory_path.rsplit(".", 1)
            factory = getattr(importlib.import_module(module_path), attribute)
        except (AttributeError, ImportError, ModuleNotFoundError, ValueError) as exc:
            raise SemanticPolicyError("invalid_guard_factory", "Configured guard_factory cannot be loaded") from exc
        if not callable(factory):
            raise SemanticPolicyError("invalid_guard_factory", "Configured guard_factory must be callable")
        try:
            guard = factory(rls_registry=rls_registry, **factory_kwargs)
        except Exception as exc:  # noqa: BLE001 - policy construction must fail startup
            raise SemanticPolicyError("guard_factory_failed", "Configured PBAC policy could not be loaded") from exc
        if not isinstance(guard, DataPlanePolicyGuard) or getattr(guard, "_evaluator", None) is None:
            raise SemanticPolicyError(
                "invalid_policy_guard", "guard_factory must return a configured DataPlanePolicyGuard"
            )
        return guard

    def _create_tool_from_method(self, name: str, bound_method: callable) -> ToolkitTool:
        """Create tools that always bind this toolkit's configured local identity."""
        base_tool = super()._create_tool_from_method(name, bound_method)
        local_tool = LocalSemanticToolkitTool(
            name=base_tool.name,
            bound_method=bound_method,
            description=base_tool.description,
            args_schema=base_tool.args_schema,
            return_direct=base_tool.return_direct,
            executor=base_tool.executor,
            webhook_callback_url=base_tool.webhook_callback_url,
            remote_timeout_seconds=base_tool.remote_timeout_seconds,
            local_toolkit=self,
        )
        for attribute in ("_required_permissions", "credential_provider", "routing_meta"):
            if hasattr(base_tool, attribute):
                setattr(local_tool, attribute, getattr(base_tool, attribute))
        return local_tool

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
        """Record semantic audit events with immutable local identity metadata."""
        context = current_pctx()
        if context is None or current_identity() != self._static_identity:
            raise SemanticAccessError("context_required", "A matching local semantic context is required")
        entry = SemanticAuditEntry(
            entry_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            channel="mcp-local",
            agent_id=self._static_identity.agent_id,
            subject_digest=governed.subject_digest if governed else handle.subject_digest if handle else "unavailable",
            roles=sorted(context.roles),
            static_subject=True,
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
            pbac="allow" if governed or (handle is not None and outcome == "ok") else "deny",
            outcome=outcome,
            error_code=error_code,
            row_count=row_count,
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return (await self._ledger.append(entry, required=self._audit_required)).entry_id
