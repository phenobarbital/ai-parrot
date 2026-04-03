---
description: Start working on an SDD task by name or ID
---

# /sdd-start — Start an SDD Task

Pick up a task from the SDD task index by ID or slug, validate it is ready, mark it in-progress,
and begin implementation following the task's instructions.

## Guardrails
- Do NOT start a task whose dependencies are not all `"done"`.
- Do NOT start a task that is already `"in-progress"` or `"done"` unless the user explicitly confirms.
- Update **both** `sdd/tasks/.index.json` and the task markdown file when changing status.

## Input
The user provides a task identifier after the command:
```
/sdd-start TASK-004
/sdd-start lyria-music-tests
```
Accept either the full ID (`TASK-NNN`) or the slug (`lyria-music-tests`).
If nothing is provided, run `/sdd-next` logic and ask the user to pick one.

## Steps

### 1. Resolve the Task
1. Read `sdd/tasks/.index.json`.
2. Match the user's input against `id` or `slug` (case-insensitive).
3. If no match is found, print available tasks and ask the user to pick one.

### 2. Validate Readiness
Check:
- **Status** must be `"pending"`. If `"in-progress"`, warn and ask to confirm resume; if `"done"`, abort.
- **Dependencies** — every task in `depends_on` must have status `"done"`.
  If any dependency is not done, print:
  ```
  ❌ TASK-<NNN> is blocked.
     Waiting on: TASK-<X> (<status>), TASK-<Y> (<status>)
     Resolve those first or run /sdd-status to see the full board.
  ```
  and STOP.

### 3. Mark In-Progress
1. Update `sdd/tasks/.index.json`:
   - Set `status` → `"in-progress"`.
   - Set `assigned_to` → current session/conversation ID.
2. Update the task markdown file header:
   - Set `**Status**: in-progress`.
   - Set `**Assigned-to**:` to the session/conversation ID.

### 4. Read Context
1. Read the **task file** at the path from the index.
2. Read the **spec file** referenced in the task header.
3. Extract:
   - Scope and implementation notes
   - Files to create/modify
   - Acceptance criteria
   - Test specification

### 5. Print Kickoff Summary
Output:
```
🚀 Starting TASK-<NNN>: <title>
   Feature: <feature>
   Priority: <priority>  |  Effort: <effort>
   Depends-on: <deps or "none">

📋 Scope:
   - <scope item 1>
   - <scope item 2>

📂 Files:
   - <file1> (CREATE)
   - <file2> (MODIFY)

✅ Acceptance Criteria:
   - <criterion 1>
   - <criterion 2>
```

> **Do NOT stop here.** The kickoff summary is informational only. Proceed immediately to Step 6.
### 6. Begin Implementation

> **CRITICAL — THIS IS THE CORE PURPOSE OF `/sdd-start`.**
> Do NOT stop after printing the kickoff summary.
> You MUST proceed to actually implement the task code NOW.
> The kickoff summary is just informational; the real work starts here.

Follow the **Agent Instructions** section in the task file:

1. Read the spec for full context.
2. **Verify the Codebase Contract (Anti-Hallucination Check):**
   Before writing ANY code, verify every entry in the task's `## Codebase Contract`:
   - `grep` or `read` each file listed in "Verified Imports" to confirm the imports exist.
   - `read` each file in "Existing Signatures" to confirm class/method signatures are accurate.
   - Check the "Does NOT Exist" section — do NOT reference anything listed there.
   - If any entry is stale, update the contract FIRST, then proceed with corrected references.
   - **NEVER guess an import or attribute. If unsure, verify with `grep` or `read` first.**
3. **Actually write the code** — create/modify the files listed in the task scope.
   Use ONLY the imports and signatures from the verified Codebase Contract.
4. Run linting (`ruff check`) and fix any issues.
5. Run the acceptance-criteria tests (`pytest` commands from the task).
6. Verify **all** acceptance criteria are met.
6. On completion, move the task file to `sdd/tasks/completed/TASK-<NNN>-<slug>.md`.
7. Update `sdd/tasks/.index.json` → `"done"`.
8. Fill in the **Completion Note** section of the task file.

**⚠ STOP condition**: Only stop (ask the user) if:
- A dependency is missing or broken.
- The spec is ambiguous and you need clarification.
- Tests are failing and you cannot determine the fix.

Otherwise, keep going until the task is **done**.

## Reference
- Index file: `sdd/tasks/.index.json`
- Task template: `sdd/templates/task.md`
- SDD methodology: `sdd/WORKFLOW.md`
