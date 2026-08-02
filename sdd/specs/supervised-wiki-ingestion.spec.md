---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# FEAT-402 was reserved by the /sdd-proposal run for this same initiative
# (ledger commit 00ba864fa); the spec intentionally reuses it (FEAT-387).
reuse_feature_id: FEAT-402
---

# Feature Specification: Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)

**Feature ID**: FEAT-402
**Date**: 2026-08-02
**Author**: Jesus Lara (proposal research: Cowork session 2026-07-30; spec: Claude session 2026-08-02)
**Status**: approved
**Target version**: next minor
**Proposal**: `sdd/proposals/supervised-wiki-ingestion.proposal.md`
**Research state**: `sdd/state/FEAT-402-supervised-wiki-ingestion/`

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit build` performs **unsupervised ingestion**: `_ingest_files`
admits every scanned file, with staleness (`SourceCollectionManager.is_stale`)
as the only gate. That is correct for code repositories (deterministic,
offline, post-commit-hook friendly) but wrong for **document corpora** —
meeting notes, summaries, "corporate digital life" — where much of the
content should never become a wiki page ("si en una reunión solo se contaron
chistes, se debería descartar del wiki"). There is no pre-ingestion
evaluation, classification, or human checkpoint.

### Goals

- A new, **opt-in** `wikitoolkit ingest <folder>` command for document
  corpora that triages content *before* it becomes wiki pages. `build`
  stays untouched.
- **Charter-driven scoring**: a versioned YAML editorial charter defines
  scope include/exclude, scoring dimensions (density / novelty /
  durability) with weights, and thresholds that route each document to
  `admit` / gray zone / `reject`.
- **Cheap-first cascade**: deterministic heuristics (duplicate hash,
  size caps) → lightweight-model structured triage → heavy-model
  escalation only for the gray zone.
- **HITL review flow**: JSONL review manifest with `--dry-run` (emit
  manifest) → human edit → `--review` (apply decisions); `--interactive`
  for small batches; `--auto` with **stratified audit sampling**
  (60% near-threshold / 40% uniform, charter-configurable).
- **Auditability**: charter sha256 + version stamped in every manifest
  run header; every admission decision logged via `WikiBookkeeper`;
  decision provenance (`decision_source`) persisted in the source
  manifest.
- **Triage work is reused, not repeated**: the triage briefing feeds the
  existing `TwoStepIngester` `hint` channel.

### Non-Goals (explicitly out of scope)

- Changing `wikitoolkit build` or `repo_scan.py` — the deterministic,
  offline, no-LLM contract (module docstring `repo_scan.py:1-5`) is load-
  bearing for the git post-commit hook.
- Modifying GraphIndex builders/extractors — grounding machinery is
  *consumed* for novelty scoring, never modified.
- A **separate archive storage plane** — rejected during spec Q&A in
  favor of archive-as-category-pages (see §8). A dedicated searchable
  archive plane remains future work.
- **Full claim-level admission** — v1 admits/rejects whole documents;
  claim extraction ships behind an experimental flag (`--extract`), and
  per-claim ingestion is a fast-follow (see §8).
- Charter auto-tuning that *applies* changes — v1 calibration is
  `propose`-only; amendments happen via versioned charter edits.
- Touching the query/search read paths beyond archive-category exclusion.

---

## 2. Architectural Design

### Overview

A new supervised ingestion pipeline is added alongside (not inside) the
existing build path:

1. **Charter** (`charter.py`): Pydantic `Charter` model loaded from YAML —
   scope rules, dimension weights (must sum to 1.0), thresholds
   (`reject < admit`), routing destinations, calibration policy, few-shot
   examples (+ optional `examples_file`), amendments log. A sha256
   fingerprint of the canonical charter bytes versions every decision.
2. **Triage router** (`triage.py`): `IngestTriageRouter` runs a cascade
   per document:
   - **Stage 0 — heuristics (free)**: duplicate detection via
     `SourceCollectionManager` file hash; size/suffix caps → immediate
     `reject` with `decision_source="heuristic"`.
   - **Stage 1 — lightweight triage**: `PageIndexLLMAdapter.ask_structured`
     with the charter's `lightweight_model` tier produces a `TriageOutput`
     (briefing, `DimensionScores`, optional `Claim` list, `sensitive`
     flag). **Code, not the LLM, computes the weighted composite** and
     `Thresholds.route()` maps it to admit / gray / reject bands.
     `sensitive=true` forces discard regardless of score.
   - **Stage 2 — heavy escalation (gray zone only)**: the `model` tier
     re-scores gray-zone documents with the charter few-shot examples in
     context; the refined score re-routes within the band.
   - **Novelty dimension**: scored via `GroundingEvaluator.ground_claim`
     over the triage-extracted claims against the GraphIndex plane —
     novelty ≈ 1 − mean(groundedness). **Fallback** (graph DB absent):
     `WikiCombinedSearch.search` top-k similarity proxy, with a logged
     warning and `novelty_backend` recorded in the manifest entry.
3. **Review manifest** (`review.py`): JSONL file — one `ManifestRunHeader`
   line (charter sha256/version, counts, mode, novelty backend) + one
   `ManifestDocEntry` per document (briefing, dimension scores,
   composite, `proposed_action`, claims, `decision`, `decision_source`,
   audit-sample flags). Reader applies human edits; stratified sampler
   flags the audit subset; `agreement_rate()` compares human vs. proposed
   decisions and drives gray-zone widening per the charter `calibration`
   policy (propose-only).
4. **CLI** (`wiki/cli.py`): new `ingest` command with `--dry-run`,
   `--review <manifest.jsonl>`, `--interactive`, `--auto`,
   `--charter <path>`, `--extract` (experimental). Interactive prompts
   (questionary, blocking) collect all decisions **before** the async
   apply-pipeline launches.
5. **Apply path**: admitted docs flow through the existing
   `WikiIngestOrchestrator.ingest`, extended to accept an optional triage
   decision object and forward the briefing as
   `insert_content(..., hint=briefing)` — the `hint` slot the orchestrator
   currently drops at `ingest.py:343`. **Archive-routed docs are ingested
   as wiki pages with the new `WikiPageCategory.ARCHIVE` category**,
   which the search plane excludes from ranking by default (opt back in
   via explicit `category="archive"` filter). Rejected docs are recorded
   in the source manifest with `status="rejected"` and never ingested.
6. **Persistence**: `sources` table gains `destination`,
   `decision_source`, `charter_version`, `composite_score` columns
   (additive `ALTER TABLE` migration with defaults, following the
   `_migrate_json_manifest` compatibility precedent). Human decisions
   append to the charter's `examples_file` for the few-shot loop.
   `WikiBookkeeper.log_operation` (free-string op tags) logs `TRIAGE`,
   `ADMIT`, `ARCHIVE`, `DISCARD`.

### Component Diagram

```
wikitoolkit ingest <folder>
        │
        ├── Charter.load(yaml) ── sha256 fingerprint
        │
        ├── for each doc: IngestTriageRouter.triage()
        │       Stage 0 heuristics ──(dup/size)──→ reject
        │       Stage 1 lightweight ask_structured → TriageOutput
        │       │       └─ novelty: GroundingEvaluator.ground_claim(claims)
        │       │                    └─(no graph db)→ WikiCombinedSearch proxy
        │       Stage 2 heavy re-score (gray zone only)
        │       Thresholds.route(composite) → admit | gray | reject
        │
        ├── ManifestWriter → manifest.jsonl  (run_header + doc entries)
        │       --dry-run → stop here (human edits decisions)
        │       --review  → ManifestReader applies human decisions
        │       --interactive → questionary loop (BEFORE async apply)
        │       --auto    → thresholds decide; stratified audit sample flagged
        │
        └── apply pipeline (async)
                admit   → WikiIngestOrchestrator.ingest(triage=…)
                │             └── PageIndexToolkit.insert_content(hint=briefing)
                archive → orchestrator ingest with category=ARCHIVE
                reject  → SourceCollectionManager (status="rejected") only
                all     → WikiBookkeeper.log_operation + manifest columns
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `wiki/cli.py` (`@wiki.command`) | extends (additive) | one new `ingest` command block; no existing command named `ingest` (verified full inventory) |
| `WikiIngestOrchestrator.ingest` | modifies (optional param) | accepts optional triage decision; forwards briefing via `insert_content(hint=…)` |
| `PageIndexToolkit.insert_content` | uses | already accepts `hint: Optional[str]` (`toolkit.py:730-736`) |
| `TwoStepIngester.ingest(content, hint)` | uses (indirect) | `hint` interpolated into both LLM prompts |
| `PageIndexLLMAdapter.ask_structured` | uses | structured `TriageOutput` from the lightweight tier |
| `WikiConfig` | modifies (new fields) | `charter_path: Optional[Path]`; reuses `lightweight_model` / `model` tiers |
| `WikiPageCategory` | modifies (new value) | `ARCHIVE = "archive"` |
| `WikiCombinedSearch.search` / `SQLiteWikiStore.search_fts` | modifies (filter) | exclude `archive` category from default ranking |
| `SourceCollectionManager` + `store.py` schema | modifies (migration) | 4 new columns on `sources` table |
| `WikiBookkeeper.log_operation` | uses | free-string op tags — no schema change |
| `GroundingEvaluator.ground_claim` | uses | novelty backend (graph plane); requires graph DB |
| `IntentRouterMixin` | pattern donor only | cascade + typed decision/trace models; NOT imported |

### Data Models

Adapted from the reference sketch
`sdd/state/FEAT-402-supervised-wiki-ingestion/references/schemas.py`
(design reference — **not** an import target):

```python
class DimensionScores(BaseModel):
    density: float      # 0..1 — information density
    novelty: float      # 0..1 — new vs. existing wiki (grounding-backed)
    durability: float   # 0..1 — long-term relevance

class Claim(BaseModel):
    text: str
    grounded: Optional[bool] = None   # filled by novelty scoring

class TriageOutput(BaseModel):        # LLM structured output (no composite!)
    briefing: str                     # 2-3 sentence summary → ingester hint
    scores: DimensionScores
    claims: list[Claim] = []
    sensitive: bool = False           # forces discard
    category_hint: Optional[str] = None

class Thresholds(BaseModel):
    admit: float                      # composite >= admit → admit
    reject: float                     # composite <  reject → reject
    # reject < admit enforced by validator; between = gray zone
    def route(self, composite: float) -> Literal["admit", "gray", "reject"]: ...

class Charter(BaseModel):
    version: str
    scope: CharterScope               # include/exclude rules
    weights: dict[str, float]         # keys = DimensionScores fields; sum ≈ 1.0
    thresholds: Thresholds
    destinations: list[str]           # ["wiki", "archive", "discard"]
    calibration: CalibrationPolicy    # audit fractions, gray widening, propose-only
    examples: list[TriageExample] = []
    examples_file: Optional[Path] = None
    amendments: list[Amendment] = []
    # + sha256 fingerprint computed at load time (not a stored field)

class ManifestRunHeader(BaseModel):
    charter_sha256: str; charter_version: str
    mode: Literal["dry-run", "review", "interactive", "auto"]
    novelty_backend: Literal["grounding", "search-proxy"]
    counts: dict[str, int]; created_at: str

class ManifestDocEntry(BaseModel):
    source_uri: str; file_hash: str
    briefing: str; scores: DimensionScores; composite: float
    proposed_action: Literal["admit", "archive", "discard"]
    claims: list[Claim] = []
    decision: Optional[Literal["admit", "archive", "discard"]] = None
    decision_source: Literal["heuristic", "model", "human", "auto"] | None = None
    audit_sample: bool = False; audit_stratum: Optional[str] = None
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/charter.py
def load_charter(path: Path) -> Charter: ...          # YAML + validation + fingerprint

# parrot/knowledge/wiki/triage.py
class IngestTriageRouter:
    def __init__(self, charter: Charter, adapter: PageIndexLLMAdapter,
                 sources: SourceCollectionManager,
                 novelty_scorer: NoveltyScorer) -> None: ...
    async def triage(self, path: Path, content: str) -> ManifestDocEntry: ...

class NoveltyScorer:                                   # grounding-first, proxy fallback
    async def score(self, claims: list[Claim], text: str) -> tuple[float, str]: ...
    # returns (novelty, backend_used)

# parrot/knowledge/wiki/review.py
class ManifestWriter:   ...   # run_header + append entries (JSONL)
class ManifestReader:   ...   # parse + validate human-edited decisions
def stratified_sample(entries, near_fraction=0.6, uniform_fraction=0.4, ...) -> None: ...
def agreement_rate(entries: list[ManifestDocEntry]) -> Optional[float]: ...

# CLI (wiki/cli.py)
# wikitoolkit ingest <folder> [--charter PATH] [--dry-run | --review MANIFEST |
#                              --interactive | --auto] [--extract]
```

---

## 3. Module Breakdown

### Module 1: Charter
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/charter.py`
- **Responsibility**: `Charter` + sub-models, YAML loader, validators
  (weights sum ≈ 1.0 mirroring `WikiConfig.validate_search_weights`;
  `reject < admit`), sha256 fingerprint, `examples_file` append helper.
- **Depends on**: nothing new (PyYAML, Pydantic).

### Module 2: Manifest / review layer
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/review.py`
- **Responsibility**: `ManifestRunHeader` / `ManifestDocEntry` JSONL
  writer + reader, stratified audit sampler, `agreement_rate()`,
  gray-zone-widening proposal per calibration policy.
- **Depends on**: Module 1 (models).

### Module 3: Triage router + novelty scorer
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py`
- **Responsibility**: `IngestTriageRouter` cascade (heuristics →
  lightweight structured triage → heavy gray-zone escalation),
  composite computation in code, `Thresholds.route()` application,
  `NoveltyScorer` (GroundingEvaluator-backed; `WikiCombinedSearch`
  proxy fallback when the graph DB is absent).
- **Depends on**: Modules 1-2; existing `PageIndexLLMAdapter`,
  `GroundingEvaluator`, `WikiCombinedSearch`, `SourceCollectionManager`.

### Module 4: Archive category + ranking exclusion
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`,
  `search.py`, `store.py` (filter only)
- **Responsibility**: add `WikiPageCategory.ARCHIVE`; exclude the
  `archive` category from default ranking in `WikiCombinedSearch.search`
  and `search_fts` unless explicitly requested; `WikiConfig.charter_path`.
- **Depends on**: none (can run parallel to Modules 1-3).

### Module 5: Sources migration + bookkeeper tags
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`,
  `store.py` (schema)
- **Responsibility**: additive `ALTER TABLE sources` migration adding
  `destination TEXT`, `decision_source TEXT`, `charter_version TEXT`,
  `composite_score REAL` (all nullable/defaulted so pre-FEAT-402 wikis
  open cleanly); persist triage outcome on `mark_ingested`/reject path;
  `TRIAGE`/`ADMIT`/`ARCHIVE`/`DISCARD` bookkeeper logging.
- **Depends on**: Module 2 (entry fields).

### Module 6: Orchestrator wiring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`
- **Responsibility**: `WikiIngestOrchestrator.ingest` accepts optional
  triage context (decision + briefing + category override); forwards
  briefing as `insert_content(..., hint=…)`; archive category on
  archive-routed docs; idempotent re-review (existing
  `replace_source_slice` semantics — re-running `--review` must not
  duplicate pages).
- **Depends on**: Modules 3, 5.

### Module 7: CLI `ingest` command
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: `wikitoolkit ingest` with `--charter`, `--dry-run`,
  `--review`, `--interactive`, `--auto`, `--extract`; questionary
  interactive loop runs before the async apply pipeline; rich progress
  output; wires Modules 1-6.
- **Depends on**: all previous modules. **Keep the diff additive** —
  `cli.py` is a hot file (see §7 risks).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_charter_load_valid` | 1 | YAML → `Charter`; fingerprint stable across loads |
| `test_charter_weights_must_sum` | 1 | weights ≠ 1.0 rejected |
| `test_charter_thresholds_order` | 1 | `reject >= admit` rejected |
| `test_examples_file_append` | 1 | human decision appended; round-trips |
| `test_manifest_roundtrip` | 2 | write → edit decision → read; header preserved |
| `test_manifest_rejects_bad_decision` | 2 | invalid decision value fails validation |
| `test_stratified_sampler_fractions` | 2 | 60/40 near-threshold/uniform split honored |
| `test_agreement_rate` | 2 | human vs proposed agreement math |
| `test_router_heuristic_duplicate` | 3 | known hash → reject without LLM call |
| `test_router_composite_in_code` | 3 | composite computed from weights, not LLM |
| `test_router_sensitive_forces_discard` | 3 | `sensitive=true` overrides high score |
| `test_router_gray_zone_escalates` | 3 | heavy tier called only for gray band |
| `test_novelty_fallback_no_graph` | 3 | graph DB absent → search proxy + backend recorded |
| `test_archive_category_value` | 4 | `WikiPageCategory.ARCHIVE == "archive"` |
| `test_search_excludes_archive_by_default` | 4 | archive pages absent from default ranking; present with explicit filter |
| `test_sources_migration_old_db` | 5 | pre-FEAT-402 SQLite opens; new columns defaulted |
| `test_sources_persist_decision` | 5 | destination/decision_source/charter_version/composite stored |
| `test_orchestrator_forwards_hint` | 6 | briefing reaches `insert_content(hint=…)` |
| `test_orchestrator_reject_no_pages` | 6 | rejected doc creates zero pages, manifest row updated |
| `test_cli_ingest_dry_run` | 7 | manifest emitted, decisions null, nothing ingested |
| `test_cli_ingest_review_apply` | 7 | edited manifest applied; idempotent on re-run |
| `test_cli_ingest_auto_audit_flags` | 7 | audit sample flagged per charter fractions |

### Integration Tests
| Test | Description |
|---|---|
| `test_supervised_ingest_end_to_end` | folder → dry-run manifest → simulated human edits → review apply → admitted pages exist, archive pages carry ARCHIVE category, rejected absent, bookkeeper log has TRIAGE/ADMIT/ARCHIVE/DISCARD lines |
| `test_build_unaffected` | `build` path produces identical results with FEAT-402 code present (no behavior change) |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_charter(tmp_path) -> Path: ...   # minimal valid charter YAML
@pytest.fixture
def doc_corpus(tmp_path) -> Path: ...       # mix: dense doc, joke-meeting doc, duplicate, oversized
@pytest.fixture
def fake_adapter() -> PageIndexLLMAdapter: ...  # ask_structured stub returning canned TriageOutput
```
Location: `tests/knowledge/wiki/test_charter.py`, `test_triage.py`,
`test_review.py`; CLI cases extend the existing
`tests/knowledge/wiki/test_cli.py` suite.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `wikitoolkit ingest` exists with `--charter/--dry-run/--review/--interactive/--auto/--extract`; `wikitoolkit build` behavior is byte-identical for code repos (integration test).
- [ ] Triage is a cheap-first cascade: duplicates/oversized documents are rejected with **zero** LLM calls; the heavy model tier is invoked **only** for gray-zone documents.
- [ ] The composite score is computed in Python from charter weights; the LLM never emits a composite.
- [ ] `sensitive=true` in `TriageOutput` forces discard regardless of composite.
- [ ] v1 admission is **document-level**; `--extract` (claim extraction into the manifest) is flagged experimental and off by default.
- [ ] Archive-routed documents become wiki pages with category `archive`, excluded from default query ranking but retrievable via explicit category filter.
- [ ] Novelty is scored via `GroundingEvaluator.ground_claim` over triage claims when the graph DB exists; otherwise falls back to `WikiCombinedSearch` similarity with a warning, and the manifest `run_header.novelty_backend` records which backend ran.
- [ ] The JSONL manifest round-trips: `--dry-run` output, hand-edited decisions, `--review` apply — and re-running `--review` is idempotent (no duplicate pages).
- [ ] `--auto` flags a stratified audit sample (default 60% near-threshold / 40% uniform, charter-configurable) and `agreement_rate()` is computable from a reviewed manifest.
- [ ] Human decisions append to the charter `examples_file`; charter sha256 + version appear in every manifest run header; calibration is propose-only (no charter auto-writes).
- [ ] Pre-FEAT-402 wiki SQLite databases open cleanly; the `sources` migration adds `destination`, `decision_source`, `charter_version`, `composite_score` with safe defaults.
- [ ] Every admission decision is visible in `wikitoolkit audit` via `WikiBookkeeper` ops `TRIAGE`/`ADMIT`/`ARCHIVE`/`DISCARD`.
- [ ] Interactive (questionary) prompting completes **before** the async apply pipeline starts; no blocking I/O inside async code paths.
- [ ] All unit + integration tests above pass (`pytest tests/knowledge/wiki/ -v`); no breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` @ `ad6365242` (2026-08-02) by direct read.
> The proposal's line numbers for `cli.py` were ~110-120 lines stale and
> have been re-anchored here. Implementation agents MUST NOT reference
> imports, attributes, or methods not listed here without verifying via
> `wikitoolkit query` / grep / read first.

### Verified Imports

```python
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory, SourceManifestEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator, IngestReport
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore
from parrot.knowledge.pageindex.ingest import TwoStepIngester
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.graphindex.grounding import GroundingEvaluator, GroundingResult
from parrot.models.outputs import StructuredOutputConfig   # re-exported at parrot/models/__init__.py:16,127
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (2062 lines)
# @click.group(name="wiki")                             line 685-686
# def main() -> None:                                   line 2028
# build command: decorators 695-722, function 723-847
def build(path_, name, backend, force, no_git, quiet, no_export, no_graph, graph_kinds) -> None: ...
async def _ingest_files(store: BaseWikiStore, sources: SourceCollectionManager,
                        root: Path, scan: Any, force: bool = False) -> dict[str, int]: ...  # 316-378
# shared --path decorator: path_option, lines 71-73
# Existing @wiki.command inventory (NO command named "ingest"):
#   build 695, upsert 886, query 1005, page 1090, related 1133, status 1171,
#   communities 1221, export 1323, remember 1577, note 1732, link 1796,
#   memories 1847, audit 1884, ground 1943, claude-hook(hidden) 2013,
#   codex/claude/gemini dynamic at 2046-2062

# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
class WikiIngestOrchestrator:                            # line 69
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any,
                 source_manager: SourceCollectionManager, bookkeeper: WikiBookkeeper,
                 store: Optional[BaseWikiStore] = None, sync_graph: bool = False) -> None: ...  # 89-95
    async def ingest(self, source_path: str, wiki_config: WikiConfig) -> IngestReport: ...     # 123-306
# NOTE: currently NO hint/triage parameter; PageIndex call at ingest.py:343 is
#   await self._pi.insert_content(tree_name, content)   ← drops the hint slot
class IngestReport(BaseModel): ...                       # line 45

# packages/ai-parrot/src/parrot/knowledge/pageindex/ingest.py
class TwoStepIngester:                                   # line 43; __init__(adapter, lightweight_adapter=None) 54-58
    async def ingest(self, content: str, hint: Optional[str] = None) -> IngestedMarkdown: ...  # 62-69
    # hint is interpolated into BOTH prompts (_step1_analyze :71-73, _step2_generate :83-90)

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit:
    async def insert_content(self, tree_name: str, content: str,
                             parent_node_id: Optional[str] = None,
                             hint: Optional[str] = None) -> dict[str, Any]: ...  # 730-736

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                               # line 42
    async def ask_structured(self, prompt: str, output_type: type,
                             temperature: float = 0.0,
                             system_prompt: Optional[str] = None) -> Any: ...    # 99-105
    # delegates to client.invoke(..., output_type=...) with retry + manual-JSON fallback

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiPageCategory(str, Enum):                       # line 25; values 38-44
    SUMMARY, ENTITY, CONCEPT, COMPARISON, OVERVIEW, SYNTHESIS, ANSWER  # 7 values; NO ARCHIVE yet
class WikiConfig(BaseModel):                             # line 47
    lightweight_model: Optional[str] = None              # 88-91 "fast CoT analysis step"
    model: Optional[str] = None                          # 92-95 "heavyweight generation step"
    storage_backend: Literal["sqlite","memory","arangodb"] = "sqlite"  # 103
    # only validator: validate_search_weights (114-140): each weight in [0,1], sum ≈ 1.0 ±0.01

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                           # line 47; __init__ 72
    def add_source(self, path: Path) -> SourceManifestEntry: ...                  # 160
    def is_stale(self, source_id: str) -> bool: ...                               # 239
    def mark_ingested(self, source_id: str, pages_generated: list[str],
                      status: str = "ingested") -> Optional[SourceManifestEntry]: ...  # 282-287
    def _migrate_json_manifest(self) -> None: ...                                 # 657
    # also: list_sources 202, get_source 219, remove_source 321, find_by_uri 352,
    #       _connect 367, _upsert 379, _compute_hash 426; ArangoDB async path 600-656

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py — sources DDL lives HERE (58-66):
#   sources(source_id PK, source_uri UNIQUE, file_hash, mtime, ingested_at,
#           pages_generated TEXT DEFAULT '[]', status TEXT DEFAULT 'ingested')  — 7 columns
class BaseWikiStore:                                     # line 279
    async def search_fts(self, query: str, category: Optional[str] = None,
                         limit: int = 10) -> list[dict[str, Any]]: ...   # abstract 334; SQLite impl 987-992
    async def search_vector(self, embedding: list[float],
                            limit: int = 10) -> list[dict[str, Any]]: ...  # abstract 339; SQLite impl 1025-1029
class SQLiteWikiStore(BaseWikiStore): ...                # line 431

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                                # line 32; __init__ 47
    async def search(self, query: str, mode: str = "combined", top_k: int = 10,
                     tree_name: Optional[str] = None,
                     weights: Optional[dict[str, float]] = None) -> list[WikiSearchResult]: ...  # 85-92

# packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py
class WikiBookkeeper:                                    # line 31; LOG_FILENAME = "log.md" (45)
    def log_operation(self, wiki_dir: Path, operation: str, details: str,
                      timestamp: Optional[str] = None) -> None: ...   # 175-181
    # operation is a FREE STRING, upper-cased at write (:199) — no enum, no schema change needed
    # tags in tree today: INGEST, QUERY, LINT, REMEMBER (cli:1677), NOTE (cli:1786), LINK (cli:1831)

# packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py
class GroundingEvaluator:                                # line 96
    def __init__(self, retriever: GraphExpandedRetriever, client: Optional[Any] = None,
                 max_hops: int = 2) -> None: ...         # 108-112
    async def ground_claim(self, claim: str) -> GroundingResult: ...   # 204
class GroundingResult(BaseModel): ...                    # 53: decision, reason, supported_paths, contradictions, required_evidence
# CAVEAT: grounds a claim against the GraphIndex plane (.parrot/graph/<wiki>.db);
# it is NOT a novelty scorer and REQUIRES the graph DB to exist.
# CLI `ground` command (cli.py:1943/1947-2011) shows the full wiring:
#   SQLitePersistence → GraphAssembler → HashingGraphEmbedder → GraphExpandedRetriever → GroundingEvaluator

# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py  (PATTERN DONOR ONLY — do not import)
# _KEYWORD_STRATEGY_MAP: dict[str, RoutingType]          line 59
# class IntentRouterMixin:                               line 123; override merge 481-494

# packages/ai-parrot/src/parrot/models/outputs.py
@dataclass
class StructuredOutputConfig:                            # 66-67
    output_type: type; format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None
    # get_schema() at :73
# Client-level structured entry points (clients/base.py, class AbstractClient :253):
#   async def invoke(...) :1700 — output_type :1704, structured_output :1705
#   async def ask(...) :1611 — structured_output: Union[type, StructuredOutputConfig, None] :1619
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `IngestTriageRouter` | `PageIndexLLMAdapter.ask_structured()` | method call | `pageindex/llm_adapter.py:99-105` |
| `IngestTriageRouter` | `SourceCollectionManager.find_by_uri()` / `_compute_hash` | dup heuristic | `wiki/sources.py:352,426` |
| `NoveltyScorer` | `GroundingEvaluator.ground_claim()` | per-claim call | `graphindex/grounding.py:204`; wiring recipe `wiki/cli.py:1947-2011` |
| `NoveltyScorer` (fallback) | `WikiCombinedSearch.search()` | top-k similarity | `wiki/search.py:85-92` |
| orchestrator wiring | `PageIndexToolkit.insert_content(hint=…)` | fill dropped slot | call site `wiki/ingest.py:343`; signature `pageindex/toolkit.py:730-736` |
| `ingest` CLI command | `@wiki.command` group | additive registration | group `wiki/cli.py:685-686` |
| decision persistence | `sources` table migration | `ALTER TABLE` | DDL `wiki/store.py:58-66`; precedent `sources.py:657` |
| audit trail | `WikiBookkeeper.log_operation()` | free-string tags | `wiki/bookkeeper.py:175-181,199` |
| archive exclusion | `search_fts(category=…)` / `WikiCombinedSearch.search` | category filter | `wiki/store.py:334,987-992`; `wiki/search.py:85-92` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/knowledge/wiki/charter.py`~~, ~~`triage.py`~~, ~~`review.py`~~ — to be created by this feature (zero hits under `packages/`).
- ~~`TriageOutput`~~, ~~`IngestTriageRouter`~~, ~~`Charter`~~, ~~`ManifestDocEntry`~~, ~~`ManifestRunHeader`~~, ~~`agreement_rate`~~ — no such symbols in shipped code. They appear ONLY in the design reference `sdd/state/FEAT-402-supervised-wiki-ingestion/references/schemas.py`, which is **not importable** — re-implement per this spec.
- ~~`wikitoolkit ingest`~~ — no CLI command named `ingest` exists (full inventory above); closest write paths are `build` and `upsert`.
- ~~`WikiIngestOrchestrator.ingest(hint=…)`~~ / ~~`(triage=…)`~~ — `ingest` currently takes only `(source_path, wiki_config)`; the optional triage param is created by Module 6.
- ~~`AbstractClient.ask_structured`~~ / ~~`clients/base.py::ask_structured`~~ — `ask_structured` exists ONLY on `PageIndexLLMAdapter`. Client-level equivalents are `invoke(output_type=…)` / `ask(structured_output=…)`.
- ~~`WikiPageCategory.ARCHIVE`~~ — does not exist yet (7 values today); added by Module 4.
- ~~a novelty scorer~~ — no novelty/dedup scorer exists anywhere; `GroundingEvaluator` grounds claims, it does not score novelty by itself.
- ~~`WikiBookkeeper` operation enum~~ — operation tags are free strings, not an enum; do not invent one.
- ~~`sources.py` DDL~~ — the `sources` CREATE TABLE lives in `store.py:58-66`, not in `sources.py`.
- Grep trap: a naive `review.py` search matches `parrot/flows/dev_loop/code_review.py` — unrelated dev-loop code, do not touch.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Cascade + typed decision/trace models: mirror `IntentRouterMixin`
  (`bots/mixins/intent_router.py:59,123`) — pattern only, no import.
- Dual model tiers: reuse `WikiConfig.lightweight_model` / `model`
  exactly as `TwoStepIngester` does (light analysis, heavy generation).
- Structured output: `PageIndexLLMAdapter.ask_structured(prompt, TriageOutput)`.
- Weight validation: mirror `WikiConfig.validate_search_weights`
  (`models.py:114-140`) for charter weights.
- Migration: follow the `_migrate_json_manifest` compatibility precedent
  (`sources.py:657`) — additive, defaulted, old DBs open cleanly.
- Sync I/O (SQLite, file hashing) offloaded via `asyncio.to_thread`, as
  existing wiki code does. Google-style docstrings, strict type hints,
  `self.logger` — per repo rules.
- Idempotence: re-applying a manifest must reuse the
  `replace_source_slice`-style semantics so pages are replaced, not
  duplicated.

### Known Risks / Gotchas
- **Double-LLM cost on large corpora** (triage + ingestion per admitted
  doc). Mitigation: Stage-0 heuristics are free; lightweight tier for
  triage; heavy tier gray-zone-only; briefing reused as ingester `hint`.
- **Grounding-backed novelty requires the graph DB** and one
  `ground_claim` call per claim (LLM-judged). Mitigations: cap claims
  scored per doc (charter-configurable, default 3); fall back to the
  search proxy when `.parrot/graph/<wiki>.db` is absent; record the
  backend in the manifest header.
- **Blocking TUI**: questionary is synchronous. All interactive
  prompting happens before the async apply pipeline starts; the manifest
  flow avoids the problem entirely.
- **`wiki/cli.py` is a hot file** (8+ commits in 3 weeks; 2062 lines and
  growing — proposal line refs went stale in 3 days). Keep the CLI diff
  to one additive command block; put all logic in the new modules;
  rebase frequently.
- **Archive ranking exclusion touches the read path.** Keep the filter
  narrowly scoped (default exclusion of one category) and covered by
  `test_search_excludes_archive_by_default` to avoid regressing existing
  search behavior.
- **Charter drift**: decisions must be auditable against the policy that
  produced them — charter sha256 + version in every run header;
  calibration is propose-only in v1.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `PyYAML` | `>=6.0.2` (already core dep, pyproject:52) | charter loading |
| `click` | `>=8.1.7` (already core dep, pyproject:84) | CLI command |
| `rich` | `>=13.0` (already core dep, pyproject:80) | progress/report output |
| `questionary` | `>=2.1.1` (already core dep, pyproject:101) | interactive mode |

**No new runtime dependencies.**

---

## 8. Open Questions

> Decision trail: [x] items are resolved and reflected in the spec body.

- [x] **Where does HITL live given async-first?** — *Resolved in proposal*:
  manifest-file flow (`--dry-run` → edit → `--review`) as primary;
  blocking interactive mode only as an explicit small-batch option, run
  before the async pipeline. (§2 Overview, §5, §7.)
- [x] **New command vs. changing `build`?** — *Resolved in proposal*: new
  `wikitoolkit ingest` command; `build` keeps its offline contract.
  (§1 Goals/Non-Goals, §5.)
- [x] **Uniform vs. stratified audit sample?** — *Resolved in proposal*:
  stratified, 60% near-threshold / 40% uniform, charter-configurable.
  (§2, §5.)
- [x] **Claim-level admission in v1?** — *Resolved in spec Q&A (2026-08-02,
  Jesus)*: document-level admission in v1; claim extraction behind the
  experimental `--extract` flag; per-claim ingestion is a fast-follow.
  (§1 Non-Goals, §5.)
- [x] **Where do `archive` destinations live?** — *Resolved in spec Q&A
  (2026-08-02, Jesus)*: archive-routed docs become wiki pages with a new
  `archive` category excluded from default query ranking (retrievable
  via explicit filter). No separate storage plane in v1. (§2, Module 4, §5.)
- [x] **Novelty via grounding vs. store search?** — *Resolved in spec Q&A
  (2026-08-02, Jesus)*: `GroundingEvaluator` from day one, modeled as
  novelty ≈ 1 − mean claim groundedness; spec adds a search-proxy
  fallback when the graph DB is absent (verification found grounding
  requires it), with the backend recorded per run. (§2, Module 3, §5, §7.)
- [x] **Where are human decisions persisted for the few-shot loop?** —
  *Resolved in spec Q&A (2026-08-02, Jesus)*: appended to the charter's
  `examples`/`examples_file`; charter stays the single versioned policy
  artifact. (§2, Module 1, §5.)
- [x] **Default thresholds for a corporate-docs charter** — *Resolved at
  spec approval (2026-08-02, Jesus)*: calibrate on a real corpus during
  implementation to find the real values; the reference sketch
  (admit 0.75 / reject 0.35) ships only as the documented example
  charter, never as hardcoded defaults.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree
  (`.claude/worktrees/feat-402-supervised-wiki-ingestion`, branched from
  `dev`), tasks sequential.
- Modules 1-2 (charter, review) are pure-new and independent; Module 4
  (archive category) is also independent — a worker MAY parallelize
  those first three, but the default is sequential in dependency order
  (1 → 2 → 3 → 4 → 5 → 6 → 7) since Modules 3-7 form a chain.
- **Cross-feature dependencies**: none pending. Rebase on `dev` before
  touching `wiki/cli.py` (hot file).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-02 | Jesus Lara + Claude | Initial draft from proposal FEAT-402 + spec Q&A + contract re-verification on dev @ ad6365242 |
| 0.2 | 2026-08-02 | Jesus Lara | Approved; thresholds resolved: calibrate on a real corpus during implementation |
