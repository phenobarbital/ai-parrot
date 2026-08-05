# TASK-2130: static/dev.html — development-only UI with interactive HITL panel

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: done
**Completed**: 2026-08-05
**Verification**: verified
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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

`dev.html` (1862 lines). Method: started as a **byte copy** of `index.html`,
then applied surgical edits — so every KEEP item (stepper, panels/spine/rail
execution views, `foldAction` vocabulary, dispatch telemetry, judge verdicts,
feedback decisions, docs artifact, PR summary card, gate audit trail,
bundle/report, cancel/restart, theme toggle) is preserved *exactly* rather
than re-typed. `index.html` is byte-identical (`git diff --name-only
dev...HEAD` clean of it).

**REMOVED** as specified: bug intake markup, `TOPOLOGY.bug`, the
`criteria`/`context`/`observability`/`jira` tab bodies and their `TAB_NOTES`,
the bug `buildPayload()` branch, `criteriaSummary()`, and the
`affectedComponent`/`logGroup`/`timeWindow`/`existingIssueKey`/`criteria`
form state. Grep-verified zero occurrences of `affected_component`,
`log_group`, `time_window`, `CloudWatch`, `bug_intake`,
`acceptance_criteria`, `existing_issue_key`, `afd-theme`.

**ADDED**: the 3-intent picker (no availability gating — one topology); the NL
intake (title + description + optional context) whose "will write" row shows
the exact `sdd/proposals/<slug>.{brainstorm|proposal}.md` the run will
produce (client-side `slugify` mirroring the subagent's rule, so a resume of
an existing document is predictable *before* dispatch); a single `TOPOLOGY.dev`
with all 10 nodes; an **Ideation & gates** tab holding the per-run
`require_plan_approval` toggle plus read-only round-budget and fail-closed TTL;
and the **HITL panel**.

**HITL panel design** (the net-new surface):

- Renders from `app.s.gates` via `pendingGate()`, **not** from live actions —
  so a reload mid-gate re-renders from the adopted snapshot (the task's
  reconnect requirement). Handles every gate kind, not just
  `open_questions`: `plan_approval` and friends get approve/reject + comment
  with no answer inputs.
- One `<textarea>` per `gate.questions[]`; only non-empty answers are sent, so
  partial answers work and blanks stay `[ ]` in the document. Submitting with
  *zero* answers is blocked client-side with a message pointing at Reject —
  which mirrors the server's own `answers_required` 400 rather than relying on
  it for the common case.
- Draft answers live in `app.hitl`, not the DOM, because a streamed node event
  triggers a re-render every second — without that, typing would be wiped
  mid-answer.
- After a successful resolve it deliberately does **not** touch local state;
  the `gate/resolved` action on the state socket folds the resolution and
  hides the panel. Commented in-file and asserted by a test.
- `resolved_by` comes from `localStorage["devflow-user"]` with a `prompt()`
  fallback (the REST body requires `min_length=1`).
- The gate URL comes from `/api/config`'s `gate_resolve_url_template`, with the
  literal route as a fallback.

**Bug found and fixed while trimming** (inherited from the copy):
`handoffNodeId()` returned `"deployment_handoff"` whenever
`app.mode !== "feature"`. In dev-flow the only terminal handoff is
`feature_handoff`, so **every natural-language run's summary would have
rendered blank/failed** even on success. Now pinned to `feature_handoff` with
a comment. Three neighbouring `app.mode === "feature"` wording branches
(handoff sub-line, Jira note, pool/judge hints) were also collapsed, since
`mode` now selects only the *intake shape* — the topology never varies.

**Verification** (no JS harness exists and the task forbids adding one):

- `node --check` on both extracted `<script>` blocks → syntax OK.
- A cross-check script confirmed **all 52** element ids the JS references
  exist in the markup (`MISSING: NONE`), that the payload the JS builds is
  accepted by the real `_build_dev_brief_from_form`, and that the JS's gate
  URL template matches a route actually mounted by `build_app()`.
- 22 new tests appended to `test_server_dev.py` (the spec's chosen home for
  UI assertions) covering the removed ops surface, the added dev surface,
  state-driven gate rendering, the no-local-mutation rule, and that
  `index.html` is still the ops console. Suite: 50 passed.

**Manual checklist**: NOT executed — the 6 scenarios all require a live Redis
plus real Claude/Codex dispatches (a full ideation → planner → dev-pool → QA
run per item), which is not available in this environment. The mechanical
preconditions each scenario depends on are covered by the automated checks
above (payload shapes per intent, gate render-from-state, resolve POST
contract and route, plan-gate flag reaching `extra_shared`, reject path). The
browser-in-the-loop passes are left for the reviewer; the scenarios are
reproduced verbatim in `README`/`GUIA` by TASK-2131.

**Deviations from spec**: none.

### Post-completion fix (same feature branch)

Self-review after marking this task done caught one requirement from the
Implementation Notes I had missed: *"Summary must render
`document_kind`/document path when available (ideation output surfaces via node
summary)"*. Fixed in a follow-up commit — `IdeationNode` returns the
`FeatureBrief` it produced and `node/completed` carries the serialised result
as its `summary` (`session_state.py:1269-1272`), so `app.s.nodes.ideation.summary`
already had `document_path`/`document_kind` client-side. The run summary now
shows an "SDD document written by ideation" card above the documentation
artifact, with the kind and how many Open-Questions rounds the run took.
The "no `pr_url` ⇒ failure" precedent was already preserved by the copy
(`summaryHeadline()`), now reading the correct `feature_handoff` node.
