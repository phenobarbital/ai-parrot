# TASK-1573: Offline PageIndex builder (`build_odoo_pageindex.py`)

**Feature**: FEAT-240 — Odoo PageIndex Documentation Agent
**Spec**: `sdd/specs/odoo-pageindex-documentation-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1572
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec. Builds the documentation PageIndex from the
Odoo 16/18/19 PDFs produced by TASK-1572, organised as **one tree per Odoo version**
(`odoo_16`, `odoo_18`, `odoo_19`), persisted to
`storage_dir = agents/odoo_agent/documentation/` (must match TASK-1574). Resolves G2 /
AC4 (ingestion half). This is an OFFLINE one-time/periodic job — never on the
request path.

---

## Scope

- Add `scripts/odoo_agent/build_odoo_pageindex.py` that:
  1. Constructs a `PageIndexLLMAdapter` over a Google client + a lightweight model
     for summaries.
  2. Constructs a `PageIndexToolkit(adapter=..., storage_dir="agents/odoo_agent/documentation/")`.
  3. Creates **one tree per version**: `odoo_16`, `odoo_18`, `odoo_19`.
  4. For each version PDF under `agents/odoo_agent/documentation/<version>/`, calls
     `toolkit.import_pdf(tree_name=<odoo_NN>, pdf_path,
     with_summaries=True, with_doc_description=True)` — no `parent_node_id` (each version
     is its own tree; the PDF already contains that version's CLI reference).
  5. Persists the trees to the configured `storage_dir`.
- Idempotent: re-running must not duplicate trees (check `list_trees()` first).
- Unit tests with `import_pdf` mocked (no real LLM / PDF needed).

**NOT in scope**: generating the PDFs (TASK-1572); agent runtime wiring (TASK-1574).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/odoo_agent/build_odoo_pageindex.py` | CREATE | Offline ingestion driver |
| `packages/ai-parrot/tests/knowledge/pageindex/test_build_odoo_pageindex.py` | CREATE | Unit tests (mocked `import_pdf`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import (   # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py:1-43
    PageIndexToolkit, PageIndexLLMAdapter, build_page_index,
)
from parrot.clients.google import GoogleGenAIClient   # google client (verify exact import at impl)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                 # line 50 ; tool_prefix = "pageindex" (line 86)
    def __init__(self, adapter: PageIndexLLMAdapter, storage_dir: str | Path,
                 reranker=None, lightweight_model=None, model=None,
                 default_bm25_k=20, folder_concurrency=4, content_cache_size=256,
                 embedding_model=None, embedding_dimension=256,
                 embedding_backend=None, use_vec_rank=False,
                 use_embedding_walk=False, **kwargs): ...  # lines 88-104
    async def create_tree(self, tree_name, doc_name=None): ...
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None,
                         with_summaries=False, with_doc_description=False): ...  # lines 773-821
    async def insert_markdown(self, tree_name, markdown, parent_node_id=None,
                              doc_name=None): ...          # lines 692-728 (returns new_node_ids)
    async def list_trees(self): ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                                # line 42
    def __init__(self, client: AbstractClient,
                 model="gemini-3.1-flash-lite-preview",
                 max_retries=3, retry_delay=1.0): ...      # lines 49-59
```

### Does NOT Exist
- ~~a `PageIndex` class~~ — the tree is a dict validated by `PageIndexTree`/`PageIndexNode`.
- ~~`PageIndexToolkit.save_learning()`~~ — use `insert_content` / `insert_markdown`.
- ~~one tree with `Odoo 16/18/19` parent nodes~~ — OQ4 resolved to **one tree per version**
  (`odoo_16`/`odoo_18`/`odoo_19`); do NOT nest versions under a single tree.

---

## Implementation Notes

### Pattern to Follow
```python
STORAGE_DIR = "agents/odoo_agent/documentation/"
adapter = PageIndexLLMAdapter(client=GoogleGenAIClient(...), model="<light model>")
toolkit = PageIndexToolkit(adapter=adapter, storage_dir=STORAGE_DIR)
VERSIONS = {"odoo_16": "16.0", "odoo_18": "18.0", "odoo_19": "19.0"}
for tree_name, ver in VERSIONS.items():
    if tree_name in (await toolkit.list_trees()):   # idempotent
        continue
    pdf_path = f"agents/odoo_agent/documentation/{ver}/<docs>.pdf"
    await toolkit.import_pdf(tree_name, pdf_path,
                             with_summaries=True, with_doc_description=True)
```

### Key Constraints
- async throughout (`asyncio.run(main())`).
- Idempotency: check `list_trees()` before creating/importing a version tree.
- Use a lightweight model for summaries to control cost (spec §7).
- `storage_dir` is fixed at `agents/odoo_agent/documentation/` (must match TASK-1574).

### References in Codebase
- `packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py` — toolkit usage + mocking patterns.

---

## Acceptance Criteria

- [ ] `scripts/odoo_agent/build_odoo_pageindex.py` builds one tree per version (`odoo_16`/`odoo_18`/`odoo_19`) under `agents/odoo_agent/documentation/` (mocked `import_pdf`).
- [ ] Re-running does not duplicate trees (idempotent via `list_trees()`).
- [ ] Calls `import_pdf(... with_summaries=True ...)` once per discovered version PDF.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_build_odoo_pageindex.py -v`
- [ ] No lint errors: `ruff check scripts/odoo_agent/build_odoo_pageindex.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_build_odoo_pageindex.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_creates_per_version_trees(tmp_path):
    # import build module, run with PageIndexToolkit.import_pdf/list_trees mocked
    # assert trees odoo_16/odoo_18/odoo_19 created and import_pdf called once per version PDF
    ...


@pytest.mark.asyncio
async def test_idempotent_rerun(tmp_path):
    # with list_trees() already returning the version trees, second run imports nothing new
    ...
```

---

## Agent Instructions

1. Read the spec (§3 Module 3, §6, §7).
2. Verify the Codebase Contract (confirm `create_tree`/`list_trees` names in toolkit.py;
   adjust to the real method names if they differ).
3. Update index status → `in-progress`.
4. Implement per scope.
5. Verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update index → `done`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
