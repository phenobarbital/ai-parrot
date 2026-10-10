"""Redis snapshot store for resumable audio form sessions (FEAT-649, Module 7)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from ..core.llm_validation import PlausibilityReport
from ..core.voice import VoiceFormConfig
from ..services.partial_saves import PartialSaveStore
from .models import Phase

AUDIO_KEY_PREFIX = "parrot:audio:"

# Compare-and-set on the raw stored value: write ARGV[2] (EX ARGV[3]) only if the
# current value equals ARGV[1] ("" means the key must be absent).
_CAS_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
if not cur then cur = '' end
if cur == ARGV[1] then
  redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
  return 1
end
return 0
"""
_MAX_CAS_RETRIES = 5


class SnapshotConflict(Exception):
    """Stored revision differs from ``expected_revision`` (S5 compare-and-set)."""


class ResumeUnavailable(Exception):
    """Redis is not configured — resume cannot work (wire code RESUME_UNAVAILABLE)."""


class AudioSnapshot(BaseModel):
    """Private audio-engine snapshot; never exposed through /partial."""

    revision: int = 0
    form_version: str
    phase: Phase
    cursor: str | None = None
    history: list[str] = Field(default_factory=list)
    review_cursor: int = 0
    return_to_review: bool = False
    locale: str = "en"
    config: VoiceFormConfig | None = None
    blob_refs: dict[str, str] = Field(default_factory=dict)  # field_id → blob_ref
    answer_meta: dict[str, dict[str, Any]] = Field(default_factory=dict)  # field_id → evidence
    plausibility: PlausibilityReport | None = None  # discarded on resume (re-run at review)
    flagged: dict[str, int] = Field(default_factory=dict)
    submission_id: str
    user_id: str
    tenant: str | None = None
    saved_at: datetime | None = None
    expires_at: datetime | None = None


def _text(value: Any) -> str | None:
    """Decode a Redis reply (bytes or str) to str."""
    if value is None:
        return None
    return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)


class AudioSessionStore:
    """Snapshots under ``parrot:audio:{form_uid}:{session_id}`` reusing the partial store's Redis client."""

    def __init__(self, partial_store: PartialSaveStore, *, ttl_seconds: int) -> None:
        self.partial_store = partial_store
        self.ttl_seconds = ttl_seconds
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(form_uid: str, session_id: str) -> str:
        return f"{AUDIO_KEY_PREFIX}{form_uid}:{session_id}"

    @staticmethod
    def _active_key(user_id: str) -> str:
        return f"{AUDIO_KEY_PREFIX}active:{user_id}"

    async def save(
        self,
        form_uid: str,
        session_id: str,
        snapshot: AudioSnapshot,
        *,
        expected_revision: int | None = None,
    ) -> int:
        """Compare-and-set on ``revision``; returns the new revision; no-op without Redis.

        Atomicity: the write is a Lua ``EVAL`` that only SETs when the stored raw value
        still equals the value read just before; on a lost race it re-reads and retries.
        """
        redis = await self.partial_store._get_redis()
        if redis is None:
            return snapshot.revision
        key = self._key(form_uid, session_id)
        try:
            for _ in range(_MAX_CAS_RETRIES):
                raw = _text(await redis.get(key))
                stored = AudioSnapshot.model_validate_json(raw).revision if raw else 0
                if expected_revision is not None and stored != expected_revision:
                    raise SnapshotConflict(
                        f"expected revision {expected_revision}, stored {stored}"
                    )
                now = datetime.now(tz=timezone.utc)
                new = snapshot.model_copy(
                    update={
                        "revision": stored + 1,
                        "saved_at": now,
                        "expires_at": now + timedelta(seconds=self.ttl_seconds),
                    }
                )
                ok = await redis.eval(
                    _CAS_SCRIPT, 1, key, raw or "", new.model_dump_json(), self.ttl_seconds
                )
                if ok:
                    return new.revision
            raise SnapshotConflict("snapshot changed concurrently")
        except SnapshotConflict:
            raise
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.save failed: %s", exc)
            return snapshot.revision

    async def load(self, form_uid: str, session_id: str) -> AudioSnapshot | None:
        """Return the snapshot, None when absent; raises ResumeUnavailable without Redis."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            raise ResumeUnavailable("audio session resume requires Redis")
        try:
            raw = await redis.get(self._key(form_uid, session_id))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.load failed: %s", exc)
            return None
        return AudioSnapshot.model_validate_json(raw) if raw else None

    async def delete(self, form_uid: str, session_id: str, *, user_id: str | None = None) -> None:
        """Delete the snapshot and release the active marker held by this session.

        ``user_id`` is the connection's known user: it releases the marker even when no snapshot was ever
        saved (a session ended before its first answer would otherwise block the user until the TTL).
        """
        redis = await self.partial_store._get_redis()
        if redis is None:
            return
        try:
            snap = await self.load(form_uid, session_id)
            await redis.delete(self._key(form_uid, session_id))
            owner = snap.user_id if snap is not None else user_id
            if owner is not None:
                await self._release(redis, owner, session_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.delete failed: %s", exc)

    async def _release(self, redis: Any, user_id: str, session_id: str) -> None:
        """Delete the user's active marker when it is held by ``session_id``."""
        akey = self._active_key(user_id)
        if _text(await redis.get(akey)) == session_id:
            await redis.delete(akey)

    async def release_active(self, user_id: str, session_id: str) -> None:
        """Release the active marker only (the snapshot stays resumable); best effort."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            return
        try:
            await self._release(redis, user_id, session_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.release_active failed: %s", exc)

    async def claim_active(self, user_id: str, session_id: str) -> bool:
        """SET NX ``parrot:audio:active:{user_id}``; False when another session is active."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            return True  # no Redis → cannot enforce; resume is unavailable anyway
        key = self._active_key(user_id)
        try:
            if await redis.set(key, session_id, nx=True, ex=self.ttl_seconds):
                return True
            if _text(await redis.get(key)) == session_id:
                await redis.set(key, session_id, ex=self.ttl_seconds)
                return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.claim_active failed: %s", exc)
            return True
        return False
