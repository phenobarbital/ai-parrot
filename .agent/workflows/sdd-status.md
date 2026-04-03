---
description: Show SDD task index status summary
---

# /sdd-status — Show Task Status

Read `sdd/tasks/.index.json` and print a human-friendly status report of all SDD tasks.

## Guardrails
- This is a **read-only** workflow — do not modify any files.
- If `sdd/tasks/.index.json` does not exist, inform the user and suggest running `/sdd-task` first.

## Steps

### 1. Read the Task Index
Read `sdd/tasks/.index.json`. If a `<feature-name>` filter is provided, show only tasks for that feature.

### 2. Compute Task States
For each task, determine the display status:
- **✅ done** — status is `"done"`
- **🔄 in-progress** — status is `"in-progress"`
- **⏳ pending** — status is `"pending"` AND all `depends_on` tasks are `"done"`
- **🔒 blocked** — status is `"pending"` AND some `depends_on` tasks are NOT `"done"`

### 3. Print the Status Table
Output:
```
📊 SDD Status — <feature-name>
Spec: sdd/specs/<feature>.spec.md

  ID        Priority  Effort  Status       Assigned       Title
  ────────────────────────────────────────────────────────────────────
  TASK-001  high      S       ✅ done      session-abc    Setup structure
  TASK-002  high      M       🔄 progress  session-def    BaseRetriever interface
  TASK-003  high      L       ⏳ pending   —              PgVector integration
  TASK-004  high      L       🔒 blocked   —              ArangoDB integration

Progress: X/N done (XX%)
Unblocked & unassigned: TASK-003, ... ← ready to assign
```

## Reference
- Index file: `sdd/tasks/.index.json`
- SDD methodology: `sdd/WORKFLOW.md`
