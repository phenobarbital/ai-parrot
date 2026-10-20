"""Frozen, stdlib-only data carriers for the test-scope kernel (FEAT-563)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class TestTarget:
    """One pytest operand selected for a plan."""

    __test__ = False  # not a pytest test class

    path: str  # repo-relative file, dir or node id
    distribution: str  # "<dist>" or "root"
    reason: str  # "declared" | "mirror" | "import" | "core" | "escalated"
    runner: str = "pytest"


@dataclass(frozen=True)
class Invocation:
    """One runner command for exactly one (runner, distribution) group (FEAT-709)."""

    distribution: str
    argv: tuple[str, ...]
    targets: tuple[TestTarget, ...]
    runner: str = "pytest"
    cwd: str = "."
    report_path: str = ""
    report_format: str = "junit"
    timeout_s: int = 0


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
    invocations: tuple[Invocation, ...]
    escalated: tuple[str, ...]
    core_hits: tuple[CoreHit, ...]
    skipped_escalations: tuple[str, ...]
    notes: tuple[str, ...]
    cap_hits: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    cap_impacted: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    mode: str = "fallback"  # "contract" | "fallback" (FEAT-699)
    cached: tuple[str, ...] = ()  # targets dropped by the green cache (FEAT-699)

    def __post_init__(self) -> None:
        """Freeze the mapping fields so the frozen dataclass is truly immutable."""
        for name in ("cap_hits", "cap_impacted"):
            value = getattr(self, name)
            if not isinstance(value, MappingProxyType):
                object.__setattr__(self, name, MappingProxyType(dict(value)))


@dataclass(frozen=True)
class TestContract:
    """Normalized spec-declared validation contract (per-spec index header ``test_contract``, FEAT-699)."""

    __test__ = False  # not a pytest test class

    schema: int  # payload version; only 1 is understood
    tests: tuple[str, ...]  # pytest operands: repo-relative file or file::node
    markers: tuple[str, ...]  # registered marker names, never "real_llm"
    digest: str  # "sha256:<hex>" of the normalized payload


@dataclass(frozen=True)
class GreenCacheEntry:
    """One cached-green test target within a feature (FEAT-699 green cache)."""

    target: str  # repo-relative file or file::node exactly as planned
    key: str  # content key, see green_cache.target_key
    recorded_at: str  # UTC ISO-8601


@dataclass(frozen=True)
class BaselineVerdict:
    """Classification of one failed node id against origin/<base_branch> (FEAT-699)."""

    nodeid: str
    status: str  # "new_red" | "baseline_red" | "unknown" | "flaky"
    detail: str = ""


@dataclass(frozen=True)
class RunReport:
    """Normalized outcome of one Invocation, whatever its runner."""

    runner: str
    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    exit_code: int
    status: str
    nodes: tuple[tuple[str, str], ...] = ()
    failure_text: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    unmapped: int = 0

    def __post_init__(self) -> None:
        """Freeze ``failure_text``."""
        if not isinstance(self.failure_text, MappingProxyType):
            object.__setattr__(self, "failure_text", MappingProxyType(dict(self.failure_text)))


@dataclass(frozen=True)
class Failure:
    """One failed node as a seat sees it."""

    runner: str
    nodeid: str
    verdict: str
    excerpt: str


@dataclass(frozen=True)
class RunnerSummary:
    """Per-invocation counts inside a verdict."""

    runner: str
    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    cached: int
    duration_s: float
    exit_code: int
    status: str


@dataclass(frozen=True)
class ValidationVerdict:
    """The only validation payload a coder seat ever receives (FEAT-709)."""

    schema: int
    status: str
    tier: str
    runners: tuple[RunnerSummary, ...]
    failures: tuple[Failure, ...]
    cached: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class LedgerEntry:
    """Last green escalated run for one distribution."""

    distribution: str
    core_blobs: dict[str, str]  # core file path -> git blob hash
    impact_blobs: dict[str, str] = field(default_factory=dict)
    impacted_hash: str = ""


@dataclass(frozen=True)
class AttemptContext:
    """Written by the sdd-coder engine into an attempt's per-worktree git dir."""

    tier: str
    task_id: str
    task_file: str
    base_ref: str
