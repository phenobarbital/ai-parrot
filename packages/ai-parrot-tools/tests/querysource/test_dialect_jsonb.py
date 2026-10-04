"""FEAT-610 TASK-3841 — JSONB operators in the toolkit dialect (AC2, AC3)."""

from __future__ import annotations

import pytest

from parrot_tools.querysource.dialect import (
    DIALECT_REFERENCE,
    DIALECT_VERIFIED_AGAINST,
    JSONB_OPERATORS,
    validate_filter,
)
from parrot_tools.querysource.errors import InvalidConditionsError


def test_validate_filter_accepts_jsonb_operators() -> None:
    """@> list-of-dict, <@, @>|, ->, and ->> are accepted."""
    assert validate_filter({"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}) == []
    assert validate_filter({"graduation_details": {"<@": {"course": "Pilates Studio"}}}) == []
    assert validate_filter({"graduation_details": {"@>|": ["Pilates Studio"]}}) == []
    assert validate_filter({"graduation_details": {"->": "course"}}) == []
    assert validate_filter({"graduation_details": {"->>": '{"course": "Pilates Studio"}'}}) == []


def test_validate_filter_still_rejects_unknown_operator() -> None:
    """Unknown dict operators remain invalid."""
    with pytest.raises(InvalidConditionsError):
        validate_filter({"col": {"~~": 1}})


def test_dialect_reference_lists_jsonb_operators() -> None:
    """The reference exposes the verified JSONB operator set."""
    assert DIALECT_VERIFIED_AGAINST == "5.1.2"
    assert DIALECT_REFERENCE.operators_jsonb == list(JSONB_OPERATORS)
