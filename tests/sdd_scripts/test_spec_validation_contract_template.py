"""FEAT-699: the spec template's Validation Contract example is parseable and documented in both twins."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/ai-parrot/src/parrot/flows/dev_loop"))
import test_scope.contract as contract  # noqa: E402

TWINS = (".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md")


def test_template_example_parses() -> None:
    text = (ROOT / "sdd/templates/spec.md").read_text(encoding="utf-8").replace("<dist>", "ai-parrot")
    parsed = contract.parse_spec_contract(text)
    assert parsed is not None
    # FEAT-709 schema 2: the template still writes the flat `tests:` form, which is lifted on
    # read into exactly one pytest runner. `TestContract.tests`/`.markers` no longer exist.
    assert parsed.schema == 2
    assert len(parsed.runners) == 1
    runner = parsed.runners[0]
    assert runner.kind == "pytest"
    assert len(runner.targets) == 2
    assert runner.settings.get("markers", "") == ""


def test_twins_carry_hint() -> None:
    for rel in TWINS:
        assert "Validation Contract hint (FEAT-699" in (ROOT / rel).read_text(encoding="utf-8")


def test_skill_mentions_contract() -> None:
    text = (ROOT / ".agents/skills/sdd-spec/SKILL.md").read_text(encoding="utf-8")
    assert "### Validation Contract" in text
