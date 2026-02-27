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
                await self._docdb.documentdb_connect()
                await self._ensure_indexes()
            except Exception as exc:
                self.logger.warning(
                    f"Failed to initialize DocumentDB: {exc}"
                )
        self._initialized = True

    async def _ensure_indexes(self) -> None:
        """Create DocumentDB indexes for efficient querying."""
        await self._docdb.create_indexes(
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
        await self._docdb.create_indexes(
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
            # Prepare message dicts
            user_dict = user_msg.to_dict()
            assistant_dict = assistant_msg.to_dict()

            # DIAGNOSTIC: Log what we're about to write
            self.logger.debug(
                f"_save_to_documentdb: Writing 2 messages for session_id={user_msg.session_id}"
            )
            self.logger.debug(
                f"  user_dict keys: {list(user_dict.keys())}, session_id={user_dict.get('session_id')}"
            )
            self.logger.debug(
                f"  assistant_dict keys: {list(assistant_dict.keys())}, session_id={assistant_dict.get('session_id')}"
            )

            # Save both messages
            result = await self._docdb.write(
                MESSAGES_COLLECTION,
                [user_dict, assistant_dict],
            )
            self.logger.debug(f"_save_to_documentdb: write result = {result}")
            # Upsert conversation metadata
            session_id = user_msg.session_id
            user_id = user_msg.user_id
            existing = await self._docdb.read(
                CONVERSATIONS_COLLECTION,
                {"session_id": session_id},
            )
            if existing:
                await self._docdb.update_one(
                    CONVERSATIONS_COLLECTION,
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
                await self._docdb.write(
                    CONVERSATIONS_COLLECTION, conv.to_dict()
                )
            self.logger.debug("Chat turn saved to DocumentDB")
        except Exception as exc:
            self.logger.error(
                f"DocumentDB save failed for session {user_msg.session_id}: {exc}",
                exc_info=True,
            )

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
                self.logger.info(
                    "load_conversation: session_id=%s, user_id=%s, agent_id=%s",
                    session_id, user_id, agent_id,
                )
                # --- Diagnostic: count total docs in collection ---
                try:
                    db_obj = await self._docdb._get_db()
                    coll = db_obj[MESSAGES_COLLECTION]
                    total_count = await coll.count_documents({})
                    session_count = await coll.count_documents(
                        {"session_id": session_id}
                    )
                    self.logger.info(
                        "DIAG: %s has %d total docs, %d for session %s",
                        MESSAGES_COLLECTION, total_count, session_count,
                        session_id,
                    )
                    # If session_count > 0, sample the first doc:
                    if session_count > 0:
                        sample = await coll.find_one({"session_id": session_id})
                        self.logger.info(
                            "DIAG: sample doc keys=%s", list(sample.keys()) if sample else "None"
                        )
                    else:
                        # Sample ANY doc to see the structure
                        any_sample = await coll.find_one({})
                        if any_sample:
                            sample_session_id = any_sample.get('session_id')
                            sample_type = type(sample_session_id).__name__
                            self.logger.info(
                                "DIAG: Random doc has session_id=%r (type=%s), "
                                "query session_id=%r (type=%s)",
                                sample_session_id, sample_type,
                                session_id, type(session_id).__name__
                            )
                            self.logger.info(
                                "DIAG: Random doc keys=%s",
                                list(any_sample.keys())
                            )
                            # Show a few more fields to understand the structure
                            self.logger.info(
                                "DIAG: Random doc preview: message_id=%r, role=%r, user_id=%r, agent_id=%r",
                                any_sample.get('message_id'),
                                any_sample.get('role'),
                                any_sample.get('user_id'),
                                any_sample.get('agent_id'),
                            )
                except Exception as diag_exc:
                    self.logger.warning("DIAG count failed: %s", diag_exc)

                # --- Primary path: find_documents (Motor cursor) ---
                results = await self._docdb.find_documents(
                    MESSAGES_COLLECTION,
                    query={"session_id": session_id},
                    sort=[("timestamp", 1)],
                    limit=limit * 2,
                )
                self.logger.info(
                    "find_documents returned %d messages for session %s",
                    len(results), session_id,
                )

                # --- Fallback: try asyncdb read if find_documents empty ---
                if not results:
                    try:
                        alt_results = await self._docdb.read(
                            MESSAGES_COLLECTION,
                            query={"session_id": session_id},
                            limit=limit * 2,
                        )
                        if isinstance(alt_results, list):
                            self.logger.info(
                                "DIAG read() returned %d messages for session %s",
                                len(alt_results), session_id,
                            )
                            if alt_results:
                                results = alt_results
                        else:
                            self.logger.warning(
                                "DIAG read() returned non-list: %s", type(alt_results)
                            )
                    except Exception as alt_exc:
                        self.logger.warning("DIAG read() failed: %s", alt_exc)

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
            results = await self._docdb.read(
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
            query: Dict[str, Any] = {"user_id": user_id}
            if agent_id:
                query["agent_id"] = agent_id
            if since:
                query["updated_at"] = {"$gte": since.isoformat()}
            results = await self._docdb.find_documents(
                CONVERSATIONS_COLLECTION,
                query=query,
                sort=[("updated_at", -1)],
                limit=limit,
            )
            return results
        except Exception as exc:
            self.logger.warning(f"list_user_conversations failed: {exc}")
        return []

    async def create_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        title: str = "New Conversation",
    ) -> Optional[Dict[str, Any]]:
        """Create a conversation record in DocumentDB."""
        if not self._docdb:
            return None
        now = datetime.utcnow()
        conv = Conversation(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            title=title,
            created_at=now,
            updated_at=now,
            message_count=0,
        )
        try:
            await self._docdb.write(
                CONVERSATIONS_COLLECTION, conv.to_dict()
            )
            self.logger.debug(
                f"Conversation {session_id} created in DocumentDB"
            )
            return conv.to_dict()
        except Exception as exc:
            self.logger.error(
                f"create_conversation failed for {session_id}: {exc}",
                exc_info=True,
            )
            return None

    async def update_conversation_title(
        self,
        session_id: str,
        title: str,
    ) -> bool:
        """Update the title of a conversation in DocumentDB."""
        if not self._docdb:
            return False
        try:
            await self._docdb.update_one(
                CONVERSATIONS_COLLECTION,
                {"session_id": session_id},
                {"$set": {
                    "title": title,
                    "updated_at": datetime.utcnow().isoformat(),
                }},
            )
            self.logger.debug(
                f"Conversation {session_id} title updated to '{title}'"
            )
            return True
        except Exception as exc:
            self.logger.warning(
                f"update_conversation_title failed for {session_id}: {exc}"
            )
            return False

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
                await self._docdb.delete_many(
                    CONVERSATIONS_COLLECTION,
                    {"session_id": session_id},
                )
                await self._docdb.delete_many(
                    MESSAGES_COLLECTION,
                    {"session_id": session_id},
                )
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
