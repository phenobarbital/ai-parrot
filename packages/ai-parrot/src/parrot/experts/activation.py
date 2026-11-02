"""Attribution scope for an expert activation (FEAT-778 M3, G8)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from parrot.observability.context import agent_identity, usage_attribution

if TYPE_CHECKING:
    from parrot.experts.agent import ExpertAgent


@asynccontextmanager
async def activate_expert(
    expert: "ExpertAgent", *, run_id: str | None, stage: str | None
) -> AsyncIterator["ExpertAgent"]:
    """Bind agent identity and usage attribution to an expert; restored on exit (AC12).

    Args:
        expert: The expert being activated.
        run_id: Run identifier for usage attribution.
        stage: Stage name; the seat becomes ``<stage>.<expert>`` (or just the expert name).

    Yields:
        The same expert, with attribution context vars bound.
    """
    name = expert.bundle.manifest.name
    seat = f"{stage}.{name}" if stage else name
    with agent_identity(name), usage_attribution(run_id, seat):
        yield expert
