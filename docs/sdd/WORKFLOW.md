# AI-Parrot SDD Workflow for Claude Code

## Overview

This document defines the **Spec-Driven Development (SDD)** methodology for AI-Parrot,
optimized for Claude Code with multi-agent task distribution.

The key idea: specifications are the Single Source of Truth (SSOT). Claude Code agents
consume spec documents and produce **Task Artifacts** — discrete, self-contained files
in `tasks/active/` that can be independently picked up and executed by any Claude Code
agent in parallel.

---

## The SDD Lifecycle (Claude Code Edition)

```
[Human] Feature Spec → [Agent: Planner] Task Artifacts → [Agents: Executors] Code → [Agent: Reviewer] Validation
           ↑                                                                                    |
           └────────────────────────── Feedback Loop ───────────────────────────────────────────┘
```

### Phase 1 — Feature Specification (Human)
Engineer writes a `docs/sdd/specs/<feature>.spec.md` describing:
- Business requirements and motivation
- Architectural design decisions
- Module boundaries and interfaces
- Acceptance criteria

Use `/sdd-spec` to scaffold the spec template.

### Phase 2 — Task Generation (Claude Code Planner Agent)
Run `/sdd-task <spec-file>` to decompose the spec into Task Artifacts.

Each task is written to `tasks/active/TASK-<id>-<slug>.md`.
The index `tasks/.index.json` is updated with task metadata.

Tasks are designed to be:
- **Atomic** — completable independently
- **Bounded** — clear scope, no ambiguity
- **Testable** — every task includes its own test criteria
- **Assignable** — formatted so any Claude Code agent can start immediately

### Phase 3 — Task Execution (Claude Code Executor Agents)
Each executor agent picks up a task file:
```bash
# In a new Claude Code session:
claude "Read tasks/active/TASK-003-pgvector-loader.md and implement it"
```

Tasks declare their dependencies, so agents know what must be done first.

### Phase 4 — Validation (Claude Code Reviewer Agent)
After execution, tasks move to `tasks/completed/`.
A reviewer agent validates against the Test Specification.

---

## Task Artifact Format

Every task file (`tasks/active/TASK-<NNN>-<slug>.md`) follows this structure:

```markdown
# TASK-<NNN>: <Title>

**Feature**: <parent feature name>
**Spec**: docs/sdd/specs/<feature>.spec.md
**Status**: [ ] pending | [ ] in-progress | [x] done
**Priority**: high | medium | low
**Depends-on**: TASK-<X>, TASK-<Y>   (or "none")
**Assigned-to**: (agent session ID or "unassigned")

## Context
Brief explanation of why this task exists and how it fits the feature.

## Scope
Exactly what this task must implement. Be precise.

## Files to Create/Modify
- `parrot/path/to/file.py` — description
- `tests/path/to/test_file.py` — unit tests

## Implementation Notes
Technical guidance for the agent: patterns to follow, existing code to reference,
gotchas, constraints.

## Reference Code
Existing patterns in the codebase the agent should follow:
- See `parrot/loaders/base.py` for BaseLoader pattern
- See `parrot/bots/orchestration/crew.py` for DAG execution pattern

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All tests pass: `pytest tests/path/ -v`

## Test Specification
```python
# Minimal test scaffold the agent must make pass
def test_feature_does_x():
    ...

def test_feature_handles_edge_case():
    ...
```

## Output
When complete, the agent must:
1. Move this file to `tasks/completed/`
2. Update `tasks/.index.json` status to "done"
3. Add a brief completion note below

### Completion Note
(Agent fills this in when done)
```

---

## Task Index Schema (`tasks/.index.json`)

```json
{
  "feature": "feature-name",
  "spec": "docs/sdd/specs/feature-name.spec.md",
  "created_at": "ISO-8601",
  "tasks": [
    {
      "id": "TASK-001",
      "slug": "base-loader-interface",
      "title": "Define BaseLoader abstract interface",
      "status": "done",
      "priority": "high",
      "depends_on": [],
      "assigned_to": null,
      "file": "tasks/completed/TASK-001-base-loader-interface.md"
    },
    {
      "id": "TASK-002",
      "slug": "pgvector-store",
      "title": "Implement PgVector store integration",
      "status": "in-progress",
      "priority": "high",
      "depends_on": ["TASK-001"],
      "assigned_to": "session-abc123",
      "file": "tasks/active/TASK-002-pgvector-store.md"
    }
  ]
}
```

---

## Parallelism Rules

Claude Code agents can work in parallel when tasks have no shared dependencies:

```
TASK-001 (base interface)
    ├── TASK-002 (pgvector)    ← parallel after 001
    ├── TASK-003 (arangodb)    ← parallel after 001
    └── TASK-004 (embeddings)  ← parallel after 001
            └── TASK-005 (rag-pipeline) ← waits for 002, 003, 004
```

A Claude Code agent should **never start a task** if its `depends_on` tasks
are not in `tasks/completed/`.

---

## Commands Reference

| Command | Description |
|---|---|
| `/sdd-spec` | Scaffold a new Feature Specification |
| `/sdd-task <spec.md>` | Decompose a spec into Task Artifacts |
| `/sdd-status` | Show task index status summary |
| `/sdd-next` | Suggest next unblocked tasks to assign |

---

## Quality Rules for Agents

1. **Never modify files outside the task scope** — respect boundaries
2. **Follow existing patterns** — reference code mentioned in the task
3. **Write tests first** — TDD approach per task
4. **Update the index** — always update `.index.json` on completion
5. **Small commits** — one task = one logical commit
6. **Ask via the spec** — if unclear, note the ambiguity in the completion note
   and let the Planner agent refine the spec for the next iteration
