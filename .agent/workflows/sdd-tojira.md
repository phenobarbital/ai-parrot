---
description: Export an SDD Specification to a Jira Story using mcp-atlassian
---

# /sdd-tojira — Export Specification to Jira

Export the content of a formal specification file (`sdd/specs/*.spec.md`) to a new Jira ticket.

## Guardrails
- REQUIRES `mcp-atlassian` MCP to be installed and configured.
- The input must be a valid path to an existing `.spec.md` file.
- Do NOT create duplicate tickets if one already exists for this Feature ID (search first).
- Default target: Project `NAV`, Component `Nav-AI`, Issue Type `Story`.

## Steps

### 1. Parse Specification
Read the provided spec file (e.g., `sdd/specs/adaptive-rag.spec.md`):
- Extract **Feature Name** (slug) and **Feature ID**.
- Extract the content of **Section 1: Motivation & Business Requirements**.

### 2. Prepare Jira Data
Format the data for the `jira_create_issue` tool:
- **Project**: `NAV`
- **Summary**: `[FEAT-<ID>] <Feature Name>`
- **Description**: The content of Section 1 in Markdown format.
- **Issue Type**: `Story`
- **Additional Fields**:
  - `components`: `[{"name": "Nav-AI"}]`
  - `timeoriginalestimate`: `28800` (8 hours = 1 day)
  - `remainingEstimate`: `28800`

### 3. Search for Existing Ticket
Use `jira_search` to check if a ticket with the same Feature ID already exists in project `NAV`:
- Query: `project = NAV AND summary ~ "FEAT-<ID>"`
- If found, notify the user and ask if they want to update the existing ticket or create a new one.

### 4. Create Jira Issue
Invoke the `mcp-atlassian` Jira tool `jira_create_issue`:
```python
jira_create_issue(
    project_key="NAV",
    summary="[FEAT-NNN] <slug>",
    issue_type="Story",
    description="<Section 1 Content>",
    components="Nav-AI",
    additional_fields='{"timeoriginalestimate": "28800"}'
)
```

### 5. Output and Next Steps
Print confirmation with the new Jira Key:
```
✅ Spec exported to Jira: <Jira-Key> (https://trocglobal.atlassian.net/browse/<Jira-Key>)
   
   Project: NAV
   Component: Nav-AI
   Type: Story
   Estimate: 1d

Next steps:
  1. Review the ticket in Jira.
  2. Proceed with /sdd-task to decompose the spec into implementable tasks.
```

## References
- Jira Tool: `mcp_mcp-atlassian_jira_create_issue`
- SDD methodology: `sdd/WORKFLOW.md`
