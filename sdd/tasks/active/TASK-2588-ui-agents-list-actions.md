# TASK-2588: Agents list/detail actions — Create, Edit, Delete dialog, "Show disabled" toggle

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD
**Spec**: `sdd/specs/ui-agent-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2583, TASK-2585, TASK-2586
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (list/detail affordances), §3 Module 6, §5 ACs 1, 5, 10.
FEAT-468's `AgentsList.svelte` / `AgentDetail.svelte` are read-only by
design; this task adds the entry points into the form (TASK-2587) and the
delete flow, strictly for `source === "database"` rows.

---

## Scope

- `AgentsList.svelte`:
  - **Create Agent** button → `router.navigate("/admin/agents/new")`.
  - Row actions column: **Edit** (→ `/admin/agents/${agent.name}`) and
    **Delete** (opens dialog) — rendered only when `agent.source === "database"`;
    registry rows show nothing (keep `data-testid` hooks for tests). Row
    click still opens the detail dialog; action buttons must
    `stopPropagation`.
  - "Show disabled" Switch/checkbox (default off) → refetch with
    `listAgents({ includeDisabled: true })`; disabled rows get a muted
    style / `Badge` "disabled".
  - Use `listAgents()` from `$lib/api/agents` instead of the raw
    `apiClient.get` (keep behaviour identical; existing tests may need the
    mock target updated).
- `AgentDetail.svelte`: **Edit** button in the header for database agents
  (closes dialog, navigates).
- `pages/agents/DeleteAgentDialog.svelte`: props `agent`, bindable `open`,
  `ondeleted`; typed-name confirmation (`Input` must equal `agent.name`
  to enable the destructive `Button`); calls `deleteAgent(name)`; success
  → `ondeleted()` (list refetch); `ApiError.message` shown inline (403
  for repo registry agents verbatim), dialog stays open on error.
- Tests updated/added.

**NOT in scope**: the form pages (TASK-2587); bulk actions; sorting/pagination.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/pages/agents/AgentsList.svelte` (+ `.test.ts`) | MODIFY | create/edit/delete affordances, show-disabled |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.svelte` (+ `.test.ts`) | MODIFY | Edit button (database only) |
| `packages/ai-parrot-server/ui/src/pages/agents/DeleteAgentDialog.svelte` (+ `.test.ts`) | CREATE | typed-name confirm + DELETE |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (TS)
```ts
import { router } from "$lib/router.svelte";
import { listAgents, deleteAgent } from "$lib/api/agents";              // TASK-2586
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";  // { name: string; source: "database"|"registry"; [k: string]: unknown }
import { ApiError } from "$lib/api/http";
import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";    // TASK-2585
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "$lib/ui/internal/shadcn/ui/dialog/index.js";
```

### Existing Signatures to Use
```ts
// ui/src/pages/agents/AgentsList.svelte (FEAT-468 TASK-2530)
//   state: agents, loading, error, search, sourceFilter ("all"|"database"|"registry"), detailOpen, selectedAgent
//   fetchAgents(): apiClient.get<BotsListResponse>("/api/v1/bots")  ← switch to listAgents({includeDisabled})
//   table rows: data-testid={`agent-row-${agent.name}`}, onclick={() => openDetail(agent)}
//   <AgentDetail agent={selectedAgent} bind:open={detailOpen} />
// ui/src/pages/agents/AgentDetail.svelte — props { agent: BotAgentItem | null; open = $bindable(false) }; Dialog-based
// ui/src/pages/agents/AgentsList.test.ts — mocks via vi.spyOn(apiClient, "get").mockResolvedValue({ data: { agents, total } })
//   (if you route through listAgents(), keep spying on apiClient.get — listAgents wraps it — or vi.mock("$lib/api/agents"))
```
```python
# DELETE /api/v1/bots/{name}  (handlers/bots.py:1247-1326)
#   repo registry agent → 403 {"message": "Agent '<n>' is a repo YAML/code agent and cannot be deleted via this endpoint."}
#   factory registry agent → 200 {"message","name","source":"factory"}; DB → 200 {"message","name"}; missing → 404
# GET /api/v1/bots?include_disabled=true (TASK-2583)
```

### Does NOT Exist
- ~~bulk delete / multi-select~~, ~~pagination~~ — not in this feature.
- ~~a toast system~~ — inline messages only.
- ~~`AgentsList` props~~ — it is a page component without props; keep it that way.
- ~~delete for registry rows~~ — never rendered; the 403 path is only reachable if a DB row turns out to be registry-backed server-side, still surface it.

---

## Implementation Notes

- Preserve every existing `AgentsList.test.ts` / `AgentDetail.test.ts`
  assertion that is not about affordances; extend rather than rewrite.
- Row-action buttons inside a clickable `<tr>`: use `onclick={(e) => { e.stopPropagation(); … }}`.
- Destructive button style: existing `Button` `variant="destructive"` if
  the vendored button defines it (verify in `button.svelte`); otherwise add
  the variant there.

---

## Acceptance Criteria

- [ ] Create button visible; Edit/Delete only on `source === "database"` rows; registry rows have no mutating affordance
- [ ] Detail dialog shows Edit for database agents only
- [ ] Delete requires typing the exact name; success refetches the list; 403/other errors shown verbatim, dialog stays open
- [ ] "Show disabled" off by default (byte-identical request to today); on → `?include_disabled=true`, disabled rows badged
- [ ] `pnpm test` green including all pre-existing FEAT-468 tests (modified only where affordances were added)

---

## Test Specification

```ts
// AgentsList.test.ts (add)
it("renders Create button and navigates to /admin/agents/new", ...)
it("shows Edit/Delete only on database rows", ...)
it("Show disabled toggles include_disabled param", ...)
// AgentDetail.test.ts (add) — Edit button visibility per source
// DeleteAgentDialog.test.ts — typed-name gating, DELETE call, 403 message, ondeleted callback
```

---

## Agent Instructions

1. Read spec §2 Overview, §3 Module 6, §5, §6.
2. Confirm TASK-2583/2585/2586 are completed and their exports match.
3. Implement + tests; move to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
