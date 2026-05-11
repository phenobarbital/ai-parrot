"""Tests for OntologyCache.build_key extended with resolved_entities (FEAT-158).

Verifies both backwards-compatible (no resolved_entities arg) and
new key shapes for cross-target isolation.
"""
from parrot.knowledge.ontology.cache import OntologyCache


class TestBuildKey:
    """Tests for OntologyCache.build_key signature extension."""

    def test_backwards_compatible_shape(self) -> None:
        """Calling without resolved_entities produces the legacy key shape."""
        k = OntologyCache.build_key("t1", "u1", "team")
        assert k.endswith(":t1:u1:team")

    def test_prefix_present(self) -> None:
        """Key starts with the configured (or default) prefix."""
        k = OntologyCache.build_key("t1", "u1", "team")
        # Default prefix is 'parrot:ontology'
        assert "parrot:ontology" in k

    def test_empty_entities_matches_no_arg(self) -> None:
        """Passing resolved_entities={} produces the same key as no arg."""
        assert OntologyCache.build_key("t1", "u1", "team") == \
               OntologyCache.build_key("t1", "u1", "team", resolved_entities={})

    def test_none_entities_matches_no_arg(self) -> None:
        """Passing resolved_entities=None produces the same key as no arg."""
        assert OntologyCache.build_key("t1", "u1", "team") == \
               OntologyCache.build_key("t1", "u1", "team", resolved_entities=None)

    def test_deterministic_sort(self) -> None:
        """Keys are identical regardless of dict insertion order."""
        k1 = OntologyCache.build_key(
            "t1", "u1", "team",
            resolved_entities={"a": "1", "b": "2"},
        )
        k2 = OntologyCache.build_key(
            "t1", "u1", "team",
            resolved_entities={"b": "2", "a": "1"},
        )
        assert k1 == k2

    def test_different_entities_distinct_keys(self) -> None:
        """Different resolved entity values produce distinct cache keys."""
        k1 = OntologyCache.build_key(
            "t1", "u1", "team",
            resolved_entities={"target": "Emp/1"},
        )
        k2 = OntologyCache.build_key(
            "t1", "u1", "team",
            resolved_entities={"target": "Emp/2"},
        )
        assert k1 != k2

    def test_entity_suffix_format(self) -> None:
        """Entity suffix is appended as ':e={k}={v},...' after base key."""
        k = OntologyCache.build_key(
            "t1", "u1", "team",
            resolved_entities={"target": "Emp/42"},
        )
        assert ":e=target=Emp/42" in k

    def test_multiple_entities_sorted_suffix(self) -> None:
        """Multiple entities are joined sorted by key."""
        k = OntologyCache.build_key(
            "t1", "u1", "team",
            resolved_entities={"z_rule": "Emp/99", "a_rule": "Emp/1"},
        )
        # Sorted: a_rule comes before z_rule
        assert "a_rule=Emp/1,z_rule=Emp/99" in k

    def test_different_users_distinct_keys(self) -> None:
        """Different user_ids produce distinct cache keys (existing behavior)."""
        k1 = OntologyCache.build_key("t1", "u1", "team")
        k2 = OntologyCache.build_key("t1", "u2", "team")
        assert k1 != k2

    def test_different_tenants_distinct_keys(self) -> None:
        """Different tenant_ids produce distinct cache keys (existing behavior)."""
        k1 = OntologyCache.build_key("t1", "u1", "team")
        k2 = OntologyCache.build_key("t2", "u1", "team")
        assert k1 != k2
