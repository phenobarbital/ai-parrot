"""Unit tests for the knowledge:// URI scheme module (FEAT-239).

Tests verify:
- build_uri() produces correct knowledge:// URIs.
- parse_uri() correctly parses knowledge:// URIs.
- parse_uri() handles legacy pageindex:// URIs.
- parse_uri() raises ValueError for unrecognised schemes.
- Round-trip invariant: parse_uri(build_uri(t, i)) == (t, i).
"""

import pytest

from parrot.knowledge.okf.uri import build_uri, parse_uri


class TestBuildUri:
    """Tests for build_uri()."""

    def test_basic(self) -> None:
        """build_uri() produces correct knowledge:// URI."""
        assert build_uri("graphindex", "node-1") == "knowledge://graphindex/node-1"

    def test_with_slashes_in_identifier(self) -> None:
        """build_uri() accepts identifiers containing slashes."""
        assert build_uri("pageindex", "tree/concept") == "knowledge://pageindex/tree/concept"

    def test_empty_index_type_raises(self) -> None:
        """build_uri() raises ValueError for empty index_type."""
        with pytest.raises(ValueError, match="index_type"):
            build_uri("", "node-1")

    def test_empty_identifier_raises(self) -> None:
        """build_uri() raises ValueError for empty identifier."""
        with pytest.raises(ValueError, match="identifier"):
            build_uri("graphindex", "")

    def test_various_index_types(self) -> None:
        """build_uri() works for different index namespaces."""
        assert build_uri("graphindex", "sym-abc") == "knowledge://graphindex/sym-abc"
        assert build_uri("pageindex", "docs/readme") == "knowledge://pageindex/docs/readme"


class TestParseUri:
    """Tests for parse_uri()."""

    def test_knowledge_scheme_simple(self) -> None:
        """parse_uri() parses a simple knowledge:// URI."""
        assert parse_uri("knowledge://graphindex/node-1") == ("graphindex", "node-1")

    def test_knowledge_scheme_nested_id(self) -> None:
        """parse_uri() handles identifiers with slashes."""
        assert parse_uri("knowledge://pageindex/tree/concept") == ("pageindex", "tree/concept")

    def test_legacy_pageindex_scheme(self) -> None:
        """parse_uri() maps pageindex:// URIs to ('pageindex', rest)."""
        assert parse_uri("pageindex://my-tree/my-node") == ("pageindex", "my-tree/my-node")

    def test_legacy_pageindex_with_nested_path(self) -> None:
        """parse_uri() preserves full path for legacy pageindex:// URIs."""
        assert parse_uri("pageindex://tree/deep/node") == ("pageindex", "tree/deep/node")

    def test_unknown_scheme_raises(self) -> None:
        """parse_uri() raises ValueError for unrecognised schemes."""
        with pytest.raises(ValueError, match="Unrecognised URI scheme"):
            parse_uri("http://example.com")

    def test_ftp_scheme_raises(self) -> None:
        """parse_uri() raises ValueError for ftp:// scheme."""
        with pytest.raises(ValueError, match="Unrecognised URI scheme"):
            parse_uri("ftp://example.com/file")

    def test_no_scheme_raises(self) -> None:
        """parse_uri() raises ValueError when no :// separator is found."""
        with pytest.raises(ValueError):
            parse_uri("garbage-no-scheme")

    def test_malformed_knowledge_uri_no_identifier(self) -> None:
        """parse_uri() raises ValueError when knowledge:// URI lacks identifier."""
        with pytest.raises(ValueError, match="Malformed"):
            parse_uri("knowledge://graphindex/")

    def test_malformed_knowledge_uri_empty_index_type(self) -> None:
        """parse_uri() raises ValueError when knowledge:// URI has empty index_type."""
        with pytest.raises(ValueError, match="Malformed"):
            parse_uri("knowledge:///node-1")


class TestRoundTrip:
    """Round-trip invariant tests."""

    def test_graphindex_round_trip(self) -> None:
        """build_uri → parse_uri → original (index_type, identifier)."""
        uri = build_uri("graphindex", "sym-builder-abc")
        idx_type, identifier = parse_uri(uri)
        assert idx_type == "graphindex"
        assert identifier == "sym-builder-abc"

    def test_pageindex_round_trip(self) -> None:
        """build_uri → parse_uri for pageindex namespace."""
        uri = build_uri("pageindex", "tree/concept-id")
        idx_type, identifier = parse_uri(uri)
        assert idx_type == "pageindex"
        assert identifier == "tree/concept-id"

    def test_build_parse_build_identity(self) -> None:
        """build_uri(parse_uri(build_uri(t,i))) == build_uri(t,i)."""
        original = build_uri("graphindex", "x")
        parsed = parse_uri(original)
        rebuilt = build_uri(*parsed)
        assert original == rebuilt
