# TASK-2529: Admin UI pages — Home and Status Dashboard

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2526, TASK-2528
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (Home/Dashboard behavior) + §3 Module 5. First real
content on the shell: the welcome Home and the status Dashboard rendering
`GET /api/v1/admin/status` with generated types.

---

## Scope

- `Home.svelte` (replaces placeholder): server identity (name + version
  from the status payload), welcome copy, navigation cards to Dashboard and
  Agents (uses the nav registry).
- `Dashboard.svelte` (replaces placeholder):
  - Fetches `GET /api/v1/admin/status` via the API client using the
    GENERATED `AdminStatus` type (TASK-2526 output) — no hand-written
    status types.
  - Tiles/cards: version, formatted uptime, agent counts
    (database/registry/loaded), crews count.
  - Dependency health list: postgres / redis / vector_store with per-entry
    status badge (`ok` green, `unreachable` destructive, `unconfigured`
    muted) + optional detail/latency.
  - Auto-refresh on an interval (default 15s, cleared on unmount); manual
    refresh button; last-updated timestamp.
  - Loading skeletons + error state (fetch failure shows a retry card, does
    not blank the shell; 401 handled by the interceptor from TASK-2527).
- A small `StatusTile.svelte` / `HealthBadge.svelte` component pair in
  `ui/src/lib/components/` reusable by future dashboards.
- Vitest suites with mocked API responses (ok, degraded dependency, fetch
  error).

**NOT in scope**: charts/telemetry (out of spec), agents page (TASK-2530).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/pages/Home.svelte` | MODIFY | real content |
| `packages/ai-parrot-server/ui/src/pages/Dashboard.svelte` | MODIFY | real content |
| `packages/ai-parrot-server/ui/src/lib/components/{StatusTile,HealthBadge}.svelte` | CREATE | reusable tiles |
| corresponding `*.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Backend API contract (verified at spec time; re-verify after TASK-2524)
```text
GET /api/v1/admin/status  (created by TASK-2524, @is_authenticated)
→ AdminStatus JSON:
  { name, version, uptime_seconds,
    agents: {database, registry, loaded}, crews,
    dependencies: {postgres|redis|vector_store:
        {status: "ok"|"unreachable"|"unconfigured", detail?, latency_ms?}} }
```

### Generated types contract (TASK-2526 output — verify paths before import)
```typescript
import type { AdminStatus, DependencyHealth } from '$lib/types/generated/...';
// Files carry "GENERATED … DO NOT EDIT" banner — NEVER hand-edit them.
```

### Runtime contract from prior tasks (verify exports)
```typescript
import { createApiClient } from '$lib/api/http';   // TASK-2527 adapted copy
import { authStore } from '$lib/stores/auth.svelte';
// Vendored primitives from TASK-2525: card, badge, skeleton, button, separator.
```

### Does NOT Exist
- ~~hand-written TS interfaces for the status payload~~ — forbidden; use
  generated types only.
- ~~a websocket/streaming status feed~~ — polling only in this spec.
- ~~usage/token metrics in the payload~~ — explicitly out of scope
  (spec Non-Goals).

---

## Implementation Notes

### Key Constraints
- Interval lifecycle via `$effect` with teardown (svelte5); no leaks across
  route changes.
- Uptime formatting: humanize (e.g. "3d 4h 12m") — pure helper with a unit
  test.
- Tokens per conventions: scale tokens in pages, semantic in primitives;
  status colors from the token palette (destructive/muted), not raw hex.

### References in Codebase
- Corporate dashboard widget classes
  (`navigator-frontend-next/src/lib/dashboard/domain/widget.svelte.ts`) are
  a PATTERN reference only — do NOT copy the widget framework; simple
  components suffice here.

---

## Acceptance Criteria

- [ ] Dashboard renders all `AdminStatus` fields from a mocked OK response.
- [ ] Degraded dependency renders `unreachable` badge without breaking the
  page; `unconfigured` renders muted.
- [ ] Auto-refresh fires on interval and stops on unmount (test with fake
  timers); manual refresh works.
- [ ] Fetch error shows retry card; retry re-fetches.
- [ ] Home shows name/version + nav cards.
- [ ] Types imported ONLY from `types/generated/`; `pnpm test` + `pnpm
  build` green.

---

## Test Specification

```typescript
// ui/src/pages/Dashboard.test.ts
describe('Dashboard', () => {
  it('renders tiles from AdminStatus');
  it('renders degraded dependency badge');
  it('auto-refreshes on interval and cleans up');
  it('shows retry card on fetch error');
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2526 and TASK-2528 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/ui-server-backend.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
