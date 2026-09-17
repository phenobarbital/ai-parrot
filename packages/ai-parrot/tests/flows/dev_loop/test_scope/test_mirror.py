"""Parity tests for the moved mirror selector (FEAT-563 M1)."""

import pytest

from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.test_scope import distribution_of, pytest_targets


@pytest.fixture
def mirrored(tmp_path):
    """Same layout as test_qa_default_criteria.py `worktree` + `mirrored` fixtures."""
    for pkg in ("ai-parrot", "ai-parrot-tools"):
        (tmp_path / "packages" / pkg / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot-visualizations" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot" / "tests" / "flows" / "dev_loop").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot" / "tests" / "loaders").mkdir(parents=True)
    return tmp_path


@pytest.mark.parametrize(
    "files",
    [
        ["packages/ai-parrot-tools/src/a.py", "packages/ai-parrot/src/b.py", "scripts/sdd/reserve_ids.py"],
        ["packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py"],
        ["packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py"],
        ["packages/ai-parrot/tests/loaders/test_gone.py"],
        ["packages/ai-parrot-visualizations/src/parrot/outputs/x.py"],
        ["tests/test_missing_root.py"],
    ],
)
def test_mirror_parity_with_qanode_fixtures(mirrored, files):
    assert pytest_targets(files, str(mirrored)) == QANode._pytest_targets(files, str(mirrored))


def test_distribution_of():
    assert distribution_of("packages/ai-parrot/tests/x.py") == "ai-parrot"
    assert distribution_of("tests/sdd_scripts/test_x.py") == "root"
    with pytest.raises(ValueError):
        distribution_of("scripts/sdd/x.py")
