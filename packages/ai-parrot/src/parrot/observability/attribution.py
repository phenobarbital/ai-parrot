"""UsageAttribution — immutable SDD identity for one dispatched unit of work (FEAT-783 M1)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class UsageAttribution(BaseModel):
    """Immutable SDD attribution for one dispatched unit of work.

    "Seat" is deliberately split into three fields: the codebase gives the word two
    incompatible meanings (roster label ``"a"`` vs accounting seat ``"development.w1"``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    feat_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_uid: Optional[str] = None
    execution_id: Optional[str] = None
    dispatch_kind: Optional[str] = None  # "in-process" | "cli" | "sdk"
    roster_seat: Optional[str] = None  # sdd-coder roster label: "a"/"b"/"c"
    accounting_seat: Optional[str] = None  # observability seat: "development.w1"
