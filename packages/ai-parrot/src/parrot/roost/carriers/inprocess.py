"""In-process carrier: one asyncio.Queue per address, payloads by reference (FEAT-747 M7, resolved U5)."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
import uuid
from typing import Sequence

from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind
from .base import Carrier, CarrierClosed, Inbound, Undeliverable


class InProcessCarrier(Carrier):
    """Shared by every RoostEndpoint in the process. Never copies ``content``."""

    kind = CarrierKind.IN_PROCESS

    def __init__(self, *, maxsize: int = 1024) -> None:
        self.logger = logging.getLogger(__name__)
        self._maxsize = maxsize
        self._subs: dict[str, tuple[AgentAddress, Inbound, tuple[str, ...], asyncio.Queue, asyncio.Task]] = {}
        self._closed = False

    async def send(self, msg: RoostMessage) -> None:
        """Put the same message object on every matching subscriber queue."""
        if self._closed:
            raise CarrierClosed("in-process carrier is closed")
        if msg.capability_filter:
            pattern = msg.capability_filter
            targets = [
                sub
                for sub in self._subs.values()
                if sub[0].name != msg.sender.name and any(fnmatch.fnmatchcase(cap, pattern) for cap in sub[2])
            ]
            if not targets:
                raise Undeliverable(f"no subscriber matches capability filter {pattern!r}")
        else:
            targets = []
            for receiver in msg.receivers:
                found = [sub for sub in self._subs.values() if sub[0].name == receiver.name]
                if not found:
                    raise Undeliverable(receiver.name)
                targets.extend(found)
            if not targets:
                raise Undeliverable("message has no receivers")
        for sub in targets:
            await sub[3].put(msg)

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        """Create a queue and consumer task for *address*."""
        if self._closed:
            raise CarrierClosed("in-process carrier is closed")
        sub_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        task = asyncio.create_task(self._consume(queue, inbound, address.name))
        self._subs[sub_id] = (address, inbound, tuple(capabilities), queue, task)
        return sub_id

    async def _consume(self, queue: asyncio.Queue, inbound: Inbound, name: str) -> None:
        while True:
            msg = await queue.get()
            try:
                await inbound(msg)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a handler failure must not kill the consumer
                self.logger.exception("Roost inbound handler for %s failed", name)

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Cancel the consumer task of a subscription."""
        sub = self._subs.pop(subscription_id, None)
        if sub is None:
            return False
        sub[4].cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sub[4]
        return True

    async def close(self) -> None:
        """Cancel every consumer; subsequent sends raise CarrierClosed."""
        self._closed = True
        for sub_id in list(self._subs):
            await self.unsubscribe(sub_id)

    def pending(self, name: str) -> int:
        """Queue depth for *name* (tests and the L-S1 metric)."""
        return sum(q.qsize() for addr, _, _, q, _ in self._subs.values() if addr.name == name)
