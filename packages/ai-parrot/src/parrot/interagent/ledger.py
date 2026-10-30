"""Served-ledger records for inter-agent capability decisions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.interagent.errors import SquawkErrorCode


class CallerIdentity(BaseModel):
    """Identify the peer agent and network that initiated a call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    network: str
    subject: str | None = None
    token_fingerprint: str | None = None


class CallCost(BaseModel):
    """Capture the resource cost of one capability call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = Field(ge=0)
    rows: int | None = None
    bytes: int | None = None
    cost_usd: float | None = None


class ServedLedgerEntry(BaseModel):
    """Represent one signed, append-only record of a capability decision."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    entry_id: str
    created_at: datetime
    caller: CallerIdentity
    cap_id: str
    category: str
    contract_hash: str
    args_digest: str
    policy_applied: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    result_kind: Literal["inline", "artifact", "error"]
    result_digest: str | None = None
    cost: CallCost
    backing: Literal["deterministic", "llm_backed"]
    status: Literal["OK"] | SquawkErrorCode
    trace_id: str
    correlation_id: str | None = None
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Return sorted-key JSON bytes excluding the mutable signature.

        Returns:
            The UTF-8 canonical representation used for signing and verification.
        """
        payload = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
