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
    ],
)
def test_is_broad_pytest_matrix(argv, broad):
    assert is_broad_pytest(argv) is broad
