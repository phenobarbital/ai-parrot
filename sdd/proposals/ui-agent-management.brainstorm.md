# Brainstorm: UI Agent Management

**Date**: 2026-03-18
**Author**: Antigravity
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

The `ChatbotHandler` in `/api/v1/bots` allows creating, editing, and managing agents, but there is no dedicated User Interface to manage these bots. Currently, agent creation requires direct API interaction or database manipulation. We need a new UI in `navigator-frontend-next` (at `/agents`) to provide a complete CRUD experience for `BotModel` entities stored in the DB.

**Who is affected:**
- **Admins & Developers** — Currently have to use API clients to configure complex bot behaviors, memory, and vector stores.
- **End users** — Cannot easily view or manage available agents in the platform without a UI.

## Constraints & Requirements

- **DB Bots Only**: The UI only needs to handle the creation, editing, and deletion of bots stored in the database. Read-only registry bots are excluded from management.
- **Strictly CRUD**: The goal is to provide a complete form for all attributes in `BotModel` but no live "Testing/Preview" feature is required for now.
- **Integration Points**: 
  - Tools are selectable from `/api/v1/agent_tools`.
  - Knowledge Bases are currently manual/hardcoded based on `parrot/stores/kb`.
- **Advanced Options**: Class path is a simple text input. Permissions uses a JSON editor component.
- **Form UI**: Must be a dedicated page (e.g., `/agents/new` or `/agents/[id]`) separate from the list view (`/agents`).

---

## Options Explored

### Option A: Monolithic Single-Page Form

Create a single `AgentManagement.svelte` component that contains all sections (General, Behavior, AI, Tools, Knowledge Base, Vector Store, Conversation Memory, Advanced Options) laid out sequentially on one long scrolling page.

**Pros:**
- Simple to implement with straightforward two-way `$state` data binding.
- Users can use browser search (Ctrl+F) to find specific fields.
- No complex validation logic across hidden tabs.

**Cons:**
- High cognitive overload. `BotModel` has over 30 configurable fields.
- Poor user experience resulting in a cluttered interface.
- Does not feel like a "Premium" design.

**Effort:** Low

---

### Option B: Tabbed Wizard Interface

Use Flowbite Svelte Tabs (or a custom stepper) to logically group the configuration into distinct sections: `General`, `Behavior`, `AI & LLM`, `Capabilities` (Tools & KB), `Data & Memory` (Vector Store, Conversation), and `Advanced`.

**Pros:**
- Excellent UX; reduces cognitive overload by revealing complexity progressively.
- Logical grouping of related fields aligns well with mental models of configuring an LLM agent.
- Feels like a premium, modern dashboard application.

**Cons:**
- State management requires maintaining the overall form state while validating fields that might be hidden on other tabs.
- Slightly more code to wire up the Tab navigation.

| Library / Tool | Purpose | Notes |
|---|---|---|
| `flowbite-svelte` | UI Components | Tabs, Inputs, Checkboxes, Selects, Buttons |
| `Svelte 5 Runes` | State Management | Deeply reactive state for complex objects |

**Existing code to reuse:**
- Existing Svelte 5 patterns in `navigator-frontend-next/src/lib/components`.

**Effort:** Medium

---

### Option C: Accordion-Based Interface

Use an Accordion component where sections like "General" and "AI Behavior" are expanded by default, while "Vector Store" or "Advanced Options" are collapsed to save space.

**Pros:**
- Good balance between seeing everything on one page and not being overwhelmed.
- Easier cross-section validation than tabs.

**Cons:**
- Finding specific settings might require clicking through multiple accordions to find where a setting lives.
- Still results in a very long page if the user expands multiple sections.

**Effort:** Low

---

## Recommendation

**Option B — Tabbed Wizard Interface** is the recommended approach.

**Rationale:**
Given the sheer number of configuration options in `BotModel` (LLM params, system prompts, vector store configs, memory settings), a tabbed interface is the only way to provide a premium, uncluttered experience. While it requires slightly more effort to manage validation across tabs, the organization into logical groups (General, Behavior, AI, Capabilities, Memory/Data, Advanced) makes the complex task of agent creation approachable. 

---

## Feature Description

### User-Facing Behavior

**Agent List View (`/agents`):**
- Displays a data table or grid of existing cards showing bot name, description, role, and status (enabled/disabled).
- "Create Agent" button navigates to `/agents/new`.
- Clicking an existing agent navigates to `/agents/[id]`.

**Agent Management Form (`/agents/new` or `/agents/[id]`):**
A dedicated page featuring a Tabbed layout:
1. **General**: UUID (read-only), Name, Description, Avatar URL, Enabled toggle.
2. **Behavior**: Goal, Backstory, Rationale, Capabilities, and a list builder for `pre_instructions`.
3. **AI**: LLM provider (dropdown), Model selector, Temperature slider, Max Tokens.
4. **Capabilities**: 
   - Tools: Checkbox for `tools_enabled`. If checked, fetches `/api/v1/agent_tools` to show a multi-select or list builder for tools.
   - Knowledge Base: Checkbox for `use_kb`. Hardcoded list of KBs from `parrot/stores/kb`.
5. **Data & Memory**: 
   - Vector Store: `use_vector` checkbox. If true, shows config editor for PGVector/Redis, Embedding model dropdown, search limit, score threshold.
   - Conversation Memory: `memory_type` dropdown (nothing, redis, file, memory), and `use_conversation_history` toggle.
6. **Advanced Options**: Text input for `bot_class`, JSON editor for `permissions`.

Save/Cancel buttons remain sticky at the bottom of the page across all tabs.

### Internal Behavior

- **State Management**: Uses a centralized Svelte 5 `$state` object representing the `BotModel` payload.
- **Data Fetching**: 
  - In `/agents/[id]`, load existing agent data on mount.
  - Fetch available tools from `/api/v1/agent_tools` on mount.
- **JSON Editor**: For `permissions` and advanced configs, integrate a basic JSON editor or a `textarea` with JSON validation.
- **Form Submission**: Sends a `PUT` request to `/api/v1/bots` for new agents (including `storage: "database"`) or `POST` to `/api/v1/bots/{id}` for existing agents.

### Edge Cases & Error Handling

- **JSON Validation Errors**: Ensure the JSON editor for permissions and vector store config catches malformed JSON before allowing submission.
- **Missing Required Fields**: Highlight the specific tab with a red indicator if a required field (e.g., Name, Goal, Backstory) is empty when attempting to save.
- **Navigation without saving**: Warn user if they attempt to navigate away from the form with unsaved changes.

---

## Capabilities

### New Capabilities

- `ui-agent-list` — List, view, and initiate deletion of agents from the frontend.
- `ui-agent-creation` — Comprehensive tabbed form mapped to `BotModel` for creating/editing DB agents.

### Modified Capabilities

- None. Strictly adding frontend UI consuming existing `ChatbotHandler` API.

---

## Impact & Integration

| Component | Impact | Description |
|---|---|---|
| `navigator-frontend-next/src/routes/agents/+page.svelte` | **New** | Agent list view. |
| `navigator-frontend-next/src/routes/agents/[id]/+page.svelte` | **New** | Agent form wrapper for editing. |
| `navigator-frontend-next/src/routes/agents/new/+page.svelte` | **New** | Agent form wrapper for creation. |
| `navigator-frontend-next/src/lib/components/agents/AgentManagement.svelte` | **New** | Core tabbed form component. |

---

## Open Questions

| # | Question | Owner | Impact |
|---|---|---|---|
| 1 | Should the JSON editor for advanced permissions use an external library (e.g., `svelte-jsoneditor`) or just a validated auto-resizing textarea? | User | UX and dependency footprint |
| 2 | For the hardcoded KBs, what are the exact IDs/names we should hardcode in the UI for now? | User | Hardcoded data accuracy |
