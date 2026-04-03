---
description: Bootstrap an SDD Brainstorm from a Jira ticket using mcp-atlassian
---

# /sdd-fromjira — Bootstrap Brainstorm from Jira

Fetch requirements from a Jira ticket (`issue_key`) and scaffold a structured brainstorm document in `sdd/proposals/`.

## Guardrails
- REQUIRES `mcp-atlassian` MCP to be installed and configured.
- Do NOT modify the Jira ticket — only READ from it.
- Always use the `sdd/templates/brainstorm.md` template for the output.
- The output file must be named `sdd/proposals/<issue-key>-<slug>.brainstorm.md`.

## Steps

### 1. Fetch Jira Ticket
Invoke the `mcp-atlassian` Jira tool `jira_get_issue` with the provided `issue_key` (e.g., `NAV-7724`).
- Extract the **Summary** (title) and **Description**.
- If the ticket is not found or inaccessible, notify the user.

### 2. Parse and Analyze
Extract the core requirements from the Jira description:
- **Problem Statement**: What is the primary pain point described?
- **Constraints / Requirements**: Look for technical constraints or business rules.
- **Context**: Any existing systems or background mentioned.

### 3. Generate Brainstorm Options
Based on the ticket's intent, perform research on the codebase to identify:
- Relevant modules or classes to extend.
- Available internal tools or loaders.
- Potential technical approaches (Option A, B, C).

### 4. Scaffold the Document
1. Read the template at `sdd/templates/brainstorm.md`.
2. Map Jira data to the template:
   - `Jira Summary` → Document Title
   - `Jira Key` → Included in metadata and filename.
   - `Jira Description` → Initial "Problem Statement" and "Constraints".
3. Auto-fill the **Options Explored** with at least **3 distinct technical approaches** derived from your codebase research.
4. Set `Status: exploration`.
5. Save to `sdd/proposals/<issue-key>-<slug>.brainstorm.md`.

### 5. Output and Next Steps
Print confirmation and location:
```
✅ Brainstorm bootstrapped from Jira: sdd/proposals/<issue-key>-<slug>.brainstorm.md
   
   Summary: <Jira Summary>
   Approaches: <Count> options generated.

Next steps:
  1. Review the generated brainstorm options.
  2. Refine the recommendation.
  3. When ready: /sdd-spec <slug> (uses this brainstorm document)
```

## References
- Jira Tool: `mcp_mcp-atlassian_jira_get_issue`
- Brainstorm template: `sdd/templates/brainstorm.md`
- SDD methodology: `sdd/WORKFLOW.md`
