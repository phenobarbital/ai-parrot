# TASK-2130: static/dev.html — development-only UI with interactive HITL panel

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2129
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 + §2 REMOVED/ADDED/KEPT lists. Copy-and-trim of
`index.html` (single file, inline CSS + vanilla ES module, no build step,
no templating): drop every ops surface, add the interactive Open-Questions
panel and the plan-approval toggle. `index.html` stays byte-identical.

---

## Scope

Starting from a copy of `examples/dev_loop/static/index.html`:

- **REMOVE** (line refs into index.html, verified 2026-08-05):
  - `#work-intake` bug wording/placeholder (:221–233 — replace with NL
    title + description intake)
  - `TOPOLOGY.bug` (:337–346) and `KIND_HINTS` bug entries (:361–363)
  - ops tab bodies `criteria`/`context`/`observability`/`jira`
    (:1125–1168) and `tabsForMode()` bug tab list (:1088–1092)
  - `buildPayload()` bug branch (:1331–1347)
  - form state `affectedComponent`/`logGroup`/`timeWindow`/
    `existingIssueKey` (:416–417), `criteriaSummary()` (:696–706),
    `renderReady()` bug rows (:720–728)
- **ADD**:
  - 3-intent picker: `enhancement` / `new_feature` / `feature` (document);
    NL intake (title input + description textarea) for the first two;
    document path/kind intake (existing pattern :235–247) for `feature`.
  - `TOPOLOGY.dev = [dev_intake, ideation, planner, development, synthesis,
    qa, feedback_router, feature_handoff, close, failure_handler]`.
  - **Open-Questions panel**: on `gate/opened` action with
    `kind === "open_questions"`, render one input per `gate.questions[]`
    + Submit (POST the gate-resolve route from `/api/config` with
    `resolution:"approved"`, `resolved_by`, `answers:{q: a}`; partial
    answers allowed) + Reject/abort button (`resolution:"rejected"`).
    Show the gate title (carries the document path — resume/extend
    detection).
  - **Plan-approval toggle** in advanced options → `require_plan_approval`
    in the run payload; `plan_approval` gates render in the same HITL panel
    as approve/reject + comment (no answers inputs).
  - `localStorage` theme key `"devflow-theme"` (not `"afd-theme"`).
- **KEEP**: stepper, execution views (panels/spine/rail), `foldAction`
  vocabulary (gates actions already folded :497–571), dispatch telemetry,
  judge verdicts, feedback decisions, docs artifact, PR summary card,
  bundle/report actions, cancel/restart, theme toggle.

**NOT in scope**: server changes (TASK-2129), any edit to `index.html` or
`afd.html`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/static/dev.html` | CREATE | Development-only console |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```javascript
// examples/dev_loop/static/index.html — verified 2026-08-05
// TOPOLOGY (:336-358)      — hardcoded node lists per mode; add "dev"
// emptyState() (:387-393)  — {phase, nodes, gates, prUrl, ...}
// app.form (:412-420)      — form model to slim down
// adoptSnapshot() (:472)   — snake_case snapshot → client state (gates incl.)
// foldAction() (:497-571)  — action vocabulary; gate/opened payload is
//                            a.gate {gate_id, kind, title, node_id}
//                            (+ questions[] after TASK-2122);
//                            gate/resolved {gate_id, resolution,
//                            resolved_by, comment} (+ answers)
// connect(runId) (:581-625) — two sockets: ?view=both&replay=true and
//                            ?view=state (snapshot|action envelopes)
// renderExecution() (:782-878), renderSummary() (:929-1075),
// gate audit trail (:1030-1041) — KEEP
// buildPayload() (:1331+)  — feature branch stays; bug branch removed
// boot (:1571-1588)        — /api/config fetch + degraded fallback
```

```
# Server routes available (TASK-2129 — read its /api/config for the
# gate-resolve URL template):
POST <resolve route>  body: {resolution, resolved_by, comment, client_seq,
                             answers}
POST /api/flow/run · POST /api/flow/{id}/cancel ·
GET /api/flow/{id}/ws?view=... · GET /api/flow/{id}/bundle
```

### Does NOT Exist
- ~~templating/placeholders~~ — dev.html is fully static; all dynamic
  values come from `GET /api/config` at boot.
- ~~an interactive gate UI in index.html~~ — today gates render read-only
  (audit trail); the prompt/answer panel is NET-NEW here.
- ~~`afd.html` design-system assets (`_ds/...`, `support.js`)~~ — dead
  references; do not copy them in.
- ~~a shared JS bundle between index.html and dev.html~~ — accepted
  duplication (spec §7); do not extract shared modules in this task.

---

## Implementation Notes

### Key Constraints
- Keep the single-file/no-build constraint: inline CSS + one ES module.
- `gate/opened` may arrive in the replay/snapshot as an already-pending
  gate — the HITL panel must render from STATE (`app.s.gates`), not only
  from live actions (reconnect case).
- After a successful resolve POST, do not mutate local state directly —
  the `gate/resolved` action arrives on the state socket (single source of
  truth).
- `resolved_by`: use a small persisted client identity (e.g.
  `localStorage["devflow-user"]` with a prompt fallback) — the REST body
  requires min_length 1.
- Summary must render `document_kind`/document path when available
  (ideation output surfaces via node summary), and keep treating "no
  pr_url" as failure (index.html:893-917 precedent).

### References in Codebase
- `examples/dev_loop/static/index.html` — the source to trim
- spec §2 "server_dev.py and dev.html (deliverable shape)"

---

## Acceptance Criteria

- [ ] No bug-intake, CloudWatch, affected-component, or mandatory-Jira UI anywhere in dev.html
- [ ] Intent picker drives the three payload shapes; run starts and streams
- [ ] A live `open_questions` gate renders inputs and resolves end-to-end from the browser (answers reach the server; run resumes)
- [ ] `plan_approval` gate renders approve/reject+comment in the same panel when the toggle was set
- [ ] Reconnect mid-gate re-renders the pending gate from the snapshot
- [ ] `index.html` byte-identical (`git diff --name-only` clean of it)

---

## Test Specification

> UI is exercised through TASK-2129's aiohttp integration tests plus a
> manual checklist (no JS test harness exists in the repo — do not add one).

```
Manual checklist (record results in the Completion Note):
1. enhancement run → ideation asks 2 questions → answer → draft PR summary
2. new_feature run → same, document is .brainstorm.md
3. feature run with existing proposal → ideation skipped
4. plan toggle on → plan gate appears → approve → development proceeds
5. reject open_questions gate → run fails to failure_handler
6. reload page mid-gate → pending gate re-renders → resolve works
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2129 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
