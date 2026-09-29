# TASK-3853: Wire doc and toolkit doc updates

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3841, TASK-3847, TASK-3844
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (FEAT-610). The linked-surfaces wire doc §3 disagrees with the code (routes, the 500 cap,
`refresh` semantics).

---

## Scope

- `docs/outputs/a2ui-linked-surfaces.md` §3: list the four routes (`/api/v3/queries/{slug}`;
  `/api/v1/{tenant}/queries/{slug}`; `/api/v1/queries/{schema}/{slug}` alias, querysource ≥5.1.2;
  `/api/v2/services/queries/{slug}`), `querylimit` cap 5000, `refresh` sent only when true; add a per-source refresh
  subsection (`LinkedLane.refreshSource(key)`, `refreshAll` order).
- `docs/tools/querysource-toolkit.md`: a `qs_build_linked_dashboard` bullet after `qs_build_linked_surface` (:64) and
  the JSONB operators; add the tool to the tenant sentence (:80).
- `packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py`: asserts the doc strings exist (AC12).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | §3 routes, cap, refresh |
| `docs/tools/querysource-toolkit.md` | MODIFY | new tool + JSONB |
| `packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py` | CREATE | doc presence test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified anchors
```text
docs/outputs/a2ui-linked-surfaces.md:44   POST /api/v1/{tenant}/queries/{slug}          (occurrences: 1)
docs/outputs/a2ui-linked-surfaces.md:49   - `querylimit: 500` (capped by toolkit)       (occurrences: 1)
docs/tools/querysource-toolkit.md:64      - **`qs_build_linked_surface`** — (FEAT-598) Emits a linked A2UI surface for a query-slug: checks the slug
docs/tools/querysource-toolkit.md:80      The `qs_list_slugs`, `qs_describe_slug`, `qs_execute_slug`, and `qs_build_linked_surface` tools accept an optional `tenant` ...
```
### Does NOT Exist
- ~~A per-widget refresh HTTP endpoint~~ — say refresh is client-side.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/outputs/a2ui-linked-surfaces.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/tools/querysource-toolkit.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3841 (documents JSONB_OPERATORS), TASK-3847 (documents qs_build_linked_dashboard) and TASK-3844 (documents LinkedLane.refreshSource).
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Read both docs around the anchors; rewrite the §3 route block and the cap line.
2. Add the toolkit bullets. 3. Doc test.

```markdown
<!-- docs/outputs/a2ui-linked-surfaces.md — REPLACE the route block containing `POST /api/v1/{tenant}/queries/{slug}` (verified :44) -->
POST /api/v3/queries/{slug}                     # no tenant
POST /api/v1/{tenant}/queries/{slug}            # tenant store
POST /api/v1/queries/{schema}/{slug}            # alias, querysource >= 5.1.2
POST /api/v2/services/queries/{slug}            # service route
<!-- and line 49 -->
- `querylimit` capped at 5000 rows per fetch (`DEFAULT_MAX_FETCH_ROWS`); `refresh: true` is sent only on a manual refresh
<!-- FILL IN: a "Per-source refresh" subsection — refreshSource(key) re-fetches one source (+ transform dependents); refreshAll keeps dependency order -->
```
```markdown
<!-- docs/tools/querysource-toolkit.md — AFTER the `qs_build_linked_surface` bullet (:64) -->
- **`qs_build_linked_dashboard`** — (FEAT-610) Emits ONE linked A2UI dashboard: each widget `{key, slug, component, request?, tenant?, section?, refresh?}` gets its own source; KPIs, charts and tables are laid out in rows. KPICards name their aggregate column.
<!-- FILL IN: JSONB operators paragraph (@>, <@, @>|, ->, ->> in the {op: value} filter form, querysource >= 5.1) -->
```
```python
# packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py — CREATE
"""FEAT-610 AC12 — the wire doc and toolkit doc describe the new behaviour."""
# FILL IN: repo root = Path(__file__).resolve().parents[4]; assert the 4 routes, "5000" and "refreshSource" in the wire
#   doc; "qs_build_linked_dashboard" and "@>" in the toolkit doc.
```
**FILL IN checklist**
- [ ] per-source refresh subsection; JSONB paragraph; doc test.

---

## Acceptance Criteria

- [ ] Wire doc §3 lists the four routes, the 5000 cap and `refresh` semantics; per-source refresh documented (AC12).
- [ ] Toolkit doc documents `qs_build_linked_dashboard` and the JSONB operators (AC12).

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_docs_linked_dashboard.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_docs_linked_dashboard` | AC12 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3853 — Wire doc and toolkit doc updates`.
5. Close with `scripts/sdd/close_task.sh TASK-3853 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Tokens: n/a

Wire doc + toolkit doc updated; doc test passes. Caveat: the /api/v1/queries/{schema}/{slug} alias is documented per spec/design research S6 (querysource 5.1.2) but could not be verified — the local venv has an older querysource. /api/v2/services/queries/{slug} verified in installed querysource. Merge-tier sweep skipped (env-red, see TASK-3842).
