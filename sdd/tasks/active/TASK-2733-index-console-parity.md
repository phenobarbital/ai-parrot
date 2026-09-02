# TASK-2733: `index.html` — mirror the console treatment

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2732
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, §5 AC7b, §8 (resolved: *"Yes — `index.html` gets the
identical treatment"*).

`examples/dev_loop/static/index.html` is the bug/feature-mode console. It
carries its **own independent copy** of every function TASK-2732 changed —
`briefOf`, `foldAction`, `nodesForRender`, `eventRowsHtml`, `nodeMetaHtml` —
at different line numbers. There is no shared JS module between the two
consoles, so a fix landing in only one of them is the exact failure mode this
task exists to prevent.

One structural difference matters: `index.html` switches topology on
`app.mode` (`index.html:775`, `TOPOLOGY.bug` / `TOPOLOGY.feature`,
`:336-350`), so the seat-grouping rule must work for **both** topologies, not
just the feature one.

This task deliberately **adopts** TASK-2732's decisions rather than
re-deciding them. Read that task's Completion Note first — it records the seat
badge format, the seat table columns, the empty-state rule and the merge/sort
rule. Divergence between the two consoles is a defect.

---

## Scope

- Apply the identical `briefOf` summary branch to `index.html:447`.
- Apply the identical seat-claiming rule to `nodesForRender`
  (`index.html:774-788`), working for both `TOPOLOGY.bug` and
  `TOPOLOGY.feature`.
- Apply the identical seat badge rendering to `eventRowsHtml`
  (`index.html:790`).
- Apply the identical seat table to `nodeMetaHtml` (`index.html:810-818`).
- Apply the identical empty-state rule (`index.html:792`).

**NOT in scope**: `dev.html` (TASK-2732 owns it); `afd.html` (Non-Goal); any
Python; inventing a rendering that differs from TASK-2732's.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/static/index.html` | MODIFY | mirror TASK-2732's five function changes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures

```javascript
// examples/dev_loop/static/index.html — INDEPENDENT copies of dev.html's functions
const TOPOLOGY = {                                            // line 336
  bug: [                                                      // line 337
    { id: "intent_classifier",  label: "Classify",    ... },  // line 338
    { id: "bug_intake",         label: "Bug Intake",  ... },  // line 339
    { id: "research",           label: "Research",    ... },  // line 340
    { id: "development",        label: "Development", ... },  // line 341
    { id: "qa",                 label: "QA",          ... },  // line 342
    { id: "deployment_handoff", label: "Handoff",     ... },  // line 343
    { id: "close",              label: "Close",       ... },  // line 344
    { id: "failure_handler",    label: "Failure",     ... },  // line 345
  ],
  feature: [                                                  // line 346
    { id: "intent_classifier",  label: "Classify",    ... },  // line 347
    { id: "planner",            label: "Planner",     ... },  // line 348
    { id: "development",        label: "Development", ... },  // line 349
    { id: "synthesis",          label: "Synthesis",   ... },  // line 350
    { id: "qa", ... }, ...
  ],
};

function briefOf(kind, p) {                                   // line 447
  ...
  if (p.tool_name) return String(p.tool_name);                // line 455
  ...
  const keys = Object.keys(p);                                // line 463
  return keys.length ? `${keys[0]}=${String(p[keys[0]]).slice(0, 40)}` : "";  // 463
}

function foldAction(a) { ... }                                // line 498
  // dispatch.status = "running" etc.                         // line 525

// event socket handler — seats ARE stored, exactly like dev.html
const list = app.events.get(env.node_id) || [];               // line 602
app.events.set(env.node_id, list);                            // line 604

function nodesForRender() {                                   // line 774
  const spec = TOPOLOGY[app.mode] || TOPOLOGY.bug;            // line 775  ← TWO topologies
  return spec.map((n, i) => {
    const st = app.s.nodes[n.id] || { status: "idle" };       // line 777
    const events = app.events.get(n.id) || [];                // line 778  ← SEATS DROPPED
    ...
    dispatch: st.dispatch || null, summary: st.summary || {}, // line 784
  });
}                                                             // line 788

function eventRowsHtml(nodeId, events) {                      // line 790
  if (!events.length) {
    return `<p class="muted" ...>This node has not been dispatched yet.</p>`;  // 792
  }
  ...
}

function nodeMetaHtml(n) {                                    // line 810
  const d = n.dispatch; if (!d) return "";                    // lines 811-812
  const bits = [];
  if (d.dispatcher) bits.push(d.dispatcher);                  // line 814
  if (d.message_count) bits.push(`${d.message_count} msgs`);  // line 815
  if (d.tool_use_count) bits.push(`${d.tool_use_count} tools`);// line 816
  return bits.join(" · ");                                    // line 817
}                                                             // line 818

app.events = new Map();                                       // lines 1472, 1513
```

### The reference implementation

```
examples/dev_loop/static/dev.html — as delivered by TASK-2732:
  briefOf         (was line 494)
  nodesForRender  (was line 995)
  eventRowsHtml   (was line 1011)
  nodeMetaHtml    (was line 1031)
Read the delivered code, not these pre-change line numbers.
```

### Does NOT Exist

- ~~a shared JS module between `dev.html` and `index.html`~~ — the whole
  reason this task exists. Do **not** try to extract one as part of this
  task; that is a refactor, not this scope.
- ~~`TOPOLOGY.dev` in `index.html`~~ — this file has `bug` and `feature`, and
  selects via `app.mode` (`:775`). Do not copy `dev.html`'s `TOPOLOGY.dev`
  reference across.
- ~~a build step or framework~~ — plain DOM + template literals, same as
  `dev.html`.
- ~~a different `esc()` helper~~ — `index.html` has its own; use it.

---

## Implementation Notes

### Read TASK-2732 first

Open `sdd/tasks/completed/TASK-2732-dev-console-summary-and-seats.md` and its
Completion Note, then open the delivered `dev.html`. Copy the *decisions*
(badge format, table columns, sort rule, empty-state rule) exactly. Adapt only
what the file structurally requires:

- `TOPOLOGY[app.mode] || TOPOLOGY.bug` instead of `TOPOLOGY.dev`;
- `index.html`'s own `esc()` and CSS class names;
- its own line positions.

### Both topologies

The `bug` topology also has a `development` node (`index.html:341`), so pooled
seats appear there too. Verify the seat grouping in **both** modes, not just
`feature`.

### Key Constraints

- **No divergence.** If something in `dev.html` turned out to need a different
  shape than TASK-2732 specified, change **both** files and say so in the
  Completion Note — never leave the two consoles rendering differently.
- No new dependencies, no build step.
- Escape every interpolated value.
- A single-agent run must render exactly as it does today in both modes.

### References in Codebase

- `examples/dev_loop/static/dev.html` — the reference implementation (post-TASK-2732).
- `examples/dev_loop/static/index.html:774-818` — the block being mirrored.

---

## Acceptance Criteria

- [ ] **AC7b** — `index.html`'s `briefOf` returns `p.summary` when present.
- [ ] No row renders a `keys[0]=value` fallback for a `dispatch.*` event.
- [ ] Seat events (`development.w1`, `development.resolver`, …) render under the `development` card in **both** the `bug` and `feature` topologies.
- [ ] Seat badges and the seat table match `dev.html`'s format exactly — same columns, same ordering, same badge shape.
- [ ] The empty-state rule matches `dev.html`'s.
- [ ] A single-agent run renders unchanged in both modes.
- [ ] A visual diff of the two consoles' Development cards on the same replayed run shows no rendering difference.
- [ ] Manual verification recorded in the Completion Note, with evidence under `artifacts/logs/feat-496/`.

---

## Test Specification

> No automated JS harness (same as TASK-2732). Verification is manual, plus a
> direct comparison against `dev.html`.

```
Manual verification procedure
─────────────────────────────
1. source .venv/bin/activate && python examples/dev_loop/server_dev.py
2. Replay the SAME finished run id in both consoles:
     - examples/dev_loop/static/dev.html
     - examples/dev_loop/static/index.html   (mode=feature)
   Confirm the Development cards render identically.
3. Replay a bug-mode run in index.html (mode=bug) and confirm the
   development node groups its seats there too.
4. Replay a single-agent run in both modes; confirm no visual regression.
5. Diff the two files' briefOf / nodesForRender / eventRowsHtml /
   nodeMetaHtml bodies and confirm they differ only in TOPOLOGY selection,
   esc()/class names and line positions.
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 9, §5 AC7b, §7 "duplicated across two consoles".
2. **Check dependencies** — TASK-2732 must be in `sdd/tasks/completed/`. Read its Completion Note **and** the delivered `dev.html` before writing anything.
3. **Verify the Codebase Contract** — confirm `index.html:447`, `:463`, `:774-788`, `:790-792`, `:810-818` before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** — mirror, do not re-invent.
6. **Verify** with the procedure above, including the two-console comparison.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — note any place where you had to change `dev.html` too.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Any change back-ported to `dev.html`**: none | describe

**Deviations from spec**: none | describe if any
