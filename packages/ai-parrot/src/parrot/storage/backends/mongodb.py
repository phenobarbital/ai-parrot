"""MongoDB conversation backend using motor (via asyncdb[mongo]).

Suitable for GCP deployments or teams already running MongoDB / DocumentDB.
Uses native MongoDB TTL indexes on ``expires_at``.

Note: Mongo's TTL reaper runs once per minute. Tests must NOT assert instant
expiry after writing an expired document — the TTL index is for background
cleanup. Use ``delete_thread_cascade`` or ``delete_session_artifacts`` for
deterministic cleanup in tests.

FEAT-116: dynamodb-fallback-redis — Module 6 (MongoDB backend).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from navconfig.logging import logging

from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_US = timedelta(microseconds=1)
_RESERVED = ("_id", "user_id", "agent_id", "session_id", "kind", "sort_key", "turn_id", "ts_utc", "seq")


def _chrono_fields(data: dict) -> Tuple[Optional[int], int]:
    """Return ``(ts_utc_microseconds, sequence)`` from a turn payload (``None`` when unusable).

    Naive timestamps are read as UTC; a bad / negative sequence yields ``0``.
    """
    raw = data.get("timestamp")
    ts: Optional[datetime] = None
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip())
        except ValueError:
            ts = None
    micros: Optional[int] = None
    if ts is not None:
        ts = (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts).astimezone(timezone.utc)
        micros = (ts - _EPOCH) // _ONE_US
        micros = micros if micros >= 0 else None
    seq = data.get("sequence")
    valid_seq = isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0
    return micros, (seq if valid_seq else 0)


class ConversationMongoBackend(ConversationBackend):
    """Async MongoDB implementation of ConversationBackend.

    Uses ``motor`` (the async MongoDB driver) accessed via ``asyncdb[mongo]``.
    Two collections are used:
      - ``conversations``: thread metadata + turns (discriminated by ``kind``).
      - ``artifacts``: artifact items.

    ``replace_one(..., upsert=True)`` is used for all writes to match
    DynamoDB's overwrite-or-create semantics.

    Args:
        dsn: MongoDB connection string, e.g.
            ``"mongodb://user:pw@host:27017/parrot"``.
        database: Database name (default ``"parrot"``).
        default_ttl_days: TTL for new documents in days (default 180).
    """

    DEFAULT_TTL_DAYS = 180

    def __init__(
        self,
        dsn: str,
        database: str = "parrot",
        default_ttl_days: int = 180,
    ) -> None:
        self._dsn = dsn
        self._database = database
        self._default_ttl_days = default_ttl_days
        self._client = None
        self._db = None
        self._conversations = None
        self._artifacts = None
        self._tombstones = None
        self._index_state = None
        self._initialized: bool = False
        self.logger = logging.getLogger("parrot.storage.ConversationMongoBackend")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to MongoDB and create indexes (idempotent)."""
        if self._initialized and self._client is not None:
            return
        import motor.motor_asyncio  # type: ignore[import]

        self._client = motor.motor_asyncio.AsyncIOMotorClient(self._dsn)
        self._db = self._client[self._database]
        self._conversations = self._db["conversations"]
        self._artifacts = self._db["artifacts"]

        # Conversations indexes
        await self._conversations.create_index(
            [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("sort_key", 1)],
            unique=True,
            name="conv_compound_unique",
        )
        await self._conversations.create_index(
            [("user_id", 1), ("agent_id", 1), ("updated_at", -1)],
            name="conv_user_agent_time",
        )
        await self._conversations.create_index(
            [("expires_at", 1)],
            expireAfterSeconds=0,
            name="conv_ttl",
            sparse=True,
        )

        self._tombstones = self._db["conversation_tombstones"]
        self._index_state = self._db["conversation_index_state"]
        await self._conversations.create_index(
            [
                ("user_id", 1),
                ("agent_id", 1),
                ("session_id", 1),
                ("kind", 1),
                ("ts_utc", 1),
                ("seq", 1),
                ("turn_id", 1),
            ],
            name="conv_turn_chrono",
        )
        await self._tombstones.create_index(  # NO TTL: tombstones are kept indefinitely
            [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("turn_id", 1)],
            unique=True,
            name="tomb_unique",
        )
        await self._index_state.create_index(
            [("user_id", 1), ("agent_id", 1), ("session_id", 1)],
            unique=True,
            name="idxstate_unique",
        )

        # Artifacts indexes
        await self._artifacts.create_index(
            [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("artifact_id", 1)],
            unique=True,
            name="art_compound_unique",
        )
        await self._artifacts.create_index(
            [("expires_at", 1)],
            expireAfterSeconds=0,
            name="art_ttl",
            sparse=True,
        )

        self._initialized = True
        self.logger.info("MongoDB backend initialized (db=%s)", self._database)

    async def close(self) -> None:
        """Close the MongoDB client.

        Note: motor's ``AsyncIOMotorClient.close()`` is synchronous — no
        ``await`` needed. This is intentional and correct, but looks
        surprising inside an ``async def``.
        """
        if self._client is not None:
            try:
                self._client.close()  # synchronous — motor's design
            except Exception as exc:
                self.logger.warning("Error closing MongoDB client: %s", exc)
            finally:
                self._client = None
                self._conversations = None
                self._artifacts = None
                self._tombstones = None
                self._index_state = None
                self._initialized = False

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._initialized

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _expires_at(self) -> Optional[datetime]:
        if self._default_ttl_days <= 0:
            return datetime.now(timezone.utc)
        return datetime.now(timezone.utc) + timedelta(days=self._default_ttl_days)

    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("MongoDB conversation backend is not connected")

    @staticmethod
    def _translate(exc: BaseException, *, write: bool) -> StorageError:
        """Map a driver/transport exception to the typed storage error (never swallow)."""
        from pymongo import errors as mongo_errors  # lazy: optional dependency

        transport = (mongo_errors.ConnectionFailure, mongo_errors.InvalidOperation, OSError, asyncio.TimeoutError)
        if isinstance(exc, transport):
            return StorageUnavailableError(f"MongoDB unavailable: {exc}")
        cls = StorageWriteError if write else StorageUnavailableError
        return cls(f"MongoDB operation failed: {exc}")

    async def _is_tombstoned(self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None) -> bool:
        """Session tombstone, or (when ``turn_id`` is given) session OR turn tombstone."""
        found = await self._tombstones.find_one(
            {
                "user_id": user_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "turn_id": {"$in": ["", turn_id or ""]},
            },
            projection={"_id": 1},
        )
        return found is not None

    async def _build_turn_doc(self, key: Dict[str, Any], turn_id: str, data: dict) -> dict:
        """Document to write: payload spread at top level, fixed keys last, ordering kept if already set."""
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items() if k not in _RESERVED}
        ts_us, seq = _chrono_fields(data)
        existing = await self._conversations.find_one(
            key, projection={"ts_utc": 1, "seq": 1, "timestamp": 1, "sequence": 1}
        )
        if existing is not None and existing.get("ts_utc") is not None:
            ts_us, seq = existing["ts_utc"], existing.get("seq", 0)
            for name in ("timestamp", "sequence"):  # immutable once set
                if name in existing:
                    payload[name] = existing[name]
                else:
                    payload.pop(name, None)
        return {
            **payload,
            **key,
            "kind": "turn",
            "turn_id": turn_id,
            "updated_at": datetime.now(timezone.utc),
            "expires_at": self._expires_at(),
            "ts_utc": ts_us,
            "seq": seq,
        }

    def _clean(self, doc: dict) -> dict:
        """Strip internal Mongo fields and normalize datetimes."""
        doc.pop("_id", None)
        doc.pop("ts_utc", None)
        doc.pop("seq", None)
        for k in ("updated_at", "expires_at"):
            if k in doc and isinstance(doc[k], datetime):
                doc[k] = doc[k].isoformat()
        return doc

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    async def put_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        metadata: dict,
    ) -> None:
        if not self.is_connected:
            return
        now = datetime.now(timezone.utc)
        payload = {}
        for k, v in metadata.items():
            payload[k] = v.isoformat() if isinstance(v, datetime) else v
        doc = {
            "user_id": user_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "kind": "thread",
            "sort_key": "THREAD",
            "updated_at": now,
            "expires_at": self._expires_at(),
            **payload,
        }
        await self._conversations.replace_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "sort_key": "THREAD"},
            doc,
            upsert=True,
        )

    async def update_thread(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        **updates,
    ) -> None:
        if not self.is_connected or not updates:
            return
        existing = await self._conversations.find_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "sort_key": "THREAD"},
        )
        if existing is None:
            await self.put_thread(user_id, agent_id, session_id, updates)
            return
        for k, v in updates.items():
            existing[k] = v.isoformat() if isinstance(v, datetime) else v
        existing["updated_at"] = datetime.now(timezone.utc)
        existing["expires_at"] = self._expires_at()
        await self._conversations.replace_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "sort_key": "THREAD"},
            existing,
            upsert=True,
        )

    async def query_threads(
        self,
        user_id: str,
        agent_id: str,
        limit: int = 50,
    ) -> List[dict]:
        if not self.is_connected:
            return []
        cursor = (
            self._conversations.find(
                {"user_id": user_id, "agent_id": agent_id, "kind": "thread"},
            )
            .sort("updated_at", -1)
            .limit(limit)
        )
        # Fix #8: always use the return value of _clean() for consistency
        result = []
        async for doc in cursor:
            result.append(self._clean(doc))
        return result

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id`` fenced by a tombstone check before AND after the write.

        Guarded two-phase write (valid on standalone ``mongod`` too): check the tombstone, upsert,
        re-check; a tombstone that landed in between deletes the document just written.

        Raises:
            StorageUnavailableError: not connected / transport failure.
            ConversationDeletedError: the session or this turn is tombstoned.
            StorageWriteError: the write failed (nothing is swallowed).
        """
        self._require_connection()
        key = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "sort_key": f"TURN#{turn_id}"}
        try:
            if await self._is_tombstoned(user_id, agent_id, session_id, turn_id):
                raise ConversationDeletedError(f"session {session_id} or turn {turn_id} is tombstoned; write rejected")
            doc = await self._build_turn_doc(key, turn_id, data)
            await self._conversations.replace_one(key, doc, upsert=True)
            if await self._is_tombstoned(user_id, agent_id, session_id, turn_id):  # phase 3: lost the race
                await self._conversations.delete_one(key)
                raise ConversationDeletedError(
                    f"session {session_id} or turn {turn_id} was tombstoned during the write; rolled back"
                )
        except StorageError:
            raise
        except Exception as exc:
            raise self._translate(exc, write=True) from exc

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        self._require_connection()
        sort_dir = -1 if newest_first else 1
        try:
            cursor = (
                self._conversations.find(
                    {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "kind": "turn"},
                )
                .sort("sort_key", sort_dir)
                .limit(limit)
            )
            result = []
            async for doc in cursor:
                self._clean(doc)
                result.append(doc)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return result

    async def delete_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
    ) -> bool:
        if not self.is_connected:
            return False
        sort_key = f"TURN#{turn_id}"
        result = await self._conversations.delete_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "sort_key": sort_key},
        )
        return result.deleted_count > 0

    async def delete_thread_cascade(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        if not self.is_connected:
            return 0
        r1 = await self._conversations.delete_many(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id},
        )
        r2 = await self._artifacts.delete_many(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id},
        )
        return r1.deleted_count + r2.deleted_count

    # ------------------------------------------------------------------
    # FEAT-886: ordered window, tombstones, index state, backfill
    # ------------------------------------------------------------------

    async def query_turn_window(self, user_id: str, agent_id: str, session_id: str, limit: int) -> List[dict]:
        """Newest ``limit`` turns by (ts_utc, seq, turn_id), limit applied descending, returned ascending."""
        self._require_connection()
        if await self.is_deleted(user_id, agent_id, session_id):
            raise ConversationDeletedError(f"session {session_id} is tombstoned")
        if await self.get_index_state(user_id, agent_id, session_id) != "ready":
            raise IndexNotReadyError(f"chronological index of session {session_id} is not ready")
        if limit <= 0:
            return []
        scope = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id}
        try:
            gone = [
                d["turn_id"]
                async for d in self._tombstones.find({**scope, "turn_id": {"$ne": ""}}, projection={"turn_id": 1})
            ]
            cursor = (
                self._conversations.find({**scope, "kind": "turn", "ts_utc": {"$ne": None}, "turn_id": {"$nin": gone}})
                .sort([("ts_utc", -1), ("seq", -1), ("turn_id", -1)])
                .hint("conv_turn_chrono")
                .limit(limit)
            )
            window = [self._clean(doc) async for doc in cursor]
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        window.reverse()
        return window

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence for the session, ``0`` when none (durable maximum)."""
        self._require_connection()
        pipeline = [
            {"$match": {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "kind": "turn"}},
            {"$group": {"_id": None, "m": {"$max": "$seq"}}},
        ]
        try:
            rows = await self._conversations.aggregate(pipeline).to_list(length=1)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return int(rows[0]["m"]) if rows and rows[0].get("m") is not None else 0

    async def put_tombstone(self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; no TTL."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        try:
            await self._tombstones.update_one(
                {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "turn_id": turn_id or ""},
                {"$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as exc:
            raise self._translate(exc, write=True) from exc

    async def deleted_turn_ids(self, user_id: str, agent_id: str, session_id: str) -> Set[str]:
        """Every turn-scoped tombstone of the session in one query."""
        self._require_connection()
        try:
            return {
                d["turn_id"]
                async for d in self._tombstones.find(
                    {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "turn_id": {"$ne": ""}},
                    projection={"turn_id": 1},
                )
            }
        except Exception as exc:
            raise self._translate(exc, write=False) from exc

    async def deleted_session_ids(self, user_id: str, agent_id: str, session_ids: Sequence[str]) -> Set[str]:
        """The session-tombstoned members of ``session_ids``: one ``$in`` query per 1000 ids."""
        self._require_connection()
        wanted = list(dict.fromkeys(session_ids))
        gone: Set[str] = set()
        try:
            for start in range(0, len(wanted), 1000):
                query = {
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "turn_id": "",
                    "session_id": {"$in": wanted[start : start + 1000]},
                }
                gone.update([d["session_id"] async for d in self._tombstones.find(query, projection={"session_id": 1})])
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return gone

    async def is_deleted(self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined."""
        self._require_connection()
        try:
            return await self._is_tombstoned(user_id, agent_id, session_id, turn_id)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'``.

        Derived: ``ready`` iff the session has no turn document with ``ts_utc: None``; the state
        collection only distinguishes ``invalid`` from ``pending``.
        """
        self._require_connection()
        scope = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id}
        try:
            unindexed = await self._conversations.find_one(
                {**scope, "kind": "turn", "ts_utc": None}, projection={"_id": 1}
            )
            if unindexed is None:
                return "ready"
            state = await self._index_state.find_one(scope, projection={"state": 1})
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return "invalid" if state is not None and state.get("state") == "invalid" else "pending"

    async def _finalize_session(self, scope: Dict[str, str], saw_invalid: bool) -> None:
        """Write ``invalid`` / ``ready`` for a session touched by a batch (otherwise leave it pending)."""
        if saw_invalid:
            state = "invalid"
        elif (
            await self._conversations.find_one({**scope, "kind": "turn", "ts_utc": None}, projection={"_id": 1}) is None
        ):
            state = "ready"
        else:
            return
        await self._index_state.update_one(
            scope, {"$set": {"state": state, "updated_at": datetime.now(timezone.utc)}}, upsert=True
        )

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor`` (resumable, safe next to new writes).

        ``invalid_sessions`` entries are formatted ``"<user_id>/<agent_id>/<session_id>"``; the cursor is
        the ``str(ObjectId)`` of the last examined document.
        """
        from bson import ObjectId  # lazy: ships with pymongo

        self._require_connection()
        query: Dict[str, Any] = {"kind": "turn", "ts_utc": None}
        if cursor is not None:
            query["_id"] = {"$gt": ObjectId(cursor)}
        touched: Dict[Tuple[str, str, str], bool] = {}
        skipped: Dict[Tuple[str, str, str], bool] = {}
        indexed_count = 0
        try:
            docs = [d async for d in self._conversations.find(query).sort("_id", 1).limit(batch_size)]
            for doc in docs:
                key = (doc["user_id"], doc["agent_id"], doc["session_id"])
                if key not in skipped:
                    skipped[key] = await self._is_tombstoned(*key)
                if skipped[key] or await self._is_tombstoned(*key, doc.get("turn_id")):
                    continue  # tombstoned sessions / turns are never indexed
                ts_us, seq = _chrono_fields(doc)
                if ts_us is None:
                    touched[key] = True
                    continue
                result = await self._conversations.update_one(
                    {"_id": doc["_id"], "ts_utc": None}, {"$set": {"ts_utc": ts_us, "seq": seq}}
                )
                indexed_count += result.modified_count
                touched.setdefault(key, False)
            for key, saw_invalid in touched.items():
                scope = dict(zip(("user_id", "agent_id", "session_id"), key, strict=False))
                await self._finalize_session(scope, saw_invalid)
        except Exception as exc:
            raise self._translate(exc, write=True) from exc
        invalid = tuple("/".join(k) for k, bad in touched.items() if bad)
        next_cursor = str(docs[-1]["_id"]) if docs and len(docs) == batch_size else None
        return BackfillBatch(processed=indexed_count, next_cursor=next_cursor, invalid_sessions=invalid)

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    async def put_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
        data: dict,
    ) -> None:
        if not self.is_connected:
            return
        now = datetime.now(timezone.utc)
        payload = {}
        for k, v in data.items():
            payload[k] = v.isoformat() if isinstance(v, datetime) else v
        doc = {
            "user_id": user_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "artifact_id": artifact_id,
            "updated_at": now,
            "expires_at": self._expires_at(),
            **payload,
        }
        await self._artifacts.replace_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "artifact_id": artifact_id},
            doc,
            upsert=True,
        )

    async def get_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> Optional[dict]:
        if not self.is_connected:
            return None
        doc = await self._artifacts.find_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "artifact_id": artifact_id},
        )
        if doc is None:
            return None
        return self._clean(doc)

    async def query_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> List[dict]:
        if not self.is_connected:
            return []
        cursor = self._artifacts.find(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id},
        ).sort("updated_at", -1)
        result = []
        async for doc in cursor:
            result.append(self._clean(doc))
        return result

    async def delete_artifact(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        artifact_id: str,
    ) -> None:
        if not self.is_connected:
            return
        await self._artifacts.delete_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "artifact_id": artifact_id},
        )

    async def delete_session_artifacts(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> int:
        if not self.is_connected:
            return 0
        result = await self._artifacts.delete_many(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id},
        )
        return result.deleted_count

    async def sweep_expired(self) -> int:
        """No-op for Mongo: TTL indexes handle expiry automatically."""
        return 0
