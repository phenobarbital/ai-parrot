"""Serial and model applicability decisions."""

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import (
    Applicability,
    SerialRange,
    Step,
    StepIdentity,
    applies,
    content_hash,
    normalize_serial,
)


def _step(applicability: Applicability) -> Step:
    """Build a minimally evidenced step for applicability tests."""
    evidence = Evidence(node_id="0001", quote="Applies to model X serials 2024-0001 through 2024-0099.")
    return Step(
        identity=StepIdentity(step_id="manual:repair:one", content_hash=content_hash("tighten")),
        order=1,
        text=Extracted[str](value="Tighten bolt", evidence=evidence),
        applicability=applicability,
    )


def test_applies_matrix() -> None:
    """Models, bounded ranges, missing serials, and open ranges follow Q7."""
    evidence = Evidence(node_id="0001", quote="Applies to model X serials 2024-0001 through 2024-0099.")
    bounded = _step(
        Applicability(
            models=["X"],
            serial_ranges=[SerialRange(start="2024-0001", end="2024-0099", format="2024-0000")],
            evidence=evidence,
        )
    )
    assert applies(bounded, model="Y", serial="2024-0005") == "no"
    assert applies(bounded, model="X", serial=None) == "unknown"
    assert applies(bounded, model="X", serial="2024-0005") == "yes"
    assert applies(bounded, model="X", serial="2024-0100") == "no"
    open_ended = _step(
        Applicability(serial_ranges=[SerialRange(end="2024-0099", format="2024-0000")], evidence=evidence)
    )
    assert applies(open_ended, model=None, serial="2024-0001") == "yes"


def test_normalize_serial_rejects_foreign_format() -> None:
    """A different separator or token shape is not comparable."""
    assert normalize_serial("2024-0007", format="2024-0000") == (2024, 7)
    with pytest.raises(ValueError):
        normalize_serial("2024/0007", format="2024-0000")


def test_applicability_requires_evidence() -> None:
    """Serial qualification is a critical, evidence-backed field."""
    with pytest.raises(ValueError):
        Applicability(serial_ranges=[SerialRange(start="2024-0001", format="2024-0000")])
