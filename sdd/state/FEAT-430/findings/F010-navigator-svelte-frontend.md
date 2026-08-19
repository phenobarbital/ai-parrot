# F010 — The frontend is navigator-svelte (separate org folder, separate SDD flow)

**Query:** Q012 follow-up (post-synthesis correction)
**Repo:** `/home/jelitox/repos/Trocdigital/navigator-svelte` — note **`Trocdigital/`**, not
`trocglobal/`. Not covered by the original research plan.
**Citations:**
  `src/lib/helpers/module/share.ts` L102; `src/lib/components/modules/Module.svelte` L502
  `src/lib/fn/share/snapshot-service.ts` L29, L112-121
  `src/lib/fn/dashboard/components/modals/ShareWidgetModal.svelte` L33-36
  `src/lib/fn/dashboard/domain/iframe-widget.svelte.ts` L12-23
**Confidence:** high (direct source read)

## Correction to this proposal's own research scope

Q012 targeted `navigator-front` (in `trocglobal/`) as "the Svelte 5 frontend". The
**actual** frontend for dashboards is `navigator-svelte`, in a different org folder.
Brainstorm §4.1.E was therefore verified against the wrong repository.

`navigator-svelte` has its **own independent SDD flow** — `sdd/{specs,proposals,tasks,
state,reviews,reports,templates,WORKFLOW.md}` — with its own FEAT numbering (FEAT-475+
in recent commits, vs ai-parrot's 430). **FEAT-430 cannot carry frontend tasks**; the
settings panel needs its own FEAT-ID in that repo.

It also has an established cross-repo convention: `sdd/BACKEND-REQUEST-<topic>.md`,
addressed to the owner of another repo and citing the requesting FEAT/TASK
(example: `BACKEND-REQUEST-event-name.md`, from FEAT-418 / TASK-798 to the fieldsync repo).

## TRAP: two share routes, only one is usable for scheduled delivery

| Route | Backing | Usable by scheduler? |
|---|---|---|
| `/share/dashboard/<dashboard_id>` (singular) | server-side; the URL `navigator-api` builds in F005 | **YES** — this is decision D2's target |
| `/share/dashboards/<snapshotId>` (plural) | `SnapshotService` over **browser storage** (`STORAGE_KEY = "shared_snapshots"`, `storage.get/set`) | **NO** |

The plural route creates a **client-side snapshot living in browser storage**
(`ShareWidgetModal.svelte` L33-36, `DashboardShell.svelte` L85,
`dashboard-container.svelte` L59). A scheduled send has no browser and no user session,
so this mechanism cannot participate in SPEC-A. The spec must state this explicitly —
the two routes differ by a single character and one of them is a dead end.

## Q5 partially RESOLVED: the iframe widget is a real domain entity

```ts
export class IFrameWidget extends UrlManagedWidget {
  sandboxAttr = $state<string>("allow-scripts allow-same-origin");
  allowFullscreen = $state<boolean>(true);
  refreshToken = $state<number>(0);
  // onRefresh -> widget.refreshFrame()
}
```

The URL is owned by the `UrlManagedWidget` base class, so widget → artifact-URL
resolution exists on the frontend side. What remains for Q5 is its **persisted backend
counterpart** (which table stores the widget and its URL), still not located in
`navigator-api/resources/dashboards`.

## Open design point CLOSED: iframe cache behavior after refresh

Brainstorm §4.1.B lists "versioned S3 keys vs stable-key overwrite (iframe cache
behavior)" as unresolved. `IFrameWidget` already ships a cache-busting refresh path —
`refreshToken` state plus `refreshFrame()` wired to an `onRefresh` handler. A stable
S3 key plus a refresh-token bump is therefore viable; versioned keys are not required
purely for cache reasons.

## Prior art to read before speccing the panel

`sdd/specs/` in navigator-svelte already contains: `modal-share.spec.md`,
`actualizacion-sistema-notificacion.spec.md`, `bug-notificaciones.spec.md`,
`notificacion-briefing.spec.md`, `dashboard-customize.spec.md`.
