#!/usr/bin/env python
"""Code-enforced E2E evidence gate for the SDD closeout surfaces (FEAT-703).

Both ``/sdd-done`` twins (``.claude/commands/sdd-done.md`` and
``.agents/skills/sdd-done/SKILL.md``) invoke this before any stamp, push, PR,
merge or cleanup step. The decision table implemented here is the one proven in
``tests/sdd_scripts/test_e2e_closeout_contract.py`` against the real
``parrot.e2e.evidence.verify_evidence`` validator (FEAT-581 TASK-3543); it was
promoted out of that test file so closeout enforcement is a code invariant
rather than prose an agent is merely asked to follow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import yaml

_VALID_POLICIES = ("required", "optional", "none")
_GATED_POLICIES = ("required", "invalid")


@dataclass
class _GateResult:
    """Duck-compatible stand-in for ``VerificationResult``.

    ``parrot.e2e`` ships from the optional ``ai-parrot-server`` distribution, so
    when it cannot be imported no real ``VerificationResult`` can be built. This
    gives both paths one shape the decision table can read uniformly.
    """

    status: str
    gate_satisfied: bool
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class GateDecision:
    """The full outcome of the closeout gate, including what to report."""

    allowed: bool
    policy: str
    status: str
    gate_satisfied: bool
    reason_codes: list[str]


def resolve_policy(spec_path: Path) -> str:
    """Return the spec's E2E policy, or ``invalid`` when it is malformed.

    A spec with no ``e2e`` key returns ``optional`` (the documented default for
    every spec written before FEAT-581). A present-but-malformed ``policy`` is
    NEVER coerced to a safe default -- it returns ``invalid``, which the gate
    treats exactly like ``required`` with missing evidence.

    Args:
        spec_path: Path to the feature's spec file.

    Returns:
        One of ``required``, ``optional``, ``none`` or ``invalid``.
    """
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError:
        return "optional"

    parts = text.split("---", 2)
    if len(parts) < 3:
        return "optional"

    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return "invalid"
    if not isinstance(front, dict):
        return "optional"

    e2e = front.get("e2e")
    if e2e is None:
        return "optional"
    if not isinstance(e2e, dict):
        return "invalid"

    policy = e2e.get("policy", "optional")
    if policy not in _VALID_POLICIES:
        return "invalid"
    return str(policy)


async def _verify(plan_path: Path, worktree: Path) -> Any:
    """Run the read-only validator, failing closed on absence or error.

    Args:
        plan_path: The feature's ``e2e-plan.md``.
        worktree: The feature worktree the evidence is validated against.

    Returns:
        A ``VerificationResult`` or a duck-compatible :class:`_GateResult`.
    """
    try:
        from parrot.e2e.errors import E2EConfigError, E2EEvidenceError
        from parrot.e2e.evidence import verify_evidence
    except ImportError:
        # ai-parrot-server is not installed: identical to MISSING evidence.
        # Never a traceback, and never read as a pass.
        return _GateResult(status="MISSING", gate_satisfied=False, reason_codes=["e2e_validator_unavailable"])

    try:
        return await verify_evidence(plan_path, worktree=worktree)
    except (E2EEvidenceError, E2EConfigError) as exc:
        # Fails closed exactly like a synthesized BLOCKED VerificationResult:
        # a malformed/tampered/stale evidence blob is never treated as PASS.
        return _GateResult(status="BLOCKED", gate_satisfied=False, reason_codes=[exc.reason_code or "evidence_error"])


async def evaluate_closeout_gate_detailed(*, policy: str, plan_path: Optional[Path], worktree: Path) -> GateDecision:
    """Evaluate the closeout gate and return everything the caller reports.

    Accepts no ``force`` argument by construction: FEAT-581 AC9's "generic force
    cannot bypass required E2E" is structural here, not merely documented.

    Args:
        policy: ``required``, ``optional``, ``none`` or ``invalid``.
        plan_path: The feature's ``e2e-plan.md``, or ``None`` when none exists.
        worktree: The feature worktree to validate evidence against.

    Returns:
        The :class:`GateDecision` describing whether closeout may proceed.
    """
    if policy == "none":
        return GateDecision(
            allowed=True, policy=policy, status="NONE", gate_satisfied=False, reason_codes=["e2e_policy_none"]
        )

    if plan_path is None or not await asyncio.to_thread(plan_path.is_file):
        if policy in _GATED_POLICIES:
            return GateDecision(
                allowed=False,
                policy=policy,
                status="MISSING",
                gate_satisfied=False,
                reason_codes=["e2e_required_missing_plan"],
            )
        return GateDecision(
            allowed=True, policy=policy, status="MISSING", gate_satisfied=False, reason_codes=["e2e_optional_no_plan"]
        )

    result = await _verify(plan_path, worktree)

    if policy in _GATED_POLICIES:
        if result.status == "PASS" and result.gate_satisfied:
            return GateDecision(
                allowed=True,
                policy=policy,
                status=result.status,
                gate_satisfied=result.gate_satisfied,
                reason_codes=["e2e_required_satisfied", *result.reason_codes],
            )
        return GateDecision(
            allowed=False,
            policy=policy,
            status=result.status,
            gate_satisfied=result.gate_satisfied,
            reason_codes=[f"e2e_required_not_satisfied:{result.status}", *result.reason_codes],
        )

    # optional: advisory only, real status always carried through, never
    # upgraded to a pass.
    return GateDecision(
        allowed=True,
        policy=policy,
        status=result.status,
        gate_satisfied=result.gate_satisfied,
        reason_codes=[f"e2e_optional_advisory:{result.status}", *result.reason_codes],
    )


async def evaluate_closeout_gate(*, policy: str, plan_path: Optional[Path], worktree: Path) -> tuple[bool, list[str]]:
    """Return ``(allowed, reason_codes)`` for a feature's E2E closeout gate.

    Thin wrapper over :func:`evaluate_closeout_gate_detailed`. Accepts no
    ``force`` argument by construction (FEAT-581 AC9).

    Args:
        policy: ``required``, ``optional``, ``none`` or ``invalid``.
        plan_path: The feature's ``e2e-plan.md``, or ``None`` when none exists.
        worktree: The feature worktree to validate evidence against.

    Returns:
        ``(allowed, reason_codes)``.
    """
    decision = await evaluate_closeout_gate_detailed(policy=policy, plan_path=plan_path, worktree=worktree)
    return decision.allowed, decision.reason_codes


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Exit 0 when closeout may proceed, 1 when it must abort.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Gate SDD closeout on validated E2E evidence.")
    parser.add_argument("--spec", type=Path, required=True, help="Path to the feature's spec file.")
    parser.add_argument("--feat-id", required=True, help="FEAT-<NNN>, used to locate the plan.")
    parser.add_argument("--worktree", type=Path, required=True, help="Feature worktree to validate against.")
    args = parser.parse_args(argv)

    policy = resolve_policy(args.spec)
    plan_path = args.worktree / "sdd" / "state" / args.feat_id / "e2e-plan.md"
    decision = asyncio.run(evaluate_closeout_gate_detailed(policy=policy, plan_path=plan_path, worktree=args.worktree))

    print(
        json.dumps(
            {
                "policy": decision.policy,
                "status": decision.status,
                "gate_satisfied": decision.gate_satisfied,
                "reason_codes": decision.reason_codes,
                "allowed": decision.allowed,
            }
        )
    )
    return 0 if decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
