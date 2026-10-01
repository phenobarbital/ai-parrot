# Planogram compliance — migrating configurations to the new cycle (FEAT-574, FEAT-612)

## Who needs this

Every active row using one of the six registered types must migrate before the new runtime is
deployed. A missing `slots_definition` fails construction with a `ValueError` that names this
runbook.

## What changes in scores

Old and new values are not comparable for the four types that previously used a different path.
Label new expectations before comparing outcomes.

- Every expected facing stays in the denominator.
- `match` and `expected_empty` earn `1.0` in strict and lenient scoring.
- `inferred_present` and `variant_unresolved` earn `1.0` lenient credit and `0.0` strict credit;
  `misplaced` earns `0.5` lenient credit and `0.0` strict credit.
- Zone-only units measure coverage from assessed mandatory rules, and their threshold is enforced
  even with zero facings.
- Inconclusive and all-photo-failure results are never compliant.

## Removed imports and contracts

Release 1.1.0 removes `PlanogramCompliancePipeline`, `RetailDetector`, `AbstractDetector`,
`legacy_adapter`, `GridDetector`, `HorizontalBands`, `AbstractGridStrategy`, `CellResultMerger`,
`LegacyPayload`, `compute_roi`, and `check_planogram_compliance`. There is no compatibility
replacement; use `PlanogramCompliance` and the cycle contract instead.

## Layout and reference policy

Store `layout_profile` inside `planogram_config`. Its validated overrides merge with the type
default; lists replace rather than append, and unknown fields are rejected with a layout field
path. Top-level `perception_mode` is an accepted alias only when it agrees with the nested value.

For one release, `roi_detection_prompt`, `object_identification_prompt`, `detection_model`,
`confidence_threshold`, and `detection_grid` are accepted but ignored. `reference_images` supports
paths, stable path lists, and PIL images; valid entries are hydrated once per run into opaque
reference labels.

Legacy `fact_tag` and `price_tag` elements become informative `fact_tag_present` bindings on the
first facing of the product they name (`"ES-60W Fact Tag"` → product `ES-60W`, same shelf),
carrying `price_required`. A tag that names no product of its shelf is reported as unresolved.

## Deployment sequence

Migration happens before deployment.

1. Apply the existing `alter_planograms_configurations_feat574.sql` ALTER script.
2. Export original active rows privately.
3. Run `python -m parrot_pipelines.planogram.migration convert exported.json --out candidate.json`.
   It supports all six types, never overwrites its input, and reports a `layout_profile`; exit `0`
   is ready, `2` is unresolved, and `1` is usage or I/O failure.
4. Review unresolved quantities, descriptors, selectors, expected-empty expectations, bindings,
   and weights with a human.
5. Apply the approved SQL update by hand; the converter never writes a database.
6. Run `python -m parrot_pipelines.planogram.migration preflight --dsn "$PLANOGRAM_DSN"` until every
   active row is ready, then deploy.

### Whole-table runner

`python -m parrot_pipelines.planogram.migration_runner` runs the same sequence over every active
row from one work directory; the `/planogram-migrate` command drives it with the human review in
between. The DSN comes from `--dsn` or, by default, `querysource.conf.default_dsn` of the active
`ENV`; `target` shows the resolved host and database without credentials.

| Subcommand | Writes to the database | What it does |
|---|---|---|
| `alter [--yes]` | only with `--yes` | Prints, or applies, the ALTER script. |
| `export --dir D` | no | One file per active row in `D/original/`; never overwrites an export. |
| `convert --dir D` | no | Candidates in `D/candidates/`; reviewed candidates are kept unless `--force`. |
| `render --dir D` | no | `D/apply.sql` from candidates with an empty `unresolved` list that pass the preflight checks. |
| `apply --dir D --yes` | yes | Runs `D/apply.sql`: one transaction, aborted when a row changed since the export. |
| `preflight` | no | Same report as `migration preflight`. |

Exit codes match the converter: `0` ready, `2` unresolved or not-ready rows, `1` usage, I/O or
database failure.

## Rollback

Redeploy the prior runtime and retain the exported original row content. This release deletes no
configuration data, so no same-release database restore is required.

Owner/date: to be assigned before deployment.

## Process-pool sizing under gunicorn

Each run creates its own spawn-based CPU pool. Budget for `gunicorn workers × concurrent runs ×
cpu_workers` processes. OCR auto-enables when the optional planogram extra is installed, so each
worker may load OCR models; reduce `cpu_workers` or omit the extra on constrained hosts.
`llm_concurrency` bounds vision calls per run.

## Live verification

The [live E2E harness](../../examples/planogram/e2e/README.md) is opt-in and is not a CI gate.
Accuracy signoff requires three successful local reports from the documented case types.

## Troubleshooting

| Symptom | Action |
|---|---|
| `invalid layout_profile...` | Correct the reported nested field path or remove an unknown override. |
| Missing `zone_present` binding | Add a binding for every mandatory zone rule and rerun preflight. |
| Empty or invalid definition | Review slots, expected-empty facings, descriptors, and selector ids. |
| Unmigrated row in a handler job | Export, convert, review, apply SQL, and preflight before deployment. |
| Exit code `2` | Resolve every reported candidate or readiness problem; do not deploy it. |
| `tag '…' matches no product of the shelf` | Bind the tag to the right facing by hand, or drop it. |
