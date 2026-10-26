"""Same-host carrier: frames as Arrow IPC in shared memory (FEAT-747 M8)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional, Sequence

import pandas as pd
from pydantic import BaseModel

from parrot.tools.repl_worker.transport import decode_dataframe_from_shm, encode_dataframe, unlink_shm

from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind
from .base import Carrier, Inbound


class ShmPayloadRef(BaseModel):
    """Reference to a frame living in a shared-memory segment."""

    shm_name: str
    size: int
    schema_digest: str
    rows: int


class SharedMemoryCarrier(Carrier):
    """Moves DataFrame content through shared memory; signalling rides the *signal* carrier."""

    kind = CarrierKind.SAME_HOST

    def __init__(self, *, signal: Carrier, max_bytes: Optional[int] = None) -> None:
        self.logger = logging.getLogger(__name__)
        self._signal = signal
        self._max_bytes = max_bytes
        self._owned: dict[str, ShmPayloadRef] = {}

    async def send(self, msg: RoostMessage) -> None:
        """Encode frame content (strict Arrow), replace it by ShmPayloadRef, deliver over *signal*."""
        content = msg.content
        if hasattr(content, "to_pandas") and not isinstance(content, pd.DataFrame):
            content = content.to_pandas()  # pyarrow.Table
        if not isinstance(content, pd.DataFrame):
            await self._signal.send(msg)
            return
        encoded = await asyncio.to_thread(
            encode_dataframe, content, msg.conversation_id, strict=True, max_bytes=self._max_bytes
        )
        digest = hashlib.sha256(
            ",".join(f"{col}:{dtype}" for col, dtype in zip(content.columns, content.dtypes)).encode("utf-8")
        ).hexdigest()
        ref = ShmPayloadRef(
            shm_name=encoded.shm_name or "",
            size=encoded.size or 0,
            schema_digest=digest,
            rows=len(content),
        )
        self._owned[ref.shm_name] = ref
        try:
            await self._signal.send(msg.model_copy(update={"content": ref}))
        except BaseException:
            await self.ack(ref)
            raise

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        """Wrap *inbound*: decode a ShmPayloadRef, call inbound, then ACK."""

        async def _wrapper(msg: RoostMessage) -> None:
            ref = msg.content
            if not isinstance(ref, ShmPayloadRef):
                await inbound(msg)
                return
            try:
                df = await asyncio.to_thread(decode_dataframe_from_shm, ref.shm_name, ref.size)
                await inbound(msg.model_copy(update={"content": df}))
            finally:
                await self.ack(ref)

        return await self._signal.subscribe(address, _wrapper, capabilities=capabilities)

    async def ack(self, ref: ShmPayloadRef) -> None:
        """Receiver ACK ⇒ sender unlinks; idempotent."""
        if self._owned.pop(ref.shm_name, None) is not None:
            unlink_shm(ref.shm_name)

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription on the signal carrier."""
        return await self._signal.unsubscribe(subscription_id)

    async def close(self) -> None:
        """Unlink every segment still owned, then close the signal carrier."""
        for name in list(self._owned):
            self._owned.pop(name)
            unlink_shm(name)
        await self._signal.close()
