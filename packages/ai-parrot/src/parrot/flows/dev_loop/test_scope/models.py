"""Pydantic boundary models for the test-scope kernel (FEAT-563). The ONLY kernel module importing pydantic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .datatypes import ScopePlan


class TestTargetModel(BaseModel):
    """One selected test path and why it was selected."""

    __test__ = False  # not a pytest test class
    path: str
    distribution: str
    reason: Literal["declared", "mirror", "import", "core", "escalated"]


class PytestInvocationModel(BaseModel):
    """One per-distribution pytest invocation."""

    distribution: str
    argv: list[str]
    targets: list[TestTargetModel]


class CoreHitModel(BaseModel):
    """A changed core module that triggered escalation."""

    path: str
    module: str
    fanin: int
    forced: bool
    distributions: list[str]


class ScopePlanModel(BaseModel):
    """JSON-serialisable mirror of `ScopePlan`."""

    tier: Literal["task", "merge", "feature"]
    invocations: list[PytestInvocationModel]
    escalated: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    core_hits: list[CoreHitModel] = Field(default_factory=list)
    skipped_escalations: list[str] = Field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: ScopePlan) -> "ScopePlanModel":
        """Convert the stdlib dataclass plan into its Pydantic mirror."""
        return cls(
            tier=plan.tier,
            invocations=[
                PytestInvocationModel(
                    distribution=inv.distribution,
                    argv=list(inv.argv),
                    targets=[
                        TestTargetModel(path=t.path, distribution=t.distribution, reason=t.reason) for t in inv.targets
                    ],
                )
                for inv in plan.invocations
            ],
            escalated=list(plan.escalated),
            notes=list(plan.notes),
            core_hits=[
                CoreHitModel(
                    path=hit.path,
                    module=hit.module,
                    fanin=hit.fanin,
                    forced=hit.forced,
                    distributions=list(hit.distributions),
                )
                for hit in plan.core_hits
            ],
            skipped_escalations=list(plan.skipped_escalations),
        )
