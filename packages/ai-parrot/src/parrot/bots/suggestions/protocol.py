"""Suggestion provider protocol (FEAT-752)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol, Sequence, runtime_checkable

from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage
from parrot.models.suggestions import Suggestion

Lane = Literal["skill", "deterministic", "llm"]
LANES: tuple[str, ...] = ("skill", "deterministic", "llm")


@dataclass(frozen=True)
class SuggestionContext:
    """Everything a provider may look at. ``bot`` is the producing bot (read-only use)."""

    question: str
    response: AIMessage
    output_mode: OutputMode
    bot: Any
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tenant: Optional[str] = None
    # Per-collect scratch space (one context per turn). Providers use it to hand per-call results, such as the LLM
    # cost record, back to the engine without keeping them on a provider instance that every request shares.
    scratch: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@runtime_checkable
class SuggestionProvider(Protocol):
    """Cooperative chip producer. Async; should not raise (the engine guards anyway)."""

    name: str
    lane: Lane

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        """Return zero or more chips for this answer."""
        ...
