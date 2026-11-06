import pytest

from parrot.knowledge.pageindex.generation import (
    BodyRef,
    GenerationInfo,
    body_sha16,
    ensure_concept_ids,
    flatten_concept_id,
    next_generation,
)


def test_body_ref_roundtrip():
    ref = BodyRef(flat_concept_id="intro", sha16=body_sha16("hello"))
    assert BodyRef.parse(ref.key) == ref


@pytest.mark.parametrize("value", ["bad", "a.XYZ", "a/b.0123456789abcdef"])
def test_body_ref_rejects(value):
    with pytest.raises(ValueError):
        BodyRef.parse(value)


def test_next_generation():
    assert next_generation(None).id == 1
    nxt = next_generation(GenerationInfo(id=4, published_at="2026-01-01T00:00:00Z"))
    assert (nxt.id, nxt.parent) == (5, 4)


def test_ensure_concept_ids_preserves_existing():
    tree = {"structure": [{"title": "A", "concept_id": "keep", "nodes": [{"title": "B"}]}]}
    assert ensure_concept_ids(tree) == 1
    assert tree["structure"][0]["concept_id"] == "keep"
    assert tree["structure"][0]["nodes"][0]["concept_id"]


def test_flatten_matches_okf():
    assert flatten_concept_id("a/b") == "a--b"

