"""Authenticated semantic-layer HTTP views with trusted session identity."""

from __future__ import annotations

from typing import Any

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from pydantic import ValidationError

from parrot.auth import PermissionContext, UserSession


@is_authenticated()
@user_session()
class SemanticLayerHandler(BaseView):
    """Resolve host identity and call semantic tools within scoped binding."""

    async def get(self) -> web.Response:
        """Return only the authenticated subject's authorized catalog."""
        try:
            agent_id = self._agent_id()
            context = await self._pctx()
            identity = await self._identity(context, agent_id)
            toolkit = await self._toolkit(agent_id)
            from parrot.semantic.context import bind_semantic_context

            async with bind_semantic_context(context, identity=identity):
                models = await toolkit.list_models()
            return self.json_response({"models": models})
        except PermissionError as exc:
            return self.json_response({"error": str(exc)}, status=401)
        except LookupError as exc:
            return self.json_response({"error": str(exc)}, status=404)
        except ValueError as exc:
            return self.json_response({"error": str(exc)}, status=400)
        except Exception as exc:  # Semantic errors and host PBAC denials are fail-closed.
            return self._semantic_error(exc)

    async def post(self) -> web.Response:
        """Dispatch compile/query or guarded result publication."""
        try:
            body = await self.request.json()
        except Exception:  # noqa: BLE001 - malformed client JSON is a 400 response.
            return self.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, dict):
            return self.json_response({"error": "invalid_request"}, status=400)

        try:
            agent_id = self._agent_id()
            context = await self._pctx()
            identity = await self._identity(context, agent_id)
            toolkit = await self._toolkit(agent_id)
            result = await self._dispatch(toolkit, context, identity, body)
            return self.json_response(result)
        except PermissionError as exc:
            return self.json_response({"error": str(exc)}, status=401)
        except LookupError as exc:
            return self.json_response({"error": str(exc)}, status=404)
        except (TypeError, ValidationError, ValueError) as exc:
            return self.json_response({"error": "invalid_request", "details": str(exc)}, status=400)
        except Exception as exc:  # Semantic errors and host PBAC denials are fail-closed.
            return self._semantic_error(exc)

    async def _dispatch(self, toolkit: object, context: PermissionContext, identity: object, body: dict[str, Any]) -> dict:
        """Execute one supported semantic operation in the trusted binding."""
        from parrot.semantic.context import bind_semantic_context
        from parrot.semantic.models import SemanticQuery

        payload = dict(body)
        for field in ("agent_id", "session_id", "identity", "context", "_permission_context", "pctx"):
            payload.pop(field, None)
        tail = self.request.match_info.get("tail", "").strip("/")
        async with bind_semantic_context(context, identity=identity):
            if tail == "compile":
                query = SemanticQuery.model_validate(payload.get("query", payload))
                return await toolkit.compile_query(query)
            if tail == "query":
                query = SemanticQuery.model_validate(payload.get("query", payload))
                result = await toolkit.query_metrics(query)
                return result.model_dump(mode="json")
            prefix, separator, dataset = tail.partition("/dataset")
            if separator and prefix.startswith("results/") and prefix.count("/") == 1:
                result_id = prefix.removeprefix("results/")
                if not result_id or dataset:
                    raise ValueError("invalid semantic result route")
                name = payload.get("name")
                description = payload.get("description")
                if not isinstance(name, str):
                    raise ValueError("dataset name is required")
                if description is not None and not isinstance(description, str):
                    raise ValueError("dataset description must be a string")
                return await toolkit.save_result_as_dataset(result_id, name, description)
        raise ValueError("unknown semantic operation")

    async def _toolkit(self, agent_id: str) -> object:
        """Resolve the authorized agent's ordinary SemanticLayerToolkit lazily."""
        from parrot.semantic import SemanticLayerToolkit
        from parrot.semantic.bootstrap import LocalSemanticLayerToolkit

        manager = self.request.app.get("bot_manager")
        if manager is None:
            raise LookupError("semantic agent not found")
        bot = await manager.get_bot(agent_id, request=self.request)
        if bot is None or not hasattr(bot, "tool_manager"):
            raise LookupError("semantic agent not found")
        tool_manager = bot.tool_manager
        if tool_manager.find_registered_toolkit(LocalSemanticLayerToolkit) is not None:
            from parrot.semantic.errors import SemanticAccessError

            raise SemanticAccessError("local_toolkit_rejected", "Local semantic toolkits are unavailable over HTTP")
        toolkit = tool_manager.find_registered_toolkit(SemanticLayerToolkit)
        if toolkit is None:
            raise LookupError("semantic toolkit is not configured for this agent")
        return toolkit

    async def _pctx(self) -> PermissionContext:
        """Build from authenticated navigator session, never caller JSON."""
        session = await get_session(self.request)
        if session is None:
            raise PermissionError("authenticated session is required")
        user = getattr(self.request, "user", None)
        userinfo = session.get("user") or session.get("userinfo") or session.get("auth")
        if userinfo is None:
            userinfo = next(
                (value for value in getattr(session, "values", lambda: ())() if isinstance(value, dict) and "user_id" in value),
                {},
            )
        if not isinstance(userinfo, dict):
            userinfo = {}
        user_id = getattr(user, "user_id", None) or getattr(user, "id", None) or userinfo.get("user_id")
        user_id = user_id or session.get("user_id")
        tenant_id = getattr(user, "tenant_id", None) or userinfo.get("tenant_id") or session.get("tenant_id")
        if not user_id or not tenant_id:
            raise PermissionError("authenticated user and tenant are required")
        roles = getattr(user, "roles", None) or userinfo.get("roles") or session.get("roles") or ()
        if not isinstance(roles, (list, tuple, set, frozenset)):
            raise PermissionError("authenticated roles are invalid")
        metadata = userinfo.get("metadata") or session.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return PermissionContext(
            session=UserSession(str(user_id), str(tenant_id), frozenset(roles), dict(metadata)),
            channel="http",
        )

    def _agent_id(self) -> str:
        """Return the path-controlled agent identifier or reject the request."""
        agent_id = self.request.match_info.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        return agent_id

    async def _identity(self, context: PermissionContext, agent_id: str) -> object:
        """Build a retention identity from server-side session state only."""
        from parrot.semantic.context import SemanticRequestIdentity

        session = await get_session(self.request)
        session_id = getattr(session, "session_id", None) or session.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise PermissionError("authenticated session id is required")
        return SemanticRequestIdentity(ctx=context, channel="http", agent_id=agent_id, session_id=session_id)

    def _semantic_error(self, error: Exception) -> web.Response:
        """Map semantic failures to stable, fail-closed HTTP responses."""
        from parrot.auth import AgentAccessDenied
        from parrot.semantic.errors import SemanticAccessError, SemanticError, SemanticResultError

        if isinstance(error, (AgentAccessDenied, SemanticAccessError)):
            status = 403
        elif isinstance(error, SemanticResultError) and error.code == "handoff_unavailable":
            status = 503
        elif isinstance(error, SemanticError):
            status = 400
        else:
            self.logger.exception("Semantic HTTP request failed")
            return self.json_response({"error": "semantic_unavailable"}, status=503)
        return self.json_response({"error": error.code}, status=status)
