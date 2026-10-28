"""REST lane of the FEAT-756 metric registry: /api/v1/metrics[/schema|/{metric_id}]."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from parrot.handlers.models.metric_definitions import MetricVersionConflict, PgMetricDefinitionStore
from parrot.handlers.scope import RequestScope, get_scope_resolver
from parrot.handlers.ui_surfaces import _get_user_id
from parrot.metrics import MetricDefinition
from parrot.metrics.registry import MetricView
from pydantic import BaseModel, ValidationError

_SERVER_SET_FIELDS = ("tenant", "owner")


class UpsertMetricRequest(BaseModel):
    """``definition: dict`` — a ``MetricDefinition`` WITHOUT ``tenant`` / ``owner`` (server-set; 422 when present)."""

    definition: dict[str, Any]


@is_authenticated()
@user_session()
class MetricDefinitionsHandler(BaseView):
    """REST lane of the metric registry (UISurfacesHandler idiom: one view, dispatch on match_info/path)."""

    _logger_name: str = "Parrot.MetricDefinitions"

    def post_init(self, *args: Any, **kwargs: Any) -> None:
        """Create the handler logger."""
        self.logger = logging.getLogger(self._logger_name)

    @property
    def store(self) -> PgMetricDefinitionStore:
        """``app["metric_definitions_store"]`` or a lazily created ``PgMetricDefinitionStore()``."""
        store = self.request.app.get("metric_definitions_store")
        if store is None:
            store = PgMetricDefinitionStore()
            self.request.app["metric_definitions_store"] = store
        return store

    async def _scope(self) -> RequestScope:
        """Resolve the caller scope once per request."""
        return await get_scope_resolver(self.request.app).resolve(self.request)

    def _error(self, message: str, *, status: int = 400) -> web.Response:
        """Build an error response directly (BaseView.error() has a status whitelist)."""
        return self.json_response({"status": "error", "message": message}, status=status)

    async def _write_gate(self) -> tuple[str, RequestScope] | web.Response:
        """Run the 401/403 gates shared by POST and PUT; return ``(user_id, scope)`` or an error response."""
        user_id = await _get_user_id(self.request)
        if not user_id:
            return self._error("Authentication required", status=401)
        scope = await self._scope()
        if not scope.may_author:
            return self._error("Not allowed to author metric definitions", status=403)
        if scope.tenant is None and not scope.is_superuser:
            return self._error("Global metric definitions require a superuser", status=403)
        return user_id, scope

    async def _parse_definition(self, user_id: str, scope: RequestScope) -> MetricDefinition | web.Response:
        """Parse the body into a ``MetricDefinition`` with server-set tenant/owner (422 on any problem)."""
        try:
            raw = await self.request.json()
        except Exception:  # noqa: BLE001 - any body-decoding failure is a client error
            return self._error("Invalid JSON body", status=422)
        try:
            body = UpsertMetricRequest.model_validate(raw)
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc.errors(include_url=False)}", status=422)
        forbidden = [key for key in _SERVER_SET_FIELDS if key in body.definition]
        if forbidden:
            return self._error(f"Server-set fields not allowed in body: {forbidden}", status=422)
        payload = {**body.definition, "tenant": scope.tenant, "owner": user_id}
        try:
            return MetricDefinition.model_validate(payload)
        except ValidationError as exc:
            return self._error(f"Invalid metric definition: {exc.errors(include_url=False)}", status=422)

    async def _effective_view(self, scope: RequestScope) -> MetricView:
        """Compose the caller's effective view (tenant shadows global; ``global_only`` globals win)."""
        visible = await self.store.list_visible(scope)
        global_defs = [definition for definition in visible if definition.tenant is None]
        tenant_defs = [definition for definition in visible if definition.tenant is not None]
        return MetricView(global_defs, tenant_defs, tenant=scope.tenant, logger=self.logger).compose()

    async def _locked_by_global(self, definition: MetricDefinition, scope: RequestScope) -> bool:
        """Whether a tenant author targets an id reserved by a ``global_only`` global metric."""
        if scope.tenant is None:
            return False
        existing = await self.store.get(definition.id, tenant=None)
        return existing is not None and existing.global_only

    async def get(self) -> web.Response:
        """``/schema`` → JSON Schema; ``{metric_id}`` → 200 | 404; list → ``store.list_visible(scope, program=)``."""
        if self.request.path.rstrip("/").endswith("/schema"):
            return self.json_response(MetricDefinition.json_schema_v1())
        scope = await self._scope()
        metric_id = self.request.match_info.get("metric_id")
        if metric_id:
            definition = (await self._effective_view(scope)).get(metric_id)
            if definition is None:
                return self._error("Metric not found", status=404)
            return self.json_response(definition.model_dump(mode="json"))
        program = self.request.query.get("program")
        view = await self._effective_view(scope)
        return self.json_response([d.model_dump(mode="json") for d in view.list(program=program)])

    async def post(self) -> web.Response:
        """Create: 401/403/422 gates; tenant := scope.tenant; global needs is_superuser; 409 duplicate; 201."""
        gate = await self._write_gate()
        if not isinstance(gate, tuple):
            return gate
        user_id, scope = gate
        definition = await self._parse_definition(user_id, scope)
        if not isinstance(definition, MetricDefinition):
            return definition
        if await self._locked_by_global(definition, scope):
            return self._error(f"Metric id {definition.id!r} is reserved by a global_only metric", status=409)
        try:
            await self.store.save(definition, overwrite=False)
        except ValueError as exc:
            return self._error(str(exc) or "Metric already exists", status=409)
        return self.json_response(definition.model_dump(mode="json"), status=201)

    async def put(self) -> web.Response:
        """Replace: same gates; owner or may_administer only; 404 when absent; 200."""
        gate = await self._write_gate()
        if not isinstance(gate, tuple):
            return gate
        user_id, scope = gate
        metric_id = self.request.match_info.get("metric_id")
        if not metric_id:
            return self._error("metric_id is required", status=400)
        existing = await self.store.get(metric_id, tenant=scope.tenant)
        if existing is None:
            return self._error("Metric not found", status=404)
        if not (existing.owner == user_id or scope.may_administer):
            return self._error("Only the owner or an administrator may replace this metric", status=403)
        definition = await self._parse_definition(user_id, scope)
        if not isinstance(definition, MetricDefinition):
            return definition
        if definition.id != metric_id:
            return self._error("Body id must match the path metric_id", status=422)
        if await self._locked_by_global(definition, scope):
            return self._error(f"Metric id {definition.id!r} is reserved by a global_only metric", status=409)
        definition = definition.model_copy(update={"version": existing.version + 1, "owner": existing.owner or user_id})
        try:
            await self.store.save(definition, overwrite=True, expected_version=existing.version)
        except MetricVersionConflict as exc:
            return self._error(str(exc), status=409)
        return self.json_response(definition.model_dump(mode="json"), status=200)
