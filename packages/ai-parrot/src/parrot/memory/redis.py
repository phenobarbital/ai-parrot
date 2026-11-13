from typing import List, Dict, Any, Callable, Optional, TYPE_CHECKING
from datetime import datetime, timezone
import asyncio
import json
import random
from redis.asyncio import Redis
from redis.exceptions import WatchError
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .abstract import (
    ConversationMemory,
    ConversationHistory,
    ConversationTurn,
    is_hydration_pending,
    merge_pending_history,
)
from .compaction.omission import OmissionStore, RedisOmissionStore
from ..conf import REDIS_HISTORY_URL

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .compaction.tokens import TokenCounter

#: How many times a compare-and-merge retries before giving up (FEAT-538).
#: Bounded on purpose: an unbounded retry under sustained contention would
#: turn a lost update into a hang, which is harder to diagnose and worse
#: to operate.
_MERGE_MAX_ATTEMPTS: int = 16

#: Base backoff between compare-and-swap retries, in seconds.
#: Retrying immediately is what turns contention into a thundering herd:
#: every loser re-reads at the same instant and collides again. Jittered
#: exponential backoff spreads them out, which is the difference between
#: "converges" and "exhausts the budget" once more than a couple of
#: writers are involved.
_MERGE_BACKOFF_BASE: float = 0.002
_MERGE_BACKOFF_CAP: float = 0.100


def _turn_sort_key(turn: Dict[str, Any]) -> Optional[tuple]:
    """``(UTC timestamp, sequence or 0, turn_id)`` of a stored turn dict, or ``None`` when unparseable."""
    try:
        ts = datetime.fromisoformat(str(turn["timestamp"]))
    except (KeyError, ValueError, TypeError):
        return None
    ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    return ts, int(turn.get("sequence") or 0), str(turn.get("turn_id", ""))


def _upsert_turn_dict(turns: List[Dict[str, Any]], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Replace the dict with ``new['turn_id']`` (keeping its ``timestamp``/``sequence``) or insert it chronologically."""
    result = list(turns)
    for i, old in enumerate(result):
        if old.get("turn_id") == new.get("turn_id"):
            result[i] = {**new, "timestamp": old.get("timestamp", new.get("timestamp")),
                         "sequence": old.get("sequence")}
            return result
    new_key = _turn_sort_key(new)
    if new_key is None:
        return result + [new]
    insert_at = len(result)
    for i, old in enumerate(result):
        old_key = _turn_sort_key(old)
        if old_key is None:
            return result + [new]  # an unparseable stored timestamp: never reorder around it
        if old_key > new_key:
            insert_at = i
            break
    result.insert(insert_at, new)
    return result


def _without_turn(turns: Any, turn_id: str) -> Optional[List[Dict[str, Any]]]:
    """``turns`` minus the stored turn ``turn_id``; ``None`` when ``turns`` is not a list or holds no such turn."""
    if not isinstance(turns, list):
        return None
    kept = [t for t in turns if not (isinstance(t, dict) and t.get("turn_id") == turn_id)]
    return kept if len(kept) != len(turns) else None


_INSTALL_NX_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], unpack(ARGV))
return 1
"""


async def _merge_backoff(attempt: int) -> None:
    """Sleep for a jittered exponential interval before retrying a CAS.

    Args:
        attempt: Zero-based retry number.
    """
    delay = min(_MERGE_BACKOFF_BASE * (2**attempt), _MERGE_BACKOFF_CAP)
    await asyncio.sleep(random.uniform(0, delay))


class RedisConversation(ConversationMemory):
    """Redis-based conversation memory with proper encoding handling."""

    history_ttl: Optional[int] = None  # class default: instances built without __init__ (test doubles) stay TTL-less

    def __init__(
        self,
        redis_url: str = None,
        key_prefix: str = "conversation",
        use_hash_storage: bool = True,
        *,
        token_counter: Optional["TokenCounter"] = None,
        omission_store: Optional[OmissionStore] = None,
        normalize: bool = True,
        omission_ttl: Optional[int] = None,
        history_ttl: Optional[int] = None,
    ) -> None:
        """Initialize the store.

        Args:
            redis_url: Redis connection URL; defaults to
                ``REDIS_HISTORY_URL``.
            key_prefix: Prefix for every history key this instance owns
                (e.g. ``"chat"`` for the ``ChatStorage`` cold tier).
            use_hash_storage: Whether to use Redis hashes (recommended) or
                plain string keys.
            token_counter: Stage 0.5 counter override (see
                :class:`~parrot.memory.abstract.ConversationMemory`).
            omission_store: Omission-store override; defaults to a
                :class:`~parrot.memory.compaction.omission.RedisOmissionStore`
                sharing this instance's Redis client.
            normalize: Disables Stage 0 for this instance when ``False``.
            omission_ttl: Expiry (seconds) for the default omission store;
                ``None`` (default) means no expiry, independent of the
                (TTL-less) history keys.
            history_ttl: Expiry (seconds) refreshed on every write to a
                history key, so an idle conversation expires. ``None``
                (default) keeps history keys TTL-less.
        """
        self.history_ttl = history_ttl if history_ttl and history_ttl > 0 else None
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.key_prefix = key_prefix
        self.use_hash_storage = use_hash_storage
        self.redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        super().__init__(
            token_counter=token_counter,
            omission_store=omission_store
            or RedisOmissionStore(self.redis, key_prefix=self.key_prefix, ttl=omission_ttl),
            normalize=normalize,
        )

    def _supports_cas(self) -> bool:
        """Whether the client can do ``WATCH``/``MULTI``/``EXEC`` (FEAT-538).

        Real Redis can. Lightweight test doubles and Redis-compatible
        clients without transaction support cannot, and calling
        ``pipeline()`` on them raises. Those clients fall back to the
        pre-FEAT-538 direct write: a single-process double has no
        competing writer for a compare-and-swap to protect against, so
        the fallback costs nothing there — and crashing on them would be
        a regression in behaviour that the atomicity work is not entitled
        to cause.

        Returns:
            ``True`` when the compare-and-swap path is usable.
        """
        return callable(getattr(self.redis, "pipeline", None))

    def _get_key(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> str:
        """Generate Redis key for conversation history."""
        parts = [self.key_prefix]
        if chatbot_id:
            parts.append(str(chatbot_id))
        parts.extend([str(user_id), str(session_id)])
        return ":".join(parts)

    def _get_user_sessions_key(self, user_id: str, chatbot_id: Optional[str] = None) -> str:
        """Generate Redis key for user's session list."""
        parts = [f"{self.key_prefix}_sessions"]
        if chatbot_id:
            parts.append(str(chatbot_id))
        parts.append(str(user_id))
        return ":".join(parts)

    def _serialize_data(self, data: Any) -> str:
        """Serialize data to JSON string with proper encoding."""
        try:
            # Use standard json module with specific settings to avoid encoding issues
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
        except Exception as e:
            print(f"Serialization error: {e}")
            # Fallback to your custom encoder
            return json_encoder(data)

    def _deserialize_data(self, data: str) -> Any:
        """Deserialize JSON string to Python object."""
        try:
            # Use standard json module first
            return json.loads(data)
        except Exception as e:
            print(f"Deserialization error with standard json: {e}")
            # Fallback to your custom decoder
            try:
                # Fallback to your custom decoder
                return json_decoder(data)
            except Exception as e2:
                print(f"Deserialization error with custom decoder: {e2}")
                print(f"Problematic data (first 200 chars): {data[:200]}")
                return None

    async def create_history(
        self,
        user_id: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        chatbot_id: Optional[str] = None,
    ) -> ConversationHistory:
        """Create a new conversation history."""
        history = ConversationHistory(
            session_id=session_id, user_id=user_id, chatbot_id=chatbot_id, metadata=metadata or {}
        )

        if self.use_hash_storage:
            # Method 1: Using Redis Hash (RECOMMENDED for objects)
            key = self._get_key(user_id, session_id, chatbot_id)
            await self.redis.hset(key, mapping=self._history_mapping(history))
        else:
            # Method 2: Using simple key-value storage
            key = self._get_key(user_id, session_id, chatbot_id)
            serialized_data = self._serialize_data(history.to_dict())
            await self.redis.set(key, serialized_data)

        # Add to user sessions set
        await self.redis.sadd(self._get_user_sessions_key(user_id, chatbot_id), session_id)
        await self._refresh_ttl(user_id, session_id, chatbot_id)
        return history

    async def get_history(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get a conversation history, re-keying a legacy record if needed.

        FEAT-524 unified the storage key to ``(chatbot, user, session)``.
        Histories written before that live under the un-segmented
        ``conversation:{user}:{session}`` key, and these keys carry no TTL, so
        without a fallback every live conversation would silently restart the
        first time a bot asked for its history under the new key.

        When ``chatbot_id`` is given and the segmented key holds nothing, the
        legacy key is read once, copied under the segmented key and returned.
        The legacy record is deliberately **left in place** so a rollback still
        finds it. The copy is idempotent, so two concurrent first reads racing
        each other is benign — no locking (spec §7 "Re-key race").

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent key segment. Falsy means "read the legacy key
                directly" — no re-key is attempted.

        Returns:
            The history, or ``None`` when neither key holds one.
        """
        history = await self._load_history(user_id, session_id, chatbot_id)
        if history is not None or not chatbot_id:
            return history

        legacy = await self._load_history(user_id, session_id, None)
        if legacy is None:
            return None

        legacy.chatbot_id = str(chatbot_id)
        await self.update_history(legacy)
        # Keep list_sessions(user_id, chatbot_id) able to find the migrated
        # session — update_history alone only writes the history key.
        await self.redis.sadd(self._get_user_sessions_key(user_id, chatbot_id), session_id)
        self.logger.info("Re-keyed legacy conversation %s/%s under chatbot %s", user_id, session_id, chatbot_id)
        return legacy

    async def _load_history(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Read the history stored at exactly one key, without any fallback.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent key segment; ``None`` reads the un-segmented key.

        Returns:
            The deserialized history, or ``None`` if the key is empty or the
            stored payload cannot be parsed.
        """
        key = self._get_key(user_id, session_id, chatbot_id)

        if self.use_hash_storage:
            # Method 1: Get from Redis Hash
            data = await self.redis.hgetall(key)
            if not data:
                return None

            try:
                # Reconstruct the history dict
                history_dict = {
                    "session_id": data.get("session_id", session_id),
                    "user_id": data.get("user_id", user_id),
                    "chatbot_id": data.get("chatbot_id", chatbot_id),
                    "turns": self._deserialize_data(data.get("turns", "[]")),
                    "created_at": data.get("created_at", datetime.now().isoformat()),
                    "updated_at": data.get("updated_at", datetime.now().isoformat()),
                    "metadata": self._deserialize_data(data.get("metadata", "{}")),
                }
                return ConversationHistory.from_dict(history_dict)
            except (KeyError, ValueError) as e:
                print(f"Error deserializing conversation history: {e}")
                return None
        else:
            # Method 2: Get from simple key-value
            data = await self.redis.get(key)
            if data:
                try:
                    history_dict = self._deserialize_data(data)
                    if history_dict is not None and chatbot_id and not history_dict.get("chatbot_id"):
                        history_dict["chatbot_id"] = chatbot_id
                    return ConversationHistory.from_dict(history_dict)
                except (ValueError, KeyError) as e:
                    print(f"Error deserializing conversation history: {e}")
                    return None
            return None

    def _history_mapping(self, history: ConversationHistory) -> Dict[str, str]:
        """The hash fields of one history (single source for create / install / merge)."""
        data = history.to_dict()
        mapping = {
            "session_id": str(data["session_id"]),
            "user_id": str(data["user_id"]),
            "turns": self._serialize_data(data["turns"]),
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "metadata": self._serialize_data(data["metadata"]),
        }
        if data.get("chatbot_id") is not None:
            mapping["chatbot_id"] = str(data["chatbot_id"])
        return mapping

    async def _install_history(self, history: ConversationHistory) -> bool:
        """Atomic NX install (single Lua script in hash mode, ``SET NX`` in string mode); pending histories merge by CAS."""
        key = self._get_key(history.user_id, history.session_id, history.chatbot_id)
        if history.chatbot_id:
            legacy = self._get_key(history.user_id, history.session_id, None)
            if legacy != key and not await self.redis.exists(key) and await self.redis.exists(legacy):
                await self.get_history(history.user_id, history.session_id, history.chatbot_id)  # FEAT-524 re-key
                return False  # never shadow a legacy history
        if self.use_hash_storage:
            flat = [x for item in self._history_mapping(history).items() for x in item]
            installed = bool(await self.redis.eval(_INSTALL_NX_LUA, 1, key, *flat))
        else:
            installed = bool(await self.redis.set(key, self._serialize_data(history.to_dict()), nx=True))
        if installed:
            await self.redis.sadd(self._get_user_sessions_key(history.user_id, history.chatbot_id), history.session_id)
            await self._refresh_ttl(history.user_id, history.session_id, history.chatbot_id)
            return True
        return await self._merge_pending(key, history)

    def _merged_or_none(
        self, existing: Optional[ConversationHistory], history: ConversationHistory
    ) -> Optional[ConversationHistory]:
        """The history to write for a pending merge, or ``None`` when the existing one is not pending."""
        if existing is None:
            return history
        if is_hydration_pending(existing.metadata):
            return merge_pending_history(existing, history)
        return None

    async def _write_merged(self, conn: Any, key: str, merged: ConversationHistory) -> None:
        if self.use_hash_storage:
            conn.hset(key, mapping=self._history_mapping(merged))
        else:
            conn.set(key, self._serialize_data(merged.to_dict()))

    async def _merge_pending(self, key: str, history: ConversationHistory) -> bool:
        """CAS-merge ``history`` into an existing PENDING history; ``False`` when the existing one is not pending."""
        if not self._supports_cas():
            merged = self._merged_or_none(
                await self._load_history(history.user_id, history.session_id, history.chatbot_id), history)
            if merged is None:
                return False
            await self.update_history(merged)
            await self._refresh_ttl(history.user_id, history.session_id, history.chatbot_id)
            return True
        for attempt in range(_MERGE_MAX_ATTEMPTS):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    existing = await self._load_history(history.user_id, history.session_id, history.chatbot_id)
                    merged = self._merged_or_none(existing, history)
                    if merged is None:
                        await pipe.unwatch()
                        return False
                    pipe.multi()
                    await self._write_merged(pipe, key, merged)
                    await pipe.execute()
                    await self._refresh_ttl(history.user_id, history.session_id, history.chatbot_id)
                    return True
                except WatchError:
                    pass
            await _merge_backoff(attempt)
        raise RuntimeError(f"history install for {key} still conflicting after {_MERGE_MAX_ATTEMPTS} attempts")

    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        key = self._get_key(history.user_id, history.session_id, history.chatbot_id)

        if self.use_hash_storage:
            # Method 1: Update Redis Hash
            history_dict = history.to_dict()
            mapping = {
                "session_id": history_dict["session_id"],
                "user_id": history_dict["user_id"],
                "turns": self._serialize_data(history_dict["turns"]),
                "created_at": history_dict["created_at"],
                "updated_at": history_dict["updated_at"],
                "metadata": self._serialize_data(history_dict["metadata"]),
            }
            if history_dict.get("chatbot_id") is not None:
                mapping["chatbot_id"] = history_dict["chatbot_id"]
            await self.redis.hset(key, mapping=mapping)
        else:
            # Method 2: Update simple key-value
            serialized_data = self._serialize_data(history.to_dict())
            await self.redis.set(key, serialized_data)
        await self._refresh_ttl(history.user_id, history.session_id, history.chatbot_id)

    async def read_metadata(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Read a conversation's whole ``metadata`` blob (FEAT-538).

        In hash mode this is a single targeted ``hget``, avoiding the
        FEAT-524 lazy legacy re-key that a full :meth:`get_history` may
        perform as a side effect.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent key segment.

        Returns:
            The metadata dict, or ``None`` when the conversation has none.
        """
        if self.use_hash_storage:
            raw = await self.redis.hget(self._get_key(user_id, session_id, chatbot_id), "metadata")
            if not raw:
                return None
            meta = self._deserialize_data(raw)
            return meta if isinstance(meta, dict) else None
        history = await self.get_history(user_id, session_id, chatbot_id)
        return dict(history.metadata) if history is not None else None

    async def merge_metadata(
        self,
        user_id: str,
        session_id: str,
        chatbot_id: Optional[str] = None,
        *,
        mutate: Callable[[Dict[str, Any]], Dict[str, Any]],
        ttl: Optional[int] = None,
        max_attempts: int = _MERGE_MAX_ATTEMPTS,
    ) -> Dict[str, Any]:
        """Atomically compare-and-merge a conversation's ``metadata`` (FEAT-538).

        ``metadata`` is shared by writers that know nothing about each
        other: the compaction layer owns ``metadata["compaction"]`` and
        task memory owns ``metadata["task_memory"]``. The previous
        read-modify-write lost whichever update landed second.

        A task-scoped lock cannot fix that, because **the other writer
        would not take it**. So this uses Redis' own
        ``WATCH``/``MULTI``/``EXEC``: the transaction aborts if *anyone*
        touches the key in between, and ``mutate`` is re-run against the
        freshly read value. Correctness therefore does not depend on every
        writer cooperating — only on them going through Redis.

        ``mutate`` must be a **pure** function of the metadata it is
        given: it may be called several times, and it must merge into the
        dict it receives rather than into one captured earlier.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent key segment.
            mutate: Pure function from current metadata to new metadata.
            ttl: Optional expiry in seconds applied to the conversation
                key. Task-memory mode requires an explicit finite hot-key
                retention when the underlying history has no TTL.
            max_attempts: Bound on compare-and-swap retries.

        Returns:
            The metadata that was written.

        Raises:
            RuntimeError: If the merge still conflicts after
                ``max_attempts``. Callers that must not fail a user
                action should treat this as a degraded cache write, not
                as a lost record.
        """
        key = self._get_key(user_id, session_id, chatbot_id)

        if not self._supports_cas():
            return await self._merge_metadata_unguarded(key, mutate, ttl)

        for attempt in range(max_attempts):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    if self.use_hash_storage:
                        raw = await pipe.hget(key, "metadata")
                        current = self._deserialize_data(raw) if raw else {}
                        if not isinstance(current, dict):
                            current = {}
                        merged = mutate(dict(current))
                        pipe.multi()
                        pipe.hset(key, "metadata", self._serialize_data(merged))
                        if ttl:
                            pipe.expire(key, ttl)
                        await pipe.execute()
                    else:
                        raw = await pipe.get(key)
                        payload = self._deserialize_data(raw) if raw else None
                        if not isinstance(payload, dict):
                            payload = {}
                        current = payload.get("metadata")
                        if not isinstance(current, dict):
                            current = {}
                        merged = mutate(dict(current))
                        payload["metadata"] = merged
                        pipe.multi()
                        pipe.set(key, self._serialize_data(payload))
                        if ttl:
                            pipe.expire(key, ttl)
                        await pipe.execute()
                    return merged
                except WatchError:
                    # Somebody else wrote the key between our read and our
                    # write. Re-read and re-merge; do NOT reuse the stale
                    # value, which is exactly how the update was lost.
                    pass
            await _merge_backoff(attempt)

        raise RuntimeError(f"metadata merge for {key} still conflicting after {max_attempts} attempts")

    async def _merge_metadata_unguarded(
        self, key: str, mutate: Callable[[Dict[str, Any]], Dict[str, Any]], ttl: Optional[int]
    ) -> Dict[str, Any]:
        """Merge metadata WITHOUT a compare-and-swap.

        Only used for clients that cannot do transactions. This is the
        pre-FEAT-538 read-modify-write and is **not** protected against a
        concurrent writer; it exists so a non-transactional client keeps
        working rather than crashing.

        Args:
            key: The conversation key.
            mutate: The merge function.
            ttl: Optional expiry in seconds.

        Returns:
            The metadata that was written.
        """
        if self.use_hash_storage:
            raw = await self.redis.hget(key, "metadata")
            current = self._deserialize_data(raw) if raw else {}
            if not isinstance(current, dict):
                current = {}
            merged = mutate(dict(current))
            await self.redis.hset(key, mapping={"metadata": self._serialize_data(merged)})
        else:
            raw = await self.redis.get(key)
            payload = self._deserialize_data(raw) if raw else None
            if not isinstance(payload, dict):
                payload = {}
            current = payload.get("metadata")
            if not isinstance(current, dict):
                current = {}
            merged = mutate(dict(current))
            payload["metadata"] = merged
            await self.redis.set(key, self._serialize_data(payload))
        if ttl:
            expire = getattr(self.redis, "expire", None)
            if callable(expire):
                await expire(key, ttl)
        return merged

    async def _refresh_ttl(self, user_id: str, session_id: str, chatbot_id: Optional[str]) -> None:
        """Re-arm ``history_ttl`` on a history key (no-op when no TTL is configured)."""
        if self.history_ttl:
            await self.redis.expire(self._get_key(user_id, session_id, chatbot_id), self.history_ttl)

    async def _store_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None,
        *,
        compaction_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append ``turn`` (see :meth:`_append_turn`) and refresh the history TTL."""
        await self._append_turn(user_id, session_id, turn, chatbot_id, compaction_state=compaction_state)
        await self._refresh_ttl(user_id, session_id, chatbot_id)

    async def upsert_turn(
        self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None
    ) -> None:
        """Replace the stored turn with the same ``turn_id``, or insert it, in ONE compare-and-swap write.

        Creates the history when absent. Runs the ``add_turn`` normalize / count / offload steps.
        Idempotent: replaying the same turn leaves one copy; the ordering fields of an existing turn
        never change.

        Raises:
            RuntimeError: the CAS still conflicts after ``_MERGE_MAX_ATTEMPTS`` (the caller's bus retries).
        """
        prepared = await self._prepare_turn(user_id, session_id, turn, chatbot_id)
        key = self._get_key(user_id, session_id, chatbot_id)
        new = prepared.to_dict()
        attempts = _MERGE_MAX_ATTEMPTS if self._supports_cas() else 1
        for attempt in range(attempts):
            if self._supports_cas():
                async with self.redis.pipeline() as pipe:
                    try:
                        await pipe.watch(key)
                        await self._write_upserted(pipe, key, user_id, session_id, chatbot_id, new, cas=True)
                    except WatchError:
                        await _merge_backoff(attempt)
                        continue
            else:
                await self._write_upserted(self.redis, key, user_id, session_id, chatbot_id, new, cas=False)
            await self._refresh_ttl(user_id, session_id, chatbot_id)
            await self.redis.sadd(self._get_user_sessions_key(user_id, chatbot_id), session_id)
            return
        raise RuntimeError(f"turn upsert for {key} still conflicting after {_MERGE_MAX_ATTEMPTS} attempts")

    async def _write_upserted(
        self, conn: Any, key: str, user_id: str, session_id: str, chatbot_id: Optional[str],
        new: Dict[str, Any], *, cas: bool,
    ) -> None:
        """Read the stored turns through ``conn``, upsert ``new`` and write once (MULTI/EXEC when ``cas``)."""
        now = datetime.now().isoformat()
        if self.use_hash_storage:
            exists = await conn.exists(key)
            raw = await conn.hget(key, "turns") if exists else None
            turns = self._deserialize_data(raw) if raw else []
            mapping: Dict[str, Any] = {"turns": self._serialize_data(_upsert_turn_dict(turns, new)),
                                       "updated_at": now}
            if chatbot_id is not None:
                mapping["chatbot_id"] = str(chatbot_id)
            if not exists:
                mapping.update({"session_id": str(session_id), "user_id": str(user_id), "created_at": now,
                                "metadata": self._serialize_data({})})
            if cas:
                conn.multi()
                conn.hset(key, mapping=mapping)
                await conn.execute()
            else:
                await conn.hset(key, mapping=mapping)
            return
        raw = await conn.get(key)
        payload = self._deserialize_data(raw) if raw else None
        if isinstance(payload, dict):
            history = ConversationHistory.from_dict(payload)
        else:
            history = ConversationHistory(session_id=session_id, user_id=user_id, chatbot_id=chatbot_id)
        if chatbot_id and not history.chatbot_id:
            history.chatbot_id = chatbot_id
        merged = _upsert_turn_dict([t.to_dict() for t in history.turns], new)
        history.turns = [ConversationTurn.from_dict(t) for t in merged]
        data = self._serialize_data(history.to_dict())
        if cas:
            conn.multi()
            conn.set(key, data)
            await conn.execute()
        else:
            await conn.set(key, data)

    async def remove_turn(self, user_id: str, session_id: str, turn_id: str, chatbot_id: Optional[str] = None) -> bool:
        """Remove the turn ``turn_id`` in ONE compare-and-swap write (``WATCH``/``MULTI``/``EXEC``).

        The base read-modify-write (``get_history`` -> filter -> ``update_history``) overwrote a turn appended
        between its read and its write. Here a concurrent writer aborts the transaction and the filter re-runs
        against the fresh value. Hash mode rewrites only ``turns``/``updated_at``, so a concurrent ``metadata``
        write survives as well. A legacy un-segmented history is re-keyed first (FEAT-524), exactly as
        :meth:`get_history` would, so the turn also leaves the record the bot reads next.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            turn_id: The turn to drop.
            chatbot_id: Agent key segment.

        Returns:
            ``True`` when this call removed the turn; ``False`` when there is no history or it holds no such turn.

        Raises:
            RuntimeError: the CAS still conflicts after ``_MERGE_MAX_ATTEMPTS`` (the deletion cleanup retries).
        """
        key = self._get_key(user_id, session_id, chatbot_id)
        if chatbot_id and not await self.redis.exists(key):
            if await self.get_history(user_id, session_id, chatbot_id) is None:  # FEAT-524 legacy re-key
                return False
        attempts = _MERGE_MAX_ATTEMPTS if self._supports_cas() else 1
        for attempt in range(attempts):
            if self._supports_cas():
                async with self.redis.pipeline() as pipe:
                    try:
                        await pipe.watch(key)
                        removed = await self._write_without_turn(pipe, key, turn_id, cas=True)
                    except WatchError:
                        await _merge_backoff(attempt)
                        continue
            else:
                removed = await self._write_without_turn(self.redis, key, turn_id, cas=False)
            if removed:
                await self._refresh_ttl(user_id, session_id, chatbot_id)
            return removed
        raise RuntimeError(f"turn removal for {key} still conflicting after {_MERGE_MAX_ATTEMPTS} attempts")

    async def _write_without_turn(self, conn: Any, key: str, turn_id: str, *, cas: bool) -> bool:
        """Read the stored turns through ``conn``, drop ``turn_id`` and write once (MULTI/EXEC when ``cas``).

        Args:
            conn: The watching pipeline (``cas``) or the plain client.
            key: The history key.
            turn_id: The turn to drop.
            cas: Whether ``conn`` is a pipeline in ``WATCH`` mode.

        Returns:
            ``True`` when the turn was dropped and written; ``False`` (nothing written) when the key holds no
            such turn.
        """
        payload: Optional[Dict[str, Any]] = None
        if self.use_hash_storage:
            raw = await conn.hget(key, "turns")
            kept = _without_turn(self._deserialize_data(raw) if raw else None, turn_id)
        else:
            raw = await conn.get(key)
            loaded = self._deserialize_data(raw) if raw else None
            payload = loaded if isinstance(loaded, dict) else None
            kept = _without_turn(payload.get("turns") if payload is not None else None, turn_id)
        if kept is None:
            if cas:
                await conn.unwatch()
            return False
        now = datetime.now().isoformat()
        if payload is None:
            mapping = {"turns": self._serialize_data(kept), "updated_at": now}
            if cas:
                conn.multi()
                conn.hset(key, mapping=mapping)
                await conn.execute()
            else:
                await conn.hset(key, mapping=mapping)
            return True
        payload["turns"] = kept
        payload["updated_at"] = now
        data = self._serialize_data(payload)
        if cas:
            conn.multi()
            conn.set(key, data)
            await conn.execute()
        else:
            await conn.set(key, data)
        return True

    async def _append_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None,
        *,
        compaction_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append ``turn`` and, when given, ``metadata['compaction']`` — in ONE write.

        Hash mode issues exactly one ``hset`` whose mapping carries
        ``turns``/``updated_at``[/``chatbot_id``] and, when a compaction
        state is given, ``metadata``.

        FEAT-538: the read-modify-write is now wrapped in
        ``WATCH``/``MULTI``/``EXEC``. Previously a concurrent writer
        touching ``metadata`` (task association) or ``turns`` between this
        method's read and its write was silently overwritten. The visible
        behaviour is unchanged — one write, same fields — but a losing
        writer now retries against fresh data instead of clobbering.
        """
        if self.use_hash_storage:
            key = self._get_key(user_id, session_id, chatbot_id)

            for attempt in range(_MERGE_MAX_ATTEMPTS if self._supports_cas() else 0):
                async with self.redis.pipeline() as pipe:
                    try:
                        await pipe.watch(key)
                        current_turns_data = await pipe.hget(key, "turns")
                        turns = self._deserialize_data(current_turns_data) if current_turns_data else []
                        turns.append(turn.to_dict())

                        mapping: Dict[str, Any] = {
                            "turns": self._serialize_data(turns),
                            "updated_at": datetime.now().isoformat(),
                        }
                        if chatbot_id is not None:
                            mapping["chatbot_id"] = str(chatbot_id)
                        if compaction_state is not None:
                            raw_meta = await pipe.hget(key, "metadata")
                            meta = self._deserialize_data(raw_meta) if raw_meta else {}
                            if not isinstance(meta, dict):
                                meta = {}
                            meta["compaction"] = compaction_state
                            mapping["metadata"] = self._serialize_data(meta)

                        pipe.multi()
                        pipe.hset(key, mapping=mapping)
                        await pipe.execute()
                        return
                    except WatchError:
                        pass
                await _merge_backoff(attempt)

            # Contention did not clear. Fall back to the pre-FEAT-538
            # single write rather than dropping the user's turn: losing a
            # conversation turn is worse than losing a metadata race.
            if self._supports_cas():
                self.logger.warning(
                    "Turn append for %s contended past %d attempts; writing without CAS",
                    key,
                    _MERGE_MAX_ATTEMPTS,
                )
            current_turns_data = await self.redis.hget(key, "turns")
            turns = self._deserialize_data(current_turns_data) if current_turns_data else []
            turns.append(turn.to_dict())
            mapping = {
                "turns": self._serialize_data(turns),
                "updated_at": datetime.now().isoformat(),
            }
            if chatbot_id is not None:
                mapping["chatbot_id"] = str(chatbot_id)
            if compaction_state is not None:
                raw_meta = await self.redis.hget(key, "metadata")
                meta = self._deserialize_data(raw_meta) if raw_meta else {}
                if not isinstance(meta, dict):
                    meta = {}
                meta["compaction"] = compaction_state
                mapping["metadata"] = self._serialize_data(meta)
            await self.redis.hset(key, mapping=mapping)
        else:
            # Full-history mode. The old path was get_history -> mutate ->
            # update_history, which replaces the ENTIRE record and so loses
            # any concurrent metadata write outright. Same CAS treatment.
            key = self._get_key(user_id, session_id, chatbot_id)
            for attempt in range(_MERGE_MAX_ATTEMPTS if self._supports_cas() else 0):
                async with self.redis.pipeline() as pipe:
                    try:
                        await pipe.watch(key)
                        raw = await pipe.get(key)
                        if not raw:
                            break
                        payload = self._deserialize_data(raw)
                        if not isinstance(payload, dict):
                            break
                        history = ConversationHistory.from_dict(payload)
                        if chatbot_id and not history.chatbot_id:
                            history.chatbot_id = chatbot_id
                        history.add_turn(turn)
                        if compaction_state is not None:
                            history.metadata["compaction"] = compaction_state
                        pipe.multi()
                        pipe.set(key, self._serialize_data(history.to_dict()))
                        await pipe.execute()
                        return
                    except WatchError:
                        pass
                await _merge_backoff(attempt)

            history = await self.get_history(user_id, session_id, chatbot_id)
            if history:
                history.add_turn(turn)
                if compaction_state is not None:
                    history.metadata["compaction"] = compaction_state
                await self.update_history(history)

    async def _get_compaction_state(
        self, user_id: str, session_id: str, chatbot_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Read ``metadata['compaction']`` with a single targeted ``hget`` in hash mode.

        Avoids the FEAT-524 lazy legacy re-key that a full
        :meth:`get_history` call may perform as a side effect.
        """
        if not self.use_hash_storage:
            return await super()._get_compaction_state(user_id, session_id, chatbot_id)
        key = self._get_key(user_id, session_id, chatbot_id)
        raw_meta = await self.redis.hget(key, "metadata")
        if not raw_meta:
            return None
        meta = self._deserialize_data(raw_meta)
        if not isinstance(meta, dict):
            return None
        return meta.get("compaction")

    async def clear_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> None:
        """Clear a conversation history."""
        if self.use_hash_storage:
            # Optimized: Only clear turns
            key = self._get_key(user_id, session_id, chatbot_id)
            # Reset turns to empty list and update updated_at
            mapping = {"turns": self._serialize_data([]), "updated_at": datetime.now().isoformat()}
            if chatbot_id is not None:
                mapping["chatbot_id"] = str(chatbot_id)
            await self.redis.hset(key, mapping=mapping)
        else:
            history = await self.get_history(user_id, session_id, chatbot_id)
            if history:
                history.clear_turns()
                await self.update_history(history)
        await self.omission_store.clear(self.omission_key(user_id, session_id, chatbot_id))

    async def list_sessions(self, user_id: str, chatbot_id: Optional[str] = None) -> List[str]:
        """List all session IDs for a user."""
        sessions = await self.redis.smembers(self._get_user_sessions_key(user_id, chatbot_id))
        # Since decode_responses=True, sessions should already be strings
        return list(sessions)

    async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> bool:
        """Delete a conversation history entirely."""
        key = self._get_key(user_id, session_id, chatbot_id)
        result = await self.redis.delete(key)
        await self.redis.srem(self._get_user_sessions_key(user_id, chatbot_id), session_id)
        await self.omission_store.clear(self.omission_key(user_id, session_id, chatbot_id))
        return result > 0

    async def close(self):
        """Close the Redis connection."""
        try:
            await self.redis.close()
        except Exception as e:
            self.logger.error(f"Error closing Redis connection: {e}")

    async def ping(self) -> bool:
        """Test Redis connection."""
        try:
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"Error pinging Redis: {e}")
            return False

    # Additional utility methods for debugging
    async def get_raw_data(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> Optional[Dict]:
        """Get raw data from Redis for debugging."""
        key = self._get_key(user_id, session_id, chatbot_id)

        if self.use_hash_storage:
            return await self.redis.hgetall(key)
        data = await self.redis.get(key)
        return {"raw_data": data} if data else None

    async def debug_conversation(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Debug method to inspect conversation data."""
        raw_data = await self.get_raw_data(user_id, session_id, chatbot_id)
        history = await self.get_history(user_id, session_id, chatbot_id)

        return {
            "raw_data": raw_data,
            "parsed_history": history.to_dict() if history else None,
            "turns_count": len(history.turns) if history else 0,
            "storage_method": "hash" if self.use_hash_storage else "string",
        }

    async def list_sessions_by_chatbot(self, chatbot_id: str, user_id: Optional[str] = None) -> List[str]:
        """List all sessions for a specific chatbot.

        Args:
            chatbot_id: The chatbot identifier
            user_id: Optional user filter

        Returns:
            List of session IDs
        """
        if user_id:
            # Get sessions for specific user and chatbot
            return await self.list_sessions(user_id, chatbot_id)

        # Get all sessions for this chatbot across all users
        pattern = f"{self.key_prefix}:{chatbot_id}:*"
        sessions = []
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                # Extract session_id from key
                # Format: conversation:chatbot_id:user_id:session_id
                parts = key.split(":")
                if len(parts) >= 4:
                    sessions.append(parts[3])

            if cursor == 0:
                break

        return sessions

    async def get_chatbot_stats(self, chatbot_id: str) -> Dict[str, Any]:
        """Get statistics for a specific chatbot.

        Returns:
            Dictionary with conversation counts, active users, etc.
        """
        pattern = f"{self.key_prefix}:{chatbot_id}:*"
        total_conversations = 0
        total_turns = 0
        unique_users = set()
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            total_conversations += len(keys)

            for key in keys:
                # Extract user_id
                parts = key.split(":")
                if len(parts) >= 3:
                    unique_users.add(parts[2])

                # Count turns
                if self.use_hash_storage:
                    turns_data = await self.redis.hget(key, "turns")
                    if turns_data:
                        turns = self._deserialize_data(turns_data)
                        total_turns += len(turns)

            if cursor == 0:
                break

        return {
            "chatbot_id": chatbot_id,
            "total_conversations": total_conversations,
            "total_turns": total_turns,
            "unique_users": len(unique_users),
            "avg_turns_per_conversation": total_turns / total_conversations if total_conversations > 0 else 0,
        }

    async def delete_all_chatbot_conversations(self, chatbot_id: str, user_id: Optional[str] = None) -> int:
        """Delete all conversations for a chatbot.

        Args:
            chatbot_id: The chatbot identifier
            user_id: Optional user filter

        Returns:
            Number of conversations deleted
        """
        if user_id:
            pattern = f"{self.key_prefix}:{chatbot_id}:{user_id}:*"
        else:
            pattern = f"{self.key_prefix}:{chatbot_id}:*"

        deleted_count = 0
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)

            if keys:
                deleted_count += await self.redis.delete(*keys)

            if cursor == 0:
                break

        # Also clean up session sets
        if user_id:
            await self.redis.delete(self._get_user_sessions_key(user_id, chatbot_id))
        else:
            # Clean all user session sets for this chatbot
            session_pattern = f"{self.key_prefix}_sessions:{chatbot_id}:*"
            cursor = 0
            while True:
                cursor, session_keys = await self.redis.scan(cursor, match=session_pattern, count=100)
                if session_keys:
                    await self.redis.delete(*session_keys)
                if cursor == 0:
                    break

        return deleted_count

    async def _update_chatbot_index(
        self, chatbot_id: str, user_id: str, session_id: str, operation: str = "add"
    ) -> None:
        """Maintain reverse index for fast chatbot queries.

        Args:
            chatbot_id: The chatbot identifier
            user_id: The user identifier
            session_id: The session identifier
            operation: 'add' or 'remove'
        """
        # Index: all users who interacted with this chatbot
        users_key = f"{self.key_prefix}_index:chatbot_users:{chatbot_id}"

        if operation == "add":
            await self.redis.sadd(users_key, user_id)
            # Set expiry if needed
            # await self.redis.expire(users_key, 86400 * 30)  # 30 days
        elif operation == "remove":
            # Check if user has any other sessions with this chatbot
            sessions = await self.list_sessions(user_id, chatbot_id)
            if not sessions:
                await self.redis.srem(users_key, user_id)

    async def get_chatbot_users(self, chatbot_id: str) -> List[str]:
        """Get all users who have interacted with a chatbot."""
        users_key = f"{self.key_prefix}_index:chatbot_users:{chatbot_id}"
        users = await self.redis.smembers(users_key)
        return list(users)
