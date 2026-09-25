# TASK-2671: GraphIndex derived rebuild + Query workflow (§28)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2661, TASK-2662
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 13 + D3. Build/refresh the derived GraphIndex/PageIndex plane (the
**primary query graph**) and implement the §28 query workflow (retrieve → verify).

## Scope

- `graph.py`: build the wiki toolkit (PageIndex + GraphIndex via `build_graph_memory_toolkit`) and call `ingest_obsidian_vault(incremental=True)` after each ingest to rebuild the derived plane from the vault. **Derived only — never the content authority or the dedup gate.**
- `nodes/query.py`: §28 — query the GraphIndex/PageIndex for candidates (primary), then **read the Obsidian source pages** for the answer + provenance; the answer distinguishes **supported facts / inferences / unknowns / unresolved contradictions** (§28 step 7); GraphIndex output never quoted as authority. Save synthesis only on request (§28 step 10).
- Internal-index retrieval is allowed (rule #15 exception, D6); no external knowledge.

**NOT in scope**: ingest orchestration (TASK-2672).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/graph.py` | CREATE | derived rebuild + toolkit wiring |
| `.../wiki_ingest/nodes/query.py` | CREATE | §28 query |
| `packages/ai-parrot/tests/unit/test_wiki_kb_query.py` | CREATE | retrieval→verify + distinctions tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit          # knowledge/wiki/toolkit.py:54
from parrot.knowledge.wiki.models import WikiConfig                # knowledge/wiki/models.py:52
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit  # graphindex/factory.py:203
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit    # pageindex/toolkit.py:50
```
### Existing Signatures to Use
```python
async def ingest_obsidian_vault(self, wiki_name, vault_path, incremental=False,
                                extract_entities=False, granularity="standard")  # toolkit.py:295
def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit, config, agent_id="agent", store=None, **kwargs)  # toolkit.py:83
async def build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent", ...)  # factory.py:203
```
### Does NOT Exist
- ~~GraphIndex as content source-of-truth or dedup authority~~ — it is derived only (D3/R1).

## Implementation Notes
- `LLMWikiToolkit._config_for` raises on wiki_name mismatch — one toolkit per plane.
- A missing/stale GraphIndex must never block ingest or cause a re-download.

## Acceptance Criteria
- [ ] Ingest rebuilds the derived plane incrementally.
- [ ] Query retrieves via GraphIndex then answers from Obsidian pages with provenance.
- [ ] Answer distinguishes facts/inferences/unknowns/contradictions.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_query_graphindex_then_verify_pages(): ...
async def test_answer_distinguishes_fact_types(): ...
```

### Completion Note

`graph.py`: `build_wiki_kb_graph_toolkit()`/`rebuild_graph_index()` mirror
`agents/fireflies_wiki.py`'s `LLMWikiToolkit` construction pattern
(pageindex + graph memory toolkit + `WikiConfig`) for this subsystem's
own, independent wiki plane (`WIKI_KB_GRAPH_WIKI_NAME`, storage at
`<vault>/.wiki_kb/graph` — no new conf key, a hidden dir alongside the
vault like `.obsidian/`, outside `Wiki/` so it's never confused with
Claude-managed content). `rebuild_graph_index()` calls
`ingest_obsidian_vault(incremental=True)` — derived only (D3/R1); its
docstring is explicit that a rebuild failure must never block ingest or
gate a fetch decision.

`nodes/query.py`: `run_query()` implements §28 verbatim — retrieves via
`LLMWikiToolkit.search(mode="combined")` (primary), then
`_resolve_and_read()` re-finds and re-reads each candidate from the
**Obsidian vault** via this subsystem's own `ObsidianToolkit` before the
LLM ever sees it (a candidate that can't be resolved/read in the vault
is dropped, never guessed, never answered from the GraphIndex snippet
directly); when zero candidates verify, the LLM call is skipped entirely
and the answer is `unknowns`-only. `QueryAnswer` has explicit typed
fields for supported facts / inferences / unknowns / unresolved
contradictions (§28 step 7). `build_synthesis_page()` is a separate,
opt-in function — never called by `run_query` itself (§28 step 9: an
ordinary query never writes to the Wiki).

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_query.py`
(4 passed — retrieval-then-verify with the GraphIndex snippet proven
absent from the LLM prompt, fact-type distinctions round-trip, zero
verified candidates skips the LLM call, synthesis-page rendering is
separate from the query call); `ruff check` clean; `mypy` clean; full
wiki-kb suite (81 tests) stays green.
