# TASK-049: WebSearchAgent Config Svelte Component

**Feature**: WebSearchAgent Support in CrewBuilder
**Spec**: `sdd/specs/crew-websearchagent-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 1 from the spec: the WebSearchAgent-specific configuration panel in the CrewBuilder UI.

When users add a `WebSearchAgent` to their crew in the visual designer, they currently see only the generic agent config. This task creates a specialized configuration component that exposes WebSearchAgent's unique parameters.

**Repository**: `navigator-frontend-next` (NOT ai-parrot)

---

## Scope

- Create `WebSearchAgentConfig.svelte` component
- Implement temperature slider (default: 0.0, range: 0.0-1.0)
- Implement "Enable Contrastive Search" checkbox
  - When checked: show textarea for `contrastive_prompt`
  - Show placeholder hint: "Use $query and $search_results in prompts"
- Implement "Enable Synthesis" checkbox
  - When checked: show textarea for `synthesize_prompt`
  - Show placeholder hint: "Use $query and $search_results in prompts"
- Show default prompt examples for reference (per open question decision)
- Add warning if temperature > 0.3 ("Higher temperature may cause hallucinations in search results")

**NOT in scope**:
- Agent type detection logic (TASK-050)
- JSON serialization to store (TASK-051)
- Backend validation (TASK-052)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/lib/components/crew-builder/WebSearchAgentConfig.svelte` | CREATE | Main configuration component |
| `src/lib/components/crew-builder/index.ts` | MODIFY | Export the new component |

---

## Implementation Notes

### Pattern to Follow

Follow the existing pattern in the CrewBuilder for agent configuration panels. Look at how other specialized agents (if any) handle their config.

```svelte
<script lang="ts">
  export let agentConfig: AgentDefinition;

  // Reactive bindings to agentConfig.config
  $: temperature = agentConfig.config.temperature ?? 0.0;
  $: contrastiveSearch = agentConfig.config.contrastive_search ?? false;
  $: contrastivePrompt = agentConfig.config.contrastive_prompt ?? '';
  $: synthesize = agentConfig.config.synthesize ?? false;
  $: synthesizePrompt = agentConfig.config.synthesize_prompt ?? '';
</script>
```

### Key Constraints

- Use two-way binding to update `agentConfig.config` in real-time
- Temperature defaults to 0.0 (NOT the usual 0.7) to avoid hallucination
- Textareas for prompts should only be visible when corresponding checkbox is checked
- Show default prompt examples inline for user reference

### Default Prompts for Reference

Contrastive:
```
Based on following query: $query
Below are search results about its COMPETITORS. Analyze ONLY the competitors:

$search_results

Structure your response as:
**Market Category**: [category]
**Competitors Found**: ...
```

Synthesis:
```
Based on the following query: $query
Analyze and synthesize the following search results into a comprehensive summary:

$search_results

Provide:
- **Key Findings**: Main insights from the results
- **Analysis**: Critical evaluation of the information
- **Summary**: Concise synthesis of all findings
```

---

## Acceptance Criteria

- [ ] Component renders temperature slider with default 0.0
- [ ] Component renders "Enable Contrastive Search" checkbox
- [ ] Contrastive prompt textarea appears only when checkbox is checked
- [ ] Component renders "Enable Synthesis" checkbox
- [ ] Synthesis prompt textarea appears only when checkbox is checked
- [ ] Default prompts shown for reference
- [ ] Warning shown when temperature > 0.3
- [ ] Two-way binding works: changes update agentConfig.config
- [ ] Component exported from index.ts

---

## Test Specification

```typescript
// Tests would be in the frontend repo
describe('WebSearchAgentConfig', () => {
  it('renders with default temperature 0.0', () => {
    // ...
  });

  it('shows contrastive prompt textarea when checkbox checked', () => {
    // ...
  });

  it('shows synthesis prompt textarea when checkbox checked', () => {
    // ...
  });

  it('shows warning when temperature > 0.3', () => {
    // ...
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
6. **Move this file** to `tasks/completed/TASK-049-websearchagent-config-component.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
