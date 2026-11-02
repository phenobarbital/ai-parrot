"""FEAT-784 M10: the template and every /sdd-spec and /sdd-task entry point carry the audit steps."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_ENTRY_POINTS = (
    ".claude/commands/sdd-spec.md",
    ".agent/workflows/sdd-spec.md",
    ".agents/skills/sdd-spec/SKILL.md",
)
_TASK_ENTRY_POINTS = (
    ".claude/commands/sdd-task.md",
    ".agent/workflows/sdd-task.md",
    ".agents/skills/sdd-task/SKILL.md",
)
_TEMPLATE_ORDER = (
    "## Governing Decisions",
    "## 2. Architectural Design",
    "## 7. Implementation Notes",
    "## Decisions",
    "## Decision Waivers",
    "## Consequences",
    "## 8. Open Questions",
)


def _read(rel: str) -> str:
    """Return the UTF-8 text of a repository-relative file."""
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


def _line_index(lines: list[str], heading: str) -> int:
    """Return the index of the line that starts with ``heading`` exactly once."""
    hits = [i for i, line in enumerate(lines) if line == heading or line.startswith(heading + " ")]
    if heading == "## 7. Implementation Notes":
        hits = [i for i, line in enumerate(lines) if line.startswith(heading)]
    assert len(hits) == 1, f"{heading!r} occurs {len(hits)} times"
    return hits[0]


def test_template_sections_in_order() -> None:
    """The spec template carries the four audit sections at their spliced positions (AC15)."""
    lines = _read("sdd/templates/spec.md").splitlines()
    positions = [_line_index(lines, heading) for heading in _TEMPLATE_ORDER]
    assert positions == sorted(positions)


@pytest.mark.parametrize("rel", _SPEC_ENTRY_POINTS)
def test_sdd_spec_has_retrieve_and_gate(rel: str) -> None:
    """Every /sdd-spec entry point retrieves governing decisions, then gates approval (AC15)."""
    text = _read(rel)
    for needle in ("wikitoolkit spec governing", "check_spec_consequences", "--render", "approved"):
        assert needle in text, f"{rel} lacks {needle!r}"
    assert text.index("wikitoolkit spec governing") < text.index("check_spec_consequences")


@pytest.mark.parametrize("rel", _TASK_ENTRY_POINTS)
def test_sdd_task_check_is_advisory(rel: str) -> None:
    """Every /sdd-task entry point runs the audit as advisory only (AC19)."""
    text = _read(rel)
    for needle in ("check_spec_consequences", "--advisory"):
        assert needle in text, f"{rel} lacks {needle!r}"
    assert "never refuses" in text.replace("**", "")
