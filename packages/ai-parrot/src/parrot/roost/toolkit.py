"""LLM-facing Roost origin tools (FEAT-747 M11). The harness maps each tool to a Performative."""

from __future__ import annotations

from typing import Any, Literal, Optional

from parrot.tools.toolkit import AbstractToolkit

from .endpoint import RoostEndpoint
from .messages import AgentAddress
from .performatives import Performative


class RoostToolkit(AbstractToolkit):
    """Talk to other agents of this trust domain. Never exposes the inter-agent grant."""

    def __init__(self, endpoint: RoostEndpoint, **kwargs: Any) -> None:
        self._endpoint = endpoint
        super().__init__(**kwargs)

    async def send(
        self,
        performative: Literal["inform", "request", "query", "subscribe"],
        receiver: str,
        content: str,
        body: Optional[str] = None,
    ) -> dict:
        """Send a message to another agent when no more specific tool fits."""
        message = await self._endpoint.send(
            Performative(performative),
            receivers=[AgentAddress(name=receiver)],
            content=content,
            body=body,
        )
        return {"status": "sent", "conversation_id": message.conversation_id}

    async def report(self, receiver: str, fact: str) -> dict:
        """Tell another agent a fact or result. Fire-and-forget: no reply is expected or awaited."""
        message = await self._endpoint.send(
            Performative.INFORM,
            receivers=[AgentAddress(name=receiver)],
            content=fact,
        )
        return {"status": "sent", "conversation_id": message.conversation_id}

    async def call_for_proposals(self, capability_filter: str, task: str, bid_window_ms: int = 500) -> dict:
        """Ask every agent advertising a capability to bid on a task; returns the award (winner, decided_by)."""
        award = await self._endpoint.cfp(
            capability_filter=capability_filter,
            task=task,
            bid_window_ms=bid_window_ms,
        )
        return award.model_dump(mode="json")

    async def watch(self, key: str) -> dict:
        """Subscribe to a shared blackboard key; changes arrive as notifications."""
        subscription_id = await self._endpoint.subscribe(blackboard_key=key)
        return {"status": "subscribed", "subscription_id": subscription_id}

    async def find_agents(self, query: str) -> list[dict]:
        """Find agents that can answer by capability or keyword (no LLM involved)."""
        if self._endpoint.registry is None:
            return []
        matches = self._endpoint.registry.find_capability(query, caller=self._endpoint.agent_name)
        return [match.model_dump(mode="json") for match in matches]
