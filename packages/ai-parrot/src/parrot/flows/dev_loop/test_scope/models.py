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
    reason: Literal["declared", "contract", "mirror", "import", "core", "escalated"]


class InvocationModel(BaseModel):
    """One per-distribution runner invocation."""

    distribution: str
    argv: list[str]
    targets: list[TestTargetModel]
    runner: str = "pytest"
    cwd: str = "."
    report_path: str = ""
    report_format: str = "junit"
    timeout_s: int = 0


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
    invocations: list[InvocationModel]
    escalated: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    core_hits: list[CoreHitModel] = Field(default_factory=list)
    skipped_escalations: list[str] = Field(default_factory=list)
    cap_hits: dict[str, list[str]] = Field(default_factory=dict)
    cap_impacted: dict[str, str] = Field(default_factory=dict)
    mode: str = "fallback"
    cached: list[str] = Field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: ScopePlan) -> "ScopePlanModel":
        """Convert the stdlib dataclass plan into its Pydantic mirror."""
        return cls(
            tier=plan.tier,
            invocations=[
                InvocationModel(
                    distribution=inv.distribution,
                    argv=list(inv.argv),
                    targets=[
                        TestTargetModel(path=t.path, distribution=t.distribution, reason=t.reason) for t in inv.targets
                    ],
                    runner=inv.runner,
                    cwd=inv.cwd,
                    report_path=inv.report_path,
                    report_format=inv.report_format,
                    timeout_s=inv.timeout_s,
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
            cap_hits={key: list(value) for key, value in plan.cap_hits.items()},
            cap_impacted=dict(plan.cap_impacted),
            mode=plan.mode,
            cached=list(plan.cached),
        )
