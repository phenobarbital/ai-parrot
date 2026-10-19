"""Tests for Apache Ossie document detection and validation."""

import copy
import json
from pathlib import Path

import pytest

from parrot.semantic.errors import SemanticPolicyError
from parrot.semantic.ossie import is_ossie_document, validate_ossie_document

FIXTURE = Path(__file__).parent / "fixtures/ossie/orders.ossie.json"


def test_ossie_schema_validation() -> None:
    """Validate a fixture and reject malformed or unsupported documents."""
    doc = json.loads(FIXTURE.read_text())

    assert is_ossie_document(doc)
    validate_ossie_document(doc)

    missing_source = copy.deepcopy(doc)
    del missing_source["semantic_model"][0]["datasets"][0]["source"]
    with pytest.raises(SemanticPolicyError) as invalid_error:
        validate_ossie_document(missing_source)
    assert invalid_error.value.code == "ossie_invalid"
    assert invalid_error.value.details["path"] == ["semantic_model", 0, "datasets", 0]

    unsupported_version = copy.deepcopy(doc)
    unsupported_version["version"] = "0.2.0"
    assert is_ossie_document(unsupported_version)
    with pytest.raises(SemanticPolicyError) as version_error:
        validate_ossie_document(unsupported_version)
    assert version_error.value.code == "ossie_version"
