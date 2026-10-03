"""Approval token of the host write confirmation (FEAT-622 M8) — split out of ``confirmation.py``.

ToolManager binds the token after a ``confirmed`` guard decision; ``AbstractTool`` consumes it exactly once.
``parrot.auth.confirmation`` re-exports every public name, so import paths are unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

def _args_hash(parameters: dict) -> str:
    from .confirmation import compute_args_hash  # pylint: disable=import-outside-toplevel  (confirmation re-exports us)

    return compute_args_hash(parameters)


_APPROVED_CALL: ContextVar[Optional[tuple[int, str]]] = ContextVar("parrot_approved_tool_call", default=None)


def current_confirmed_call() -> Optional[tuple[int, str]]:
    """``(id(tool), args_hash)`` of the call ToolManager approved, or ``None`` (FEAT-622 M8)."""
    return _APPROVED_CALL.get()


def consume_confirmed_call(tool: Any, parameters: dict) -> bool:
    """True once when the bound token names exactly ``tool`` + ``parameters``; the token is spent (single use)."""
    if _APPROVED_CALL.get() != (id(tool), _args_hash(parameters)):
        return False
    _APPROVED_CALL.set(None)
    return True


@contextmanager
def _approved_call(tool: Any, parameters: dict) -> Iterator[None]:
    """Bind the approval token for exactly one ``tool.execute`` (ToolManager only)."""
    token = _APPROVED_CALL.set((id(tool), _args_hash(parameters)))
    try:
        yield
    finally:
        _APPROVED_CALL.reset(token)


def is_enforced_write_class(cls: type) -> bool:
    """Whether instances of ``cls`` are host write tools whose execution needs an enforced confirmation.

    A standalone host ``AbstractTool`` whose ``access`` is ``"write"`` or undeclared (``None`` is treated as write,
    like host toolkit methods); decided from the class, without instantiating it (FEAT-622 M8).
    """
    from parrot.tools.toolkit import _is_host_class  # pylint: disable=import-outside-toplevel

    if getattr(cls, "access", None) not in (None, "write"):
        return False
    if getattr(cls, "__module__", "").startswith(("parrot.", "parrot_tools.")):
        return False  # framework classes are never host classes: skip the resolver walk
    return _is_host_class(cls)
