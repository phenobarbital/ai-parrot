"""Regression tests for shared provenance primitives (FEAT-601 M1)."""

from __future__ import annotations

import pytest

from parrot.knowledge.common import provenance, validation
from parrot.knowledge.contracts import carding as contracts_carding
from parrot.knowledge.contracts import models as contracts_models


def test_common_reexports_identity() -> None:
    """Contracts compatibility imports resolve to the common objects."""
    for name in (
        "Evidence",
        "Extracted",
        "FieldProvenance",
        "trim_quote",
        "MAX_QUOTE_CHARS",
        "UNSUBSTANTIATED_CONFIDENCE_CAP",
    ):
        assert getattr(contracts_models, name) is getattr(provenance, name)
    assert contracts_carding._quote_supported is validation.quote_supported
    assert contracts_carding._validate_extracted is validation.validate_extracted


def test_unsubstantiated_confidence_is_capped() -> None:
    """Unsubstantiated extraction confidence remains capped."""
    field = provenance.Extracted[str](value="x", evidence=None, confidence=0.9)
    assert field.confidence == provenance.UNSUBSTANTIATED_CONFIDENCE_CAP


def test_quote_supported_is_whitespace_insensitive() -> None:
    """Quotes remain valid across source whitespace wrapping."""
    evidence = provenance.Evidence(node_id="0001", quote="torque  to 12 Nm")
    assert validation.quote_supported(evidence, {"0001": "Then torque to\n12 Nm."})


def test_validate_extracted_drops_unsupported_quote() -> None:
    """Unsupported evidence is removed and its confidence is capped."""
    field = provenance.Extracted[str](
        value="x",
        evidence=provenance.Evidence(node_id="0001", quote="not in body"),
        confidence=0.9,
    )
    updated, dropped = validation.validate_extracted(field, {"0001": "supported body"})
    assert dropped is True
    assert updated.evidence is None
    assert updated.confidence == provenance.UNSUBSTANTIATED_CONFIDENCE_CAP


def test_trim_quote_word_boundary() -> None:
    """Overlong quotes still trim to a word boundary when possible."""
    quote = " ".join(f"word{index}" for index in range(80))
    trimmed = provenance.trim_quote(quote)
    assert len(trimmed) <= provenance.MAX_QUOTE_CHARS
    assert quote.startswith(trimmed)
    assert not trimmed.endswith(" ")


@pytest.mark.asyncio
async def test_load_bodies_skips_empty_and_unreadable() -> None:
    """Body loading retains only readable, nonempty bodies."""
    def loader(node_id: str) -> str | None:
        if node_id == "error":
            raise OSError("unreadable")
        return {"present": "body", "empty": "", "missing": None}[node_id]

    assert await validation.load_bodies(loader, ["present", "empty", "missing", "error"]) == {"present": "body"}
