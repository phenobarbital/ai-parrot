"""A tenant-scoped agent registry that touches nothing global.

``AgentsFlow.from_definition`` and ``FlowContext.resolve_agent`` need *an*
object that can resolve an agent by name. The obvious candidate,
:class:`parrot.registry.registry.AgentRegistry`, cannot be instantiated per
tenant: its constructor creates directories, writes an ``__init__.py``, appends
to ``sys.path`` and writes an ``agents.yaml`` if one is missing. Those are
reasonable things for a single process-wide registry to do and unacceptable to
repeat per tenant — ``sys.path`` would grow without bound, and one directory
would be created per customer.

(That is not theoretical: simply importing ``parrot`` during this package's
first build wrote ``agents/agents.yaml`` into the repository.)

So this class implements only the surface those two call sites actually use.
It holds already-configured agents handed to it by the tenant runtime and does
no discovery of its own.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

from navconfig.logging import logging


class TenantAgentRegistry:
    """In-memory, per-tenant agent lookup.

    Satisfies the duck type ``AgentsFlow`` requires — ``get_bot_instance``,
    ``has``, ``get_instance`` — without any filesystem or ``sys.path`` effects.

    Note the Community Manager flow contains no ``type="agent"`` nodes (its
    LLM nodes hold their configured agent directly, injected by their factory),
    so in practice this registry is never consulted during graph construction.
    It is bound to the flow context anyway, so that a future agent-typed node
    resolves correctly instead of hitting the engine's synchronous
    ``get_bot_instance``, which returns ``None`` for anything not already
    instantiated.

    Args:
        tenant_id: Owning tenant, used only for logging and repr.
        agents: Optional initial mapping of name to configured agent.
    """

    def __init__(
        self, tenant_id: str, agents: Optional[Dict[str, Any]] = None
    ) -> None:
        self._tenant_id = tenant_id
        self._agents: Dict[str, Any] = dict(agents or {})
        self.logger = logging.getLogger("parrot_saas.tenancy.registry")

    @property
    def tenant_id(self) -> str:
        """The tenant this registry belongs to."""
        return self._tenant_id

    def register_instance(self, name: str, instance: Any) -> None:
        """Register an already-configured agent.

        Args:
            name: Lookup name.
            instance: An agent on which ``configure()`` has already been
                awaited. Registering an unconfigured agent is a latent
                failure, since the engine calls it without configuring.
        """
        self._agents[name] = instance

    def get_bot_instance(self, name: str) -> Optional[Any]:
        """Return an agent by name, or ``None``.

        Synchronous by contract: this is what ``from_definition`` calls.
        """
        return self._agents.get(name)

    def has(self, name: str) -> bool:
        """Whether an agent is registered under ``name``."""
        return name in self._agents

    async def get_instance(
        self, name: str, request: Any = None, **kwargs: Any
    ) -> Optional[Any]:
        """Async counterpart of :meth:`get_bot_instance`.

        Args:
            name: Lookup name.
            request: Accepted and ignored, for signature compatibility.
            **kwargs: Accepted and ignored.

        Returns:
            The agent, or ``None``.
        """
        return self._agents.get(name)

    def names(self) -> Iterator[str]:
        """Iterate the registered agent names."""
        return iter(self._agents)

    def __len__(self) -> int:
        """Number of registered agents."""
        return len(self._agents)

    def __repr__(self) -> str:
        """Debug representation naming the tenant and its agents."""
        return (
            f"TenantAgentRegistry(tenant_id={self._tenant_id!r}, "
            f"agents={sorted(self._agents)})"
        )


__all__ = ("TenantAgentRegistry",)
