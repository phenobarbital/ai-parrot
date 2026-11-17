"""Roost capability-directory models (FEAT-747 M3). Imported by parrot.registry — keep it dependency-light."""

from __future__ import annotations

from enum import IntEnum
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

from .performatives import CarrierKind


class Locality(IntEnum):
    """Relative location of a registered agent, ordered from nearest to farthest."""

    IN_PROCESS = 0
    SAME_HOST = 1
    SAME_NETWORK = 2
    REMOTE = 3


class InterAgentGrant(BaseModel):
    """Capability-pattern scopes an agent may call (``hr.*``, ``*``). Empty means not granted."""

    scopes: list[str] = Field(default_factory=list)


class RoostAgentConfig(BaseModel):
    """What an agent advertises on its registry entry and how it is reached."""

    capabilities: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    category_hashes: dict[str, str] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    carrier: CarrierKind = CarrierKind.IN_PROCESS
    host_id: Optional[str] = None
    cost: float = 1.0
    backing: Literal["deterministic", "llm_backed"] = "llm_backed"
    grant: Optional[InterAgentGrant] = None
    bid: Optional[dict[str, float]] = None


class CapabilityMatch(BaseModel):
    """One ranked agent match for a requested capability."""

    agent_name: str
    cap_id: str
    locality: Locality
    cost: float
    kind: str = "local"
    backing: str = "llm_backed"
    score: float = 1.0
    category_hash: Optional[str] = None


def locality_of(config: Optional[RoostAgentConfig], *, kind: str, local_host_id: Optional[str]) -> Locality:
    """Classify where an agent runs relative to the caller.

    Args:
        config: Roost advertisement for the agent, if it has one.
        kind: Registry entry kind, including remote ``a2a`` and ``squawk`` entries.
        local_host_id: Host identifier of the caller.

    Returns:
        The deterministic locality classification.
    """
    if kind in ("a2a", "squawk"):
        return Locality.REMOTE
    if config is None or config.carrier == CarrierKind.IN_PROCESS:
        return Locality.IN_PROCESS
    if config.carrier == CarrierKind.SAME_HOST:
        if config.host_id == local_host_id:
            return Locality.SAME_HOST
        return Locality.SAME_NETWORK
    return Locality.SAME_NETWORK


def rank(matches: Iterable[CapabilityMatch]) -> list[CapabilityMatch]:
    """Stable sort by locality, cost, and descending score.

    Args:
        matches: Capability matches to order.

    Returns:
        A new list ordered from the preferred match to the least preferred match.
    """
    return sorted(matches, key=lambda match: (int(match.locality), match.cost, -match.score))
