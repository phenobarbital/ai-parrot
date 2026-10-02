"""Studio testing surface — test/ask, deterministic tool execute, tool
assignment (FEAT-467 TASK-2517).

Implements spec §3 Module 9:

    POST   /api/v1/astudio/agents/{name}/test/ask   — query a session-scoped
                                                        test instance (BYOK-aware)
    DELETE /api/v1/astudio/agents/{name}/test        — end the test session
    POST   /api/v1/astudio/tools/{slug}/execute      — deterministic tool call
    POST   /api/v1/astudio/agents/{name}/tools       — assign tools/toolkits
                                                        to the LIVE agent instance

Session-scoped test instances follow the proven ``BotConfigTestHandler``
pattern (``handlers/testing_handler.py``): ``manager.get_bot(name, new=True,
session_id=...)`` creates an isolated, expiring bot instance whose name is
stashed in the caller's session and reused across calls.

Package layout (oversize-module split, owner decision D1): the three views
live here with their verbs; request models, helpers, the shared mixin and the
ask / legacy / database-mode bodies are in ``_models.py`` / ``_helpers.py`` /
``_mixin.py`` / ``_ask.py`` / ``_legacy.py`` / ``_db.py``.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from navigator_auth.decorators import is_authenticated, user_session
from parrot.auth.confirmation import is_enforced_write_class
from parrot.clients.factory import LLMFactory
from parrot.tools.abstract import AbstractTool
from parrot.tools.discovery import resolve_class
from parrot.tools.toolkit import AbstractToolkit
from pydantic import ValidationError

from .._base import StudioBaseView
from ..access import StudioTenantRequired
from ..agents import _StudioAgentsMixin
from ..byok import resolve_user_api_key  # re-exported: tests patch ``testing.resolve_user_api_key``
from ._ask import _StudioTestingAskMixin
from ._db import _StudioTestingDbMixin
from ._helpers import _instantiate_tool, _resolve_registry_class
from ._legacy import _StudioTestingLegacyMixin
from ._mixin import _StudioTestingMixin
from ._models import (
    SESSION_PREFIX,
    TestAskRequest,
    ToolAssignRequest,
    ToolExecuteRequest,
    ToolkitAssignEntry,
    _ServerManagedDepsError,
)

__all__ = [
    "LLMFactory",
    "SESSION_PREFIX",
    "StudioTestingHandler",
    "StudioToolAssignHandler",
    "StudioToolExecuteHandler",
    "TestAskRequest",
    "ToolAssignRequest",
    "ToolExecuteRequest",
    "ToolkitAssignEntry",
    "resolve_class",
    "resolve_user_api_key",
]


@is_authenticated()
@user_session()
class StudioTestingHandler(
    _StudioTestingLegacyMixin, _StudioTestingDbMixin, _StudioTestingAskMixin, _StudioTestingMixin, StudioBaseView
):
    """``/api/v1/astudio/agents/{name}/test/ask`` and ``.../test``.

    POST queries the session-scoped test instance (creating it on first
    call); DELETE tears the session instance down.
    """

    _dispatch = _StudioAgentsMixin._dispatch  # one database/filesystem switch for every Studio view

    async def post(self):
        """Query the test instance: Studio rows through ``manager.studio.use()`` (database mode), else legacy."""
        gate = lambda: self._pbac_gate("testing", "astudio:testing:ask")  # noqa: E731
        return await self._dispatch(self._legacy_post, self._db_post, gate)

    async def delete(self):
        """End the test session: a Studio session entry is evicted from the runtime cache, else legacy."""
        return await self._dispatch(self._legacy_delete, self._db_delete)


@is_authenticated()
@user_session()
class StudioToolExecuteHandler(_StudioTestingMixin, StudioBaseView):
    """``POST /api/v1/astudio/tools/{slug}/execute`` — deterministic tool call."""

    async def _executable_refusal(self, slug: str, cls: type | None, args: dict):
        """404 for an unknown / non-tool slug; 403 ``tooling_not_permitted`` (tenant policy, phase ``execute``);
        403 ``confirmation_required`` for a host write tool; 422 ``server_managed`` for a body key the server fills.

        A host standalone write tool has no approval channel on this path (FEAT-622 M8), so it is refused
        before any instantiation.
        """
        if (
            cls is None
            or not (isinstance(cls, type) and issubclass(cls, AbstractTool))
            or (isinstance(cls, type) and issubclass(cls, AbstractToolkit))
        ):
            return self._error(f"Unknown tool '{slug}'.", status=404, code="not_found")
        if (refused := await self._policy_check(slug, phase="execute", status=403)) is not None:
            return refused
        if (refused := self._scope_refusal(cls, slug)) is not None:
            return refused  # before _instantiate_tool: no constructor side effect without a valid scope
        if is_enforced_write_class(cls):
            return self._error(
                f"Tool '{slug}' requires confirmation and cannot be executed directly.",
                status=403,
                code="confirmation_required",
            )
        if sent := sorted(set(args) & set(getattr(cls, "server_managed_params", None) or {})):
            return self._error(
                f"Server-managed parameters cannot be set: {', '.join(sent)}",
                status=422,
                code="server_managed",
                details={"params": sent},
            )
        return None

    def _execute_response(self, result):
        """200 with the result; a structured ``tool_scope_unavailable`` result is the same 403 as the pre-check."""
        meta = result.metadata or {}
        if meta.get("error_code") == "tool_scope_unavailable":
            return self._scope_error_response(result.error or "tool_scope_unavailable", meta.get("reason"))
        return self.json_response(result.model_dump(), status=200)

    async def post(self):
        if (denied := await self._require_author()) is not None:
            return denied
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("testing", "astudio:testing:execute")) is not None:
            return denied

        slug = self.request.match_info.get("slug")
        if not slug:
            return self._error("Tool slug is required.", status=400, code="missing_slug")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            execute_request = ToolExecuteRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        try:
            async with self._bound_scope():   # agent=None: the caller's scope; nothing bound without a resolver
                return await self._run_tool(slug, execute_request)
        except StudioTenantRequired:
            return self._tenant_required()    # an opted-in caller with no tenant

    async def _run_tool(self, slug: str, execute_request):
        """Refusals, construction and the call — all inside the bound request context (scope gate first, R-b)."""
        cls = _resolve_registry_class(slug)
        if (refused := await self._executable_refusal(slug, cls, execute_request.args)) is not None:
            return refused

        try:
            instance = _instantiate_tool(cls, self.request.app)
        except _ServerManagedDepsError as exc:
            return self._error(
                f"Tool '{slug}' requires server-managed dependencies.",
                status=422,
                code="server_managed",
                details={"missing": exc.missing},
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to instantiate tool '%s': %s", slug, exc)
            return self._error(
                f"Failed to instantiate tool '{slug}': {exc}",
                status=500,
                code="instantiation_failed",
            )

        try:
            instance.validate_args(**execute_request.args)
        except ValueError as exc:
            return self._error(f"Invalid arguments for '{slug}': {exc}", status=422, code="invalid_args")

        return self._execute_response(await instance.execute(**execute_request.args))


@is_authenticated()
@user_session()
class StudioToolAssignHandler(_StudioAgentsMixin, _StudioTestingMixin, StudioBaseView):
    """``POST /api/v1/astudio/agents/{name}/tools`` — assign tools/toolkits.

    Mutates the LIVE agent instance's ``tool_manager`` (shared-instance
    semantics — resolved in TASK-2517 scope). YAML persistence of toolkit
    config is TASK-2518's concern; this endpoint always reports
    ``persisted: false``.
    """

    async def _agent_owner(self, name: str):
        """``(owner, None)`` of the agent, or ``(None, response)`` (404 unknown/invisible, 403 not manageable)."""
        owner = await self._assign_owner(name)
        return (None, owner) if isinstance(owner, web.Response) else (owner, None)

    async def _attach_refusal(self, assign_request):
        """422 ``tooling_not_permitted`` for the first tool/toolkit slug the tenant policy refuses (phase ``attach``).

        Runs before any registration, so a refused request changes nothing on the live agent.
        """
        for slug in [*assign_request.tools, *(entry.slug for entry in assign_request.toolkits)]:
            if (refused := await self._policy_check(slug, phase="attach", status=422)) is not None:
                return refused
        return None

    async def post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("agents", "astudio:agents:assign_tools")) is not None:
            return denied

        name = self.request.match_info.get("name")
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            assign_request = ToolAssignRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        owner, missing = await self._agent_owner(name)
        if missing is not None:
            return missing

        user = await self._get_user()
        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial

        if (refused := await self._attach_refusal(assign_request)) is not None:
            return refused  # the tenant policy answers before any live-instance lookup

        manager = self._manager()
        if manager is None:
            return self._error("BotManager unavailable.", status=503, code="unavailable")

        bot = await self._live_bot(manager, name)
        if bot is None:
            return self._error(f"Agent '{name}' has no live instance.", status=404, code="not_found")

        errors: list[dict[str, Any]] = []
        registered_names: set[str] = set()

        if assign_request.tools:
            before = set(bot.tool_manager.list_tools())
            bot.tool_manager.register_tools(assign_request.tools)
            after = set(bot.tool_manager.list_tools())
            registered_names |= after - before

        for entry in assign_request.toolkits:
            cls = _resolve_registry_class(entry.slug)
            if cls is None or not (isinstance(cls, type) and issubclass(cls, AbstractToolkit)):
                errors.append({"slug": entry.slug, "error": "Unknown toolkit."})
                continue
            try:
                registered = bot.tool_manager.register_toolkit(cls, **entry.params)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error(
                    "Studio: failed to register toolkit '%s' on '%s': %s",
                    entry.slug,
                    name,
                    exc,
                )
                errors.append({"slug": entry.slug, "error": str(exc)})
                continue
            registered_names |= {t.name for t in registered}

        response: dict[str, Any] = {
            "agent": name,
            "registered_tools": sorted(registered_names),
            "persisted": False,
        }
        if errors:
            response["errors"] = errors
        return self.json_response(response, status=200)
