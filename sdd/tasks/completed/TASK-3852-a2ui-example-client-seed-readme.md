# TASK-3852: Example client, by-course slug seed and README

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3849
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (FEAT-610). The course pie reads a seeded slug `polestar_graduates_by_course` (interim; QS-2
follow-up). The seed writes to PRODUCTION `public.queries` — the only write in the feature, behind `--yes`.

---

## Scope

- `examples/a2ui/client.py`: `--open` (webbrowser), `--check --user U` (password from `A2UI_DEMO_PASSWORD`): login,
  fetch the surface, re-fetch every source with the same route rule as linked.js (v3 / v1 tenant), print a value table,
  exit non-zero on any failure. aiohttp only.
- `examples/a2ui/seed_by_course.py`: refuses without `--yes`; copies the base slug row's columns and upserts the new slug
  with spec §3 M9's SQL. Check for a unique key on `query_slug` first (`pg_indexes`); use `ON CONFLICT` only if present,
  else UPDATE-then-INSERT in one transaction. Idempotent. Uses asyncdb / querysource connection config — FILL IN the
  verified DB access pattern (see `examples/seed_finance_projection.py` if present).
- `examples/a2ui/README.md`: `ENV=prod`, `QS_PBAC_ENABLED=false`, querysource ≥5.1.2, run order (seed → server → open/check).
- `tests/examples/test_a2ui_client_seed.py`: seed refuses without `--yes` (no DB touched), SQL template contains the
  LATERAL expansion, client arg parsing, check-mode value-table formatting with a fake server.

**NOT in scope**: running the seed against prod (manual, by the operator).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/a2ui/client.py` | CREATE | --open / --check CLI |
| `examples/a2ui/seed_by_course.py` | CREATE | idempotent seed |
| `examples/a2ui/README.md` | CREATE | run guide |
| `tests/examples/test_a2ui_client_seed.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### References
```text
spec §3 M9 SQL (copy verbatim into seed_by_course.py):
  SELECT {fields} FROM (SELECT d.student_uid, e->>'course' AS course, e->>'category' AS category
    FROM polestar.vw_graduates_directory d
    CROSS JOIN LATERAL jsonb_array_elements(d.graduation_details) e
    WHERE e->>'course' IS NOT NULL) t {where_cond}
Base slug SQL: SELECT {fields} FROM polestar.vw_graduates_directory {where_cond}   (QS appends GROUP BY)
Login: POST /api/v1/login, header X-Auth-Method: BasicAuth (admin.py:394 pattern)
Memory: data scripts run with ENV=prod (dev DB times out).
```
### Does NOT Exist
- ~~File-based slug loading~~ — slugs are rows in `public.queries`. ~~The QS management API for seeding~~ (resolved §8: SQL upsert).
- ~~`requests` / `httpx`~~ — aiohttp only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/a2ui/client.py",
      "action": "CREATE"
    },
    {
      "path": "examples/a2ui/seed_by_course.py",
      "action": "CREATE"
    },
    {
      "path": "examples/a2ui/README.md",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/test_a2ui_client_seed.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3849: client.py --check drives server.py's /api/v1/login and /api/a2ui/dashboard; README documents server.py's CLI.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. `seed_by_course.py` — argparse `--yes`; without it print the plan and exit 2 BEFORE opening any connection (AC11).
2. `client.py` — `--check` uses the same `queryUrl` rule as linked.js; print `key | value` rows (a CLI may print).
3. README; tests (no network, no DB).

```python
# examples/a2ui/seed_by_course.py — CREATE
"""FEAT-610 — upsert the interim `polestar_graduates_by_course` slug into PRODUCTION public.queries.

Run: ENV=prod python examples/a2ui/seed_by_course.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import sys

BASE_SLUG = "polestar_graduates_directory"
NEW_SLUG = "polestar_graduates_by_course"
QUERY_RAW = (
    "SELECT {fields} FROM (SELECT d.student_uid, e->>'course' AS course, e->>'category' AS category "
    "FROM polestar.vw_graduates_directory d "
    "CROSS JOIN LATERAL jsonb_array_elements(d.graduation_details) e "
    "WHERE e->>'course' IS NOT NULL) t {where_cond}"
)


async def seed() -> str:
    """Copy BASE_SLUG's row, swap slug + query_raw, upsert idempotently; return 'inserted' | 'updated'."""
    # FILL IN: connection from the querysource/asyncdb config; detect unique index on public.queries(query_slug);
    #   ON CONFLICT when present, else UPDATE then INSERT-if-0-rows, one transaction.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirm the write to production public.queries")
    args = parser.parse_args(argv)
    if not args.yes:
        print(f"Refusing to write {NEW_SLUG} to production public.queries without --yes.")
        return 2
    print(asyncio.run(seed()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
```python
# examples/a2ui/client.py — CREATE (skeleton)
"""FEAT-610 — open the dashboard or run a headless smoke check against a running example server."""
# FILL IN: argparse --base-url (http://localhost:5000) --open --check --user; password from env A2UI_DEMO_PASSWORD;
#   async check(): aiohttp login → GET /api/a2ui/dashboard → for each parrot_data_sources entry POST its route with the
#   descriptor conditions → print value table (KPI values, group counts, pie slices); return non-zero on any failure.
```
**FILL IN checklist**
- [ ] DB access + index detection + upsert; client check flow; README; tests.

---

## Acceptance Criteria

- [ ] `client.py --check` exits 0 against a running server and prints the AC7 values (manual, prod) (AC10).
- [ ] `seed_by_course.py` refuses without `--yes` and is idempotent (AC11).
- [ ] README covers ENV=prod, QS_PBAC_ENABLED=false, querysource ≥5.1.2 and run order; no secrets committed (AC13).

---

## Validation Commands

- `pytest tests/examples/test_a2ui_client_seed.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_seed_refuses_without_yes` | AC11 |
| `test_client_check_prints_values` (fake server) | AC10 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3852 — Example client, by-course slug seed and README`.
5. Close with `scripts/sdd/close_task.sh TASK-3852 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 232.1s · Tokens: 792679 in / 11379 out

client.py (--open/--check), seed_by_course.py (idempotent upsert, requires --yes + ENV=prod), README.md, tests; tests/examples: 15 passed, 1 skipped. seed_by_course.py was NOT executed — it writes to PRODUCTION public.queries and needs explicit operator approval. Merge-tier sweep skipped (env-red, see TASK-3842).
