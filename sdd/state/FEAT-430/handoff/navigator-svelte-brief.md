# Handoff brief — dashboard notifications settings panel (navigator-svelte)

**From:** FEAT-430 (ai-parrot) — `sdd/proposals/dashboard-scheduled-notifications-canvas.proposal.md`
**For:** a Claude Code session run **inside** `/home/jelitox/repos/Trocdigital/navigator-svelte`
**How to use:** open a session there and run that repo's own `/sdd-proposal` with this
file as the source. It has its own command, templates and CLAUDE.md — do not reuse
ai-parrot's.
**Prepared:** 2026-08-18. Read-only research; nothing in navigator-svelte was modified.

---

## 1. What the frontend must deliver

A per-dashboard **Notifications** panel (brainstorm §4.1.E) letting a user configure:

- toggle on/off; channels (Teams / Email / both)
- recipients — async-notify model: `name` + `account.provider` + `address`
- frequency: daily / weekly / days-of-week + time
- template choice, limited to the available `TEMPLATE_DIR` set (**no template editing in v1**)
- upcoming sends (`next_run`) + basic history (`last_run`, `run_count`)
- edit / pause / resume / delete

The user story: *"send this report every day via Teams to jlara@ at 6am"*.

---

## 2. Landing surface (verified in-repo)

| Element | Path | Note |
|---|---|---|
| Actions menu | `src/lib/components/dashboards/DashboardActionsDropdown.svelte` | has `Share Dashboard` (L183) and `Settings` (L219) — the natural home for a `Notifications` entry |
| Settings modal | `src/lib/fn/dashboard/components/modals/settings-modal.svelte` | existing settings surface (title, icon, layout mode, grid) |
| Share modal | `src/lib/fn/dashboard/components/modals/ShareModal.svelte` | |
| iframe widget | `src/lib/fn/dashboard/domain/iframe-widget.svelte.ts` | `IFrameWidget extends UrlManagedWidget`, has `refreshToken` + `refreshFrame()` |
| API clients | `src/lib/api/` | incl. **`ai-parrot.ts`** — the frontend already calls ai-parrot directly |
| Config | `src/lib/config.ts` | `apiBaseUrl` (`PUBLIC_API_URL`) and `apiAiUrl` (`PUBLIC_API_AI_URL`) |

**Permission patterns already in use** in the actions dropdown, to mirror on the new
entry: `isOwner`, `user.superuser`, `isCurrentUserDashboard`, `isShared`,
`currentDashboard?.is_system`, and per-dashboard toggles read from
`currentDashboard?.params?.*` (e.g. `hideCopyDashboard`).

---

## 3. Backend contract (verified in ai-parrot / navigator-api)

Schedules are rows in Postgres `navigator.agents_scheduler` (ai-parrot-server):

```
method_name      = "refresh_dashboard_artifact"
metadata         = {"dashboard_id": "<uuid>"}
schedule_type    = once|daily|weekly|monthly|interval|cron|crontab
schedule_config  = {...}          # from the panel's frequency controls
callbacks        = [...]          # delivery (Teams card / email)
enabled, last_run, next_run, run_count
```

REST CRUD exists at `/api/v1/parrot/scheduler/schedules` (+ `/callbacks` catalog,
`restart`; PATCH supports pause/resume). **It exists but has never had a real consumer** —
expect first-adopter bugs and budget for them.

**Open design decision for the frontend spec:** the panel can either
(a) call ai-parrot's scheduler CRUD directly via the existing `src/lib/api/ai-parrot.ts`
    + `apiAiUrl` pattern, or
(b) go through a **thin NavAPI wrapper** (`/api/v1/dashboards/{id}/notifications`) that
    handles dashboard scoping and permissions.
FEAT-430 §4.1.C recommends (b) so the UI never touches the generic scheduler surface —
but (a) is the path the repo already has wiring for. **Decide this explicitly.**

---

## 4. Constraints inherited from FEAT-430 (do not re-litigate)

- **D2 — link target:** the delivered link points at the Navigator **dashboard share
  page** `/share/dashboard/<dashboard_id>` (singular).
- ⚠️ **TRAP:** `/share/dashboards/<snapshotId>` (plural) is backed by `SnapshotService`
  over **browser storage** (`STORAGE_KEY = "shared_snapshots"`). A scheduled send has no
  browser — **that route cannot be used here.** The two differ by one character.
- **D4 — templates:** file-based only. async-notify resolves `template=` as a *filename*
  via `FileSystemLoader`; there is no inline-Jinja support. The panel therefore offers a
  **fixed list**, never a free-text template field. Config key is `TEMPLATE_DIR`.
- **HI-4:** delivery is card + URL only; artifacts are never attached.
- **Coexistence:** `Dashboard.attributes.artifact_type` = `v1-html` | `v2-a2ui`, default
  `v1-html` when absent. The panel must behave identically for both — it is scheduling
  metadata, not generation config.

---

## 5. Prior art in this repo — read before speccing

`sdd/specs/`: `modal-share.spec.md`, `actualizacion-sistema-notificacion.spec.md`,
`bug-notificaciones.spec.md`, `notificacion-briefing.spec.md`, `dashboard-customize.spec.md`

There is already a notification system in this frontend. **Establish whether the new
panel extends it or stands beside it** — that is the first question the proposal should
answer, and it is not answered by FEAT-430.

---

## 6. Suggested open questions for the frontend proposal

1. Does the panel live inside `settings-modal.svelte` as a section, or as its own modal
   off `DashboardActionsDropdown`?
2. Direct ai-parrot call vs NavAPI wrapper (see §3)?
3. Relationship to the existing notification system (see §5)?
4. Recipient picker: free-text address, or a directory/user lookup?
5. Which permission gate — `isOwner`, `superuser`, or a new capability?
6. Mobile/Capacitor behavior for the panel?

---

## 7. Coordination

`navigator-svelte` runs an independent SDD flow (own FEAT numbering, FEAT-475+). This
work needs **its own FEAT-ID there**; FEAT-430 cannot carry it. For backend asks, follow
the existing convention: `sdd/BACKEND-REQUEST-<topic>.md` addressed to the owning repo
and citing the requesting FEAT/TASK — see `sdd/BACKEND-REQUEST-event-name.md`.

A draft of that request is provided alongside this brief:
`BACKEND-REQUEST-dashboard-notifications.md`.
