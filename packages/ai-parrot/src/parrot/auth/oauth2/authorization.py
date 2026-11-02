"""Request-independent authorization for connection operations (FEAT-777 M2).

Core declares the contract; the server injects a navigator-auth PDP adapter.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from parrot.auth.principal import Principal


@runtime_checkable
class ConnectionAuthorizer(Protocol):
    """Decide whether a principal may perform a connection action without HTTP."""

    async def authorize(
        self,
        principal: Principal,
        action: str,
        provider_id: Optional[str],
        scopes: List[str],
    ) -> bool:
        """Return ``True`` only for an explicit allow decision.

        Args:
            principal: Resolved platform principal.
            action: Integration action being authorized.
            provider_id: Provider id, or ``None`` for collection operations.
            scopes: Effective requested scopes.
        """
        ...
