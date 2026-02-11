"""REST handler for chat interaction persistence.

Provides endpoints to list, load, and delete chat conversations
stored via ChatStorage (Redis + DocumentDB).
"""

from typing import Optional
from datetime import datetime

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navconfig.logging import logging


@is_authenticated()
@user_session()
class ChatInteractionHandler(BaseView):
    """Manage persisted chat interactions.

    GET  /api/v1/chat/interactions          — list conversations
    GET  /api/v1/chat/interactions/{sid}     — load messages for a session
    DELETE /api/v1/chat/interactions/{sid}   — delete a conversation
    """

    _logger_name: str = "Parrot.ChatInteraction"

    def _get_storage(self):
        """Retrieve ChatStorage from the application context."""
        try:
            return self.request.app["chat_storage"]
        except KeyError:
            self.logger.error("chat_storage not found in app context")
            return None

    def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        try:
            return self.request.get("user_id", None)
        except Exception:
            return None

    async def get(self) -> web.Response:
        """List conversations or load a specific session's messages."""
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        # Check for session_id in URL path
        session_id = self.request.match_info.get("session_id")

        if session_id:
            return await self._get_conversation_messages(storage, user_id, session_id)
        return await self._list_conversations(storage, user_id)

    async def _list_conversations(
        self, storage, user_id: str
    ) -> web.Response:
        """List all conversations for the authenticated user."""
        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id")
        limit = int(qs.get("limit", 50))
        since_str = qs.get("since")

        since: Optional[datetime] = None
        if since_str:
            try:
                since = datetime.fromisoformat(since_str)
            except ValueError:
                return self.error(
                    response={"message": "Invalid 'since' format, use ISO 8601"},
                    status=400,
                )

        conversations = await storage.list_user_conversations(
            user_id=user_id,
            agent_id=agent_id,
            limit=limit,
            since=since,
        )
        return self.json_response({
            "conversations": conversations,
            "count": len(conversations),
        })

    async def _get_conversation_messages(
        self, storage, user_id: str, session_id: str
    ) -> web.Response:
        """Load messages for a specific conversation."""
        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id")
        limit = int(qs.get("limit", 50))

        messages = await storage.load_conversation(
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
            limit=limit,
        )

        metadata = await storage.get_conversation_metadata(session_id)

        return self.json_response({
            "session_id": session_id,
            "messages": messages,
            "count": len(messages),
            "metadata": metadata,
        })

    async def delete(self) -> web.Response:
        """Delete a conversation by session_id."""
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "session_id is required in path"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id")

        deleted = await storage.delete_conversation(
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        if deleted:
            return self.json_response({
                "message": f"Conversation {session_id} deleted",
                "session_id": session_id,
            })
        return self.error(
            response={"message": f"Conversation {session_id} not found"},
            status=404,
        )
