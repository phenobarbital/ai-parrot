"""Unified hot+cold chat storage.

Redis (via RedisConversation) for fast access to recent turns.
DocumentDB for permanent history, search, and analytics.
"""

import asyncio
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from navconfig.logging import logging

from .models import ChatMessage, Conversation, MessageRole, ToolCall, Source


# DocumentDB collection names
CONVERSATIONS_COLLECTION = "chat_conversations"
MESSAGES_COLLECTION = "chat_messages"

# Default limits
HOT_TTL_HOURS = 48
DEFAULT_LIST_LIMIT = 50
DEFAULT_CONTEXT_TURNS = 10


class ChatStorage:
    """Unified chat persistence with Redis hot cache and DocumentDB cold storage."""

    def __init__(
        self,
        redis_conversation: Optional[Any] = None,
        document_db: Optional[Any] = None,
    ):
        self._redis = redis_conversation
        self._docdb = document_db
        self._initialized = False
        self.logger = logging.getLogger("parrot.storage.ChatStorage")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect DocumentDB and ensure indexes exist."""
        if self._initialized:
            return
        # Lazy import to avoid circular deps
        if self._redis is None:
            try:
                from parrot.memory import RedisConversation  # noqa: E501 pylint: disable=import-outside-toplevel
                self._redis = RedisConversation(key_prefix="chat")
            except Exception as exc:
                self.logger.warning(
                    f"RedisConversation unavailable, hot cache disabled: {exc}"
                )
        if self._docdb is None:
            try:
                from parrot.interfaces.documentdb import DocumentDb  # noqa: E501 pylint: disable=import-outside-toplevel
                self._docdb = DocumentDb()
            except Exception as exc:
                self.logger.warning(
                    f"DocumentDb unavailable, cold storage disabled: {exc}"
                )
        # Ensure DocumentDB indexes
        if self._docdb:
            try:
                await self._ensure_indexes()
            except Exception as exc:
                self.logger.warning(
                    f"Failed to create DocumentDB indexes: {exc}"
                )
        self._initialized = True

    async def _ensure_indexes(self) -> None:
        """Create DocumentDB indexes for efficient querying."""
        async with self._docdb as db:
            # Conversations collection indexes
            await db.create_indexes(
                CONVERSATIONS_COLLECTION,
                [
                    "session_id",
                    "user_id",
                    "agent_id",
                    ("updated_at", -1),
                    {
                        "keys": [("user_id", 1), ("updated_at", -1)],
                    },
                    {
                        "keys": [("user_id", 1), ("agent_id", 1), ("updated_at", -1)],
                    },
                ],
            )
            # Messages collection indexes
            await db.create_indexes(
                MESSAGES_COLLECTION,
                [
                    "session_id",
                    "user_id",
                    "message_id",
                    ("timestamp", -1),
                    {
                        "keys": [("session_id", 1), ("timestamp", 1)],
                    },
                    {
                        "keys": [("user_id", 1), ("session_id", 1), ("timestamp", 1)],
                    },
                ],
            )

    async def close(self) -> None:
        """Release connections."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
        if self._docdb:
            try:
                await self._docdb.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Save operations
    # ------------------------------------------------------------------

    async def save_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        agent_id: str,
        user_message: str,
        assistant_response: str,
        output: Any = None,
        output_mode: Optional[str] = None,
        data: Any = None,
        code: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        response_time_ms: Optional[int] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Save a complete user→assistant turn.

        Writes to Redis (hot) synchronously and to DocumentDB (cold)
        as a fire-and-forget background task.

        Returns:
            The generated turn_id.
        """
        turn_id = uuid.uuid4().hex
        now = datetime.now()

        # Build ChatMessage objects
        user_msg = ChatMessage(
            message_id=f"{turn_id}_user",
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            role=MessageRole.USER.value,
            content=user_message,
            timestamp=now,
        )

        tool_call_objs = [
            ToolCall.from_dict(tc) for tc in (tool_calls or [])
        ]
        source_objs = [
            Source.from_dict(s) for s in (sources or [])
        ]

        assistant_msg = ChatMessage(
            message_id=f"{turn_id}_assistant",
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            role=MessageRole.ASSISTANT.value,
            content=assistant_response or "",
            timestamp=now,
            output=output,
            output_mode=output_mode,
            data=data,
            code=code,
            model=model,
            provider=provider,
            response_time_ms=response_time_ms,
            tool_calls=tool_call_objs,
            sources=source_objs,
            metadata=metadata or {},
        )

        # --- Hot tier: Redis ---
        if self._redis:
            try:
                from parrot.memory.abstract import ConversationTurn  # noqa: E501 pylint: disable=import-outside-toplevel
                turn = ConversationTurn(
                    turn_id=turn_id,
                    user_id=user_id,
                    user_message=user_message,
                    assistant_response=assistant_response or "",
                    tools_used=[tc.name for tc in tool_call_objs],
                    timestamp=now,
                    metadata={
                        "output_mode": output_mode,
                        "model": model,
                        "provider": provider,
                        "response_time_ms": response_time_ms,
                    },
                )
                # Ensure conversation history exists, then add turn
                history = await self._redis.get_history(
                    user_id, session_id, chatbot_id=agent_id
                )
                if not history:
                    await self._redis.create_history(
                        user_id, session_id, chatbot_id=agent_id
                    )
                await self._redis.add_turn(
                    user_id, session_id, turn, chatbot_id=agent_id
                )
            except Exception as exc:
                self.logger.warning(f"Redis save_turn failed: {exc}")

        # --- Cold tier: DocumentDB (fire-and-forget) ---
        if self._docdb:
            asyncio.get_running_loop().create_task(
                self._save_to_documentdb(
                    user_msg, assistant_msg, agent_id, now
                )
            )

        return turn_id

    async def _save_to_documentdb(
        self,
        user_msg: ChatMessage,
        assistant_msg: ChatMessage,
        agent_id: str,
        now: datetime,
    ) -> None:
        """Background task: persist messages + upsert conversation metadata."""
        try:
            async with self._docdb as db:
                # Save both messages
                await db.write(
                    MESSAGES_COLLECTION,
                    [user_msg.to_dict(), assistant_msg.to_dict()],
                )
                # Upsert conversation metadata
                session_id = user_msg.session_id
                user_id = user_msg.user_id
                existing = await db.read(
                    CONVERSATIONS_COLLECTION,
                    {"session_id": session_id},
                )
                if existing:
                    # Update existing
                    collection = db._db.get_collection(CONVERSATIONS_COLLECTION)
                    await collection.update_one(
                        {"session_id": session_id},
                        {
                            "$set": {
                                "updated_at": now.isoformat(),
                                "last_user_message": user_msg.content[:200],
                                "last_assistant_message": assistant_msg.content[:200],
                                "model": assistant_msg.model,
                                "provider": assistant_msg.provider,
                            },
                            "$inc": {"message_count": 2},
                        },
                    )
                else:
                    # Create new conversation
                    conv = Conversation(
                        session_id=session_id,
                        user_id=user_id,
                        agent_id=agent_id,
                        title=user_msg.content[:100],
                        created_at=now,
                        updated_at=now,
                        message_count=2,
                        last_user_message=user_msg.content[:200],
                        last_assistant_message=assistant_msg.content[:200],
                        model=assistant_msg.model,
                        provider=assistant_msg.provider,
                    )
                    await db.write(
                        CONVERSATIONS_COLLECTION, conv.to_dict()
                    )
            self.logger.debug("Chat turn saved to DocumentDB")
        except Exception as exc:
            self.logger.warning(f"DocumentDB save failed: {exc}")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def load_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> List[Dict[str, Any]]:
        """Load messages for a conversation, Redis-first with DocumentDB fallback.

        Returns:
            List of message dicts, sorted by timestamp ascending.
        """
        # Try Redis first
        if self._redis:
            try:
                history = await self._redis.get_history(
                    user_id, session_id, chatbot_id=agent_id
                )
                if history and history.turns:
                    messages = []
                    for turn in history.turns[-limit:]:
                        messages.append({
                            "role": MessageRole.USER.value,
                            "content": turn.user_message,
                            "timestamp": turn.timestamp.isoformat()
                            if isinstance(turn.timestamp, datetime)
                            else str(turn.timestamp),
                            "turn_id": turn.turn_id,
                            "metadata": turn.metadata,
                        })
                        messages.append({
                            "role": MessageRole.ASSISTANT.value,
                            "content": turn.assistant_response,
                            "timestamp": turn.timestamp.isoformat()
                            if isinstance(turn.timestamp, datetime)
                            else str(turn.timestamp),
                            "turn_id": turn.turn_id,
                            "tools_used": turn.tools_used,
                            "metadata": turn.metadata,
                        })
                    return messages
            except Exception as exc:
                self.logger.warning(f"Redis load failed, falling back to DocumentDB: {exc}")

        # Fallback: DocumentDB
        if self._docdb:
            try:
                async with self._docdb as db:
                    collection = db._db.get_collection(MESSAGES_COLLECTION)
                    query = {"session_id": session_id, "user_id": user_id}
                    cursor = collection.find(query).sort("timestamp", 1).limit(limit * 2)
                    results = []
                    async for doc in cursor:
                        doc.pop("_id", None)
                        results.append(doc)
                    return results
            except Exception as exc:
                self.logger.warning(f"DocumentDB load failed: {exc}")

        return []

    async def get_conversation_metadata(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Load conversation metadata from DocumentDB."""
        if not self._docdb:
            return None
        try:
            async with self._docdb as db:
                results = await db.read(
                    CONVERSATIONS_COLLECTION,
                    {"session_id": session_id},
                )
                if results:
                    doc = results[0] if isinstance(results, list) else results
                    doc.pop("_id", None)
                    return doc
        except Exception as exc:
            self.logger.warning(f"get_conversation_metadata failed: {exc}")
        return None

    async def list_user_conversations(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List conversations for a user from DocumentDB.

        Returns:
            List of Conversation dicts, sorted by updated_at desc.
        """
        if not self._docdb:
            return []
        try:
            async with self._docdb as db:
                query: Dict[str, Any] = {"user_id": user_id}
                if agent_id:
                    query["agent_id"] = agent_id
                if since:
                    query["updated_at"] = {"$gte": since.isoformat()}
                collection = db._db.get_collection(CONVERSATIONS_COLLECTION)
                cursor = collection.find(query).sort("updated_at", -1).limit(limit)
                results = []
                async for doc in cursor:
                    doc.pop("_id", None)
                    results.append(doc)
                return results
        except Exception as exc:
            self.logger.warning(f"list_user_conversations failed: {exc}")
        return []

    async def delete_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Delete a conversation from both Redis and DocumentDB.

        Returns:
            True if at least one store deleted successfully.
        """
        deleted = False

        # Redis
        if self._redis:
            try:
                result = await self._redis.delete_history(
                    user_id, session_id, chatbot_id=agent_id
                )
                if result:
                    deleted = True
            except Exception as exc:
                self.logger.warning(f"Redis delete failed: {exc}")

        # DocumentDB
        if self._docdb:
            try:
                async with self._docdb as db:
                    collection_conv = db._db.get_collection(CONVERSATIONS_COLLECTION)
                    collection_msg = db._db.get_collection(MESSAGES_COLLECTION)
                    await collection_conv.delete_many({"session_id": session_id})
                    await collection_msg.delete_many({"session_id": session_id})
                    deleted = True
            except Exception as exc:
                self.logger.warning(f"DocumentDB delete failed: {exc}")

        return deleted

    async def get_context_for_agent(
        self,
        user_id: str,
        session_id: str,
        agent_id: Optional[str] = None,
        max_turns: int = DEFAULT_CONTEXT_TURNS,
        model: str = "claude",
    ) -> List[Dict[str, str]]:
        """Return recent messages formatted for LLM context window.

        Returns:
            List of {role, content} dicts ready for the model API.
        """
        # Try Redis first for speed
        if self._redis:
            try:
                history = await self._redis.get_history(
                    user_id, session_id, chatbot_id=agent_id
                )
                if history and history.turns:
                    return history.get_messages_for_api(model=model)[-max_turns * 2:]
            except Exception:
                pass

        # Fallback to DocumentDB
        messages = await self.load_conversation(
            user_id, session_id, agent_id=agent_id, limit=max_turns
        )
        return [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        ]
