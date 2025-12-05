"""Simple in-memory storage for agent interactions keyed by turn_id."""

import asyncio
from typing import Any, Dict, Optional


class AgentMemory:
    """Store and retrieve agent interactions by turn identifier."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._interactions: Dict[str, Dict[str, Any]] = {self.agent_id: {}}
        self._lock = asyncio.Lock()

    async def store_interaction(self, turn_id: str, question: str, answer: Any) -> None:
        """Persist a question/answer pair under the provided turn identifier."""
        if not turn_id:
            raise ValueError("turn_id is required to store an interaction")

        async with self._lock:
            self._interactions[self.agent_id][turn_id] = {
                "question": question,
                "answer": answer,
            }

    async def get(self, turn_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a stored interaction by turn identifier."""
        if not turn_id:
            return None

        async with self._lock:
            return self._interactions.get(self.agent_id, {}).get(turn_id)
