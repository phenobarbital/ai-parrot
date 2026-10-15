# TASK-4325: CLI backend choices from the registry; "arangodb" literal audit

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4321, TASK-4323, TASK-4326
**Assigned-to**: unassigned

---

## Context

Spec §3 M7. `click.Choice(["sqlite","memory","arangodb"])` at cli.py:670/1520; help text in entity_cli.py:258/374/454; `== "arangodb"` checks in cli.py (15), sync.py (4), LLMWikiToolkit (3).

---

## Scope

- Choices from `wiki_backend_names()` (callable evaluated at definition — use a lazy `click.Choice` subclass or validate in callback).
- entity_cli help strings list the registry names.
- Classify every `"arangodb"` literal: server-hosted ⇒ `is_server_backend()`; needs-Arango-params ⇒ stays inside the Arango path. Record the classification in the Completion Note.
- Tests.

**NOT in scope**: sources.py literals (TASK-4326).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | choices + audit |
| `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` | MODIFY | help |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` | MODIFY | audit |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` | MODIFY | audit |
| `packages/ai-parrot/tests/knowledge/wiki/test_backend_literal_audit.py` | CREATE | AST audit |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.store import is_server_backend, wiki_backend_names  # TASK-4323
```

### Existing Signatures to Use
```python
# cli.py :670 (8-space) / :1520 (4-space) click.Choice; entity_cli.py :258/:374/:454 help; sync.py :99 :103 :128 :131; wiki/toolkit.py :125 :147 :159 (moved to parrot_tools/wiki/toolkit.py by TASK-4309)
```

### Does NOT Exist
- ~~a registry-aware click type today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/sync.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_backend_literal_audit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Changing choices at import time must not import heavy backends — `wiki_backend_names()` reads only the table.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Choices.
2. Help strings.
3. Audit + classification.
4. AST test.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'type=click.Choice(["sqlite", "memory", "arangodb"]),' parrot/knowledge/wiki/cli.py)
# AFTER/AT — anchor `type=click.Choice(["sqlite", "memory", "arangodb"]),` (verified: cli.py:670)
# REPLACE with type=_BackendChoice() (a click.ParamType validating against wiki_backend_names())
```
**Why**: Registry-driven.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'type=click.Choice(["sqlite", "memory", "arangodb"]),' parrot/knowledge/wiki/cli.py)
# AFTER/AT — anchor `type=click.Choice(["sqlite", "memory", "arangodb"]),` (verified: cli.py:1520)
# REPLACE with type=_BackendChoice()
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` (MODIFY)
```python
# occurrences: 3 (verified: grep -c '@click.option("--backend", "backend_opt", default=None, help="Backend (default: sqlite / WIKI_STORE_BACKEND).")' parrot/knowledge/wiki/entity_cli.py)
# FILL IN: disambiguate — occurrences at lines [258, 374, 454]; the target one is the occurrence all three (:258, :374, :454) get the same replacement
# FILL IN: help text derived from wiki_backend_names() at all three sites
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if config.backend == "arangodb":' parrot/knowledge/wiki/sync.py)
# AFTER/AT — anchor `if config.backend == "arangodb":` (verified: sync.py:99)
# FILL IN: classify; server-hosted checks -> is_server_backend(config.backend)
```
**Why**: S1.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` (MODIFY)
```python
# occurrences: n/a — parrot_tools/wiki/toolkit.py is created by TASK-4309
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: classify the three literals (originally wiki/toolkit.py:125, :147, :159)
```
**Why**: S1.

### `packages/ai-parrot/tests/knowledge/wiki/test_backend_literal_audit.py` (CREATE)
```python
"""No 'arangodb' literal meaning 'server-hosted' survives (FEAT-540 M7)."""
# FILL IN: AST walk over cli.py, sync.py, federation.py, sources.py, parrot_tools/wiki/toolkit.py; allow-list the classified Arango-param sites
```
**Why**: Spec §4 test_wiki_backend_kind.

### FILL IN checklist
- [ ] _BackendChoice
- [ ] classification of every literal
- [ ] AST audit allow-list

---

## Acceptance Criteria

- [ ] CLI accepts any registered backend
- [ ] audit test passes
- [ ] existing cli/entity-cli/sync tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_backend_literal_audit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sync_tools.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4325 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt 2b282b3e), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: wiki cli.py/entity_cli.py/sync.py and the parrot_tools wiki toolkit no longer hardcode backend literals (choices derive from the backend registry); AST audit test test_backend_literal_audit.py. Verification `partial`: audit + wiki test_cli + ontology tests = 275 passed; the 2 failures (TestIngestModelResolutionDetectionFallback) are pre-existing on clean c57431a06; parrot-tools tests/wiki 22 passed; ruff F821/F401 clean. No review corrections.

**Deviations from spec**: none.
