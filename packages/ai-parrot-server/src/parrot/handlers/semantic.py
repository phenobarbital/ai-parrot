"""HTTP surface of the semantic layer (FEAT-704 spec §3 Module 11)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session

from parrot.auth import PermissionContext, UserSession

from .datasets import _resolve_dataset_manager

if TYPE_CHECKING:
    from parrot.semantic import SemanticLayerToolkit


@is_authenticated()
@user_session()
class SemanticLayerHandler(BaseView):
    """GET catalog; POST compile | query | results/{result_id}/dataset for semantic agents."""

    async def get(self) -> web.Response:
        """Return the role-filtered catalog for the requested agent."""
        agent_id = self.request.match_info.get("agent_id")
        if not agent_id:
            return self.json_response({"error": "agent_id is required"}, status=400)
        try:
            pctx = await self._pctx()
            result = await self._call_tool(await self._toolkit(agent_id), "list_models", pctx)
            return self.json_response(result)
        except web.HTTPException as error:
            return self.json_response({"error": error.reason}, status=error.status)
        except Exception as error:  # semantic exceptions are lazily imported with the satellite.
            return self._semantic_error_response(error)

    async def post(self) -> web.Response:
        """Dispatch a compile, query, or result-to-dataset request."""
        agent_id = self.request.match_info.get("agent_id")
        if not agent_id:
            return self.json_response({"error": "agent_id is required"}, status=400)

        tail = self.request.match_info.get("tail", "").strip("/")
        if tail not in {"compile", "query"} and not (tail.startswith("results/") and tail.endswith("/dataset")):
            return self.json_response({"error": "unknown semantic action"}, status=404)

        try:
            body = await self.request.json()
        except Exception:
            return self.json_response({"error": "invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return self.json_response({"error": "JSON body must be an object"}, status=400)

        try:
            pctx = await self._pctx()
            toolkit = await self._toolkit(agent_id)
            if tail == "compile" or tail == "query":
                from parrot.semantic import SemanticQuery

                query = SemanticQuery.model_validate(body)
                method = "compile_query" if tail == "compile" else "query_metrics"
                result = await self._call_tool(toolkit, method, pctx, query=query)
            else:
                result_id = tail.split("/")[1]
                result = await self._save_result_as_dataset(toolkit, agent_id, pctx, result_id, body)
            return self.json_response(result)
        except web.HTTPException as error:
            return self.json_response({"error": error.reason}, status=error.status)
        except ValueError as error:
            return self.json_response({"error": str(error)}, status=400)
        except Exception as error:  # semantic exceptions are lazily imported with the satellite.
            return self._semantic_error_response(error)

    async def _toolkit(self, agent_id: str) -> "SemanticLayerToolkit":
        """Return the agent's semantic toolkit, or raise 404 when it is absent."""
        from parrot.semantic import SemanticLayerToolkit
        from parrot.tools.manager import get_toolkit_owner

        bot_manager = self.request.app.get("bot_manager")
        agent = bot_manager._bots.get(agent_id) if bot_manager else None
        if agent is None:
            raise web.HTTPNotFound(reason=f"Agent '{agent_id}' not found")

        tool_manager = getattr(agent, "tool_manager", None)
        if tool_manager is None:
            raise web.HTTPNotFound(reason=f"Agent '{agent_id}' has no semantic toolkit")
        tools: Any
        if hasattr(tool_manager, "get_tools"):
            tools = tool_manager.get_tools()
            tools = tools.values() if isinstance(tools, dict) else tools
        elif hasattr(tool_manager, "all_tools"):
            tools = tool_manager.all_tools()
        else:
            tools = getattr(tool_manager, "_tools", {}).values()
        for tool in tools:
            toolkit = get_toolkit_owner(tool)
            if isinstance(toolkit, SemanticLayerToolkit):
                return toolkit
        raise web.HTTPNotFound(reason=f"Agent '{agent_id}' has no semantic toolkit")

    async def _pctx(self) -> PermissionContext:
        """Build a permission context from the authenticated navigator session."""
        session = getattr(self.request, "session", None) or await get_session(self.request)
        if not session:
            raise web.HTTPUnauthorized(reason="authentication required")
        user_id = session.get("user_id") or session.get("username")
        if not user_id:
            raise web.HTTPUnauthorized(reason="session carries no user identity")
        tenant_id = session.get("tenant_id") or session.get("program") or "default"
        return PermissionContext(
            session=UserSession(
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                roles=frozenset(session.get("groups") or session.get("roles") or ()),
            ),
            channel="api",
            extra={"session_id": str(getattr(session, "session_id", ""))},
        )

    async def _call_tool(
        self, toolkit: "SemanticLayerToolkit", method: str, pctx: PermissionContext, **kwargs: Any
    ) -> Any:
        """Invoke a semantic method through its ``ToolkitTool`` lifecycle path."""
        tool_name = f"{toolkit.tool_prefix}_{method}"
        for tool in toolkit.get_tools():
            if tool.name == tool_name:
                result = await tool.execute(_permission_context=pctx, **kwargs)
                if result.status == "error":
                    raise web.HTTPBadGateway(reason=result.error or "semantic tool failed")
                return result.result
        raise web.HTTPNotFound(reason=f"Semantic operation '{method}' is unavailable")

    async def _save_result_as_dataset(
        self,
        toolkit: "SemanticLayerToolkit",
        agent_id: str,
        pctx: PermissionContext,
        result_id: str,
        body: dict[str, Any],
    ) -> Any:
        """Resolve the request-scoped dataset manager before the governed hand-off."""
        name = body.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("name is required")
        manager = await _resolve_dataset_manager(
            self.request,
            agent_id,
            f"{agent_id}_dataset_manager",
            self.logger,
        )
        toolkit._dataset_manager_factory = lambda _ctx: manager
        toolkit.exclude_tools = tuple(name for name in toolkit.exclude_tools if name != "save_result_as_dataset")
        return await self._call_tool(
            toolkit,
            "save_result_as_dataset",
            pctx,
            result_id=result_id,
            name=name,
            description=body.get("description"),
        )

    def _semantic_error_response(self, error: Exception) -> web.Response:
        """Map semantic failures to their public HTTP status without exposing SQL."""
        try:
            from parrot.semantic import (
                SemanticAccessError,
                SemanticExecutionError,
                SemanticResultError,
                SemanticValidationError,
            )
        except ImportError:
            return self.json_response({"error": "semantic layer unavailable"}, status=503)
        statuses = {
            SemanticAccessError: 403,
            SemanticValidationError: 400,
            SemanticResultError: 404,
            SemanticExecutionError: 502,
        }
        for error_type, status in statuses.items():
            if isinstance(error, error_type):
                return self.json_response({"error": error.code, "details": error.details}, status=status)
        self.logger.exception("Unexpected semantic handler error")
        return self.json_response({"error": "semantic request failed"}, status=502)
