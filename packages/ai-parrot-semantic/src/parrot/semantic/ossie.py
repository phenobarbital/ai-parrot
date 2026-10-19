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
    """Load the vendored Apache Ossie 0.1.1 schema."""
    return json.loads(files("parrot.semantic").joinpath("schemas/ossie-0.1.1.schema.json").read_text())


def is_ossie_document(doc: dict) -> bool:
    """Return whether ``doc`` declares itself as an Apache Ossie document."""
    return "version" in doc


def validate_ossie_document(doc: dict) -> None:
    """Validate a document against the vendored Apache Ossie 0.1.1 schema.

    Args:
        doc: Candidate Apache Ossie document.

    Raises:
        SemanticPolicyError: If the declared version is unsupported or schema validation fails.
    """
    version = doc.get("version")
    if version is not None and version != OSSIE_SPEC_VERSION:
        raise SemanticPolicyError(
            "ossie_version",
            f"Unsupported Apache Ossie specification version: {version!r}",
            details={"version": version, "expected": OSSIE_SPEC_VERSION},
        )

    validator = jsonschema.Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(doc), key=lambda error: tuple(str(part) for part in error.absolute_path))
    if errors:
        first_error = errors[0]
        raise SemanticPolicyError(
            "ossie_invalid",
            first_error.message,
            details={"path": list(first_error.absolute_path)},
        )
