# Connections map — where each project advances

**Scope:** the two deliverables of `BRAINSTORM-dashboard-notify-canvas.md` (rev 2.1).
**Status:** proposals done everywhere; **no specs, no tasks yet** — that is the next step
in each project, run from inside that project.
**Updated:** 2026-08-19

---

## The architectural rule (F011)

> Any parrot implementation is implemented in **navigator-api**.

`ai-parrot` is the **framework**, consumed by navigator-api as a published dependency
(`ai-parrot[...]>=0.16.10`; the editable local path is deliberately commented out).
`navigator-api` is the **application**: it constructs `BotManager` and
`AgentSchedulerManager` and mounts parrot's handlers (`app.py` L412-425).

Consequence: the `sdd/` proposals living in the ai-parrot repo are **design documents**,
not the implementation home. Implementation lands in navigator-api and navigator-svelte.

---

## SPEC-A — Scheduled dashboard delivery (v1, the PoC)

| Project | What it does | Where | State |
|---|---|---|---|
| **navigator-api** | `refresh_dashboard_artifact()`, card-aware scheduler callback, thin wrapper `/api/v1/dashboards/{id}/notifications`, `Dashboard.attributes.artifact_type` | *no `sdd/` flow — see Gaps* | ✗ not started |
| **navigator-svelte** | Notifications settings panel | branch `feat/dashboard-notifications-panel`, **FEAT-496** | proposal ✓ · spec ✗ · tasks ✗ |
| **ai-parrot** | design + audit only (FEAT-430); **no new code expected** | branch `feat/dashboard-scheduled-delivery` | proposal ✓ |

**Entry points**
- Design: `sdd/proposals/dashboard-scheduled-notifications-canvas.proposal.md` (on `dev`)
- Audit: `sdd/state/FEAT-430/` — 11 findings
- Frontend brief: `sdd/state/FEAT-430/handoff/navigator-svelte-brief.md` (**read the rev-2 ERRATA**)
- Backend ask: `sdd/state/FEAT-430/handoff/BACKEND-REQUEST-dashboard-notifications.md`

**Order of work.** The frontend is **blocked** until the navigator-api endpoint exists.
The first real task of SPEC-A is the BACKEND-REQUEST, not code.

---

## SPEC-B — Artifact & Canvas Builder (v2, A2UI)

| Project | What it does | Where | State |
|---|---|---|---|
| **navigator-api** | agent → A2UI generation for a dashboard; reverse-adapter consumption | *no `sdd/` flow — see Gaps* | ✗ not started |
| **ai-parrot** | reverse adapter A2UI → canvas block vocabulary (**framework-level, genuinely belongs here**); supersede FEAT-301 | branch `feat/artifact-canvas-builder-a2ui`, **FEAT-431** | proposal ✓ |
| **navigator-svelte** | Canvas Builder UI | **no FEAT-ID yet** | ✗ not started |

**Entry points**
- Design: `sdd/proposals/artifact-canvas-builder-a2ui.proposal.md` (on its branch)
- Audit: `sdd/state/FEAT-431/` — 5 findings

**Note.** SPEC-B is the one place where an ai-parrot code change is expected: the reverse
adapter sits beside the existing `outputs/a2ui/adapters/infographic.py`, which is
framework, not application. That still implies a **release cycle**, since navigator-api
pins a published version.

---

## Cross-project conventions

- **Backend asks** use `sdd/BACKEND-REQUEST-<topic>.md` in the *requesting* repo,
  addressed to the owning repo and citing the requesting FEAT/TASK
  (precedent: `navigator-svelte/sdd/BACKEND-REQUEST-event-name.md`).
- **FEAT-IDs are per repo.** ai-parrot is at 430/431; navigator-svelte at 496. They do
  not share a ledger and must not be cross-referenced as if they did.

---

## Gaps that block advancing

1. **navigator-api has no `sdd/` flow.** It is the implementation home for most of
   SPEC-A and part of SPEC-B, yet has no `sdd/` tree, no templates and no FEAT ledger.
   Decide: bootstrap SDD there, or track its work from another repo's spec.
   *This is the single biggest blocker to César starting SPEC-A.*
2. **No specs or tasks anywhere.** Every lane holds a proposal only. Each needs
   `/sdd-spec` then `/sdd-task`, run **inside its own repo** so it picks up that repo's
   command, templates and conventions.
3. **SPEC-B's Canvas Builder has no FEAT-ID** in navigator-svelte.
4. **Two open decisions** carried in FEAT-496: panel mount (overlay vs local component —
   see F009, it costs two extra files as an overlay) and how to structure tasks while the
   backend is blocked.
