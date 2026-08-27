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
"""
from __future__ import annotations

import inspect
import uuid
from typing import Any

from navigator_auth.decorators import is_authenticated, user_session
from parrot.clients.factory import LLMFactory
from parrot.tools.abstract import AbstractTool
from parrot.tools.discovery import discover_all, resolve_class
from parrot.tools.toolkit import AbstractToolkit
from pydantic import BaseModel, Field, ValidationError

from ._base import StudioBaseView
from .agents import _StudioAgentsMixin
from .byok import resolve_user_api_key
from .models import StudioError

SESSION_PREFIX = "_studio_test:"

# App-context dependency wiring for tool instantiation (spec §3 Module 9 —
# "app-context-wired" instantiation for tools whose constructor requires a
# server-managed resource). Extend this map as more such tools are added.
_KNOWN_APP_DEPS: dict[str, str] = {
    "artifact_store": "artifact_store",
}


class _ServerManagedDepsError(Exception):
    """Raised when a tool's constructor requires deps this endpoint can't supply."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Missing server-managed dependencies: {missing}")


class TestAskRequest(BaseModel):
    """``POST .../test/ask`` payload.

    Attributes:
        query: The question to send to the test agent instance.
        use_byok: When ``True`` (default) and a BYOK key is stored for the
            agent's LLM provider, the test client is built with that key
            (TASK-2516 ``resolve_user_api_key``). When no key is stored,
            this is a no-op — the agent's normally-configured client is
            used. An auth failure from a genuinely stored key is NEVER
            retried against the server's default key (spec §7).
    """
    query: str
    use_byok: bool = True


class ToolExecuteRequest(BaseModel):
    """``POST /tools/{slug}/execute`` payload."""
    args: dict[str, Any] = Field(default_factory=dict)


class ToolkitAssignEntry(BaseModel):
    """One toolkit assignment entry."""
    slug: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolAssignRequest(BaseModel):
    """``POST /agents/{name}/tools`` payload."""
    tools: list[str] = Field(default_factory=list)
    toolkits: list[ToolkitAssignEntry] = Field(default_factory=list)


def _resolve_registry_class(slug: str) -> type | None:
    """Resolve ``slug`` to a class via ``discover_all()`` + ``resolve_class()``.

    Matches case-insensitively, mirroring
    ``ToolManager._load_tool_from_registry``. Deliberately bypasses the
    deprecated ``ToolkitRegistry`` string lookup (see TASK-2517 Codebase
    Contract "Does NOT Exist").

    Args:
        slug: Candidate tool/toolkit slug.

    Returns:
        The resolved class, or ``None`` if the slug is unknown or
        resolution fails.
    """
    registry = discover_all()
    entry = registry.get(slug)
    if entry is None:
        lowered = {key.lower(): value for key, value in registry.items()}
        entry = lowered.get(slug.lower())
    if entry is None:
        return None
    if isinstance(entry, str):
        try:
            return resolve_class(entry)
        except (ImportError, AttributeError):
            return None
    return entry


def _instantiate_tool(cls: type, app: Any) -> AbstractTool:
    """Instantiate ``cls`` (an ``AbstractTool`` subclass) for deterministic execution.

    Zero-arg tools instantiate directly. Tools whose constructor requires a
    parameter listed in :data:`_KNOWN_APP_DEPS` are wired from the aiohttp
    app context (e.g. ``app['artifact_store']``). Any other required
    (no-default) constructor parameter is reported via
    :class:`_ServerManagedDepsError`.

    Args:
        cls: The resolved tool class.
        app: The aiohttp Application (source of server-managed deps).

    Returns:
        An instantiated tool.

    Raises:
        _ServerManagedDepsError: One or more required constructor params
            could not be resolved.
    """
    sig = inspect.signature(cls.__init__)
    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        app_key = _KNOWN_APP_DEPS.get(pname)
        resolved = app.get(app_key) if app_key else None
        if resolved is not None:
            kwargs[pname] = resolved
        else:
            missing.append(pname)
    if missing:
        raise _ServerManagedDepsError(missing)
    return cls(**kwargs)


class _StudioTestingMixin:
    """Shared helpers for the testing-surface views in this module."""

    def _manager(self):
        """Return the ``BotManager`` instance, or ``None`` if unavailable."""
        return self.request.app.get("bot_manager")

    def _error(self, message: str, *, status: int, code: str | None = None,
               details: dict | None = None):
        """Return a JSON error response shaped like :class:`StudioError`."""
        return self.json_response(
            StudioError(message=message, code=code, details=details).model_dump(),
            status=status,
        )

    def _session_key(self, agent_name: str) -> str:
        """Session key for the Studio test instance (namespaced — TASK-2517)."""
        return f"{SESSION_PREFIX}{agent_name}"

    async def _get_or_create_test_bot(self, agent_name: str, session: Any):
        """Return the reused test bot for ``(session, agent_name)``, creating it once.

        Mirrors ``BotConfigTestHandler._create_agent``/session discipline
        (``handlers/testing_handler.py:54-72``).

        Args:
            agent_name: The base agent name to clone a test instance from.
            session: The resolved caller session (dict-like).

        Returns:
            The (possibly newly created) test bot instance.

        Raises:
            LookupError: ``agent_name`` is not a known agent.
            RuntimeError: ``BotManager`` is not installed.
        """
        manager = self._manager()
        if not manager:
            raise RuntimeError("BotManager is not installed.")

        key = self._session_key(agent_name)
        bot_name = session.get(key) if session is not None else None
        if bot_name:
            bot = manager._bots.get(bot_name)
            if bot is not None:
                return bot
            # Session referenced a bot that expired/was cleaned up — recreate.

        session_id = uuid.uuid4().hex[:12]
        bot = await manager.get_bot(agent_name, new=True, session_id=session_id)
        if not bot:
            raise LookupError(f"Agent '{agent_name}' not found in registry.")
        if session is not None:
            session[key] = bot.name
        return bot


@is_authenticated()
@user_session()
class StudioTestingHandler(_StudioTestingMixin, StudioBaseView):
    """``/api/v1/astudio/agents/{name}/test/ask`` and ``.../test``.

    POST queries the session-scoped test instance (creating it on first
    call); DELETE tears the session instance down.
    """

    # -- POST: query the test agent (test/ask) --------------------------

    async def post(self):
        agent_name = self.request.match_info.get("name")
        if not agent_name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            ask_request = TestAskRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        session = await self._resolve_session()
        try:
            bot = await self._get_or_create_test_bot(agent_name, session)
        except LookupError as exc:
            return self._error(str(exc), status=404, code="not_found")
        except RuntimeError as exc:
            return self._error(str(exc), status=503, code="unavailable")

        if ask_request.use_byok:
            await self._maybe_apply_byok(bot)

        try:
            self.request.session = session
            async with bot.session(request=self.request, app=self.request.app) as live_bot:
                response = await live_bot.ask(question=ask_request.query)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.exception(
                "Studio test/ask failed for '%s': %s", agent_name, exc
            )
            return self._error(f"Agent query failed: {exc}", status=502, code="query_failed")

        content = str(response.content) if hasattr(response, "content") else str(response)
        metadata = getattr(response, "metadata", None) or {}

        return self.json_response({
            "agent_name": agent_name,
            "query": ask_request.query,
            "response": content,
            "metadata": metadata,
        })

    async def _maybe_apply_byok(self, bot) -> None:
        """Swap ``bot.llm`` for a BYOK-keyed client, when a key is stored.

        No-op when the bot's LLM was not configured from a plain
        ``"provider:model"`` string, or when the caller has no stored key
        for that provider. Never catches an auth failure and retries with
        the server default (spec §7) — a swapped-in client that fails
        auth on the subsequent ``ask()`` call surfaces as a query error.

        Args:
            bot: The (session-scoped) test bot instance.
        """
        llm_raw = getattr(bot, "_llm_raw", None)
        if not isinstance(llm_raw, str):
            return
        provider, _model = LLMFactory.parse_llm_string(llm_raw)
        user = await self._get_user()
        api_key = await resolve_user_api_key(self.request.app, user.user_id, provider)
        if not api_key:
            return
        bot.llm = LLMFactory.create(
            llm_raw, tool_manager=bot.tool_manager, api_key=api_key
        )

    # -- DELETE: stop the test session -----------------------------------

    async def delete(self):
        agent_name = self.request.match_info.get("name")
        if not agent_name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        session = await self._resolve_session()
        key = self._session_key(agent_name)
        bot_name = session.pop(key, None) if session is not None else None

        if not bot_name:
            return self.json_response(
                {"message": f"No active test session for '{agent_name}'"}, status=200
            )

        manager = self._manager()
        if manager is not None:
            try:
                manager.remove_bot(bot_name)
            except KeyError:
                self.logger.warning("Studio: test bot '%s' already removed", bot_name)

        return self.json_response({
            "message": f"Test session for '{agent_name}' stopped",
            "agent_name": agent_name,
        })


@is_authenticated()
@user_session()
class StudioToolExecuteHandler(_StudioTestingMixin, StudioBaseView):
    """``POST /api/v1/astudio/tools/{slug}/execute`` — deterministic tool call."""

    async def post(self):
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

        cls = _resolve_registry_class(slug)
        if cls is None or not (
            isinstance(cls, type) and issubclass(cls, AbstractTool)
        ) or (isinstance(cls, type) and issubclass(cls, AbstractToolkit)):
            return self._error(f"Unknown tool '{slug}'.", status=404, code="not_found")

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
            return self._error(
                f"Invalid arguments for '{slug}': {exc}", status=422, code="invalid_args"
            )

        result = await instance.execute(**execute_request.args)
        return self.json_response(result.model_dump(), status=200)


@is_authenticated()
@user_session()
class StudioToolAssignHandler(_StudioAgentsMixin, _StudioTestingMixin, StudioBaseView):
    """``POST /api/v1/astudio/agents/{name}/tools`` — assign tools/toolkits.

    Mutates the LIVE agent instance's ``tool_manager`` (shared-instance
    semantics — resolved in TASK-2517 scope). YAML persistence of toolkit
    config is TASK-2518's concern; this endpoint always reports
    ``persisted: false``.
    """

    async def post(self):
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

        db_agent = await self._get_db_agent(name)
        if db_agent is not None:
            owner = str(db_agent.created_by) if db_agent.created_by is not None else None
        else:
            registry = self._registry()
            meta = registry.get_metadata(name) if registry is not None else None
            if meta is None:
                return self._error(f"Agent '{name}' not found.", status=404, code="not_found")
            owner = self._registry_agent_owner(meta)

        user = await self._get_user()
        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial

        manager = self._manager()
        if manager is None:
            return self._error("BotManager unavailable.", status=503, code="unavailable")

        bot = await manager.get_bot(name)
        if bot is None:
            return self._error(f"Agent '{name}' has no live instance.", status=404, code="not_found")

        errors: list[dict[str, Any]] = []
        registered_names: set[str] = set()

        if assign_request.tools:
            before = set(bot.tool_manager.list_tools())
            bot.tool_manager.register_tools(assign_request.tools)
            after = set(bot.tool_manager.list_tools())
            registered_names |= (after - before)

        for entry in assign_request.toolkits:
            cls = _resolve_registry_class(entry.slug)
            if cls is None or not (
                isinstance(cls, type) and issubclass(cls, AbstractToolkit)
            ):
                errors.append({"slug": entry.slug, "error": "Unknown toolkit."})
                continue
            try:
                registered = bot.tool_manager.register_toolkit(cls, **entry.params)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error(
                    "Studio: failed to register toolkit '%s' on '%s': %s",
                    entry.slug, name, exc,
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
