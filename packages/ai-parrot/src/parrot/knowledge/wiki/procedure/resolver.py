"""Deterministic `next` resolution over a procedure graph (FEAT-891). No LLM, no history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from parrot.knowledge.wiki.procedure.models import (
    ProbeCheck,
    ProbeCost,
    ProbeResult,
    ProcedureSpec,
    ResolvedProcedure,
    Resolution,
)


class ProbeRunner(Protocol):
    """Evaluates named probes for a scope."""

    def cost(self, probe: str) -> ProbeCost | None:
        """Return the cost class of a registered probe, or None when unknown."""
        ...

    def run(self, check: ProbeCheck, scope: Mapping[str, str]) -> bool | None:
        """Return whether the check holds, or None when it cannot be decided."""
        ...


def resolve(
    specs: Sequence[ProcedureSpec],
    scope: Mapping[str, str],
    runner: ProbeRunner,
    *,
    allow_remote: bool = True,
    stale: bool = False,
) -> Resolution:
    """Resolve the not-done procedures whose required procedures are complete.

    Args:
        specs: Procedure nodes to resolve.
        scope: Feature, task, and branch values available to probes.
        runner: Probe implementation for the current checkout.
        allow_remote: Whether probes classified as remote may run.
        stale: Whether the procedure index used for this resolution is stale.

    Returns:
        A deterministic resolution ordered with mandatory procedures first.
    """
    by_id = {spec.id: spec for spec in specs}
    done_cache: dict[str, bool | None] = {}

    def result(check: ProbeCheck) -> ProbeResult:
        """Evaluate one check while preserving unknown-probe detail."""
        cost = runner.cost(check.probe)
        if cost is None:
            return ProbeResult(check=check, value=None, cost="remote", detail="unknown probe")
        if cost == "remote" and not allow_remote:
            return ProbeResult(check=check, value=None, cost=cost, detail="remote probes are disabled")

        value = runner.run(check, scope)
        detail = "probe returned unknown" if value is None else ""
        return ProbeResult(check=check, value=value, cost=cost, detail=detail)

    def done(spec: ProcedureSpec) -> bool | None:
        """Return and memoize the tri-state completion value for one node."""
        if spec.id in done_cache:
            return done_cache[spec.id]
        if not spec.done_when:
            value: bool | None = False
        else:
            values = [result(check).value for check in spec.done_when]
            if any(item is False for item in values):
                value = False
            elif all(item is True for item in values):
                value = True
            else:
                value = None
        done_cache[spec.id] = value
        return value

    resolved_next: list[ResolvedProcedure] = []
    for spec in specs:
        completed = done(spec)
        ready = all(required in by_id and done(by_id[required]) is True for required in spec.requires_procedures)
        if spec.mode != "constraint" and completed is not True and ready:
            resolved_next.append(
                ResolvedProcedure(
                    spec=spec,
                    done=completed,
                    ready=ready,
                    preconditions=[result(check) for check in spec.preconditions],
                )
            )

    resolved_next.sort(key=lambda item: (item.spec.mode != "mandatory", item.spec.id))
    mandatory = sorted(
        (spec for spec in specs if spec.mode == "mandatory" and done(spec) is not True),
        key=lambda spec: spec.id,
    )
    return Resolution(scope=dict(scope), stale=stale, next=resolved_next, mandatory=mandatory)
