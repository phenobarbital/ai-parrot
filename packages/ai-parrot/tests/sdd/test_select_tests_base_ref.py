"""select_tests._default_base_ref — null-safe base ref (FEAT-830, issue:bfb29d4ffe49)."""

from __future__ import annotations

import pytest

from parrot.sdd.scripts import select_tests


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ({}, "origin/dev"),
        ({"base_branch": None}, "origin/dev"),
        ({"base_branch": "  "}, "origin/dev"),
        ({"base_branch": "staging"}, "origin/staging"),
    ],
)
def test_default_base_ref(header: dict, expected: str) -> None:
    """A missing, null or blank base_branch falls back to origin/dev."""
    assert select_tests._default_base_ref(header) == expected
