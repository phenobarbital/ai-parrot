"""Attribution scope for an expert activation (FEAT-778 M3, G8)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from parrot.observability.context import agent_identity, usage_attribution

if TYPE_CHECKING:
    from parrot.experts.agent import ExpertAgent


@asynccontextmanager
async def activate_expert(
    expert: "ExpertAgent", *, run_id: str | None, stage: str | None, mode: str | None = None
) -> AsyncIterator["ExpertAgent"]:
    """Bind agent identity and usage attribution to an expert; restored on exit (AC12).

    Args:
        expert: The expert being activated.
        run_id: Run identifier for usage attribution.
        stage: Stage name; the seat becomes ``<stage>.<expert>`` (or just the expert name).
        mode: Expert dispatch mode for trace attribution.

    Yields:
        The same expert, with attribution context vars bound.
    """
    name = expert.bundle.manifest.name
    seat = f"{stage}.{name}" if stage else name
    with agent_identity(name), usage_attribution(run_id, seat):
        _set_expert_span_attributes(name, expert.bundle.manifest.tier.value, stage, mode)
        yield expert


def _set_expert_span_attributes(slug: str, tier: str, stage: str | None, mode: str | None) -> None:
    """Set expert attributes on the current recording span when OpenTelemetry is available.

    Args:
        slug: Expert manifest name.
        tier: Lowercase expert tier value.
        stage: Stage executing the expert, if known.
        mode: Expert dispatch mode, if known.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return

    span = trace.get_current_span()
    if not span.is_recording():
        return

    attributes = {
        "expert.slug": slug,
        "expert.tier": tier,
        "expert.stage": stage,
        "expert.mode": mode,
    }
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)
