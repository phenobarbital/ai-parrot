# TASK-3448: Config migration utility, read-only preflight and deployment runbook

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3426, TASK-3435
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 19**, goal G15 and brainstorm "Migration and compatibility
contract". Migrated types (`ProductOnShelves`, `InkWall`) refuse to construct
without a valid `slots_definition`; existing ProductOnShelves configurations
only have `planogram_config.shelves[].products`. A nullable column is **not** a
completed migration: before the new runtime is deployed every active migrated
configuration needs a *reviewed* `slots_definition` plus explicit
`rule_bindings`. This task ships the tooling and the runbook. The user applies
all database changes — nothing here writes to a database.

---

## Scope

- `convert_config(planogram_config, *, planogram_type) -> ConversionReport`:
  offline **candidate** conversion of a ProductOnShelves config dict.
  - Never mutates its input (work on a deep copy; the original is kept for
    review and rollback).
  - `quantity_range == (n, n)` (or `[n, n]`) ⇒ `n` candidate facings for that
    product; a real range (`min != max`) or a missing/ambiguous position ⇒ an
    entry in `unresolved` — **never invent an exact layout**.
  - Skips `fact_tag | price_tag | slot` product types (not facings).
  - Promotional / header products (`promotional_graphic`, backlit, …) become
    **zones** (`ZoneDefinition`), not facings.
  - Extracts nested `illumination_required`, `illumination_penalty`,
    `text_requirements`, `visual_features` from `shelves[].products[]` — and the
    endcap's `text_requirements` — into `rule_bindings` targeting the stable ids
    it generated. Thresholds, shelf weights and `advertisement_endcap` stay in
    `planogram_config` untouched.
  - Stable ids: `shelf_id = "shelf-<n>"`, `facing_id = "<shelf_id>:<slot>"`,
    `zone_id = "zone-<level>-<n>"`, `rule_id = "<kind>:<target_id>"`.
  - Validates its own candidate with `load_slots_definition` +
    `validate_bindings`; validation failures go to `warnings`, not exceptions.
- `preflight(dsn) -> List[PreflightRow]`: **SELECT-only** listing of active rows
  whose `planogram_type` is migrated and whose `slots_definition` is missing /
  invalid or whose bindings dangle.
- CLI: `python -m parrot_pipelines.planogram.migration convert <config.json> [--planogram-type …] [--out …]`
  and `… preflight --dsn <dsn>`.
- Runbook `docs/pipelines/planogram-cycle-migration.md`.
- Offline tests (no database).

**NOT in scope**: applying the ALTER script or any `UPDATE`; converting `InkWall`
definitions (they are authored, not converted); copying one fixture's sample
JSON to other configs; the handler; descriptor proposals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` | CREATE | `convert_config`, `preflight`, models, CLI |
| `docs/pipelines/planogram-cycle-migration.md` | CREATE | deployment / rollback runbook + score-semantics change |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py` | CREATE | offline tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field
from asyncdb import AsyncDB        # verified usage: packages/ai-parrot/src/parrot/auth/userinfo.py:19, :118 — import LAZILY inside preflight()
# created by dependency tasks
from parrot_pipelines.planogram.comparison.definition import (load_slots_definition, validate_bindings,
    SlotsDefinitionError)          # TASK-3435
```

### Existing Signatures to Use
```python
# AsyncDB idiom (verified: packages/ai-parrot/src/parrot/auth/userinfo.py:118, :132-137)
db = AsyncDB('pg', dsn=dsn)
async with await db.connection() as conn:
    row = await conn.fetch_one("SELECT … WHERE user_id = $1", manager_id)     # single row — VERIFIED
# multi-row fetch on the same connection: `await conn.fetch_all(sql)` — (unverified — check before use;
#   grep asyncdb's pg driver for `async def fetch_all` / `async def query` and use whichever exists)

# Handler query this preflight mirrors (verified: parrot_pipelines/handlers/planogram_compliance.py:284-294)
#   "SELECT * FROM troc.planograms_configurations WHERE config_name = $1 AND is_active = TRUE LIMIT 1"
#   via `db = self.request.app["database"]; async with await db.acquire() as conn: await conn.fetch_one(...)`
#   (that `db` is the app pool — NOT available to a CLI; the CLI builds its own AsyncDB from --dsn)

# Raw config layout the converter reads (verified: parrot/models/detections.py + product_on_shelves.py:411-436)
# planogram_config = {"brand", "category", "aisle", "shelves": [ {"level": str, "products": [ {
#       "name": str, "product_type": str, "quantity_range": [min, max] (default (1,1), detections.py:250),
#       "position_preference": "left"|"center"|"right"|None (:251), "mandatory": bool (:252),
#       "visual_features": [str]|None (:253),
#       "illumination_required": "on"|"off"   (RAW dict only — product_on_shelves.py:420-427),
#       "illumination_penalty": float         (RAW dict only — default 0.5, product_on_shelves.py:429-436),
#       "text_requirements": [...]            (RAW dict only — read at plan.py:159-170) } ],
#     "compliance_threshold", "product_weight", "text_weight", "visual_weight", … (ShelfConfig :302-326) } ],
#   "advertisement_endcap": {"enabled", "position", "text_requirements": [TextRequirement], …} (:337-354),
#   "use_fact_tag_boundaries", "product_subtypes", … }
# promotional product types (product_on_shelves.py:391-404): promotional_graphic, graphic, banner, backlit_graphic,
#   backlit, advertisement, advertisement_graphic, display_graphic, promotional_display, promotional_material,
#   promotional_materials, text_overlay
# non-facing product types (product_on_shelves.py:533, :546-547): fact_tag, price_tag, slot

# troc.planograms_configurations (verified: parrot_pipelines/table.sql:3-47): config_name :8, planogram_config JSONB :13,
#   is_active :46. NO planogram_type column in the DDL — deployed rows may still carry it (handler reads
#   row.get("planogram_type", "product_on_shelves"), handlers/planogram_compliance.py:323) → use dict(row).get(...)
```

```python
# Created by TASK-3435 (dependency) — planogram/comparison/definition.py, spec §3 Module 9
def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition   # raises SlotsDefinitionError
def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]
class SlotsDefinitionError(ValueError)
# SlotsDefinition(version, meta, shelves: [ShelfDefinition(shelf_id, shelf_number, level, facings)],
#                 zones: [ZoneDefinition(zone_id, kind, shelf_id, required)])
# FacingDefinition(facing_id, shelf_id, slot, product, brand, facings, descriptors)
# RuleBinding(rule_id, kind: illumination|text_requirements|visual_features|zone_present, target_id, params, mandatory)
# Created by TASK-3426 (dependency): PlanogramConfig.slots_definition / .llm_backend and
#   packages/ai-parrot-pipelines/src/parrot_pipelines/alter_planograms_configurations_feat574.sql
```

### Does NOT Exist
- ~~any existing migration / ALTER tooling in `parrot_pipelines`~~ — this is the first.
- ~~`planogram_type` column in `table.sql`~~ — absent from the DDL; treat as optional in rows.
- ~~`conn.fetch_all` verified~~ — only `fetch_one` is verified; check before use.
- ~~`self.request.app["database"]` outside a handler~~ — the CLI has no aiohttp app.
- ~~a catalog / SKU / price source~~ — never generate `price` or descriptors here; facings get `product`, `brand` and empty descriptors (this is why converted definitions usually need descriptor work before they are useful).
- ~~`ShelfProduct.slot` or any explicit position index in legacy configs~~ — only `position_preference`; slot order inside a shelf is the product list order and must be flagged for review.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py",
      "action": "CREATE"
    },
    {
      "path": "docs/pipelines/planogram-cycle-migration.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
- Pure functions for conversion; the only I/O is in the CLI (`asyncio.to_thread`
  is unnecessary in a CLI — plain file reads are fine there) and in `preflight`.
- No `print`: the CLI writes JSON with `sys.stdout.write` and logs with `logging`.
- `preflight` must be impossible to misuse for writes: a single hard-coded
  `SELECT`, no string interpolation of user input.

### Key Constraints
- The candidate is a *proposal*: `ConversionReport.unresolved` non-empty ⇒ the
  CLI exits with code 2 so a script cannot mistake it for a finished migration.
- Deep-copy the input; a test asserts the input dict is unchanged.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:411-436` — where the nested raw keys are read today
- `packages/ai-parrot/src/parrot/auth/userinfo.py:118-137` — AsyncDB idiom
- spec §2 "Scoring contract for migrated types" — the semantics the runbook must explain

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `migration.py` models + `convert_config` — *why*: everything else (CLI, runbook examples, tests) builds on the report shape.
2. Add `preflight` with the lazy `AsyncDB` import — *why*: importing the module must not require a database driver.
3. Add the CLI (`_main`) — *why*: the runbook tells operators to run it.
4. Write the runbook — *why*: G15 deliverable; the ValueError raised by migrated types at construction points operators here.
5. Write tests and run the Validation Command.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` (CREATE) — part 1
```python
"""Offline configuration migration for the perceive → identify → compare cycle (FEAT-574).

Candidate conversion of legacy ProductOnShelves configs into ``slots_definition`` +
``rule_bindings``, and a read-only database preflight. Nothing here writes to a database.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)

logger = logging.getLogger(__name__)

MIGRATED_TYPES = frozenset({"product_on_shelves", "ink_wall"})
_NON_FACING_TYPES = frozenset({"fact_tag", "price_tag", "slot"})
_ZONE_TYPES = frozenset({
    "promotional_graphic", "graphic", "banner", "backlit_graphic", "backlit", "advertisement",
    "advertisement_graphic", "display_graphic", "promotional_display", "promotional_material",
    "promotional_materials", "text_overlay",
})
_PREFLIGHT_SQL = (
    "SELECT * FROM troc.planograms_configurations WHERE is_active = TRUE ORDER BY config_name"
)


class ConversionReport(BaseModel):
    """Result of a candidate conversion. ``candidate`` is a proposal for human review."""

    candidate: Dict[str, Any] = Field(default_factory=dict)
    bindings: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PreflightRow(BaseModel):
    """Preflight verdict for one active configuration row."""

    config_name: str
    planogram_type: str
    ok: bool
    problems: List[str] = Field(default_factory=list)


def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport:
    """Build a candidate slots definition and rule bindings from a legacy config dict.

    Args:
        planogram_config: The raw ``planogram_config`` dict (never mutated).
        planogram_type: The configuration's planogram type.

    Returns:
        A ConversionReport. ``unresolved`` lists everything a human must decide.

    Raises:
        ValueError: When ``planogram_type`` is not ``"product_on_shelves"``.
    """
    if planogram_type != "product_on_shelves":
        raise ValueError(f"Only product_on_shelves configs are convertible, got '{planogram_type}'")
    config = copy.deepcopy(planogram_config)
    report = ConversionReport()
    # FILL IN: walk config["shelves"] in order (shelf_number = index+1, shelf_id f"shelf-{n}") —
    #   bounded by the Scope rules: fixed quantity ⇒ n facings with consecutive slots 1..n;
    #   range / missing quantity ⇒ ONE placeholder facing + an `unresolved` entry naming shelf+product;
    #   zone types ⇒ zones[] + a mandatory `zone_present` binding; non-facing types skipped;
    #   slot order = list order ⇒ always add a warning "slot order taken from list order — review".
    # FILL IN: bindings from nested illumination_required/illumination_penalty (kind "illumination",
    #   params {"required", "penalty"}), text_requirements (product-level AND advertisement_endcap, kind
    #   "text_requirements", params {"requirements": [...]}), visual_features (kind "visual_features",
    #   params {"expected": [...]}) — bounded by: target_id must be an id generated above.
    # FILL IN: self-validation — load_slots_definition(report.candidate) and
    #   validate_bindings(definition, {**config, "rule_bindings": report.bindings}); catch
    #   SlotsDefinitionError → report.warnings (never raise).
    return report
```
**Why this shape**: model fields and both function signatures are fixed by spec
Module 19's skeleton. `_ZONE_TYPES` / `_NON_FACING_TYPES` are copied from the
verified legacy sets so conversion classifies products exactly as today's
compliance code does.

### same file — part 2
```python
async def preflight(dsn: str) -> List[PreflightRow]:
    """List active rows and whether each migrated-type row is ready. SELECT-only.

    Args:
        dsn: PostgreSQL DSN.

    Returns:
        One PreflightRow per active configuration (legacy types are always ``ok``).
    """
    from asyncdb import AsyncDB  # lazy: importing this module must not need a DB driver

    db = AsyncDB("pg", dsn=dsn)
    async with await db.connection() as conn:
        # FILL IN: fetch all rows of _PREFLIGHT_SQL — bounded by: verify the driver's multi-row
        #   method name first (contract: fetch_all is unverified); no other statement may be issued.
        rows: Sequence[Any] = []
    return [check_row(dict(row)) for row in rows]


def check_row(row: Dict[str, Any]) -> PreflightRow:
    """Pure verdict for one row dict (unit-testable without a database)."""
    ptype = row.get("planogram_type") or "product_on_shelves"
    verdict = PreflightRow(config_name=str(row.get("config_name", "")), planogram_type=ptype, ok=True)
    if ptype not in MIGRATED_TYPES:
        return verdict
    # FILL IN: problems for — slots_definition NULL/empty; JSON string that does not decode;
    #   SlotsDefinitionError from load_slots_definition; SlotsDefinitionError from validate_bindings
    #   (planogram_config may also arrive as a JSON string). ok = not problems.
    return verdict


def _main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 2 unresolved items / failing rows, 1 usage or I/O error."""
    parser = argparse.ArgumentParser(prog="python -m parrot_pipelines.planogram.migration")
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("convert", help="candidate slots JSON from a legacy config JSON file")
    conv.add_argument("config", type=Path)
    conv.add_argument("--planogram-type", default="product_on_shelves")
    conv.add_argument("--out", type=Path, default=None)
    pre = sub.add_parser("preflight", help="read-only readiness report")
    pre.add_argument("--dsn", required=True)
    args = parser.parse_args(argv)
    # FILL IN: convert → read JSON (accept either a bare planogram_config or an exported row with a
    #   "planogram_config" key), write report JSON to --out or sys.stdout.write; never overwrite the
    #   input file (refuse when --out == config). preflight → asyncio.run(preflight(args.dsn)).
    return 0


if __name__ == "__main__":
    sys.exit(_main())
```
**Why**: `check_row` is split out of `preflight` so the readiness logic is
tested without a database; the only DB statement is the constant
`_PREFLIGHT_SQL`, which makes the "read-only" promise auditable.

### `docs/pipelines/planogram-cycle-migration.md` (CREATE)
```markdown
# Planogram compliance — migrating configurations to the new cycle (FEAT-574)

## Who needs this
<!-- FILL IN: migrated types = product_on_shelves, ink_wall; legacy types need nothing but their prompts -->
## What changes in scores (read before comparing old and new numbers)
<!-- FILL IN — bounded by spec §2: all expected facings stay in the denominator; weights are normalised
     (legacy non-header defaults 0.8/0.1/0.2 summed to 1.1 and were clamped); coverage is separate from
     compliance; inconclusive ⇒ overall_compliant False; unseen ≠ missing; empty result list never passes -->
## Sequence
1. Apply the idempotent ALTER script (`alter_planograms_configurations_feat574.sql`, shipped as package data).
2. Export each active configuration; run `python -m parrot_pipelines.planogram.migration convert …`.
3. Review the candidate: resolve every `unresolved` item, confirm slot order, review `rule_bindings`.
4. Backfill `slots_definition` and `planogram_config.rule_bindings` (user-applied `UPDATE`; keep the original JSON).
5. Run `… migration preflight --dsn …` until every migrated row is `ok`.
6. Deploy the new runtime.
## Rollback
<!-- FILL IN: redeploy previous version; new columns are nullable and ignored by it; original
     shelves[].products were never removed -->
## Process-pool sizing under gunicorn
<!-- FILL IN: cpu_workers is PER gunicorn worker; OCR/ONNX models load per process — memory arithmetic -->
## Troubleshooting
<!-- FILL IN: construction ValueError messages and what to fix -->
```
**Why**: section list is fixed (spec Module 19: ALTER → review + backfill →
preflight → deploy → rollback, plus the score-semantics change and the
executor sizing note from §7). Replace every HTML comment with prose.

### FILL IN checklist
- [ ] `convert_config` — shelf walk, facings/zones, unresolved, slot-order warning
- [ ] `convert_config` — bindings extraction (illumination, text, visual, zone_present)
- [ ] `convert_config` — self-validation into `warnings`
- [ ] `preflight` — verified multi-row fetch, single SELECT
- [ ] `check_row` — four problem kinds, JSON-string tolerance
- [ ] `_main` — I/O, exit codes, refuse to overwrite the input
- [ ] runbook prose (no HTML comments left)
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `convert_config` never mutates its input and never touches a database.
- [ ] Fixed quantities seed candidate facings with slots `1..n`; ranges / ambiguous positions appear in `unresolved`; no exact layout is invented.
- [ ] Nested `illumination_required`, `illumination_penalty`, `text_requirements`, `visual_features` and the endcap text requirements become bindings whose `target_id` exists in the candidate.
- [ ] Thresholds, shelf weights and `advertisement_endcap` are left in `planogram_config`.
- [ ] `check_row` flags: missing definition, undecodable JSON, invalid definition, dangling bindings; legacy types are always `ok`.
- [ ] `preflight` issues exactly one statement and it is a `SELECT`.
- [ ] CLI exit code is `2` when `unresolved` is non-empty or any row is not `ok`.
- [ ] Runbook covers ALTER → backfill → preflight → deploy → rollback and the score-semantics change.
- [ ] No `print`; `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` passes.
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q` passes offline.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py
"""Offline tests for the config migration utility."""
import copy
import pytest

from parrot_pipelines.planogram.migration import (ConversionReport, PreflightRow, check_row,
                                                  convert_config, _main, _PREFLIGHT_SQL)


@pytest.fixture
def legacy_config() -> dict:
    """header shelf (backlit promotional_graphic + illumination_required + endcap text reqs) and a
    middle shelf: product A quantity_range [2, 2], product B quantity_range [1, 3], one fact_tag."""
    ...


def test_convert_does_not_mutate_input(legacy_config):
    before = copy.deepcopy(legacy_config)
    convert_config(legacy_config, planogram_type="product_on_shelves")
    assert legacy_config == before


def test_fixed_quantity_seeds_facings_and_range_is_unresolved(legacy_config): ...


def test_promotional_product_becomes_zone_with_zone_present_binding(legacy_config): ...


def test_nested_illumination_and_text_become_bindings(legacy_config): ...


def test_fact_tags_are_not_facings(legacy_config): ...


def test_non_pos_type_rejected():
    with pytest.raises(ValueError):
        convert_config({}, planogram_type="graphic_panel_display")


def test_check_row_legacy_type_is_ok():
    assert check_row({"config_name": "x", "planogram_type": "product_counter"}).ok


def test_check_row_flags_missing_and_invalid_definition(): ...


def test_preflight_sql_is_select_only():
    assert _PREFLIGHT_SQL.lstrip().upper().startswith("SELECT")
    assert not any(w in _PREFLIGHT_SQL.upper() for w in ("UPDATE", "INSERT", "DELETE", "ALTER"))


def test_cli_convert_exit_code_two_when_unresolved(tmp_path, legacy_config): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3448-config-migration-tooling-runbook.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
