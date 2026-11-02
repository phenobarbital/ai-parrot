# TASK-4927: `ExpertKnowledgeToolkit` — knowledge search and ADR proposal tools

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4914
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, G6, AC9 (producer part). Two LLM-facing tools in the tools distribution:
`expert_knowledge_search` fans out over the context's retrieval handles (wiki namespace query + bookstore search),
`expert_propose_adr` turns a decision into an **inferred, unreviewed** ADR candidate through
`DecisionService.generate()`; acceptance stays a human `review()` and is never exposed as a tool.

---

## Scope

- Create `parrot_tools/experts/__init__.py` and `parrot_tools/experts/toolkit.py`.
- Create the test package `packages/ai-parrot-tools/tests/experts/` and `test_expert_toolkit.py` with stubs for the
  wiki toolkit, the bookstore toolkit and `DecisionService`.

**NOT in scope**: registering the toolkit on experts (TASK-4926), the `review` flow.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/experts/__init__.py` | CREATE | Export `ExpertKnowledgeToolkit` |
| `packages/ai-parrot-tools/src/parrot_tools/experts/toolkit.py` | CREATE | The toolkit |
| `packages/ai-parrot-tools/tests/experts/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot-tools/tests/experts/test_expert_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                       # verified: parrot/tools/toolkit.py:225
from parrot.knowledge.wiki.decisions.service import DecisionService     # verified: decisions/service.py:96
from parrot.experts.models import ExpertCapabilityError, ExpertManifest, KnowledgeContext   # TASK-4914
```

### Existing Signatures to Use
```python
# parrot/tools/toolkit.py
class AbstractToolkit:            # line 225 — public async methods become tools
    tool_prefix: str | None = None    # line 276 — "expert" → tool names "expert_<method>"
    prefix_separator: str = "_"
# parrot/knowledge/wiki/decisions/service.py
async def generate(self, target: str) -> GenerationResult   # line 389 — GenerationResult.decision_ids / reused (models.py:262)
# parrot_tools/wiki/toolkit.py
async def query(self, wiki_name: str, question: str, file_answer: bool = False, mode: str = "combined") -> dict   # line 373
# parrot/knowledge/bookstore/toolkit.py
async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3,
                 expand_related: bool = False) -> dict   # line 195
```

### Does NOT Exist
- ~~`AbstractToolkit.name`~~ — no `name` class attribute on toolkits; do not add one (the spec skeleton's `name = "experts"` is dropped).
- ~~`DecisionService.propose`~~ — the producer entry point is `generate(target)`.
- ~~a `review` tool~~ — never exposed (human-only).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/experts/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/experts/toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/experts/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/experts/test_expert_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService.generate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every public async method's docstring is the LLM-facing description — write it for the model.
- Search results carry `source` and `revision` of the handle they came from; a failing backend is reported in the
  result (`errors: [...]`), never raised.
- `propose_adr` returns `{"decision_ids": [...], "reused": [...], "origin": "inferred",
  "review_status": "unreviewed"}`; without `"write"` in `manifest.capabilities` it raises `ExpertCapabilityError`.

---

## Implementation Blueprint

### Steps (in order)
1. `toolkit.py`, then `__init__.py`, then tests.

### `packages/ai-parrot-tools/src/parrot_tools/experts/toolkit.py` (CREATE)
```python
"""Expert-facing tools: retrieval fan-out and ADR proposal (FEAT-778 M9)."""
from __future__ import annotations

from typing import Any

from parrot.experts.models import ExpertCapabilityError, ExpertManifest, KnowledgeContext
from parrot.tools.toolkit import AbstractToolkit


class ExpertKnowledgeToolkit(AbstractToolkit):
    """Search an expert's knowledge handles and propose ADRs for human review."""

    tool_prefix = "expert"

    def __init__(self, context: KnowledgeContext, manifest: ExpertManifest, *, wiki: Any = None,
                 bookstore: Any = None, decisions: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._context = context
        self._manifest = manifest
        self._wiki = wiki
        self._bookstore = bookstore
        self._decisions = decisions

    async def knowledge_search(self, question: str, top_k: int = 8) -> dict[str, Any]:
        """Search this expert's knowledge: its wiki namespace and the bookstore. Returns hits with their source."""
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for layer in self._context.retrieval_handles():
            handle = layer.handle or {}
            # FILL IN: wiki -> await self._wiki.query(wiki_name=handle["wiki_name"], question=question);
            # bookstore -> await self._bookstore.search(question, max_books=3); tag each with layer.source and
            # layer.revision; catch exceptions into `errors`; cap at top_k — bounded by spec M9
        return {"question": question, "results": results[:top_k], "errors": errors}

    async def propose_adr(self, target: str, rationale: str) -> dict[str, Any]:
        """Propose an architecture decision record for `target`; it is born inferred and unreviewed (human review accepts it)."""
        if "write" not in self._manifest.capabilities:
            raise ExpertCapabilityError(f"expert {self._manifest.name} lacks the 'write' capability")
        if self._decisions is None:
            raise ExpertCapabilityError("no DecisionService configured for this expert")
        result = await self._decisions.generate(target)
        return {"target": target, "rationale": rationale, "decision_ids": list(result.decision_ids),
                "reused": list(result.reused), "origin": "inferred", "review_status": "unreviewed"}
```

### `packages/ai-parrot-tools/src/parrot_tools/experts/__init__.py` (CREATE)
```python
"""Toolkits for domain experts (FEAT-778)."""
from .toolkit import ExpertKnowledgeToolkit

__all__ = ["ExpertKnowledgeToolkit"]
```

### FILL IN checklist
- [ ] `knowledge_search` — per-handle dispatch and error capture.

---

## Acceptance Criteria

- [ ] AC9 (producer part) — `expert_propose_adr` requires `write`, returns `origin="inferred"`, `review_status="unreviewed"`.
- [ ] Tool names are `expert_knowledge_search` and `expert_propose_adr`.
- [ ] A failing backend yields an `errors` entry, not an exception.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/experts/test_expert_toolkit.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/experts/test_expert_toolkit.py
def test_tool_names_are_prefixed(): ...                       # FILL IN
async def test_knowledge_search_fans_out(): ...               # FILL IN
async def test_knowledge_search_captures_backend_error(): ... # FILL IN
async def test_propose_adr_requires_write_capability(): ...   # FILL IN
async def test_propose_adr_returns_inferred_unreviewed(): ... # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4927 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: sonnet (native) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier gate and chunk merge-tier validation green (80 + 5 passed).

**Deviations from spec**: none
