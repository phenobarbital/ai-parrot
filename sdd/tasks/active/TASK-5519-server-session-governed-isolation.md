# TASK-5519: Server session paths never share governed entries or rows (M3)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5515
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (review finding efbd3899f28d). `_clone_agent_dm` copies loaded frames into a user manager, and `UserObjectsHandler.configure_dataset_manager` — the production PandasAgent chat path — shares the agent's DatasetEntry objects outright (`user_objects.py:342`).

---

## Scope

- `_clone_agent_dm`: for self-governed sources skip copying `_df` and `_column_types`.
- `configure_dataset_manager`: for self-governed sources build a fresh `DatasetEntry` around `request_scoped_copy(entry.source)` preserving registration settings; other kinds keep sharing.
- Tests in the existing clone test file and a new session-isolation test file.

**NOT in scope**: DatasetManager internals (TASK-5516/5518).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/datasets.py` | MODIFY | no frame copy for governed entries |
| `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` | MODIFY | fresh governed entries per session |
| `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py` | MODIFY | clone tests |
| `packages/ai-parrot-server/tests/handlers/test_semantic_dataset_session_isolation.py` | CREATE | chat-path isolation tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager  # verified: test_datasets_clone.py:11
from parrot.tools.dataset_manager.sources import request_scoped_copy     # verified: sources/__init__.py:31
from parrot.handlers.datasets import _clone_agent_dm                      # verified: test_datasets_clone.py:10
```

### Existing Signatures to Use
```python
# handlers/datasets.py
def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None   # line 48
    # DatasetEntry(...) built at lines 69-76; `if entry.loaded and entry.df is not None:` line 77
# handlers/user_objects.py
async def configure_dataset_manager(self, request_session, agent, agent_name=None) -> DatasetManager  # line 282
    # loop `for name, entry in agent_dm._datasets.items():` line 337; `user_dm._datasets[name] = entry` line 342
# DatasetEntry.__init__ kwargs (tool.py:223): name, description, source, metadata, is_active,
#   auto_detect_types, cache_ttl, no_cache, computed_columns, usage_guidance, protected
#   attributes: entry._computed_columns (list), entry.usage_guidance (dict)
```

### Does NOT Exist
- ~~a copy helper for DatasetEntry~~ — none exists; build the entry explicitly.
- ~~`evict_table_sources` covering other kinds~~ — it evicts only TableSource; do not rely on it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/datasets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/user_objects.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_datasets_clone.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_semantic_dataset_session_isolation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/datasets.py#_clone_agent_dm",
    "sym:packages/ai-parrot-server/src/parrot/handlers/user_objects.py#UserObjectsHandler.configure_dataset_manager"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Leave the agent's entry untouched; copy mutable config (`dict(...)`, `list(...)`).
- Copy no `_df`, no column types, no `unavailable_reason`.
- The fake source in tests must override `current_owner()` with a stable id: after TASK-5518 lands, a governed entry whose owner is None reads as not loaded.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/datasets.py:66-81` — the entry-building pattern to reuse.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Guard the frame copy in `_clone_agent_dm`.
2. Replace the shared assignment with a governed branch in `configure_dataset_manager`.
3. Write tests with an in-test self-governed double (owner fixed per test).

### `packages/ai-parrot-server/src/parrot/handlers/datasets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            if entry.loaded and entry.df is not None:' datasets.py)
# REPLACE that line (verified: datasets.py:77) with:
            governed = bool(entry.source is not None and getattr(entry.source, "self_governed", False))
            if not governed and entry.loaded and entry.df is not None:
# and guard the following `if entry.column_types:` (line 79) with `if not governed and entry.column_types:`
```

### `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                    user_dm._datasets[name] = entry' user_objects.py)
# REPLACE that line (verified: user_objects.py:342) with:
                    if getattr(entry.source, "self_governed", False):
                        # FEAT-880: never share a governed entry or its rows across sessions.
                        user_dm._datasets[name] = DatasetEntry(
                            name=name,
                            description=entry.description,
                            source=request_scoped_copy(entry.source),
                            metadata=dict(entry.metadata or {}),
                            is_active=entry.is_active,
                            auto_detect_types=entry.auto_detect_types,
                            cache_ttl=entry.cache_ttl,
                            no_cache=entry.no_cache,
                            computed_columns=list(entry._computed_columns),
                            usage_guidance={k: list(v) for k, v in (entry.usage_guidance or {}).items()},
                            protected=entry.protected,
                        )
                    else:
                        user_dm._datasets[name] = entry
# FILL IN: add the needed imports at module top (DatasetEntry, request_scoped_copy) — check what user_objects.py
#   already imports first.
```

### FILL IN checklist
- [ ] imports in user_objects.py.
- [ ] tests `test_clone_agent_dm_drops_self_governed_df` (append to the clone file), `test_configure_dataset_manager_isolates_self_governed_entries`, `test_configure_dataset_manager_preserves_existing_session`, `test_chat_session_governed_dataset_isolation` (new file) — bounded by spec §4 rows for M3.

---

## Acceptance Criteria

- [ ] `_clone_agent_dm` never copies a governed frame; other entries still copied
- [ ] `configure_dataset_manager` gives two new sessions distinct, unloaded governed entries with independent config
- [ ] A's rows never reach B's active dataframes or pandas namespace before B fetches; B's fetch/eviction leaves A's entry unchanged
- [ ] Ordinary entries keep today's sharing behavior; existing session managers are reused

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_datasets_clone.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_semantic_dataset_session_isolation.py -q`

---

## Test Specification

Build `UserObjectsHandler` the way existing server handler tests do (FILL IN: locate with `wikitoolkit query "UserObjectsHandler test"`); use a dict as `request_session`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug datasetmanager-semantic-source --feature-id FEAT-880`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/datasetmanager-semantic-source.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/datasetmanager-semantic-source.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH` set to the absolute `src` dirs of every changed package (worktree rule)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5519 datasetmanager-semantic-source verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
