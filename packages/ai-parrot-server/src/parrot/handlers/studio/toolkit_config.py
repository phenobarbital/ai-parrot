"""Agent Studio agent-level tooling endpoints (FEAT-593)."""
from __future__ import annotations

import asyncio
import inspect

from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

from parrot.tools.spec import hydrate_params, mask_mcp, mask_spec

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
from .tooling_store import AgentToolingStore

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
        self._require_owner(state.owner, await self._get_user())
        return store, state

    def _map_exc(self, exc: Exception):
        """Map persistence and vault exceptions to the Studio error contract."""
        if isinstance(exc, PermissionError):
            return self._error(str(exc), status=409, code="read_only_definition")
        if isinstance(exc, ValueError):
            return self._error(str(exc), status=422, code="invalid_params")
        if isinstance(exc, RuntimeError):
            return self._error("Vault service unavailable.", status=503, code="vault_unavailable")
        if isinstance(exc, LookupError):
            return self._error("Requested resource was not found.", status=404, code="not_found")
        raise exc

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
        store, _ = authorized
        try:
            await store.put_toolkit(name, slug, request.params, request.user_overridable)
        except Exception as exc:
            return self._map_exc(exc)
        return self.json_response(ToolkitPersistResponse(agent=name, slug=slug).model_dump())

    async def delete(self):
        """Delete one agent-level toolkit specification."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:toolkits:persist")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        store, _ = authorized
        try:
            await store.delete_toolkit(name, slug)
        except Exception as exc:
            return self._map_exc(exc)
        return self.json_response(ToolkitPersistResponse(agent=name, slug=slug).model_dump())


@is_authenticated()
@user_session()
class StudioToolkitOptionsHandler(_ToolingViewMixin, StudioBaseView):
    """GET dynamic options evaluated on the persisted spec only."""

    async def get(self):
        """Return dynamic options without accepting request-provided configuration."""
        authorized = await self._authorize(self.request.match_info.get("name"), "astudio:toolkits:options")
        if self._is_error_response(authorized):
            return authorized
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        param = self.request.match_info.get("param")
        store, state = authorized
        try:
            cls, _ = store.schema_for(slug)
        except LookupError as exc:
            return self._map_exc(exc)
        if param not in cls.options_params:
            return self._error(f"Unknown options parameter '{param}'.", status=404, code="not_found")
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
        store, _ = authorized
        try:
            await store.put_mcp_servers(name, request.servers)
        except Exception as exc:
            return self._map_exc(exc)
        return self.json_response(ToolkitPersistResponse(agent=name).model_dump())
