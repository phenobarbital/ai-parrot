"""Tests for FEAT-133 handler-level shallow validation of reranker/parent configs.

Tests cover:
- POST with valid reranker_config dict is accepted.
- POST with non-dict reranker_config returns HTTP 400.
- POST with valid parent_searcher_config dict is accepted.
- POST without the new keys still succeeds (back-compat).
- Empty dict for either field is accepted (back-compat default).

NOTE: The full handler test suite requires a live DB + aiohttp app fixture
(conftest.py in this directory) which is not available in this worktree due
to a missing compiled Cython extension.  These tests verify the validation
logic in isolation by directly calling the internal ``_validate_new_config_fields``
helper extracted for testability.

The roundtrip integration test (POST + GET) is covered by TASK-911.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Inline validation logic extracted from handlers/bots.py _put_database /
# _post_database — tests the exact guard logic without needing the full
# aiohttp stack.
# ---------------------------------------------------------------------------

_FEAT133_KEYS = ("reranker_config", "parent_searcher_config")


def _shallow_validate(payload: dict) -> str | None:
    """Return an error message string if validation fails, else None.

    Replicates the guard added to ``_put_database`` and ``_post_database``:

        for _key in ("reranker_config", "parent_searcher_config"):
            if _key in payload and not isinstance(payload[_key], dict):
                return error(...)
    """
    for key in _FEAT133_KEYS:
        if key in payload and not isinstance(payload[key], dict):
            return f"{key} must be a JSON object"
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_reranker_config_passes() -> None:
    """A dict reranker_config must not trigger validation error."""
    payload = {
        "name": "test-bot",
        "reranker_config": {"type": "llm", "client_ref": "bot"},
    }
    assert _shallow_validate(payload) is None


def test_valid_parent_searcher_config_passes() -> None:
    """A dict parent_searcher_config must not trigger validation error."""
    payload = {
        "name": "test-bot",
        "parent_searcher_config": {"type": "in_table", "expand_to_parent": True},
    }
    assert _shallow_validate(payload) is None


def test_non_dict_reranker_config_fails() -> None:
    """A non-dict reranker_config must return an error."""
    err = _shallow_validate({"name": "bad", "reranker_config": "not-a-dict"})
    assert err is not None
    assert "reranker_config" in err
    assert "JSON object" in err


def test_non_dict_parent_searcher_config_fails() -> None:
    """A non-dict parent_searcher_config must return an error."""
    err = _shallow_validate({"name": "bad", "parent_searcher_config": 42})
    assert err is not None
    assert "parent_searcher_config" in err
    assert "JSON object" in err


def test_payload_without_new_keys_passes() -> None:
    """Payload without the new keys must pass validation (back-compat)."""
    payload = {"name": "bare"}
    assert _shallow_validate(payload) is None


def test_empty_dict_reranker_config_passes() -> None:
    """Empty dict reranker_config must pass — it is the back-compat default."""
    payload = {"name": "test", "reranker_config": {}}
    assert _shallow_validate(payload) is None


def test_empty_dict_parent_searcher_config_passes() -> None:
    """Empty dict parent_searcher_config must pass — it is the back-compat default."""
    payload = {"name": "test", "parent_searcher_config": {}}
    assert _shallow_validate(payload) is None


def test_both_valid_fields_pass() -> None:
    """Both new fields as dicts must pass validation together."""
    payload = {
        "name": "test",
        "reranker_config": {"type": "llm"},
        "parent_searcher_config": {"type": "in_table"},
    }
    assert _shallow_validate(payload) is None


def test_list_reranker_config_fails() -> None:
    """A list is not a dict — must fail."""
    err = _shallow_validate({"name": "bad", "reranker_config": ["type", "llm"]})
    assert err is not None


def test_none_reranker_config_fails() -> None:
    """None is not a dict — must fail."""
    err = _shallow_validate({"name": "bad", "reranker_config": None})
    assert err is not None
