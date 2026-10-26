"""Carrier contract (FEAT-747 M7). The protocol is identical on every carrier; only payload passing differs."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, ClassVar, Sequence

from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind


class CarrierError(Exception):
    """Base class for carrier failures."""


class Undeliverable(CarrierError):
    """No recipient could be found for a message."""


class CarrierClosed(CarrierError):
    """The carrier has been closed."""


Inbound = Callable[[RoostMessage], Awaitable[None]]


class Carrier(ABC):
    """Transport contract implemented by every Roost carrier."""

    kind: ClassVar[CarrierKind]

    @abstractmethod
    async def send(self, msg: RoostMessage) -> None:
        """Deliver to every receiver (or every subscriber matching ``capability_filter``). Raises Undeliverable."""

    @abstractmethod
    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        """Register *inbound* for *address*; return a subscription id."""

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription; return whether it existed."""

    @abstractmethod
    async def close(self) -> None:
        """Release every resource held by the carrier."""
