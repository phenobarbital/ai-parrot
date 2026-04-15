# PR Review: Trocdigital/navigator-dataintegrator-tasks#4028 ↔ NAV-8036

**Date**: 2026-04-14
**Reviewer**: Claude Code (automated)
**PR State**: MERGED (2026-04-13)
**Author**: William Cabrera (@willicab)
**Branch**: `NAV-8036-roadshows-workers-to-odoo` → `master`
**Human Approvers**: @vijoin, @jelitox
**Overall Verdict**: ⚠️ Needs Attention

> **Note**: This PR is already merged. Findings below are post-merge advisories
> that may require follow-up fixes.

---

## Acceptance Criteria Compliance

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Queries workers from Navigator using provided SQL | ✅ Met | `workers_to_odoo.sql` matches the ticket's SQL query exactly |
| 2 | Sends data to Odoo using `OdooInjector` component | ✅ Met | `workers_to_odoo.yaml` uses `OdooInjector` step |
| 3 | Use `QueryToPandas` to retrieve workers dataset | ✅ Met | First step in YAML is `QueryToPandas` with `file_sql: "workers_to_odoo.sql"` |
| 4 | Remove fields `start_date`, `inserted_at`, `updated_at` using tPluck | ⚠️ Partially Met | PR uses `FilterRows` with `drop_columns` instead of `tPluck` as specified. Achieves the same result but uses a different component. |
| 5 | Target Odoo model: `res.partner` | ✅ Met | `model: "res.partner"` in YAML |
| 6 | Use ROADSHOWS credentials (not TROC) | ✅ Met | Uses `ODOO_ROADSHOWS_APIKEY`, `ODOO_ROADSHOWS_HOST`, `ODOO_ROADSHOWS_PORT`, `ODOO_ROADSHOWS_INJECTOR_URL` |
| 7 | Follow `apple/workers_to_odoo` structure as reference | ✅ Met | Structure matches: QueryToPandas → (filter) → OdooInjector with `chunk_size: 10` |

**Score**: 6/7 criteria fully met (86%)

---

## Description Alignment

### ✅ Addressed
- New SQL file queries `troc.troc_employees` with correct job codes and department filter
- YAML task pipeline: QueryToPandas → FilterRows → OdooInjector
- ROADSHOWS-specific credential environment variables used
- Target model is `res.partner`
- Chunk size matches reference (10)

### ⚠️ Deviations
- **`tPluck` vs `FilterRows`**: Ticket explicitly says "use the tPluck component to remove the fields". PR uses `FilterRows` with `drop_columns` instead. Functionally equivalent but deviates from the specification.
- **Credential key naming**: Reference (Apple) uses `APIKEY`, but PR uses `BEARER_TOKEN`. This may be intentional if the Roadshows Odoo instance uses a different auth mechanism, but it's worth confirming.

### ❌ Gaps
- None — all core requirements are addressed.

### ⚠️ Out of Scope
- None — changes are tightly scoped to the two new files.

---

## Code Observations

1. **Missing newline at end of SQL file** — `workers_to_odoo.sql` lacks a trailing newline (`\ No newline at end of file` in diff). Minor but can cause issues with some tools.

2. **Credential key `BEARER_TOKEN` vs `APIKEY`** — The reference Apple task uses `APIKEY` as the credential key, but this PR uses `BEARER_TOKEN`. If the `OdooInjector` component expects a specific key name for the authentication token, using `BEARER_TOKEN` instead of `APIKEY` could cause a runtime failure. This should be verified against the `OdooInjector` implementation.

3. **SQL is clean and correct** — Exact match to the ticket's provided query, with proper JOINs and WHERE clause filtering.

---

## AI Bot Review Findings

### Gemini Code Assist (6 inline comments, all high priority)

| # | File | Line | Finding | Our Assessment |
|---|------|------|---------|----------------|
| 1 | `workers_to_odoo.sql` | 1 | **Duplicate records**: Query may return duplicate `associate_id` records if source has historical data. Suggests adding `DISTINCT ON (e.associate_id)`. | ⚠️ **Conditionally Agree** — If `troc_employees` can have multiple rows per `associate_id` (e.g., historical records), this is a valid concern and would cause duplicate partner records in Odoo. However, the Jira ticket provided this exact query without `DISTINCT ON`, so the ticket author may know the source table is already deduplicated. **Needs verification** against the actual `troc_employees` table structure. |
| 2 | `workers_to_odoo.sql` | 13 | **`state_id` type mismatch**: `cs.state` may return a string, but Odoo `many2one` fields require integer IDs. | ❌ **Disagree** — The `OdooInjector` component handles field mapping between Navigator data and Odoo. The injector resolves string names to Odoo IDs internally. This pattern is consistent with other tasks in the repository (e.g., Apple workers). The query correctly provides the state name for the injector to resolve. |
| 3 | `workers_to_odoo.sql` | 14 | **`country_id` type mismatch**: Same as above — `c.country` may return a string instead of Odoo integer ID. Also flags SA/ZA country code mapping issue. | ❌ **Disagree on type mismatch** (same reasoning as #2). ⚠️ **Partially Agree on SA/ZA mapping** — If the source data has inconsistent country codes for South Africa, this could cause lookup failures in Odoo. Worth verifying but this is a data quality issue, not a code bug. |
| 4 | `workers_to_odoo.sql` | 18 | **Boolean type**: `'True'` (string) instead of `TRUE` (boolean) for `is_roadshow_worker`. Claims Odoo boolean fields reject strings. | ❌ **Disagree** — The data passes through Pandas (via `QueryToPandas`) before reaching Odoo. Pandas will receive the string `'True'` from PostgreSQL. The `OdooInjector` handles type coercion. Moreover, the Jira ticket explicitly provides this exact SQL with `'True'` as a string. This is the intended pattern. |
| 5 | `workers_to_odoo.sql` | 20 | **Boolean type for `active`**: Same issue — `CASE WHEN ... THEN 'True' ELSE 'False'` returns strings instead of booleans. | ❌ **Disagree** — Same reasoning as #4. The Jira ticket provides this exact SQL. The `OdooInjector` handles the coercion. |
| 6 | `workers_to_odoo.sql` | 34 | **ORDER BY clause**: Suggests changing to `ORDER BY e.associate_id, e.start_date DESC` to support `DISTINCT ON`. | ❌ **Disagree** — This suggestion is contingent on adding `DISTINCT ON` from finding #1, which the current query doesn't use. The existing `ORDER BY e.start_date DESC` is correct for the query as written and matches the Jira ticket's specification. |

**Summary**: Gemini flagged 6 issues, all marked as high priority. After analysis:
- **0 fully valid**: None of the findings represent confirmed bugs in the current implementation.
- **1 conditionally valid** (#1): Duplicate records concern depends on whether `troc_employees` has historical data — worth verifying.
- **1 partially valid** (#3): SA/ZA country code mapping is a legitimate data quality concern.
- **4 false positives** (#2, #4, #5, #6): These misunderstand how the `OdooInjector` pipeline works — data flows through Pandas and the injector handles type mapping. The SQL was also provided verbatim in the Jira ticket.

### Human Reviews

| Reviewer | Action | Notes |
|----------|--------|-------|
| @vijoin | APPROVED | No comments |
| @jelitox | APPROVED | No comments |

Both human reviewers approved without addressing any of Gemini's findings. The Gemini comments were not resolved or responded to before merge.

---

## Verdict & Recommendation

The PR correctly implements the core ETL task as specified in NAV-8036. The SQL query matches the Jira ticket exactly, the YAML pipeline follows the reference pattern, and ROADSHOWS-specific credentials are used.

**Gemini Code Assist** raised 6 high-priority findings, but most are false positives that misunderstand the `OdooInjector` pipeline's type coercion behavior. The one finding worth investigating post-merge is the potential for duplicate `associate_id` records (#1) — if `troc_employees` contains historical rows per worker, the query could push duplicates to Odoo.

**Two spec deviations** remain minor:
1. `FilterRows` used instead of `tPluck` (functionally equivalent)
2. `BEARER_TOKEN` credential key vs `APIKEY` in reference (may be intentional)

**Action**: POST-MERGE ADVISORY

**Recommended follow-ups** (in priority order):
1. **Verify `troc_employees` uniqueness** — Confirm that `associate_id` + `department_code = '008300'` returns at most one row per worker. If not, add `DISTINCT ON`.
2. **Verify `BEARER_TOKEN` key** — Confirm `OdooInjector` accepts `BEARER_TOKEN` as a valid credential key for the Roadshows instance.
3. **Add trailing newline** to `workers_to_odoo.sql` (minor).
