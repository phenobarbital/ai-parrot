"""Unit tests for PUT/PATCH edit endpoints and utility functions (TASK-601 / FEAT-086)."""

import pytest
from parrot.formdesigner.handlers.api import _bump_version, _deep_merge


# ---------------------------------------------------------------------------
# _deep_merge utility
# ---------------------------------------------------------------------------

class TestDeepMerge:
    """Tests for RFC 7396 deep merge utility."""

    def test_simple_override(self) -> None:
        """Simple key override works."""
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_add_new_key(self) -> None:
        """New keys from patch are added to base."""
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_nested_merge(self) -> None:
        """Nested dicts are merged recursively."""
        base = {"a": {"b": 1, "c": 2}}
        patch = {"a": {"b": 3}}
        assert _deep_merge(base, patch) == {"a": {"b": 3, "c": 2}}

    def test_null_removes_key(self) -> None:
        """None values in patch remove the key from base."""
        assert _deep_merge({"a": 1, "b": 2}, {"a": None}) == {"b": 2}

    def test_null_removes_nested_key(self) -> None:
        """None values remove nested keys when parent dict is merged."""
        base = {"a": {"b": 1, "c": 2}}
        patch = {"a": {"b": None}}
        assert _deep_merge(base, patch) == {"a": {"c": 2}}

    def test_list_replaces_entirely(self) -> None:
        """Lists are replaced entirely — not merged element-by-element (RFC 7396)."""
        base = {"items": [1, 2, 3]}
        patch = {"items": [4, 5]}
        assert _deep_merge(base, patch) == {"items": [4, 5]}

    def test_empty_patch_returns_base_copy(self) -> None:
        """An empty patch returns a copy of the base."""
        base = {"a": 1, "b": 2}
        result = _deep_merge(base, {})
        assert result == base
        assert result is not base  # must be a copy

    def test_base_is_not_mutated(self) -> None:
        """The original base dict is never mutated."""
        base = {"a": 1}
        _deep_merge(base, {"a": 2})
        assert base["a"] == 1

    def test_deep_nested_merge(self) -> None:
        """Multiple levels of nesting are merged correctly."""
        base = {"x": {"y": {"z": 1, "w": 2}}}
        patch = {"x": {"y": {"z": 99}}}
        assert _deep_merge(base, patch) == {"x": {"y": {"z": 99, "w": 2}}}


# ---------------------------------------------------------------------------
# _bump_version utility
# ---------------------------------------------------------------------------

class TestBumpVersion:
    """Tests for version string incrementing."""

    def test_minor_bump_basic(self) -> None:
        """Basic X.Y → X.(Y+1)."""
        assert _bump_version("1.0") == "1.1"

    def test_minor_bump_non_zero(self) -> None:
        """Higher minor value bumps correctly."""
        assert _bump_version("1.5") == "1.6"

    def test_major_only_gets_minor(self) -> None:
        """Version with only major gets .1 appended."""
        assert _bump_version("1") == "1.1"

    def test_three_part_bumps_last(self) -> None:
        """Three-part version bumps the last component."""
        assert _bump_version("1.2.3") == "1.2.4"

    def test_zero_minor(self) -> None:
        """Zero minor is bumped to 1."""
        assert _bump_version("2.0") == "2.1"

    def test_large_minor(self) -> None:
        """Large minor numbers are bumped correctly."""
        assert _bump_version("3.99") == "3.100"
