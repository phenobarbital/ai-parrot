# TASK-2732: `dev.html` — read the summary, render the seats

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2723, TASK-2729, TASK-2730
**Assigned-to**: unassigned

---

## Context

Spec §1 root causes 3 and 5, §2 "Layer 4", §3 Module 8, §5 AC7.

This is the task the user actually sees. Everything before it enriches the
data; this one makes the console read it.

Two changes, both small, both load-bearing:

1. **`briefOf` never looks for a summary.** Its branch list (`dev.html:494-511`)
   checks `decision`, `command`/`cmd`, `criterion`, `tool_name`, `pr_url`,
   `issue_key`, `step`, `error`, `status`, `kind` — then falls off the end
   into `keys[0]=value` (`:509-510`). That last resort is what printed
   `message_class=SystemMessage`.

2. **Seat events are received and thrown away.** The socket handler stores
   events under their real `node_id`, seats included (`dev.html:648-651`), but
   `nodesForRender` only reads `app.events.get(n.id)` for the ten fixed
   `TOPOLOGY.dev` ids (`:995-1009`). So every `development.w1` /
   `development.w2` / `development.resolver` event is held in memory and never
   drawn, and the Development card shows *"This node has not been dispatched
   yet"* (`:1013`) for the whole run.

---

## Scope

- Add a leading `if (p.summary) return String(p.summary);` branch to `briefOf`
  (`dev.html:494`).
- Change `nodesForRender` (`dev.html:995`) so a node claims every event whose
  `node_id` is `id` **or** starts with `id + "."`.
- Render seat attribution in the event rows (`eventRowsHtml`, `dev.html:1011`):
  a seat badge and the `task_id` when the event carries them.
- Render the seat table in `nodeMetaHtml` (`dev.html:1031`) from
  `dispatch.seats` (added to session state by TASK-2729): one row per seat
  with its task, agent/model, status and counters.
- Make the empty-state message (`dev.html:1013`) accurate — it must not claim
  "not dispatched" while seats are running.

**NOT in scope**: `index.html` (TASK-2733); `afd.html` (Non-Goal); any Python;
any change to the WebSocket protocol or the multiplexer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/static/dev.html` | MODIFY | `briefOf`, `nodesForRender`, `eventRowsHtml`, `nodeMetaHtml`, `foldAction` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```javascript
// examples/dev_loop/static/dev.html
const TOPOLOGY = {                                            // line 384
  dev: [
    { id: "dev_intake",      label: "Intake",      role: "..." },   // 386
    { id: "ideation",        label: "Ideation",    role: "..." },   // 387
    { id: "planner",         label: "Planner",     role: "..." },   // 388
    { id: "development",     label: "Development", role: "..." },   // 389
    { id: "synthesis",       label: "Synthesis",   role: "..." },   // 390
    { id: "qa",              label: "QA",          role: "..." },   // 391
    { id: "feedback_router", label: "Feedback",    role: "..." },   // 392
    { id: "feature_handoff", label: "Handoff",     role: "..." },   // 393
    { id: "close",           label: "Close",       role: "..." },   // 394
    { id: "failure_handler", label: "Failure",     role: "..." },   // 395
  ],
};                                                            // line 397

function briefOf(kind, p) {                                   // line 494
  if (!p || typeof p !== "object") return "";                 // line 495
  if (p.decision) return String(p.decision);                  // line 496
  if (p.command || p.cmd) { ... }                             // lines 497-500
  if (p.criterion) return String(p.criterion).slice(0, 52);   // line 501
  if (p.tool_name) return String(p.tool_name);                // line 502
  if (p.pr_url) return String(p.pr_url);                      // line 503
  if (p.issue_key) return String(p.issue_key);                // line 504
  if (p.step) return String(p.step);                          // line 505
  if (p.error) return String(p.error).slice(0, 60);           // line 506
  if (p.status) return String(p.status);                      // line 507
  if (p.kind) return String(p.kind);                          // line 508
  const keys = Object.keys(p);                                // line 509
  return keys.length ? `${keys[0]}=${String(p[keys[0]]).slice(0, 40)}` : "";  // 510  ← THE BUG SURFACE
}                                                             // line 511

function foldAction(a) { ... }                                // line 545
  case "dispatch/queued":  node(a.node_id).dispatch = {...}   // lines 569-570
  case "dispatch/started": ...                                // lines 571-572
  case "dispatch/delta":   d.message_count += 1               // lines 573-574
  case "dispatch/tool_use": d.tool_use_count += 1             // lines 575-576
  case "dispatch/completed": telemetry fold                   // lines 581-600

function connect(runId) {                                     // line 639
  // event socket: view=both&replay=true
  if (!env.node_id) return;                                   // line 648
  const list = app.events.get(env.node_id) || [];             // line 649
  list.push({ ts: env.ts, kind: env.event_kind,
              payload: env.payload });                        // line 650
  app.events.set(env.node_id, list);                          // line 651
  // state socket: view=state → adoptSnapshot / foldAction    // lines 658-666

function nodesForRender() {                                   // line 995
  const spec = TOPOLOGY.dev;                                  // line 996
  return spec.map((n, i) => {
    const st = app.s.nodes[n.id] || { status: "idle" };       // line 998
    const events = app.events.get(n.id) || [];                // line 999  ← SEATS DROPPED
    ...
    dispatch: st.dispatch || null, summary: st.summary || {}, // line 1005
  });
}                                                             // line 1009

function eventRowsHtml(nodeId, events) {                      // line 1011
  if (!events.length) {
    return `<p class="muted" ...>This node has not been dispatched yet.</p>`;  // 1013
  }
  return events.slice().reverse().map((e, j) => {             // line 1015
    // ev-head: caret, fmtClock(e.ts), e.kind, rule,
    //          briefOf(e.kind, e.payload)                    // lines 1019-1024
    // expanded: <pre class="ev-json">JSON.stringify(e.payload, null, 2)</pre>  // 1026
  }).join("");
}                                                             // line 1029

function nodeMetaHtml(n) {                                    // line 1031
  const d = n.dispatch; if (!d) return "";                    // lines 1032-1033
  const bits = [];
  if (d.dispatcher) bits.push(d.dispatcher);                  // line 1035
  ...
}
```

### Payload keys now available (from TASK-2723 / TASK-2730)

```javascript
// every dispatch.* payload:
//   summary     — one line, <= 160 chars, ALWAYS present
//   task_id, task_title, seat, agent, model, subagent, judge_id, attempt
//                 (present only when the dispatch was labelled)
// tool events additionally:
//   tool_name, tool_input, tool_use_id, is_error
```

### Session-state shape now available (from TASK-2729)

```javascript
// state.nodes["development"].dispatch.seats = {
//   "development.w1": { seat, task_id, task_title, agent, model, status,
//                       started_at, finished_at, message_count,
//                       tool_use_count, last_tool, last_summary, last_error },
//   ...
// }
```

### Does NOT Exist

- ~~a build step, bundler or framework in this console~~ — `dev.html` is a
  single hand-written file with inline `<script>`. No npm, no JSX, no
  imports. Match the existing plain-DOM, template-literal style.
- ~~a shared JS module with `index.html`~~ — every function here is
  duplicated in `index.html` at different line numbers. This task edits
  `dev.html` **only**; TASK-2733 mirrors it.
- ~~`app.s.nodes["development.w1"]`~~ — session state is keyed by the ten
  `NodeId` values only. Seat detail lives at
  `app.s.nodes["development"].dispatch.seats[...]`.
- ~~a `TOPOLOGY.dev` entry per seat~~ — seats are dynamic (pool size varies
  per run); do not hardcode `w1`/`w2` into `TOPOLOGY`.
- ~~an `esc()` replacement~~ — the file already has an `esc()` helper used by
  every render function. Use it for every interpolated value.

---

## Implementation Notes

### `briefOf` — one line

```javascript
function briefOf(kind, p) {
  if (!p || typeof p !== "object") return "";
  if (p.summary) return String(p.summary).slice(0, 160);   // ← NEW, first branch
  if (p.decision) return String(p.decision);
  ...                                                       // everything else unchanged
}
```

Keep every existing branch — flow-level events (`flow.*`) do not carry a
`summary` and still rely on them.

### `nodesForRender` — claim the seats

```javascript
const ownEvents = (id) => {
  const out = [];
  for (const [nid, list] of app.events) {
    if (nid === id || nid.startsWith(id + ".")) out.push(...list);
  }
  return out.sort((a, b) => a.ts - b.ts);
};
```

Merge by timestamp so a pooled node's rows read as one chronological stream.
Node ids never contain a dot (the same invariant `_owning_node_id` relies on,
`_shared.py:53-74`), so the prefix test is exact.

### Seat badge in the rows

When `e.payload.seat` is present, prefix the row with a short badge — the seat
suffix (`w1`) plus the `task_id`:

```
14:22:07  dispatch.tool_use  [w1 · TASK-1857]  Read parrot/flows/dev_loop/…
```

Derive the short seat as `seat.split(".").pop()`. Escape everything with
`esc()`.

### Seat table in `nodeMetaHtml`

Render `d.seats` as a compact table under the node's meta line: seat, task
(id + title), agent/model, status, `msgs`/`tools` counters, and the seat's
`last_summary`. Sort by seat name so the order is stable across renders.

### Empty state

Only show *"This node has not been dispatched yet"* when the node genuinely
has no events **and** no seats. Otherwise the message contradicts the seat
table right above it.

### Key Constraints

- No new dependencies, no build step, no framework — plain DOM + template
  literals, matching the file's existing style.
- Escape every interpolated value with the existing `esc()`.
- Rendering must stay cheap: `scheduleRender` batches, and a long run holds
  thousands of events. Do not rebuild the merged list per row — compute once
  per node per render.
- The expanded-JSON view (`dev.html:1026`) keeps showing the **full** payload,
  including the raw provider event — the summary is a collapsed-row
  convenience, not a replacement.
- Do not touch the WebSocket URLs, the view parameters, or `adoptSnapshot`.

### References in Codebase

- `examples/dev_loop/static/dev.html:1031-1040` — `nodeMetaHtml`'s existing "dispatcher · N msgs · N tools" line; the seat table extends it.
- `examples/dev_loop/static/dev.html:604-620` — the `judgeVerdicts` fold, an existing example of rendering a per-actor collection.

---

## Acceptance Criteria

- [ ] `briefOf` returns `p.summary` when present, for every event kind.
- [ ] No console row renders `message_class=SystemMessage`, `codex_event=[object Object]`, or any other `keys[0]=value` fallback for a `dispatch.*` event.
- [ ] The Development card renders events from `development`, `development.w1`, `development.w2` and `development.resolver`, merged chronologically.
- [ ] Each seat-originated row shows a seat badge and its `task_id`.
- [ ] `nodeMetaHtml` renders one row per entry in `dispatch.seats`, naming the seat's current task, agent/model, status and counters.
- [ ] *"This node has not been dispatched yet"* never appears while the node has seats or events.
- [ ] A run with **no** pool (single-agent development, empty `seats`) renders exactly as it does today — no empty table, no visual regression.
- [ ] The expanded JSON view still shows the complete payload.
- [ ] The QA card shows judge-attributed rows when `judge_id` is present.
- [ ] Manual verification: load `examples/dev_loop/static/dev.html` against a replayed run and confirm the Development card is populated.

---

## Test Specification

> This console has no automated JS test harness. Verification is manual plus
> a documented replay procedure — record the evidence in the Completion Note
> and save screenshots under `artifacts/logs/feat-496/`.

```
Manual verification procedure
─────────────────────────────
1. Start the dev server:
     source .venv/bin/activate
     python examples/dev_loop/server_dev.py
2. Launch a feature-mode run with a >= 2-seat pool (or replay a finished
   run id — the state view rebuilds from `flow:{run_id}:actions` and works
   identically for a finished run).
3. Open the console and confirm, on the Development card:
     a. rows appear while workers run (not "not been dispatched yet");
     b. each row's collapsed gist is a sentence, not `key=value`;
     c. a seat badge + TASK-<NNN> is visible per row;
     d. the seat table lists every seat with its current task;
     e. expanding a row still shows the full JSON payload.
4. Confirm the QA card shows per-judge rows during the panel review.
5. Confirm a single-agent run renders unchanged.
```

Optional (nice to have, not blocking): extract `briefOf` into a `<script>`
block that can be `node`-evaluated in a smoke test, and assert
`briefOf("dispatch.message", {summary: "x"}) === "x"`.

---

## Agent Instructions

1. **Read the spec** — §1 root causes 3 and 5, §2 "Layer 4", §3 Module 8, §5 AC7, §7 "duplicated across two consoles".
2. **Check dependencies** — TASK-2723, TASK-2729 and TASK-2730 must be in `sdd/tasks/completed/`; without them there is no `summary`, no `seats` and no `task_id` to render.
3. **Verify the Codebase Contract** — re-read `dev.html:494-511`, `:995-1009` and `:1011-1040` before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** in plain DOM/template-literal style. No dependencies.
6. **Verify** by running the manual procedure; save evidence to `artifacts/logs/feat-496/`.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — record exactly what you rendered, so TASK-2733 can mirror it without re-deciding anything.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `briefOf` gained a leading `if (p.summary) return
String(p.summary).slice(0, 160);` branch. Added `ownEvents(id)` (merges
`app.events` for `id` and any `id.*` seat, sorted by `ts` ascending) and
rewired `nodesForRender` to use it instead of the bare `app.events.get(n.id)`
lookup. `foldAction` gained a new `foldSeat(n, a)` helper (the browser-side
twin of `session_state.py`'s `_fold_seat_from_action`) called from every
`dispatch/*` case (added a `dispatch/tool_result` case that previously fell
through to `default: break` — no roll-up change, seat-fold only), so
`app.s.nodes[id].dispatch.seats` builds up live from the actions stream
exactly like the roll-up counters already did — this was necessary because
the actions the browser receives are individual mutations, not full
snapshots, so the seat fold has to be replicated client-side the same way
the roll-up already is. `eventRowsHtml` renders a `[seat · task_id ·
judge_id]` badge (whichever parts are present) per row and only shows "This
node has not been dispatched yet" when the node has neither events nor
seats. `nodeMetaHtml` is UNCHANGED (still the plain "dispatcher · N msgs · N
tools" text line, safe to wrap in `esc()`); a NEW function `nodeSeatsHtml(n)`
renders the seat table as raw HTML (every interpolated value individually
escaped) — added as a sibling rather than folded into `nodeMetaHtml` because
both existing call sites wrap `nodeMetaHtml(n)`'s return value in `esc()`,
which would have HTML-escaped a literal `<table>` into visible tag text.
Wired `nodeSeatsHtml` into both the "panels" and the focus-"rail" view
(the "spine" view was left untouched — it never called `nodeMetaHtml`/
`eventRowsHtml` in the first place, and its own-node-status-driven "not
dispatched" text already satisfies AC7 without a seat-aware rewrite).

**Rendering decisions for TASK-2733 to mirror**: badge format is
`[shortSeat · task_id · judge_id]` — a single bracketed group, `·`-joined,
only the present parts; the seat table has 6 columns (`seat`, `task`,
`agent/model`, `status` as a `.pill`, `counts` as `"Nm/Nt"`, `last` as
`last_summary` falling back to `last_error`), sorted by seat id; empty-state
rule is "show 'not dispatched yet' iff zero events AND zero seats";
merge/sort rule is `ownEvents(id)`: prefix-match `id` or `id.` then sort by
`ts` ascending.

**Verification**: no live server run in this session (see
`artifacts/logs/feat-496/task-2732-smoke-evidence.md`) — instead, extracted
and `node --check`'d the real `<script type="module">` block (my first
attempt accidentally checked the wrong, tiny `<script>` tag and reported a
false "OK"; corrected the regex to `<script[^>]*>` before trusting the
result), then ran 8 runtime assertions against the extracted pure functions
(`briefOf`, `foldSeat`, `ownEvents`, `nodeSeatsHtml`) under plain Node — all
passed. Browser rendering/CSS/click-to-expand interaction is unverified;
deferred to a live/replayed run.

**Deviations from spec**: `nodeSeatsHtml` is a new function rather than a
change folded into `nodeMetaHtml` itself — required to avoid double-escaping
the seat table's HTML (see above); both call sites of `nodeMetaHtml` are
otherwise unchanged.
