---
description: Decompose an approved spec into SDD Task Artifacts
---

# /sdd-task — Generate Task Artifacts from a Spec

Read an approved Feature Specification and decompose it into discrete, self-contained Task Artifacts
that can be independently picked up and executed.

## Guardrails
- The spec MUST have `status: approved` before generating tasks. If it is `draft` or `review`, remind the user to approve it first.
- Do NOT implement any code — this workflow only produces task markdown files and the index.
- Each task must be **atomic**, **bounded**, and **testable**.
- Every task must clearly define its **acceptance criteria** and **dependency pre-requisites**.

## Steps

### 1. Read the Spec
Read the spec file provided by the user (e.g., `sdd/specs/<feature>.spec.md`).
Extract:
- Feature name
- Module breakdown (Section 3)
- Acceptance criteria (Section 5)
- Test specification (Section 4)
- Implementation notes (Section 6)

### 2. Determine Task Numbering
- Check `sdd/tasks/.index.json` for existing tasks.
- Continue the numbering sequence (e.g., if highest is TASK-007, start at TASK-008).
- If no index exists, start at TASK-001.

### 3. Decompose into Tasks
Map each module from the spec's Module Breakdown (Section 3) into one or more tasks.

For each task, determine:
- **Title**: concise imperative description (e.g., "Implement BaseRetriever interface")
- **Priority**: `high` | `medium` | `low`
- **Estimated effort**: `S` (< 2h) | `M` (2-4h) | `L` (4-8h) | `XL` (> 8h)
- **Dependencies**: which other TASK-IDs must be completed first (or `none`)
- **Scope**: exactly what this task implements — nothing more
- **NOT in scope**: things that belong to other tasks
- **Files to create/modify**: concrete file paths
- **Codebase contract**: verified imports, signatures, and anti-hallucination entries
- **Implementation notes**: patterns to follow, references in codebase
- **Acceptance criteria**: how to verify this task is done
- **Test specification**: minimal test scaffold the agent must make pass

**CRITICAL — Codebase Contract per Task (Anti-Hallucination):**
For EACH task, you MUST populate its `## Codebase Contract` section:

1. **Extract from the spec's Section 6 (Codebase Contract)**: copy the verified imports,
   signatures, and "Does NOT Exist" entries relevant to THIS specific task.
2. **Verify freshness**: `read` or `grep` each referenced file to confirm accuracy.
3. **Add task-specific references**: if the task touches files not in the spec's
   contract, read those files now and add their signatures.
4. **Include the "Does NOT Exist" section**: list plausible-sounding things that
   an agent might assume exist but don't.

**Quality bar**: A task without a populated Codebase Contract section is incomplete.

### 4. Build the Dependency Graph
Order tasks so that:
- Foundation tasks (interfaces, base classes) come first.
- Tasks that can run in parallel share the same depth level.
- Integration/validation tasks come last.

Print the dependency tree:
```
TASK-001 (base interface)
    ├── TASK-002 (impl A)    ← parallel after 001
    ├── TASK-003 (impl B)    ← parallel after 001
    └── TASK-004 (integration) ← waits for 002 + 003
```

### 5. Create Task Files
1. Ensure `sdd/tasks/active/` directory exists (create if needed).
2. Read the task template at `sdd/templates/task.md`.
3. For each task, create `sdd/tasks/active/TASK-<NNN>-<slug>.md` using the template, filled with the decomposed information.

### 6. Create/Update the Task Index
Create or update `sdd/tasks/.index.json` with the schema:
```json
{
  "feature": "<feature-name>",
  "spec": "sdd/specs/<feature>.spec.md",
  "created_at": "<ISO-8601 timestamp>",
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "slug": "<slug>",
      "title": "<title>",
      "status": "pending",
      "priority": "high|medium|low",
      "effort": "S|M|L|XL",
      "depends_on": ["TASK-X"],
      "assigned_to": null,
      "file": "sdd/tasks/active/TASK-<NNN>-<slug>.md"
    }
  ]
}
```

### 7. Output Summary
Print:
```
✅ Generated <N> tasks from spec: sdd/specs/<feature>.spec.md

  ID        Priority  Effort  Depends-on    Title
  ───────────────────────────────────────────────────
  TASK-001  high      S       none          <title>
  TASK-002  high      M       TASK-001      <title>
  ...

Dependency graph:
  <tree from step 4>

Next: Run /sdd-status to see the full status board.
      Assign tasks to agents or start with /sdd-next.
```

## Reference
- Task template: `sdd/templates/task.md`
- Index schema: `sdd/WORKFLOW.md` (section "Task Index Schema")
- Completed tasks go to: `sdd/tasks/completed/`
