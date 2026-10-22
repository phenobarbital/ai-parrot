# TASK-4305: Wiki triage and inbox consumers typed to LLMCaller

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4302
**Assigned-to**: unassigned

---

## Context

Spec §3 M2. `wiki/triage.py:42` and `wiki/inbox/{classify,links,processor}.py` import `PageIndexLLMAdapter` at module level only to annotate; that pulls pageindex adapters into plain wiki paths.

---

## Scope

- Replace the four module-level `PageIndexLLMAdapter` imports with `LLMCaller` (runtime) or a `TYPE_CHECKING` import.
- Keep `processor.py`'s pydantic `SkipValidation[...]` fields working (use `SkipValidation[LLMCaller]`).
- Test: each module imports without loading `parrot.knowledge.pageindex.llm_adapter`; triage/inbox run with an `LLMCaller` double.

**NOT in scope**: `wiki/runtime.py` adapter construction and `llm_resolve.py` (framework factories stay lazy there; TASK-4311 touches llm_resolve).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY | LLMCaller |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` | MODIFY | LLMCaller |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` | MODIFY | LLMCaller |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` | MODIFY | LLMCaller |
| `packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py` | CREATE | import + double tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import LLMCaller  # TASK-4302
```

### Existing Signatures to Use
```python
# triage.py:42 import; NoveltyScorer :67 (grounding_evaluator :90); IngestTriageRouter :243
# inbox/classify.py:9 import; __init__(self, adapter: PageIndexLLMAdapter, taxonomy, *, max_chars=24_000) :117
# inbox/links.py:6 import; adapter: PageIndexLLMAdapter | None :36
# inbox/processor.py:15 import; light_adapter/heavy_adapter: SkipValidation[PageIndexLLMAdapter] :58-59
```

### Does NOT Exist
- ~~any use of `ask_with_finish_info` in these modules (verify with grep before narrowing)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/triage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#NoveltyScorer"
  ]
}
```

---

## Implementation Notes

If any of these modules calls `ask_with_finish_info`, stop: `LLMCaller` deliberately omits it — report instead of widening the Protocol.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. grep the four modules for adapter method calls — *why*: confirm they stay within ask/ask_structured/ask_json.
2. Swap imports/annotations — *why*: G2.
3. Add the test — *why*: prove the adapter module is no longer loaded.

### `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter' parrot/knowledge/wiki/triage.py)
# AFTER/AT — anchor `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` (verified: triage.py:42)
# REPLACE with:
from parrot.knowledge.graphindex.protocols import LLMCaller
# FILL IN: change every `PageIndexLLMAdapter` annotation in this module to `LLMCaller`
```
**Why**: Protocol module is stdlib-only.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter' parrot/knowledge/wiki/inbox/classify.py)
# AFTER/AT — anchor `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` (verified: classify.py:9)
# REPLACE with:
from parrot.knowledge.graphindex.protocols import LLMCaller
# FILL IN: :117 `adapter: LLMCaller`
```
**Why**: Same swap.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter' parrot/knowledge/wiki/inbox/links.py)
# AFTER/AT — anchor `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` (verified: links.py:6)
# REPLACE with:
from parrot.knowledge.graphindex.protocols import LLMCaller
# FILL IN: :36 `adapter: LLMCaller | None`
```
**Why**: Same swap.

### `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter' parrot/knowledge/wiki/inbox/processor.py)
# AFTER/AT — anchor `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` (verified: processor.py:15)
# REPLACE with:
from parrot.knowledge.graphindex.protocols import LLMCaller
# FILL IN: :58-59 `SkipValidation[LLMCaller]`
```
**Why**: `SkipValidation` keeps pydantic from validating a Protocol type.

### `packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py` (CREATE)
```python
"""Wiki triage/inbox depend on LLMCaller, not the PageIndex adapter (FEAT-540 M2)."""
import pytest

MODULES = ["parrot.knowledge.wiki.triage", "parrot.knowledge.wiki.inbox.classify", "parrot.knowledge.wiki.inbox.links", "parrot.knowledge.wiki.inbox.processor"]


@pytest.mark.parametrize("module", MODULES)
def test_module_does_not_load_adapter(module: str) -> None:
    # FILL IN: run_import_probe(module) and assert 'parrot.knowledge.pageindex.llm_adapter' not loaded
    ...
```
**Why**: Absence check via the fresh-interpreter probe.

### FILL IN checklist
- [ ] annotation swaps in each module
- [ ] probe-based test body

---

## Acceptance Criteria

- [ ] none of the four modules imports `parrot.knowledge.pageindex.llm_adapter` at module level
- [ ] existing triage/inbox tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_llmcaller_consumers.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4305 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: native sonnet, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: Wiki triage/inbox consumers typed to LLMCaller instead of PageIndexLLMAdapter + test_llmcaller_consumers.py (4 passed). The coder's final report was an empty placeholder, so the orchestrator reviewed the full diff and ran the test itself. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings show no failure absent from the clean origin/dev baseline (52 known reds).

**Deviations from spec**: none
