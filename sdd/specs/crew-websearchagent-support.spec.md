# Feature Specification: WebSearchAgent Support in CrewBuilder

**Feature ID**: FEAT-012
**Date**: 2026-02-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`WebSearchAgent` is a specialized agent that supports advanced search capabilities including contrastive search (competitor/alternatives analysis) and LLM synthesis of search results. Currently, when users design agent crews in the CrewBuilder UI, they cannot configure these WebSearchAgent-specific parameters (`contrastive_search`, `contrastive_prompt`, `synthesize`, `synthesize_prompt`). This limits the usefulness of WebSearchAgent in visual workflow design.

### Goals

- Enable full configuration of WebSearchAgent parameters in the CrewBuilder UI (navigator-frontend-next)
- Ensure CrewHandler correctly passes WebSearchAgent-specific parameters through the agent creation pipeline
- Validate end-to-end flow from UI design to agent execution

### Non-Goals (explicitly out of scope)

- Adding new search capabilities to WebSearchAgent itself (already implemented)
- Modifying the core search tools (GoogleSearchTool, BingSearchTool, etc.)
- Changes to other agent types

---

## 2. Architectural Design

### Overview

This feature extends the existing CrewBuilder visual designer to recognize `WebSearchAgent` as a special agent type with additional configuration options. The backend already supports passing arbitrary config via `agent_def.config`, so the primary work is frontend UI changes and validation.

### Component Diagram

```
CrewBuilder UI (Svelte)
       │
       ▼
┌──────────────────────────┐
│  WebSearchAgent Config   │
│  - temperature slider    │
│  - contrastive_search    │
│  - contrastive_prompt    │
│  - synthesize checkbox   │
│  - synthesize_prompt     │
└──────────────────────────┘
       │
       ▼
   JSON Definition
       │
       ▼
┌──────────────────────────┐
│     CrewHandler          │
│  _create_crew_from_def() │
│  agent_def.config ──────►│ WebSearchAgent(**config)
└──────────────────────────┘
       │
       ▼
   WebSearchAgent
   (contrastive_search, synthesize, etc.)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WebSearchAgent` | uses | Receives parameters via `**kwargs` in `__init__` |
| `AgentDefinition` | extends | Config dict already supports arbitrary keys |
| `CrewHandler` | uses | Already passes `**agent_def.config` to agent constructor |
| `BotManager` | uses | `get_bot_class()` returns `WebSearchAgent` class |

### Data Models

The existing `AgentDefinition.config` dictionary will carry WebSearchAgent-specific parameters:

```python
# Example AgentDefinition for WebSearchAgent
AgentDefinition(
    agent_id="web_search_1",
    agent_class="WebSearchAgent",
    name="Research Agent",
    config={
        "temperature": 0.0,  # Default for search to avoid hallucination
        "contrastive_search": True,
        "contrastive_prompt": "Compare $query vs: $search_results",
        "synthesize": True,
        "synthesize_prompt": "Summarize for $query: $search_results"
    },
    tools=[],  # WebSearchAgent has built-in search tools
    system_prompt="You are a research assistant..."
)
```

### New Public Interfaces

No new public interfaces required. The feature uses existing data structures.

---

## 3. Module Breakdown

### Module 1: WebSearchAgent Config Component (Frontend)

- **Path**: `navigator-frontend-next/src/lib/components/crew-builder/WebSearchAgentConfig.svelte`
- **Responsibility**: Render configuration panel when WebSearchAgent node is selected
- **Depends on**: CrewBuilder node selection system

UI Elements:
- Temperature slider (default: 0.0, range: 0.0-1.0)
- Checkbox: "Enable Contrastive Search"
  - When checked: show textarea for `contrastive_prompt`
- Checkbox: "Enable Synthesis"
  - When checked: show textarea for `synthesize_prompt`

### Module 2: Agent Type Detection (Frontend)

- **Path**: `navigator-frontend-next/src/lib/components/crew-builder/AgentConfigPanel.svelte`
- **Responsibility**: Detect agent_class and render appropriate config component
- **Depends on**: Module 1

Logic:
```typescript
if (selectedAgent.agent_class === "WebSearchAgent") {
    // Render WebSearchAgentConfig component
} else {
    // Render generic agent config
}
```

### Module 3: JSON Serialization (Frontend)

- **Path**: `navigator-frontend-next/src/lib/stores/crewStore.ts`
- **Responsibility**: Serialize WebSearchAgent config into JSON definition
- **Depends on**: Module 1, Module 2

Ensures that when the crew is saved, the config object includes:
- `contrastive_search` (boolean)
- `contrastive_prompt` (string, only if contrastive_search is true)
- `synthesize` (boolean)
- `synthesize_prompt` (string, only if synthesize is true)

### Module 4: Backend Validation (ai-parrot)

- **Path**: `parrot/handlers/crew/handler.py`
- **Responsibility**: Validate WebSearchAgent-specific parameters before agent creation
- **Depends on**: Existing `_create_crew_from_definition` method

Add optional validation to warn if invalid prompt templates are provided (missing `$query` or `$search_results` placeholders).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_websearchagent_config_defaults` | Module 4 | Validate default values when no config provided |
| `test_websearchagent_contrastive_params` | Module 4 | Validate contrastive_search and prompt pass through |
| `test_websearchagent_synthesize_params` | Module 4 | Validate synthesize and prompt pass through |
| `test_websearchagent_combined_params` | Module 4 | Validate all parameters work together |

### Integration Tests

| Test | Description |
|---|---|
| `test_crew_with_websearchagent_creation` | Create crew via API with WebSearchAgent config |
| `test_crew_websearchagent_execution` | Execute crew with contrastive + synthesize enabled |

### Test Data / Fixtures

```python
@pytest.fixture
def websearchagent_crew_definition():
    return {
        "name": "research_crew",
        "execution_mode": "sequential",
        "agents": [
            {
                "agent_id": "web_search_1",
                "agent_class": "WebSearchAgent",
                "name": "Research Agent",
                "config": {
                    "temperature": 0.0,
                    "contrastive_search": True,
                    "contrastive_prompt": "Compare $query vs: $search_results",
                    "synthesize": True,
                    "synthesize_prompt": "Summarize: $search_results"
                },
                "tools": [],
                "system_prompt": "Research assistant"
            }
        ],
        "flow_relations": [],
        "shared_tools": []
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] CrewBuilder UI shows WebSearchAgent-specific config when that agent type is selected
- [ ] Temperature defaults to 0.0 for WebSearchAgent (to avoid hallucination)
- [ ] Contrastive search checkbox enables/disables the contrastive prompt textarea
- [ ] Synthesize checkbox enables/disables the synthesize prompt textarea
- [ ] JSON definition includes all WebSearchAgent parameters correctly
- [ ] CrewHandler creates WebSearchAgent with correct parameters
- [ ] Unit tests pass (`pytest tests/test_crew_websearchagent.py -v`)
- [ ] Integration test: crew with WebSearchAgent executes contrastive search successfully
- [ ] No breaking changes to existing crew definitions

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use existing `AgentDefinition.config` dict for parameters (no schema changes needed)
- Follow Svelte component patterns in `navigator-frontend-next`
- Use reactive stores for UI state management
- Validate prompts contain required placeholders (`$query`, `$search_results`)

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| Users forget placeholder syntax | Show hint text: "Use $query and $search_results in prompts" |
| Temperature too high causes hallucination | Default to 0.0, show warning if > 0.3 |
| Existing crews lack new fields | Fields are optional; defaults work correctly |

### External Dependencies

No new external dependencies required.

---

## 7. Open Questions

- [x] Do we need to update `AgentDefinition` model with explicit WebSearchAgent fields? — **No, config dict is sufficient**
- [ ] Should we validate prompt templates server-side? — *Owner: backend team*: No, we can do it in the frontend
- [ ] Should the UI show default prompts for reference? — *Owner: frontend team*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-27 | Jesus Lara | Initial draft from proposal |
