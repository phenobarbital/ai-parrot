"""NAV-7762: the Office Depot EcoTank End Cap rows (Backlit / Not Backlit) on the new cycle.

The two JSON fixtures are the rows applied by ``sdd/migrations/NAV-7762-ecotank-endcap-rows.sql``.
They must pass the migration preflight AND the validation the pipeline constructor runs, bind only
the checks the ticket asks for, and stay identical to what the SQL writes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings
from parrot_pipelines.planogram.layout import resolve_layout_profile, validate_zone_selectors
from parrot_pipelines.planogram.migration import check_row
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional

_DATA = Path(__file__).resolve().parent / "data" / "nav_7762"
_SQL = Path(__file__).resolve().parents[4] / "sdd" / "migrations" / "NAV-7762-ecotank-endcap-rows.sql"

BACKLIT = "epson_depot_ecotank_backlit_planogram_config"
NOT_BACKLIT = "epson_depot_ecotank_not_backlit_planogram_config"
ROWS = (BACKLIT, NOT_BACKLIT)
PLANOGRAM_TYPE = "endcap_no_shelves_promotional"

#: zone_id -> rule kinds bound to it. Presence for every graphic; identity checks on the top graphic only.
EXPECTED_RULES: dict[str, dict[str, set[str]]] = {
    BACKLIT: {
        "zone-header-1": {"zone_present", "illumination", "text_requirements", "visual_features"},
        "zone-comparison-1": {"zone_present"},
        "zone-base-1": {"zone_present"},
    },
    NOT_BACKLIT: {
        "zone-header-1": {"zone_present", "text_requirements"},
        "zone-backlit-1": {"zone_present", "illumination", "text_requirements", "visual_features"},
        "zone-comparison-1": {"zone_present"},
        "zone-base-1": {"zone_present"},
    },
}
#: The one difference between the two planograms: the light must be on (Backlit) or off (Not Backlit).
EXPECTED_LIGHT = {BACKLIT: ("zone-header-1", "on"), NOT_BACKLIT: ("zone-backlit-1", "off")}

_SQL_ROW = re.compile(
    r"SET planogram_type = \$pgm\$(?P<ptype>.*?)\$pgm\$,\s*"
    r"slots_definition = \$pgm\$(?P<slots>.*?)\$pgm\$,\s*"
    r"planogram_config = \$pgm\$(?P<config>.*?)\$pgm\$,\s*"
    r"roi_detection_prompt = \$pgm\$(?P<roi>.*?)\$pgm\$,\s*"
    r"updated_at = now\(\)\s*"
    r"WHERE config_name = \$pgm\$(?P<name>.*?)\$pgm\$\s*"
    r"AND is_active = TRUE;",
    re.S,
)


def _row(name: str) -> dict[str, Any]:
    """Load one row fixture.

    Args:
        name: The ``config_name`` of the row.

    Returns:
        The row as a dict.
    """
    return json.loads((_DATA / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ROWS)
def test_row_passes_preflight_and_runtime_validation(name: str) -> None:
    row = _row(name)
    assert row["config_name"] == name
    assert row["planogram_type"] == PLANOGRAM_TYPE

    verdict = check_row(row)
    assert verdict.ok, verdict.problems

    # check_row does not run validate_zone_selectors; PlanogramCompliance._load_definition does.
    definition = load_slots_definition(row["slots_definition"])
    validate_bindings(definition, row["planogram_config"])
    layout = resolve_layout_profile(
        EndcapNoShelvesPromotional.default_layout_profile(), row["planogram_config"], config_name=name
    )
    validate_zone_selectors(layout, definition, config_name=name)
    assert layout.perception_mode == "llm_detector"


@pytest.mark.parametrize("name", ROWS)
def test_row_binds_only_the_checks_the_ticket_asks_for(name: str) -> None:
    row = _row(name)
    zones = row["slots_definition"]["zones"]
    assert [zone["zone_id"] for zone in zones] == list(EXPECTED_RULES[name])
    assert all(zone["required"] for zone in zones)

    bindings = row["planogram_config"]["rule_bindings"]
    assert all(binding["mandatory"] is True for binding in bindings)
    bound: dict[str, set[str]] = {}
    for binding in bindings:
        bound.setdefault(binding["target_id"], set()).add(binding["kind"])
    assert bound == EXPECTED_RULES[name]

    lights = [(b["target_id"], b["params"]["required"]) for b in bindings if b["kind"] == "illumination"]
    assert lights == [EXPECTED_LIGHT[name]]


def test_not_backlit_header_accepts_both_artwork_wordings() -> None:
    bindings = _row(NOT_BACKLIT)["planogram_config"]["rule_bindings"]
    header = next(b for b in bindings if b["rule_id"] == "text_requirements:zone-header-1")
    required = [req["required_text"] for req in header["params"]["requirements"]]
    # "EcoTank Printers" (stores) and "EcoTank Cartridge-Free Printers" (rendering) both contain these.
    assert required == ["EPSON", "EcoTank", "Printers"]
    assert all(req["match_type"] == "contains" for req in header["params"]["requirements"])


def test_sql_is_keyed_by_config_name_and_matches_the_fixtures() -> None:
    sql = _SQL.read_text(encoding="utf-8")
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "planogram_id" not in statements  # ids differ between environments
    assert statements.count("BEGIN;") == 1 and statements.rstrip().endswith("COMMIT;")

    blocks = {match["name"]: match for match in _SQL_ROW.finditer(statements)}
    assert set(blocks) == set(ROWS)
    for name, match in blocks.items():
        row = _row(name)
        assert match["ptype"] == row["planogram_type"]
        assert json.loads(match["slots"]) == row["slots_definition"]
        assert json.loads(match["config"]) == row["planogram_config"]
        assert match["roi"] == row["roi_detection_prompt"]
