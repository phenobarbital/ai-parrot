---
id: F020
query_id: live-run
type: read
intent: live verification of slugs, seeding and the E2E tiers (run on the DEV env — staging Postgres unreachable)
executed_at: 2026-09-29T13:55:00Z
parent_id: null
depth: 0
---
# F020 — Live run on dev (ENV=dev, querysource 5.1.2): slug reality, seeding, 32/32 runner + 4/4 pytest

## Summary
The live tier ran against the **dev** env (`env/dev/.env`). Staging (`env/staging`) Postgres times out on :5432 from the
workstation, and `env/.env` targets production, so neither was used. Results:
- `run_e2e.py`: **32/32 PASS**, exit code 0. It used 3 servers: policy on :5000, deny on :5001 and none on :5002.
- `pytest -m staging tests/integration/test_linked_e2e_staging.py`: **4/4 PASS** (s1, s2, s3, s5).
- `prove-policy`: allow with the policy, deny without it.
- `seed` inserted all three slugs on the first run and returned `updated` on the second (idempotent).
- `preview`: the MQ frames are `{result: 112 rows, targets: 7 rows}` for 2025-03-01..07.

## Slug reality (read-only checks before seeding)
- `epson_field_activity` EXISTS, but returns ONE aggregated KPI row (dsm_visits, ww_visits, training_visits,
  selling_events, total_trained, sales_from_events, ...). It does NOT have the fixture shape (`day, visits, program`).
  Several numeric columns come back as **object dtype** (Postgres numeric → Decimal). The builder's numeric axis check
  would reject KPICard/Chart bindings on those columns.
- `epson_program_targets` and `epson_multiquery` DO NOT EXIST. They were fictional names in the FEAT-598 fixtures.
- Dev data covers only 2024-12-31..2025-03-23. The E2E ranges used are A = 2025-03-01..07 (112 rows, 8 programs) and
  B = 2025-03-11..15 (71 rows).

## Seeded into dev public.queries (user-approved)
- `epson_e2e_activity`: `SELECT {fields} FROM (visit_date AS day, account_name AS program, store_id, count(*) visits
  FROM epson.vw_form_information WHERE visit_date BETWEEN {firstdate} AND {lastdate} ... GROUP BY 1,2,3) t {where_cond}`.
- `epson_e2e_targets`: a static `VALUES` table of 7 programs, with **no-op `{firstdate}`/`{lastdate}` placeholders**.
- `epson_e2e_activity_vs_targets_mq`: queries `result` and `targets`, with the child dates pinned (MQ_RANGE).

## Defects / gotchas found live (not visible to the offline fakes)
1. **querysource 5.1.2 schema migration.** `QueryModel` gained `columns_definition` (`querysource/models.py:68`) and
   ships no migration. On an unmigrated DB every model read fails, e.g. `QueryModel.get` → `column
   "columns_definition" does not exist`; that includes the toolkit `describe_slug` / `build_linked_surface` and
   `SlugCatalog`. Direct `QS(slug=…)` execution still works. The user applied this on dev:
   `ALTER TABLE public.queries ADD COLUMN IF NOT EXISTS columns_definition varchar[] DEFAULT '{}'`.
   → Every env that moves to QS 5.1.2 needs this.
2. **MultiQS drops flat conditions.** It applies conditions only when they are keyed by child query name
   (`self._conditions.pop(name, {})`, `querysource/queries/multi/__init__.py:451`). A linked `is_multiquery` source
   sends flat conditions, so its params never reach the children, and refresh params on a multiquery source are
   ineffective. The E2E works around this by pinning the child conditions in the stored pipeline.
3. **Undeclared placeholders become WHERE filters.** A slug without `{firstdate}`/`{lastdate}` gets them appended as
   filters (`column "firstdate" does not exist`). Because `/refresh` broadcasts params to every source, any sibling
   slug must declare them.
4. **Tenant routes need PBAC grants.** QS 5.1.2 tenant routes (`/api/v1/{tenant}/queries/{slug}` and
   `/api/v1/queries/{tenant}/{slug}`) run an owner-aware PBAC pre-flight on the SAME app evaluator that parrot's
   `setup_pbac` installs: `slug:execute`, then `datasource:use`. With parrot's policies loaded but no slug or
   datasource grants, the answer is a **bare 404**. v3 skips the check. The example policy dir now grants
   `slug:epson_e2e_*` and `datasource:db` / `driver:*`. This confirms FEAT-610's "QS guardian vs parrot PBAC
   coexistence" risk.
5. **Env drift in dev.** `navigator.ai_bots.toolkit_config` column is missing; this is non-fatal because DB bots are
   disabled. The LLM client registry resolves `google` only via an installed distribution's entry points; putting
   `ai-parrot-client-google/src` on PYTHONPATH is not enough, so `--via-agent` / S4 stays blocked in this venv.

## Citations
- path: `examples/agents/a2ui/linked_e2e/seed_staging.py`
  symbol: `SQL_SLUGS`, `MQ_PIPELINE`, `MQ_RANGE`, `seed_sql_slugs`, `assert_live_target`
- path: `examples/agents/a2ui/linked_e2e/policies/source-epson.yaml`
- path: `venv:querysource/models.py`
  lines: 68
  symbol: `QueryModel.columns_definition`
- path: `venv:querysource/queries/multi/__init__.py`
  lines: 451
- path: `venv:querysource/handlers/service.py`
  lines: 185-215
  symbol: owner-aware PBAC pre-flight
- path: `venv:querysource/handlers/abstract.py`
  lines: 455-530
  symbol: `_enforce_owned_slug`
