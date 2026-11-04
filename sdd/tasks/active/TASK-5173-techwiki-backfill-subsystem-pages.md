# TASK-5173: Backfill subsystem pages

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5169, TASK-5172
**Assigned-to**: unassigned

---

## Context

> Spec §3 M8. Creates ten authored subsystem pages from the `sdd/templates/techwiki-page.md`
> template, each covering a major subsystem. Pages that already exist after M7's migration
> are extended, not duplicated. Content is written from the code and existing specs. Depends
> on TASK-5169 (page template) and TASK-5172 (wiki sections exist).

---

## Scope

- CREATE / EXTEND ten wiki pages:
  - `wiki/bots/agents-and-chatbots.md`
  - `wiki/clients/abstract-client.md`
  - `wiki/tools/tools-and-toolkits.md`
  - `wiki/memory/conversation-memory.md`
  - `wiki/flows/agentcrew-and-agentsflow.md`
  - `wiki/skills/skills.md`
  - `wiki/stores/vector-stores-and-embeddings.md`
  - `wiki/stores/loaders.md`
  - `wiki/mcp/mcp-server-and-client.md`
  - `wiki/server/handlers-and-manager.md`
- Each page follows the `sdd/templates/techwiki-page.md` template structure
- Each page links its `ref:` pages to the generated API reference
- Content written from code inspection and existing specs/docs

**NOT in scope**: Migration (TASK-5172), additional subsystem pages beyond the ten listed, M9 follow-up.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/bots/agents-and-chatbots.md` | CREATE/EXTEND | Bot/Agent/Chatbot subsystem |
| `wiki/clients/abstract-client.md` | CREATE/EXTEND | AbstractClient + providers |
| `wiki/tools/tools-and-toolkits.md` | CREATE/EXTEND | @tool, AbstractToolkit, ToolManager |
| `wiki/memory/conversation-memory.md` | CREATE/EXTEND | ConversationMemory, compaction |
| `wiki/flows/agentcrew-and-agentsflow.md` | CREATE/EXTEND | AgentCrew + AgentsFlow |
| `wiki/skills/skills.md` | CREATE/EXTEND | Skills system |
| `wiki/stores/vector-stores-and-embeddings.md` | CREATE/EXTEND | Vector stores + embeddings |
| `wiki/stores/loaders.md` | CREATE/EXTEND | Document loaders |
| `wiki/mcp/mcp-server-and-client.md` | CREATE/EXTEND | MCP integration |
| `wiki/server/handlers-and-manager.md` | CREATE/EXTEND | HTTP handlers + BotManager |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No Python code — this is a content authoring task
```

### Existing Signatures to Use
```python
# Key classes to document (from .agent/CONTEXT.md):
# parrot/clients/base.py — AbstractClient
# parrot/bots/ — AbstractBot, Chatbot, Agent
# parrot/tools/ — AbstractTool, AbstractToolkit, @tool, ToolManager
# parrot/memory/ — ConversationMemory, render_history, compaction/
# parrot/bots/flows/crew/ — AgentCrew
# parrot/bots/flows/flow/ — AgentsFlow
# parrot/skills/ — SkillFileToolkit, SkillRegistryToolkit
# parrot/stores/ — AbstractStore, PgVector, Milvus, ArangoDB
# parrot/loaders/ — BaseLoader
# parrot/integrations/mcp/ — MCP server
# parrot/handlers/ — HTTP handlers
# parrot/server/ — BotManager
```

### Does NOT Exist
- Some pages may already exist after M7 migration — check first, extend rather than duplicate

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/bots/agents-and-chatbots.md", "action": "CREATE"},
    {"path": "wiki/clients/abstract-client.md", "action": "CREATE"},
    {"path": "wiki/tools/tools-and-toolkits.md", "action": "CREATE"},
    {"path": "wiki/memory/conversation-memory.md", "action": "CREATE"},
    {"path": "wiki/flows/agentcrew-and-agentsflow.md", "action": "CREATE"},
    {"path": "wiki/skills/skills.md", "action": "CREATE"},
    {"path": "wiki/stores/vector-stores-and-embeddings.md", "action": "CREATE"},
    {"path": "wiki/stores/loaders.md", "action": "CREATE"},
    {"path": "wiki/mcp/mcp-server-and-client.md", "action": "CREATE"},
    {"path": "wiki/server/handlers-and-manager.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Use the six-section template from `sdd/templates/techwiki-page.md` (TASK-5169)
- Each page must have YAML frontmatter with `title` and `summary`
- Link to generated API reference pages using `ref:` scheme (e.g. `[AbstractClient](ref:parrot.clients.base)`)
- Content must be accurate — read the actual source code and existing docs
- If a page already exists from M7, extend it with the template's missing sections
- All pages must be in English (AC-15)

---

## Implementation Blueprint

### Steps (in order)
1. Check which of the ten pages already exist after TASK-5172 — *why*: extend, don't duplicate
2. For each missing page, create from template — *why*: consistency
3. For each existing page, add missing sections — *why*: completeness
4. Read source code for each subsystem — *why*: accurate content
5. Add `ref:` links to API reference pages — *why*: cross-linking
6. Validate page titles have no hyphens — *why*: `PageNameError` prevention

### Page content guidelines (all pages)
Each page should cover:
- **Purpose**: What the subsystem does, when to use it
- **Public API**: key classes/functions with `ref:` links
- **Configuration**: constructor args, environment variables, config keys
- **Usage Examples**: working, copy-pasteable code
- **Gotchas**: common mistakes, known issues, async patterns
- **Related**: links to other wiki pages

### FILL IN checklist
- [ ] All ten pages — content from code inspection; bounded by the template structure
- [ ] `ref:` links — must reference modules that the API generator will render; bounded by the config

---

## Acceptance Criteria

- [ ] Ten subsystem pages exist under `wiki/` with the template structure
- [ ] Each page has YAML frontmatter with `title` and `summary`
- [ ] Each page links to generated API reference pages via `ref:`
- [ ] Content is accurate (based on current source code)
- [ ] All pages in English (AC-15)
- [ ] No page title contains a literal hyphen
- [ ] `parrot sdd techwiki bundle --dry-run` produces no dangling links from these pages

---

## Validation Commands

- `pytest tests/sdd_scripts/test_feat801_doc_contract.py -q`

---

## Test Specification

Validation is through `parrot sdd techwiki bundle --dry-run` (no dangling links) and manual
review of content accuracy. The doc contract test validates the template exists.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
2. **Check dependencies** — TASK-5169 and TASK-5172 must be `done`
3. **Check** which pages already exist (from M7 migration)
4. **Read source code** for each subsystem before writing its page
5. **Use the template** from `sdd/templates/techwiki-page.md`
6. **Run** `parrot sdd techwiki bundle --dry-run` to check for dangling links
7. **Commit** all wiki pages
8. **Close** with `parrot sdd task close TASK-5173 github-wiki-technical-reference verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
