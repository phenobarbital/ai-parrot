"""FEAT-540 import ceilings (spec §1). TASK-4333 removes the xfail marks."""

from __future__ import annotations

import pytest

from ._support.import_probe import run_import_probe

CEILINGS = [
    pytest.param("parrot.auth.exceptions", 150, id="auth.exceptions"),
    pytest.param(
        "parrot.knowledge.ontology.schema",
        240,
        id="ontology.schema",
        marks=pytest.mark.xfail(strict=False, reason="TASK-4301/4333"),
    ),
    pytest.param(
        "parrot.knowledge.graphindex", 800, id="graphindex", marks=pytest.mark.xfail(strict=False, reason="TASK-4333")
    ),
    pytest.param(
        "parrot.knowledge.graphindex.builder",
        1200,
        id="graphindex.builder",
        marks=pytest.mark.xfail(strict=False, reason="TASK-4333"),
    ),
    pytest.param(
        "parrot.knowledge.wiki.cli", 850, id="wiki.cli", marks=pytest.mark.xfail(strict=False, reason="TASK-4333")
    ),
]


@pytest.mark.parametrize(("module", "ceiling"), CEILINGS)
def test_import_ceiling(module: str, ceiling: int) -> None:
    """Assert that an entry-point import stays within its current ceiling."""
    result = run_import_probe(module)
    assert result.error is None, result.error
    assert result.loaded_forbidden == [], result.loaded_forbidden
    assert result.count <= ceiling, result.count
