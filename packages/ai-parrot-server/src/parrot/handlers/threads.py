"""REST handler for thread management.

Provides endpoints for conversation thread CRUD operations with
DynamoDB backend support.  Uses ChatStorage (DynamoDB) for thread
and turn persistence, and ArtifactStore for cascade deletes.

FEAT-103: agent-artifact-persistency — Module 7.

Endpoints:
    GET    /api/v1/threads?agent_id=X           — list conversations (sidebar)
    POST   /api/v1/threads                      — create new thread
    GET    /api/v1/threads/{session_id}          — load thread turns (limit=10)
    PATCH  /api/v1/threads/{session_id}          — update metadata (title, pinned, tags)
    DELETE /api/v1/threads/{session_id}          — delete thread + cascade artifacts
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
class ThreadListView(BaseView):
    """List and create conversation threads.

    GET  /api/v1/threads?agent_id=X&limit=N  — list threads
    POST /api/v1/threads                      — create thread
    """

    _logger_name: str = "Parrot.ThreadListView"

    def _get_storage(self):
        """Retrieve ChatStorage from the application context."""
        try:
            return self.request.app["chat_storage"]
        except KeyError:
            self.logger.error("chat_storage not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
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
        """List conversation threads for the authenticated user.

        Query params:
            agent_id (required): Agent/bot identifier.
            limit (optional): Max threads to return (default 50).
        """
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")
        limit = int(qs.get("limit", 50))

        threads = await storage.list_user_conversations(
            user_id=user_id,
            agent_id=agent_id,
            limit=limit,
        )

        return self.json_response({
            "threads": threads,
            "count": len(threads),
        })

    async def post(self) -> web.Response:
        """Create a new conversation thread.

        Body:
            session_id (required): Conversation session identifier.
            agent_id (required): Agent/bot identifier.
            title (optional): Thread title (default "New Conversation").
        """
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
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
            return self.error(
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
                "message": "Thread created",
                "thread": result,
            }, status=201)
        return self.error(
            response={"message": "Failed to create thread"},
            status=500,
        )


@is_authenticated()
@user_session()
class ThreadDetailView(BaseView):
    """Detail operations on a single conversation thread.

    GET    /api/v1/threads/{session_id}    — load turns
    PATCH  /api/v1/threads/{session_id}    — update metadata
    DELETE /api/v1/threads/{session_id}    — delete + cascade
    """

    _logger_name: str = "Parrot.ThreadDetailView"

    def _get_storage(self):
        """Retrieve ChatStorage from the application context."""
        try:
            return self.request.app["chat_storage"]
        except KeyError:
            self.logger.error("chat_storage not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
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
        """Load turns for a conversation thread.

        URL params:
            session_id: Conversation session identifier.
        Query params:
            agent_id (optional): Agent/bot identifier.
            limit (optional): Max turns to return (default 10).
        """
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
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
        agent_id = qs.get("agent_id", "")
        limit = int(qs.get("limit", 10))

        messages = await storage.load_conversation(
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
            limit=limit,
        )

        return self.json_response({
            "session_id": session_id,
            "messages": messages,
            "count": len(messages),
        })

    async def patch(self) -> web.Response:
        """Update thread metadata (title, pinned, tags).

        URL params:
            session_id: Conversation session identifier.
        Body:
            title (optional): New title.
            pinned (optional): Pin/unpin flag.
            tags (optional): List of tags.
            agent_id (required): Agent/bot identifier for DynamoDB PK.
        """
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
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

        try:
            body = await self.json_data()
        except Exception:
            body = {}

        agent_id = body.get("agent_id")
        if not agent_id:
            return self.error(
                response={"message": "agent_id is required"},
                status=400,
            )

        # Build update kwargs from body
        title = body.get("title")
        if title:
            updated = await storage.update_conversation_title(
                session_id=session_id,
                title=title,
                user_id=user_id,
                agent_id=agent_id,
            )
            if not updated:
                return self.error(
                    response={"message": "Failed to update thread"},
                    status=500,
                )

        # For pinned/tags, update directly through DynamoDB if available
        dynamo = getattr(storage, "_dynamo", None)
        if dynamo:
            update_fields = {}
            if "pinned" in body:
                update_fields["pinned"] = bool(body["pinned"])
            if "tags" in body:
                update_fields["tags"] = body["tags"]
            if "archived" in body:
                update_fields["archived"] = bool(body["archived"])
            if update_fields:
                update_fields["updated_at"] = datetime.utcnow()
                await dynamo.update_thread(
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    **update_fields,
                )

        return self.json_response({
            "message": "Thread updated",
            "session_id": session_id,
        })

    async def delete(self) -> web.Response:
        """Delete a thread and cascade-delete all artifacts.

        URL params:
            session_id: Conversation session identifier.
        Query params:
            agent_id (optional): Agent/bot identifier.
        """
        storage = self._get_storage()
        if storage is None:
            return self.error(
                response={"message": "Chat storage not available"},
                status=503,
            )

        user_id = await self._get_user_id()
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
        agent_id = qs.get("agent_id", "")

        # ChatStorage.delete_conversation now cascade-deletes from both tables
        deleted = await storage.delete_conversation(
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        if deleted:
            return self.json_response({
                "message": f"Thread {session_id} deleted",
                "session_id": session_id,
            })
        return self.error(
            response={"message": f"Thread {session_id} not found"},
            status=404,
        )
