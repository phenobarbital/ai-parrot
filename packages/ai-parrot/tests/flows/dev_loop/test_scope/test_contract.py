"""Validation-Commands parser + over-broad pytest matrix tests (FEAT-563 M1/M9)."""

import pytest

from parrot.flows.dev_loop.test_scope import is_broad_pytest, parse_validation_commands

TASK_MD = (
    "## Acceptance Criteria\n- [ ] x\n\n## Validation Commands\n\n"
    "- `pytest tests/a.py -q`\n- `pytest tests/b.py::test_x`\n\n"
    "## Test Specification\n- `pytest nope.py`\n"
)


def test_parse_validation_commands():
    assert parse_validation_commands(TASK_MD) == [["pytest", "tests/a.py", "-q"], ["pytest", "tests/b.py::test_x"]]
    assert parse_validation_commands("## Scope\n") == []


@pytest.mark.parametrize(
    "argv,broad",
    [
        (["pytest"], True),
        (["pytest", "-q"], True),
        (["pytest", "."], True),
        (["pytest", "tests"], True),
        (["pytest", "packages/ai-parrot/tests"], True),
        (["pytest", "packages/ai-parrot"], True),
        (["python", "-m", "pytest", "-q"], True),
        (["pytest", "-m", "not e2e", "tests/"], True),
        (["pytest", "tests/sdd_scripts/test_x.py"], False),
        (["pytest", "packages/ai-parrot/tests/flows"], False),
        (["pytest", "tests/a.py::test_b"], False),
        (["ruff", "check", "."], False),
        # Hardening regressions (FEAT-563 review): documented worktree idioms and a
        # space-separated `--maxfail` value used to defeat detection entirely.
        (["PYTHONPATH=packages/ai-parrot/src", "pytest", "tests"], True),
        (["PYTHONPATH=packages/ai-parrot/src", "pytest", "tests/a.py::test_b"], False),
        (["uv", "run", "pytest", "tests"], True),
        (["uv", "run", "--no-sync", "pytest", "tests"], True),
        (["uv", "run", "--no-sync", "pytest", "tests/a.py::test_b"], False),
        (["pytest", "tests", "--maxfail", "1"], True),
        (["pytest", "--maxfail=1", "tests"], True),
    ],
)
def test_is_broad_pytest_matrix(argv, broad):
    assert is_broad_pytest(argv) is broad


def test_absolute_path_to_a_broad_directory_is_recognized_when_worktree_is_known(tmp_path):
    """FEAT-563 review: an absolute operand pointing at the same broad directory as its relative
    form must be recognized too — is_broad_pytest only ever inspected the relative shape."""
    broad_abs = str(tmp_path / "packages" / "ai-parrot" / "tests")
    assert is_broad_pytest(["pytest", broad_abs], worktree=tmp_path) is True
    # narrow (a specific file, or specific node) stays narrow even as an absolute path
    narrow_abs = str(tmp_path / "packages" / "ai-parrot" / "tests" / "test_x.py")
    assert is_broad_pytest(["pytest", narrow_abs], worktree=tmp_path) is False
    assert is_broad_pytest(["pytest", f"{narrow_abs}::test_y"], worktree=tmp_path) is False


def test_absolute_path_outside_the_worktree_is_left_unchanged(tmp_path):
    """An absolute operand that is not under `worktree` at all cannot be relativized; it must not
    be misclassified as broad."""
    outside = "/some/unrelated/path/packages/ai-parrot/tests"
    assert is_broad_pytest(["pytest", outside], worktree=tmp_path) is False


def test_absolute_path_without_a_known_worktree_is_unchanged_narrow_default():
    """Callers with no worktree in scope (worktree=None, the default) keep the pre-fix behavior:
    an absolute operand is never treated as broad."""
    assert is_broad_pytest(["pytest", "/abs/repo/packages/ai-parrot/tests"]) is False
