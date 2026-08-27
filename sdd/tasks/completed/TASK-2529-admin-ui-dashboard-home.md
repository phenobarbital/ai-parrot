# TASK-2529: Admin UI pages — Home and Status Dashboard

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: done
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

**Completed by**: sdd-worker (resumed)
**Date**: 2026-08-27
**Notes**:
- `pages/Home.svelte` — one-shot `GET /api/v1/admin/status` fetch (via
  `apiClient`, not polled — Dashboard owns the auto-refreshing view) for
  `name`/`version`, welcome `Card`, and a nav-card grid driven by
  `navEntries` from `lib/nav.ts` (filters out the Home entry itself so the
  cards list is future-proof against new nav entries).
- `pages/Dashboard.svelte` — `<script module>`-exported pure
  `formatUptime(seconds)` helper (`Xd Yh Zm` / `Xh Ym` / `Xm Ys` / `Xs`,
  clamped to `"0s"` for negative/NaN input), imported directly by
  `Dashboard.test.ts` for a dedicated unit test (mirrors the
  `badgeVariants` export pattern in `badge.svelte`). `fetchStatus()`
  fetches the GENERATED `AdminStatus` type from `GET
  /api/v1/admin/status`; 6-tile grid (version, uptime, crews, agents ×
  database/registry/loaded) via the new `StatusTile`, dependency list via
  the new `HealthBadge`, manual refresh button, last-updated timestamp,
  retry card on a first-load failure (`error && status === null`).
  Auto-refresh: a single `$effect` calls `fetchStatus()` and sets a 15s
  `setInterval`, returning `clearInterval` as its teardown — verified with
  `vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync()` in
  `Dashboard.test.ts`.
- **Reactive-loop guard (important, not obvious from the diff alone)**:
  `fetchStatus()` deliberately performs no `$state` READS before its first
  `await` — only writes (`loading = true` unconditionally, no `status ===
  null` branch at entry). `$effect` in Svelte 5 captures state reads that
  happen synchronously during its call stack, including reads inside
  functions it calls directly (like `fetchStatus()`, invoked synchronously
  from the effect body up to its first `await`). Had `fetchStatus` read
  `status`/`loading`/`error` synchronously at entry, the effect would have
  taken a dependency on that state; since `fetchStatus` later WRITES that
  same state (after the awaited `apiClient.get()` resolves), the effect
  would re-run on every fetch completion — tearing down and rebuilding the
  `setInterval` and firing an immediate extra `fetchStatus()` each time,
  turning the 15s poll into a request-storm. This was caught during
  implementation, not by a failing test (the interval test as written
  wouldn't have distinguished "polls every 15s" from "polls every
  network-round-trip"); documenting it here since it's a Svelte 5
  `$effect`-inside-async-function gotcha worth being aware of in any
  future component with a similar polling `$effect`.
- New components: `lib/components/StatusTile.svelte` (label/value/loading
  tile, `data-testid="status-tile-<slug>"`) and
  `lib/components/HealthBadge.svelte` (status pill using the vendored
  `Badge` primitive — `ok` → `outline` variant + `text-success` class
  (global `--color-success` token from `_tokens.css`, not theme-scoped),
  `unreachable` → the primitive's own `destructive` variant, `unconfigured`
  → `outline` + `text-muted-foreground`/`bg-muted`; `title` attribute
  combines `detail`/`latency_ms` when present).
- Test files: `Dashboard.test.ts` (`formatUptime` unit tests + 4 component
  tests: renders tiles from a mocked `AdminStatus`, renders a mixed
  ok/unreachable/unconfigured dependency list, auto-refresh + unmount
  cleanup under fake timers, retry-card-then-recovers on fetch error),
  `Home.test.ts` (identity banner from a mocked status response, nav
  cards render for every non-Home `navEntries` entry, generic fallback
  copy when the status fetch fails), `HealthBadge.test.ts`,
  `StatusTile.test.ts` (loading-skeleton vs. value rendering).
- `pnpm test` — 44/44 passed (10 files, up from 26/6 after TASK-2528).
  `pnpm build` green (`pnpm generate && vite build`, 757 modules,
  `Dashboard`/`Home` chunks still code-split per-route).

**Deviations from spec**: none — `config.ts` was intentionally left
untouched (not in this task's Files table); the status endpoint path
`/api/v1/admin/status` is inlined as a local constant in `Dashboard.svelte`
and `Home.svelte` instead, verified directly against
`packages/ai-parrot-server/src/parrot/server/ui/serving.py`'s
`add_view("/api/v1/admin/status", AdminStatusHandler)` registration.
