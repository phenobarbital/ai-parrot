# TASK-3665: Admin UI: Tools tab (TabsTools, ToolkitDrawer, AgentMcpPanel) replacing the checkbox list

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3664
**Assigned-to**: unassigned

---

## Context

Spec §2 User-Facing Behavior (operator), §3 Module 12; AC14. Plain tools stay one click (`tools`
field of the form, saved by the existing form save); toolkits open a drawer that saves through the
Studio endpoints (single writer) and shows "Reload required" + **Reload agent**. Registry agents
that are not editable show the tab read-only with the `reason` from the GET-list response.

---

## Scope

- `fields.ts`: add `"tools"` to `TabId`; `FIELD_TAB.tools = "tools"` (was capabilities, :126).
- `AgentForm.svelte`: `{ id: "tools", label: "Tools" }` after capabilities (:94); `<TabsContent value="tools"><TabsTools …/></TabsContent>`;
  pass `state`, `tools` (listTools result) and the agent `name` (undefined for /new → drawer disabled with hint "save the agent first").
- `TabsCapabilities.svelte`: remove the tools checkbox list + unknown-tools editor (keep tools_enabled,
  auto_tool_detection, tool_threshold, operation_mode, use_kb, kb, custom_kbs).
- `TabsTools.svelte`: list from `tools` (+ `/astudio/catalog/tools` if needed); switch per plain tool
  toggles `state.values.tools`; unknown selected names still surfaced (never dropped — port the old logic);
  toolkits (detected by a successful `getToolkitSchema(slug)`, cached) show "Configure" → ToolkitDrawer;
  configured toolkits (from GET list) show a badge; `unavailable` slugs shown greyed. Sections:
  **Toolkits**, **Datasets** (opens the drawer for `dataset_manager`), **MCP servers** (AgentMcpPanel).
- `ToolkitDrawer.svelte`: AppSheet; loads schema + current masked spec; SchemaForm with
  `showOverridable`, `optionsLoader` only when the spec is persisted; Save → `putAgentToolkit` →
  banner "Reload required" + Reload button (`reloadAgent`, shows `warnings`); Delete; optional Test
  (existing `POST /astudio/agents/{name}/toolkits`). Errors via `ApiError` message.
- `AgentMcpPanel.svelte`: list/add/edit/remove servers (name, transport, url/command, args,
  allowed/blocked tools, description, auth_type, headers/auth_config/env as masked JSON editors) →
  `putAgentMcpServers`.
- vitest + pytest wrapper.

**NOT in scope**: chat modal (TASK-3666).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.svelte` | CREATE | Catalog switches + toolkit drawer launcher + Datasets/MCP panels |
| `packages/ai-parrot-server/ui/src/pages/agents/form/ToolkitDrawer.svelte` | CREATE | AppSheet with SchemaForm, Save, Test, Reload |
| `packages/ai-parrot-server/ui/src/pages/agents/form/AgentMcpPanel.svelte` | CREATE | Agent-level MCP server list editor |
| `packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.test.ts` | CREATE | vitest |
| `packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte` | MODIFY | Add Tools tab |
| `packages/ai-parrot-server/ui/src/lib/agents/fields.ts` | MODIFY | TabId 'tools'; FIELD_TAB.tools → 'tools' |
| `packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte` | MODIFY | Remove the tools checkbox list (moved to TabsTools) |
| `packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py` | CREATE | pytest wrapper |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
// see Existing Signatures
```

### Existing Signatures to Use
```python
// packages/ai-parrot-server/ui/src/lib/api/agents.ts — `import apiClient from "$lib/api/http";` (:16); axios instance:
//   const { data } = await apiClient.get<T>(url); apiClient.put / post / delete likewise (see getAgent :34, updateAgent :58)
// packages/ai-parrot-server/ui/src/lib/api/http.ts — export class ApiError (:31); export default apiClient (:197)
// Generated types (after TASK-3663): import type { ToolkitSchemaEnvelope } from "$lib/types/generated/ToolkitSchemaEnvelope";
//   same pattern for ToolkitSpec, AgentMCPServerSpec, ConfigOption, ToolkitConfigPutRequest, AgentToolkitsResponse,
//   ToolkitPersistResponse, AgentMcpServersPutRequest, AgentMcpServersResponse, ToolkitOptionsResponse
// Widgets: $lib/ui/internal/shadcn/ui/{checkbox,label,slider,switch}/index.js (used by form/TabsCapabilities.svelte:15-18)
// Kit: $lib/ui/components — AppTabs, AppSheet (drawer), AppDialog, AppToggle, AppTooltip (index.ts)
// Existing editors: $lib/components/JsonEditor.svelte, $lib/components/StringListEditor.svelte
// Svelte 5 runes only: $state, $derived, $props, $effect — never `export let`.

# packages/ai-parrot-server/tests/ui/_vitest.py (created by TASK-3664) — run_vitest(*files: str) -> None
#   runs `pnpm exec vitest run <files>` in packages/ai-parrot-server/ui; pytest.skip when pnpm or packages/ai-parrot-server/ui/node_modules is missing;
#   asserts returncode == 0 and prints stdout/stderr on failure.

// packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte — import TabsCapabilities (:48); const TABS (:90-97)
//   `    { id: "capabilities", label: "Capabilities" },` (:94) ← anchor
//   `      <TabsCapabilities state={formState} {catalog} {tools} />` (:199) ← anchor (inside <TabsContent value="capabilities">, :198)
// packages/ai-parrot-server/ui/src/lib/agents/fields.ts — `export type TabId = "general"|"behavior"|"ai"|"capabilities"|"data_memory"|"advanced";` (:15-21)
//   `  tools: "capabilities",` (:126) ← anchor
// packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte — knownToolNames (:31), selectedTools (:32), unknownTools (:35), toggleTool (:37-40)
// packages/ai-parrot-server/ui/src/lib/stores/agent-form.svelte.ts — class AgentFormState (:77): values, load (:118), diff (:201), payload (:216)
```

### Does NOT Exist
- ~~`/admin/studio` route~~ — not added; the tab lives in `/admin/agents/:name` (nav unchanged).
- ~~writing toolkit_config through `updateAgent`~~ — forbidden (400 use_studio_endpoint); drawer uses studio.ts.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.svelte",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/pages/agents/form/ToolkitDrawer.svelte",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/pages/agents/form/AgentMcpPanel.svelte",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/agents/fields.ts",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Keep each component ≤ ~250 lines. Follow TabsCapabilities' markup/classes for visual consistency.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. fields.ts + AgentForm wiring — *why*: tab routing and field→tab mapping for validation errors.
2. Trim TabsCapabilities — *why*: one owner for the tools list.
3. TabsTools, ToolkitDrawer, AgentMcpPanel — *why*: AC14.
4. vitest + wrapper.

### `packages/ai-parrot-server/ui/src/lib/agents/fields.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  tools: "capabilities",' fields.ts)
// REPLACE `  tools: "capabilities",` (verified: fields.ts:126) with:
  tools: "tools",
// and add `| "tools"` to `export type TabId` (verified: fields.ts:15-21), after `| "capabilities"`.
```

### `packages/ai-parrot-server/ui/src/pages/agents/AgentForm.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -c '{ id: "capabilities", label: "Capabilities" },' AgentForm.svelte)
     AFTER that line (verified: AgentForm.svelte:94) insert: -->
    { id: "tools", label: "Tools" },
<!-- occurrences: 1 (verified: grep -c '<TabsCapabilities state={formState} {catalog} {tools} />' AgentForm.svelte)
     AFTER the closing </TabsContent> that wraps that line (verified: AgentForm.svelte:198-200) insert: -->
    <TabsContent value="tools">
      <TabsTools state={formState} {tools} agentName={agentName} />
    </TabsContent>
<!-- FILL IN: import TabsTools from "./form/TabsTools.svelte"; derive agentName from the route param
     (undefined on /admin/agents/new) the same way the page already reads it -->
```

### `packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.svelte` (CREATE — skeleton)
```svelte
<!-- TabsTools (FEAT-593) — plain tools (form field), toolkits (Studio drawer), Datasets, MCP servers. -->
<script lang="ts">
  import type { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";
  import type { AgentToolkitsResponse } from "$lib/types/generated/AgentToolkitsResponse";
  import { getAgentToolkits, getToolkitSchema } from "$lib/api/studio";
  import ToolkitDrawer from "./ToolkitDrawer.svelte";
  import AgentMcpPanel from "./AgentMcpPanel.svelte";

  let { state, tools, agentName }: { state: AgentFormState; tools: Record<string, ToolInfo>; agentName?: string } = $props();

  let configured = $state<AgentToolkitsResponse | null>(null);
  let drawerSlug = $state<string | null>(null);
  const selected = $derived(state.values.tools ?? []);
  const unknownTools = $derived(selected.filter((t) => !(t in tools)));

  $effect(() => {
    if (agentName) getAgentToolkits(agentName).then((r) => (configured = r)).catch(() => (configured = null));
  });

  function toggleTool(name: string, on: boolean): void {
    state.values.tools = on ? [...selected, name] : selected.filter((t) => t !== name);
  }
  // FILL IN: toolkit detection (getToolkitSchema per slug, cached in a $state Map; 404 → plain tool)
</script>

<!-- FILL IN: sections Toolkits / Datasets / MCP servers; read-only banner when configured?.editable === false
     (show configured.reason); unknown tools surfaced; <ToolkitDrawer slug={drawerSlug} {agentName} readonly={…}
     onclose={…} onsaved={refresh} />; <AgentMcpPanel {agentName} readonly={…} /> -->
```

### `packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py` (CREATE)
```python
from ._vitest import run_vitest


def test_tools_tab_vitest():
    run_vitest("src/pages/agents/form/TabsTools.test.ts")
```

### FILL IN checklist
- [ ] TabsCapabilities trimming (remove tools list + unknown editor + toggleTool); bounded by "one owner of the tools list"
- [ ] TabsTools sections + toolkit detection; bounded by AC14
- [ ] ToolkitDrawer (load/save/delete/reload/test) + AgentMcpPanel; bounded by spec §2 User-Facing Behavior 1–7

---

## Acceptance Criteria

- [ ] Tools tab present; Capabilities no longer lists tools (AC14).
- [ ] Toggling a plain tool updates `state.values.tools` (saved by the normal form save).
- [ ] Drawer save calls `putAgentToolkit` and shows Reload; secrets never displayed after save.
- [ ] Non-editable registry agent → read-only with reason.
- [ ] `pnpm build` passes; vitest file passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py -q`

---

## Test Specification

```python
// packages/ai-parrot-server/ui/src/pages/agents/form/TabsTools.test.ts
// FILL IN: mock "$lib/api/studio" (vi.mock); render TabsTools with a fake AgentFormState-like object;
// test("toggling a plain tool updates state.values.tools"), test("unknown selected tools are surfaced"),
// test("read-only banner when editable=false")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `gpt-5.6-terra` (MCP backend `codex`), delivered via `coder_run_chunk` job `job-412b41cf2f54`, attempt `ba84499d1f7e486caf96486c7a7ff0e4`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `ee0eca26eb4c4a06f989cd760c7e5f2de8ef44c1` (`feat(tool-configuration-agentstudio): TASK-3665 — engine-committed coder deliverable`)
**Merge commit**: `787808d0c`
**Review**: `coder_record_review` recorded — `feedback_id: coder-review:ab20312cb836b2ef20b4ef1b`, `fix_commits: []`.

**Notes**: `coder_wait`/`coder_merge` returned `outcome: "merged"`, attempt `terminal: "completed"`, 1 attempt,
0 retries, 0 failures (319s), 0 lint residual. Diff verified against the task's file table: `TabsTools.svelte`
(CREATE, 130 insertions), `ToolkitDrawer.svelte` (CREATE, 121 insertions), `AgentMcpPanel.svelte` (CREATE, 76
insertions), `TabsTools.test.ts` (CREATE, 61 insertions), `AgentForm.svelte` (MODIFY, +8/-... adds Tools tab),
`lib/agents/fields.ts` (MODIFY, TabId 'tools'), `TabsCapabilities.svelte` (MODIFY, -58, tools checkbox list
removed), and `tests/ui/test_vitest_tools_tab.py` (CREATE, 5 insertions) — exactly the 8 declared files, no
unlisted files, nothing under `sdd/` touched.

This delivery consumes `SchemaForm.svelte` (TASK-3664) via `ToolkitDrawer.svelte`. TASK-3664's own compile-blocking
and runtime-crashing bugs (invalid `{#const}` sigil, wrong `AppTooltip` import, undefined `isOverridable`) were
discovered and fixed in `fix(tool-configuration-agentstudio): TASK-3664 review fixes` (commit `1fa02e65e`) while
unblocking TASK-3666.

**Post-review correction (2026-09-23, feature-level adversarial code review)**: `TabsTools.svelte` itself had a
Critical, this-task-own defect — it destructured a `$props()` field literally named `state` while also calling
the `$state(...)` rune 3 times in the same script block. Svelte 5 treats a local binding named `state` as
ambiguous with the rune, crashing the component at mount (`store_invalid_shape`) — confirmed by actually
running `TabsTools.test.ts`, which failed all 3 tests for exactly this reason. `AgentForm.svelte` (this same
delivery's own sibling file) already documents this exact gotcha in its header comment ("local class instance
is named `formState`, not `state`") — the convention existed in the diff but wasn't followed. Fixed in
`841da0c44`: prop renamed `state` → `formState` throughout `TabsTools.svelte`, `TabsTools.test.ts`, and the
`AgentForm.svelte` call site. Re-ran `pytest packages/ai-parrot-server/tests/ui/test_vitest_tools_tab.py -q`
(wraps this same vitest file) after both this fix and the TASK-3664 fix above — 3/3 passing, confirming the
earlier-flagged "not independently re-run" concern is now resolved. Feedback recorded —
`feedback_id: coder-feedback:5bbc677afc7b09ef26b755e7`.

**Deviations from spec**: none.
