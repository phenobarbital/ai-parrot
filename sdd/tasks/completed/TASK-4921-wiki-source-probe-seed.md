# TASK-4921: WikiSource — namespace handle, probe and LLM-free seeding

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (`WikiSource`), G9, §8 Q2 (fail at load), §8 Q7(b) (seed from Tier-1 knowledge). Every expert has
a mandatory wiki source bound to the namespace `expert-<slug>`. The registry (TASK-4926) calls `probe()` per bundle,
`seed()` when the namespace is empty, and rejects the bundle if it is still empty.

**Task-time contract correction (verified at `9d5a6476b8`; the spec asked for this check in §7):**
`LLMWikiToolkit._store_for(name)` returns a separate scoped store **only** when a wiki federation is configured
and `name` is one of its namespaces (`_is_namespace`, `parrot_tools/wiki/toolkit.py:208-226`); otherwise it
silently returns the toolkit's single local store. A fresh install has no federation, so every expert would share
one store and `stats()` would count every expert's pages. Therefore:

- `probe()` counts only pages whose `concept_id` starts with `f"{namespace}/"` (`list_pages`, which every backend
  implements), never `stats()`;
- `seed()` writes `concept_id = f"{namespace}/{file.stem}"`, so pages stay attributable inside a shared store;
- "unresolvable" means `_store_for` raised, or returned `None`.

This keeps Q2 (fail at load) and works with and without a federation.

---

## Scope

- Create `sources/wiki.py` with `WikiSource`: `kind`, `store`, `store_for`, `probe`, `seed`, `layers`.
- Write `test_wiki_source.py` against an `InMemoryWikiStore` behind a fake toolkit.

**NOT in scope**: calling probe/seed during load (TASK-4926); downloading advisories (TASK-4929).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/wiki.py` | CREATE | `WikiSource` |
| `packages/ai-parrot/tests/experts/test_wiki_source.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord   # verified: wiki/store.py:697,433
from parrot.knowledge.wiki.file_store import InMemoryWikiStore           # verified: wiki/file_store.py:74 (tests only)
from parrot.experts.knowledge.budget import sha256_revision              # TASK-4919
from parrot.experts.models import (ExpertBundle, ExpertKnowledgeError, KnowledgeLayer, KnowledgeMode,
                                   KnowledgeSourceKind, KnowledgeSourceSpec)   # TASK-4914
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter   # verified: tokens.py:30,89
# LLMWikiToolkit is ONLY a TYPE_CHECKING import (ai-parrot-tools is a separate distribution):
#   if TYPE_CHECKING: from parrot_tools.wiki.toolkit import LLMWikiToolkit   # verified: parrot_tools/wiki/toolkit.py:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):    # line 433
    concept_id: str (min_length=1); node_id: Optional[str] = None; title: str = ""; category: str = "concept"
    summary: str = ""; body: str = ""; source_id: Optional[str] = None; token_count: int = 0
    origin: str = "ingest"; asserted_by: Optional[str] = None; updated_at: Optional[str] = None
    content_hash: Optional[str] = None; attrs: dict[str, str] = {}
class BaseWikiStore(ABC):           # line 697
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                     # line 744
    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                         origin: Optional[list[str]] = None) -> list[dict[str, Any]]    # line 768
    def _assert_writable(self) -> None                                                  # line 881 — read-only stores raise
# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py
class InMemoryWikiStore(BaseWikiStore):                                  # line 74
    def __init__(self, bundle_dir: str | Path, wiki_name: str = "") -> None   # line 91
# packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):              # line 48
    def _is_namespace(self, wiki_name: str) -> bool # line 208 — False when no federation
    def _store_for(self, wiki_name: str) -> BaseWikiStore   # line 215 — falls back to the local store
```

### Does NOT Exist
- ~~a public store accessor on `LLMWikiToolkit`~~ — only private `_store_for`; this module is the ONE place that calls it.
- ~~`LLMWikiToolkit.ingest_source` for seeding~~ — it runs `TwoStepIngester` (needs an LLM); seed with `upsert_pages`.
- ~~`BaseWikiStore.count_pages` / prefix filter on `list_pages`~~ — filter `concept_id` prefixes in Python.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/wiki.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_wiki_source.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py#LLMWikiToolkit._store_for"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `PROBE_LIMIT = 10_000` pages scanned by `probe()`; record the limit in a module constant and a docstring note.
- `seed()` wraps write failures (`_assert_writable` raising, any store exception) in `ExpertKnowledgeError` with
  reason text `wiki-not-writable` — the registry turns that into a skip reason.
- `layers()` returns one RETRIEVAL layer: `handle = {"toolkit": "wiki", "wiki_name": namespace, "scope":
  spec.scope, "documents": n}`, `tokens=0`, `revision = sha256_revision(json.dumps(handle, sort_keys=True))`.
  It raises `ExpertKnowledgeError` when `n == 0` (Q2) — it never warns.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor, `store`, `store_for` — *why*: one wrapper around the private `_store_for`.
2. `probe`, then `seed`, then `layers`.

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/wiki.py` (CREATE)
```python
"""Mandatory wiki source for an expert: namespace handle, probe and LLM-free seeding (FEAT-778 M5, G9)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Sequence

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, ExpertKnowledgeError, KnowledgeLayer, KnowledgeMode,
                                   KnowledgeSourceKind, KnowledgeSourceSpec)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter

if TYPE_CHECKING:
    from parrot_tools.wiki.toolkit import LLMWikiToolkit

PROBE_LIMIT: Final[int] = 10_000
_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


class WikiSource:
    """Binds an expert to `expert-<slug>`; pages are attributed by the `<namespace>/` concept_id prefix."""

    kind = KnowledgeSourceKind.WIKI

    def __init__(self, toolkit: "LLMWikiToolkit | Any", *, namespace: str,
                 counter: TokenCounter | None = None) -> None:
        self.toolkit = toolkit
        self.namespace = namespace
        self.counter = counter or get_default_counter()

    def store_for(self, wiki_name: str) -> BaseWikiStore:
        """Resolve a store (federated namespace or the local store); ExpertKnowledgeError when unresolvable."""
        try:
            store = self.toolkit._store_for(wiki_name)  # noqa: SLF001 — the only caller of the private API
        except Exception as exc:  # pylint: disable=broad-except
            raise ExpertKnowledgeError(f"wiki namespace {wiki_name!r} cannot be resolved: {exc}") from exc
        if store is None:
            raise ExpertKnowledgeError(f"wiki namespace {wiki_name!r} cannot be resolved")
        return store

    @property
    def store(self) -> BaseWikiStore:
        return self.store_for(self.namespace)

    async def probe(self) -> int:
        """Pages whose concept_id starts with '<namespace>/'; no LLM call."""
        prefix = f"{self.namespace}/"
        pages = await self.store.list_pages(limit=PROBE_LIMIT)
        return sum(1 for page in pages if str(page.get("concept_id", "")).startswith(prefix))

    async def seed(self, files: Sequence[Path], *, asserted_by: str) -> int:
        """One WikiPageRecord per file via upsert_pages; ExpertKnowledgeError('wiki-not-writable') on failure."""
        records: list[WikiPageRecord] = []
        # FILL IN: per file (sorted): text, title = first H1 or file.stem, WikiPageRecord(
        #   concept_id=f"{self.namespace}/{file.stem}", title=…, category="knowledge", body=text,
        #   summary=first paragraph (<= 280 chars), token_count=self.counter.count(text), origin="bundle",
        #   asserted_by=asserted_by, content_hash=sha256_revision(file.read_bytes())) — bounded by AC23
        try:
            return await self.store.upsert_pages(records) if records else 0
        except ExpertKnowledgeError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            raise ExpertKnowledgeError(f"wiki-not-writable: {self.namespace}: {exc}") from exc

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """One RETRIEVAL layer; raises ExpertKnowledgeError when the namespace holds zero pages (§8 Q2)."""
        documents = await self.probe()
        if documents == 0:
            raise ExpertKnowledgeError(f"empty-wiki-namespace: {self.namespace}")
        handle: dict[str, Any] = {"toolkit": "wiki", "wiki_name": self.namespace, "scope": spec.scope,
                                  "documents": documents}
        return [KnowledgeLayer(layer="retrieval", source=f"wiki:{self.namespace}", mode=KnowledgeMode.RETRIEVAL,
                               revision=sha256_revision(json.dumps(handle, sort_keys=True).encode()),
                               tokens=0, handle=handle)]
```
**Why this shape**: prefix attribution is the only scheme that is correct both with a federation (scoped store)
and without one (shared local store). Seeding never calls the LLM ingester.

### FILL IN checklist
- [ ] `seed` — record construction; bounded by AC23 (sha256 `content_hash`, `origin="bundle"`).

---

## Acceptance Criteria

- [ ] AC19 (source part) — an unresolvable namespace and a zero-page namespace both raise `ExpertKnowledgeError`.
- [ ] AC23 (source part) — `seed` writes one record per file with `origin="bundle"`, sha256 `content_hash`,
      `token_count > 0`; re-seeding unchanged files leaves the page count unchanged.
- [ ] `probe` ignores pages of other namespaces in a shared store.
- [ ] `LLMWikiToolkit.ingest_source` is never called (test asserts on a mock).
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_wiki_source.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_wiki_source.py
# fake toolkit: class FakeWiki: _store_for = lambda self, name: store; ingest_source = MagicMock()
def test_probe_counts_only_own_prefix(tmp_path): ...                 # FILL IN: two namespaces in one store
def test_seed_records_shape(tmp_path): ...                           # FILL IN
def test_seed_is_idempotent(tmp_path): ...                           # FILL IN
def test_wiki_source_unresolvable_and_empty_both_raise(tmp_path): ...  # FILL IN
def test_seed_on_read_only_store_raises_not_writable(tmp_path): ...  # FILL IN: store whose upsert raises
def test_layers_handle_shape(tmp_path): ...                          # FILL IN
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4921 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-sol (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier and chunk merge-tier validation green.

**Deviations from spec**: none
