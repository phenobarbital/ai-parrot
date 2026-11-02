"""Provenance carried by every artifact handle."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HandleProvenance(BaseModel):
    """Describe who produced artifact bytes and under which contract and policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    serving_agent: str
    cap_id: str
    contract_hash: str
    args_digest: str
    policy_applied: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    backing: Literal["deterministic", "llm_backed"]
    produced_at: datetime
    trace_id: str
    derived_from: tuple[str, ...] = Field(default_factory=tuple)
