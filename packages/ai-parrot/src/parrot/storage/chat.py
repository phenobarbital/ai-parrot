"""Unified hot+cold chat storage.

Redis (via RedisConversation) for fast access to recent turns.
DynamoDB (via ConversationDynamoDB) for permanent history, search, and analytics.

FEAT-103: Migrated from DocumentDB to DynamoDB.
"""

import asyncio
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from navconfig.logging import logging

from .models import ChatMessage, Conversation, MessageRole, ToolCall, Source


# Default limits
HOT_TTL_HOURS = 48
DEFAULT_LIST_LIMIT = 50
DEFAULT_CONTEXT_TURNS = 10


class ChatStorage:
    """Unified chat persistence with Redis hot cache and DynamoDB cold storage."""

    def __init__(
        self,
        redis_conversation: Optional[Any] = None,
        dynamodb: Optional[Any] = None,
        # Keep document_db for backward compatibility during transition
        document_db: Optional[Any] = None,
    ):
        self._redis = redis_conversation
        self._dynamo = dynamodb
        # Legacy: if document_db is provided but not dynamodb, store it
        self._docdb = document_db
        self._initialized = False
        self.logger = logging.getLogger("parrot.storage.ChatStorage")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect DynamoDB backend and set up Redis."""
        if self._initialized:
            return
        # Lazy import to avoid circular deps
        if self._redis is None:
            try:
                from parrot.memory import RedisConversation  # noqa: E501 pylint: disable=import-outside-toplevel
                self._redis = RedisConversation(key_prefix="chat")
            except Exception as exc:
                self.logger.warning(
                    "RedisConversation unavailable, hot cache disabled: %s", exc
                )

        # Storage backend — selected via PARROT_STORAGE_BACKEND env var (FEAT-116)
        if self._dynamo is None:
            try:
                from parrot.storage.backends import build_conversation_backend  # noqa: E501 pylint: disable=import-outside-toplevel
                self._dynamo = await build_conversation_backend()
                await self._dynamo.initialize()
            except Exception as exc:
                self.logger.warning(
                    "Storage backend unavailable, cold storage disabled: %s", exc
                )

        self._initialized = True

    async def close(self) -> None:
        """Release connections."""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
        if self._dynamo:
            try:
                await self._dynamo.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Save operations
    # ------------------------------------------------------------------

    async def save_turn(
        self,
        *,
        turn_id: Optional[str] = None,
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
        """Save a complete user->assistant turn.

        Writes to Redis (hot) synchronously and to DynamoDB (cold)
        as a fire-and-forget background task.

        Args:
            turn_id: Optional client-provided turn identifier. When the
                frontend sends a ``message_id`` the handler can forward it
                here so both sides share the same ID, preventing duplicates
                on sync.  Falls back to a server-generated UUID when *None*.

        Returns:
            The turn_id used (client-provided or generated).
        """
        turn_id = turn_id or uuid.uuid4().hex
        # Fix #3: always use timezone-aware UTC datetime to avoid comparison
        # errors with backend timestamps (Postgres TIMESTAMPTZ, SQLite ISO strings).
        now = datetime.now(timezone.utc)

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
            timestamp=now + timedelta(milliseconds=1),
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
                self.logger.warning("Redis save_turn failed: %s", exc)

        # --- Cold tier: DynamoDB (fire-and-forget) ---
        if self._dynamo:
            asyncio.get_running_loop().create_task(
                self._save_to_dynamodb(
                    user_msg, assistant_msg, agent_id, now
                )
            )

        return turn_id

    async def _save_to_dynamodb(
        self,
        user_msg: ChatMessage,
        assistant_msg: ChatMessage,
        agent_id: str,
        now: datetime,
    ) -> None:
        """Background task: persist turn + upsert thread metadata in DynamoDB."""
        try:
            session_id = user_msg.session_id
            user_id = user_msg.user_id

            # Prepare turn data
            turn_data = {
                "user_message": user_msg.content,
                "assistant_response": assistant_msg.content,
                "timestamp": now,
                "output": _safe_serialize_value(assistant_msg.output),
                "output_mode": assistant_msg.output_mode,
                "data": _safe_serialize_value(assistant_msg.data),
                "code": assistant_msg.code,
                "model": assistant_msg.model,
                "provider": assistant_msg.provider,
                "response_time_ms": assistant_msg.response_time_ms,
                "tool_calls": [tc.to_dict() for tc in assistant_msg.tool_calls],
                "sources": [s.to_dict() for s in assistant_msg.sources],
                "metadata": assistant_msg.metadata,
            }

            # Extract turn_id from the message_id (e.g. "abc123_user" -> "abc123")
            turn_id = user_msg.message_id.rsplit("_user", 1)[0]

            # Save turn
            await self._dynamo.put_turn(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                turn_id=turn_id,
                data=turn_data,
            )

            # Upsert thread metadata
            await self._dynamo.update_thread(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                updated_at=now,
                last_user_message=user_msg.content[:200],
                last_assistant_message=assistant_msg.content[:200],
                model=assistant_msg.model,
                provider=assistant_msg.provider,
            )

            self.logger.debug("Chat turn saved to DynamoDB")
        except Exception as exc:
            self.logger.warning(
                "DynamoDB save failed for session %s: %s",
                user_msg.session_id, exc,
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
        """Load messages for a conversation, Redis-first with DynamoDB fallback.

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
                self.logger.warning(
                    "Redis load failed, falling back to DynamoDB: %s", exc
                )

        # Fallback: DynamoDB
        if self._dynamo:
            try:
                agent = agent_id or ""
                turns = await self._dynamo.query_turns(
                    user_id=user_id,
                    agent_id=agent,
                    session_id=session_id,
                    limit=limit,
                    newest_first=False,
                )
                messages = []
                for turn in turns:
                    turn_id = turn.get("turn_id", "")
                    ts = turn.get("timestamp", "")
                    messages.append({
                        "role": MessageRole.USER.value,
                        "content": turn.get("user_message", ""),
                        "timestamp": ts,
                        "turn_id": turn_id,
                    })
                    messages.append({
                        "role": MessageRole.ASSISTANT.value,
                        "content": turn.get("assistant_response", ""),
                        "timestamp": ts,
                        "turn_id": turn_id,
                        "output": turn.get("output"),
                        "output_mode": turn.get("output_mode"),
                        "data": turn.get("data"),
                        "code": turn.get("code"),
                        "model": turn.get("model"),
                        "provider": turn.get("provider"),
                        "response_time_ms": turn.get("response_time_ms"),
                        "tool_calls": turn.get("tool_calls", []),
                        "sources": turn.get("sources", []),
                        "metadata": turn.get("metadata", {}),
                    })
                return messages
            except Exception as exc:
                self.logger.warning("DynamoDB load failed: %s", exc)

        return []

    async def get_conversation_metadata(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Load conversation metadata.

        Note: This method requires user_id and agent_id for DynamoDB
        queries. If they are not available, returns None.
        """
        # DynamoDB requires PK (user_id + agent_id) — cannot query by session_id alone
        # without a GSI. Return None for now; callers should use
        # list_user_conversations() with a known user_id.
        return None

    async def list_user_conversations(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List conversations for a user from DynamoDB.

        Returns:
            List of thread metadata dicts, sorted by updated_at desc.
        """
        if not self._dynamo:
            return []
        try:
            agent = agent_id or ""
            threads = await self._dynamo.query_threads(
                user_id=user_id,
                agent_id=agent,
                limit=limit,
            )
            # Filter by 'since' if provided
            if since:
                since_iso = since.isoformat()
                threads = [
                    t for t in threads
                    if t.get("updated_at", "") >= since_iso
                ]
            # Clean up DynamoDB internal fields
            results = []
            for t in threads:
                clean = {k: v for k, v in t.items()
                         if k not in ("PK", "SK", "type", "ttl")}
                results.append(clean)
            return results
        except Exception as exc:
            self.logger.warning("list_user_conversations failed: %s", exc)
        return []

    async def create_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        title: str = "New Conversation",
    ) -> Optional[Dict[str, Any]]:
        """Create a conversation thread in DynamoDB."""
        if not self._dynamo:
            return None
        now = datetime.now(timezone.utc)
        metadata = {
            "title": title,
            "created_at": now,
            "updated_at": now,
            "turn_count": 0,
            "pinned": False,
            "archived": False,
            "tags": [],
        }
        try:
            await self._dynamo.put_thread(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                metadata=metadata,
            )
            self.logger.debug(
                "Conversation %s created in DynamoDB", session_id
            )
            return {
                "session_id": session_id,
                "user_id": user_id,
                "agent_id": agent_id,
                **metadata,
            }
        except Exception as exc:
            self.logger.error(
                "create_conversation failed for %s: %s",
                session_id, exc,
                exc_info=True,
            )
            return None

    async def update_conversation_title(
        self,
        session_id: str,
        title: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Update the title of a conversation in DynamoDB.

        Note: DynamoDB requires user_id and agent_id to build the PK.
        """
        if not self._dynamo or not user_id or not agent_id:
            return False
        try:
            await self._dynamo.update_thread(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                title=title,
                updated_at=datetime.now(timezone.utc),
            )
            self.logger.debug(
                "Conversation %s title updated to '%s'", session_id, title
            )
            return True
        except Exception as exc:
            self.logger.warning(
                "update_conversation_title failed for %s: %s", session_id, exc
            )
            return False

    async def delete_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Delete a conversation from both Redis and DynamoDB.

        Cascade-deletes from both the conversations table and artifacts table.

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
                self.logger.warning("Redis delete failed: %s", exc)

        # DynamoDB: cascade delete from both tables in parallel
        if self._dynamo:
            try:
                agent = agent_id or ""
                conv_deleted, art_deleted = await asyncio.gather(
                    self._dynamo.delete_thread_cascade(user_id, agent, session_id),
                    self._dynamo.delete_session_artifacts(user_id, agent, session_id),
                )
                if conv_deleted > 0 or art_deleted > 0:
                    deleted = True
                self.logger.debug(
                    "Deleted %d conversation items and %d artifacts for session %s",
                    conv_deleted, art_deleted, session_id,
                )
            except Exception as exc:
                self.logger.warning("DynamoDB delete failed: %s", exc)

        return deleted

    async def delete_turn(
        self,
        session_id: str,
        turn_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Delete a single turn from DynamoDB.

        Note: DynamoDB requires user_id and agent_id to build the PK.

        Returns:
            True if deletion succeeded.
        """
        if not self._dynamo or not user_id or not agent_id:
            return False
        try:
            # Delegate to backend ABC — no direct DynamoDB internals here
            ok = await self._dynamo.delete_turn(user_id, agent_id, session_id, turn_id)
            if not ok:
                return False

            # Update thread turn count
            await self._dynamo.update_thread(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                updated_at=datetime.now(timezone.utc),
            )
            self.logger.debug(
                "Deleted turn %s from session %s", turn_id, session_id
            )
            return True
        except Exception as exc:
            self.logger.warning(
                "delete_turn failed for %s in %s: %s", turn_id, session_id, exc
            )
            return False

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

        # Fallback to DynamoDB
        messages = await self.load_conversation(
            user_id, session_id, agent_id=agent_id, limit=max_turns
        )
        return [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        ]


def _safe_serialize_value(obj: Any) -> Any:
    """Convert complex objects to a serializable form for DynamoDB."""
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "to_json"):
        return obj.to_json()
    return obj
