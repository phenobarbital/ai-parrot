# TASK-051: JSON Serialization for WebSearchAgent Config

**Feature**: WebSearchAgent Support in CrewBuilder
**Spec**: `sdd/specs/crew-websearchagent-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-049, TASK-050
**Assigned-to**: unassigned

---

## Context

> This task implements Module 3 from the spec: ensuring WebSearchAgent-specific configuration is correctly serialized into the JSON crew definition when saving.

When the crew is saved (exported or sent to the backend), the JSON must include all WebSearchAgent parameters in the `config` object for each agent.

**Repository**: `navigator-frontend-next` (NOT ai-parrot)

---

## Scope

- Update `crewStore.ts` to ensure WebSearchAgent config fields are serialized
- Handle conditional serialization: only include `contrastive_prompt` if `contrastive_search` is true
- Handle conditional serialization: only include `synthesize_prompt` if `synthesize` is true
- Validate that prompts contain required placeholders (`$query`, `$search_results`) on save
- Show validation warning (not error) if placeholders missing

**NOT in scope**:
- UI components (TASK-049, TASK-050)
- Backend parsing/validation (TASK-052)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/lib/stores/crewStore.ts` | MODIFY | Add serialization logic for WebSearchAgent config |

---

## Implementation Notes

### Expected JSON Output

When WebSearchAgent is configured with contrastive search and synthesis enabled:

```json
{
  "agents": [
    {
      "agent_id": "web_search_1",
      "agent_class": "WebSearchAgent",
      "name": "Research Agent",
      "config": {
        "temperature": 0.0,
        "contrastive_search": true,
        "contrastive_prompt": "Compare $query vs: $search_results",
        "synthesize": true,
        "synthesize_prompt": "Summarize: $search_results"
      },
      "tools": [],
      "system_prompt": "..."
    }
  ]
}
```

When only contrastive is enabled (synthesis disabled):

```json
{
  "config": {
    "temperature": 0.0,
    "contrastive_search": true,
    "contrastive_prompt": "...",
    "synthesize": false
  }
}
```

Note: `synthesize_prompt` is omitted when `synthesize` is false.

### Pattern to Follow

```typescript
function serializeAgentConfig(agent: AgentDefinition): AgentDefinition {
  const config = { ...agent.config };

  if (agent.agent_class === 'WebSearchAgent') {
    // Ensure temperature defaults
    config.temperature = config.temperature ?? 0.0;

    // Conditional prompt inclusion
    if (!config.contrastive_search) {
      delete config.contrastive_prompt;
    }
    if (!config.synthesize) {
      delete config.synthesize_prompt;
    }
  }

  return { ...agent, config };
}
```

### Validation Logic

```typescript
function validateWebSearchAgentPrompt(prompt: string): string[] {
  const warnings: string[] = [];
  if (!prompt.includes('$query')) {
    warnings.push('Prompt should include $query placeholder');
  }
  if (!prompt.includes('$search_results')) {
    warnings.push('Prompt should include $search_results placeholder');
  }
  return warnings;
}
```

### Key Constraints

- Do NOT fail save on validation warnings — just display them
- Preserve all other config fields unchanged
- Only apply WebSearchAgent-specific logic when `agent_class === "WebSearchAgent"`

---

## Acceptance Criteria

- [ ] WebSearchAgent config fields serialize to JSON correctly
- [ ] `contrastive_prompt` omitted when `contrastive_search` is false
- [ ] `synthesize_prompt` omitted when `synthesize` is false
- [ ] Validation warning shown if prompts missing `$query` or `$search_results`
- [ ] Save succeeds even with validation warnings
- [ ] Non-WebSearchAgent agents serialize unchanged

---

## Test Specification

```typescript
describe('crewStore serialization', () => {
  it('serializes WebSearchAgent with all fields', () => {
    const agent = {
      agent_class: 'WebSearchAgent',
      config: {
        temperature: 0.0,
        contrastive_search: true,
        contrastive_prompt: 'Compare $query: $search_results',
        synthesize: true,
        synthesize_prompt: 'Summarize $query: $search_results'
      }
    };
    const result = serializeAgentConfig(agent);
    expect(result.config.contrastive_prompt).toBeDefined();
    expect(result.config.synthesize_prompt).toBeDefined();
  });

  it('omits contrastive_prompt when contrastive_search is false', () => {
    const agent = {
      agent_class: 'WebSearchAgent',
      config: {
        contrastive_search: false,
        contrastive_prompt: 'should be removed'
      }
    };
    const result = serializeAgentConfig(agent);
    expect(result.config.contrastive_prompt).toBeUndefined();
  });

  it('validates prompt placeholders', () => {
    const warnings = validateWebSearchAgentPrompt('No placeholders');
    expect(warnings).toContain('Prompt should include $query placeholder');
    expect(warnings).toContain('Prompt should include $search_results placeholder');
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
6. **Move this file** to `tasks/completed/TASK-051-json-serialization.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
