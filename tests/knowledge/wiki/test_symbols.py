"""Tests for the FEAT-498 symbol plane models and id grammar."""

from __future__ import annotations

import hashlib

import pytest
from parrot.knowledge.wiki.symbols import (
    StructuralOutline,
    SymbolKind,
    SymbolRecord,
    SymbolRef,
    parse_sym_id,
    sha1_of_text,
    sym_concept_id,
)
from pydantic import ValidationError


def test_sym_id_plain_and_ordinal():
    assert sym_concept_id("a/b.py", "Cls.m") == "sym:a/b.py#Cls.m"
    assert sym_concept_id("a/b.py", "Cls.m", 2) == "sym:a/b.py#Cls.m~2"
    assert parse_sym_id("sym:a/b.py#Cls.m~3") == ("a/b.py", "Cls.m", 3)
    assert parse_sym_id(
        "sym:src/App/User.php#App\\Models\\User::getFullName"
    ) == ("src/App/User.php", "App\\Models\\User::getFullName", 1)


def test_sym_id_ordinal_one_has_no_tilde():
    assert "~" not in sym_concept_id("a/b.py", "X", ordinal=1)


def test_parse_sym_id_requires_prefix():
    with pytest.raises(ValueError):
        parse_sym_id("file:a/b.py")


def test_parse_sym_id_requires_hash():
    with pytest.raises(ValueError):
        parse_sym_id("sym:a/b.py")


def test_sha1_of_text_matches_hashlib():
    assert sha1_of_text("x") == hashlib.sha1(b"x").hexdigest()


def test_record_defaults():
    r = SymbolRecord(
        rel_path="a.py",
        language="python",
        kind=SymbolKind.FUNCTION,
        name="f",
        qualname="f",
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=10,
        content_hash="deadbeef",
    )
    assert r.depth == 1
    assert r.decorators == []
    assert r.exported is False
    assert r.is_async is False
    assert r.parent is None


def test_symbol_ref_rel_literal():
    ref = SymbolRef(src_qualname="f", rel="calls", target_text="g", line=1)
    assert ref.rel == "calls"
    with pytest.raises(ValidationError):
        SymbolRef(src_qualname="f", rel="not-a-rel", target_text="g", line=1)


def test_structural_outline_defaults():
    outline = StructuralOutline()
    assert outline.summary == ""
    assert outline.symbols == []
    assert outline.refs == []
    assert outline.imports == []


class TestSymConceptIdOrdinalRoundtrip:
    """Ensure a wide range of qualnames used across the five languages
    round-trip through sym_concept_id / parse_sym_id."""

    @pytest.mark.parametrize(
        "rel_path,qualname,ordinal",
        [
            ("a/b.py", "Cls.method", 1),
            ("a/b.py", "Cls.method", 2),
            ("src/App/User.php", "App\\Models\\User::getFullName", 1),
            ("src/parser.rs", "Parser::new", 1),
            ("src/parser.rs", "Parser::new", 5),
            ("lib/Foo.pm", "Foo::bar", 1),
        ],
    )
    def test_roundtrip(self, rel_path, qualname, ordinal):
        cid = sym_concept_id(rel_path, qualname, ordinal)
        assert parse_sym_id(cid) == (rel_path, qualname, ordinal)
