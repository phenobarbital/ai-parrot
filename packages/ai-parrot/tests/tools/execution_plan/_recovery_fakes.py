"""Shared fakes for FEAT-585 recovery tests. Stores hold REAL FlowStateSerializer bytes.

These fakes are imported by every FEAT-585 recovery test module (TASK-3593..3603) —
keep this file's public surface stable; new tests depend on it verbatim.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpoint, FlowStateSerializer
from parrot.clients.base import AbstractClient


class SerializingFakeCheckpointStore(CheckpointStore):
    """In-memory store that encodes/decodes every checkpoint through the real serializer.

    ``failures`` lets a test inject ``ConnectionError`` on the Nth ``put``.
    ``ttl_expired`` simulates Redis key expiry (``latest`` returns None) without deleting history.
    """

    def __init__(self, *, durable: bool = False) -> None:
        self._bytes: Dict[str, Dict[int, bytes]] = {}
        self._leases: Dict[str, str] = {}
        self._serializer = FlowStateSerializer()
        self.durable = durable
        self.put_calls = 0
        self.failures: List[int] = []
        self.ttl_expired: set[str] = set()

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        self.put_calls += 1
        if self.put_calls in self.failures:
            raise ConnectionError("checkpoint store unavailable")
        # `checkpoint.model_dump()` recursively dumps ANY nested BaseModel it
        # finds — including one sitting under a `dict[str, Any]` field like
        # `context.results` — turning it into a plain dict *before*
        # `FlowStateSerializer` ever sees it as a model instance. Restore the
        # live `results`/`responses` values after the structural dump so
        # `serializer.encode()`'s own `isinstance(value, BaseModel)` walk is
        # the ONE place that tags a registered type (R1) — this is what
        # `FlowContext.to_snapshot()` + a real store correctly avoid doing
        # twice; a hand-built checkpoint must have the same property.
        payload = checkpoint.model_dump(mode="python")
        payload["context"]["results"] = dict(checkpoint.context.results)
        if checkpoint.context.responses is not None:
            payload["context"]["responses"] = dict(checkpoint.context.responses)
        self._bytes.setdefault(checkpoint.flow_id, {})[checkpoint.checkpoint_id] = self._serializer.encode(payload)

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        if flow_id in self.ttl_expired or flow_id not in self._bytes:
            return None
        return await self.get(flow_id, max(self._bytes[flow_id]))

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        raw = self._bytes.get(flow_id, {}).get(checkpoint_id)
        return None if raw is None else FlowCheckpoint.model_validate(self._serializer.decode(raw))

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        ids = sorted(self._bytes.get(flow_id, {}), reverse=True)[:limit]
        checkpoints = []
        for checkpoint_id in ids:
            checkpoint = await self.get(flow_id, checkpoint_id)
            if checkpoint is not None:
                checkpoints.append(checkpoint)
        return checkpoints

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        flows: list[dict[str, Any]] = []
        for flow_id in self._bytes:
            latest = await self.latest(flow_id)
            if latest is None:
                continue
            if status is not None and latest.status != status:
                continue
            flows.append({"flow_id": flow_id, "flow_name": latest.flow_name, "status": latest.status,
                          "checkpoint_id": latest.checkpoint_id})
        return flows

    async def delete_flow(self, flow_id: str) -> None:
        self._bytes.pop(flow_id, None)
        self._leases.pop(flow_id, None)
        self.ttl_expired.discard(flow_id)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leases:
            return False
        self._leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self._leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if self._leases.get(flow_id) == holder:
            del self._leases[flow_id]

    async def close(self) -> None:
        pass


class ScriptedPlannerClient(AbstractClient):
    """AbstractClient double returning scripted ask() texts; counts calls (AC2/AC8 evidence)."""

    def __init__(self, responses: List[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._responses = list(responses)
        self.calls: List[str] = []

    async def get_client(self) -> Any:
        return self

    async def __aenter__(self) -> "ScriptedPlannerClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        text = self._responses.pop(0)
        return SimpleNamespace(output=text)

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class CountingToolManager:
    """ToolManagerLike fake counting dispatches per tool (proves completed nodes are not re-run).

    ``gates`` optionally maps a tool name to an ``asyncio.Event`` that
    ``execute_tool`` awaits before returning — used to deterministically
    interrupt a run mid-dispatch without ``asyncio.sleep``-based timing.
    """

    def __init__(
        self,
        tools: Dict[str, Any],
        *,
        delays: Optional[Dict[str, float]] = None,
        gates: Optional[Dict[str, "asyncio.Event"]] = None,
    ) -> None:
        self._tools = tools
        self._delays = delays or {}
        self._gates = gates or {}
        self.calls: List[tuple] = []
        self.dispatch_counts: Dict[str, int] = {}

    def get_tool(self, name: str) -> Optional[Any]:
        return object() if name in self._tools else None

    def list_tools(self) -> List[str]:
        return list(self._tools)

    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        permission_context: Optional[Any] = None,
    ) -> Any:
        self.calls.append((tool_name, dict(parameters)))
        self.dispatch_counts[tool_name] = self.dispatch_counts.get(tool_name, 0) + 1
        delay = self._delays.get(tool_name)
        if delay:
            await asyncio.sleep(delay)
        gate = self._gates.get(tool_name)
        if gate is not None:
            await gate.wait()
        payload = self._tools[tool_name]
        return payload(parameters) if callable(payload) else payload
