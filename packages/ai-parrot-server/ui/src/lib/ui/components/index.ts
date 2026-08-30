// App UI wrapper components — public API for feature code.
// Import from '$lib/ui/components' in feature files.
// Do NOT import from bits-ui or internal/ directly in features.
//
// ai-parrot (FEAT-476 TASK-2593): trimmed from navigator's full index.ts
// (139 lines, re-exporting every shadcn-svelte primitive alongside the
// App* wrappers) to only the App* wrappers the AgentChat closure actually
// imports (spec §3 Module 3). Every shadcn primitive already exists in
// the Admin UI's own `$lib/ui/internal/shadcn/ui/*` (FEAT-468/475) and is
// imported directly from there by the vendored chat components — no
// second re-export surface here.
export { default as AppDialog } from "./AppDialog.svelte";
export { default as AppTooltip } from "./AppTooltip.svelte";
export { default as AppDropdown } from "./AppDropdown.svelte";
export { default as AppDropdownItem } from "./AppDropdownItem.svelte";
export { default as AppTabs } from "./AppTabs.svelte";
export { default as AppTabItem } from "./AppTabItem.svelte";
export { default as AppToggle } from "./AppToggle.svelte";
export { default as SimpleTable } from "./SimpleTable.svelte";
export { default as AppTextEditor } from "./AppTextEditor.svelte";
export { default as AppTextEditorLite } from "./AppTextEditorLite.svelte";
export { default as LlmModelPicker } from "./LlmModelPicker.svelte";
export { default as AppSheet } from "./AppSheet.svelte";
export { default as AppCommand } from "./AppCommand.svelte";
