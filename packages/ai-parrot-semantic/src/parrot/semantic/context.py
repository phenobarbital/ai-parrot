"""Trusted semantic identity; runtime binding is added separately."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal

from parrot.auth import PermissionContext
from parrot.core.events.lifecycle import TraceContext
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SemanticRequestIdentity(BaseModel, frozen=True):
    """Host-authenticated identity for retained semantic results."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    ctx: PermissionContext
    channel: Literal["http", "agent", "mcp-local"]
    agent_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def snapshot_context(self) -> "SemanticRequestIdentity":
        """Copy trusted request context so later caller mutations cannot alter it."""
        object.__setattr__(self, "ctx", deepcopy(self.ctx))
        if not self.agent_id.strip() or not self.session_id.strip():
            raise ValueError("agent_id and session_id must not be blank")
        return self


SemanticRequestIdentity.model_rebuild(_types_namespace={"TraceContext": TraceContext})
