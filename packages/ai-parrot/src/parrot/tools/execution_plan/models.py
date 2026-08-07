"""Toolkit-internal models for ``ExecutionPlanToolkit``.

``RunRecord``/``RunningSummary`` are the run-registry data models (spec
§2 Data Models). The live ``asyncio.Task``/``AgentsFlow`` handle for a run
is deliberately NOT a field here — it stays out-of-band in the toolkit's
own internal dict so this model stays a plain, ``extra="forbid"``
serializable record.

Tool-argument schemas (``PlanStatusArgs``, ``PlanArtifactsArgs``) follow the
repo's ``AbstractToolArgsSchema`` convention (see
``.agent/workflows/create-parrot-tool.md``). ``PlanExecuteArgs`` /
``PlanValidateArgs`` are added by TASK-2184, not here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..abstract import AbstractToolArgsSchema
from parrot.bots.flows.plan import ExecutionManifest

__all__ = (
    "PlanArtifactsArgs",
    "PlanStatusArgs",
    "RunRecord",
    "RunningSummary",
)


class RunRecord(BaseModel):
    """Registry entry for one plan run (toolkit-internal).

    Attributes:
        run_id: Short unique id, e.g. ``"run_ab12cd"``.
        plan_name: The executed plan's ``name``.
        source: Which acquisition mode produced the plan.
        status: Current run status.
        started_at: When the run's background task was created.
        finished_at: When the run reached a terminal status, if it has.
        manifest: The final :class:`ExecutionManifest`, set on completion.
        nodes_total: Total plan nodes (bound for progress reporting).
        nodes_done: Nodes that have reached a terminal per-node status
            (``ok``/``skipped``/``partial``/``error``) so far.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    plan_name: str
    source: Literal["objective", "plan_name"]
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: Optional[datetime] = None
    manifest: Optional[ExecutionManifest] = None
    nodes_total: int
    nodes_done: int = 0


class RunningSummary(BaseModel):
    """What ``plan_execute`` returns when ``soft_timeout`` elapses first."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["running"] = "running"
    plan_name: str
    nodes_total: int
    nodes_done: int
    hint: str = "poll plan_status(run_id)"


class PlanStatusArgs(AbstractToolArgsSchema):
    """Arguments for the ``plan_status`` tool."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Run id returned by plan_execute.")


class PlanArtifactsArgs(AbstractToolArgsSchema):
    """Arguments for the ``plan_artifacts`` tool."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Run id returned by plan_execute.")
