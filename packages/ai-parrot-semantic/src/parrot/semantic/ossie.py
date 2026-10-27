"""Apache Ossie 0.1.1 detection and validation against the vendored JSON Schema."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

import jsonschema

from .errors import SemanticPolicyError

OSSIE_SPEC_VERSION = "0.1.1"


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    """Load the vendored Apache Ossie schema once per process."""
    schema_path = files("parrot.semantic").joinpath("schemas/ossie-0.1.1.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def is_ossie_document(doc: dict) -> bool:
    """Return whether a document declares an Apache Ossie specification version."""
    return "version" in doc


def validate_ossie_document(doc: dict) -> None:
    """Validate a document against the vendored Apache Ossie 0.1.1 schema.

    Args:
        doc: Parsed JSON or YAML document to validate.

    Raises:
        SemanticPolicyError: If the declared version does not match 0.1.1 or
            the document does not conform to the schema.
    """
    declared_version = doc.get("version")
    if "version" in doc and declared_version != OSSIE_SPEC_VERSION:
        raise SemanticPolicyError(
            "ossie_version",
            f"Unsupported Apache Ossie version: expected {OSSIE_SPEC_VERSION}",
            details={"expected": OSSIE_SPEC_VERSION, "actual": declared_version},
        )

    validator = jsonschema.Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(doc), key=lambda error: list(error.absolute_path))
    if errors:
        first_error = errors[0]
        raise SemanticPolicyError(
            "ossie_invalid",
            "Invalid Apache Ossie document",
            details={"path": list(first_error.absolute_path)},
        )
