# TASK-3880: Update cycle docs, migration runbook and package README

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3872, TASK-3873, TASK-3874, TASK-3877, TASK-3879
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 15** (documentation half) and **AC19**: "Runbook/release notes cover changed scores,
removed imports, layout/reference policy, migration-before-deployment and rollback". FEAT-574 wrote
`docs/pipelines/planogram-compliance-cycle.md` and `docs/pipelines/planogram-cycle-migration.md` for a
world where four types still ran through a legacy adapter; FEAT-612 migrates all six types, adds
`layout_profile`, the reference bank, OCR auto-enable, expected-empty/zone-only scoring, a six-type
converter, and deletes the legacy pipeline. The package README still advertises `RetailDetector`,
`AbstractDetector`, a wrong Quick Start and a `pytesseract` requirement.

The docs must describe the FINAL behaviour, which is why this task depends on the handler/config
contract (TASK-3872), both removal tasks (TASK-3873, TASK-3874), the converter/preflight (TASK-3877) and
the live harness (TASK-3879). It also fixes a verified stale statement: the runbook says
`misplaced`, `variant_unresolved` and `inferred_present` earn 0.5 lenient credit
(`docs/pipelines/planogram-cycle-migration.md:30`), but the code gives 1.0 to inferred/variant and 0.5
only to misplaced (`contracts.py:259-264`, spec §2 Stage 3 and §6 corrections table).

---

## Scope

- Rewrite `docs/pipelines/planogram-compliance-cycle.md` for the final six-type cycle: stages, fallback
  ownership, layout profile, OCR, references, rule evidence, three-hook type contract, scoring (expected
  empty, zone-only units), result assembly.
- Rewrite `docs/pipelines/planogram-cycle-migration.md` as the FEAT-612 runbook: who is affected (all six
  types), changed scores, removed imports, layout/reference policy, accepted-but-ignored legacy fields,
  deployment order (export → convert → review → human SQL → preflight → deploy), rollback, pool sizing,
  troubleshooting, and the live E2E signoff pointer.
- Update `packages/ai-parrot-pipelines/README.md` for 1.1.0: accurate features/pipelines table, a working
  Quick Start, dependencies without `pytesseract`, optional `[planogram]` extra, links to both docs.
- Correct the stale 0.5 inferred/variant credit statement.

**NOT in scope**: any code, test, `pyproject.toml`, `version.py` or `uv.lock` change (TASK-3881 owns
packaging — keep README consistent with it but do not edit metadata); the live harness README
(`examples/planogram/e2e/README.md`, TASK-3879 — link to it only); assigning the production migration
owner/date (spec §8 open item for Jesus Lara — leave an explicit placeholder line, never invent a name or date);
measured accuracy claims (none exist — spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | Final six-type cycle reference |
| `docs/pipelines/planogram-cycle-migration.md` | MODIFY | FEAT-612 migration runbook + release notes |
| `packages/ai-parrot-pipelines/README.md` | MODIFY | 1.1.0 package README |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Documentation-only task. Snippets placed in the docs must use imports verified at write time, e.g.:
from parrot_pipelines.planogram.plan import PlanogramCompliance  # verified: planogram/plan.py:48
from parrot_pipelines.models import PlanogramConfig  # verified: models.py:32
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:249-265  CreditPolicy.default() (@classmethod at :249, def at :250)
#   MATCH 1.0/1.0; INFERRED_PRESENT and VARIANT_UNRESOLVED strict 0.0 / lenient 1.0 (:259);
#   MISPLACED strict 0.0 / lenient 0.5; everything else 0.0/0.0.
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py:333-372  CLI
#   python -m parrot_pipelines.planogram.migration convert <config.json> [--planogram-type T] [--out F]
#   python -m parrot_pipelines.planogram.migration preflight --dsn <DSN>
#   exit codes: 0 ready, 2 unresolved/failing readiness, 1 usage/I/O error (spec §7)
# packages/ai-parrot-pipelines/src/parrot_pipelines/alter_planograms_configurations_feat574.sql  (package data, exists)
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:134  run(image, output_dir=None, image_id=None, **kwargs)
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:365-389  eight legacy + additive result keys
```

Current document anchors (all `grep -Fxc` = 1):

| File | Heading | Line |
|---|---|---|
| planogram-compliance-cycle.md | `# Planogram compliance cycle (perceive → identify → compare)` | 1 |
| planogram-compliance-cycle.md | `## Overview` / `## Stage contracts` / `## Type hook contract` | 3 / 24 / 39 |
| planogram-compliance-cycle.md | `## Adding a planogram type` / `## Result keys` / `## Optional local OCR` | 63 / 107 / 133 |
| planogram-cycle-migration.md | `# Planogram compliance — migrating configurations to the new cycle (FEAT-574)` | 1 |
| planogram-cycle-migration.md | `## Who needs this` / `## What changes in scores (read before comparing old and new numbers)` | 3 / 18 |
| planogram-cycle-migration.md | `## Sequence` / `## Rollback` / `## Process-pool sizing under gunicorn` / `## Troubleshooting` | 41 / 75 / 82 / 92 |
| README.md | `# AI-Parrot Pipelines` / `## Features` / `## Available Pipelines` / `## Quick Start` / `## Dependencies` | 1 / 11 / 18 / 27 / 42 |

### Symbols created by dependency tasks (not yet on dev) — document only what exists after them
```python
# TASK-3855 layout.py: LayoutProfile, ReferencePolicy, ZoneSelector, resolve_layout_profile(...)
#   key: PlanogramConfig.planogram_config["layout_profile"]; fields per spec §2 table
# TASK-3854 contracts: IdentifyStrategy.SLOTS; FacingStatus.EXPECTED_EMPTY / UNEXPECTED_OCCUPIED; OcrReading; ReferenceImage; RuleObservation
# TASK-3860 definition: FacingDefinition.expected_occupancy ("occupied"|"empty"); Descriptors.attributes;
#   zone kinds graphic/advertisement/counter/information_label; virtual "zone:<zone_id>" score shelves
# TASK-3871 plan.py: enabled_ocr: bool | None = None (None = auto); fallback once per image; LegacyPayload removed
# TASK-3872 models/handler: accepted-but-ignored legacy fields marked; list-valued reference_images hydrated
# TASK-3873/3874: removed modules and names (list in blueprint — re-verify each with grep before writing)
# TASK-3877 migration.py: MIGRATED_TYPES = six keys; ConversionReport.layout_profile; layout-aware preflight
# TASK-3879 examples/planogram/e2e/README.md: live harness usage
```

### Does NOT Exist
- ~~Measured accuracy of the new CV profiles or reference cap~~ — provisional (spec §2, §8); never claim accuracy.
- ~~A DB-writing migration command~~ — the converter never writes; SQL is human-applied (spec §7).
- ~~A `tv_wall` planogram type~~ — not registered (spec §6 corrections); do not document it.
- ~~A compatibility shim for `PlanogramCompliancePipeline` / `RetailDetector` / `AbstractDetector`~~ — removed with no replacement.
- ~~A new DB column for the layout profile~~ — it lives inside the existing `planogram_config` JSON.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/pipelines/planogram-compliance-cycle.md", "action": "MODIFY"},
    {"path": "docs/pipelines/planogram-cycle-migration.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/README.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CreditPolicy.default",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance.run"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Keep the existing documents' voice: short sections, tables for contracts, fenced `bash`/`python` snippets,
and "why" sentences next to every rule. Rewrite in place (same file paths, same H1 subject) so existing
links (`plan.py` error message, handler docs) keep working.

### Key Constraints
- **Verify before you write.** Every class, key, CLI flag, default and removed name must be confirmed with
  `grep` on the feature branch after the dependency tasks landed — *why*: docs that name a non-existent API
  are worse than no docs. If a spec item did not land as specified, document the code and record the
  difference in the Completion Note.
- The missing-definition `ValueError` names `docs/pipelines/planogram-cycle-migration.md` (spec §2
  Overview) — keep that path and file name unchanged.
- Credits: MATCH 1.0; inferred_present and variant_unresolved **1.0 lenient / 0.0 strict**; misplaced
  0.5 lenient; expected_empty 1/1; unexpected_occupied 0/0 (spec §2 Stage 3).
- Scores of four previously-legacy types change meaning — say plainly that old and new numbers are not
  comparable and that new labelled expectations are needed (spec §7 risk table).
- Live E2E: opt-in, not a CI gate; three successful local reports are required for accuracy signoff (AC17).
- Deployment order and rollback text come from spec §7 "Converter details and rollout"; the production
  migration owner/date stays an explicit open line ("Owner/date: to be assigned before deployment").
- No retailer names, store numbers, SKUs or photo names anywhere (public repository).
- Remove the `pytesseract`/Tesseract note from the README; `rapidocr`+`onnxruntime` remain the optional
  `[planogram]` extra (spec M15 skeleton).

### References in Codebase
- `sdd/specs/refactor-planogram-compliance.spec.md` §2 (all subsections), §7 — source of truth for behaviour.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/layout.py` (after TASK-3855) — profile fields/defaults.
- `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` (after TASK-3872) — ignored-field descriptions.

---

## Implementation Blueprint

### Steps (in order)
1. On the feature branch, grep the final code for every symbol in "Symbols created by dependency tasks"
   and for the removed names — *why*: docs must match what shipped, not the spec's intent.
2. Rewrite `planogram-compliance-cycle.md` — *why*: developers read the cycle reference first.
3. Rewrite `planogram-cycle-migration.md` — *why*: AC19 lives here; operators run it before deploying.
4. Update the package README — *why*: it is the PyPI long description for 1.1.0 (`readme = "README.md"`).
5. Run the smoke command and re-read all three files rendered (e.g. `grep -n "0.5"`) — *why*: catch leftovers.

### `docs/pipelines/planogram-compliance-cycle.md` (MODIFY) — REPLACE lines 1-135 (whole file), outline
```text
# occurrences: 1 (verified: grep -Fxc '# Planogram compliance cycle (perceive → identify → compare)' docs/pipelines/planogram-compliance-cycle.md)
# REPLACE — keep this H1 at line 1; rewrite every section below it
- Overview: six types, one template; OpenCV-first perception, OCR + vision-LLM identification, deterministic
  comparison; untouched full-resolution image for all types; per-run CycleContext state.
- Stage contracts table: perceive / fallback (orchestrator-owned, once per image, generic prompt, rebuilt
  geometry, provenance cv|llm|mixed, errors on empty/failed fallback) / identify (full_image|strips|slots,
  OCR readings, reference attachments on initial and repair calls, rule evidence) / compare (pure, no I/O).
- Layout profile: `planogram_config["layout_profile"]` field table from spec §2 with defaults; merge rules
  (recursive models, list replacement, unknown keys rejected); `perception_mode` alias rule; zone selectors
  (ordinal, normalized region, ambiguity ⇒ unassessed); per-type defaults table (spec §2 "Type defaults").
- OCR: auto when the extra is installed; `enabled_ocr=False` disables; own-box crops; absence ≠ empty.
- References: flattening order, `ref-0001` labels, `all`/`by_brand`, cap 5 provisional, diagnostics, cache invalidation.
- Type hook contract: three hooks + `default_layout_profile`; legacy contract removed; `validate_contract` errors.
- Adding a planogram type: rewrite the four steps around `perceive_image` / `identify_image` /
  `compare_observations` and a default profile (replace the InkWall-internals walkthrough).
- Scoring: denominators, credit table (1.0 inferred/variant, 0.5 misplaced), expected-empty, zone-only units
  and coverage, evidence quality, complete vs inconclusive, all-photo failure.
- Result keys: eight legacy keys (first successfully processed image) + additive keys; observed ShelfRegions;
  meaningful product types; no `legacy_unmeasured`/`legacy_llm` in new runs (historical values still parse).
- Links: migration runbook, `examples/planogram/e2e/README.md`.
```
**Why**: the current text documents the legacy adapter and FEAT-574-only defaults (e.g. `enabled_ocr` off,
`slots=[]` after fallback) that FEAT-612 removes; a section-by-section rewrite avoids contradictory leftovers.

### `docs/pipelines/planogram-cycle-migration.md` (MODIFY) — REPLACE lines 1-100 (whole file), outline
```text
# occurrences: 1 (verified: grep -Fxc '# Planogram compliance — migrating configurations to the new cycle (FEAT-574)' docs/pipelines/planogram-cycle-migration.md)
# REPLACE — retitle to "... (FEAT-574, FEAT-612)"; keep the file path
- Who needs this: every active row of all six types; missing slots_definition ⇒ construction ValueError naming this file.
- What changes in scores: keep the still-true FEAT-574 bullets; FIX line 30 (inferred/variant 1.0 lenient,
  misplaced 0.5); add expected-empty statuses, zone-only coverage, threshold enforced with zero facings,
  "four types' numbers are not comparable with legacy".
- Removed imports (release note): list every removed module/name verified by grep (see FILL IN list).
- Layout and reference policy: where `layout_profile` lives, alias/ignored legacy fields for one release
  (prompts, detection_model, confidence_threshold, detection_grid), reference list hydration.
- Sequence: ALTER script (unchanged) → export originals privately → `convert` (six types, exit codes 0/2/1,
  `--out` never overwrites input, layout_profile in report) → human review (unresolved quantities,
  descriptors, selectors, expected-empty, weights) → human-applied SQL → `preflight` until all rows ready
  → deploy. Migration BEFORE deployment.
- Rollback: redeploy previous runtime; original row content retained; nothing deleted in the same release.
- Production migration owner/date: explicit open placeholder (spec §8, AC19).
- Process-pool sizing: keep, note OCR now auto-enables when the extra is installed.
- Live verification: link `examples/planogram/e2e/README.md`; opt-in, not CI; three reports for signoff.
- Troubleshooting table: refresh messages (layout field-path errors, missing zone_present binding,
  empty definition, unmigrated row in handler job).
```
**Why**: AC19 enumerates exactly these topics; the verified stale 0.5 statement must not survive.

### `packages/ai-parrot-pipelines/README.md` (MODIFY) — edit sections, outline
```text
# occurrences: 1 each (verified: grep -Fxc on '## Features', '## Available Pipelines', '## Quick Start', '## Dependencies')
- Intro line (README.md:3): drop "retail product detection" wording tied to RetailDetector.
- ## Features (:11-16): remove "Abstract Detector" and "Retail Detection" bullets; add three-stage cycle,
  layout profiles, optional local OCR, six-type migration utility.
- ## Available Pipelines (:18-25): PlanogramCompliance + the six registered types; remove RetailDetector.
- ## Quick Start (:27-40): replace with a working example —
  PlanogramConfig(config_name=..., planogram_type="product_on_shelves", planogram_config={...},
  slots_definition={...}); pipeline = PlanogramCompliance(planogram_config=config, llm="provider:model");
  result = await pipeline.run("shelf_photo.jpg") — verify every argument against models.py/plan.py.
- ## Dependencies (:42-49): remove pytesseract lines 47 and 49; add `pip install "ai-parrot-pipelines[planogram]"`
  for local OCR; keep versions consistent with pyproject.toml after TASK-3881.
- Add links to both docs and a short "1.1.0 breaking changes" pointer to the runbook.
```
**Why**: the current Quick Start passes non-existent `image_path`/`reference_path` fields and
`config=` (the constructor takes `planogram_config=`), and the README advertises removed classes.

### FILL IN checklist
- [ ] Removed-name list — confirm on the feature branch with `grep -rn "PlanogramCompliancePipeline\|RetailDetector\|AbstractDetector\|legacy_adapter\|GridDetector\|HorizontalBands\|AbstractGridStrategy\|CellResultMerger\|LegacyPayload\|compute_roi\|check_planogram_compliance" packages/*/src` returns nothing (or only historical enum text)
- [ ] Layout field table — copy names/defaults from the final `layout.py`, not from memory; bounded by spec §2 table
- [ ] Credit table — copy from final `CreditPolicy.default()`; bounded by spec §2 Stage 3
- [ ] Converter/preflight usage — run `python -m parrot_pipelines.planogram.migration --help` and `convert --help`
- [ ] README Quick Start — every keyword verified against `PlanogramConfig` and `PlanogramCompliance.__init__`
- [ ] Owner/date placeholder present; no invented name/date

---

## Acceptance Criteria

- [ ] AC19: runbook covers changed scores, removed imports, layout/reference policy, migration-before-deployment,
      rollback, and carries an explicit production-migration owner/date line (open until assigned).
- [ ] The stale "0.5 for variant_unresolved/inferred_present" text is gone; docs state 1.0 lenient for those and
      0.5 for misplaced, matching `CreditPolicy.default()`.
- [ ] Cycle doc describes all six types on the three-hook contract, layout profile, OCR auto-enable, references,
      fallback ownership, expected-empty and zone-only scoring, and the final result keys; no legacy-adapter text remains.
- [ ] README lists no removed class, no pytesseract requirement, and a Quick Start whose arguments exist.
- [ ] No retailer names, store identifiers, SKUs or accuracy claims in any of the three files.
- [ ] Smoke test passes (docs-only change must not break the converter tests it documents).

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q`

(Doc review: `grep -n "0\.5" docs/pipelines/planogram-cycle-migration.md` must show only the misplaced credit;
`grep -n "RetailDetector\|AbstractDetector\|pytesseract\|legacy adapter" docs/pipelines/*.md packages/ai-parrot-pipelines/README.md`
must show only the "Removed imports" release-note list.)

---

## Test Specification

```text
# Documentation task — no new test module. Verification is the smoke pytest above plus these
# manual checks, recorded in the Completion Note:
# 1. Every fenced python snippet in the three files imports only names that exist:
#      python - <<'PY'  (paste each snippet's import lines; they must import without error)
# 2. `python -m parrot_pipelines.planogram.migration convert --help` matches the documented flags.
# 3. The missing-definition ValueError points readers at this runbook. On dev today it says
#      "planogram cycle migration runbook under docs/pipelines" (types/abstract.py:489, :494);
#      TASK-3870/3871 may name the file path (spec §2). Either way the runbook file name must not change:
#      grep -rn "migration runbook\|planogram-cycle-migration" packages/ai-parrot-pipelines/src
# 4. Links resolve: docs/pipelines/*.md and examples/planogram/e2e/README.md exist on the branch.
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3880 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
