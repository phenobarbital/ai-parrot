---
kind: brief
slug: ecotank-endcap-rows-new-cycle
key: NAV-7762
base_branch: main
source:
  type: jira
  ref: NAV-7762
  url: https://trocglobal.atlassian.net/browse/NAV-7762
jira_issue_key: NAV-7762
ledger_issue: null
created: "2026-11-06"
---

# Brief: New-cycle rows for the Office Depot EcoTank End Cap planograms (Backlit / Not Backlit)

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/ecotank-endcap-rows-new-cycle/tasks/. -->

## Problem

NAV-7762 ("Epson360: Planogram Compliance – Create Office Depot Planograms: EcoTank End Cap Backlit &
EcoTank End Cap Not Backlit", Story, Major) was resolved on 2026-03-17 and **reopened on 2026-10-21**.
The ticket asks for two Office Depot planograms and, for the Not Backlit one, four checks:

> Top Graphic is present · Top Graphic is correct image · Middle Graphic is present · Bottom Graphic is present

The rows delivered in March (`epson_depot_ecotank_backlit_planogram_config` and
`epson_depot_ecotank_not_backlit_planogram_config`, `planogram_id` 23 and 24 in production) are in the
legacy configuration format. Production now runs the perceive → identify → compare cycle and these two
rows were not migrated, so their Epson360 FlowTask tasks
(`epson.endcap_compliance_ecotank_end_cap_backlit` / `..._not_backlit`) fail with `ConfigError` instead of
producing a compliance result. The reopen reason and the production state were confirmed by the user on
2026-11-06; no production database was queried.

This brief is the urgent part of FEAT-826 (`sdd/proposals/fix-planogram-compliance.proposal.md` on `dev`):
validated rows for the two configurations. The report itemisation, the preflight parity fix and wider
regression coverage stay in FEAT-826.

## Root cause

The new runtime refuses a row without `slots_definition`, and no new-format version of these two rows
was ever delivered.

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:127` —
  `if planogram_config.slots_definition is None:` followed by
  `raise ValueError(... has no slots_definition; convert it as described in {MIGRATION_RUNBOOK})`.
- FlowTask (sibling repository) `flowtask/components/PlanogramCompliance.py:251-252` —
  `if slots_definition is None:` / `raise ConfigError(` — this is the error the Epson360 tasks hit.
- The only new-format versions of the rows are two git-ignored scripts in the main checkout
  (`artifacts/apply_epson_backlit.py`, `artifacts/apply_epson_not_backlit.py`, written 2026-10-15) and a
  local database. Nothing tracked names either configuration, so there is no reviewed artefact to apply
  to production.
- The mechanical converter cannot produce them: it never sets `perception_mode: llm_detector`, and it
  emits an `illumination` rule only from `illumination_required`, while the legacy rows encode the
  backlight as free text.

## Research findings

Full research: `sdd/state/FEAT-826/` on `dev` (32 findings, 299 citation checks). The points this fix
depends on:

- **Type.** Both rows use `planogram_type = endcap_no_shelves_promotional`. The type is read from the row
  **column**, never from `slots_definition.meta`; the 2026-10-15 scripts wrote only the meta copy.
  FEAT-090 left an unticked item to move the EcoTank config off `graphic_panel_display`, so the column in
  production may still hold the old type. The SQL sets it explicitly.
- **Key.** `planogram_id` differs between environments (9 / 3 in the local export, 23 / 24 in production).
  `config_name` is the only stable key.
- **Rules.** "Graphic is present" is the `zone_present` rule. Backlit vs Not Backlit is one parameter:
  `illumination.params.required` = `on` / `off`. There is no rule that compares a zone with reference
  artwork; "correct image" is expressed with `text_requirements` + `visual_features` + `illumination`.
- **Scoring.** In `comparison/scoring.py::score_shelves` (lines 311-434) a non-mandatory text or visual
  rule still enters the zone score. With the default weights a zone whose text and visual rules both miss
  scores 0.73, below the 0.8 default threshold. A truly presence-only zone must therefore carry no text or
  visual binding at all.
- **Perception.** The type defaults to `perception_mode = "cv"`. For these displays a lit lightbox alone
  satisfies the CV poster profile, the ROI step is skipped and the zone bands are computed over the
  lightbox only. Both rows need `layout_profile.perception_mode = "llm_detector"`.
- **Preflight gap.** `migration.check_row` (line 698) does not run `validate_zone_selectors`
  (`layout.py:209`); only `PlanogramCompliance._load_definition` (`plan.py:201-210`) does. Both rows repeat
  the zone kind `graphic`, so they depend on selectors. The new test runs both validations.
- **Geometry kept.** Zones, bands, ROI labels and ROI prompts are taken unchanged from the 2026-10-15
  scripts (run against store photos on 2026-10-15, per that session's notes; no result was kept). Only the rule bindings are reduced. The
  generated ROI prompts were compared with the scripts' `ROI_DETECTION_PROMPT` constants and are identical.
- **Pre-validation.** The two candidate rows built for this brief pass `check_row`,
  `load_slots_definition`, `validate_bindings`, `resolve_layout_profile` and `validate_zone_selectors` on
  the current code; the test file specified in the task passes against them (6 passed) and is `ruff` clean.
  No pipeline run on photos was made with the reduced rule set.
- **Source parity.** `git diff origin/main origin/dev` is empty for the planogram package, so the rows are
  valid for the released code. The worker that runs the compliance needs `ai-parrot-pipelines >= 1.2.5`.
- **Ledger.** `wikitoolkit ledger context` on `migration.py`, `layout.py` and the type test: no relevant
  open issues.
- **Precedent.** `sdd/migrations/FEAT-096-planogram15-config.sql` — a planogram row change committed as
  SQL and applied by hand.

## Decisions

Answers from the user (proposal Q&A and this brief's Q&A, 2026-11-06):

1. **Ticket-minimal rules.** Presence is mandatory for every graphic; identity checks (text, visual
   keywords, backlight) apply to the top graphic only.
2. **Middle and bottom graphics carry only `zone_present`.** Their text, visual and appearance rules are
   removed, because a non-mandatory rule can still take the zone below the threshold.
3. **"Top Graphic is correct image"** is verified by text + visual keywords + backlight state. No
   artwork-comparison rule.
4. **Not Backlit top graphic = header strip + Shaq panel.** Both must be present. The strip is checked by
   its text; the Shaq panel by text, visual keywords and light OFF. This matches the row accepted in March
   and keeps the four-zone geometry.
5. **Header strip wording: accept both artworks.** Require `EPSON`, `EcoTank` and `Printers`, so
   "EcoTank Printers" (store photos) and "EcoTank Cartridge-Free Printers" (reference rendering) both pass.
6. **Backlit top graphic** (the lightbox): text `EPSON`, `Goodbye Cartridges`, `Hello Savings`; visual
   keywords; light ON.

Resulting rule bindings (all mandatory):

| Planogram | Zone | Graphic | Rules |
|---|---|---|---|
| Backlit | `zone-header-1` | lit lightbox (top) | `zone_present`, `illumination: on`, `text_requirements`, `visual_features` |
| Backlit | `zone-comparison-1` | comparison panel (middle) | `zone_present` |
| Backlit | `zone-base-1` | base graphic (bottom) | `zone_present` |
| Not Backlit | `zone-header-1` | header strip (top) | `zone_present`, `text_requirements` |
| Not Backlit | `zone-backlit-1` | Shaq panel (top) | `zone_present`, `illumination: off`, `text_requirements`, `visual_features` |
| Not Backlit | `zone-comparison-1` | comparison panel (middle) | `zone_present` |
| Not Backlit | `zone-base-1` | base graphic (bottom) | `zone_present` |

Not decided here, left as they are: the row `description` (the March screenshot already lists
"EcoTank End Cap Backlit" / "EcoTank End Cap Not Backlit" in Epson360), `llm_backend`, `reference_images`,
and the default zone threshold.

## Fix plan

- **HOTFIX-NAV-7762-1** — Commit the two rows as JSON fixtures, the SQL that applies them
  (`sdd/migrations/NAV-7762-ecotank-endcap-rows.sql`, keyed by `config_name`, one transaction, fails
  unless exactly one active row matches each name), and a test that runs the preflight and the runtime
  validation on the fixtures, asserts the ticket-minimal bindings, and fails when the SQL and the
  fixtures differ.

By hand, after the task is merged (not automated; every database write needs the operator's explicit
confirmation of the target database):

1. Back up both rows (command in the SQL header), then apply the SQL to the **local / dev** database.
2. Run the photos of each configuration through the pipeline and review the per-zone results:
   `python examples/planogram/e2e/main.py epson_depot_ecotank_backlit_planogram_config --output-dir <new dir>`
   and the same for `epson_depot_ecotank_not_backlit_planogram_config`. Expect `detection_source=llm` for
   every photo; a Not Backlit photo run against the Backlit row must fail on the backlight.
3. Check the production worker has `ai-parrot-pipelines >= 1.2.5` and that `llm_backend` on both rows is
   the model the photos were validated with.
4. Back up and apply the SQL to **production**, run the verification query from the SQL header, then run
   the two Epson360 tasks and confirm rows land in `epson.compliance_photo_reports`.
5. Mark the SQL header `Status : APPLIED <date>` in a follow-up commit and resolve NAV-7762.

## Validation commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_nav_7762_ecotank_endcap_rows.py -q`
- `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -q`
