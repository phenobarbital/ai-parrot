"""Frozen, stdlib-only data carriers for the test-scope kernel (FEAT-563)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestTarget:
    """One pytest operand selected for a plan."""

    __test__ = False  # not a pytest test class

    path: str  # repo-relative file, dir or node id
    distribution: str  # "<dist>" or "root"
    reason: str  # "declared" | "mirror" | "import" | "core" | "escalated"


@dataclass(frozen=True)
class PytestInvocation:
    """One pytest command for exactly one distribution."""

    distribution: str
    argv: tuple[str, ...]  # full argv starting with "pytest"
    targets: tuple[TestTarget, ...]


@dataclass(frozen=True)
class CoreHit:
    """A changed core source module that triggers escalation."""

    path: str
    module: str
    fanin: int
    forced: bool
    distributions: tuple[str, ...]


@dataclass(frozen=True)
class ScopePlan:
    """The per-tier selection result."""

    tier: str  # "task" | "merge" | "feature"
    invocations: tuple[PytestInvocation, ...]
    escalated: tuple[str, ...]
    core_hits: tuple[CoreHit, ...]
    skipped_escalations: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class LedgerEntry:
    """Last green escalated run for one distribution."""

    distribution: str
    core_blobs: dict[str, str]  # core file path -> git blob hash


@dataclass(frozen=True)
class AttemptContext:
    """Written by the sdd-coder engine into an attempt's per-worktree git dir."""

    tier: str
    task_id: str
    task_file: str
    base_ref: str
