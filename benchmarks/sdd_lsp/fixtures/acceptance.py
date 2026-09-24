"""Independently authored expected-evidence and behavior checks (FEAT-580 M5).

Every table and function here is written from the *expected outcome* of a
task, never derived by introspecting
:mod:`benchmarks.sdd_lsp.fixtures.scenarios`'s fixture-construction
internals, so a check cannot pass merely because a fixture happened to be
built a particular way (spec §3 M5: "independent expected-evidence/check
definitions"). Running a behavior check executes the fixture's own bundled
``check.py`` against whatever content currently sits on disk; it never
inspects which arm produced that content, so the same check applies
identically across all five arms (spec §2: "Preserve identical task checks
across all arms").
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks.sdd_lsp.fixtures.scenarios import ScenarioFixture

__all__ = (
    "EXPECTED_DEFINITIONS",
    "SUPPLEMENTARY_TEXT_SEARCH_SCENARIOS",
    "AcceptanceResult",
    "check_definition_answer",
    "requires_supplementary_text_search",
    "run_behavior_check",
)


#: Independently curated expected answers for the four read-only
#: investigation tasks: (repository-relative path, one-based line) of the
#: definition a correct static/semantic tool must report. Authored by hand
#: from the spec's task descriptions and each fixture's narrative, never
#: read back from ``scenarios.py``'s generated trees.
EXPECTED_DEFINITIONS: dict[str, tuple[str, int]] = {
    "inv-duplicate-names": ("pkg/mod_a.py", 1),
    "inv-alias-reexport": ("pkg2/impl.py", 1),
    "inv-namespace-import": ("roots/root_a/nsx/tool.py", 1),
    "inv-inherited-receiver": ("pkg3/base.py", 2),
}

#: Scenarios whose correct resolution cannot rely on static go-to-definition
#: alone -- dynamic namespace-package merging, a decorator-rewritten call
#: target, a string-keyed registry, or a simulated unavailable semantic
#: server -- and therefore require a supplementary text search per the
#: spec's policy ("dynamic/registry tasks require supplementary text
#: search").
SUPPLEMENTARY_TEXT_SEARCH_SCENARIOS: frozenset[str] = frozenset(
    {
        "inv-namespace-import",
        "chg-decorator-wrapper",
        "chg-registry-dispatch",
        "fix-unavailable-server",
    }
)


def requires_supplementary_text_search(scenario_id: str) -> bool:
    """Return whether ``scenario_id`` needs a supplementary text search.

    Args:
        scenario_id: One of :data:`benchmarks.sdd_lsp.fixtures.scenarios.SCENARIO_IDS`.
    """
    return scenario_id in SUPPLEMENTARY_TEXT_SEARCH_SCENARIOS


@dataclass(frozen=True)
class AcceptanceResult:
    """The outcome of one acceptance check.

    Attributes:
        scenario_id: The task this result belongs to.
        passed: Whether the check succeeded.
        reasons: Human-readable failure detail; empty when ``passed``.
    """

    scenario_id: str
    passed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def check_definition_answer(scenario_id: str, submitted_path: str, submitted_line: int) -> AcceptanceResult:
    """Check a submitted (path, line) definition answer against ground truth.

    This is the acceptance procedure for the four read-only investigation
    tasks: correctness is judged against an independently curated answer,
    not against whether any particular tool (LSP or otherwise) was called.

    Args:
        scenario_id: One of :data:`EXPECTED_DEFINITIONS`'s keys.
        submitted_path: The repository-relative path the investigation
            claims is the true definition site.
        submitted_line: The one-based line the investigation claims.

    Returns:
        An :class:`AcceptanceResult`; failure explains the mismatch.

    Raises:
        KeyError: If ``scenario_id`` has no curated expected answer.
    """
    expected_path, expected_line = EXPECTED_DEFINITIONS[scenario_id]
    if (submitted_path, submitted_line) == (expected_path, expected_line):
        return AcceptanceResult(scenario_id=scenario_id, passed=True)
    return AcceptanceResult(
        scenario_id=scenario_id,
        passed=False,
        reasons=(f"expected {expected_path}:{expected_line}, got {submitted_path}:{submitted_line}",),
    )


def run_behavior_check(
    fixture: ScenarioFixture,
    root: Path,
    *,
    timeout_s: float = 10.0,
) -> AcceptanceResult:
    """Run a materialized fixture's bundled ``check.py`` and report the result.

    Args:
        fixture: The scenario whose acceptance script is run.
        root: A directory already materialized via
            :meth:`ScenarioFixture.materialize` (and possibly edited via
            :meth:`ScenarioFixture.apply_variant` or a real attempt).
        timeout_s: Bounded wall-clock budget for the subprocess.

    Returns:
        An :class:`AcceptanceResult` capturing pass/fail and, on failure,
        the check script's captured output.
    """
    check_path = root / fixture.check_relative_path
    if not check_path.exists():
        return AcceptanceResult(
            scenario_id=fixture.scenario_id,
            passed=False,
            reasons=(f"missing acceptance script: {fixture.check_relative_path}",),
        )
    try:
        completed = subprocess.run(
            # -B: never read or write __pycache__/*.pyc. A fixture's entry_point is
            # rewritten in place between variants (baseline/counterexample/expected_fix)
            # by apply_variant(); two variants can land on the same source size within
            # the same mtime second, which would otherwise let Python's default
            # timestamp-based .pyc cache silently serve stale bytecode from a prior
            # variant instead of recompiling the one actually on disk.
            [sys.executable, "-B", str(check_path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return AcceptanceResult(
            scenario_id=fixture.scenario_id,
            passed=False,
            reasons=(f"acceptance script timed out after {timeout_s}s: {exc}",),
        )
    if completed.returncode == 0:
        return AcceptanceResult(scenario_id=fixture.scenario_id, passed=True)
    reasons = tuple(text.strip() for text in (completed.stdout, completed.stderr) if text.strip())
    return AcceptanceResult(scenario_id=fixture.scenario_id, passed=False, reasons=reasons)
