<!-- LANGUAGE: This document MUST be written entirely in English (proper nouns keep native spelling). -->
<!-- DRAFT prepared by FEAT-430 (ai-parrot). Move to navigator-svelte/sdd/ and adjust the
     requesting FEAT/TASK ids once that repo allocates them. -->

# Backend request — dashboard-scoped notification schedules

**For**: owners of **ai-parrot** (`packages/ai-parrot-server`) and **navigator-api**
**Requested by**: navigator-svelte, FEAT-<TBD> (dashboard notifications settings panel)
**Related**: FEAT-430 (ai-parrot) — `sdd/proposals/dashboard-scheduled-notifications-canvas.proposal.md`
**Date**: 2026-08-18
**Size**: medium — one new endpoint surface, one additive model field

---

## 1. Why

The settings panel lets a user configure, per dashboard: *"send this report every day via
Teams to jlara@ at 6am"*. Everything it needs exists in
`navigator.agents_scheduler` — but the panel cannot talk to the generic scheduler CRUD
directly without leaking scheduler concepts (`agent_id`, `method_name`, callback shapes)
into the dashboard UI, and without a permission boundary tied to the dashboard.

---

## 2. What is requested

### 2.1 A dashboard-scoped schedule endpoint (navigator-api)

`/api/v1/dashboards/{dashboard_id}/notifications` — CRUD + pause/resume, translating to
the existing scheduler CRUD. Responsibilities:

- enforce dashboard-level permissions (owner / superuser), reusing the guards the UI
  already applies (`isOwner`, `user.superuser`, `is_system`)
- inject `method_name = "refresh_dashboard_artifact"` and
  `metadata = {"dashboard_id": ...}` so the UI never supplies them
- supply the sentinel `agent_id` / `agent_name` the scheduler model requires (they are
  `required=True` with `Meta.strict = True`, and a dashboard refresh is not an agent)
- expose `next_run`, `last_run`, `run_count` for the panel's "upcoming + history" section

Request/response shape the panel needs:

```jsonc
{
  "enabled": true,
  "channels": ["teams", "email"],
  "recipients": [{"name": "...", "provider": "...", "address": "..."}],
  "schedule_type": "daily",
  "schedule_config": {"time": "06:00", "days": ["mon","tue"]},
  "template": "<one of the TEMPLATE_DIR names>",
  // read-only:
  "next_run": "...", "last_run": "...", "run_count": 0
}
```

### 2.2 A template catalog endpoint

The panel must offer a **fixed list** of templates — async-notify resolves `template=` as
a filename via `FileSystemLoader` and has no inline-template support, so free text is
invalid input. Please expose the available `TEMPLATE_DIR` names.

### 2.3 `Dashboard.attributes.artifact_type` (navigator-api) — additive, no migration

`{"artifact_type": "v1-html" | "v2-a2ui"}`, **absent meaning `v1-html`**, so existing
dashboards are untouched. `attributes` is already JSONB; the frontend already reads
per-dashboard flags from `params` (e.g. `hideCopyDashboard`), so this pattern is familiar.
The panel itself is agnostic to the value — it is listed here only so both repos agree on
where the discriminator lives.

---

## 3. What is NOT requested

- No template CRUD, no DB-backed template store (YAGNI per FEAT-430 HI-5).
- No new sharing mechanism. FEAT-430 decision D1 adopts the existing FEAT-197 HMAC-signed
  artifact URLs + `ArtifactStore` presigned S3.
- No changes to `/share/dashboard/<dashboard_id>` — the panel links to it as-is.

---

## 4. Notes / gotchas found while researching

- **`SendNotifyReportCallback` auto-attaches a CSV** whenever the result payload is
  DataFrame-coercible (`attach_data` defaults to `True`). For dashboard sends this must be
  off — FEAT-430 HI-4 says card + URL only, never attachments.
- **`BaseSchedulerCallback.process_output()` assumes an `AIMessage`.** A plain dict from
  `refresh_dashboard_artifact` stringifies into the message body. The card-aware callback
  needs its own payload contract.
- The scheduler CRUD **has never had a real consumer**; this panel is its first. Please
  budget for validation/error-handling gaps surfacing on first adoption.
