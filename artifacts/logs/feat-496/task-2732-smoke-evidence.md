# TASK-2732 — dev.html smoke verification (2026-09-02)

No live server run was performed (no interactive browser available in this
session). Verification performed instead:

1. **Syntax check**: extracted the `<script type="module">` block (92161
   chars) from `examples/dev_loop/static/dev.html` and ran `node --check` —
   passes with no syntax errors.

2. **Runtime smoke test**: extracted the pure functions `briefOf`,
   `foldSeat`, `node`, `ownEvents`, `nodeSeatsHtml`, `shortSeat`, `esc` via
   a brace-matching extractor and ran them under plain Node (no DOM):

   - `briefOf("dispatch.message", {summary: "x"}) === "x"` — PASS
   - `briefOf("flow.foo", {bar: "baz"}) === "bar=baz"` (legacy fallback
     still works for `flow.*` events with no `summary`) — PASS
   - `foldSeat` creates a seat entry, records `task_id`/`agent`, bumps
     `tool_use_count`, records `last_tool` — PASS
   - `foldSeat` is a no-op when the action carries no `seat` — PASS
   - `ownEvents("development")` merges `development`, `development.w1`,
     `development.w2` events (not `qa`) and sorts them by `ts` ascending —
     PASS
   - `nodeSeatsHtml({dispatch: null}) === ""` (no seats -> no table, no
     regression for single-agent runs) — PASS
   - `nodeSeatsHtml(n)` with one seat renders a `<table>` containing the
     seat's `task_id` — PASS

All 8 assertions passed (`ALL SMOKE TESTS PASSED`).

**Not verified**: actual browser rendering (CSS layout, click-to-expand
interaction, live WebSocket stream). This requires the manual procedure
described in the task file, which needs a running dev-loop server and a
live/replayed run — deferred to whoever next drives an actual run against
this build. The `index.html` two-console visual comparison in TASK-2733's
own manual procedure will additionally exercise this rendering.
