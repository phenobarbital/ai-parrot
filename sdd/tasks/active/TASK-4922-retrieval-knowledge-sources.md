# TASK-4922: Retrieval sources — bookstore, GraphIndex, legacy KB

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (retrieval adapters), G4, U5. Three adapters that emit only a RETRIEVAL handle (no content, no
tokens): the bookstore (`topics`/`scope` from the manifest), GraphIndex (L2 retrieval request parameters) and the
legacy KB list of a bot (`LegacyKBSource`, U5 fold-in — the actual search stays in the bot, TASK-4923). The handles
are what `expert_knowledge_search` (TASK-4927) and the KB hook use later.

---

## Scope

- Create `sources/bookstore.py` (`BookstoreSource`), `sources/graphindex.py` (`GraphIndexSource`),
  `sources/kb.py` (`LegacyKBSource`).
- Write `test_sources_retrieval.py`.

**NOT in scope**: executing a retrieval (the toolkit does that, TASK-4927); modifying `AbstractBot` (TASK-4923).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/bookstore.py` | CREATE | Bookstore handle |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/graphindex.py` | CREATE | GraphIndex handle |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/kb.py` | CREATE | Legacy KB handle |
| `packages/ai-parrot/tests/experts/test_sources_retrieval.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.experts.knowledge.budget import sha256_revision   # TASK-4919
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)       # TASK-4914
from parrot.memory.compaction.tokens import TokenCounter      # verified: tokens.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
self.knowledge_bases: List[AbstractKnowledgeBase] = []   # line 583 — each kb has .name and .priority
# packages/ai-parrot/src/parrot/knowledge/retrieval/models.py
class RetrievalBudget(BaseModel)   # line 320 — deadline_ms, max_tokens, max_llm_calls
class RetrievalRequest(BaseModel)  # line 345 — query, workspace, budget
```
The handles here are plain dicts describing what to query; this task does NOT build a `RetrievalRequest`
(there is no query at resolve time). Record the intended request fields in the GraphIndex handle only.

### Does NOT Exist
- ~~`BookstoreToolkit.topics_filter`~~ — the toolkit has no topic filter; the handle carries `scope` for the caller.
- ~~`AbstractBot.knowledge_resolver`~~ — not on the base class; `LegacyKBSource` receives the bot explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/bookstore.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/graphindex.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/kb.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_sources_retrieval.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/retrieval/models.py#RetrievalRequest",
    "sym:packages/ai-parrot/src/parrot/knowledge/retrieval/models.py#RetrievalBudget"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every handle-only layer: `layer="retrieval"`, `mode=RETRIEVAL`, `tokens=0`,
  `revision = sha256_revision(json.dumps(handle, sort_keys=True).encode())` (AC6).
- `LegacyKBSource` returns **no** layer when the bot has no knowledge bases (nothing to retrieve).

---

## Implementation Blueprint

### Steps (in order)
1. Write the three adapters (same shape), then the tests.

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/bookstore.py` (CREATE)
```python
"""Bookstore retrieval handle for an expert (FEAT-778 M5)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)
from parrot.memory.compaction.tokens import TokenCounter


class BookstoreSource:
    """handle = {"toolkit": "bookstore", "scope": spec.scope}."""

    kind = KnowledgeSourceKind.BOOKSTORE

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        handle: dict[str, Any] = {"toolkit": "bookstore", "scope": spec.scope}
        return [KnowledgeLayer(layer="retrieval", source="bookstore", mode=KnowledgeMode.RETRIEVAL, tokens=0,
                               revision=sha256_revision(json.dumps(handle, sort_keys=True).encode()), handle=handle)]
```

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/graphindex.py` (CREATE)
```python
"""GraphIndex (L2) retrieval handle for an expert (FEAT-778 M5)."""
from __future__ import annotations

# FILL IN: same imports/shape as bookstore.py; class GraphIndexSource, kind = KnowledgeSourceKind.GRAPHINDEX,
# handle = {"toolkit": "graphindex", "scope": spec.scope, "workspace": str(workspace) if workspace else None,
#           "budget": {"max_tokens": 4000, "max_llm_calls": 0}} — bounded by AC6 (revision from the handle)
```

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/kb.py` (CREATE)
```python
"""Legacy knowledge-base list as a retrieval handle — the U5 fold-in (FEAT-778 M5)."""
from __future__ import annotations

# FILL IN: same imports/shape; class LegacyKBSource(bot), kind = KnowledgeSourceKind.KB,
# handle = {"toolkit": "kb", "names": [kb.name for kb in bot.knowledge_bases]} (abstract.py:583);
# return [] when bot.knowledge_bases is empty — bounded by AC11 (the search itself stays in the bot)
```

### FILL IN checklist
- [ ] `graphindex.py` — handle fields.
- [ ] `kb.py` — empty-list case.

---

## Acceptance Criteria

- [ ] Each adapter emits RETRIEVAL layers with `tokens == 0` and a deterministic `revision` (AC6).
- [ ] `LegacyKBSource` lists KB names in the bot's priority order and returns `[]` without KBs.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_sources_retrieval.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_sources_retrieval.py
def test_bookstore_handle_carries_scope(): ...        # FILL IN
def test_graphindex_handle_shape(tmp_path): ...       # FILL IN
def test_legacy_kb_handle_names(): ...                # FILL IN: fake bot with two kbs
def test_legacy_kb_without_kbs_is_empty(): ...        # FILL IN
def test_revisions_are_deterministic(): ...           # FILL IN
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4922 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
