# HOTFIX-NAV-7762-1: Commit the new-cycle rows for the two EcoTank End Cap planograms, their SQL and a guard test

**Feature**: ecotank-endcap-rows-new-cycle (BRIEF-NAV-7762)
**Spec**: sdd/briefs/ecotank-endcap-rows-new-cycle.brief.md
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Production runs the perceive → identify → compare cycle, and the two Office Depot EcoTank End Cap rows
(`epson_depot_ecotank_backlit_planogram_config`, `epson_depot_ecotank_not_backlit_planogram_config`) are
still in the legacy format, so their Epson360 tasks fail before any photo is processed
(`packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:127`). The new-format rows exist only in git-ignored scripts on one machine. This task puts
the rows under version control in the ticket-minimal form decided in the brief, together with the SQL an
operator applies by hand and a test that keeps the three in step.

This is a data + test task. It changes no production code.

## Scope

1. Create the two row fixtures and the SQL file by running the one-off generator in
   "Implementation Blueprint" from the worktree root. Commit the three files it writes; do **not** commit
   the generator.
2. Create the test file with exactly the content given in "Test Specification".
3. Run the validation commands.

**NOT in scope**: applying the SQL to any database; running the pipeline on photos; changing
`migration.check_row`, the FlowTask report or any file under `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/`; editing the rows' `description`,
`llm_backend` or `reference_images`; adding rules beyond the table in the brief's "Decisions" section.
Do not read or depend on `artifacts/` (git-ignored, absent from this worktree).

## Files to Create / Modify

- CREATE `packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762/epson_depot_ecotank_backlit_planogram_config.json`
- CREATE `packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762/epson_depot_ecotank_not_backlit_planogram_config.json`
- CREATE `sdd/migrations/NAV-7762-ecotank-endcap-rows.sql`
- CREATE `packages/ai-parrot-pipelines/tests/planogram_cycle/test_nav_7762_ecotank_endcap_rows.py`

## Codebase Contract

- Verified import: `from parrot_pipelines.planogram.migration import check_row` —
  `migration.py:698` `def check_row(row: Dict[str, Any]) -> PreflightRow`; `migration.py:81`
  `class PreflightRow(BaseModel)` with fields `config_name: str`, `planogram_type: str`, `ok: bool`,
  `problems: List[str]`. `check_row` reads `planogram_type`, `config_name`, `slots_definition` and
  `planogram_config` from the row dict.
- Verified import: `from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings` —
  `definition.py:366` `def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition`;
  `definition.py:437` `def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]`.
- Verified import: `from parrot_pipelines.planogram.layout import resolve_layout_profile, validate_zone_selectors` —
  `layout.py:154` `def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile`;
  `layout.py:209` `def validate_zone_selectors(profile: LayoutProfile, definition: SlotsDefinition, *, config_name: str) -> None`.
- Verified import: `from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional` —
  `types/endcap_no_shelves_promotional.py:66` class; `:73-74` `@classmethod def default_layout_profile(cls) -> LayoutProfile`.
- Verified: `plan.py:201-210` `PlanogramCompliance._load_definition` calls `load_slots_definition`,
  `validate_bindings` and `validate_zone_selectors` in that order; the test repeats that sequence.
- Verified: tests in `packages/ai-parrot-pipelines/tests/planogram_cycle/` locate the repository root with `Path(__file__).resolve().parents[4]`
  (`test_live_e2e_harness.py:14`).
- Verified: `sdd/migrations/FEAT-096-planogram15-config.sql` is the precedent for a committed planogram row change.
- Does NOT exist: `packages/ai-parrot-pipelines/tests/planogram_cycle/data/` (this task creates it); a call to `validate_zone_selectors` inside `check_row`;
  any tracked file under `packages/` that names either configuration; a `conftest.py` fixture for row files.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762/epson_depot_ecotank_backlit_planogram_config.json", "action": "CREATE"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762/epson_depot_ecotank_not_backlit_planogram_config.json", "action": "CREATE"},
    {"path": "sdd/migrations/NAV-7762-ecotank-endcap-rows.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_nav_7762_ecotank_endcap_rows.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#check_row",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#resolve_layout_profile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py#validate_zone_selectors"
  ]
}
```

## Implementation Notes

- In a worktree the shared `.venv` imports the main checkout. Run python and pytest with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`. Never `uv sync` here.
- The generator is deterministic. After running it, the files must have these SHA-256 digests:
  - `epson_depot_ecotank_backlit_planogram_config.json` — `eee8ef29c8c67850f66bbfa5d0c7ec75c9445a25c460b44b5242c21906bbfcc2`
  - `epson_depot_ecotank_not_backlit_planogram_config.json` — `81f8090231f000936483a00abea14980ebe2f0d6ad0f98abf2436612a6a92251`
  - `NAV-7762-ecotank-endcap-rows.sql` — `a4236589b0d5f3d37b5e68a63a61ef58ab2702b6f43b9120d14133fb559bc50f`
  A different digest means the generator text was altered while copying; fix the copy, do not edit the output.
- Zones, bands, ROI labels and ROI prompts must stay exactly as generated: they are the geometry used when
  the rows were run on store photos. Only the rule bindings were reduced.
- The SQL is applied by a person. Do not run it, and do not add a database connection to the test.

## Implementation Blueprint

Save the script below as `gen_nav7762_rows.py` in the worktree root, run
`PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src python gen_nav7762_rows.py`, check the
three digests with `sha256sum`, then delete the script.

```python
"""One-off generator for NAV-7762: writes the two row fixtures and the SQL that applies them.

Run from the repository root:  python gen_nav7762_rows.py
Do not commit this script; commit only the three files it writes.
"""
import json
from pathlib import Path

DATA = Path("packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762")
SQL = Path("sdd/migrations/NAV-7762-ecotank-endcap-rows.sql")
TYPE = "endcap_no_shelves_promotional"
BACKLIT = "epson_depot_ecotank_backlit_planogram_config"
NOT_BACKLIT = "epson_depot_ecotank_not_backlit_planogram_config"

ROI_HEAD = (
    "Analyze the {brand} promotional endcap (no shelves, no products) in this photo.\n"
    "Return one detection per element below, with its label and a confidence. In 'content', transcribe verbatim\n"
    "every text you can actually read on that element; never write text you cannot read, and leave it empty when\n"
    "nothing is legible.\n\nDETECTIONS:\n"
)
ROI_TAIL = "\nOnly report elements of this endcap; skip any element that is not visible."
LIGHT = (
    " Also add 'Light: ON' to 'content' when it emits its own glow, or 'Light: OFF' when it is matte print lit"
    " only by the store."
)

# zones: (zone_id, slots kind, band = fraction of the fixture height, ROI label)
# identity: the only zones that carry more than the mandatory zone_present rule
ROWS = {
    BACKLIT: {
        "aisle": "Epson EcoTank Endcap",
        "zones": [
            ("zone-header-1", "backlit", [0.0, 0.35], "backlit_header"),
            ("zone-comparison-1", "graphic", [0.35, 0.65], "comparison_panel"),
            ("zone-base-1", "graphic", [0.65, 1.0], "base_graphic"),
        ],
        "identity": {
            "zone-header-1": {
                "illumination": "on",
                "texts": ["EPSON", "Goodbye Cartridges", "Hello Savings"],
                "visual": ["EPSON logo", "image of Shaquille O'Neal", "EcoTank printer", "Goodbye Cartridges Hello Savings"],
            },
        },
        "roi": [
            "'endcap': the whole endcap, from the top of its header lightbox down to the floor base it stands on."
            " Exclude neighbouring aisles and shelves.",
            "'backlit_header': the large lightbox at the very top of the endcap (brand logo, headline, a photo of a"
            " person and printers)." + LIGHT,
            "'comparison_panel': the panel right below the header, with the columns comparing printer models.",
            "'base_graphic': the sign at the bottom of the endcap, resting on the floor base.",
        ],
    },
    NOT_BACKLIT: {
        "aisle": "Epson EcoTank Endcap Not Backlit",
        "zones": [
            ("zone-header-1", "header", [0.0, 0.20], "header_sign"),
            ("zone-backlit-1", "backlit", [0.20, 0.42], "backlit_panel"),
            ("zone-comparison-1", "graphic", [0.42, 0.70], "comparison_panel"),
            ("zone-base-1", "graphic", [0.70, 1.0], "base_graphic"),
        ],
        "identity": {
            "zone-header-1": {"texts": ["EPSON", "EcoTank", "Printers"]},
            "zone-backlit-1": {
                "illumination": "off",
                "texts": ["Goodbye Cartridges", "Hello Savings"],
                "visual": ["image of Shaquille O'Neal", "EcoTank printer", "Goodbye Cartridges Hello Savings"],
            },
        },
        "roi": [
            "'endcap': the whole endcap, from the top of its header sign down to the floor base it stands on."
            " Exclude neighbouring aisles and shelves.",
            "'header_sign': the sign at the very top of the endcap, with the brand logo and headline.",
            "'backlit_panel': the large lightbox panel right below the header sign (a photo of a person and"
            " printers)." + LIGHT,
            "'comparison_panel': the panel in the middle with the columns comparing printer models.",
            "'base_graphic': the sign at the bottom of the endcap, resting on the floor base.",
        ],
    },
}


def binding(kind: str, zone_id: str, params: dict | None = None) -> dict:
    return {"rule_id": f"{kind}:{zone_id}", "kind": kind, "target_id": zone_id, "params": params or {}, "mandatory": True}


def build(name: str) -> dict:
    spec = ROWS[name]
    bindings = []
    for zone_id, *_ in spec["zones"]:
        bindings.append(binding("zone_present", zone_id))
        ident = spec["identity"].get(zone_id, {})
        if "illumination" in ident:
            bindings.append(binding("illumination", zone_id, {"required": ident["illumination"], "penalty": 0.5}))
        if "texts" in ident:
            reqs = [{"required_text": t, "match_type": "contains", "mandatory": True} for t in ident["texts"]]
            bindings.append(binding("text_requirements", zone_id, {"requirements": reqs}))
        if "visual" in ident:
            bindings.append(binding("visual_features", zone_id, {"expected": ident["visual"]}))
    return {
        "config_name": name,
        "planogram_type": TYPE,
        "planogram_config": {
            "brand": "Epson",
            "category": "Printers",
            "aisle": {"name": spec["aisle"]},
            "layout_profile": {
                "perception_mode": "llm_detector",
                "roi_zone_labels": [label for *_, label in spec["zones"]],
                "zone_selectors": [{"zone_id": z, "kind": "zone", "band": band} for z, _, band, _ in spec["zones"]],
            },
            "rule_bindings": bindings,
        },
        "slots_definition": {
            "version": "1",
            "meta": {"brand": "Epson", "category": "Printers", "planogram_type": TYPE},
            "shelves": [],
            "zones": [{"zone_id": z, "kind": k, "shelf_id": None, "required": True} for z, k, _, _ in spec["zones"]],
        },
        "roi_detection_prompt": ROI_HEAD + "\n".join(f"{i}. {line}" for i, line in enumerate(spec["roi"], 1)) + ROI_TAIL,
    }


SQL_HEADER = """-- ============================================================
-- NAV-7762: Office Depot EcoTank End Cap planograms on the
--           perceive -> identify -> compare cycle
-- ============================================================
-- Table  : troc.planograms_configurations
-- Rows   : epson_depot_ecotank_backlit_planogram_config
--          epson_depot_ecotank_not_backlit_planogram_config
--          (keyed by config_name; the numeric id differs between environments)
-- Sets   : planogram_type, slots_definition, planogram_config,
--          roi_detection_prompt, updated_at
-- Keeps  : description, account_name, reference_images, llm_backend and
--          every other column
-- Safe   : data-only UPDATE of two rows, one transaction, no schema change.
--          Fails (and rolls back) unless exactly one active row matches each name.
-- Needs  : the slots_definition column (migration runbook, step "alter") and
--          ai-parrot-pipelines >= 1.2.5 on the worker that runs the compliance.
-- Status : NOT APPLIED
-- ============================================================
-- Generated from packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762/*.json;
-- test_nav_7762_ecotank_endcap_rows.py fails when this file and the fixtures differ.
--
-- Before applying (psql, same session):
--   \\copy (SELECT row_to_json(t) FROM troc.planograms_configurations t WHERE config_name IN ('epson_depot_ecotank_backlit_planogram_config', 'epson_depot_ecotank_not_backlit_planogram_config')) TO 'nav7762_rows_backup.json'
-- After applying:
--   SELECT config_name, planogram_type, slots_definition IS NOT NULL AS migrated, updated_at
--     FROM troc.planograms_configurations WHERE config_name LIKE 'epson_depot_ecotank_%backlit%';
-- Rollback: restore planogram_type, slots_definition, planogram_config and
--   roi_detection_prompt of both rows from nav7762_rows_backup.json.
-- ============================================================

BEGIN;
"""

SQL_ROW = """
-- {name}
DO $row$
DECLARE
    n integer;
BEGIN
    UPDATE troc.planograms_configurations
       SET planogram_type = $pgm${ptype}$pgm$,
           slots_definition = $pgm${slots}$pgm$,
           planogram_config = $pgm${config}$pgm$,
           roi_detection_prompt = $pgm${roi}$pgm$,
           updated_at = now()
     WHERE config_name = $pgm${name}$pgm$
       AND is_active = TRUE;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
        RAISE EXCEPTION 'expected exactly 1 active row named %, updated %', $pgm${name}$pgm$, n;
    END IF;
END$row$;
"""


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    sql = SQL_HEADER
    for name in (BACKLIT, NOT_BACKLIT):
        row = build(name)
        (DATA / f"{name}.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        sql += SQL_ROW.format(
            name=name,
            ptype=row["planogram_type"],
            slots=json.dumps(row["slots_definition"], ensure_ascii=False),
            config=json.dumps(row["planogram_config"], ensure_ascii=False),
            roi=row["roi_detection_prompt"],
        )
    assert "$pgm$" not in json.dumps([build(n) for n in ROWS])
    SQL.parent.mkdir(parents=True, exist_ok=True)
    SQL.write_text(sql + "\nCOMMIT;\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

## Acceptance Criteria

- The four files exist at the paths listed above and the three generated files have the digests given in
  "Implementation Notes".
- `gen_nav7762_rows.py` is not committed.
- Both validation commands pass; `ruff check packages/ai-parrot-pipelines/tests/planogram_cycle/test_nav_7762_ecotank_endcap_rows.py` passes.
- The SQL contains no `planogram_id`, one `BEGIN;` and a final `COMMIT;`, and its header says
  `Status : NOT APPLIED`.
- `git status --porcelain` shows only the four new files before the commit.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_nav_7762_ecotank_endcap_rows.py -q`
- `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -q`

## Test Specification

Create `packages/ai-parrot-pipelines/tests/planogram_cycle/test_nav_7762_ecotank_endcap_rows.py` with exactly this content (6 tests):

```python
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
```

## Agent Instructions

1. Verify the Codebase Contract entries against the worktree before writing anything.
2. Create only the four files listed; stage them by path (never `git add .` / `-A`).
3. Commit as `feat(ecotank-endcap-rows-new-cycle): HOTFIX-NAV-7762-1 — new-cycle rows, SQL and guard test`.
4. If a digest or a test does not match, stop and record what differed in the Completion Note instead of
   adjusting the rows.

## Completion Note

_To be filled in when the task is closed._
