"""Unit tests for BOE content-hash sealing (FEAT-449 TASK-2492)."""

import hashlib

import pytest
from parrot_tools.legal.boe.hashing import HASH_NORM_VERSION, normalize_for_hash, seal_hash
from parrot_tools.legal.boe.models import ArticleVersion
from parrot_tools.legal.boe.parser import parse_consolidated


def test_normalize_for_hash_nfc_newlines_only():
    assert normalize_for_hash("a\r\nb\rc") == "a\nb\nc"
    assert normalize_for_hash("é") == "é"  # NFC composes
    assert normalize_for_hash("a  b\n") == "a  b\n"  # no collapse, no strip


def test_seal_hash_is_sha256_of_utf8():
    assert seal_hash("hola") == hashlib.sha256("hola".encode()).hexdigest()


def test_article_version_carries_sealed_hash(boe_corpus):
    parsed = parse_consolidated(boe_corpus)
    for art in parsed.articulos:
        for v in art["versions"]:
            if v["text"] is None:
                assert v["content_hash"] is None and v["hash_norm_version"] is None
            else:
                assert v["content_hash"] == seal_hash(v["text"])
                assert v["hash_norm_version"] == HASH_NORM_VERSION


def test_article_version_validator_rejects_partial_hash():
    with pytest.raises(ValueError):
        ArticleVersion(
            n=0,
            text="x",
            valid_from="2020-01-01",
            valid_to=None,
            modified_by=None,
            kind="redaccion",
            source="boe_consolidada",
            derived=False,
            content_hash=None,
            hash_norm_version=1,
        )
