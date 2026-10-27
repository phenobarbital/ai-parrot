"""Regression contract: Vendored Ossie 0.1.1 validation (M4 import boundary)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.ossie import OSSIE_SPEC_VERSION, is_ossie_document, validate_ossie_document

FIXTURE = Path(__file__).parent / "fixtures" / "ossie" / "orders.ossie.json"


def test_official_fixture_and_version(tmp_path: Path) -> None:
    """Validate the fixture and reject a different declared Ossie version."""
    fixture_copy = tmp_path / FIXTURE.name
    fixture_copy.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    document = json.loads(fixture_copy.read_text(encoding="utf-8"))

    assert OSSIE_SPEC_VERSION == "0.1.1"
    assert is_ossie_document(document)
    assert is_ossie_document({"version": "0.2.0", "semantic_model": []})
    assert is_ossie_document({"version": 1})
    assert not is_ossie_document({"models": []})
    assert document["semantic_model"][0]["datasets"][0]["fields"]
    assert "orders.amount" in document["semantic_model"][0]["metrics"][0]["expression"]["dialects"][0]["expression"]
    validate_ossie_document(document)

    wrong_version = dict(document, version="0.2.0")
    with pytest.raises(SemanticPolicyError) as exc_info:
        validate_ossie_document(wrong_version)

    assert exc_info.value.code == "ossie_version"
    assert exc_info.value.details == {"expected": "0.1.1", "actual": "0.2.0"}


def test_invalid_document_reports_path(tmp_path: Path) -> None:
    """Report the deterministic path of the first schema validation error."""
    fixture_copy = tmp_path / FIXTURE.name
    fixture_copy.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    document = json.loads(fixture_copy.read_text(encoding="utf-8"))
    invalid_field = document["semantic_model"][0]["datasets"][0]["fields"][0]
    del invalid_field["expression"]

    with pytest.raises(SemanticPolicyError) as exc_info:
        validate_ossie_document(document)

    assert exc_info.value.code == "ossie_invalid"
    assert exc_info.value.details["path"] == ["semantic_model", 0, "datasets", 0, "fields", 0]
