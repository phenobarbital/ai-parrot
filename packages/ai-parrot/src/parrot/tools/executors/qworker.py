"""Qworker-backed remote tool executor.

Two transports are supported, picked at construction:

* ``transport="http"`` (default) — submits the envelope to a Qworker
  HTTP endpoint via ``Qclient.run()`` when the optional ``qworker`` /
  ``qclient`` package is installed, otherwise via an aiohttp client
  that follows the same conventions used elsewhere in the repo
  (``parrot/integrations/telegram/auth.py`` and
  ``parrot/interfaces/flowtask.py``).
* ``transport="redis"`` — publishes the envelope to a Redis Stream
  (``parrot:tool_tasks``) and blocks reading from a result stream
  (``parrot:tool_results``). Mirrors the pattern in
  ``parrot/services/client.py``.

The two paths are intentionally implemented in one class because they
share the envelope, the timeout semantics, and the ToolResult parsing —
only the wire details differ.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from .abstract import AbstractToolExecutor, ToolExecutionEnvelope

if TYPE_CHECKING:
    from ..abstract import ToolResult

logger = logging.getLogger(__name__)

Transport = Literal["http", "redis"]


class QworkerToolExecutor(AbstractToolExecutor):
    """Dispatch tool execution to the Qworker service.

    Args:
        transport: ``"http"`` for the Qclient HTTP API, ``"redis"`` for
            Redis Streams. Defaults to ``"http"``.
        endpoint: HTTP base URL for Qworker (e.g. ``http://qworker:9000``).
            Required when ``transport="http"`` unless
            :data:`parrot.conf.QWORKER_URL` is set.
        api_token: Optional bearer token. Falls back to
            :data:`parrot.conf.QWORKER_API_TOKEN`.
        redis_url: Redis DSN for the streams transport. Falls back to
            :data:`parrot.conf.REDIS_SERVICES_URL`.
        request_stream: Redis stream name jobs are posted to.
            Defaults to ``parrot:tool_tasks``.
        result_stream: Redis stream name results are read from.
            Defaults to ``parrot:tool_results``.
        qclient: Pre-built Qclient instance — useful for tests and for
            sharing a connection pool. When ``None``, an instance is
            created lazily from ``endpoint`` + ``api_token``.
        verify_ssl: Whether aiohttp should verify TLS certificates.
            Honours the ``NAVIGATOR_SSL_VERIFY`` env var by default.
    """

    def __init__(
        self,
        transport: Transport = "http",
        endpoint: Optional[str] = None,
        api_token: Optional[str] = None,
        redis_url: Optional[str] = None,
        request_stream: str = "parrot:tool_tasks",
        result_stream: str = "parrot:tool_results",
        qclient: Any = None,
        verify_ssl: Optional[bool] = None,
    ) -> None:
        if transport not in ("http", "redis"):
            raise ValueError(
                f"Unsupported transport {transport!r}: expected 'http' or 'redis'."
            )

        # Resolve config defaults lazily — failing fast here would force
        # importers without the relevant settings to crash.
        from ...conf import (
            QWORKER_URL,
            QWORKER_API_TOKEN,
            REDIS_SERVICES_URL,
        )

        self.transport: Transport = transport
        self.endpoint = endpoint or QWORKER_URL
        self.api_token = api_token or QWORKER_API_TOKEN
        self.redis_url = redis_url or REDIS_SERVICES_URL
        self.request_stream = request_stream
        self.result_stream = result_stream
        self._qclient = qclient
        self._owned_qclient = False
        self._http_session: Any = None
        self._redis: Any = None
        if verify_ssl is None:
            raw = os.environ.get("NAVIGATOR_SSL_VERIFY", "true")
            verify_ssl = raw.lower() not in ("false", "0", "no")
        # aiohttp wants ``False`` to disable verification, ``None`` to
        # use the default context (which does verify). It does NOT accept
        # ``True`` here.
        self._ssl_arg = None if verify_ssl else False
        self.logger = logger.getChild(self.__class__.__name__)

    async def execute(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        if self.transport == "http":
            return await self._execute_http(envelope)
        return await self._execute_redis(envelope)

    # ── HTTP transport ───────────────────────────────────────────────

    async def _execute_http(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        from ..abstract import ToolResult

        if self._qclient is None:
            self._qclient = await self._build_qclient()
            self._owned_qclient = True

        try:
            if self._qclient is not None and hasattr(self._qclient, "run"):
                payload = await asyncio.wait_for(
                    self._qclient.run(envelope.model_dump()),
                    timeout=envelope.timeout_seconds,
                )
            else:
                payload = await self._run_via_aiohttp(envelope)
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=(
                    f"Qworker HTTP did not respond within "
                    f"{envelope.timeout_seconds}s"
                ),
                metadata={
                    "executor": "qworker",
                    "transport": "http",
                    "endpoint": self.endpoint,
                },
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Qworker HTTP error: {exc}",
                metadata={
                    "executor": "qworker",
                    "transport": "http",
                    "endpoint": self.endpoint,
                },
            )

        return self._payload_to_result(payload, transport="http")

    async def _build_qclient(self) -> Any:
        """Try to instantiate the official Qclient if it's installed.

        Returns ``None`` when the package isn't present so the aiohttp
        fallback runs instead. We do not raise — Qworker over plain
        HTTP must work without the proprietary client package.
        """
        try:
            from qclient import Qclient  # type: ignore
        except ImportError:
            try:
                from qworker.client import Qclient  # type: ignore
            except ImportError:
                return None
        return Qclient(endpoint=self.endpoint, api_token=self.api_token)

    async def _run_via_aiohttp(
        self, envelope: ToolExecutionEnvelope
    ) -> Dict[str, Any]:
        import aiohttp

        if not self.endpoint:
            raise RuntimeError(
                "QworkerToolExecutor transport='http' requires endpoint "
                "(or QWORKER_URL env var)."
            )

        if self._http_session is None:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=envelope.timeout_seconds),
            )
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        url = self.endpoint.rstrip("/") + "/run"
        async with self._http_session.post(
            url,
            json=envelope.model_dump(),
            headers=headers,
            ssl=self._ssl_arg,
        ) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(
                    f"Qworker /run returned HTTP {resp.status}: {body[:512]}"
                )
            return await resp.json()

    # ── Redis Streams transport ──────────────────────────────────────

    async def _execute_redis(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        from ..abstract import ToolResult

        try:
            redis = await self._ensure_redis()
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Could not connect to Redis at {self.redis_url}: {exc}",
                metadata={"executor": "qworker", "transport": "redis"},
            )

        job_id = uuid.uuid4().hex
        message = {
            "job_id": job_id,
            "envelope": envelope.model_dump_json(),
        }
        try:
            await redis.xadd(
                self.request_stream,
                {k: v for k, v in message.items()},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Failed to publish to {self.request_stream}: {exc}",
                metadata={"executor": "qworker", "transport": "redis"},
            )

        try:
            payload = await asyncio.wait_for(
                self._await_redis_result(redis, job_id),
                timeout=envelope.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=(
                    f"No Redis result for job {job_id} within "
                    f"{envelope.timeout_seconds}s"
                ),
                metadata={
                    "executor": "qworker",
                    "transport": "redis",
                    "job_id": job_id,
                },
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Redis transport error: {exc}",
                metadata={
                    "executor": "qworker",
                    "transport": "redis",
                    "job_id": job_id,
                },
            )

        return self._payload_to_result(
            payload, transport="redis", job_id=job_id
        )

    async def _ensure_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        from redis.asyncio import from_url

        self._redis = from_url(self.redis_url, decode_responses=True)
        return self._redis

    async def _await_redis_result(
        self, redis: Any, job_id: str
    ) -> Dict[str, Any]:
        """Read the result stream until we see *job_id*.

        Uses ``xread`` with the special ``"$"`` ID for new entries and
        a one-second block, so callers can cancel the await without
        leaking a Redis blocking command for long.
        """
        last_id = "$"
        while True:
            response = await redis.xread(
                {self.result_stream: last_id},
                count=64,
                block=1000,
            )
            if not response:
                # Yield back to the event loop so cooperating tasks
                # (notably asyncio.wait_for's timeout enforcement) get
                # a chance to run even when xread returns immediately.
                await asyncio.sleep(0)
                continue
            for _stream, entries in response:
                for entry_id, fields in entries:
                    last_id = entry_id
                    if fields.get("job_id") != job_id:
                        continue
                    raw = fields.get("result", "{}")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Qworker emitted invalid JSON for job {job_id}: {exc}"
                        ) from exc

    # ── Shared helpers ───────────────────────────────────────────────

    def _payload_to_result(
        self,
        payload: Dict[str, Any],
        transport: str,
        job_id: Optional[str] = None,
    ) -> "ToolResult":
        from ..abstract import ToolResult

        if not isinstance(payload, dict) or "status" not in payload:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Qworker payload is not a ToolResult: {payload!r}",
                metadata={"executor": "qworker", "transport": transport},
            )
        metadata = dict(payload.get("metadata") or {})
        metadata.update({"executor": "qworker", "transport": transport})
        if job_id:
            metadata["job_id"] = job_id
        payload["metadata"] = metadata
        return ToolResult(**payload)

    async def close(self) -> None:
        if self._http_session is not None:
            try:
                await self._http_session.close()
            except Exception:
                pass
            self._http_session = None
        if self._owned_qclient and self._qclient is not None:
            close = getattr(self._qclient, "close", None)
            if close is not None:
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    pass
            self._qclient = None
            self._owned_qclient = False
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
