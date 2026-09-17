"""Directory auto-marking rules (FEAT-563 M10, AC8, R8)."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

# The marking hook, inlined as a string constant (not the whole ai-parrot conftest — it
# imports parrot; pytester isolates the rule from that heavy real conftest).
HOOK_SOURCE = """
from pathlib import Path

import pytest

_DIRECTORY_MARKERS = {"integration": "integration", "e2e": "e2e"}


def pytest_collection_modifyitems(config, items):
    base = Path(__file__).resolve().parent
    for item in items:
        try:
            parts = Path(str(item.path)).resolve().relative_to(base).parts[:-1]
        except ValueError:
            continue
        for segment in parts:
            marker = _DIRECTORY_MARKERS.get(segment)
            if marker:
                item.add_marker(getattr(pytest.mark, marker))
"""


def test_integration_and_e2e_marked_integrations_not(pytester: pytest.Pytester) -> None:
    """`-m integration` / `-m e2e` select by directory; `integrations/` stays unmarked."""
    pytester.makeconftest(HOOK_SOURCE)
    for d in ("integration", "e2e", "integrations", "unit"):
        pytester.mkpydir(d).joinpath(f"test_{d}.py").write_text("def test_ok():\n    assert True\n")
    pytester.runpytest("-m", "integration").assert_outcomes(passed=1)
    pytester.runpytest("-m", "e2e").assert_outcomes(passed=1)
    pytester.runpytest("-m", "not e2e and not integration").assert_outcomes(passed=2)
