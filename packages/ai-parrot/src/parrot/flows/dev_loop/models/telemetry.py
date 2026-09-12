"""Per-attempt telemetry transport for coding-agent dispatch loops (FEAT-554).

These models travel from `LLMCodeDispatcher` to the bound session host through
an explicit hook, NOT through a `dispatch.completed` payload: that path copies
only seven whitelisted scalars into the closed `DispatchCompleted` model and
swallows validation failures by design (`dispatchers/_shared.py:118-124`), so
extra keys would be dropped in silence (spec §10 R3).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

MAX_TURN_SERIES: int = 101
"""Every turn a loop can possibly produce.

`LLMCodeDispatchProfile.max_turns` is capped at 100 (verified:
parrot/flows/dev_loop/models/llm.py:23) plus the one post-loop salvage call
(verified: parrot/flows/dev_loop/dispatchers/llm.py:552). Sized to never
truncate a real series rather than as a size heuristic; the persisted line
budget in `sdd_coder/telemetry.py` is sized to fit it.
"""


class TurnUsage(BaseModel):
    """One turn's reported usage inside a coding-agent loop.

    Token fields are nullable because `_extract_usage` returns ``None`` when a
    provider reports no usage for a round (verified:
    parrot/flows/dev_loop/dispatchers/llm.py:1089) and the loop continues. A
    ``None`` here is a KNOWN GAP, never a zero: it is counted in
    `AttemptTelemetry.turns_with_unknown_usage` and makes the attempt
    ineligible as a calibration sample (spec §10 R5-R6).
    """

    round_number: int = Field(..., ge=1)
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)


class AttemptTelemetry(BaseModel):
    """Terminal telemetry for ONE dispatch attempt — success, failure or salvage."""

    resolved_model: str = Field("", max_length=200)
    turns: int = Field(0, ge=0)
    terminal: Literal["completed", "failed", "salvaged"] = "completed"
    error_class: str = Field("", max_length=120)
    provider_input_tokens: Optional[int] = Field(None, ge=0)
    provider_output_tokens: Optional[int] = Field(None, ge=0)
    turn_series: List[TurnUsage] = Field(default_factory=list, max_length=MAX_TURN_SERIES)
    turns_with_unknown_usage: int = Field(0, ge=0)
    budget_report: Optional[Dict[str, Any]] = None
    """`BudgetReport.model_dump()` when an observational ledger was bound, else None."""
