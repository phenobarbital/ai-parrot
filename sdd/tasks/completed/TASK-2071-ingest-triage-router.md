# TASK-2071: IngestTriageRouter cascade + NoveltyScorer

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2069, TASK-2070
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec (§3) — the heart of supervised
ingestion. A cheap-first cascade evaluates each document against the
charter: free heuristics kill duplicates/oversized files, the lightweight
model produces a structured `TriageOutput`, code computes the weighted
composite and routes via `Thresholds.route()`, and only gray-zone docs
escalate to the heavy tier. Novelty is grounding-backed (spec Q&A decision)
with a search-proxy fallback when the graph DB is absent.

Pattern donor (do NOT import): `IntentRouterMixin`'s
keyword-fast-path-then-LLM cascade with typed decision/trace models.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py`:
  - `class IngestTriageRouter` — `__init__(charter, adapter, sources, novelty_scorer)`;
    `async def triage(self, path: Path, content: str) -> ManifestDocEntry`:
    - **Stage 0 (free)**: duplicate via `SourceCollectionManager` file
      hash (`find_by_uri` + hash compare); size/suffix caps from charter
      scope → immediate `reject`, `decision_source="heuristic"`, no LLM call.
    - **Stage 1**: `adapter.ask_structured(prompt, TriageOutput)` on the
      **lightweight** tier; compute composite in Python from
      `charter.weights` × `DimensionScores`; `Thresholds.route()`;
      `sensitive=True` → forced discard regardless of composite.
    - **Stage 2 (gray only)**: heavy tier re-scores with charter few-shot
      examples in the prompt; re-route within the band.
    - Populate `ManifestDocEntry` (proposed_action, scores, composite,
      briefing, claims, decision_source="model" for LLM outcomes).
  - `class NoveltyScorer` — `async def score(self, claims, text) -> tuple[float, str]`:
    - Primary: `GroundingEvaluator.ground_claim` per claim (cap:
      charter-configurable, default 3); novelty ≈ 1 − mean(groundedness).
    - Fallback (graph DB absent): `WikiCombinedSearch.search` top-k
      similarity proxy; log a warning; return backend id
      (`"grounding"` | `"search-proxy"`) for the run header.
- Write `tests/knowledge/wiki/test_triage.py` (stub adapter — no real LLM).

**NOT in scope**: manifest file I/O (TASK-2070), orchestrator/page
creation (TASK-2074), CLI (TASK-2075), SQLite decision persistence (TASK-2073).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | CREATE | Router cascade + novelty scorer |
| `tests/knowledge/wiki/test_triage.py` | CREATE | Unit tests with stubbed adapter/retriever |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02).

### Verified Imports
```python
from parrot.knowledge.wiki.charter import Charter                       # TASK-2069
from parrot.knowledge.wiki.review import Claim, DimensionScores, ManifestDocEntry, TriageOutput  # TASK-2070
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.graphindex.grounding import GroundingEvaluator, GroundingResult
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                               # line 42
    async def ask_structured(self, prompt: str, output_type: type,
                             temperature: float = 0.0,
                             system_prompt: Optional[str] = None) -> Any: ...  # 99-105
    # delegates to client.invoke(..., output_type=...) with retry + manual-JSON fallback

# packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py
class GroundingEvaluator:                                # line 96
    def __init__(self, retriever: GraphExpandedRetriever, client: Optional[Any] = None,
                 max_hops: int = 2) -> None: ...         # 108-112
    async def ground_claim(self, claim: str) -> GroundingResult: ...   # 204
class GroundingResult(BaseModel): ...                    # line 53: decision, reason, supported_paths, contradictions, required_evidence
# Full wiring recipe (graph DB → retriever → evaluator): wiki/cli.py:1947-2011
#   SQLitePersistence → GraphAssembler → HashingGraphEmbedder → GraphExpandedRetriever → GroundingEvaluator
# REQUIRES .parrot/graph/<wiki>.db to exist — always guard and fall back.

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                                # line 32; __init__ 47
    async def search(self, query: str, mode: str = "combined", top_k: int = 10,
                     tree_name: Optional[str] = None,
                     weights: Optional[dict[str, float]] = None) -> list[WikiSearchResult]: ...  # 85-92

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                           # line 47
    def find_by_uri(self, ...): ...                      # 352
    def _compute_hash(self, ...): ...                    # 426 (private — prefer public surface; verify exact params before use)

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiConfig(BaseModel):                             # line 47
    lightweight_model: Optional[str] = None              # 88-91 — triage Stage 1 tier
    model: Optional[str] = None                          # 92-95 — Stage 2 escalation tier

# PATTERN DONOR ONLY (do not import): bots/mixins/intent_router.py
#   _KEYWORD_STRATEGY_MAP line 59; class IntentRouterMixin line 123
```

### Does NOT Exist
- ~~`parrot/knowledge/wiki/triage.py`~~, ~~`IngestTriageRouter`~~, ~~a novelty scorer~~ — you are creating them.
- ~~`AbstractClient.ask_structured`~~ — `ask_structured` exists ONLY on `PageIndexLLMAdapter`; client-level equivalents are `invoke(output_type=…)` / `ask(structured_output=…)` (clients/base.py:1700/:1611).
- ~~`GroundingEvaluator.score_novelty`~~ — grounding grounds a single claim; novelty math (1 − mean groundedness) is YOUR code.
- ~~`TriageOutput.composite`~~ — the LLM never emits a composite; computed in Python (spec §5).

---

## Implementation Notes

### Key Constraints
- Async throughout; no blocking I/O (hashing via `asyncio.to_thread` if needed).
- Every routed entry must carry an auditable trace: which stage decided,
  which backend scored novelty.
- Prompts include charter scope + few-shot examples (Stage 2 only) — keep
  prompt builders as private functions for testability.
- The heavy tier must be provably skipped outside the gray zone (test asserts call counts on the stub).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py:43-108` — dual-tier (light/heavy) usage pattern.
- `wiki/cli.py:1947-2011` — grounding stack construction to reuse in `NoveltyScorer` setup.

---

## Acceptance Criteria

- [ ] Duplicate/oversized docs are rejected with ZERO adapter calls (asserted via stub call count).
- [ ] Composite computed from charter weights in Python; boundary routing matches `Thresholds.route`.
- [ ] `sensitive=true` forces discard even with a high composite.
- [ ] Heavy tier invoked ONLY for gray-band docs.
- [ ] Graph DB absent → search-proxy fallback used, warning logged, backend id returned.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_triage.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` clean
- [ ] Import works: `from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer`

---

## Test Specification

```python
# tests/knowledge/wiki/test_triage.py
import pytest
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer

@pytest.fixture
def fake_adapter(): ...   # ask_structured stub returning canned TriageOutput; counts calls per tier

async def test_router_heuristic_duplicate(fake_adapter): ...     # 0 LLM calls
async def test_router_composite_in_code(fake_adapter): ...
async def test_router_sensitive_forces_discard(fake_adapter): ...
async def test_router_gray_zone_escalates(fake_adapter): ...     # heavy called only for gray
async def test_novelty_fallback_no_graph(tmp_path): ...          # proxy + backend recorded
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2069 and TASK-2070 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm every import/signature above
   still holds (and the actual charter/review APIs as implemented); update
   the contract FIRST if anything changed
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and **update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
