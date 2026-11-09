"""Redis-backed persistence layer for Job objects.

Stores job state in Redis so that video-generation (and other background) jobs
survive server restarts and can be queried from any process.

Key schema
----------
Jobs are stored as Redis hashes under the key::

    {prefix}:{job_id}

An additional sorted-set keeps track of all known job IDs so that
``list_jobs()`` does not need to do a full key scan::

    {prefix}:_index   score=created_at_timestamp  member=job_id

TTL is applied to individual job hashes after they reach a terminal state
(completed, failed, cancelled).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from navconfig.logging import logging

from .models import Job, JobStatus


def _now_ts() -> float:
    """Return current UTC timestamp as float."""
    return datetime.now(timezone.utc).timestamp()


def _serialize_job(job: Job) -> Dict[str, str]:
    """Serialize a Job to a flat dict of strings suitable for Redis HSET."""
    result: dict = job.to_dict()
    # to_dict already serialises dates to isoformat strings and
    # enums to their .value; we need to further flatten nested structures.
    flat: Dict[str, str] = {}
    for k, v in result.items():
        if v is None:
            flat[k] = ""
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, default=str)
        else:
            flat[k] = str(v)
    return flat


def _deserialize_job(data: Dict[str, str]) -> Optional[Job]:
    """Reconstruct a Job from the flat Redis hash dict."""
    if not data:
        return None

    def _parse_dt(val: str) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            return None

    def _parse_json(val: str) -> Any:
        if not val:
            return {}
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return {}

    try:
        status_raw = data.get("status", JobStatus.PENDING.value)
        try:
            status = JobStatus(status_raw)
        except ValueError:
            status = JobStatus.PENDING

        # query can be a JSON-encoded dict or a plain string
        query_raw = data.get("query", "")
        try:
            query: Any = json.loads(query_raw)
        except (json.JSONDecodeError, TypeError):
            query = query_raw

        # result can be a JSON-encoded dict/list or None
        result_raw = data.get("result", "")
        result: Any = None
        if result_raw:
            try:
                result = json.loads(result_raw)
            except (json.JSONDecodeError, TypeError):
                result = result_raw

        job = Job(
            job_id=data.get("job_id", ""),
            obj_id=data.get("obj_id", ""),
            query=query,
            status=status,
            result=result,
            error=data.get("error") or None,
            created_at=_parse_dt(data.get("created_at", "")) or datetime.now(timezone.utc),
            started_at=_parse_dt(data.get("started_at", "")),
            completed_at=_parse_dt(data.get("completed_at", "")),
            user_id=data.get("user_id") or None,
            session_id=data.get("session_id") or None,
            execution_mode=data.get("execution_mode") or None,
            metadata=_parse_json(data.get("metadata", "")),
        )
        return job
    except Exception as exc:  # pylint: disable=broad-except
        logging.getLogger("Parrot.RedisJobStore").error(
            "Failed to deserialize job: %s | data=%s", exc, data
        )
        return None


class RedisJobStore:
    """Async Redis-backed store for background Job objects.

    Args:
        redis_url: Redis connection URL. Defaults to ``REDIS_SERVICES_URL``
                   from ``parrot.conf``.
        key_prefix: Prefix for all Redis keys managed by this store.
        job_ttl: Seconds to keep a terminal job in Redis (default 24 h).
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        key_prefix: str = "parrot:jobs",
        job_ttl: int = 86400,
    ) -> None:
        if redis_url is None:
            try:
                from parrot.conf import REDIS_SERVICES_URL  # pylint: disable=import-outside-toplevel
                redis_url = REDIS_SERVICES_URL
            except ImportError:
                redis_url = "redis://localhost:6379/4"

        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._job_ttl = job_ttl
        self._redis: Any = None
        self._connect_lock = asyncio.Lock()
        self.logger = logging.getLogger("Parrot.RedisJobStore")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the Redis connection (idempotent, concurrency-safe)."""
        async with self._connect_lock:
            if self._redis is not None:
                return
            from redis.asyncio import Redis  # pylint: disable=import-outside-toplevel

            self._redis = Redis.from_url(
                self._redis_url,
                decode_responses=True,
                encoding="utf-8",
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            self.logger.debug("RedisJobStore connected to %s", self._redis_url)

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # pylint: disable=broad-except
                pass
            finally:
                self._redis = None

    async def ping(self) -> bool:
        """Return True if the Redis connection is alive."""
        try:
            await self._ensure_connected()
            return await self._redis.ping()
        except Exception:  # pylint: disable=broad-except
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_connected(self) -> None:
        """Connect lazily on first use."""
        if self._redis is None:
            await self.connect()

    def _job_key(self, job_id: str) -> str:
        return f"{self._key_prefix}:{job_id}"

    @property
    def _index_key(self) -> str:
        return f"{self._key_prefix}:_index"

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    async def save(self, job: Job) -> None:
        """Persist a Job to Redis.

        Creates or overwrites the hash for ``job.job_id`` and updates the
        sorted-set index.  Terminal jobs receive a TTL.

        Args:
            job: The Job instance to persist.
        """
        await self._ensure_connected()
        key = self._job_key(job.job_id)
        flat = _serialize_job(job)
        await self._redis.hset(key, mapping=flat)

        # Track in sorted set (score = created_at epoch)
        try:
            score = job.created_at.timestamp()
        except AttributeError:
            score = _now_ts()
        await self._redis.zadd(self._index_key, {job.job_id: score})

        # Apply TTL for terminal states
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            await self._redis.expire(key, self._job_ttl)

    async def get(self, job_id: str) -> Optional[Job]:
        """Return the Job for ``job_id``, or ``None`` if not found.

        Args:
            job_id: The identifier of the job to retrieve.

        Returns:
            Deserialized Job or None.
        """
        await self._ensure_connected()
        data = await self._redis.hgetall(self._job_key(job_id))
        return _deserialize_job(data) if data else None

    async def delete(self, job_id: str) -> bool:
        """Remove a job from Redis.

        Args:
            job_id: The identifier of the job to delete.

        Returns:
            True if the job existed and was deleted.
        """
        await self._ensure_connected()
        deleted = await self._redis.delete(self._job_key(job_id))
        await self._redis.zrem(self._index_key, job_id)
        return bool(deleted)

    async def list_jobs(
        self,
        obj_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
    ) -> List[Job]:
        """Return jobs from Redis, optionally filtered.

        Retrieves the most-recently-created ``limit`` jobs and applies
        optional in-memory filtering.  For large stores you should add
        a secondary index; for typical video-generation workloads this
        is sufficient.

        Args:
            obj_id: Filter by job object ID.
            status: Filter by job status.
            limit: Maximum number of jobs to return (newest first).

        Returns:
            List of Job objects sorted by created_at descending.
        """
        await self._ensure_connected()
        # Get newest IDs from the sorted set (ZREVRANGE = highest score first)
        fetch_count = limit * 2
        job_ids = await self._redis.zrevrange(self._index_key, 0, fetch_count - 1)

        if not job_ids:
            return []

        # Batch fetch all job hashes via pipeline (avoids N+1 round-trips)
        pipe = self._redis.pipeline()
        for jid in job_ids:
            pipe.hgetall(self._job_key(jid))
        results = await pipe.execute()

        expired_ids: list[str] = []
        jobs: List[Job] = []
        for jid, data in zip(job_ids, results):
            if not data:
                expired_ids.append(jid)
                continue
            job = _deserialize_job(data)
            if job is None:
                expired_ids.append(jid)
                continue
            if obj_id and job.obj_id != obj_id:
                continue
            if status and job.status != status:
                continue
            jobs.append(job)
            if len(jobs) >= limit:
                break

        # Clean stale index entries
        if expired_ids:
            await self._redis.zrem(self._index_key, *expired_ids)

        return jobs

    async def exists(self, job_id: str) -> bool:
        """Return True if a job with ``job_id`` is currently stored.

        Args:
            job_id: The identifier to check.
        """
        await self._ensure_connected()
        return bool(await self._redis.exists(self._job_key(job_id)))
