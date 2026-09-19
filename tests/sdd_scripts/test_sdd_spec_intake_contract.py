"""Contract: /sdd-spec twins and codex skill expose intake mode (FEAT-577, spec §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TWINS = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md")
_PROCEDURE = "sdd/templates/intake.procedure.md"


def _read(rel: str) -> str:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} missing at this checkout")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", _TWINS)
def test_sdd_spec_points_at_intake_procedure(rel: str) -> None:
    assert _PROCEDURE in _read(rel)
    assert (_REPO_ROOT / _PROCEDURE).is_file()


@pytest.mark.parametrize("rel", _TWINS)
def test_sdd_spec_documents_intake_flags(rel: str) -> None:
    text = _read(rel)
    for flag in ("--interview", "--no-interview", "--resume", "--research", "--no-gate", "--budget"):
        assert flag in text, f"{rel} does not document {flag}"


def test_codex_skill_mentions_intake() -> None:
    text = _read(".agents/skills/sdd-spec/SKILL.md")
    assert _PROCEDURE in text
    assert "--no-interview" in text