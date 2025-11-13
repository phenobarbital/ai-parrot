from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
from navconfig.logging import logging
from ...utils.helpers import RequestContext


class AbstractKnowledgeBase(ABC):
    """Base class for all knowledge bases."""

    def __init__(
        self,
        name: str,
        category: str,
        description: str = None,
        activation_patterns: List[str] = None,
        always_active: bool = False,
        priority: int = 0
    ):
        self.name = name
        self.category = category
        self.activation_patterns = activation_patterns or []
        self.description = description or f"{name} knowledge base"
        self.always_active = always_active
        self.priority = priority  # Higher = included first
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    async def should_activate(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, float]:
        """
        Determine if this KB should be activated for the query.
        Returns (should_activate, confidence_score)
        """
        pass

    async def close(self):
        """Cleanup resources if needed."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.7,
        user_id: str = None,
        session_id: str = None,
        ctx: RequestContext = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant facts/information.
        Different KBs implement this differently.
        """
        pass

    def format_context(self, results: List[Dict]) -> str:
        """Format results for prompt injection."""
        if not results:
            return ""

        lines = [f"## {self.name}:"]
        for result in results:
            lines.append(f"* {result.get('content', result)}")
        return "\n".join(lines)
