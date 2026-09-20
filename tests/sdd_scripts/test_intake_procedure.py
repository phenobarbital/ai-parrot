"""Text contract for sdd/templates/intake.procedure.md (FEAT-577, spec §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROCEDURE = _REPO_ROOT / "sdd" / "templates" / "intake.procedure.md"
_REFERENCED = (
    "sdd/templates/intake.schema.json",
    "sdd/templates/state.schema.json",
    "sdd/templates/research_plan.prompt.md",
    "sdd/templates/synthesis.prompt.md",
)


@pytest.fixture
def procedure() -> str:
    return _PROCEDURE.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _REFERENCED)
def test_intake_procedure_names_its_schemas(procedure: str, rel: str) -> None:
    """The procedure references each schema/prompt by path, and the path exists."""
    assert rel in procedure
    assert (_REPO_ROOT / rel).is_file()


def test_intake_procedure_offers_brainstorm_handoff(procedure: str) -> None:
    for needle in ("recommended_next_command", "sdd-brainstorm", "handed_off"):
        assert needle in procedure


def test_intake_procedure_has_no_unfilled_markers(procedure: str) -> None:
    """The procedure contains no FILL IN markers."""
    assert "FILL IN" not in procedure