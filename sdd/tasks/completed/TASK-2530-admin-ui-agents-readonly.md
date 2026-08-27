# TASK-2530: Admin UI — read-only Agents module

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Spec**: `sdd/specs/ui-server-backend.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2526, TASK-2528
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. The first feature module on the shell, validating the
module pattern for the whole series: a read-only agents table over the
existing `GET /api/v1/bots`, absorbing the list-view design from
`sdd/proposals/ui-agent-management.brainstorm.md`. Create/edit is the NEXT
spec — nothing here mutates.

---

## Scope

- `pages/agents/AgentsList.svelte` (replaces the Agents placeholder):
  - Fetches `GET /api/v1/bots` (generated `BotsListResponse` type).
  - Table columns: name, description, role, source (badge:
    database/registry), enabled — per the absorbed ui-agent-management
    design. Registry agents without `bot_config` may lack most fields:
    render `—` fallbacks (see contract for their minimal shape).
  - Client-side search (name/description) + source filter
    (all/database/registry).
  - Row click opens a read-only detail panel (dialog or side sheet from
    vendored primitives) showing the full agent payload as labeled fields
    plus a raw JSON view.
  - Loading skeleton, empty state, fetch-error retry card.
- NO create/edit/delete affordances anywhere (no buttons, no routes).
- Vitest suite with mocked responses covering both agent shapes.

**NOT in scope**: agent CRUD (next spec), `/api/v1/astudio/*` (future
migration), pagination (dataset is small; note if it becomes needed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/pages/agents/AgentsList.svelte` | CREATE | list page (router points here) |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.svelte` | CREATE | read-only detail panel |
| `packages/ai-parrot-server/ui/src/pages/Agents.svelte` | MODIFY/DELETE | replace placeholder wiring |
| corresponding `*.test.ts` | CREATE | vitest |

---

## Codebase Contract (Anti-Hallucination)

### Backend API contract (verified)
```text
GET /api/v1/bots — ChatbotHandler (handlers/bots.py:424; registered
manager.py:1952). Response (bots.py:751-754):
  {"agents": [...], "total": N}
Agent dict variants:
  - database agents (bots.py:610-622): full BotModel dump + source='database'
  - registry agents (bots.py:623-637): source='registry'; when bot_config is
    None the dict is ONLY {name, module_path, file_path, singleton,
    at_startup, priority, tags} (:629-636) — no description/role/enabled.
PBAC: server-side batch filter 'agent:list' (bots.py:725-748, fail-open) —
the UI renders whatever comes back; NO client-side authz.
```

### Generated types contract (TASK-2526 — verify before import)
```typescript
import type { BotsListResponse } from '$lib/types/generated/...';
// Agent item type is permissive (optional fields) by design — handle both shapes.
```

### Runtime contract from prior tasks (verify exports)
```typescript
import { createApiClient } from '$lib/api/http';
// Vendored primitives: card, badge, input, select, dialog/sheet, skeleton,
// separator (TASK-2525). SimpleTable wrapper from corporate may be copied
// (navigator-frontend-next/src/lib/ui/components/SimpleTable.svelte) or a
// plain <table> with token classes — implementer's choice; record it.
```

### Does NOT Exist
- ~~`GET /api/v1/astudio/agents`~~ — planned elsewhere, not implemented;
  consume `/api/v1/bots` only.
- ~~`BotHandler.get()`~~ — `/api/v1/chatbots` is PUT-only create; do not
  fetch it.
- ~~guaranteed fields on registry agents~~ — see minimal shape above.
- ~~mutating endpoints in this module~~ — PUT/POST/DELETE of
  `/api/v1/bots` exist server-side but are OUT of this module's scope.

---

## Implementation Notes

### Key Constraints
- Follow the module pattern this task establishes: page component under
  `pages/<module>/`, nav entry already present from TASK-2528's registry,
  data via generated types + shared API client — future module specs copy
  this shape.
- Search/filter as `$derived` over the fetched list (no server round-trips).
- Detail panel must not crash on the minimal registry shape (test).

### References in Codebase
- `sdd/proposals/ui-agent-management.brainstorm.md:104-107` — list-view
  design absorbed here (name/description/role/status columns, row → detail).

---

## Acceptance Criteria

- [ ] Table renders both database and minimal-registry agent shapes from a
  mocked mixed response; missing fields show `—`.
- [ ] Search and source filter narrow the list client-side.
- [ ] Row click opens read-only detail (fields + raw JSON); closes cleanly.
- [ ] Zero mutating affordances (assert no create/edit/delete controls).
- [ ] Loading, empty and error/retry states covered by tests.
- [ ] Types only from `types/generated/`; `pnpm test` + `pnpm build` green.

---

## Test Specification

```typescript
// ui/src/pages/agents/AgentsList.test.ts
describe('AgentsList', () => {
  it('renders database and registry agent rows');
  it('renders — for missing fields on minimal registry agents');
  it('filters by search text and source');
  it('opens read-only detail on row click');
  it('has no mutating controls');
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
- `pages/agents/AgentsList.svelte` — fetches `GET /api/v1/bots` (generated
  `BotsListResponse`/`BotAgentItem` types, both permissive per contract:
  only `name`/`source` pinned). Plain `<table>` with token classes (no
  SimpleTable wrapper exists in this scaffold — explicitly implementer's
  choice per the Codebase Contract). Client-side `$derived.by` filter over
  `search` (name/description substring, case-insensitive) and
  `sourceFilter` (all/database/registry). `fieldOf()` reads arbitrary keys
  off the permissive `BotAgentItem` via a `Record<string, unknown>` cast
  and falls back to `"—"` for `undefined`/`null`/`""`, covering the
  registry-minimal shape (`{name, module_path, file_path, singleton,
  at_startup, priority, tags}` — no `description`/`role`/`enabled`).
  Loading skeleton, empty state (`agents-empty-state`), fetch-error retry
  card (`agents-retry-card`, same `error && agents === null` pattern as
  Dashboard's `fetchStatus`) — `fetchAgents()` likewise performs no
  `$state` reads before its first `await`, for the same reactive-loop
  reason documented in `Dashboard.svelte` (this page doesn't poll, but the
  one-shot `$effect` calling an async function synchronously is the same
  shape, so the same hygiene applies).
- `pages/agents/AgentDetail.svelte` — read-only panel on the vendored
  bits-ui-backed Dialog primitive (`Dialog`/`DialogContent`/
  `DialogHeader`/`DialogTitle`/`DialogDescription` from
  `lib/ui/internal/shadcn/ui/dialog`), controlled via `bind:open` from the
  list page rather than `DialogTrigger` (list rows aren't dialog
  triggers). Renders every field except `name`/`source` as a labeled
  row (`Object.entries` over the agent, since the type is permissive) plus
  a `<pre data-testid="agent-detail-raw-json">` raw JSON view. Handles the
  minimal registry shape without crashing (`entries.length === 0` renders
  "No additional fields." instead of an empty list) and a `null` agent
  (renders nothing inside `DialogContent`, guarded by `{#if agent}`).
- `pages/Agents.svelte` — MODIFY (not DELETE): kept as a one-line wrapper
  re-exporting `AgentsList`, so `App.svelte`'s route table (which still
  points at `./pages/Agents.svelte`) needs no change — `App.svelte` is not
  in this task's Files table, so this was the narrower option vs.
  repointing the route to `pages/agents/AgentsList.svelte` directly.
- Source filter is a 3-way `Button` toggle group (All/Database/Registry),
  not the vendored bits-ui `Select` — see Deviations. Verified the Dialog
  primitive itself (used for the detail panel) DOES work under
  `jsdom`/`@testing-library/svelte` with no additional polyfills needed in
  `vitest-setup.ts` (untouched) — `bind:open` + `{#if agent}`-guarded
  content was sufficient for all 3 `AgentDetail.test.ts` cases and the
  `AgentsList.test.ts` "opens read-only detail on row click" case.
- Zero mutating affordances: no create/edit/delete buttons/routes anywhere
  in either file; `AgentsList.test.ts`'s "has no mutating controls" test
  asserts their absence by role/name.
- Test files: `AgentsList.test.ts` (8 tests — mixed database/registry
  rows, `—` fallbacks on the minimal shape, search filter, source filter,
  detail-open-on-row-click, no mutating controls, retry-then-recovers,
  empty state) and `AgentDetail.test.ts` (3 tests — full-agent fields +
  raw JSON, minimal-registry-shape no-crash, `agent === null` renders
  nothing).
- `pnpm test` — 55/55 passed (12 files, up from 44/10 after TASK-2529).
  `pnpm build` green (`pnpm generate && vite build`, 772 modules; `Agents`
  chunk — now pulling in the Dialog/bits-ui machinery — grew to ~55KB but
  remains its own code-split chunk, not inlined into the shared bundle).

**Deviations from spec**:
- Source filter uses a 3-way `Button` toggle group instead of the
  vendored `Select` primitive. The Codebase Contract lists `select` among
  available vendored primitives but does not mandate it for this specific
  filter, and the acceptance criterion only requires that "search and
  source filter narrow the list client-side" — functionally satisfied
  either way. Chosen to avoid `Select`'s floating-ui popover-positioning
  machinery being exercised for the first time in this repo's test suite
  for only 3 fixed, always-visible options; a `Button` group is
  functionally equivalent here and trivially testable. Recorded per the
  Implementation Notes' explicit invitation to record implementer choices
  like this (mirroring the SimpleTable-vs-plain-`<table>` choice already
  called out there).
- `pages/Agents.svelte` was kept (MODIFY) rather than deleted, as a thin
  wrapper around `AgentsList`, specifically to avoid touching
  `App.svelte`'s route table (not listed in this task's Files to
  Create/Modify).
