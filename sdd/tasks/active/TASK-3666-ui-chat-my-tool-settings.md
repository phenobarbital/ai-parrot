# TASK-3666: Chat DataManagementModal: 'My tool settings' tab over the /me endpoints

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3664
**Assigned-to**: unassigned

---

## Context

Spec §2 User-Facing Behavior (end user), §3 Module 13; AC15. The chat keeps a lighter per-user
surface: only toolkits with ≥1 currently-overridable param, SchemaForm restricted to those params.
Existing Data/MCP tabs keep working unchanged.

---

## Scope

- `MyToolkitSettings.svelte` (`{ agentId }`): for each configured toolkit of the agent, call
  `getMyToolkitOverride(agentId, slug)` → `{slug, overridable, params, configured}`; hide toolkits with
  empty `overridable`; build a sub-schema (the toolkit schema filtered to `overridable` properties) and
  render SchemaForm; Save → `putMyToolkitOverride`; Reset → `deleteMyToolkitOverride`; show "applies
  from your next message".
- `DataManagementModal.svelte`: add `{ value: 'mytools', title: 'My tool settings' }` to AppTabs and
  `{#if tab === 'mytools'}<MyToolkitSettings {agentId} />{/if}` next to the MCP branch.
- vitest + pytest wrapper.

**NOT in scope**: backend (/me endpoints: TASK-3661).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.svelte` | CREATE | Per-user override editor |
| `packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.test.ts` | CREATE | vitest |
| `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte` | MODIFY | Add the 'My tool settings' tab |
| `packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py` | CREATE | pytest wrapper |

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

// packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte
//   imports MCPServerTab (:11); <AppTabs tabs={[ { value: 'data', … }, { value: 'explain', … }, { value: 'mcp', title: 'MCP Servers' },
//     { value: 'appearance', … } ]} fillHeight> (:167-172); {#snippet children(tab)}
//   `{#if tab === 'mcp'}` / `      <MCPServerTab {agentId} />` (:336-338) ← anchor
```

### Does NOT Exist
- ~~a separate "My settings" modal~~ — reuse DataManagementModal's AppTabs.
- ~~writing agent-level config from the chat~~ — only `/me` endpoints.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.svelte",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.test.ts",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Which toolkits does the agent have? Use the `overridable` answer of `/me` per slug; the list of slugs comes from `getToolkitSchema`-able names the chat already knows — FILL IN: simplest reliable source is a GET-list call on the agent (TASK-3660 path); if the user lacks owner rights it 403s — then fall back to probing `/me` for slugs in the agent's tool list (document the choice).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. MyToolkitSettings — *why*: AC15.
2. Add the tab — *why*: reuse the existing modal.
3. vitest + wrapper.

### `packages/ai-parrot-server/ui/src/lib/components/agents/DataManagementModal.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -c "{ value: 'mcp', title: 'MCP Servers' }," DataManagementModal.svelte)
     AFTER that tab entry (verified: DataManagementModal.svelte:170) insert: -->
    { value: 'mytools', title: 'My tool settings' },
<!-- occurrences: 1 (verified: grep -c '      <MCPServerTab {agentId} />' DataManagementModal.svelte)
     AFTER the `{/if}` closing the mcp branch (verified: DataManagementModal.svelte:336-338) insert: -->
    {#if tab === 'mytools'}
      <MyToolkitSettings {agentId} />
    {/if}
<!-- and add `import MyToolkitSettings from "./MyToolkitSettings.svelte";` next to the MCPServerTab import (:11) -->
```

### `packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.svelte` (CREATE — skeleton)
```svelte
<!-- MyToolkitSettings (FEAT-593) — the user's own overrides of operator-allowed toolkit params. -->
<script lang="ts">
  import SchemaForm from "$lib/components/schema-form/SchemaForm.svelte";
  import { deleteMyToolkitOverride, getMyToolkitOverride, getToolkitSchema, putMyToolkitOverride } from "$lib/api/studio";

  let { agentId }: { agentId: string } = $props();
  let entries = $state<{ slug: string; overridable: string[]; schema: Record<string, any>; value: Record<string, unknown> }[]>([]);
  let status = $state<string | null>(null);

  // FILL IN: load slugs (see Implementation Notes), fetch /me + schema per slug, filter schema.properties to
  //   overridable, keep entries with overridable.length > 0
  async function save(slug: string, value: Record<string, unknown>): Promise<void> {
    await putMyToolkitOverride(agentId, slug, value);
    status = "Saved — applies from your next message.";
  }
</script>

<!-- FILL IN: empty state "No tool settings you can change for this agent"; one card per entry with
     <SchemaForm schema={e.schema} value={e.value} onchange={(v) => (e.value = v)} />, Save and Reset buttons -->
```

### `packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py` (CREATE)
```python
from ._vitest import run_vitest


def test_my_tool_settings_vitest():
    run_vitest("src/lib/components/agents/MyToolkitSettings.test.ts")
```

### FILL IN checklist
- [ ] Slug source decision (Implementation Notes); bounded by AC15
- [ ] Card markup + reset; bounded by AC15

---

## Acceptance Criteria

- [ ] 'My tool settings' tab present; hidden toolkits with no overridable params (AC15).
- [ ] Save/Reset call the /me endpoints; existing Data/MCP tabs unchanged.
- [ ] vitest file passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_my_tool_settings.py -q`

---

## Test Specification

```python
// packages/ai-parrot-server/ui/src/lib/components/agents/MyToolkitSettings.test.ts
// FILL IN: vi.mock("$lib/api/studio"); test("only toolkits with overridable params are listed"),
// test("save calls putMyToolkitOverride with the edited value")
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
