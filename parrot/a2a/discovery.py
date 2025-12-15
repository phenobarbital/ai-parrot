# parrot/a2a/discovery.py
"""
Agent Registry for discovering agents in the mesh.
"""
from typing import Dict, Optional, List
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from .models import AgentCard
from .client import A2AClient


@dataclass
class RegisteredAgent:
    url: str
    card: AgentCard
    last_seen: datetime = field(default_factory=datetime.utcnow)
    healthy: bool = True


class AgentRegistry:
    """
    Simple in-memory agent registry.
    For production, use etcd, Consul, or Redis.
    """

    def __init__(self, health_check_interval: float = 30.0):
        self._agents: Dict[str, RegisteredAgent] = {}
        self._health_check_interval = health_check_interval
        self._health_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start background health checking."""
        self._health_task = asyncio.create_task(self._health_check_loop())

    async def stop(self):
        if self._health_task:
            self._health_task.cancel()

    async def register(self, url: str) -> AgentCard:
        """Register an agent by URL (fetches its card)."""
        async with A2AClient(url) as client:
            card = await client.discover()
            self._agents[card.name] = RegisteredAgent(url=url, card=card)
            return card

    def get(self, name: str) -> Optional[RegisteredAgent]:
        """Get a registered agent by name."""
        return self._agents.get(name)

    def get_by_skill(self, skill_id: str) -> List[RegisteredAgent]:
        """Find agents that have a specific skill."""
        results = []
        for agent in self._agents.values():
            if agent.healthy:
                for skill in agent.card.skills:
                    if skill.id == skill_id:
                        results.append(agent)
                        break
        return results

    def get_by_tag(self, tag: str) -> List[RegisteredAgent]:
        """Find agents with skills matching a tag."""
        results = []
        for agent in self._agents.values():
            if agent.healthy:
                for skill in agent.card.skills:
                    if tag in skill.tags:
                        results.append(agent)
                        break
        return results

    async def _health_check_loop(self):
        """Periodically check agent health."""
        while True:
            await asyncio.sleep(self._health_check_interval)

            for name, agent in list(self._agents.items()):
                try:
                    async with A2AClient(agent.url, timeout=5.0) as client:
                        await client.discover()
                        agent.healthy = True
                        agent.last_seen = datetime.now(timezone.utc)
                except Exception:
                    agent.healthy = False

    def list_healthy(self) -> List[RegisteredAgent]:
        """Get all healthy agents."""
        return [a for a in self._agents.values() if a.healthy]
