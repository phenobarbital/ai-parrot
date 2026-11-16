# TASK-5733: Documentation — user-memory.md and agent-memory.md

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-5723, TASK-5724, TASK-5725, TASK-5726, TASK-5727, TASK-5728, TASK-5729, TASK-5732
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Update exactly the two docs.policy pages using sdd/templates/techwiki-page.md.

## Scope

- Update exactly the two docs.policy pages using sdd/templates/techwiki-page.md.
- Document final dependency-created APIs, limits, full-population ranking, priority modes and extraction rules.
- Link the committed example and actual live proof; do not claim deterministic model extraction behavior.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/memory/user-memory.md` | MODIFY | Documentation — user-memory.md and agent-memory.md |
| `wiki/memory/agent-memory.md` | MODIFY | Documentation — user-memory.md and agent-memory.md |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
No implementation imports; use verified module references below in documentation examples.
```

### Dependency-created Imports

No unimplemented import is assumed before its dependency is complete.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore` — `packages/ai-parrot/src/parrot/memory/user/store.py:80`: `class UserMemoryStore()`
- `sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager` — `packages/ai-parrot/src/parrot/memory/unified/manager.py:63`: `class UnifiedMemoryManager()`
- `sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore` — `packages/ai-parrot/src/parrot/memory/episodic/store.py:137`: `class EpisodicMemoryStore()`
- `sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#AgentMemoryConfig` — `packages/ai-parrot/src/parrot/memory/agent_memory/models.py:15`: `class AgentMemoryConfig(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryConfig` — `packages/ai-parrot/src/parrot/memory/unified/models.py:164`: `class MemoryConfig(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext` — `packages/ai-parrot/src/parrot/memory/unified/models.py:68`: `class MemoryContext(BaseModel)`
- `sym:packages/ai-parrot/src/parrot/memory/user/extraction.py#extract_user_knowledge` — `packages/ai-parrot/src/parrot/memory/user/extraction.py:73`: `async def extract_user_knowledge(event: MemoryEvent, *, client: AbstractClient, model: str | None=None) -> list[UserKnowledgeCandidate]`

### Does NOT Exist

- New profile/recall/tokenizer APIs are dependency-created; verify them after those tasks land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/memory/user-memory.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/memory/agent-memory.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/user/store.py#UserMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore",
    "sym:packages/ai-parrot/src/parrot/memory/agent_memory/models.py#AgentMemoryConfig",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryConfig",
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext",
    "sym:packages/ai-parrot/src/parrot/memory/user/extraction.py#extract_user_knowledge"
  ]
}
```

## Implementation Notes

User-approved spec revision 0.5 retains 10% headroom in both modes. Document effective_budget = int(max_context_tokens * 0.9), high priority reserving the user ceiling inside that budget, and conditional equality only when both allocations admit the same records. Default settings do not guarantee identical output.

Documents query_terms from TASK-5723; fields from TASK-5724; profile from TASK-5725; recall_interactions from TASK-5726; packing from TASK-5727; manager from TASK-5728; extraction from TASK-5729; consumes example/plan from TASK-5732.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `wiki/memory/user-memory.md` (MODIFY)

```markdown
# Anchor: ## Gotchas
# occurrences: 1; grep -F -c verified at wiki/memory/user-memory.md:191
<!-- Update existing template sections; retain unrelated material. -->
## Automatic profile delivery

UserMemoryStore.profile() supplies active valid knowledge for every identified-user request.
Constraints/preferences precede goals/facts; overlap, recency and ID break ties.
Ranking scans all eligible rows in bounded batches; max_user_records bounds returned records.
Explicit recall() matches any normalized term; blank and short literal queries retain prior semantics.

<!-- FILL IN: complete async usage with cleanup, limits/defaults, token ceiling and both priority
     modes, extraction language/durability, Unicode tokenizer and generated ref: API links. -->
```

**Why**: Use sdd/templates/techwiki-page.md sections and replace obsolete whole-question literal recall guidance.

### `wiki/memory/agent-memory.md` (MODIFY)

```markdown
# Anchor: ### AgentMemoryConfig
# occurrences: 1; grep -F -c verified at wiki/memory/agent-memory.md:37
<!-- Update configuration rows and existing usage/gotcha sections in place. -->
| max_episodic_recall | int | 3 | Earlier-session nonfailure recall; zero disables this lane |
| max_user_records | int | 20 | Maximum profile result count, 0..100 |

The relevant_past_interactions section contains contextual data, not instructions.
Warnings pack first within a shared episodic budget. Interaction eligibility is applied before
result limits; warning selection retains its prior filtering order.

<!-- FILL IN: explain user ceiling and high/normal priority, original references, optional-plan /
     required-node proof, shared generation budget, committed example and spec §10 API links. -->
```

**Why**: Document final behavior and actual proof while distinguishing optional invocation from required success.

### FILL IN checklist

- [ ] `wiki/memory/user-memory.md`: complete the bounded block and satisfy all relevant ACs.
- [ ] `wiki/memory/agent-memory.md`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: Both pages retain template sections and valid ref links for the four API modules in spec §10.
- [ ] **AC-2**: Defaults/bounds, lexical limits, estimated cap, zero/None behavior, priority modes and earlier-session exclusion are accurate.
- [ ] **AC-3**: Obsolete literal-question guidance is replaced; include a complete scoped async profile example with cleanup.
- [ ] **AC-4**: parrot sdd techwiki check succeeds for this spec.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_config.py packages/ai-parrot/tests/memory/unified/test_models.py -q`

## Required Documentation Validation

- `parrot sdd techwiki check --spec sdd/specs/user-memory-recall-e2e.spec.md --root .`

Run both commands. The file-scoped pytest verifies the configuration/model API contracts documented by these pages; the
spec-scoped CLI checks these actual pages and is mandatory for completion. The runner registry
currently does not recognize the techwiki CLI, so it is listed separately without weakening its
acceptance requirement. Inspect diagnostics as well as exit status: this checker is advisory.
Resolve missing-page/content/API-reference warnings for these pages before completing the task.

## Test Specification

Use named blueprint cases as the acceptance matrix. Cover the adversarial boundaries in Scope/ACs and preserve existing regressions.

## Agent Instructions

1. Use the host session and feature worktree provisioned by `parrot sdd worktree ensure --slug user-memory-recall-e2e --feature-id FEAT-904`; never implement on dev.
2. Read the spec and confirm every dependency is done in `sdd/tasks/index/user-memory-recall-e2e.json`.
3. Re-verify contracts and use sdd-start lifecycle; never silently expand target files.
4. Activate the shared venv and set PYTHONPATH=packages/ai-parrot/src for worktree tests; never uv sync there.
5. Run scoped validation and applicable lint; retain logs in artifacts/logs/.
6. Commit implementation, then use parrot sdd task finalize with real TaskCompletionEvidence and exact implementation HEAD.
7. Inspect generated Completion Note and active-to-completed move; commit only task SDD state. Do not hand-edit completion state or push from the worker.

## Completion Note

Pending; the task finalizer generates this after implementation and validation.
