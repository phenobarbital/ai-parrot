"""Redis snapshot store for resumable audio form sessions (FEAT-649, Module 7)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

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


class ActiveHolder(BaseModel):
    """Who holds a user's active-session slot (value of ``parrot:audio:active:{user_id}``).

    ``form_uid`` / ``tenant`` are None only for a legacy bare-string marker.
    """

    session_id: str
    form_uid: str | None = None
    tenant: str | None = None


def _parse_holder(raw: str | None) -> ActiveHolder | None:
    """JSON holder → ActiveHolder; a legacy bare session id → ActiveHolder(session_id=raw); None/'' → None."""
    if not raw:
        return None
    if raw.lstrip().startswith("{"):
        try:
            return ActiveHolder.model_validate_json(raw)
        except ValidationError:
            return None
    return ActiveHolder(session_id=raw)


class AudioSessionStore:
    """Snapshots under ``parrot:audio:{form_uid}:{session_id}`` reusing the partial store's Redis client."""

    def __init__(
        self, partial_store: PartialSaveStore, *, resume_ttl_seconds: int = 3600, active_ttl_seconds: int = 600
    ) -> None:
        """``resume_ttl_seconds``: snapshot TTL when the snapshot has no config; ``active_ttl_seconds``: marker TTL."""
        self.partial_store = partial_store
        self.resume_ttl_seconds = resume_ttl_seconds
        self.active_ttl_seconds = active_ttl_seconds
        self.logger = logging.getLogger(__name__)

    def _resume_ttl(self, snapshot: AudioSnapshot) -> int:
        """``snapshot.config.resume_ttl_seconds`` when a config is present, else the store default."""
        return snapshot.config.resume_ttl_seconds if snapshot.config is not None else self.resume_ttl_seconds

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
        ttl = self._resume_ttl(snapshot)
        try:
            for _ in range(_MAX_CAS_RETRIES):
                raw = _text(await redis.get(key))
                stored = AudioSnapshot.model_validate_json(raw).revision if raw else 0
                if expected_revision is not None and stored != expected_revision:
                    raise SnapshotConflict(f"expected revision {expected_revision}, stored {stored}")
                now = datetime.now(tz=timezone.utc)
                new = snapshot.model_copy(
                    update={
                        "revision": stored + 1,
                        "saved_at": now,
                        "expires_at": now + timedelta(seconds=ttl),
                    }
                )
                ok = await redis.eval(_CAS_SCRIPT, 1, key, raw or "", new.model_dump_json(), ttl)
                if ok:
                    await self._refresh_active(redis, snapshot.user_id, session_id)
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
        holder = _parse_holder(_text(await redis.get(akey)))
        if holder is not None and holder.session_id == session_id:
            await redis.delete(akey)

    async def _refresh_active(self, redis: Any, user_id: str, session_id: str) -> None:
        """Re-set the marker with EX ``active_ttl_seconds`` only when held by ``session_id``; best effort."""
        key = self._active_key(user_id)
        try:
            raw = _text(await redis.get(key))
            holder = _parse_holder(raw)
            if raw is not None and holder is not None and holder.session_id == session_id:
                await redis.set(key, raw, ex=self.active_ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore._refresh_active failed: %s", exc)

    async def release_active(self, user_id: str, session_id: str) -> None:
        """Release the active marker only (the snapshot stays resumable); best effort."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            return
        try:
            await self._release(redis, user_id, session_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.release_active failed: %s", exc)

    async def claim_active(self, user_id: str, session_id: str, *, form_uid: str, tenant: str | None) -> bool:
        """SET NX the holder JSON with EX ``active_ttl_seconds``; the same session re-claims (and rewrites) it.

        Returns False when another session holds the slot. Without Redis it cannot enforce → True.
        """
        redis = await self.partial_store._get_redis()
        if redis is None:
            return True  # no Redis → cannot enforce; resume is unavailable anyway
        key = self._active_key(user_id)
        value = ActiveHolder(session_id=session_id, form_uid=form_uid, tenant=tenant).model_dump_json()
        try:
            if await redis.set(key, value, nx=True, ex=self.active_ttl_seconds):
                return True
            holder = _parse_holder(_text(await redis.get(key)))
            if holder is not None and holder.session_id == session_id:
                await redis.set(key, value, ex=self.active_ttl_seconds)
                return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.claim_active failed: %s", exc)
            return True
        return False

    async def active_holder(self, user_id: str) -> ActiveHolder | None:
        """Current holder of the user's slot; None without Redis, when absent, or on a Redis error."""
        redis = await self.partial_store._get_redis()
        if redis is None:
            return None
        try:
            return _parse_holder(_text(await redis.get(self._active_key(user_id))))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("AudioSessionStore.active_holder failed: %s", exc)
            return None
