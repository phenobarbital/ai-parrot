# TASK-050: Agent Type Detection in Config Panel

**Feature**: WebSearchAgent Support in CrewBuilder
**Spec**: `sdd/specs/crew-websearchagent-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-049
**Assigned-to**: unassigned

---

## Context

> This task implements Module 2 from the spec: detecting when a WebSearchAgent is selected and rendering the appropriate configuration component.

The CrewBuilder needs to recognize when the selected agent is a `WebSearchAgent` and dynamically render the specialized `WebSearchAgentConfig` component instead of the generic agent config panel.

**Repository**: `navigator-frontend-next` (NOT ai-parrot)

---

## Scope

- Modify `AgentConfigPanel.svelte` to detect `agent_class === "WebSearchAgent"`
- Conditionally render `WebSearchAgentConfig` component when WebSearchAgent is selected
- Fall back to generic agent config for all other agent types
- Ensure smooth transition when switching between agent types in the flow designer

**NOT in scope**:
- The WebSearchAgentConfig component itself (TASK-049)
- JSON serialization logic (TASK-051)
- Other agent-specific config panels

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/lib/components/crew-builder/AgentConfigPanel.svelte` | MODIFY | Add agent type detection and conditional rendering |

---

## Implementation Notes

### Pattern to Follow

```svelte
<script lang="ts">
  import WebSearchAgentConfig from './WebSearchAgentConfig.svelte';
  import GenericAgentConfig from './GenericAgentConfig.svelte';

  export let selectedAgent: AgentDefinition | null;

  $: isWebSearchAgent = selectedAgent?.agent_class === 'WebSearchAgent';
</script>

{#if selectedAgent}
  {#if isWebSearchAgent}
    <WebSearchAgentConfig agentConfig={selectedAgent} />
  {:else}
    <GenericAgentConfig agentConfig={selectedAgent} />
  {/if}
{/if}
```

### Key Constraints

- Detection must be case-sensitive: `"WebSearchAgent"` exactly
- Generic config fields (name, system_prompt, etc.) should still render alongside specialized config
- The component must handle null/undefined selectedAgent gracefully

### Agent Classes to Support

Currently known agent classes that might appear:
- `BaseAgent` / `Agent` — generic
- `Chatbot` — generic
- `WebSearchAgent` — specialized (this task)

Future agent classes can follow this pattern.

---

## Acceptance Criteria

- [ ] `AgentConfigPanel` detects `agent_class === "WebSearchAgent"`
- [ ] `WebSearchAgentConfig` component renders when WebSearchAgent selected
- [ ] Generic config renders for non-WebSearchAgent types
- [ ] No errors when `selectedAgent` is null
- [ ] Switching agents in the designer updates the config panel correctly

---

## Test Specification

```typescript
describe('AgentConfigPanel', () => {
  it('renders WebSearchAgentConfig for WebSearchAgent', () => {
    const agent = { agent_class: 'WebSearchAgent', config: {} };
    // render and expect WebSearchAgentConfig to be present
  });

  it('renders generic config for BaseAgent', () => {
    const agent = { agent_class: 'BaseAgent', config: {} };
    // render and expect GenericAgentConfig to be present
  });

  it('handles null selectedAgent gracefully', () => {
    // render with null, expect no errors
  });
});
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-050-agent-type-detection.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
