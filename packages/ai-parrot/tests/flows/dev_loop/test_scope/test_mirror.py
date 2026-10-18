"""Parity tests for the moved mirror selector (FEAT-563 M1)."""

import pytest

from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.test_scope import distribution_of
from parrot.flows.dev_loop.test_scope.mirror import pytest_file_target_for, pytest_file_targets


@pytest.fixture
def mirrored(tmp_path):
    """Same layout as test_qa_default_criteria.py `worktree` + `mirrored` fixtures."""
    for pkg in ("ai-parrot", "ai-parrot-tools"):
        (tmp_path / "packages" / pkg / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot-visualizations" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot" / "tests" / "flows" / "dev_loop").mkdir(parents=True)
    (tmp_path / "packages" / "ai-parrot" / "tests" / "loaders").mkdir(parents=True)
    for rel in (
        "packages/ai-parrot/tests/flows/dev_loop/test_qa.py",
        "packages/ai-parrot/tests/test_b.py",
        "packages/ai-parrot-tools/tests/test_a.py",
        "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py",
        "packages/ai-parrot/src/parrot/b.py",
        "packages/ai-parrot-tools/src/parrot_tools/a.py",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    return tmp_path


@pytest.mark.parametrize(
    "files",
    [
        [
            "packages/ai-parrot-tools/src/parrot_tools/a.py",
            "packages/ai-parrot/src/parrot/b.py",
            "scripts/sdd/reserve_ids.py",
        ],
        ["packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py"],
        ["packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py"],
        ["packages/ai-parrot/tests/loaders/test_gone.py"],
        ["packages/ai-parrot-visualizations/src/parrot/outputs/x.py"],
        ["tests/test_missing_root.py"],
    ],
)
def test_mirror_parity_with_qanode_fixtures(mirrored, files):
    got = pytest_file_targets(files, str(mirrored))
    assert got == QANode._pytest_targets(files, str(mirrored))
    if files == ["packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py"]:
        assert got == ["packages/ai-parrot/tests/flows/dev_loop/test_qa.py"]


def test_distribution_of():
    assert distribution_of("packages/ai-parrot/tests/x.py") == "ai-parrot"
    assert distribution_of("tests/sdd_scripts/test_x.py") == "root"
    with pytest.raises(ValueError):
        distribution_of("scripts/sdd/x.py")


def test_file_mirror_uses_first_existing_test_file(tmp_path):
    source = tmp_path / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "dev_loop" / "runner.py"
    source.parent.mkdir(parents=True)
    source.touch()
    shallow = tmp_path / "packages" / "ai-parrot" / "tests" / "flows" / "test_runner.py"
    shallow.parent.mkdir(parents=True)
    shallow.touch()
    deep = tmp_path / "packages" / "ai-parrot" / "tests" / "flows" / "dev_loop" / "test_runner.py"
    deep.parent.mkdir(parents=True)
    deep.touch()

    assert (
        pytest_file_target_for(
            "packages/ai-parrot/src/parrot/flows/dev_loop/runner.py",
            str(tmp_path),
        )
        == "packages/ai-parrot/tests/flows/dev_loop/test_runner.py"
    )


def test_file_mirror_never_returns_directory(tmp_path):
    source = tmp_path / "packages" / "ai-parrot" / "src" / "parrot" / "flows" / "runner.py"
    source.parent.mkdir(parents=True)
    source.touch()
    (tmp_path / "packages" / "ai-parrot" / "tests" / "flows").mkdir(parents=True)

    assert pytest_file_targets(["packages/ai-parrot/src/parrot/flows/runner.py"], str(tmp_path)) == []


def test_file_mirror_maps_existing_test_to_itself(tmp_path):
    package_test = tmp_path / "packages" / "ai-parrot" / "tests" / "flows" / "test_runner.py"
    package_test.parent.mkdir(parents=True)
    package_test.touch()
    root_test = tmp_path / "tests" / "test_scripts.py"
    root_test.parent.mkdir(parents=True)
    root_test.touch()

    files = ["tests/test_scripts.py", "packages/ai-parrot/tests/flows/test_runner.py"]
    assert pytest_file_targets(files, str(tmp_path)) == sorted(files)


@pytest.mark.parametrize(
    "path",
    [
        "packages/ai-parrot/src/parrot/deleted.py",
        "packages/ai-parrot/src/parrot/data.json",
        "packages/ai-parrot/src/parrot/__init__.py",
    ],
)
def test_file_mirror_rejects_deleted_non_python_and_init_files(tmp_path, path):
    assert pytest_file_target_for(path, str(tmp_path)) is None
