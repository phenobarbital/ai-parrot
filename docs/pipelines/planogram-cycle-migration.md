# Planogram compliance — migrating configurations to the new cycle (FEAT-574)

## Who needs this

Only configurations whose `planogram_type` is a **migrated** type need a migration:
`product_on_shelves` and `ink_wall`. Both declare `requires_slots_definition = True`, so a row
without a valid `slots_definition` now fails at construction with a `ValueError` that points
here. `ink_wall` definitions are authored by hand (see
`docs/pipelines/planogram-compliance-cycle.md`); `product_on_shelves` rows can start from the
candidate conversion described below.

The unmigrated types — `graphic_panel_display`, `product_counter`,
`endcap_no_shelves_promotional`, `endcap_backlit_multitier` — keep running the legacy sequence
through the legacy adapter. They need nothing new except their two prompts
(`roi_detection_prompt`, `object_identification_prompt`), which became nullable in the table:
a legacy row with a NULL prompt now fails fast at construction instead of degrading silently.

## What changes in scores (read before comparing old and new numbers)

Scores of migrated types are **not comparable** with the legacy numbers:

- **Every expected facing stays in the denominator.** A shelf scores
  `Σ credit(facing) / |expected facings|`; a partial photo can no longer reach 100 % by leaving
  unseen positions out.
- **Weights are normalised.** The legacy non-header defaults (product 0.8, text 0.1, visual 0.2)
  summed to 1.1 and the result was silently clamped to 1.0. Migrated types divide by the sum of
  the weights of the terms that actually apply to the shelf, so `(0.9·0.8 + 0.1 + 0.2) / 1.1 =
  0.927` instead of the legacy clamped `1.0`.
- **Strict and lenient credits.** `match` earns 1.0; `misplaced`, `variant_unresolved` and
  `inferred_present` earn 0.5 only in the lenient score (the value `compliance_score` reports);
  `strict_compliance_score` is reported next to it.
- **Coverage is separate from compliance.** `coverage` is resolved facings / expected facings;
  `evidence_quality` describes how strong the deciding observations were and never changes a
  credit.
- **Inconclusive is not compliant.** A shelf with unresolved facings is never `COMPLIANT`, and
  `overall_compliant` is `False` whenever `assessment_status != "complete"`.
- **Unseen ≠ missing.** `missing_products` lists only facings proven empty (plus illumination
  pseudo-entries); a product that simply was not visible is `not_visible`, not missing.
- **An empty result list is never a pass** — for every type, legacy included.

## Sequence

1. **Apply the idempotent ALTER script** `alter_planograms_configurations_feat574.sql` (shipped as
   package data next to `table.sql`). It adds the nullable `slots_definition` / `llm_backend`
   columns and drops `NOT NULL` from both prompt columns; it is safe to run more than once.
2. **Export** each active configuration (the whole row or just its `planogram_config` JSON) and run
   the candidate conversion:

   ```bash
   python -m parrot_pipelines.planogram.migration convert exported_row.json --out candidate.json
   ```

   The output holds `candidate` (a slots definition), `bindings` (rule bindings), `unresolved`
   and `warnings`. The command exits with code `2` while anything is unresolved, so a script can
   never mistake a candidate for a finished migration. It never overwrites its input.
3. **Review the candidate.** Resolve every `unresolved` item (quantity ranges become one
   placeholder facing — decide the real count), confirm the slot order (taken from the product
   list order), author descriptors (`display_name`, `identifiers`, `family`, …: the converter
   never invents them) and review the generated `rule_bindings` (illumination, text
   requirements, visual features, zone presence).
4. **Backfill** `slots_definition` and `planogram_config.rule_bindings` with a user-applied
   `UPDATE`. Keep the original `planogram_config` JSON: thresholds, shelf weights and
   `advertisement_endcap` stay where they are, and `shelves[].products` is never removed.
5. **Run the read-only preflight** until every migrated row is `ok`:

   ```bash
   python -m parrot_pipelines.planogram.migration preflight --dsn "$PLANOGRAM_DSN"
   ```

   It issues a single `SELECT` and reports missing or undecodable definitions, invalid
   definitions and dangling bindings; it exits with `2` while any row fails.
6. **Deploy** the new runtime. Optionally set `llm_backend` (`"provider:model"`) per row; without
   it the package default is used.

## Rollback

Redeploy the previous version. The new columns are nullable and ignored by it, the prompt
columns still hold their values (the ALTER only relaxed `NOT NULL`), and the original
`shelves[].products` of every config were never removed — nothing needs to be restored in the
database.

## Process-pool sizing under gunicorn

`PlanogramCompliance(cpu_workers=2)` creates a spawn-based process pool **per run** inside each
gunicorn worker, so the machine can hold up to `gunicorn workers × concurrent runs ×
cpu_workers` extra Python processes. Each process that runs local OCR loads the RapidOCR ONNX
models on first use (hundreds of MB), so budget memory accordingly: for example 4 gunicorn
workers × 1 run × 2 CPU workers = 8 processes, each with its own OCR models. Lower `cpu_workers`
(or leave the `ai-parrot-pipelines[planogram]` extra uninstalled, which disables local OCR) on
small hosts. `llm_concurrency` bounds concurrent vision calls per run.

## Troubleshooting

| Message at construction | Fix |
|---|---|
| `… requires a slots_definition; see the FEAT-574 planogram cycle migration runbook …` | Backfill the row (steps 2-5). |
| `… uses the legacy contract and requires 'roi_detection_prompt' …` (or the other prompt) | A legacy-type row lost a prompt: restore it. |
| `SlotsDefinitionError: … slots must be exactly 1..n …` / duplicate ids / zero described positions | Fix the definition JSON and re-run preflight. |
| `SlotsDefinitionError: rule … dangling target_id …` | A binding targets an id that is not in the definition. |
| `llm_backend must be 'provider:model' …` | Fix or clear `llm_backend`. |
