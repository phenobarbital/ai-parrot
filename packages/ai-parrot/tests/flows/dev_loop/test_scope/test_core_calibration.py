"""Real-index core-detection separation (FEAT-620, spec AC2).

Builds an ImportIndex over the actual checkout, so a regression that only
appears at repo scale -- the saturation that issue:7f2f3d4d7828 reported --
cannot pass the synthetic fixtures in test_impact.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.impact import ImportIndex, detect_core
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy

REPO_ROOT = Path(__file__).resolve().parents[6]

HUBS = (
    "packages/ai-parrot/src/parrot/conf.py",
    "packages/ai-parrot/src/parrot/clients/base.py",
    "packages/ai-parrot/src/parrot/bots/abstract.py",
    "packages/ai-parrot/src/parrot/tools/abstract.py",
)
LEAVES = (
    "packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py",
    "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py",
)


@pytest.fixture(scope="module")
def repo_index() -> ImportIndex:
    """One index over the whole checkout; skipped when the source tree is absent."""
    if not (REPO_ROOT / "packages" / "ai-parrot" / "src").is_dir():
        pytest.skip("not a source workspace (wheel-only install)")
    missing = [p for p in (*HUBS, *LEAVES) if not (REPO_ROOT / p).is_file()]
    if missing:
        pytest.skip(f"measured reference files absent: {missing}")
    return ImportIndex.build(REPO_ROOT)


def test_known_hubs_are_core_by_fanin(repo_index):
    """Each measured hub clears the shipped default threshold on fan-in alone."""
    policy = ScopePolicy(core_paths=())  # exclude the forced path: fan-in must stand alone
    for path in HUBS:
        hits = detect_core(repo_index, [path], policy=policy)
        assert hits, f"{path} must be core by direct fan-in alone"
        assert hits[0].forced is False, f"{path} must not rely on CORE_PATHS"


def test_self_contained_leaves_are_not_core(repo_index):
    """A leaf module must not escalate under the shipped default policy."""
    policy = ScopePolicy(core_paths=())
    for path in LEAVES:
        hits = detect_core(repo_index, [path], policy=policy)
        assert hits == [], f"{path} is a self-contained leaf and must not escalate"
