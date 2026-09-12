"""Transport protocol the dispatch service renders through (spec §3 Module 8)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Protocol

from parrot.integrations.devloop.models import GateView, Requester, RequestType, RunEvent, RunRecord


class DevLoopTransport(Protocol):
    """Channel adapter contract.

    Every method is best-effort: the service logs failures and never lets
    them reach the run.
    """

    async def post_confirm(
        self, pending_id: str, kind: RequestType, fields: Dict[str, str], requester: Requester, channel_id: str
    ) -> str:
        """Post the confirm card (both kinds, Q1); return its message id."""
        ...

    async def update_confirm(self, pending_id: str, outcome: str, record: Optional[RunRecord]) -> None:
        """Edit the confirm card after confirm/discard/expiry."""
        ...

    async def post_run_dispatched(self, record: RunRecord) -> str:
        """Post the public thread root; return its message id (Slack ``ts``)."""
        ...

    async def post_run_started(self, record: RunRecord) -> None:
        """Announce the child is up (handshake received)."""
        ...

    async def post_spawn_failed(self, record: RunRecord, error: str) -> None:
        """Announce a child that failed before its handshake."""
        ...

    async def post_gate(self, record: RunRecord, gate: GateView) -> None:
        """Post a new gate card."""
        ...

    async def update_gate(self, record: RunRecord, gate: GateView) -> None:
        """Edit a gate card after it resolves or expires."""
        ...

    async def update_status(self, record: RunRecord, state: Dict[str, Any]) -> None:
        """Update the live node-status card (M13); no-op by default."""
        ...

    async def post_terminal(self, record: RunRecord, event: RunEvent) -> None:
        """Post the terminal summary."""
        ...


class NullTransport:
    """Logs every call; returns synthetic ids. Used by tests and headless/CLI callers."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.calls: list = []

    async def post_confirm(self, pending_id, kind, fields, requester, channel_id) -> str:
        self.calls.append(("post_confirm", (pending_id, kind)))
        return f"confirm-{pending_id}"

    async def update_confirm(self, pending_id, outcome, record) -> None:
        self.calls.append(("update_confirm", (pending_id, outcome)))

    async def post_run_dispatched(self, record) -> str:
        self.calls.append(("post_run_dispatched", (record.run_id,)))
        return f"thread-{record.run_id}"

    async def post_run_started(self, record) -> None:
        self.calls.append(("post_run_started", (record.run_id,)))

    async def post_spawn_failed(self, record, error) -> None:
        self.calls.append(("post_spawn_failed", (record.run_id, error)))

    async def post_gate(self, record, gate) -> None:
        self.calls.append(("post_gate", (record.run_id, gate.gate_id)))

    async def update_gate(self, record, gate) -> None:
        self.calls.append(("update_gate", (record.run_id, gate.gate_id)))

    async def update_status(self, record, state) -> None:
        self.calls.append(("update_status", (record.run_id,)))

    async def post_terminal(self, record, event) -> None:
        self.calls.append(("post_terminal", (record.run_id, event.kind)))
