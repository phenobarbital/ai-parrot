"""MongoDB conversation backend using motor (via asyncdb[mongo]).

Suitable for GCP deployments or teams already running MongoDB / DocumentDB.
Uses native MongoDB TTL indexes on ``expires_at``.

Note: Mongo's TTL reaper runs once per minute. Tests must NOT assert instant
expiry after writing an expired document — the TTL index is for background
cleanup. Use ``delete_thread_cascade`` or ``delete_session_artifacts`` for
deterministic cleanup in tests.

FEAT-116: dynamodb-fallback-redis — Module 6 (MongoDB backend).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from navconfig.logging import logging

from parrot.storage.backends.base import ConversationBackend


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

    def _clean(self, doc: dict) -> dict:
        """Strip internal Mongo fields and normalize datetimes."""
        doc.pop("_id", None)
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
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "sort_key": "THREAD"},
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
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "sort_key": "THREAD"},
        )
        if existing is None:
            await self.put_thread(user_id, agent_id, session_id, updates)
            return
        for k, v in updates.items():
            existing[k] = v.isoformat() if isinstance(v, datetime) else v
        existing["updated_at"] = datetime.now(timezone.utc)
        existing["expires_at"] = self._expires_at()
        await self._conversations.replace_one(
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "sort_key": "THREAD"},
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
        cursor = self._conversations.find(
            {"user_id": user_id, "agent_id": agent_id, "kind": "thread"},
        ).sort("updated_at", -1).limit(limit)
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
        if not self.is_connected:
            return
        now = datetime.now(timezone.utc)
        payload = {}
        for k, v in data.items():
            payload[k] = v.isoformat() if isinstance(v, datetime) else v
        sort_key = f"TURN#{turn_id}"
        doc = {
            "user_id": user_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "kind": "turn",
            "sort_key": sort_key,
            "turn_id": turn_id,
            "updated_at": now,
            "expires_at": self._expires_at(),
            **payload,
        }
        await self._conversations.replace_one(
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "sort_key": sort_key},
            doc,
            upsert=True,
        )

    async def query_turns(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 10,
        newest_first: bool = True,
    ) -> List[dict]:
        if not self.is_connected:
            return []
        sort_dir = -1 if newest_first else 1
        cursor = self._conversations.find(
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "kind": "turn"},
        ).sort("sort_key", sort_dir).limit(limit)
        result = []
        async for doc in cursor:
            self._clean(doc)
            result.append(doc)
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
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "sort_key": sort_key},
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
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "artifact_id": artifact_id},
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
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "artifact_id": artifact_id},
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
            {"user_id": user_id, "agent_id": agent_id,
             "session_id": session_id, "artifact_id": artifact_id},
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
