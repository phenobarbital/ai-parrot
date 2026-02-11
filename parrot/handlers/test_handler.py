"""REST API Handler for Agent Configuration Testing.

Provides session-based agent testing via PUT/POST/DELETE.

Endpoints:
    PUT    /api/v1/agents/test/{agent_name} — create test agent session
    POST   /api/v1/agents/test/{agent_name} — send query to test agent
    DELETE /api/v1/agents/test/{agent_name} — stop test session
"""
from __future__ import annotations

import uuid
from typing import Any, Optional, TYPE_CHECKING

from aiohttp import web
from navconfig.logging import logging
from navigator_session import get_session
from navigator.views import BaseView

from ..bots.abstract import AbstractBot

if TYPE_CHECKING:
    from ..manager import BotManager


SESSION_PREFIX = "_test_agent_"


class BotConfigTestHandler(BaseView):
    """Handler for testing agent configurations via ephemeral sessions."""

    _logger_name: str = "Parrot.BotConfigTestHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    @property
    def manager(self) -> "BotManager":
        """Get BotManager from the app."""
        return self.request.app.get("bot_manager")

    def _agent_name(self) -> Optional[str]:
        """Extract agent_name from URL path."""
        return self.request.match_info.get("agent_name") or None

    async def _get_session(self):
        """Get the user session."""
        try:
            return self.request.session or await get_session(self.request)
        except AttributeError:
            return await get_session(self.request)

    def _session_key(self, agent_name: str) -> str:
        """Session key for the test agent."""
        return f"{SESSION_PREFIX}{agent_name}"

    async def _create_agent(self, agent_name: str) -> AbstractBot:
        """Create a new temporary agent instance for testing."""
        manager = self.manager
        if not manager:
            raise RuntimeError("BotManager is not installed.")

        session_id = uuid.uuid4().hex[:12]
        agent = await manager.get_bot(
            agent_name,
            new=True,
            session_id=session_id,
        )
        if not agent:
            raise LookupError(f"Agent '{agent_name}' not found in registry.")
        return agent

    # -- PUT: start test session -----------------------------------------------

    async def put(self) -> web.Response:
        """Create a test agent and store it in the user session.

        Returns 201 with the agent name on success.
        """
        agent_name = self._agent_name()
        if not agent_name:
            return self.error(
                response={"message": "agent_name is required in URL"},
                status=400,
            )

        user_session = await self._get_session()
        key = self._session_key(agent_name)

        # Already exists? Return 200 instead of recreating
        existing_bot_name = user_session.get(key)
        if existing_bot_name:
            return self.json_response(
                {
                    "message": f"Test agent '{agent_name}' already active",
                    "agent_name": agent_name,
                    "bot_name": existing_bot_name,
                },
                status=200,
            )

        try:
            agent = await self._create_agent(agent_name)
        except LookupError as exc:
            return self.error(response={"message": str(exc)}, status=404)
        except RuntimeError as exc:
            return self.error(response={"message": str(exc)}, status=500)

        # Store the temporary bot name in the session
        user_session[key] = agent.name
        self.logger.info(
            f"Test session started for '{agent_name}' "
            f"(temp bot: '{agent.name}')"
        )

        return self.json_response(
            {
                "message": f"Test agent '{agent_name}' is ready",
                "agent_name": agent_name,
                "bot_name": agent.name,
            },
            status=201,
        )

    # -- POST: query the test agent --------------------------------------------

    async def post(self) -> web.Response:
        """Send a query to the test agent stored in the session.

        Body: ``{"query": "your question here"}``
        """
        agent_name = self._agent_name()
        if not agent_name:
            return self.error(
                response={"message": "agent_name is required in URL"},
                status=400,
            )

        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        query = data.get("query")
        if not query:
            return self.error(
                response={"message": "'query' field is required"},
                status=400,
            )

        manager = self.manager
        if not manager:
            return self.error(
                response={"message": "BotManager is not installed."},
                status=500,
            )

        user_session = await self._get_session()
        key = self._session_key(agent_name)
        bot_name = user_session.get(key)

        # Auto-create if not started yet (convenience)
        if not bot_name:
            try:
                agent = await self._create_agent(agent_name)
                bot_name = agent.name
                user_session[key] = bot_name
            except (LookupError, RuntimeError) as exc:
                return self.error(
                    response={"message": str(exc)},
                    status=404 if isinstance(exc, LookupError) else 500,
                )

        # Retrieve the agent from the manager
        agent = manager._bots.get(bot_name)
        if not agent:
            # Session referenced a bot that was cleaned up — recreate
            try:
                agent = await self._create_agent(agent_name)
                bot_name = agent.name
                user_session[key] = bot_name
            except (LookupError, RuntimeError) as exc:
                return self.error(
                    response={"message": str(exc)},
                    status=404 if isinstance(exc, LookupError) else 500,
                )

        # Use the ask() method
        try:
            # Patch request with session for AbstractBot.retrieval
            setattr(self.request, "session", user_session)
            
            async with agent.retrieval(
                self.request, app=self.request.app
            ) as bot:
                response = await bot.ask(question=query)
        except Exception as exc:
            self.logger.error(
                f"Error during test query for '{agent_name}': {exc}",
                exc_info=True,
            )
            return self.error(
                response={"message": f"Agent query failed: {exc}"},
                status=500,
            )

        # Format the response
        content = ""
        metadata = {}
        if response:
            content = str(response.content) if hasattr(response, "content") else str(response)
            if hasattr(response, "metadata"):
                metadata = response.metadata or {}

        return self.json_response({
            "agent_name": agent_name,
            "query": query,
            "response": content,
            "metadata": metadata,
        })

    # -- DELETE: stop test session ----------------------------------------------

    async def delete(self) -> web.Response:
        """Stop the test session and remove the temporary agent."""
        agent_name = self._agent_name()
        if not agent_name:
            return self.error(
                response={"message": "agent_name is required in URL"},
                status=400,
            )

        user_session = await self._get_session()
        key = self._session_key(agent_name)
        bot_name = user_session.pop(key, None)

        if not bot_name:
            return self.json_response(
                {"message": f"No active test session for '{agent_name}'"},
                status=200,
            )

        # Remove the temporary bot from the manager
        manager = self.manager
        if manager:
            try:
                manager.remove_bot(bot_name)
                self.logger.info(
                    f"Test session stopped for '{agent_name}' "
                    f"(removed bot: '{bot_name}')"
                )
            except KeyError:
                self.logger.warning(
                    f"Bot '{bot_name}' already removed from manager"
                )

        return self.json_response({
            "message": f"Test session for '{agent_name}' stopped",
            "agent_name": agent_name,
        })
