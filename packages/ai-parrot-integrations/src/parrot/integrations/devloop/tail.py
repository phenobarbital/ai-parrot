"""``flow:{run_id}:actions`` → :class:`RunEvent` (spec §3 Module 7)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer  # verified: streaming.py:73
from parrot.integrations.devloop.models import GateView, RunEvent

_NODE_STATUS = {
    "node/started": "running",
    "node/completed": "completed",
    "node/failed": "failed",
    "node/skipped": "skipped",
}
_TERMINAL_KINDS = frozenset({"run_closed", "run_cancelled"})
_MAX_BACKOFF = 30.0


def _gate_view(raw: Dict[str, Any]) -> GateView:
    """Project an ``ApprovalGate.model_dump()`` (session_state.py:257) onto ``GateView``."""
    return GateView(**{k: raw[k] for k in GateView.model_fields if k in raw})


def _frame_to_event(run_id: str, frame: Dict[str, Any]) -> Optional[RunEvent]:
    """Apply the M7 mapping table; ``None`` for frames the integration ignores.

    Args:
        run_id: The run the frame belongs to.
        frame: One frame yielded by ``FlowStreamMultiplexer.state_replay()``/``state_tail()``.

    Returns:
        The mapped :class:`RunEvent`, or ``None`` when the frame's action
        type is not one the dev-loop integration surfaces.
    """
    payload = frame.get("payload") or {}
    if frame.get("event_kind") == "snapshot":
        return RunEvent(
            run_id=run_id,
            kind="snapshot",
            seq=int(payload.get("from_seq", 0)),
            state=payload.get("state"),
        )

    action = payload.get("action") or {}
    seq = int(payload.get("server_seq", 0))
    atype = action.get("type", "")

    if atype == "gate/opened":
        return RunEvent(run_id=run_id, kind="gate_opened", seq=seq, gate=_gate_view(action.get("gate") or {}))
    if atype == "gate/resolved":
        gate = GateView(
            gate_id=action.get("gate_id", ""),
            kind="",
            title="",
            status=action.get("resolution", ""),
            resolved_by=action.get("resolved_by", ""),
            answers=action.get("answers") or {},
        )
        return RunEvent(run_id=run_id, kind="gate_resolved", seq=seq, gate=gate)
    if atype == "gate/expired":
        gate = GateView(gate_id=action.get("gate_id", ""), kind="", title="", status="expired")
        return RunEvent(run_id=run_id, kind="gate_expired", seq=seq, gate=gate)
    if atype in _NODE_STATUS:
        return RunEvent(
            run_id=run_id,
            kind="node_changed",
            seq=seq,
            node_id=action.get("node_id", ""),
            node_status=_NODE_STATUS[atype],
        )
    if atype == "run/jiraLinked":
        return RunEvent(
            run_id=run_id, kind="jira_linked", seq=seq, state={"jira_issue_key": action.get("issue_key", "")}
        )
    if atype == "run/closed":
        return RunEvent(
            run_id=run_id,
            kind="run_closed",
            seq=seq,
            state={
                "outcome": action.get("outcome", ""),
                "jira_issue_key": action.get("jira_issue_key", ""),
                "pr_url": action.get("pr_url", ""),
            },
        )
    if atype == "run/cancelled":
        return RunEvent(
            run_id=run_id,
            kind="run_cancelled",
            seq=seq,
            state={"requested_by": action.get("requested_by", "")},
        )
    return None


class RunStateTail:
    """Replay + live tail of one run's state stream with bounded reconnects."""

    def __init__(self, redis: Any, run_id: str) -> None:
        self._redis = redis
        self._run_id = run_id
        self._mux: Optional[FlowStreamMultiplexer] = None
        self._closed = asyncio.Event()
        self.logger = logging.getLogger(__name__)

    async def events(self, *, last_seen: Optional[int] = None) -> AsyncIterator[RunEvent]:
        """Yield ``RunEvent``s until a terminal one, or :meth:`close`.

        Reconnects on any Redis error with exponential backoff (1→30s),
        always resuming via a fresh ``state_replay(last_seen=...)`` — a
        bare ``state_tail()`` on a NEW multiplexer instance starts at
        ``"$"`` and would silently drop everything published during the
        outage (spec §7 "Redis outage while tailing").

        Args:
            last_seen: The last ``server_seq`` already delivered, or
                ``None`` to also receive the initial snapshot.

        Yields:
            Each new :class:`RunEvent`, never repeating a ``seq``.
        """
        last_yielded = last_seen or 0
        attempt = 0
        while not self._closed.is_set():
            self._mux = FlowStreamMultiplexer(self._redis, run_id=self._run_id, view="state")
            try:
                async for frame in self._mux.state_replay(last_seen=last_seen):
                    event = _frame_to_event(self._run_id, frame)
                    attempt = 0
                    if event is None:
                        continue
                    if event.kind != "snapshot" and event.seq <= last_yielded:
                        continue
                    if event.kind != "snapshot":
                        last_yielded = event.seq
                    yield event
                    if event.kind in _TERMINAL_KINDS:
                        return
                async for frame in self._mux.state_tail():
                    event = _frame_to_event(self._run_id, frame)
                    attempt = 0
                    if event is None:
                        continue
                    if event.kind != "snapshot" and event.seq <= last_yielded:
                        continue
                    if event.kind != "snapshot":
                        last_yielded = event.seq
                    yield event
                    if event.kind in _TERMINAL_KINDS:
                        return
                # state_tail() ended without a terminal event (closed()) — stop.
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - connection loss: back off and resume from last_yielded
                attempt += 1
                delay = min(_MAX_BACKOFF, 2.0**attempt)
                self.logger.warning("state tail for %s failed (%s); retrying in %.0fs", self._run_id, exc, delay)
                last_seen = last_yielded
                await asyncio.sleep(delay)

    async def close(self) -> None:
        """Stop the tail; safe to call multiple times."""
        self._closed.set()
        if self._mux is not None:
            await self._mux.close()
