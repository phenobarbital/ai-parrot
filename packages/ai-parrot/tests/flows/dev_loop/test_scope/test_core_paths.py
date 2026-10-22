"""Guards on the regenerated CORE_PATHS (FEAT-620, spec AC4/AC5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.impact import ImportIndex, detect_core, module_aliases, module_name_for
from parrot.flows.dev_loop.test_scope.policy import CORE_PATHS, ScopePolicy

REPO_ROOT = Path(__file__).resolve().parents[6]

# `parrot/tools/<x>.py` and `parrot_tools/<x>.py` are the same module through the
# sys.meta_path redirect, so the generator retains both halves of a pair when either
# clears the threshold. The partner may therefore sit below it.
_ALIAS_PREFIXES = (
    "packages/ai-parrot/src/parrot/tools/",
    "packages/ai-parrot-tools/src/parrot_tools/",
)


def _is_alias_half(path: str) -> bool:
    return path.startswith(_ALIAS_PREFIXES)


@pytest.fixture(scope="module")
def repo_index() -> ImportIndex:
    """One index over the whole checkout; skipped when the source tree is absent."""
    if not (REPO_ROOT / "packages" / "ai-parrot" / "src").is_dir():
        pytest.skip("not a source workspace (wheel-only install)")
    return ImportIndex.build(REPO_ROOT)


def test_every_core_path_exists():
    """A CORE_PATHS entry naming a deleted file silently escalates nothing (AC4)."""
    if not (REPO_ROOT / "packages" / "ai-parrot" / "src").is_dir():
        pytest.skip("not a source workspace (wheel-only install)")
    missing = [p for p in CORE_PATHS if not (REPO_ROOT / p).is_file()]
    assert missing == []


def test_every_core_path_has_importers(repo_index):
    """A module nothing imports cannot be core — the old 724-entry list had several (AC4)."""
    zero: list[str] = []
    for path in CORE_PATHS:
        module = module_name_for(path)
        assert module is not None, f"{path} is not a recognisable source module"
        importers: set[str] = set()
        for alias in module_aliases(module):
            importers |= repo_index.src_importers.get(alias, set())
        importers.discard(module)
        if not importers and not _is_alias_half(path):
            zero.append(path)
    assert zero == []


def test_forced_escalation_still_fires(tmp_path):
    """`forced` is independent of fan-in; only the list shrank (AC5)."""
    src = tmp_path / "packages" / "z" / "src" / "pz"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "lonely.py").write_text("X = 1\n")  # nothing imports it: fan-in 0
    index = ImportIndex.build(tmp_path)
    target = "packages/z/src/pz/lonely.py"
    hits = detect_core(index, [target], policy=ScopePolicy(core_fanin_threshold=999, core_paths=(target,)))
    assert len(hits) == 1
    assert hits[0].forced is True
    assert hits[0].fanin == 0
