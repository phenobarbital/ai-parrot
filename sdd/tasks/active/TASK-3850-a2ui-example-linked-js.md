# TASK-3850: Vanilla-JS linked lane (static/linked.js)

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3848
**Assigned-to**: unassigned

---

## Context

Spec §2 "Example client" step 4-5 + §3 Module 8 (FEAT-610), design research S2/S4. A vanilla port of the
FEAT-598 TS lane (`ui/.../a2ui/linked/{fetch,index}.ts`, `api/querysource.ts`) — port the contract, do not invent one.

---

## Scope

- `examples/a2ui/static/linked.js` (ES module): `DEFAULT_MAX_FETCH_ROWS = 5000`, `queryUrl(baseUrl, slug, tenant)`
  (v3 `/api/v3/queries/{slug}` without tenant; `/api/v1/queries/{tenant}/{slug}` with), `SourceUnavailable`,
  `fetchSource(src, conditions, {baseUrl, token, maxFetchRows})` (POST JSON + Bearer; 404 → `SourceUnavailable`;
  `querylimit` capped at 5000; `refresh` sent only when true), `createLane(sources, {baseUrl, token, onUpdate})` →
  `{start, refreshSource(key), refreshAll(), fetchPage(key, {offset, limit, filter, ordering})}`.
- `fetchPage` is example-only (S2): reuse the grid source's slug/tenant/locked conditions, override only
  `querylimit`/`_offset`/`ordering`/column `filter`; also returns `total` via a parallel `count(*)` request with the same
  filter.
- Conditions derivation: port `conditions.ts` `deriveConditions` (read it) — FILL IN in the port.
- `tests/examples/test_a2ui_linked_js.py`: runs `node --test` on an inline ESM harness (skip when `node` missing).

**NOT in scope**: DOM rendering (TASK-3851).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/a2ui/static/linked.js` | CREATE | lane port |
| `tests/examples/test_a2ui_linked_js.py` | CREATE | node-driven tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Existing Signatures to Port (read these files first)
```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts — DEFAULT_MAX_FETCH_ROWS = 5000 (line 13), fetchSource(src, conditions, {baseUrl, headers}), SourceUnavailable
// packages/ai-parrot-server/ui/src/lib/api/querysource.ts — queryUrl (lines 21-24)
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts — deriveConditions(request, lockedValues)
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts — createLinkedLane: lockedValues(src), runSource (line 161), refreshAll (line 225)
```
### Does NOT Exist
- ~~`paged` / `page` keys~~ — ignored by QS; use `querylimit` / `_offset`.
- ~~A per-widget refresh endpoint~~ — client-side only. ~~A slug/conditions sent by the UI outside the descriptor~~ (S4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/a2ui/static/linked.js",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/test_a2ui_linked_js.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3848: first file under examples/a2ui/static/ relies on the .gitignore whitelist TASK-3848 adds (JS itself is not ignored, but its node test harness lives in tests/examples/ created there).
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Read fetch.ts, conditions.ts, querysource.ts, index.ts; port line-for-line into plain JS (no build step, no deps).
2. `refreshSource` semantics = TASK-3844 (unknown → no-op; one request; dedup).
3. `fetchPage` + total count; always send `ordering` (default `["student_uid"]` from the descriptor request) — because
   un-ordered QS pages are nondeterministic (spec §7).
4. Node test harness.

```js
// examples/a2ui/static/linked.js — CREATE
// FEAT-610 — vanilla port of the FEAT-598 linked lane (ui/.../a2ui/linked/{fetch,conditions,index}.ts).
export const DEFAULT_MAX_FETCH_ROWS = 5000;

export class SourceUnavailable extends Error {}

export function queryUrl(baseUrl, slug, tenant) {
  const base = baseUrl.replace(/\/$/, '');
  return tenant
    ? `${base}/api/v1/queries/${encodeURIComponent(tenant)}/${encodeURIComponent(slug)}`
    : `${base}/api/v3/queries/${encodeURIComponent(slug)}`;
}

export async function fetchSource(src, conditions, { baseUrl, token, maxFetchRows = DEFAULT_MAX_FETCH_ROWS }) {
  // FILL IN: port fetch.ts — cap querylimit at maxFetchRows, drop refresh unless true, POST JSON with
  //   Authorization: Bearer token; 404 → throw new SourceUnavailable(); non-2xx → Error; return rows array
  //   (same response unwrapping as fetch.ts).
}

export function deriveConditions(request, locked) {
  // FILL IN: port conditions.ts exactly.
}

export function createLane(sources, { baseUrl, token, onUpdate }) {
  // FILL IN: start() fetches each source (snapshot already painted by the renderer); refreshSource(key);
  //   refreshAll() sequential; fetchPage(key, {offset, limit, filter, ordering}) → {rows, total} — bounded by S2/S4.
}
```
```python
# tests/examples/test_a2ui_linked_js.py — CREATE
"""FEAT-610 TASK-3850 — static/linked.js contract, exercised with node's test runner."""
# FILL IN: skip if shutil.which("node") is None; write a .mjs harness into tmp_path that imports linked.js by file URL,
#   stubs globalThis.fetch, and asserts: queryUrl routes (v3 / v1 tenant), querylimit cap 5000, refresh only when true,
#   404 → SourceUnavailable, refreshSource issues exactly one fetch, fetchPage sends querylimit/_offset/ordering/filter
#   and a count(*) request; subprocess.run(["node", "--test", harness]) returncode == 0.
```
**FILL IN checklist**
- [ ] fetch/conditions ports; lane; fetchPage + total; node harness.

---

## Acceptance Criteria

- [ ] `queryUrl`, the 5000 cap, `refresh` semantics and 404 handling match the TS lane (AC8, AC12 parity).
- [ ] `refreshSource(key)` issues exactly one request; `refreshAll` re-fetches all (AC8).
- [ ] `fetchPage` sends `querylimit`/`_offset`/`ordering`/column `filter` and fetches a total (AC9).

---

## Validation Commands

- `pytest tests/examples/test_a2ui_linked_js.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_linked_js_contract` (node) | AC8, AC9 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3850 — Vanilla-JS linked lane (static/linked.js)`.
5. Close with `scripts/sdd/close_task.sh TASK-3850 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
