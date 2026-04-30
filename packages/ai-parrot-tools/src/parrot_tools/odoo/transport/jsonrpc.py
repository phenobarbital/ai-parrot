"""JSON-RPC 2.0 transport — adapts the existing async OdooInterface."""
from __future__ import annotations

from typing import Any

from parrot.interfaces.odoointerface import OdooConfig, OdooInterface

from .base import AbstractOdooTransport


class JsonRpcTransport(AbstractOdooTransport):
    """Wrap :class:`parrot.interfaces.OdooInterface` as a transport.

    Delegates all calls to the underlying interface — the only state held here
    is the wrapped interface itself. This keeps a single source of truth for
    JSON-RPC 2.0 semantics in the parrot codebase.
    """

    name: str = "jsonrpc"

    def __init__(self, interface: OdooInterface) -> None:
        """Initialise the transport.

        Args:
            interface: A configured :class:`OdooInterface` instance.
        """
        self._interface = interface
        self.config = interface.config

    @property  # type: ignore[override]
    def uid(self) -> int | None:
        return self._interface.uid

    @uid.setter
    def uid(self, value: int | None) -> None:
        self._interface.uid = value

    @classmethod
    def from_config(cls, config: OdooConfig) -> "JsonRpcTransport":
        """Build a transport from an :class:`OdooConfig` payload."""
        return cls(
            OdooInterface(
                url=config.url,
                database=config.database,
                username=config.username,
                password=config.password,
                timeout=config.timeout,
                verify_ssl=config.verify_ssl,
            )
        )

    async def authenticate(self) -> int:
        return await self._interface.authenticate()

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        return await self._interface.execute_kw(model, method, args, kwargs)

    async def version(self) -> dict[str, Any]:
        return await self._interface.version()

    async def close(self) -> None:
        await self._interface.close()
