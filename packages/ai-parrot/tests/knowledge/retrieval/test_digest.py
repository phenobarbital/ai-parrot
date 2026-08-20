"""Tests for TASK-2273: `DigestScope` + derived digest computation.

Spec: sdd/specs/graphindex-retriever.spec.md §3.5.1.
"""

from pathlib import Path

import pytest
from parrot.knowledge.graphindex.schema import NodeKind, Provenance, UniversalNode
from parrot.knowledge.retrieval.digest import DigestScope, derive_digest

_SOURCE = (
    b"line one\n"
    b"line two\n"
    b"class Foo:\n"
    b"    def bar(self):\n"
    b"        return 1\n"
    b"trailing line\n"
)


def _class_node(**domain_tags_overrides: object) -> UniversalNode:
    domain_tags = {"symbol_type": "class", "lineno": 3, "end_lineno": 5}
    domain_tags.update(domain_tags_overrides)
    return UniversalNode(
        node_id="mod::Foo",
        kind=NodeKind.SYMBOL,
        title="Foo",
        source_uri="parrot/example.py",
        domain_tags=domain_tags,
    )


def _rationale_node() -> UniversalNode:
    return UniversalNode(
        node_id="mod::__rationale__0",
        kind=NodeKind.RATIONALE,
        title="WHY: something",
        source_uri="parrot/example.py",
        summary="something",
        domain_tags={"tag": "WHY"},
        provenance=Provenance.EXTRACTED,
    )


def _concept_node() -> UniversalNode:
    return UniversalNode(
        node_id="concept::foo",
        kind=NodeKind.CONCEPT,
        title="Foo concept",
        source_uri="concept://foo",
        summary="A concept with no backing file.",
    )


def test_span_digest_sensitive_to_inside_edit() -> None:
    node = _class_node()
    digest_a, scope_a = derive_digest(node, source_bytes=_SOURCE, file_sha1="filesha1")
    assert scope_a == DigestScope.SPAN

    mutated = _SOURCE.replace(b"        return 1\n", b"        return 2\n")
    digest_b, scope_b = derive_digest(node, source_bytes=mutated, file_sha1="filesha1")
    assert scope_b == DigestScope.SPAN
    assert digest_a != digest_b


def test_span_digest_insensitive_to_outside_edit() -> None:
    node = _class_node()
    digest_a, _ = derive_digest(node, source_bytes=_SOURCE, file_sha1="filesha1")

    mutated = _SOURCE.replace(b"trailing line\n", b"a totally different trailing line\n")
    digest_b, _ = derive_digest(node, source_bytes=mutated, file_sha1="filesha1")
    assert digest_a == digest_b


def test_rationale_node_falls_back_to_file_scope() -> None:
    node = _rationale_node()
    # RATIONALE nodes never carry lineno/end_lineno (code.py:500) — must not
    # raise, and must resolve to FILE scope using the caller-supplied sha1.
    digest, scope = derive_digest(node, source_bytes=_SOURCE, file_sha1="filesha1abc")
    assert scope == DigestScope.FILE
    assert digest == "filesha1abc"


def test_concept_node_uses_summary_scope() -> None:
    node = _concept_node()
    digest, scope = derive_digest(node, source_bytes=None, file_sha1=None)
    assert scope == DigestScope.SUMMARY
    assert isinstance(digest, str) and len(digest) == 64  # sha256 hex digest


def test_summary_digest_changes_with_summary_text() -> None:
    node_a = _concept_node()
    node_b = UniversalNode(
        node_id="concept::foo",
        kind=NodeKind.CONCEPT,
        title="Foo concept",
        source_uri="concept://foo",
        summary="A different summary.",
    )
    digest_a, _ = derive_digest(node_a, source_bytes=None, file_sha1=None)
    digest_b, _ = derive_digest(node_b, source_bytes=None, file_sha1=None)
    assert digest_a != digest_b


def test_derive_digest_does_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("derive_digest must not perform I/O")

    monkeypatch.setattr("builtins.open", _raise)
    monkeypatch.setattr(Path, "read_bytes", _raise)
    monkeypatch.setattr(Path, "read_text", _raise)

    node = _class_node()
    digest, scope = derive_digest(node, source_bytes=_SOURCE, file_sha1="filesha1")
    assert scope == DigestScope.SPAN
    assert digest

    _rationale_digest, rationale_scope = derive_digest(
        _rationale_node(), source_bytes=None, file_sha1="filesha1"
    )
    assert rationale_scope == DigestScope.FILE

    _concept_digest, concept_scope = derive_digest(
        _concept_node(), source_bytes=None, file_sha1=None
    )
    assert concept_scope == DigestScope.SUMMARY
