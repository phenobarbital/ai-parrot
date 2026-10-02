"""Server-managed parameter declarations (FEAT-622 M4).

A toolkit or tool declares ``server_managed_params`` — names the server fills, never the client JSON and never the
LLM. A *constructor* param is one that appears in ``cls.__init__``; every other declared name is a *method* param
(a toolkit method's or a standalone tool's ``_execute`` parameter), filled per call.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, model_validator

ServerParamSource = Literal["server", "app", "tenant", "caller", "agent"]
SCOPE_SOURCES: frozenset[str] = frozenset({"tenant", "caller", "agent"})


class ServerParam(BaseModel, frozen=True):
    """Where the server takes a param's value from; never the client or the LLM."""

    source: ServerParamSource
    key: str | None = None  # app key, required when source == "app"

    @model_validator(mode="after")
    def _app_needs_key(self) -> "ServerParam":
        if self.source == "app" and not self.key:
            raise ValueError("ServerParam(source='app') requires key")
        return self


def _declared(cls: type) -> Mapping[str, ServerParam]:
    return getattr(cls, "server_managed_params", None) or {}


def constructor_server_params(cls: type) -> frozenset[str]:
    """Declared names that are ``cls.__init__`` parameters."""
    declared = _declared(cls)
    if not declared:
        return frozenset()
    ctor = inspect.signature(cls.__init__).parameters
    return frozenset(name for name in declared if name in ctor)


def method_server_params(cls: type) -> dict[str, ServerParam]:
    """Declared names that are NOT constructor parameters (filled per call from the scope)."""
    ctor = constructor_server_params(cls)
    return {name: param for name, param in _declared(cls).items() if name not in ctor}


def validate_server_params(cls: type) -> None:
    """``TypeError`` when a constructor param declares a scope source (instances are shared across callers)."""
    declared = _declared(cls)
    for name in sorted(constructor_server_params(cls)):
        if declared[name].source in SCOPE_SOURCES:
            raise TypeError(
                f"{cls.__name__}.server_managed_params[{name!r}]: a constructor parameter cannot take its value "
                f"from the {declared[name].source!r} scope (instances are shared across callers)"
            )
