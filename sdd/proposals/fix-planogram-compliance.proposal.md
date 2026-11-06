---
id: FEAT-826
title: "Redeliver the Office Depot EcoTank End Cap planograms (Backlit / Not Backlit) on the perceive → identify → compare cycle"
slug: fix-planogram-compliance
type: feature
mode: investigation
status: review
source:
  kind: jira
  jira_key: NAV-7762
  jira_url: https://trocglobal.atlassian.net/browse/NAV-7762
  fetched_at: 2026-11-06
  summary_oneline: "Epson360 Planogram Compliance — Office Depot EcoTank End Cap Backlit / Not Backlit planograms (Reopened 2026-10-21)"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-pipelines, flowtask]
tags: [planogram, epson360, office-depot, config-migration, compliance-report, zone-only-endcap]
research_state: sdd/state/FEAT-826/
created: 2026-11-06
updated: 2026-11-06
---

# FEAT-826 — Redeliver the Office Depot EcoTank End Cap planograms on the new cycle

> **Mode**: investigation
> **Confidence**: medium
> **Source**: [NAV-7762](https://trocglobal.atlassian.net/browse/NAV-7762)
> **Audit**: [`sdd/state/FEAT-826/`](../state/FEAT-826/)

---

## 0. Origin

The full source (Jira metadata, changelog, comments, and the evidence extracted from the twelve
attachments) is at `sdd/state/FEAT-826/source.md`.

> Create two planogram types in the Epson360 Planogram Compliance module for Office Depot related to
> EcoTank End Cap displays. Additionally, update the name of the existing "EcoTank End Cap" planogram to
> clearly distinguish it as the Backlit version. […]
>
> **Compliance Components (for the Not Backlit Planogram)** — Top Graphic is present · Top Graphic is
> correct image · Middle Graphic is present · Bottom Graphic is present. […]
>
> **Acceptance Criteria** — The existing Office Depot planogram "EcoTank End Cap" is renamed to "EcoTank
> End Cap Backlit." · A new planogram "EcoTank End Cap Not Backlit" is created for Office Depot. · The new
> planogram includes the [four] compliance checks. · Attached images are used as reference for the display
> structure. · Both planograms appear correctly in the Planogram Compliance module for Office Depot. · No
> existing planogram compliance records are broken by the rename.

**Initial signals** (extracted, not interpreted):
- Verbs: "create", "rename" in the ticket text; status **Reopened** (2026-10-21, by the assignee, with no
  comment); the invocation calls the work a "fix".
- Named entities: Epson360, Office Depot, "EcoTank End Cap Backlit", "EcoTank End Cap Not Backlit", media
  tags "Office Depot EcoTank End Cap (Backlit)" / "(Non-Backlit)"; from the attached logs,
  `planogram_id` 23 / 24 and `config_name` `epson_depot_ecotank_backlit_planogram_config` /
  `epson_depot_ecotank_not_backlit_planogram_config`.
- Components / labels: Epson360 · Planograms · parent NAV-6184.
- Acceptance criteria provided: yes (6).
- From the attachments: the ticket was resolved on 2026-03-17 on the legacy "Pure-LLM" pipeline. The
  Not Backlit run scored 100 %. The Backlit run attached as "executed without errors" scored **32 %**
  with zero detections.

---

## 1. Synthesis Summary

NAV-7762 asked for two Office Depot EcoTank end-cap planograms and was closed in March with rows in the
legacy configuration format. That format no longer runs: both the pipeline constructor
(`PlanogramCompliance.__init__`) and the FlowTask consumer (`PlanogramCompliance._build_planogram_config`)
reject a row without `slots_definition`. The replacement rows were written by hand on 2026-10-15, but they
exist only in a local database and in two git-ignored scripts (`artifacts/apply_epson_backlit.py`,
`artifacts/apply_epson_not_backlit.py`); nothing tracked names either configuration, and no validation
result is kept. The user confirmed that the ticket was reopened to redeliver both planograms on the new
cycle and that production already runs the new runtime with these rows not migrated, so their tasks fail
with `ConfigError`. Beyond the rows, the report users read in Epson360 (built by FlowTask's
`PlanogramCompliance._create_markdown_report`) no longer shows the four checks the ticket asks for, and
the migration preflight (`check_row`) skips a validation the runtime enforces. The recommendation is a
spec that delivers reviewed, tracked, ticket-minimal rows for both planograms, closes the preflight gap,
itemises the checks in the report across both repositories, and adds the regression coverage that does
not exist today.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted at
> `sdd/state/FEAT-826/findings/`. Each cites the finding ID(s) that justify its inclusion.
> `P/` abbreviates `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/`; `flowtask:` marks a
> path in the sibling FlowTask repository (cited in the findings by its on-disk path).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `P/plan.py` | `PlanogramCompliance.__init__` | 121-130 | resolves the type handler; refuses a row whose `slots_definition` is missing | F005 |
| 2 | `P/plan.py` | `PlanogramCompliance._load_definition` | 201-210 | loads the definition; only production caller of `validate_zone_selectors` | F005, F006 |
| 3 | `P/plan.py` | `PlanogramCompliance._assemble` | 493-532 | result contract: eight legacy keys plus additive keys, no markdown | F014 |
| 4 | `P/types/endcap_no_shelves_promotional.py` | `EndcapNoShelvesPromotional.default_layout_profile` | 66-84 | type of both rows; default `perception_mode` is `cv` | F006 |
| 5 | `P/layout.py` | `LayoutProfile` | 66-129 | per-row override: `perception_mode`, `roi_detection`, `roi_zone_labels` | F006 |
| 6 | `P/layout.py` | `validate_zone_selectors` | 209-242 | selector validation for repeated zone kinds; not run by the preflight | F006 |
| 7 | `P/comparison/rules.py` | `evaluate_rules` | 738-754 | dispatch of the six rule kinds available to a zone | F008 |
| 8 | `P/comparison/rules.py` | `_rule_zone_present` | 325-373 | "graphic is present"; unassessed, not failed, when visibility is unknown | F008 |
| 9 | `P/comparison/rules.py` | `_rule_illumination` | 391-438 | backlit ON vs OFF: `params.required` = `on` / `off`, penalty on mismatch | F008 |
| 10 | `P/comparison/rules.py` | `_rule_visual` | 550-590 | keyword-overlap visual check; closest thing to "correct image" for a zone | F008 |
| 11 | `P/comparison/rules.py` | `_rule_appearance` | 441-501 | closed-vocabulary colour / finish check (FEAT-683) | F008 |
| 12 | `P/comparison/scoring.py` | `score_shelves` | 311-434 | zone-shelf score: presence / text / visual weights, illumination multiplier | F010 |
| 13 | `P/comparison/scoring.py` | `summarize` | 437-494 | zone-only run is INCONCLUSIVE unless every listed rule was assessed | F010 |
| 14 | `P/comparison/definition.py` | `_normalise_zone_shelves` | 341-362 | each unowned zone becomes a virtual shelf `zone:<zone_id>`, level `None` | F020 |
| 15 | `P/comparison/projection.py` | `project_compliance` | 139-176 | projects zone shelves into the per-shelf result the report reads | F020, F031 |
| 16 | `P/comparison/projection.py` | `finalize_comparison` | 181-202 | `overall_compliant` only when complete and every shelf compliant | F020 |
| 17 | `P/migration.py` | `check_row` | 698-739 | migration preflight verdict used by the apply scripts and the migrate command | F012 |
| 18 | `P/migration.py` | `_convert_zones_only` | 408-440 | mechanical converter for promotional endcaps | F012 |
| 19 | `P/migration.py` | `_product_rules` | 202-218 | emits an `illumination` binding only from `illumination_required` | F012 |
| 20 | `P/identification/references.py` | `select_references` | 80-87 | reference images feed product identification only, never zones | F011 |
| 21 | `P/identification/evidence.py` | `build_zone_prompt` | 75-77 | asks for illumination only when the zone has an `illumination` binding | F013 |
| 22 | `flowtask:flowtask/components/PlanogramCompliance.py` | `PlanogramCompliance._build_planogram_config` | 250-289 | consumer: `ConfigError` without `slots_definition`; type from the row column | F018 |
| 23 | `flowtask:flowtask/components/PlanogramCompliance.py` | `PlanogramCompliance._create_markdown_report` | 538-622 | builds the report shown in Epson360: per shelf, tick only at score 1.0, no rule outcomes | F018 |
| 24 | `artifacts/apply_epson_backlit.py` | `ZONES` | 45-49 | git-ignored script with the rewritten Backlit row (3 zones, `llm_detector`, illumination `on`) | F002 |
| 25 | `artifacts/apply_epson_not_backlit.py` | `ZONES` | 40-45 | git-ignored script with the rewritten Not Backlit row (4 zones, illumination `off`) | F003 |
| 26 | `examples/planogram/e2e/main.py` | `main` | 476-493 | per-config e2e runner; reads the active row from the `ENV` database | F016 |
| 27 | `packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py` | (test functions) | 120-227 | generic type tests; no fixture of either EcoTank row | F015 |
| 28 | `.claude/commands/planogram-migrate.md` | (Ground rules) | 28-48 | the sanctioned migration procedure (preflight → export → convert → render → apply) | F017 |
| 29 | `sdd/migrations/FEAT-096-planogram15-config.sql` | `FEAT-096` | — | precedent: a planogram row change committed as SQL with its feature | F030, F022 |

### 2.2 Constraints Discovered

- **New-format rows only.** `PlanogramCompliance.__init__` and FlowTask's `_build_planogram_config` both
  refuse a row without `slots_definition` before any image is processed.
  *Implication*: there is no fallback to the March configuration.
  *Evidence*: F005, F018

- **The type is the column.** `planogram_type` is read from the row column, never from
  `slots_definition.meta`; the apply scripts write only the meta copy.
  *Implication*: any row artefact must set or verify the column value `endcap_no_shelves_promotional`.
  *Evidence*: F007, F018

- **`config_name` is the only stable key.** `planogram_id` is 9 / 3 in the exported database and 23 / 24 in
  the ticket's production logs.
  *Implication*: every SQL statement and fixture is keyed by `config_name`.
  *Evidence*: F019, F021

- **Rows are hand-applied data.** FEAT-612 and FEAT-683 exclude automatic SQL application, and the migrate
  command requires an explicit confirmation naming the target database for its two writing steps.
  *Implication*: the feature ships reviewed artefacts and a procedure; it does not write to dev or
  production on its own.
  *Evidence*: F030, F012, F017

- **Preflight gap.** `check_row` does not run `validate_zone_selectors`; only the pipeline constructor does,
  and both apply scripts gate their UPDATE on `check_row` alone.
  *Implication*: a row can pass preflight and still fail at construction. Both EcoTank rows have repeated
  zone kinds and so depend on selectors.
  *Evidence*: F012, F006, F002

- **Mandatory rules and inconclusive runs.** Every required zone needs a mandatory `zone_present` binding,
  and one unassessed mandatory rule makes the run INCONCLUSIVE, which can never be compliant.
  *Implication*: each extra mandatory rule is another way for a correct display to end not compliant.
  *Evidence*: F006, F010, F020

- **No image comparison for zones.** No rule compares a zone with a reference image; reference images feed
  product identification only.
  *Implication*: "Top Graphic is correct image" is approximated by text, keyword visual features and
  illumination (accepted by the user, §5).
  *Evidence*: F008, F011

- **Thresholds changed silently.** Zone shelves are projected with level `None`, so the default threshold
  and default weights apply instead of the legacy per-level 0.95 / 0.9.
  *Implication*: the compliance cut-off for these planograms needs an explicit decision.
  *Evidence*: F020, F010

- **The report lives in another repository.** FlowTask builds it per shelf: a shelf is ticked only at
  score 1.0, rule outcomes go only to the JSON report, the projection never fills
  `text_compliance_results`, and `products_found` is off for this type by documented policy.
  *Implication*: naming the four checks in the UI needs a change in the projection and in the FlowTask
  renderer, i.e. a cross-repository change.
  *Evidence*: F018, F031, F032, F020

- **Additive only.** The eight legacy result keys must be preserved.
  *Evidence*: F014, F006

- **Nothing unreleased in source.** No planogram source differs between `origin/main` and `origin/dev`; the
  2026-10-15 fixes are first tagged in 1.2.3 and the optional-zone scoring fix in 1.2.5.
  *Implication*: what is pending for production is data and deployment; the worker needs
  ai-parrot-pipelines 1.2.5 or later.
  *Evidence*: F023, F028, F010

- **The converter cannot produce these rows.** The type defaults to `cv` perception, and `convert_config`
  never sets `llm_detector`, never emits `appearance`, and emits `illumination` only from
  `illumination_required` (the legacy rows encode it as free text).
  *Implication*: the rows are authored by hand and reviewed.
  *Evidence*: F006, F012, F024

- **No regression coverage.** No test or fixture exercises either configuration; the per-config e2e runner
  reads the row from whichever database `ENV` selects.
  *Evidence*: F015, F016, F001

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `321c9883a3` | 2026-11-05 | Jesus | feat(github-wiki-technical-reference): TASK-5172 — move technical docs to wiki/ | planogram docs, `examples/planogram/e2e/` |
| `dda9a3ed2a` | 2026-10-27 | Jesus Lara | fix(ci): repair nightly setup and package regressions | `comparison/scoring.py` (`score_shelves`), `perception/rows.py` |
| `e168ddc9f2` | 2026-10-15 | Jesus Lara | feat(comparison-rules-fixes-2): TASK-4368 — per-requirement text features | `comparison/rules.py` |
| `dd059bfa79` | 2026-10-15 | Jesus Lara | feat(planogram-appearance-rule): TASK-4362 — engine-committed coder deliverable | appearance rule (FEAT-683) |
| `b1d8d506dc` | 2026-10-15 | Jesus Lara | fix(planogram): coerce out-of-vocabulary appearance answers to unknown | appearance evidence |
| `4aae7d9738` | 2026-10-01 | Jesus Lara | feat(refactor-planogram-compliance): TASK-3867 — engine-committed coder deliverable (type moved to the staged cycle, FEAT-612) | `types/endcap_no_shelves_promotional.py` |

- 53 commits touch the planogram package since 2026-10-01; after 2026-10-15 only the first two rows above.
  **No planogram code changed between 2026-10-16 and 2026-10-26**, so no code regression explains the
  reopen of 2026-10-21 (F010).
- `origin/main..origin/dev` on the planogram path is 0 commits (F023). Tag 1.2.3 (2026-10-16) is the
  first containing `e168ddc9f2`; `dda9a3ed2a` is first in 1.2.5 (F028).
- `migration.py` has not changed since 2026-10-01 (F024).
- No commit on any branch names NAV-7762 or either configuration (F022).
- Local, untracked history (F021): the Not Backlit row went from 3 mechanical zones to 4 zones on
  2026-10-15 16:05Z; the Backlit row was rewritten at 17:17Z and gained `llm_detector` at 17:35Z.

---

## 3. Hypothesis

### Hypothesis 1 — The March deliverable cannot run on the current runtime and its replacement was never delivered  · Confidence: medium

**Supporting evidence**: F005, F018, F001, F002, F003, F019, F021, F023, F028
**Contradicting evidence**: —
**Reasoning**: Both the pipeline and FlowTask reject a row without `slots_definition`, and the only
new-format versions of the two rows are local: two git-ignored scripts and a local database, with no
tracked artefact, no retained validation result and no recorded path to production. The rewrite
(2026-10-15), tag 1.2.3 (2026-10-16) and the reopen (2026-10-21) line up, with no code change in between.
Research alone leaves this at medium because no artefact records the reopen reason and no database was
contacted. **The user confirmed both points** (§5, U1 and U2): the ticket was reopened to redeliver on the
new cycle, and production runs the new runtime with these rows not migrated, so their tasks fail with
`ConfigError`.

**Suggested next probe** (read-only, on the production database):
```sql
SELECT config_name, planogram_id, planogram_type,
       slots_definition IS NOT NULL AS migrated, updated_at
FROM troc.planograms_configurations
WHERE config_name LIKE 'epson_depot_ecotank_%backlit%';
```
and check the `ai-parrot-pipelines` version installed on the Epson360 FlowTask worker (needs ≥ 1.2.5).

### Hypothesis 2 — On the new cycle the planograms no longer report what the ticket asks  · Confidence: medium

**Supporting evidence**: F018, F020, F031, F032, F002, F003, F010
**Contradicting evidence**: F032 (the empty product list is documented policy, so part of this is by design)
**Reasoning**: The report names zones (`ZONE:ZONE-HEADER-1`) instead of the four requested checks, prints
no text or product evidence for zone shelves, and ticks a shelf only at score 1.0, so a compliant zone
scoring between its threshold and 1.0 shows a cross under an overall tick. Separately, the rewritten rows
make text, visual, illumination and appearance rules mandatory on every zone and split the Not Backlit
top into two zones, so a photo can fail on a rule the ticket never requested. All of this is read from
code and from the row scripts; none of it was observed in a run, because no result of the rewritten rows
is kept (F021).

**Suggested next probe** (local database up):
```bash
python examples/planogram/e2e/main.py epson_depot_ecotank_backlit_planogram_config --output-dir <new dir>
python examples/planogram/e2e/main.py epson_depot_ecotank_not_backlit_planogram_config --output-dir <new dir>
# read per-zone status, score and assessment_status for each of the 12 photos
```

### Hypothesis 3 — The Backlit planogram never produced a correct result  · Confidence: low

**Supporting evidence**: F006, F002, F014, F018
**Contradicting evidence**: F002 (the rewritten Backlit row already sets `llm_detector`)
**Reasoning**: The run attached when the ticket was resolved scored 32 % with zero detections (source).
In the type's default `cv` mode a lit lightbox can satisfy the poster profile, so the ROI step is skipped.
If the rewritten row is what runs, this cause is addressed; it still has to be shown on real photos.

**Suggested next probe**: in `epson.compliance_photo_reports`, the share of non-compliant rows for
"EcoTank End Cap Backlit" since 2026-03-17 and their `detection_source`.

### Direction implied by the findings and the answers in §5

Not a design; the list a spec would turn into modules and acceptance criteria.

1. **Ticket-minimal rows for both configurations** (U3, U4), keyed by `config_name`, with the
   `planogram_type` column set to `endcap_no_shelves_promotional` and `perception_mode: llm_detector`:
   presence mandatory for every graphic; text, visual keywords and backlight state (`on` for Backlit,
   `off` for Not Backlit) mandatory on the top graphic only; everything else informative.
2. **A tracked, reviewed row artefact** instead of git-ignored scripts, applied by hand through the
   existing migrate procedure. Precedent: `sdd/migrations/FEAT-096-planogram15-config.sql`. Production is
   failing today (U2), so this part is the urgent one and does not depend on items 4 and 5.
3. **Preflight parity**: `check_row` runs the same `validate_zone_selectors` the constructor runs.
4. **Report itemisation in both repositories** (U5): ai-parrot exposes per-zone check outcomes with
   readable names through additive result fields; FlowTask's `_create_markdown_report` prints them and
   derives the per-zone tick from the compliance status rather than from score 1.0. The FlowTask half needs
   its own change in that repository.
5. **Regression coverage**: a committed fixture of both rows with an offline test (preflight, selector
   validation, scoring from synthetic evidence) and expected outcomes for the local store photos in the
   opt-in live e2e suite.
6. **Runbook correction**: the stale `docs/pipelines/` path and the "ROI prompt is ignored" statement.

Out of scope: a rule that compares a zone with reference artwork (U4), automatic application of SQL to
any database, and changes to other planograms' rows.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The pipeline and the FlowTask component both refuse a row without `slots_definition`. | F005, F018 | high | both raise statements read directly |
| C2 | The row format attached to the ticket in March is the legacy format that current code rejects. | F005, F018, F019 | high | ticket logs print the legacy keys; the 2026-10-01 exports show the same shape before conversion |
| C3 | The rewritten rows exist only in git-ignored scripts and a local database; nothing tracked names either configuration. | F001, F002, F003, F021 | high | unfiltered grep plus direct reads of the scripts and backups |
| C4 | Both rows use the type `endcap_no_shelves_promotional`, taken from the `planogram_type` column. | F019, F021, F007 | high | column value read from the exports; precedence read in four readers |
| C5 | `zone_present` covers "graphic is present"; the two planograms differ by one parameter, `illumination.params.required` = `on` vs `off`. | F008, F002, F003 | high | rule code and both row scripts read directly |
| C6 | No rule compares a zone with a reference image; "correct image" can only be approximated. | F008, F011 | high | six rule kinds enumerated; `references.py` has no zone handling. *User decision (U4): the approximation is accepted.* |
| C7 | No spec or task plans an image-similarity rule for zones. | F032 | low | one lexical wiki query returned nothing |
| C8 | `check_row` skips `validate_zone_selectors`, and both apply scripts gate on `check_row` alone. | F012, F006, F002 | high | call sites enumerated; script flow read |
| C9 | The UI report is built in FlowTask per shelf; rule outcomes, text requirements and product lists are absent for these rows. | F018, F031, F032, F020 | high | renderer and projection read directly. *User decision (U5): itemise in both repositories.* |
| C10 | A compliant zone scoring between its threshold and 1.0 prints a cross under an overall tick. | F018, F020 | medium | follows from two code reads; the 0.8 default was taken from a docstring; not observed in a run |
| C11 | No planogram source differs between `origin/main` and `origin/dev`. | F023 | high | rev-list count 0; ancestry checked for five commits |
| C12 | The 2026-10-15 fixes ship in tag 1.2.3 and the optional-zone scoring fix in 1.2.5. | F028, F010 | medium | verified for one commit per tag; the other two inferred from same-day linear history |
| C13 | The rewritten rows enforce more than the ticket asks. | F002, F003 | high | rule tables read from both scripts. *User decision (U3): ticket-minimal.* |
| C14 | The ticket was reopened to deliver the planograms again on the new cycle. | F010, F021, F028 | low | timing only. *Confirmed by the user (U1); the research confidence stays low because no artefact records it.* |
| C15 | The production rows have not received the hand-rewritten configuration. | F019, F021 | low | no database contacted. *Refined by the user (U2): production runs the new cycle and these rows have no `slots_definition`.* |
| C16 | No result of the rewritten rows on the 12 local photos is retained. | F021, F004 | high | the only result folders date from 2026-10-01, before the rewrite |
| C17 | The row `description` holds "EcoTank End Cap (Backlit)" / "(Non-Backlit)", not the names the ticket asks for; where Epson360 reads the name is not in this repository. | F021 | medium | read from one export of one database; UI source not found |
| C18 | No test or fixture covers the two configurations. | F015, F001, F016 | high | grep and test listing |
| C19 | The mechanical converter cannot produce these rows. | F012, F006, F024 | high | converter code read; module unchanged since 2026-10-01 |
| C20 | The migration runbook is stale (old `docs/pipelines/` path; says the ROI prompt is ignored while `LayoutProfile` uses it). | F012, F006, F018 | medium | path checked in one lane; the contradiction is between a doc line and a field docstring |

Distribution: **13** high, **4** medium, **3** low.

> The three low claims are C7 (not load-bearing after U4), and C14 / C15, which the user confirmed. The
> overall confidence is nonetheless held at **medium**: the git research was truncated, and nothing in
> this proposal was observed in a pipeline run.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Why was NAV-7762 reopened on 2026-10-21?** — *Resolved*: Redeliver on new cycle — planograms
  23/24 must work on the perceive/identify/compare cycle; their rows are not in production yet.
  *Resolves claims*: C14
- [x] **U2 — What runs in production today for config rows 23/24, and is the Epson360 FlowTask worker on
  the new cycle?** — *Resolved*: New runtime, not migrated — production runs the new cycle but these rows
  have no `slots_definition`, so the tasks fail with `ConfigError`.
  *Resolves claims*: C15, C12 (the worker version itself is still to be read, see below)
- [x] **U3 — How strict should the two planograms be?** — *Resolved*: Ticket-minimal — presence is
  mandatory for every graphic; identity checks (text, visual, backlight) are mandatory only on the top
  graphic; middle and bottom extras become informative.
  *Resolves claims*: C13
- [x] **U4 — Is text + keyword + backlight evidence acceptable for "Top Graphic is correct image"?** —
  *Resolved*: Text + keywords suffice — no new rule kind.
  *Resolves claims*: C6, C7
- [x] **U5 — Should the Epson360 report name each requested check per graphic?** — *Resolved*: Itemise,
  both repos — ai-parrot exposes per-zone check outcomes with readable names; flowtask's report prints
  them and fixes the per-zone tick.
  *Resolves claims*: C9, C10

### Unresolved (defer to spec / implementation)

- [ ] **Which zone is the Not Backlit "Top Graphic"?** — *Owner*: Mylene Lopez (reporter)
  The reference rendering and the store photos show a header strip above the Shaq panel; the rewritten row
  models them as two zones while the ticket names three graphics. The header strip also reads "EcoTank
  Cartridge-Free Printers" in the rendering and "EcoTank Printers" in the store photos.
  *Blocks claims*: C13
  *Plausible answers*: a) the Shaq panel is the top graphic and the header strip is informative ·
  b) header strip + Shaq panel form one top zone · c) both are required graphics (four checks become five)
- [ ] **Compliance threshold for zone shelves** — *Owner*: tbd
  The default applies today instead of the legacy 0.95 / 0.9.
  *Blocks claims*: C10
  *Plausible answers*: a) keep the default · b) restore the legacy per-graphic thresholds through the row
- [ ] **Where does Epson360 read the planogram name?** — *Owner*: Jonathan Uzcategui (assignee)
  Needed for the rename acceptance criterion and "no existing compliance records are broken by the rename".
  *Blocks claims*: C17
  *Plausible answers*: a) the row `description` · b) a table or view outside this repository
- [ ] **Worker version and ordering of the FlowTask change** — *Owner*: tbd
  The installed `ai-parrot-pipelines` version on the Epson360 worker (≥ 1.2.5 needed), and whether the
  FlowTask report change ships with this feature or as a follow-up in that repository.
  *Blocks claims*: C12

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-826`** — *Rationale*: the user's answers closed the three scope forks (ticket-minimal
rules, no artwork-comparison rule, report itemised in both repositories) and confirmed the reopen reason
and the production state; localization is high-confidence. Before the Q&A the synthesis recommended
`/sdd-brainstorm` (medium confidence, truncated git research, three open product decisions); that
recommendation is superseded by the answers and is kept in `synthesis.json` for the record.

Production is failing for these two planograms today (U2). The row delivery (item 2 of §3 "Direction") is
a data operation that can be validated and applied through the existing migrate procedure without waiting
for the report work.

### Alternatives

- **`/sdd-brainstorm FEAT-826`** — if the report itemisation should be explored first (which fields
  ai-parrot adds, how FlowTask renders them, how other zone-only planograms are affected).
- **`/sdd-brief NAV-7762`** — if only the urgent part is wanted now: validated rows for the two
  configurations applied to production, with the preflight, report and coverage work left to a later
  feature.
- **Manual review** — the git research was truncated (two follow-ups in the FlowTask repository were not
  run) and no pipeline run was observed; a reviewer who wants either can start from §7.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-826/state.json` |
| Source (raw) | `sdd/state/FEAT-826/source.md` |
| Research plan | `sdd/state/FEAT-826/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-826/findings/F001-*.md` … `F032-*.md` |
| Lane originals, merge and citation reports | `sdd/state/FEAT-826/findings/.audit/` |
| Synthesis (JSON) | `sdd/state/FEAT-826/synthesis.json` |
| Synthesis reasoning | `sdd/state/FEAT-826/synthesis.thinking.log` |

**Budget consumed** (profile `loose`, raised at the plan gate):
- Files read: 33 / 100
- Grep calls: 42 / 60
- Git calls: 21 / 20
- Wall time: 689 s / 900 s (three parallel lanes: codebase 689 s, wiki 585 s, git 190 s)
- Truncated: **yes** — the git budget was exhausted (20 calls in the git lane plus one `git log -1` in
  the FlowTask repository by the codebase lane). Two git follow-ups in the FlowTask repository (history of
  the `slots_definition` requirement and of the report renderer) were not run. All 35 planned queries
  executed.

**Research execution**:
- 40 lane findings (23 codebase, 8 git, 9 wiki) merged into 30 canonical findings; two follow-ups by the
  orchestrator added F031 and F032.
- Merge rule applied: findings from different lanes that cite the same symbol with overlapping lines were
  merged; a duplicate citation inside one lane was kept in the earlier finding and replaced by a pointer
  note in the later one (6 citations), instead of merging ten findings into one. Details in
  `findings/.audit/merge_report.json`.
- Citation check: 299 deterministic checks (file, line range, symbol, excerpt anchor, commit) run by an
  inline script rather than by `sdd-contract-probe` agents; 291 passed directly and 8 were flagged and then
  confirmed by reading the source (reflowed excerpts and one dict-literal symbol). Report in
  `findings/.audit/citation_probe.json`.
- No database was contacted: the local Postgres container was stopped, and neither dev nor production was
  queried. Statements about production come from the user (§5), not from research.
- The FEAT-ID was reserved late: `reserve_ids` refuses a checkout with another session's uncommitted
  changes, so the research ran id-less and FEAT-826 was reserved from a clean clone of `origin/dev` before
  rendering.

**Mode determination**: `auto` → resolved to `investigation` (status Reopened, a "fix" in the requested
slug, and the attached Backlit run at 32 % with zero detections).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara, with Claude Code |
