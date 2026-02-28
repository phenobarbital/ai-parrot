"""Prompt middleware pipeline for query transformation."""
from typing import Callable, Awaitable, Dict, Any, List
from dataclasses import dataclass
import logging


@dataclass
class PromptMiddleware:
    """Single transformation step in the prompt pipeline."""
    name: str
    priority: int = 0  # Lower = runs first
    transform: Callable[
        [str, Dict[str, Any]], Awaitable[str]
    ] = None
    enabled: bool = True

    async def apply(self, query: str, context: Dict[str, Any]) -> str:
        if not self.enabled or not self.transform:
            return query
        return await self.transform(query, context)


class PromptPipeline:
    """Ordered chain of prompt transformations applied before LLM call."""

    def __init__(self):
        self._middlewares: List[PromptMiddleware] = []
        self.logger = logging.getLogger(__name__)

    def add(self, middleware: PromptMiddleware) -> None:
        self._middlewares.append(middleware)
        self._middlewares.sort(key=lambda m: m.priority)

    def remove(self, name: str) -> None:
        self._middlewares = [m for m in self._middlewares if m.name != name]

    async def apply(self, query: str, context: Dict[str, Any] = None) -> str:
        context = context or {}
        for mw in self._middlewares:
            try:
                query = await mw.apply(query, context)
            except Exception as e:
                self.logger.warning(
                    f"Middleware '{mw.name}' failed: {e}, skipping"
                )
        return query

    @property
    def has_middlewares(self) -> bool:
        return bool(self._middlewares)