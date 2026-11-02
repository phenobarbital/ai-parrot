"""Client-side received ledger (D13 level 2): what came back, from whom, under which contract, and what the LLM did with it."""

from __future__ import annotations

import logging
from collections import deque
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from parrot.interagent import CallCost


class ReceivedLedgerEntry(BaseModel):
    """One result received from a remote agent, and what the local LLM did with it."""

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
    """Bounded client-side record of received results (best-effort, unlike the served ledger)."""

    def __init__(self, *, sink: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None:
        """Initialize the ledger.

        Args:
            sink: Optional async JSON sink; failures are logged, never raised.
            max_entries: Size of the in-memory recent window.
        """
        self._sink = sink
        self._recent: deque[ReceivedLedgerEntry] = deque(maxlen=max_entries)
        self.logger = logging.getLogger(__name__)

    async def append(self, entry: ReceivedLedgerEntry) -> None:
        """Record an entry and forward it to the sink.

        Args:
            entry: Received-result record.
        """
        self._recent.append(entry)
        if self._sink is not None:
            try:
                await self._sink(entry.model_dump_json())
            except Exception:  # noqa: BLE001 — receiving side is best-effort (the served ledger is the fail-closed one)
                self.logger.exception("ReceivedLedger: sink failed")

    def note_follow_up(self, handle_key: str, tool_name: str) -> None:
        """Record that a local affordance consumed the handle (no-op when the handle is unknown).

        Args:
            handle_key: Handle key of the received artifact.
            tool_name: Local tool that consumed it.
        """
        for i in range(len(self._recent) - 1, -1, -1):
            entry = self._recent[i]
            if entry.handle_key == handle_key:
                updated_entry = entry.model_copy(update={"follow_ups": (*entry.follow_ups, tool_name)})
                self._recent[i] = updated_entry
                return

    def recent(self, *, limit: int = 100) -> list[ReceivedLedgerEntry]:
        """Return up to ``limit`` most recent entries, oldest first.

        Args:
            limit: Maximum entries; ``0`` or less returns none.

        Returns:
            The most recent entries.
        """
        if limit <= 0:
            return []
        return list(self._recent)[-limit:]
