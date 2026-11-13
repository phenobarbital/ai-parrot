"""Request-local persistent-memory scope."""

from contextvars import ContextVar, Token

from .models import MemoryRequestScope

_scope: ContextVar[MemoryRequestScope | None] = ContextVar("agent_memory_scope", default=None)
_exposure: ContextVar[str | None] = ContextVar("agent_memory_exposure", default=None)


def bind_memory_scope(scope: MemoryRequestScope) -> Token:
    """Bind trusted scope and return the token required to restore its predecessor."""
    return _scope.set(scope)


def reset_memory_scope(token: Token) -> None:
    """Restore the prior scope, including after nested invocation or cancellation."""
    _scope.reset(token)


def current_memory_scope() -> MemoryRequestScope | None:
    """Return this execution context's scope without consulting shared agent state."""
    return _scope.get()


def bind_memory_exposure(exposure_id: str | None) -> Token:
    """Bind a runtime-minted final-delivery ID, or clear it for a nested invocation."""
    return _exposure.set(exposure_id)


def reset_memory_exposure(token: Token) -> None:
    """Restore the prior attempt's exposure binding in finally."""
    _exposure.reset(token)


def current_memory_exposure() -> str | None:
    """Return only the final-delivery ID bound in this execution context."""
    return _exposure.get()
