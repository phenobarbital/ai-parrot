# TASK-2587: Agent form pages — six tabs, sticky footer, create/edit routes, unsaved-changes guard

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD
**Spec**: `sdd/specs/ui-agent-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2585, TASK-2586
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + Component Diagram, §2 Form ↔ API mapping, §3 Module 5,
§5 ACs 2–7, 11–13, §8 Q1–Q3 (all resolved). Assembles the headless state
(TASK-2586) and the primitives/widgets (TASK-2585) into the tabbed wizard
(brainstorm Option B).

---

## Scope

- `pages/agents/AgentFormPage.svelte`: route wrapper. Reads
  `router.params.name`; `mode = name ? "edit" : "create"`. On mount (edit)
  `getAgent(name)` → `state.load()`; loads `getCatalog()` and
  `listTools()` (tools only when the Capabilities tab first needs them is
  acceptable). Loading skeleton / retry card as in `AgentsList.svelte`.
- `pages/agents/AgentForm.svelte`: owns one `AgentFormState`; renders the
  vendored `Tabs` with six panels and `FormFooter`. **All panel state lives
  in the store** so hidden tabs are still validated.
- Tab panels under `pages/agents/form/`, fields per spec §2 diagram:
  - `TabsGeneral`: `chatbot_id` (read-only, edit only), `name` (read-only
    + hint in edit mode — §8 Q3), `description`, `avatar`, `enabled`
    (Switch), `timezone`, `language`, `disclaimer`.
  - `TabsBehavior`: `role`, `goal`, `backstory`, `rationale`,
    `capabilities` (Textarea), `pre_instructions` (StringListEditor),
    `system_prompt_template`, `human_prompt_template`, `prompt_config` (JsonEditor).
  - `TabsAI`: `llm` (Select from `catalog.llm_providers`, tolerate unknown
    current value), `model`, `temperature` (Slider), `max_tokens`, `top_p`,
    `top_k` → written into `model_config`; raw `model_config` JsonEditor
    for extra keys.
  - `TabsCapabilities`: `tools_enabled`, `auto_tool_detection`,
    `tool_threshold` (Slider), `tools` (checkbox list from
    `/api/v1/agent_tools` + StringListEditor fallback for unknown names),
    `operation_mode` (from catalog), `use_kb`, `kb` (JsonEditor, array
    mode), `custom_kbs` (StringListEditor with `catalog.knowledge_bases`
    class paths as suggestions).
  - `TabsDataMemory`: `use_vector`, `vector_store_config`,
    `reranker_config`, `parent_searcher_config` (JsonEditors),
    `context_search_limit`, `context_score_threshold`, `memory_type`
    (from catalog), `memory_config` (JsonEditor), `max_context_turns`,
    `use_conversation_history`.
  - `TabsAdvanced`: `bot_class` (Input, default `BasicBot`), `permissions`
    (JsonEditor, mode `any` — dict or list).
  - Each tab trigger shows a red badge with `tabErrors[tab]` when > 0.
- `FormFooter.svelte`: sticky bottom bar — Save (disabled while invalid or
  saving), Cancel (→ `/admin/agents`, guarded), dirty indicator, server
  error text (`ApiError.message`).
- Save: create → `createAgent(state.payload())` → navigate to
  `/admin/agents/${response.name}` and show a notice when `response.name`
  differs from the typed name; edit → `updateAgent(name, state.diff())` →
  reload `original` from response/`getAgent`. Server error keeps input.
- Unsaved-changes guard: set `router.beforeNavigate` while the form is
  mounted (confirm dialog when `dirty`, bypass for `config.loginPath`),
  clear on destroy; `beforeunload` listener while dirty.
- `App.svelte`: add routes `/admin/agents/new` and `/admin/agents/:name`
  (`requiresAuth: true`), **before** the existing `/admin/agents` entry
  order is irrelevant for static-vs-param since TASK-2585 prefers static.
- Vitest suites: create flow (slugified name navigation), edit flow (diff
  only, 400 message shown, input kept), tab badge, unsaved guard.

**NOT in scope**: list/detail buttons and delete dialog (TASK-2588); docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/pages/agents/AgentFormPage.svelte` (+ `.test.ts`) | CREATE | route wrapper, data loading |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte` (+ `.test.ts`) | CREATE | tabs + footer + save logic |
| `packages/ai-parrot-server/ui/src/pages/agents/form/Tabs{General,Behavior,AI,Capabilities,DataMemory,Advanced}.svelte` | CREATE | tab panels |
| `packages/ai-parrot-server/ui/src/pages/agents/form/FormFooter.svelte` | CREATE | sticky footer |
| `packages/ai-parrot-server/ui/src/App.svelte` | MODIFY | two new routes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (TS)
```ts
import { router } from "$lib/router.svelte";                   // router.params / router.beforeNavigate — from TASK-2585
import { config } from "$lib/config";                          // config.loginPath
import apiClient, { ApiError } from "$lib/api/http";
import { AgentFormState } from "$lib/stores/agent-form.svelte"; // TASK-2586
import { FIELD_TAB, type TabId } from "$lib/agents/fields";     // TASK-2586
import { getAgent, createAgent, updateAgent, listTools, getCatalog } from "$lib/api/agents";  // TASK-2586
import JsonEditor from "$lib/components/JsonEditor.svelte";     // TASK-2585
import StringListEditor from "$lib/components/StringListEditor.svelte";
import * as Tabs from "$lib/ui/internal/shadcn/ui/tabs/index.js";          // TASK-2585 (verify barrel export names)
import { Switch } from "$lib/ui/internal/shadcn/ui/switch/index.js";
import { Checkbox } from "$lib/ui/internal/shadcn/ui/checkbox/index.js";
import { Textarea } from "$lib/ui/internal/shadcn/ui/textarea/index.js";
import { Slider } from "$lib/ui/internal/shadcn/ui/slider/index.js";
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";      // existing
import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "$lib/ui/internal/shadcn/ui/dialog/index.js";
```

### Existing Signatures to Use
```ts
// ui/src/App.svelte — route table:
router.routes = [
  { path: "/admin/login", component: () => import("./pages/Login.svelte") },
  { path: "/admin/home", ..., requiresAuth: true }, { path: "/admin/dashboard", ... }, { path: "/admin/agents", component: () => import("./pages/Agents.svelte"), requiresAuth: true },
];  // add { path: "/admin/agents/new", component: () => import("./pages/agents/AgentFormPage.svelte"), requiresAuth: true }
    //     { path: "/admin/agents/:name", component: () => import("./pages/agents/AgentFormPage.svelte"), requiresAuth: true }
// resolve(): match → guard → lazy component; authenticated pages render inside <AppShell>.
// Fetch hygiene: no $state reads before the first await inside fetch fns (AgentsList.svelte comment) to avoid $effect self-retrigger.
// Existing Select vendored primitive uses bits-ui floating UI — awkward in jsdom (FEAT-468 lesson); a native <select> wrapper is acceptable for llm/operation_mode/memory_type.
```

### Does NOT Exist
- ~~SvelteKit `beforeNavigate`/`goto`/`$page.params`~~ — use `router.beforeNavigate`, `router.navigate`, `router.params`.
- ~~server-side re-slugify on POST~~ — only PUT slugifies; edit never sends `name` (§8 Q3).
- ~~a toast/notification system in the shell~~ — none exists; render notices inline (footer or top-of-form alert).
- ~~`AgentDetail`/`AgentsList` mutating buttons~~ — TASK-2588.

---

## Implementation Notes

- Keep `AgentForm.svelte` thin: rendering + wiring; all logic in
  `AgentFormState`.
- For `TabsAI`, derive convenience fields from `values.model_config`
  (`model ?? model_name`, `temperature`, `max_tokens`, `top_p`, `top_k`)
  and write back into the same dict so the raw JsonEditor stays in sync.
- Tools checkbox list: tools currently in `values.tools` but absent from
  `/api/v1/agent_tools` must remain (rendered as "unknown" chips), never
  silently dropped.
- Tests: mock `$lib/api/agents` with `vi.mock` or `vi.spyOn(apiClient, …)`;
  set `router.params` / `router.path` directly in tests.

---

## Acceptance Criteria

- [ ] Six tabs, every user-editable `BotModel` field reachable in exactly one tab; `chatbot_id` read-only (edit); `name` read-only (edit)
- [ ] Sticky Save/Cancel across tabs; per-tab red error badge; Save blocked while invalid
- [ ] Create → `PUT` with `storage:"database"` → navigates to returned `name`; notice when it differs
- [ ] Edit → loads by name, `POST` diff only, immutables never sent; 400 `{"message"}` shown, input kept
- [ ] All seven JSONB fields via `JsonEditor`; malformed JSON blocks Save
- [ ] Options for `llm`/`operation_mode`/`memory_type`/KB classes come from the catalog; tools from `/api/v1/agent_tools`
- [ ] Unsaved-changes guard on in-app navigation and `beforeunload`; login redirect not blocked
- [ ] `pnpm test` and `pnpm build` green

---

## Test Specification

```ts
// AgentForm.test.ts
it("create: PUT payload has storage=database and navigates to returned slug", ...)
it("edit: sends only the diff, never chatbot_id/created_*/name", ...)
it("shows server 400 message and keeps input", ...)
it("empty goal marks Behavior tab badge and disables Save", ...)
it("dirty form asks before navigating away; login redirect bypasses", ...)
// AgentFormPage.test.ts — loading skeleton, retry on error, mode by params
```

---

## Agent Instructions

1. Read spec §2 (Overview, diagram, mapping, validation), §3 Module 5, §5, §6, §7, §8.
2. Confirm TASK-2585 and TASK-2586 are in `sdd/tasks/completed/` and their exports match the contract above.
3. Implement + tests; move to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
