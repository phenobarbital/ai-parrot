"""Tier policy for the test-scope kernel (FEAT-563). Stdlib only — data, not logic."""

from __future__ import annotations

from dataclasses import dataclass

AGENT_MARKER_EXPRESSION: str = "not e2e and not real_llm and not integration"
AGENT_FLAGS: tuple[str, ...] = ("-q", "--tb=short", "-p", "no:cacheprovider", "-o", "log_cli=false")
DEFAULT_IMPACT_CAP: int = 150
DEFAULT_IMPACT_DEPTH: int = 1
DEFAULT_CORE_FANIN_THRESHOLD: int = 50
CORE_PATHS: tuple[str, ...] = (  # seed; final list written from spike S4 measurement (TASK-3318); always escalate
    "packages/ai-parrot/src/parrot/clients/base.py",  # 182 source importers (measured 2026-09-17)
    "packages/ai-parrot/src/parrot/bots/abstract.py",  # 146 source importers (measured 2026-09-17)
)
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset()  # filled by spike S3 (TASK-3317)
TIERS: tuple[str, ...] = ("task", "merge", "feature")


@dataclass(frozen=True)
class ScopePolicy:
    """Per-tier knobs; defaults are the module constants above."""

    impact_cap: int = DEFAULT_IMPACT_CAP
    impact_depth: int = DEFAULT_IMPACT_DEPTH
    core_fanin_threshold: int = DEFAULT_CORE_FANIN_THRESHOLD
    core_paths: tuple[str, ...] = CORE_PATHS
    xdist_safe: frozenset[str] = XDIST_SAFE_DISTRIBUTIONS
    marker_expression: str = AGENT_MARKER_EXPRESSION
