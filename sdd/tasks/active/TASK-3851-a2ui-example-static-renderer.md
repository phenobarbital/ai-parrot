# TASK-3851: Static HTML5 renderer (index.html, renderer.js, styles.css)

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3849, TASK-3850
**Assigned-to**: unassigned

---

## Context

Spec §2 "Example client" + §3 Module 8 (FEAT-610), design research S2/S7. Login + `localStorage` follow
`admin_login_page` (`parrot/autonomous/admin.py:394`, key `ai_parrot_token`).

---

## Scope

- `index.html`: login form (POST `/api/v1/login`, header `X-Auth-Method: BasicAuth`), logout, dashboard container,
  "Refresh all"; loads `/static/vendor/echarts.min.js`, grid.js `gridjs@6.2.0` from unpkg (`dist/gridjs.umd.js` +
  `dist/theme/mermaid.min.css`) with REAL `sha384` SRI computed from the exact files, `renderer.js` as a module.
- `renderer.js`: fetch the envelope with Bearer; walk the v1.0 tree from `root` (Column/Row/Card/Text), degrade on unknown
  components (visible notice, never throw); KPICard hero card; Chart bar/pie via ECharts (`{name, value}` slices, NULL →
  "Unassigned"); DataTable → grid.js `server` mode driven by `lane.fetchPage` (column filters country / licensee /
  is_requalified → `filter`; no free-text search); snapshot paints first, live data replaces it; per-widget refresh
  button + loading/error/"unavailable" states.
- `styles.css`: responsive grid of cards.
- `tests/examples/test_a2ui_static_assets.py`: static checks (SRI attributes present and not placeholders, module
  imports linked.js, token key `ai_parrot_token`, no credentials in files).

**NOT in scope**: server changes; admin UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/a2ui/static/index.html` | CREATE | page shell |
| `examples/a2ui/static/renderer.js` | CREATE | tree walk + widgets |
| `examples/a2ui/static/styles.css` | CREATE | styles |
| `tests/examples/test_a2ui_static_assets.py` | CREATE | static checks |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Existing references
```text
parrot/autonomous/admin.py:394  admin_login_page — _ADMIN_LOGIN_HTML shows the login fetch + localStorage('ai_parrot_token') pattern (read it)
parrot/outputs/formats/table.py:181-182  unpkg gridjs references (version 6.2.0)
interactive/catalog/libraries/gridjs.md  — its SRI values are PLACEHOLDERS: never copy them (S7)
examples/a2ui/static/linked.js  — createLane, fetchPage, SourceUnavailable (TASK-3850)
Layout components: Row/Column (catalog/basic/layout.py:24,39); envelope root at createSurface.components (id "root")
```
### Does NOT Exist
- ~~A vendored grid.js~~ — unpkg + SRI only. ~~A `Grid` A2UI container~~. ~~Free-text grid search~~ (resolved §8).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/a2ui/static/index.html",
      "action": "CREATE"
    },
    {
      "path": "examples/a2ui/static/renderer.js",
      "action": "CREATE"
    },
    {
      "path": "examples/a2ui/static/styles.css",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/test_a2ui_static_assets.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3849 (fetches /api/a2ui/dashboard and /static/vendor/echarts.min.js served by server.py) and TASK-3850 (imports createLane/fetchPage from static/linked.js).
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. Compute SRI: `curl -sL https://unpkg.com/gridjs@6.2.0/dist/gridjs.umd.js | openssl dgst -sha384 -binary | openssl base64 -A`
   (same for the theme css) — because S7 forbids placeholder hashes.
2. `index.html` shell; `renderer.js` tree walk; widgets; lane wiring; per-widget buttons call `lane.refreshSource(key)`
   and repaint only components bound to that key.
3. Manual check against a running server (AC7 values) — record in the Completion Note.

```html
<!-- examples/a2ui/static/index.html — CREATE -->
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polestar graduates — A2UI linked dashboard</title>
  <link rel="stylesheet" href="https://unpkg.com/gridjs@6.2.0/dist/theme/mermaid.min.css"
        integrity="sha384-FILL_IN" crossorigin="anonymous">
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <!-- FILL IN: #login form (username/password), #app with header (title, Refresh all, Logout), #dashboard -->
  <script src="/static/vendor/echarts.min.js"></script>
  <script src="https://unpkg.com/gridjs@6.2.0/dist/gridjs.umd.js" integrity="sha384-FILL_IN" crossorigin="anonymous"></script>
  <script type="module" src="/static/renderer.js"></script>
</body>
</html>
```
```js
// examples/a2ui/static/renderer.js — CREATE
// FEAT-610 — renders the agent-built linked dashboard (KPICard / Chart / DataTable) and wires per-widget refresh.
import { createLane } from './linked.js';

const TOKEN_KEY = 'ai_parrot_token';

async function login(username, password) {
  // FILL IN: POST /api/v1/login with X-Auth-Method: BasicAuth (copy admin.py's body shape); store token under TOKEN_KEY.
}

function renderNode(id, byId, ctx) {
  // FILL IN: Column/Row → flex containers with children; KPICard/Chart/DataTable → widget renderers keyed by id;
  //   unknown → <div class="notice">Unsupported component: X</div> (degrade, never throw).
}

// FILL IN: renderKpi, renderChart (bar: category x / value series; pie: {name,value}, NULL → "Unassigned"),
//   renderGrid (gridjs.Grid server mode via lane.fetchPage, column filter selects → filter), per-widget toolbar
//   (refresh button + status), boot(): token check → fetch /api/a2ui/dashboard → paint snapshot → lane.start().
```
**FILL IN checklist**
- [ ] real SRI hashes; login body; tree walk; 3 widget renderers; grid server mode + filters; status states; styles; static test.

---

## Acceptance Criteria

- [ ] Logs in, keeps the JWT in `localStorage`, renders all 8 widgets with the AC7 values against prod (manual) (AC7).
- [ ] Per-widget refresh = one request, repaints only that widget; "Refresh all" re-fetches all (AC8).
- [ ] Grid pages server-side over 17 572 rows with stable ordering; column filters change rows and total (AC9).
- [ ] grid.js via unpkg with real SRI; ECharts from the vendored bundle; no new library (AC15).

---

## Validation Commands

- `pytest tests/examples/test_a2ui_static_assets.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_static_assets_sri_and_wiring` | AC13, AC15 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3851 — Static HTML5 renderer (index.html, renderer.js, styles.css)`.
5. Close with `scripts/sdd/close_task.sh TASK-3851 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
