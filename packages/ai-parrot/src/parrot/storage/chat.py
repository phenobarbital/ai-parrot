"""Unified hot+cold chat storage.

Redis (via RedisConversation) for fast access to recent turns.
DynamoDB (via ConversationDynamoDB) for permanent history, search, and analytics.

FEAT-103: Migrated from DocumentDB to DynamoDB.
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timezone

from navconfig.logging import logging

if TYPE_CHECKING:  # pragma: no cover - typing only
    from navigator_eventbus import EventEnvelope
    from ..memory.abstract import ConversationTurn

from ..memory.render import render_history
from ..conf import CHAT_HOT_TTL_HOURS
from ..memory.persistence import CONVERSATION_DELETED_TOPIC
from .errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    InvalidTurnPayloadError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)
from .models import ChatStorageTurn, MessageRole

# Default limits
DEFAULT_LIST_LIMIT = 50
DEFAULT_CONTEXT_TURNS = 10


class ChatStorage:
    """Unified chat persistence with Redis hot cache and DynamoDB cold storage."""

    #: Attempts of the in-process post-delete cleanup retry.
    CLEANUP_RETRY_ATTEMPTS = 12

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
        self._memory_cleaners: List[Callable[[str, str, str], Awaitable[None]]] = []
        self._turn_memory_cleaners: List[Callable[[str, str, str, str], Awaitable[None]]] = []
        self._deletion_publisher: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
        self._cleanup_retries: Dict[Tuple[str, str, str, Optional[str]], "asyncio.Task[None]"] = {}
        #: Base delay (seconds) of the in-process cleanup retry; doubles per attempt, capped at 60 s.
        self.cleanup_retry_base_delay: float = 1.0
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

                self._redis = RedisConversation(
                    key_prefix="chat",
                    history_ttl=CHAT_HOT_TTL_HOURS * 3600 if CHAT_HOT_TTL_HOURS > 0 else None,
                )
            except Exception as exc:
                self.logger.warning("RedisConversation unavailable, hot cache disabled: %s", exc)

        # Storage backend — selected via PARROT_STORAGE_BACKEND env var (FEAT-116)
        if self._dynamo is None:
            try:
                from parrot.storage.backends import (
                    build_conversation_backend,
                )  # noqa: E501 pylint: disable=import-outside-toplevel

                self._dynamo = await build_conversation_backend()
                await self._dynamo.initialize()
            except Exception as exc:
                self.logger.warning("Storage backend unavailable, cold storage disabled: %s", exc)

        self._initialized = True

    @property
    def _backend_label(self) -> str:
        """Friendly name of the active cold-storage backend for log output."""
        if self._dynamo is None:
            return "cold storage"
        cls_name = type(self._dynamo).__name__
        for token, label in (
            ("DynamoDB", "DynamoDB"),
            ("SQLite", "SQLite"),
            ("Postgres", "Postgres"),
            ("Mongo", "MongoDB"),
        ):
            if token in cls_name:
                return label
        return cls_name

    @property
    def cold_backend(self) -> Optional[Any]:
        """The cold-tier ``ConversationBackend`` (read-only), or ``None`` when no backend is configured."""
        return self._dynamo

    @property
    def hot_redis_client(self) -> Optional[Any]:
        """The Redis client behind the hot tier (read-only), or ``None`` when there is no Redis hot tier."""
        return getattr(self._redis, "redis", None)

    def register_memory_cleaner(self, cleaner: Callable[[str, str, str], Awaitable[None]]) -> None:
        """Register a ``(user_id, agent_name, session_id)`` cleaner for one working-memory backend.

        Called after the tombstone is committed, once per delete and again on every cleanup retry,
        so it MUST be idempotent.
        """
        self._memory_cleaners.append(cleaner)

    def register_turn_memory_cleaner(self, cleaner: Callable[[str, str, str, str], Awaitable[None]]) -> None:
        """Register a ``(user_id, agent_name, session_id, turn_id)`` cleaner for one working-memory backend.

        Run after a TURN tombstone is committed (and on every cleanup retry), so a deleted turn is not fed to
        the LLM from a bot's working memory until its TTL. MUST be idempotent.
        """
        self._turn_memory_cleaners.append(cleaner)

    def attach_deletion_publisher(
        self, publisher: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]]
    ) -> None:
        """Set (or clear with ``None``) the callable that publishes deletion events: ``await publisher(topic, payload)``."""
        self._deletion_publisher = publisher

    async def close(self) -> None:
        """Release connections."""
        for task in list(self._cleanup_retries.values()):
            task.cancel()
        self._cleanup_retries.clear()
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
    # Write operations (bus subscriber)
    # ------------------------------------------------------------------

    async def store_turn(self, turn: ChatStorageTurn) -> None:
        """Upsert ``turn`` in the cold tier, update thread metadata, then upsert the hot tier.

        Returns only when both configured tiers hold the turn.

        Raises:
            StorageError: any tier failed (retryable) — nothing is swallowed, nothing is backgrounded.
            ConversationDeletedError: the session or the turn is tombstoned (terminal).
        """
        if self._dynamo is None and self._redis is None:
            raise StorageUnavailableError("no storage tier is configured")
        try:
            if self._dynamo is not None:
                await self._store_cold(turn)
            if self._redis is not None:
                await self._redis.upsert_turn(
                    turn.user_id, turn.session_id, self._hot_tier_turn(turn), chatbot_id=turn.agent_id
                )
            await self._fence_after_write(turn)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 — a foreign exception must still reach the bus as retryable
            raise StorageWriteError(f"store_turn failed for turn {turn.turn_id}: {exc}") from exc

    async def _store_cold(self, turn: ChatStorageTurn) -> None:
        """``put_turn`` (guarded + idempotent in the backend) then ``update_thread``."""
        await self._dynamo.put_turn(turn.user_id, turn.agent_id, turn.session_id, turn.turn_id, turn.to_row())
        await self._dynamo.update_thread(
            user_id=turn.user_id,
            agent_id=turn.agent_id,
            session_id=turn.session_id,
            updated_at=turn.timestamp,
            last_user_message=turn.user_message[:200],
            last_assistant_message=turn.assistant_response[:200],
            model=turn.presentation.model,
            provider=turn.presentation.provider,
        )

    @staticmethod
    def _hot_tier_turn(turn: ChatStorageTurn) -> "ConversationTurn":
        """Working-memory projection of ``turn`` with the slim presentation subset in ``metadata``."""
        ct = turn.to_conversation_turn()
        p = turn.presentation
        extra: Dict[str, Any] = {
            "output_mode": p.output_mode, "model": p.model, "provider": p.provider,
            "response_time_ms": p.response_time_ms,
        }
        for name, value in (("usage", p.usage), ("tenant", p.tenant), ("cost_usd", p.cost_usd)):
            if value is not None:
                extra[name] = value
        ct.metadata = {**ct.metadata, **extra}
        return ct

    async def _fence_after_write(self, turn: ChatStorageTurn) -> None:
        """Re-check the tombstones; if a delete landed meanwhile, undo the resurrected copy and raise."""
        if self._dynamo is None:
            return
        key = (turn.user_id, turn.agent_id, turn.session_id)
        session_gone = await self._dynamo.is_deleted(*key)
        turn_gone = await self._dynamo.is_deleted(*key, turn.turn_id)
        if not (session_gone or turn_gone):
            return
        if session_gone:
            _, errors = await self._cleanup_conversation(turn.user_id, turn.agent_id, turn.session_id)
        else:
            errors = []
            try:
                await self._delete_hot_turn(turn.user_id, turn.session_id, turn.turn_id, turn.agent_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        for exc in errors:
            self.logger.error("post-write cleanup failed for turn %s: %s", turn.turn_id, exc)
        if errors:  # the envelope is acknowledged as terminal below: nothing else would retry this cleanup
            self._schedule_cleanup_retry(turn.user_id, turn.agent_id, turn.session_id,
                                         None if session_gone else turn.turn_id)
        raise ConversationDeletedError(
            f"turn {turn.turn_id} was deleted while it was being stored; the stored copy was removed"
        )

    async def handle_turn_completed(self, envelope: "EventEnvelope") -> None:
        """Bus handler for ``TURN_COMPLETED_TOPIC``.

        Retryable ``StorageError`` propagates (the bus retries, then dead-letters).
        ``ConversationDeletedError`` and ``InvalidTurnPayloadError`` are terminal: logged at
        WARNING with the turn id and acknowledged.
        """
        try:
            await self.store_turn(ChatStorageTurn.from_event_payload(envelope.payload))
        except (ConversationDeletedError, InvalidTurnPayloadError) as exc:
            self.logger.warning("turn %s not stored (terminal %s): %s", envelope.event_id, type(exc).__name__, exc)

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

        Raises:
            ConversationDeletedError: the conversation is tombstoned (even if cleanup has not finished).
            StorageUnavailableError: the deletion guard or the cold tier could not be read.
        """
        await self._ensure_not_deleted(user_id, agent_id or "", session_id)
        # Try Redis first
        if self._redis:
            try:
                history = await self._redis.get_history(user_id, session_id, chatbot_id=agent_id)
                if history and history.turns:
                    messages = []
                    # filter FIRST, then window: a read returns up to ``limit`` LIVE turns
                    visible = (await self._drop_tombstoned_turns(
                        user_id, agent_id or "", session_id, list(history.turns), lambda t: t.turn_id))[-limit:]
                    for turn in visible:
                        messages.append(
                            {
                                "role": MessageRole.USER.value,
                                "content": turn.user_message,
                                "timestamp": (
                                    turn.timestamp.isoformat()
                                    if isinstance(turn.timestamp, datetime)
                                    else str(turn.timestamp)
                                ),
                                "turn_id": turn.turn_id,
                                "metadata": turn.metadata,
                            }
                        )
                        messages.append(
                            {
                                "role": MessageRole.ASSISTANT.value,
                                "content": turn.assistant_response,
                                "timestamp": (
                                    turn.timestamp.isoformat()
                                    if isinstance(turn.timestamp, datetime)
                                    else str(turn.timestamp)
                                ),
                                "turn_id": turn.turn_id,
                                "tools_used": turn.tools_used,
                                "metadata": turn.metadata,
                            }
                        )
                    return messages
            except Exception as exc:
                self.logger.warning(
                    "Redis load failed, falling back to %s: %s",
                    self._backend_label,
                    exc,
                )

        # Fallback: DynamoDB
        if self._dynamo:
            try:
                agent = agent_id or ""
                try:
                    # Chronological: the newest ``limit`` turns by (timestamp, sequence, turn_id), ascending.
                    turns = await self._dynamo.query_turn_window(user_id, agent, session_id, limit)
                except IndexNotReadyError:
                    # Legacy session not backfilled yet: the old (sort_key) order is the best available read.
                    # The window backends already exclude tombstoned turns; this path does not, so ask for the
                    # tombstoned count extra (ONE batched lookup), filter, then apply ``limit`` to live turns.
                    gone = await self._dynamo.deleted_turn_ids(user_id, agent, session_id)
                    turns = await self._dynamo.query_turns(
                        user_id=user_id,
                        agent_id=agent,
                        session_id=session_id,
                        limit=limit + len(gone),
                        newest_first=False,
                    )
                    turns = [t for t in turns if str(t.get("turn_id", "")) not in gone][:limit]
                # NOT filtered again on the window path: ``query_turn_window`` of every backend already excludes
                # tombstoned turns and applies ``limit`` after doing so.
                messages = []
                for row in turns:
                    try:
                        stored = ChatStorageTurn.from_row(
                            {"user_id": user_id, "session_id": session_id, "agent_id": agent, **row}
                        )
                    except (InvalidTurnPayloadError, ValueError) as exc:
                        self.logger.warning("skipping unreadable stored turn %s: %s", row.get("turn_id"), exc)
                        continue
                    messages.extend(stored.to_messages())
                return messages
            except StorageError:
                raise
            except Exception as exc:  # a failed read is raised, never reported as "empty"
                raise StorageUnavailableError(f"{self._backend_label} load failed: {exc}") from exc

        return []

    async def get_conversation_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
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
                threads = [t for t in threads if t.get("updated_at", "") >= since_iso]
            # Clean up DynamoDB internal fields
            results = []
            for t in threads:
                clean = {k: v for k, v in t.items() if k not in ("PK", "SK", "type", "ttl")}
                if await self._dynamo.is_deleted(user_id, t.get("agent_id") or agent, t.get("session_id", "")):
                    continue  # tombstoned: hidden even while its cleanup is still running
                results.append(clean)
            return results
        except StorageError:
            raise
        except Exception as exc:  # a failed read is raised, never reported as "empty"
            raise StorageUnavailableError(f"list_user_conversations failed: {exc}") from exc

    async def create_conversation(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        title: str = "New Conversation",
    ) -> Optional[Dict[str, Any]]:
        """Create a conversation thread in DynamoDB."""
        if not self._dynamo:
            self.logger.warning(
                "create_conversation: cold-storage backend not configured " "(session=%s)",
                session_id,
            )
            return None
        if not getattr(self._dynamo, "is_connected", True):
            self.logger.warning(
                "create_conversation: %s not connected — thread %s will " "NOT be persisted.",
                self._backend_label,
                session_id,
            )
            return None
        await self._ensure_not_deleted(user_id, agent_id, session_id)  # session ids are not reused
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
            self.logger.info(
                "Conversation %s created in %s (user=%s agent=%s)",
                session_id,
                self._backend_label,
                user_id,
                agent_id,
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
                session_id,
                exc,
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
        if not self._dynamo:
            self.logger.warning(
                "update_conversation_title: backend not configured " "(session=%s)",
                session_id,
            )
            return False
        if not user_id or not agent_id:
            self.logger.warning(
                "update_conversation_title: missing PK fields " "(session=%s, user_id=%r, agent_id=%r)",
                session_id,
                user_id,
                agent_id,
            )
            return False
        await self._ensure_not_deleted(user_id, agent_id, session_id)  # never recreate a thread of a deleted session
        try:
            await self._dynamo.update_thread(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                title=title,
                updated_at=datetime.now(timezone.utc),
            )
            self.logger.info(
                "Conversation %s title updated to '%s' (user=%s agent=%s)",
                session_id,
                title,
                user_id,
                agent_id,
            )
            return True
        except Exception as exc:
            self.logger.warning("update_conversation_title failed for %s: %s", session_id, exc)
            return False

    async def assert_conversation_active(self, user_id: str, agent_id: str, session_id: str) -> None:
        """Public deletion guard for callers that write a thread row directly (raises ``ConversationDeletedError``)."""
        await self._ensure_not_deleted(user_id, agent_id, session_id)

    async def _drop_tombstoned_turns(self, user_id: str, agent: str, session_id: str, turns: List[Any],
                                     turn_id_of: Callable[[Any], str]) -> List[Any]:
        """Remove turns whose turn-scoped tombstone exists (a deleted turn is never served, even before cleanup)."""
        if self._dynamo is None or not turns:
            return turns
        try:
            gone = await self._dynamo.deleted_turn_ids(user_id, agent, session_id)  # ONE batched lookup per read
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed: never serve without knowing what was deleted
            raise StorageUnavailableError(f"tombstone lookup unavailable: {exc}") from exc
        return [t for t in turns if turn_id_of(t) not in gone] if gone else turns

    async def _ensure_not_deleted(self, user_id: str, agent: str, session_id: str) -> None:
        """Raise ``ConversationDeletedError`` when the session is tombstoned; a guard failure is raised, not ignored."""
        if self._dynamo is None:
            return
        try:
            deleted = await self._dynamo.is_deleted(user_id, agent, session_id)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"deletion guard unavailable: {exc}") from exc
        if deleted:
            raise ConversationDeletedError(f"conversation {session_id} is deleted")

    def _schedule_cleanup_retry(
        self, user_id: str, agent_id: Optional[str], session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Retry the post-tombstone cleanup in-process (exponential backoff) until it succeeds.

        Independent of the bus: it covers a failed deletion publish and a cleanup that keeps failing.
        """
        key = (user_id, agent_id or "", session_id, turn_id)
        if key in self._cleanup_retries:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._retry_cleanup(key))
        except RuntimeError:  # no running loop (sync caller): the bus event is the only retry
            return
        self._cleanup_retries[key] = task
        task.add_done_callback(lambda _t, k=key: self._cleanup_retries.pop(k, None))

    async def _retry_cleanup(self, key: Tuple[str, str, str, Optional[str]]) -> None:
        user_id, agent, session_id, turn_id = key
        for attempt in range(self.CLEANUP_RETRY_ATTEMPTS):
            await asyncio.sleep(min(self.cleanup_retry_base_delay * (2 ** attempt), 60.0))
            if turn_id:
                errors = (await self._cleanup_turn(user_id, agent, session_id, turn_id))[2]
            else:
                errors = (await self._cleanup_conversation(user_id, agent or None, session_id))[1]
            if not errors:
                self.logger.info("post-delete cleanup of %s finished after %d retries", session_id, attempt + 1)
                return
        self.logger.error("post-delete cleanup of %s still failing after %d retries; the tombstone keeps it "
                          "hidden and the deletion event remains the only retry", session_id,
                          self.CLEANUP_RETRY_ATTEMPTS)

    async def delete_conversation(self, user_id: str, session_id: str, agent_id: Optional[str] = None) -> bool:
        """Tombstone first, then clear cold turns, companions, artifacts and the hot tier, run the cleaners, publish the event.

        Raises:
            StorageError: the tombstone could not be committed — the delete is NOT acknowledged and nothing is cleared.
        """
        agent = agent_id or ""
        await self._commit_tombstone(user_id, agent, session_id)
        deleted, errors = await self._cleanup_conversation(user_id, agent_id, session_id)
        for exc in errors:
            self.logger.error("post-tombstone cleanup failed for session %s (retried): %s", session_id, exc)
        published = await self._publish_deletion({"user_id": user_id, "agent_id": agent, "session_id": session_id})
        if errors or not published:
            self._schedule_cleanup_retry(user_id, agent, session_id)
        return deleted

    async def delete_turn(
        self,
        session_id: str,
        turn_id: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Turn-scoped tombstone first, then delete from the cold and hot tiers; True if either tier removed the turn."""
        if not user_id or not agent_id:
            return False
        await self._commit_tombstone(user_id, agent_id, session_id, turn_id)
        cold, hot, errors = await self._cleanup_turn(user_id, agent_id, session_id, turn_id)
        for exc in errors:
            self.logger.error("post-tombstone cleanup failed for turn %s in %s (retried): %s",
                              turn_id, session_id, exc)
        published = await self._publish_deletion(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "turn_id": turn_id})
        if errors or not published:
            self._schedule_cleanup_retry(user_id, agent_id, session_id, turn_id)
        return cold or hot

    async def _commit_tombstone(
        self, user_id: str, agent: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record the deletion; raise ``StorageError`` (never swallow) when it cannot be committed."""
        if self._dynamo is None:
            return  # no durable store: nothing can resurrect, nothing to fence
        if not agent:
            self.logger.warning(
                "deleting session %s with an empty agent id: the tombstone does not fence turns stored "
                "under a real agent name", session_id)
        try:
            await self._dynamo.put_tombstone(user_id, agent, session_id, turn_id)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageWriteError(f"could not commit the deletion tombstone for {session_id}: {exc}") from exc

    async def _cleanup_conversation(
        self, user_id: str, agent_id: Optional[str], session_id: str
    ) -> Tuple[bool, List[BaseException]]:
        """Idempotent post-tombstone cleanup. Returns ``(something_deleted, errors)``; never raises."""
        deleted = False
        errors: List[BaseException] = []
        if self._redis:
            try:
                deleted = bool(await self._redis.delete_history(user_id, session_id, chatbot_id=agent_id)) or deleted
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        if self._dynamo:
            agent = agent_id or ""
            try:
                conv_deleted, art_deleted = await asyncio.gather(
                    self._dynamo.delete_thread_cascade(user_id, agent, session_id),
                    self._dynamo.delete_session_artifacts(user_id, agent, session_id),
                )
                deleted = deleted or conv_deleted > 0 or art_deleted > 0
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        for cleaner in self._memory_cleaners:
            try:
                await cleaner(user_id, agent_id or "", session_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        return deleted, errors

    async def _cleanup_turn(
        self, user_id: str, agent_id: str, session_id: str, turn_id: str
    ) -> Tuple[bool, bool, List[BaseException]]:
        """Remove one turn from both tiers; returns ``(cold_removed, hot_removed, errors)``; never raises."""
        errors: List[BaseException] = []
        cold = hot = False
        if self._dynamo:
            try:
                cold = bool(await self._dynamo.delete_turn(user_id, agent_id, session_id, turn_id))
                if cold:
                    await self._dynamo.update_thread(
                        user_id=user_id, agent_id=agent_id, session_id=session_id,
                        updated_at=datetime.now(timezone.utc))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        try:
            hot = await self._delete_hot_turn(user_id, session_id, turn_id, agent_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        for cleaner in self._turn_memory_cleaners:
            try:
                await cleaner(user_id, agent_id, session_id, turn_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        return cold, hot, errors

    async def _delete_hot_turn(self, user_id: str, session_id: str, turn_id: str, agent_id: str) -> bool:
        """Remove ``turn_id`` from the hot-tier history, if it holds one.

        Args:
            user_id: Conversation owner.
            session_id: Conversation session.
            turn_id: The turn to drop.
            agent_id: ChatStorage key (agent NAME); the hot tier stores it as ``chatbot_id``.

        Returns:
            True when this call removed the turn from the hot tier; False when it held no such turn.

        Raises:
            Exception: whatever the hot tier raises — the callers collect it and retry via the deletion event.
        """
        if not self._redis:
            return False
        history = await self._redis.get_history(user_id, session_id, chatbot_id=agent_id)
        if history is None:
            return False
        kept = [t for t in history.turns if t.turn_id != turn_id]
        if len(kept) == len(history.turns):
            return False
        history.turns = kept
        await self._redis.update_history(history)
        return True

    async def _publish_deletion(self, payload: Dict[str, Any]) -> bool:
        """Publish the deletion event; a failure is logged, never raised.

        Returns:
            ``True`` when published or when no publisher is attached (no bus retry exists, nothing to wait
            for); ``False`` when the publish failed (the caller then falls back to the in-process retry).
        """
        if self._deletion_publisher is None:
            return True
        try:
            await self._deletion_publisher(CONVERSATION_DELETED_TOPIC, payload)
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.error("could not publish the deletion event for %s: %s", payload.get("session_id"), exc)
            return False

    async def handle_conversation_deleted(self, envelope: "EventEnvelope") -> None:
        """Idempotent cleanup retry for ``CONVERSATION_DELETED_TOPIC``; raises ``StorageWriteError`` while any step fails."""
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        user_id, session_id = payload.get("user_id"), payload.get("session_id")
        if not user_id or not session_id:
            self.logger.warning("malformed deletion event %s: %r", envelope.event_id, payload)
            return
        agent = payload.get("agent_id") or ""
        turn_id = payload.get("turn_id")
        if turn_id:
            _, _, errors = await self._cleanup_turn(user_id, agent, session_id, turn_id)
        else:
            _, errors = await self._cleanup_conversation(user_id, agent or None, session_id)
        if errors:
            raise StorageWriteError(
                f"deletion cleanup for session {session_id} still failing: "
                + "; ".join(str(e) for e in errors)
            ) from errors[0]

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

        Raises:
            ConversationDeletedError: the conversation is tombstoned.
        """
        await self._ensure_not_deleted(user_id, agent_id or "", session_id)
        # Try Redis first for speed
        if self._redis:
            try:
                history = await self._redis.get_history(user_id, session_id, chatbot_id=agent_id)
                if history and history.turns:
                    # FEAT-524: ConversationHistory.get_messages_for_api() was
                    # removed; render_history() replaces it. Without this the
                    # AttributeError would be swallowed by the `except Exception:
                    # pass` below and this Redis fast path would silently fall
                    # through to DynamoDB forever.
                    history.turns = await self._drop_tombstoned_turns(
                        user_id, agent_id or "", session_id, list(history.turns), lambda t: t.turn_id)
                    return [
                        {"role": m.role, "content": m.content} for m in render_history(history, max_turns=max_turns)
                    ]
            except Exception:
                pass

        # Fallback to DynamoDB
        messages = await self.load_conversation(user_id, session_id, agent_id=agent_id, limit=max_turns)
        return [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages]
