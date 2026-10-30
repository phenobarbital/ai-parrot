# TASK-4919: KnowledgeResolver core — order, budget, trim, source protocol

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4914, TASK-4915
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, G3, §8 Q1. The resolver walks a fixed layer order, counts tokens, derives the budget from the
active model's window (single pool, `KNOWLEDGE_FRACTION = 0.15`, Q1), trims by `TRIM_ORDER` and never trims rules.
It is pure: same inputs → byte-identical serialized `KnowledgeContext`, no LLM (AC4). Source adapters are
injected through the `KnowledgeSource` protocol defined here; concrete adapters arrive in TASK-4920–TASK-4922.

The resolver also exposes the two hooks the KB fold-in (TASK-4923) needs: `has_handle(kind)` and `search_kb(...)`.
`search_kb` delegates to a bot method `_legacy_build_kb_context` that TASK-4923 extracts from
`AbstractBot._build_kb_context`; here it is called duck-typed and tested with a fake bot.

---

## Scope

- Create `knowledge/budget.py`: `KNOWLEDGE_FRACTION`, `knowledge_budget`, `sha256_revision`.
- Create `knowledge/sources/base.py`: the `KnowledgeSource` protocol.
- Create `knowledge/resolver.py`: `LAYER_ORDER`, `TRIM_ORDER`, `KnowledgeResolver` (`resolve`, `has_handle`,
  `search_kb`, `invalidate`).
- Write `test_resolver.py`.

**NOT in scope**: concrete sources (TASK-4920–TASK-4922), rendering (TASK-4918), touching `bots/abstract.py` (TASK-4923).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/knowledge/budget.py` | CREATE | Budget + revision helpers |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/base.py` | CREATE | `KnowledgeSource` protocol |
| `packages/ai-parrot/src/parrot/experts/knowledge/resolver.py` | CREATE | The resolver |
| `packages/ai-parrot/tests/experts/test_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.compaction.budget import resolve_window          # verified: parrot/memory/compaction/budget.py:61
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter   # verified: tokens.py:30,89
from parrot.experts.models import (ExpertBundle, KnowledgeContext, KnowledgeLayer, KnowledgeMode,
                                   KnowledgeSourceKind, KnowledgeSourceSpec)    # TASK-4914
from parrot.experts.rules import resolve_chain, rules_to_layer                  # TASK-4915
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/compaction/budget.py
MODEL_WINDOWS: Dict[str, int]                         # line 43 — prefix → window, e.g. "claude-": 200_000
def resolve_window(model: Optional[str]) -> int       # line 61
# packages/ai-parrot/src/parrot/memory/compaction/tokens.py
class TokenCounter(Protocol): def count(self, text: str) -> int   # lines 30-35
def get_default_counter() -> TokenCounter                          # line 89
```

### Does NOT Exist
- ~~`build_default_budget(model).knowledge`~~ — `ContextBudget` has no knowledge share; Q1 fixed the single pool
  `int(resolve_window(model) * KNOWLEDGE_FRACTION)` instead.
- ~~`AbstractBot._legacy_build_kb_context`~~ — does not exist yet; TASK-4923 creates it. Call it duck-typed only.
- ~~a new ContextVar~~ — AC16 forbids one; cache state lives on the resolver instance.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/budget.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/base.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/resolver.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_resolver.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/compaction/budget.py#resolve_window",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/tokens.py#TokenCounter",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/tokens.py#get_default_counter"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Order: sources may be registered in any order; output layers are sorted by `LAYER_ORDER` index, then by
  `source` string — determinism (AC4, AC5).
- Trim: while `sum(tokens of INLINE layers) > budget`, drop the **last** layer (within the layer group) of the
  first non-empty group in `TRIM_ORDER`; append it to `trimmed`. `rules` and `stage_input` are never dropped.
  If only untrimmable layers remain over budget, stop and keep them (log a warning).
- The rules layer comes from `rules_to_layer(resolve_chain(workspace, expert))`, not from a source adapter.
- `revision` is mandatory on every layer (AC6); retrieval layers carry `tokens=0`.

---

## Implementation Blueprint

### Steps (in order)
1. `budget.py` — *why*: Q1 decision, tiny and pure.
2. `sources/base.py` — *why*: the protocol every adapter implements.
3. `resolver.py` — *why*: AC4/AC5/AC6.

### `packages/ai-parrot/src/parrot/experts/knowledge/budget.py` (CREATE)
```python
"""Knowledge budget and revision helpers (FEAT-778 M4, §8 Q1)."""
from __future__ import annotations

import hashlib
from typing import Final

from parrot.memory.compaction.budget import resolve_window

KNOWLEDGE_FRACTION: Final[float] = 0.15


def knowledge_budget(model: str | None, *, fraction: float = KNOWLEDGE_FRACTION) -> int:
    """Single knowledge pool: int(resolve_window(model) * fraction)."""
    return int(resolve_window(model) * fraction)


def sha256_revision(data: bytes) -> str:
    """Hex sha256 — the `revision` of every file-backed layer."""
    return hashlib.sha256(data).hexdigest()
```

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/base.py` (CREATE)
```python
"""The protocol every knowledge source adapter implements (FEAT-778 M5)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.memory.compaction.tokens import TokenCounter


@runtime_checkable
class KnowledgeSource(Protocol):
    """Produces the layers of one KnowledgeSourceKind for one bundle."""

    kind: KnowledgeSourceKind

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """INLINE sources return content+tokens+revision; RETRIEVAL sources return a handle and tokens=0."""
        ...
```

### `packages/ai-parrot/src/parrot/experts/knowledge/resolver.py` (CREATE)
```python
"""Deterministic, budgeted knowledge resolution for an expert (FEAT-778 M4)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Sequence

from parrot.experts.knowledge.budget import knowledge_budget
from parrot.experts.knowledge.sources.base import KnowledgeSource
from parrot.experts.models import ExpertBundle, KnowledgeContext, KnowledgeLayer, KnowledgeMode
from parrot.experts.rules import resolve_chain, rules_to_layer
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter

LAYER_ORDER: Final[tuple[str, ...]] = ("rules", "tier1_shared", "tier1_expert", "tier2_shared", "tier2_expert",
                                       "adr", "stage_input", "retrieval")
TRIM_ORDER: Final[tuple[str, ...]] = ("tier1_shared", "tier1_expert", "adr", "tier2_shared", "tier2_expert")


class KnowledgeResolver:
    """Pure resolver over injected sources; keeps the last context for TASK-4923's KB hook."""

    def __init__(self, sources: Sequence[KnowledgeSource], *, counter: TokenCounter | None = None) -> None:
        self._sources = list(sources)
        self._counter = counter or get_default_counter()
        self.last_context: KnowledgeContext | None = None
        self.logger = logging.getLogger(__name__)

    async def resolve(self, expert: ExpertBundle, stage: str | None, workspace: Path | None, *,
                      model: str | None, budget_tokens: int | None = None) -> KnowledgeContext:
        """Layers in LAYER_ORDER, trimmed per TRIM_ORDER to the budget; rules/stage_input never trimmed."""
        budget = budget_tokens if budget_tokens is not None else knowledge_budget(model)
        layers: list[KnowledgeLayer] = [rules_to_layer(resolve_chain(workspace, expert), self._counter)]
        for spec in expert.manifest.knowledge:
            for source in self._sources:
                if source.kind == spec.source:
                    layers.extend(await source.layers(spec, expert, workspace=workspace, counter=self._counter))
        # FILL IN: sort by (LAYER_ORDER.index(layer.layer), layer.source); trim loop per Key Constraints — AC5
        trimmed: list[KnowledgeLayer] = []
        ctx = KnowledgeContext(expert=expert.manifest.name, stage=stage, budget_tokens=budget,
                               layers=layers, trimmed=trimmed)
        self.last_context = ctx
        return ctx

    def has_handle(self, kind: str) -> bool:
        """True when a source of this kind is registered (used by AbstractBot._build_kb_context, TASK-4923)."""
        return any(source.kind.value == kind for source in self._sources)

    async def search_kb(self, bot: Any, question: str, *, user_id: str | None = None,
                        session_id: str | None = None, ctx: Any = None) -> tuple[str, dict[str, Any]]:
        """Run the bot's legacy KB search and tag the metadata; same return shape as _build_kb_context."""
        kb_context, metadata = await bot._legacy_build_kb_context(question, user_id, session_id, ctx)
        metadata["knowledge_source"] = "resolver:kb"
        return kb_context, metadata

    def invalidate(self) -> None:
        """Drop the cached context (register_kb calls this, TASK-4923)."""
        self.last_context = None
```
**Why this shape**: the rules layer is injected by the resolver itself so no manifest can omit it; source
dispatch follows the manifest's `knowledge` list, so a bundle only gets the sources it declares.

### FILL IN checklist
- [ ] `resolve` — stable sort and trim loop; bounded by AC4, AC5.

---

## Acceptance Criteria

- [ ] AC4 — two `resolve()` runs over the same inputs serialize (`model_dump_json()`) identically; no LLM client is constructed.
- [ ] AC5 — layers follow `LAYER_ORDER`; over budget, trimming follows `TRIM_ORDER`, never touches `rules`, and every trimmed layer is in `trimmed`.
- [ ] AC6 (resolver part) — every emitted layer has a non-empty `revision`.
- [ ] `knowledge_budget("claude-x")` equals `int(200_000 * 0.15)`.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_resolver.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_resolver.py — fake sources returning fixed layers
def test_resolver_layer_order_is_fixed(): ...                         # FILL IN: register sources in reverse order
def test_resolver_trims_methodology_before_tier2_never_rules(): ...   # FILL IN
def test_resolver_is_deterministic(): ...                             # FILL IN
def test_knowledge_budget_from_model_window(): ...                    # FILL IN
def test_has_handle_and_search_kb(): ...                              # FILL IN: fake bot with _legacy_build_kb_context
def test_invalidate_clears_cache(): ...                               # FILL IN
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4919 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
