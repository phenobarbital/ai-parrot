"""PostgreSQL LISTEN/NOTIFY hook."""
import asyncio
from typing import Optional

import asyncpg
import backoff
from navconfig.logging import logging

from .base import BaseHook
from .models import HookType, PostgresHookConfig


class PostgresListenHook(BaseHook):
    """Listens to a PostgreSQL channel via LISTEN/NOTIFY and emits HookEvents."""

    hook_type = HookType.POSTGRES_LISTEN

    def __init__(self, config: PostgresHookConfig, **kwargs) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._dsn = config.dsn
        self._channel = config.channel
        self._connection: Optional[asyncpg.Connection] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._reconnecting = False

    @backoff.on_exception(
        backoff.expo,
        (asyncpg.PostgresError, ConnectionError, OSError),
        max_tries=5,
        on_backoff=lambda d: logging.warning(
            f"PG reconnect attempt in {d['wait']:.1f}s..."
        ),
    )
    async def _connect(self) -> None:
        self._connection = await asyncpg.connect(dsn=self._dsn)
        await self._connection.add_listener(
            self._channel, self._notification_handler
        )
        self.logger.info(
            f"Connected to PostgreSQL, listening on '{self._channel}'"
        )
        self._listen_task = asyncio.create_task(self._keep_alive())

    async def start(self) -> None:
        await self._connect()
        self.logger.info(f"PostgresListenHook '{self.name}' started")

    async def stop(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass
        self.logger.info(f"PostgresListenHook '{self.name}' stopped")

    async def _keep_alive(self) -> None:
        """Keep the asyncio task alive so the listener remains active."""
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.logger.debug("Keep-alive task cancelled")
        except Exception as exc:
            self.logger.error(f"Keep-alive error: {exc}")
            await self._reconnect()

    async def _reconnect(self) -> None:
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            if self._connection:
                try:
                    await self._connection.close()
                except Exception:
                    pass
            self.logger.info("Attempting PostgreSQL reconnection...")
            await self._connect()
        finally:
            self._reconnecting = False

    async def _notification_handler(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        self.logger.debug(
            f"PG notification on '{channel}': {payload}"
        )
        event = self._make_event(
            event_type="pg.notification",
            payload={
                "channel": channel,
                "payload": payload,
                "pid": pid,
            },
            task=f"PostgreSQL notification: {payload}",
        )
        await self.on_event(event)
