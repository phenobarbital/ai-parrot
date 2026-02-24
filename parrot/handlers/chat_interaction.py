"""REST handler for chat interaction persistence.

Provides endpoints to list, load, and delete chat conversations
stored via ChatStorage (Redis + DocumentDB).
"""

from typing import Optional
from datetime import datetime

from aiohttp import web
from navigator.views import BaseView
from navigator_session import get_session
from navigator_auth.decorators import is_authenticated, user_session
from navigator_auth.conf import AUTH_SESSION_OBJECT


@is_authenticated()
@user_session()
class ChatInteractionHandler(BaseView):
    """Manage persisted chat interactions.

    GET    /api/v1/chat/interactions          — list conversations
    GET    /api/v1/chat/interactions/{sid}     — load messages for a session
    POST   /api/v1/chat/interactions          — create a conversation
    PUT    /api/v1/chat/interactions/{sid}     — update conversation title
    DELETE /api/v1/chat/interactions/{sid}     — delete a conversation
    """

    _logger_name: str = "Parrot.ChatInteraction"

    def _get_storage(self):
        """Retrieve ChatStorage from the application context."""
        try:
            return self.request.app["chat_storage"]
        except KeyError:
            self.logger.error("chat_storage not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        # 1. Try the user object set by @user_session / middleware
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
        # 2. Extract from session stored in Redis
        try:
            session = await get_session(self.request)
        except Exception:
            return None
        if session:
            userinfo = session.get(AUTH_SESSION_OBJECT, {})
            if isinstance(userinfo, dict):
                user_id = userinfo.get("user_id")
                if user_id:
                    return str(user_id)
            user_id = session.get("user_id")
            if user_id:
                return str(user_id)
        return None

    async def get(self) -> web.Response:
        """List conversations or load a specific session's messages."""
        storage = self._get_storage()
        if storage is None:
            self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            self.error(
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
                self.error(
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

    async def post(self) -> web.Response:
        """Create a new conversation."""
        storage = self._get_storage()
        if storage is None:
            self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        try:
            body = await self.json_data()
        except Exception:
            body = {}

        session_id = body.get("session_id")
        agent_id = body.get("agent_id")
        title = body.get("title", "New Conversation")

        if not session_id or not agent_id:
            self.error(
                response={"message": "session_id and agent_id are required"},
                status=400,
            )

        result = await storage.create_conversation(
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
            title=title,
        )

        if result is not None:
            return self.json_response({
                "message": "Conversation created",
                "conversation": result,
            }, status=201)
        self.error(
            response={"message": "Failed to create conversation"},
            status=500,
        )

    async def put(self) -> web.Response:
        """Update the title of a conversation."""
        storage = self._get_storage()
        if storage is None:
            self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            self.error(
                response={"message": "session_id is required in path"},
                status=400,
            )

        try:
            body = await self.json_data()
        except Exception:
            body = {}

        title = body.get("title")
        if not title:
            self.error(
                response={"message": "title is required"},
                status=400,
            )

        updated = await storage.update_conversation_title(
            session_id=session_id,
            title=title,
        )

        if updated:
            return self.json_response({
                "message": "Title updated",
                "session_id": session_id,
                "title": title,
            })
        self.error(
            response={"message": f"Failed to update conversation {session_id}"},
            status=500,
        )

    async def delete(self) -> web.Response:
        """Delete a conversation by session_id."""
        storage = self._get_storage()
        if storage is None:
            self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            self.error(
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
        self.error(
            response={"message": f"Conversation {session_id} not found"},
            status=404,
        )
