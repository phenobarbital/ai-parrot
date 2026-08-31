# TASK-2597: Chat page, route, and Agents list/detail integration

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2594 *(TASK-2595/2596 may be absent — flags/mocks cover them)*
**Assigned-to**: sdd-worker

---

## Context

Spec §2 "Entry points", §3 Module 7. Wires the vendored `AgentChat`
into the Admin UI: a full page at `/admin/agents/:name/chat`, a Chat
action on each enabled agent row, and a Chat tab in the FEAT-475 agent
detail page mounting the compact variant.

---

## Scope

- `ui/src/pages/agents/AgentChatPage.svelte`: reads `router.params.name`;
  for database agents fetches `GET /api/v1/bots/<name>` to obtain
  `chatbot_id` (prompt library); registry agents → no `chatbotId` →
  library hidden; unknown name → not-found state with link back to
  `/admin/agents`; topbar/heading shows the agent name; mounts
  `<AgentChat agentId={name} chatbotId variant="default" />`.
- `ui/src/App.svelte`: add `{ path: "/admin/agents/:name/chat",
  component: () => import("./pages/agents/AgentChatPage.svelte"),
  requiresAuth: true }` — order it so the static FEAT-475 routes
  (`/admin/agents/new`) still win.
- `ui/src/pages/agents/AgentsList.svelte`: Chat button per row →
  `router.navigate("/admin/agents/<name>/chat")`; hidden when
  `(agent as Record<string, unknown>).enabled === false`
  (`undefined ⇒ enabled`).
- `ui/src/pages/agents/AgentDetail.svelte` (page after FEAT-475): Chat
  tab mounting `<AgentChat agentId={name} chatbotId variant="compact"
  enableCanvas={false} />`.
- Tests: `AgentChatPage.test.ts`; extend `AgentsList.test.ts`,
  `AgentDetail.test.ts`.

**NOT in scope**: sidebar entries (`nav.ts` unchanged); backend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `ui/src/pages/agents/AgentChatPage.svelte` | CREATE | full-page host |
| `ui/src/App.svelte` | MODIFY | route entry |
| `ui/src/pages/agents/AgentsList.svelte` | MODIFY | Chat action |
| `ui/src/pages/agents/AgentDetail.svelte` | MODIFY | Chat tab |
| `ui/src/pages/agents/AgentChatPage.test.ts`, `AgentsList.test.ts`, `AgentDetail.test.ts` | CREATE/MODIFY | vitest |
| `ui/src/pages/agents/__mocks__/AgentChatStub.svelte` | CREATE (test-only) | shared fixture the three test files above mock `$lib/components/agents/AgentChat.svelte` with, per this task's own Test Specification sketch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```ts
import { router, type RouteDefinition } from "$lib/router.svelte";   // ui/src/lib/router.svelte.ts:107-109; FEAT-475 adds `params` + ":param" matching
import apiClient, { ApiError } from "$lib/api/http";                  // ui/src/lib/api/http.ts:31,197 (AgentsList.svelte:24 uses exactly this)
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem"; // AgentsList.svelte:25 — fields pinned: name, source; extras allowed
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";  // AgentsList.svelte:28
import AgentChat from "$lib/components/agents/AgentChat.svelte";      // TASK-2594
```

### Existing Signatures to Use
```ts
// ui/src/App.svelte:17-31 — router.routes = [ {path:"/admin/login", component}, {path:"/admin/home", …, requiresAuth:true}, {path:"/admin/dashboard"…}, {path:"/admin/agents"…} ]
//   (FEAT-475 adds /admin/agents/new and /admin/agents/:name — spec ui-agent-management §2 line 214)
// ui/src/lib/router.svelte.ts — match(path) (83, exact on dev; param-aware after FEAT-475), guard(path) (93), navigate(to,{replace}) (59)
// ui/src/pages/agents/AgentsList.svelte — agents = $state<BotAgentItem[]|null> (36); sourceFilter (41); fieldOf(agent, key) (68); openDetail(agent) (86);
//   {#each filtered as agent (agent.name + agent.source)} (149); row onclick={() => openDetail(agent)} (152); Badge source (161)
// ui/src/pages/agents/AgentDetail.svelte (dev) — Dialog-based, props { agent: BotAgentItem|null, open } (30); FEAT-475 replaces with a page at /admin/agents/:name
// Backend GET /api/v1/bots/{name} — ChatbotHandler (bots.py:424; _get_db_agent(name) :475 — no enabled filter); DB rows serialized with full BotModel incl. chatbot_id, enabled
//   (server/ui/models.py:23-33 docstring); registry rows: name, module_path, file_path, singleton, at_startup, priority, tags — no chatbot_id/enabled
// PBAC: AgentTalk checks "agent:chat" (agent.py:1446-1452) → 403 surfaces as error bubble (TASK-2594)
```

### Does NOT Exist
- ~~`BotAgentItem.enabled` / `.chatbot_id` as typed fields~~ — read via `(agent as Record<string, unknown>)`.
- ~~`router.params` on `dev` before FEAT-475~~ — this task requires the merge; abort if `grep -n "params" ui/src/lib/router.svelte.ts` is empty.
- ~~`GET /api/v1/agents/chat` list~~ — use `/api/v1/bots`.
- ~~a sidebar "Chat" entry~~ — not added.
- ~~`AgentDetail.svelte` as a page at `/admin/agents/:name`~~ — CORRECTED:
  verified `/admin/agents/:name` is `AgentFormPage.svelte` (edit-only,
  TASK-2587); `AgentDetail.svelte` is still the read-only Dialog
  `AgentsList.svelte` opens on row click, unchanged by FEAT-475 in this
  respect. The Chat tab was added to that existing Dialog via `AppTabs`
  instead — see Completion Note.

---

## Implementation Notes

### Pattern to Follow
```svelte
<!-- AgentsList.svelte row action (sketch) -->
{#if (agent as Record<string, unknown>).enabled !== false}
  <Button size="sm" variant="outline" onclick={(e) => { e.stopPropagation(); router.navigate(`/admin/agents/${encodeURIComponent(agent.name)}/chat`); }}>Chat</Button>
{/if}
```

### Key Constraints
- Static routes before param routes in `router.routes`.
- `encodeURIComponent` the name in URLs; decode from `router.params`.
- Unauthenticated access is handled by `Router.guard` (`requiresAuth: true`) — do not add a second guard.

---

## Acceptance Criteria

- [x] `AgentChatPage.test.ts`: reads `router.params.name`; DB agent → `chatbot_id` fetched and passed; registry agent → no `chatbotId`; unknown (404) → not-found state
- [x] `AgentsList.test.ts`: Chat button for enabled rows (both sources) of, absent for `enabled=false`; navigates to `/admin/agents/<name>/chat`
- [x] `AgentDetail.test.ts`: Chat tab mounts a compact panel with the row's own `chatbot_id` (no extra fetch — see Completion Note) — CORRECTED to a tab inside the existing detail Dialog, not a page (see Completion Note for why)
- [x] `router.test.ts` (FEAT-468/475) unchanged and green (14/14); `/admin/agents/new` still matches its static route (distinct segment count from the new `/admin/agents/:name/chat`, verified no collision)
- [x] `pnpm test` (37 files / 225 tests) / `pnpm build` green — this is the first task where `AgentChat.svelte` is genuinely reachable from an entry point; the real `pnpm build` now exercises the whole vendored dependency closure end-to-end (all TASK-2594/2595/2596 chunks: AvatarViewer, VoiceNativeAvatarViewer, CanvasPanel, DataChart/DataMap/StructuredMap, AppChart/AppChartGeo, ECharts, InfographicEditor, livekit-client, exceljs, revo-grid) with zero missing-module errors

---

## Test Specification

```ts
// ui/src/pages/agents/AgentChatPage.test.ts (sketch)
import { vi, it, expect } from "vitest";
vi.mock("$lib/router.svelte", () => ({ router: { params: { name: "helpdesk" }, navigate: vi.fn(), path: "/admin/agents/helpdesk/chat" } }));
vi.mock("$lib/api/http", () => ({ default: { get: vi.fn().mockResolvedValue({ data: { name: "helpdesk", source: "database", chatbot_id: "uuid-1", enabled: true } }) }, ApiError: class extends Error {} }));
vi.mock("$lib/components/agents/AgentChat.svelte", async () => ({ default: (await import("./__mocks__/AgentChatStub.svelte")).default }));
import { render, screen, waitFor } from "@testing-library/svelte";
import AgentChatPage from "./AgentChatPage.svelte";
it("passes chatbotId for database agents", async () => {
  render(AgentChatPage);
  await waitFor(() => expect(screen.getByTestId("agentchat-stub")).toHaveAttribute("data-chatbot-id", "uuid-1"));
});
```

---

## Agent Instructions

1. Read spec §2 Overview, §3 Module 7. 2. Confirm TASK-2594 completed and FEAT-475 merged (`router.params` exists). 3. Verify contract. 4. Index → `in-progress`. 5. Implement. 6. Verify. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-31
**Notes**:
Added `/admin/agents/:name/chat` (distinct segment count from
`/admin/agents/:name`, so no route-matching ambiguity), `AgentChatPage.svelte`
(full-page host, reusing `getAgent()` already used by `AgentFormPage.svelte`),
a "Chat" action on every enabled `AgentsList` row (both database and
registry — registry agents just render with no `chatbotId`, hiding the
prompt library per `AgentChat`'s own existing optional-prop handling), and
a "Chat" tab in the existing `AgentDetail` dialog. This is the first task
in the feature where `AgentChat.svelte` is reachable from a real route —
`pnpm build` now exercises the entire vendored dependency closure
end-to-end (37 files / 225 tests green; full production build produces
the expected separate chunks: `AgentChat`, `AvatarViewer`,
`VoiceNativeAvatarViewer`, `CanvasPanel`, `DataChart`/`DataMap`/
`StructuredMap`, `AppChart`/`AppChartGeo`, `ECharts`, `InfographicEditor`,
`livekit-client`, `exceljs`, `revo-grid` — no missing-module errors).

**Deviations from spec**:
1. **Codebase Contract correction**: the contract assumed "FEAT-475
   replaces [AgentDetail] with a page at `/admin/agents/:name`" — verified
   false. `/admin/agents/:name` is `AgentFormPage.svelte` (edit form,
   TASK-2587); `AgentDetail.svelte` is still the read-only Dialog
   `AgentsList.svelte` opens on row click. Added the Chat tab to that
   existing Dialog (via `AppTabs`, already vendored in TASK-2593) instead
   of inventing a page/route that doesn't exist and wasn't otherwise
   needed — satisfies the actual intent ("mount the compact chat panel
   from the agent's detail surface") without redesigning FEAT-475's
   already-shipped UI.
2. **Real bug found and fixed**: bits-ui's `Tabs.Content` (used by the
   vendored `AppTabs`) renders every tab's content eagerly — CSS-hidden
   when inactive, not unmounted — so a naive `{:else if tab === "chat"}`
   branch mounted `AgentChat` (WebSocket connect, prompt-library fetch,
   …) immediately on dialog open regardless of which tab was selected,
   breaking `AgentDetail.test.ts`/`AgentsList.test.ts` (neither mocks
   AgentChat's dependencies) the moment any row's detail dialog opened.
   Fixed with an explicit `{#if activeTab === "chat"}` guard inside that
   branch so `AgentChat` only mounts once the user actually selects the
   tab.
3. Chat button in `AgentsList` is shown for **both** `database` and
   `registry` sources (unlike Edit/Delete, which stay database-only) —
   the spec's Scope explicitly scopes visibility to `enabled !== false`
   only, not to source; registry agents are chattable, just without a
   prompt library.
4. Added `src/pages/agents/__mocks__/AgentChatStub.svelte`, a small
   shared fixture the three test files mock `AgentChat.svelte` with —
   exactly the pattern this task's own Test Specification sketch already
   assumed (`./__mocks__/AgentChatStub.svelte`), just not yet created.
