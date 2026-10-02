"""Agent Studio agent-level tooling endpoints (FEAT-593)."""

from __future__ import annotations

import asyncio
import inspect

from aiohttp import web
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

from parrot.tools.spec import hydrate_params, mask_mcp, mask_spec
from parrot.tools.tooling_policy import TenantToolingRefused

from ._base import StudioBaseView
from .agents import _StudioAgentsMixin
from .models import (
    AgentMcpServersPutRequest,
    AgentMcpServersResponse,
    AgentToolkitsResponse,
    StudioError,
    ToolkitConfigPutRequest,
    ToolkitOptionsResponse,
    ToolkitPersistResponse,
)
from .access import StudioTenantRequired, _store_record
from .storage import models as _studio_models
from .storage.services._common import StudioValidationError
from .tooling_store import AgentToolingStore, ServerManagedParamsRejected

_STUDIO_ERRORS = (
    _studio_models.StudioStorageUnavailable,
    _studio_models.StudioVersionConflict,
    _studio_models.StudioStaleAuthorization,
    _studio_models.StudioNameConflict,
    _studio_models.StudioNotFound,
    _studio_models.StudioToolingRefused,
    StudioValidationError,
)

_OPTIONS_TIMEOUT_S = 15.0


class _ToolingViewMixin(_StudioAgentsMixin):
    """Shared authorization and error mapping for agent tooling endpoints."""

    def _error(self, message: str, *, status: int, code: str | None = None, details: dict | None = None):
        """Return a Studio API error response."""
        return self.json_response(StudioError(message=message, code=code, details=details).model_dump(), status=status)

    async def _authorize(self, name: str, action: str):
        """PBAC gate then ownership; returns ``(store, state)`` or an error response."""
        if (denied := await self._pbac_gate("toolkits", action)) is not None:
            return denied
        store = AgentToolingStore(self)
        try:
            state = await store.load(name)
        except LookupError:
            return self._error(f"Agent '{name}' not found.", status=404, code="not_found")
        except (*_STUDIO_ERRORS, StudioTenantRequired) as exc:
            return self._studio_error(exc)
        if (denied := await self._decide_access(state, name)) is not None:
            return denied
        return store, state

    async def _decide_access(self, state, name: str):
        """404 invisible / 403 not manageable for a Studio row (the access rule); the FEAT-467 owner check otherwise."""
        if getattr(state, "source", None) == "studio":
            return await self._studio_authorize(state._studio[1], name, manage=True)
        self._require_owner(state.owner, await self._get_user())
        return None

    def _map_exc(self, exc: Exception):
        """Map persistence and vault exceptions to the Studio error contract."""
        if isinstance(exc, TenantToolingRefused):
            return self._error(str(exc), status=422, code=exc.code, details={"reason": exc.reason, "item": exc.item})
        if isinstance(exc, ServerManagedParamsRejected):
            return self._error(str(exc), status=422, code="server_managed", details={"params": exc.params})
        if isinstance(exc, _STUDIO_ERRORS):
            return self._studio_error(exc)
        if isinstance(exc, PermissionError):
            return self._error(str(exc), status=409, code="read_only_definition")
        if isinstance(exc, ValueError):
            return self._error(str(exc), status=422, code="invalid_params")
        if isinstance(exc, RuntimeError):
            return self._error("Vault service unavailable.", status=503, code="vault_unavailable")
        if isinstance(exc, LookupError):
            return self._error("Requested resource was not found.", status=404, code="not_found")
        raise exc

    async def _write(self, state, name: str, source, call):
        """Run ``call(kwargs)``; ``None`` on success, a refusal response otherwise.

        Studio rows go through the guarded write under the version the owner check authorized, re-authorized
        once on a stale one (spec §2.8). A legacy source has no version to guard: ``expected_version`` is a 400.
        """
        if getattr(state, "source", None) != "studio":
            if (refused := self._refuse_expected_version(source)) is not None:
                return refused
            await call({})
            return None
        expected = self._expected_version(source)
        storage, part, user = self._studio_storage(), await self._studio_partition(), await self._get_user()
        result = await self._studio_write(
            lambda guard: call({"guard": guard, "actor": user.user_id}),
            record=state._studio[1], reread=lambda: storage.services.agents.get(part, name),
            reauthorize=self._reauthorize("agent", name), expected_version=expected,
        )
        return result if isinstance(result, web.Response) else None

    @staticmethod
    def _is_error_response(value):
        """Return whether an authorization helper result is an HTTP response."""
        return not isinstance(value, tuple)


@is_authenticated()
@user_session()
class StudioAgentToolkitsHandler(_ToolingViewMixin, StudioBaseView):
    """GET list and PUT/DELETE one toolkit's agent-level config."""

    async def get(self):
        """Return masked persisted toolkit specifications for an agent."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:toolkits:persist")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        store, state = authorized
        unavailable = []
        for spec in state.tooling.toolkits:
            try:
                store.schema_for(spec.slug)
            except LookupError:
                unavailable.append(spec.slug)
        response = AgentToolkitsResponse(
            agent=name,
            editable=state.editable,
            reason=state.reason,
            toolkits=[mask_spec(spec) for spec in state.tooling.toolkits],
            unavailable=unavailable,
        )
        return self.json_response(response.model_dump())

    async def put(self):
        """Persist one agent-level toolkit specification."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:toolkits:persist")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        try:
            payload = await self.request.json()
        except Exception:
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            request = ToolkitConfigPutRequest(**(payload or {}))
        except (ValidationError, ValueError) as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")
        store, state = authorized
        try:
            refused = await self._write(
                state, name, payload,
                lambda kw: store.put_toolkit(name, slug, request.params, request.user_overridable, **kw),
            )
        except Exception as exc:
            return self._map_exc(exc)
        if refused is not None:
            return refused
        return self.json_response(ToolkitPersistResponse(agent=name, slug=slug).model_dump())

    async def delete(self):
        """Delete one agent-level toolkit specification."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:toolkits:persist")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        store, state = authorized
        try:
            refused = await self._write(
                state, name, self.request.query,
                lambda kw: store.delete_toolkit(name, slug, **kw),
            )
        except Exception as exc:
            return self._map_exc(exc)
        if refused is not None:
            return refused
        return self.json_response(ToolkitPersistResponse(agent=name, slug=slug).model_dump())


@is_authenticated()
@user_session()
class StudioToolkitOptionsHandler(_ToolingViewMixin, StudioBaseView):
    """GET dynamic options evaluated on the persisted spec only."""

    def _options_refusal(self, cls, slug: str, param: str):
        """403 ``tool_scope_unavailable`` for a tenant-bound toolkit without a scope; 404 for an unknown parameter."""
        if (refused := self._scope_refusal(cls, slug)) is not None:
            return refused
        if param not in cls.options_params:
            return self._error(f"Unknown options parameter '{param}'.", status=404, code="not_found")
        return None

    async def get(self):
        """Return dynamic options without accepting request-provided configuration."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:toolkits:options")
        if self._is_error_response(authorized):
            return authorized
        slug = self.request.match_info.get("slug")
        param = self.request.match_info.get("param")
        store, state = authorized
        try:
            cls, _ = store.schema_for(slug)
        except LookupError as exc:
            return self._map_exc(exc)
        async with self._bound_scope(await self._state_agent_ref(state)):   # the agent's own reference (C16)
            return await self._load_options(cls, state, slug, param)

    async def _state_agent_ref(self, state):
        """The :class:`StudioAgentRef` of a Studio row (access rule view), or ``None`` for a legacy agent."""
        if getattr(state, "source", None) != "studio":
            return None
        rec = state._studio[1]
        return (await self._access()).agent_ref(_store_record("agent", rec.agent_id, rec))

    async def _load_options(self, cls, state, slug: str, param: str):
        """Scope gate, then the persisted spec's options (vault read and construction come after the gate)."""
        if (refused := self._options_refusal(cls, slug, param)) is not None:
            return refused  # the scope gate runs before hydrate_params (vault read) and before construction
        spec = next((item for item in state.tooling.toolkits if item.slug.lower() == slug.lower()), None)
        if spec is None:
            return self._error("Toolkit is not configured.", status=409, code="not_configured")
        instance = None
        try:
            hydrated = await hydrate_params(spec)
            ctor_params = inspect.signature(cls).parameters
            params = {key: value for key, value in hydrated.items() if key in ctor_params}
            instance = cls(**params)
            options = await asyncio.wait_for(instance.config_options(param), _OPTIONS_TIMEOUT_S)
        except asyncio.TimeoutError:
            return self._error("Unable to load toolkit options.", status=502, code="options_failed")
        except (RuntimeError, ValueError, LookupError) as exc:
            return self._map_exc(exc)
        except Exception:
            return self._error("Unable to load toolkit options.", status=502, code="options_failed")
        finally:
            if instance is not None and (instance.auto_open or instance._opened):
                try:
                    await instance._close()
                except Exception:
                    pass
        return self.json_response(ToolkitOptionsResponse(options=options).model_dump())


@is_authenticated()
@user_session()
class StudioAgentMcpServersHandler(_ToolingViewMixin, StudioBaseView):
    """GET/PUT the agent-level MCP server list."""

    async def get(self):
        """Return masked agent-level MCP server specifications."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:mcp:persist")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        _, state = authorized
        response = AgentMcpServersResponse(
            agent=name,
            editable=state.editable,
            reason=state.reason,
            servers=[mask_mcp(server) for server in state.tooling.mcp_servers],
        )
        return self.json_response(response.model_dump())

    async def put(self):
        """Replace the persisted agent-level MCP server list."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:mcp:persist")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        try:
            payload = await self.request.json()
        except Exception:
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            request = AgentMcpServersPutRequest(**(payload or {}))
        except (ValidationError, ValueError) as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")
        store, state = authorized
        try:
            refused = await self._write(
                state, name, payload,
                lambda kw: store.put_mcp_servers(name, request.servers, **kw),
            )
        except Exception as exc:
            return self._map_exc(exc)
        if refused is not None:
            return refused
        return self.json_response(ToolkitPersistResponse(agent=name).model_dump())
