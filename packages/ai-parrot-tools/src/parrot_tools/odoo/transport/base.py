"""Abstract transport for Odoo external API dialects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from parrot.interfaces.odoointerface import OdooConfig


class AbstractOdooTransport(ABC):
    """Common surface for JSON-2, legacy JSON-RPC, and XML-RPC backends.

    Concrete transports are responsible for authentication, dispatching
    toolkit calls, and reporting server version. The toolkit composes one of
    these — it never constructs an Odoo client directly.
    """

    config: OdooConfig
    uid: int | None

    @abstractmethod
    async def authenticate(self) -> int:
        """Authenticate against Odoo and cache the user id.

        Returns:
            The authenticated user id.

        Raises:
            OdooAuthenticationError: On invalid credentials.
            OdooRPCError: On Odoo-side errors.
            OdooConnectionError: On network failures.
        """

    @abstractmethod
    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Dispatch a model method via the underlying Odoo external API."""

    @abstractmethod
    async def version(self) -> dict[str, Any]:
        """Return server version info (no auth required)."""

    @abstractmethod
    async def close(self) -> None:
        """Release any held resources (sessions, sockets)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable transport identifier ('json2' | 'jsonrpc' | 'xmlrpc')."""
