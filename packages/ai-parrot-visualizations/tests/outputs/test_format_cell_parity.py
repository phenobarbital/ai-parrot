"""FEAT-623 (TASK-3996): ``format_cell`` agrees with the admin UI's ``formatA2UIValue``.

Both read ``display_format.json``; the TS side is
``a2ui-format.parity.test.ts`` (run from pytest by ai-parrot-server's
``test_vitest_a2ui_format_parity.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui_renderers._table_format import format_cell

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "ai-parrot"
    / "src"
    / "parrot"
    / "outputs"
    / "a2ui"
    / "format_contract"
    / "fixtures"
    / "display_format.json"
)
FIXTURES = json.loads(FIXTURE.read_text(encoding="utf-8"))


def _render(value, fmt, unit):
    """Compose ``format_cell`` with the unit rule (appended unless percent)."""
    text = format_cell(value, col_type="number", col_format=fmt)
    return f"{text} {unit}" if unit and fmt != "percent" else text


def test_fixtures_present() -> None:
    assert FIXTURES


@pytest.mark.parametrize("fx", FIXTURES, ids=lambda f: f"{f['value']!r}-{f['format']}-{f.get('unit', '')}")
def test_format_cell_parity_fixtures(fx) -> None:
    assert _render(fx["value"], fx["format"], fx.get("unit")) == fx["expected"]


def test_untyped_fallback_unchanged() -> None:
    assert format_cell(1234, col_type="integer") == "1,234"
    assert format_cell(1234.567, col_type="number") == "1,234.57"
