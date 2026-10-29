"""Client-side received ledger (D13 level 2): what came back, from whom, under which contract, and what the LLM did with it."""

from __future__ import annotations

import logging
from collections import deque
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from parrot.interagent import CallCost


class ReceivedLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    remote_agent: str
    cap_id: str
    contract_hash: str
    handle_key: str | None = None
    descriptor_digest: str | None = None
    cost: CallCost
    trace_id: str
    follow_ups: tuple[str, ...] = ()


class ReceivedLedger:
    def __init__(self, *, sink: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None:
        self._sink = sink
        self._recent: deque[ReceivedLedgerEntry] = deque(maxlen=max_entries)
        self.logger = logging.getLogger(__name__)

    async def append(self, entry: ReceivedLedgerEntry) -> None:
        self._recent.append(entry)
        if self._sink is not None:
            try:
                await self._sink(entry.model_dump_json())
            except Exception:  # noqa: BLE001 — receiving side is best-effort (the served ledger is the fail-closed one)
                self.logger.exception("ReceivedLedger: sink failed")

    def note_follow_up(self, handle_key: str, tool_name: str) -> None:
        """Record that a local affordance consumed the handle."""
        # Find the latest entry with handle_key, replace it with model_copy(update={"follow_ups": (*e.follow_ups, tool_name)})
        # No-op when absent
        for i in range(len(self._recent) - 1, -1, -1):
            entry = self._recent[i]
            if entry.handle_key == handle_key:
                updated_entry = entry.model_copy(update={"follow_ups": (*entry.follow_ups, tool_name)})
                self._recent[i] = updated_entry
                return

    def recent(self, *, limit: int = 100) -> list[ReceivedLedgerEntry]:
        return list(self._recent)[-limit:]
