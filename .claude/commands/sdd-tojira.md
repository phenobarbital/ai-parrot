---
description: Export an SDD Specification to a Jira Story (and optionally subtasks). Creates the ticket, updates the spec with the Jira key, and commits the change.
---

# /sdd-tojira — Export Specification to Jira

Export the content of a formal specification file (`sdd/specs/*.spec.md`) to a new
Jira ticket. Optionally creates subtasks from decomposed SDD tasks.

```
/sdd-spec → /sdd-task → /sdd-tojira → Jira Story + Subtasks
```

## Usage
```
/sdd-tojira sdd/specs/jira-oauth.spec.md
/sdd-tojira sdd/specs/jira-oauth.spec.md --with-subtasks    # also create subtasks from tasks
/sdd-tojira sdd/specs/jira-oauth.spec.md --project=NAVAI    # override project key
/sdd-tojira FEAT-071                                        # resolve by Feature ID
```

## Guardrails
- The input must be a valid path to an existing `.spec.md` file, or a Feature ID.
- Do NOT create duplicate tickets — search first.
- Default target: Project `NAV`, Component `Nav-AI`, Issue Type `Story`.
- **Always commit the spec update** (with Jira key) so worktrees can see it.
- Do NOT modify existing Jira tickets unless the user explicitly requests an update.

## Jira Access Strategy

Use **mcp-atlassian** if available, falling back to **curl** if not.

### Detect available method
```bash
# Check if mcp-atlassian tools are available
# If jira_create_issue tool exists → use MCP
# Otherwise → use curl with env vars
```

### MCP path (preferred)
```
jira_create_issue(project_key="NAV", summary="...", ...)
jira_search(jql="...", ...)
```

### curl fallback
```bash
# Requires env vars loaded via navconfig (env/.env):
#   JIRA_INSTANCE  — e.g. https://trocglobal.atlassian.net/
#   JIRA_USERNAME  — email for Jira Cloud
#   JIRA_API_TOKEN — API token (Personal Access Token)
#
# Load them:
#   eval "$(python -c "from navconfig import config; import os; [print(f'export {k}={v}') for k,v in os.environ.items() if k.startswith('JIRA_')]")"

JIRA_INSTANCE="${JIRA_INSTANCE%/}"
curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$JIRA_INSTANCE/rest/api/3/issue" \
  -d '{ ... }'
```

## Steps

### 1. Resolve the Spec File

If the user passes a Feature ID instead of a path:
```bash
# Search sdd/specs/ for matching FEAT-ID
grep -rl "FEAT-071" sdd/specs/ | head -1
```

Read the spec file and extract:

| Field | Source in Spec | Maps to Jira |
|-------|---------------|--------------|
| Feature ID | Metadata header | Summary prefix: `[FEAT-NNN]` |
| Feature Name | `# <title>` | Summary |
| Section 1 | Motivation & Business Requirements | Description |
| Section 5 | Acceptance Criteria | AC custom field |
| Components | Module Breakdown / Impact | Jira components |
| Effort | Worktree Strategy or task index | Original estimate |
| Status | `status:` metadata | Not mapped (always creates as "To Do") |

### 2. Extract Spec Content

**Description**: Render Section 1 (Motivation & Business Requirements) as the
Jira description. For Jira Cloud v3, use ADF format or plain markdown
(Jira Cloud accepts markdown in the v2 endpoint):

```markdown
## Motivation

<Section 1 content>

## Architectural Overview

<Section 2 summary — first 2-3 paragraphs only, not full design>

## Acceptance Criteria

<Section 5 content>

---
_Exported from SDD spec: sdd/specs/<feature-name>.spec.md_
_Feature ID: FEAT-<ID>_
```

**Acceptance Criteria**: Extract the numbered list from Section 5.
Format for the AC custom field:
```
# User can authenticate via OAuth 2.0
# Tokens are stored securely in Redis
# Token refresh happens automatically
```

**Estimate**: Calculate from task index if `--with-subtasks`:
```bash
# Read sdd/tasks/.index.json, sum effort for this feature
# S=4h, M=8h, L=16h, XL=32h
TOTAL_SECONDS=$(echo "$TASKS" | jq '[.tasks[] | select(.feature_id=="FEAT-071") |
  if .effort=="S" then 14400
  elif .effort=="M" then 28800
  elif .effort=="L" then 57600
  elif .effort=="XL" then 115200
  else 28800 end] | add')
```
Default: `28800` (8h = 1 day) if no tasks exist.

### 3. Search for Existing Ticket

Before creating, check for duplicates:

**MCP path:**
```
jira_search(jql="project = NAV AND summary ~ \"FEAT-071\"", max_results=5)
```

**curl fallback:**
```bash
curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  "$JIRA_INSTANCE/rest/api/3/search?jql=project%3DNAV%20AND%20summary~%22FEAT-071%22&maxResults=5"
```

If found:
```
⚠️  Existing ticket found: NAV-8036 — "[FEAT-071] jira-oauth"
    Status: In Progress | Assignee: jleon

    Options:
    1. Skip — do nothing (ticket already exists)
    2. Update — overwrite description and AC with current spec content
    3. Create new — create a separate ticket anyway (not recommended)
```

Wait for user confirmation. Default: `skip`.

### 4. Create Jira Issue

**MCP path:**
```
jira_create_issue(
    project_key="NAV",
    summary="[FEAT-071] jira-oauth — OAuth 2.0 support for JiraToolkit",
    issue_type="Story",
    description="<formatted description>",
    components="Nav-AI",
    additional_fields='{"timeoriginalestimate": "<TOTAL_SECONDS>"}'
)
```

**curl fallback:**
```bash
curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$JIRA_INSTANCE/rest/api/3/issue" \
  -d '{
    "fields": {
      "project": {"key": "NAV"},
      "summary": "[FEAT-071] jira-oauth — OAuth 2.0 support for JiraToolkit",
      "issuetype": {"name": "Story"},
      "description": {"type": "doc", "version": 1, "content": [...]},
      "components": [{"name": "Nav-AI"}],
      "timeoriginalestimate": 28800
    }
  }'
```

Extract the created ticket key from the response: `JIRA_KEY=$(echo "$RESPONSE" | jq -r '.key')`

### 5. Set Acceptance Criteria

After creating the ticket, set the AC custom field separately
(some Jira instances require this as a second call):

**MCP path:**
```
jira_update_issue(issue_key="<JIRA_KEY>", additional_fields='{"customfield_10021": "<formatted AC>"}')
```

**curl fallback:**
```bash
curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X PUT "$JIRA_INSTANCE/rest/api/3/issue/$JIRA_KEY" \
  -d '{"fields": {"customfield_10021": "<formatted AC>"}}'
```

Try fields in order: `customfield_10021`, `customfield_10022`, `customfield_10035`.
Log which field worked for future reference.

### 6. Create Subtasks (if --with-subtasks)

If the `--with-subtasks` flag is present and tasks exist in `sdd/tasks/.index.json`:

For each task belonging to this feature:
```bash
# Read task file for description
TASK_FILE=$(jq -r ".tasks[] | select(.id==\"TASK-001\") | .file" sdd/tasks/.index.json)
```

Create a subtask:

**MCP path:**
```
jira_create_issue(
    project_key="NAV",
    summary="[TASK-001] OAuth callback handler",
    issue_type="Sub-task",
    parent="<JIRA_KEY>",
    description="<task description + scope>",
    additional_fields='{"timeoriginalestimate": "<effort_seconds>"}'
)
```

**curl fallback:**
```bash
curl -s -u "$JIRA_USERNAME:$JIRA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$JIRA_INSTANCE/rest/api/3/issue" \
  -d '{
    "fields": {
      "project": {"key": "NAV"},
      "parent": {"key": "<JIRA_KEY>"},
      "summary": "[TASK-001] OAuth callback handler",
      "issuetype": {"name": "Sub-task"},
      "description": {"type": "doc", "version": 1, "content": [...]},
      "timeoriginalestimate": 14400
    }
  }'
```

Map effort to seconds: S=4h(14400), M=8h(28800), L=16h(57600), XL=32h(115200).

### 7. Update Spec with Jira Key

After successful creation, update the spec file with the Jira key:

```bash
# Add jira key to spec metadata
# Look for the metadata block at the top of the spec
```

If the spec has a YAML frontmatter block, add `jira: NAV-8036`.
If not, add a metadata line after the title:

```markdown
# FEAT-071 — OAuth 2.0 support for JiraToolkit

**Jira**: [NAV-8036](https://trocglobal.atlassian.net/browse/NAV-8036)
**Status**: approved
```

### 8. Update Task Index (if --with-subtasks)

Update `sdd/tasks/.index.json` with the Jira subtask keys:

```json
{
  "id": "TASK-001",
  "feature_id": "FEAT-071",
  "jira_key": "NAV-8037",
  "jira_parent": "NAV-8036"
}
```

### 9. Commit Changes

```bash
git add sdd/specs/<feature-name>.spec.md
# If subtasks were created:
git add sdd/tasks/.index.json
git commit -m "sdd: export FEAT-<ID> to Jira <JIRA_KEY>"
```

### 10. Output

```
✅ Spec exported to Jira: NAV-8036
   https://trocglobal.atlassian.net/browse/NAV-8036

   Project: NAV
   Component: Nav-AI
   Type: Story
   Estimate: 3d (24h across 4 tasks)
   AC: 3 criteria exported

   Subtasks created: (if --with-subtasks)
     NAV-8037 — [TASK-001] OAuth callback handler [S/4h]
     NAV-8038 — [TASK-002] CredentialResolver abstraction [M/8h]
     NAV-8039 — [TASK-003] JiraToolkit OAuth integration [M/8h]
     NAV-8040 — [TASK-004] Redis token storage [S/4h]

   Spec updated: sdd/specs/jira-oauth.spec.md (jira key added)
   Changes committed.

Next steps:
  1. Review the ticket in Jira.
  2. Assign and prioritize in your sprint.
  3. To implement: /sdd-start or use sdd-autopilot.
```

## Reverse Linking

When the Jira ticket is created, the spec gains a `jira:` metadata field.
This enables:
- `/pr-review` to auto-detect the Jira key from the spec
- `sdd-autopilot` to post completion comments back to Jira
- `/sdd-done` to optionally transition the Jira ticket to "Done"

## Edge Cases

- **Spec not approved**: Warn that exporting a draft spec may create confusion.
  Ask for confirmation.
- **No AC in spec**: Create the ticket without AC. Warn that the AC field is empty.
- **mcp-atlassian not configured**: Fall back to curl. If env vars are also missing,
  error with setup instructions.
- **Subtask issue type not available**: Some projects don't have Sub-task enabled.
  Fall back to creating linked Tasks instead:
  ```
  jira_create_issue(issue_type="Task", ...)
  jira_link_issues(inward="NAV-8036", outward="NAV-8037", link_type="is parent of")
  ```
- **ADF vs Markdown**: Jira Cloud v3 (`/rest/api/3/`) requires ADF for description.
  Use v2 (`/rest/api/2/`) with markdown, or construct ADF JSON programmatically.
  When using mcp-atlassian, the tool handles conversion internally.
- **Custom field IDs differ per instance**: The AC field auto-detection tries
  10021 → 10022 → 10035. If all fail, log a warning and skip AC export.
  Suggest the user run `jira_get_issue` on an existing ticket with AC to discover
  the correct field ID.

## Reference
- Jira tool (MCP): `mcp_mcp-atlassian_jira_create_issue`
- Jira tool (ai-parrot): `JiraToolkit.jira_create_issue()`
- Spec template: `sdd/templates/spec.md`
- Task index: `sdd/tasks/.index.json`
- SDD methodology: `sdd/WORKFLOW.md`
- Auto-commit rule: `CLAUDE.md` (section "SDD Auto-Commit Rule")
