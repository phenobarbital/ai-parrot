---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent

**Feature ID**: FEAT-481
**Date**: 2026-08-31
**Author**: Arturo Martinez
**Status**: draft
**Target version**: next minor

**Input**: `sdd/proposals/fireflies-wiki-knowledgebase-agent.brainstorm.md` (Recommended Option B; all open questions resolved)
**Operating contract (acceptance oracle)**: `sdd/references/obsidian-wiki-operating-contract.md`
**Hard dependency (merged)**: FEAT-472 fireflies-meeting-registry (PR #1264)

---

## 1. Motivation & Business Requirements

### Problem Statement

The user maintains a mature, Obsidian-based **LLM-Wiki Operating Contract**
(`sdd/references/obsidian-wiki-operating-contract.md`, 36 sections) that defines
how meeting transcripts and summaries are compiled into a trustworthy,
provenance-preserving knowledge base: immutable raw sources, canonical normalized
meeting pages, living current-state project pages, entities/concepts/
contradictions, daily-diary synthesis, and continuous integrity checks. **No
agent implements this contract today.**

The closest existing code — `FirefliesWikiAgent` (`agents/fireflies_wiki.py`) and
its parent `FirefliesObsidianAgent` (`packages/ai-parrot/src/parrot/agents/obsidian.py`)
— has the concept (fetch → Obsidian → GraphIndex) but is on the wrong side of the
contract: it dumps the raw transcript verbatim into one flat note, has no
compilation/classification/reconciliation/contradiction machinery, and (before
FEAT-472) deduped by filename. FEAT-472 has since delivered the id-keyed dedup
spine (`MeetingRegistry`, `external_id`, content fingerprints, `suggest_from_date`
watermark, no-refetch skip, `move_note`/`delete_note`) — the foundation this
feature builds on.

This feature is the **Parrot agent that faithfully executes the operating
contract**: participant-filtered Fireflies fetch (skipping already-processed
meetings), immutable `Raw/` capture, contract-shaped compilation into the user's
existing Obsidian vault, and a **derived GraphIndex/PageIndex** kept as the
primary query surface. Contract fidelity is the acceptance bar; the contract's
§34 Post-Operation Validation + §36 Quality Standard are the QA oracle.

**Who is affected**: the user (single operator) whose Fireflies meetings should
flow unattended into the governed vault without re-downloading processed
meetings, with a queryable GraphIndex alongside Obsidian.

### Goals

- **G1** A registered Parrot agent that ingests participant-filtered Fireflies
  meetings and compiles them into the user's existing contract-structured Obsidian
  vault, exactly per `obsidian-wiki-operating-contract.md`.
- **G2** **Never re-download an already-processed meeting** through the MCP —
  authoritative gate = `MeetingRegistry` (`wiki.db`) ∪ a scan of `Raw/`, with the
  `suggest_from_date` watermark; GraphIndex is never the id gate.
- **G3** **Hybrid execution**: deterministic Python owns the safety-critical spine
  (hashing, dedup gate, immutable `Raw/` moves, provenance, registry mirror,
  index maintenance, §34 validation/rollback); the LLM owns semantics
  (classification+confidence, typed extraction, project reconciliation with a
  diff-guard, contradiction detection) via `AbstractClient.invoke(output_type=…)`.
- **G4** **Immutable transcripts, no revision workflow** — a re-seen `source_id`
  is a permanent skip (contract §14.3, amended).
- **G5** **Chronological processing** — batches processed oldest→newest by
  `meeting_date`; a late-arriving older meeting never overwrites newer current
  state (contract §2 rule 16, §19 rule 10).
- **G6** **GraphIndex/PageIndex is the primary query graph**, rebuilt from the
  vault each ingest; Obsidian's wikilink graph is the secondary human-navigation
  view. Vault pages remain the content source-of-truth.
- **G7** **Model tiering** via `invoke(model=…)`: strong model for reconciliation,
  ambiguous classification, and contradiction reasoning; cheap model for bulk
  extraction and summary-first reads.
- **G8** **Contract-conformance QA**: an executable checklist derived from §34/§36
  verifies the agent's output against the contract, section by section.
- **G9** Email digests retained but **shipped disabled** behind a feature flag.

### Non-Goals (explicitly out of scope)

- **Monolithic subclass** (brainstorm Option A) and the **two-process
  producer/compiler split** (Option C) — both rejected; see
  `proposals/fireflies-wiki-knowledgebase-agent.brainstorm.md`.
- **Migrating the legacy flat `meetings/` vault** into the contract layout. The
  agent targets the user's existing contract-structured vault and produces into it
  (R2). An optional one-time backfill utility is future work.
- **A revision workflow** — transcripts are immutable (R3); no `Raw/Processed/
  Revisions/`, no `source-revision` review type, no `revision-detected` op.
- **Re-implementing the dedup registry** — reuse FEAT-472's `MeetingRegistry`.
- **Enabling email digests** — retained but off by default.
- **Changing FEAT-472's `MeetingRegistry`, `external_id`, or the wiki `sources`
  schema** — consumed as-is.

---

## 2. Architectural Design

### Overview

A dedicated **ingest flow subsystem** at `parrot/flows/wiki_ingest/` (modeled on
`parrot/flows/dev_loop/`: `definition.py` + `factories.py` + `nodes/` + `runner.py`),
driven by a thin Parrot `Agent` façade that exposes the contract's plain-English
intents (`ingest`, `query`, `health`, `lint`, `archive`, `graph`).

Each contract section maps to a pipeline node. **Deterministic nodes** own the
mechanical spine; **structured-LLM nodes** own semantics via
`AbstractClient.invoke(output_type=<PydanticModel>, model=<tier>)`. The shared
contract between nodes is a set of Pydantic frontmatter/schema models (one per
contract §10 page type) plus the §34 validation checklist rendered as an
executable function — that function **is** the QA oracle.

Three distinct authorities, kept separate and non-contradictory:
- **Content source-of-truth** = the Obsidian vault pages.
- **Dedup/identity authority** = `MeetingRegistry` (`wiki.db`, FEAT-472). The
  Markdown `Wiki/Registry/processed-sources.md` is a **derived mirror
  regenerated every ingest** (R1).
- **Primary query/relationship engine** = the derived GraphIndex/PageIndex plane,
  rebuilt from the vault each ingest (D3).

### Component Diagram

```
Fireflies MCP ──listing──▶ [FetchGate]  (reuse MeetingRegistry:
                              │           suggest_from_date + classify → create|skip)
                              ▼
                         [RawBundle]  drop transcript/summary/metadata → Raw/Incoming/
                              │        pair(§13) · sha256(§14) · move→Raw/Processed (verify)
                              ▼   (bundles sorted oldest→newest by meeting_date)
   ┌───────────────── Ingest Pipeline (parrot/flows/wiki_ingest/runner.py) ─────────────────┐
   │  [Classify+Confidence(§15)] → [ContradictionDetect(§22)] → [MeetingPage(§17)]           │
   │        → [ProjectReconcile(§19, diff-guarded, chronological)]                           │
   │        → [Entities(§20)] → [Concepts(§21)] → [DailyDiary(§23)]                           │
   │        → [Indexes/Overview(§24)] → [RegistryMirror(§25)] → [Log(§33)]                    │
   │        → [PostOpValidation(§34) ── fail ⇒ rollback compiled, queue review, no log]       │
   └────────────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
             [GraphIndexRebuild] LLMWikiToolkit.ingest_obsidian_vault(incremental=True)
                              │
     Query(§28): GraphIndex retrieval (primary) → read Obsidian pages (verify + provenance)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/agents/meeting_registry.py::MeetingRegistry` (FEAT-472) | **reuse (hard dep)** | dedup gate, `classify`, `suggest_from_date`, `fingerprint`, lifecycle stamps |
| `parrot/agents/obsidian.py::FirefliesObsidianAgent` | reuse + modify | reuse `FirefliesFilters` (participant filter) + fetch pagination; repoint sink to `Raw/Incoming/` |
| `parrot/tools/obsidian.py::ObsidianToolkit` | reuse + extend | `create_note`/`update_note`/`move_note`/`delete_note` exist; add §8.1 link-fixup; enable `move`/`delete` in `allowed_operations` |
| `parrot/clients/base.py::AbstractClient.invoke` | reuse | structured extraction (`output_type=`) + per-call model tiering (`model=`) |
| `parrot/knowledge/wiki/toolkit.py::LLMWikiToolkit` | reuse | derived GraphIndex rebuild + query |
| `parrot/knowledge/graphindex/factory.py::build_graph_memory_toolkit` | reuse | graph plane |
| `parrot/knowledge/pageindex/toolkit.py::PageIndexToolkit` | reuse | authoring plane |
| `parrot/agents/conf.py` | extend | new keys (vault path, participant allowlist, model tiers, email flag, `Raw/` roots, active-window default) |
| `parrot/registry::register_agent`, `parrot/scheduler::schedule` | reuse | agent registration + `ingest` cadence |
| `parrot/mcp/integration.py::add_fireflies_mcp_server` | reuse | transcript/summary/metadata MCP tools |
| **External Obsidian vault** (outside repo) | write target | path via config; **no auto-commit** |

### Data Models

Pydantic models (one per contract §10 page type) plus pipeline-node contracts.
Sketch (fields per contract §10 — full definitions in Module 5):

```python
# parrot/flows/wiki_ingest/models.py (new)
class MeetingSourceFrontmatter(BaseModel):   # §10.1
    id: str; type: Literal["meeting-source"]; title: str
    source_id: str                            # authoritative identity = "fireflies:<id>" (D4)
    meeting_date: str; processed_at: str
    processing_mode: Literal["summary-only", "summary-and-transcript"]
    classification_confidence: Literal["high", "medium", "low"]
    review_required: bool = False
    raw_summary: str; raw_transcript: str      # PLAIN relative paths, never wikilinks (D1)
    summary_sha256: str; transcript_sha256: str
    primary_project: str                       # invariant: primary_project ∈ projects (D2)
    projects: list[str] = []; clients: list[str] = []; people: list[str] = []
    products: list[str] = []; concepts: list[str] = []; contradictions: list[str] = []
    # ... ProjectFrontmatter (§10.2), EntityFrontmatter (§10.3), ConceptFrontmatter
    #     (§10.4), ContradictionFrontmatter (§10.5), DailyNoteFrontmatter (§10.6),
    #     SynthesisFrontmatter (§10.7)

class Classification(BaseModel):               # §15 — invoke(output_type=…)
    primary_client: str | None; primary_project: str | None
    additional_projects: list[str]; people: list[str]; products: list[str]
    concepts: list[str]; confidence: Literal["high", "medium", "low"]
    transcript_fallback_reason: str | None

class MeetingExtraction(BaseModel):            # §15.2 — invoke(output_type=…)
    decisions: list[str]; requirements: list[str]
    action_items: list[ActionItem]; risks: list[str]; open_questions: list[str]
    potential_contradictions: list[str]

class ValidationResult(BaseModel):             # §34 — the QA oracle
    passed: bool; failures: list[str]; warnings: list[str]
```

### New Public Interfaces

```python
# parrot/flows/wiki_ingest/agent.py (new)
@register_agent(name="fireflies_wiki_kb", at_startup=True)
class FirefliesWikiKBAgent(Agent):
    async def configure(self, app=None) -> None: ...
    @schedule(schedule_type=ScheduleType.CRON, ...)     # ingest cadence
    async def ingest(self, *, limit=None, force_refetch=False) -> IngestReport: ...
    async def query(self, question: str) -> QueryResult: ...
    async def health(self) -> HealthReport: ...
    async def lint(self, *, fix: bool = False) -> LintReport: ...
    async def archive(self) -> ArchiveReport: ...
    async def build_graph_report(self, target: str) -> GraphReport: ...

# parrot/flows/wiki_ingest/runner.py (new)
async def run_ingest(ctx: WikiIngestContext) -> IngestReport: ...  # §27 ordered flow
```

---

## 3. Module Breakdown

> Deterministic spine (M1–M6) is the foundation phase; semantic compilers (M7–M12)
> and workflows (M13–M16) fan out against the frozen schemas + §34 validator.

### Module 1: Subsystem scaffolding, config, agent façade
- **Path**: `parrot/flows/wiki_ingest/{__init__,agent,definition,factories,runner}.py`, `parrot/agents/conf.py`
- **Responsibility**: `parrot/flows/wiki_ingest/` package (dev_loop-shaped); `@register_agent("fireflies_wiki_kb")` façade with the six intents; conf keys (external `WIKI_KB_VAULT_PATH`, `WIKI_KB_PARTICIPANTS` allowlist, model-tier keys, `FIREFLIES_WIKI_EMAIL_ENABLED=false`, `WIKI_KB_RAW_ROOT`, `WIKI_KB_ACTIVE_WINDOW_DAYS=14`).
- **Depends on**: `parrot.registry`, `parrot.scheduler`, FEAT-472 conf.

### Module 2: Fetch-gate (reuse FEAT-472)
- **Path**: `parrot/flows/wiki_ingest/nodes/fetch_gate.py`
- **Responsibility**: participant-filtered Fireflies fetch via `FirefliesFilters`; `MeetingRegistry.suggest_from_date()` watermark; `MeetingRegistry.classify()` (∪ `Raw/` id scan) → fetch only unknown meetings; `force_refetch` override. **No revisions** — a known id is a permanent skip.
- **Depends on**: `MeetingRegistry` (FEAT-472), `add_fireflies_mcp_server`.

### Module 3: Raw bundle layer (§13/§14/§27 spine)
- **Path**: `parrot/flows/wiki_ingest/nodes/raw_bundle.py`
- **Responsibility**: drop `transcript`/`summary`/`metadata` into `Raw/Incoming/`; pair by strongest key (§13); SHA-256 hash (§14.2); immutable move to `Raw/Processed/<client>/<project>/YYYY/MM/<source-id>/` with pre/post hash verify; `Duplicates/`/`Uncategorized/` routing (§14.3/§15.5). Raw bytes never edited.
- **Depends on**: Module 2.

### Module 4: Vault access layer + §11 init + §25 mirror
- **Path**: `parrot/flows/wiki_ingest/vault.py`
- **Responsibility**: thin wrapper over `ObsidianToolkit` (enable `move`/`delete`); **§8.1 link-fixup** after move/rename (the only genuinely new toolkit piece); §11 initialization (create missing control files without overwriting); regenerate `Wiki/Registry/processed-sources.md` mirror from the DB **every ingest** (R1).
- **Depends on**: `ObsidianToolkit`, `MeetingRegistry`.

### Module 5: §10 frontmatter schemas + §34 validation (QA oracle)
- **Path**: `parrot/flows/wiki_ingest/models.py`, `parrot/flows/wiki_ingest/validation.py`
- **Responsibility**: Pydantic models for every §10 page type (incl. D1 plain-path provenance, D2 `primary_project ∈ projects` validator, D4 `source_id` identity); the §34 Post-Operation Validation checklist as an executable function returning `ValidationResult`, incl. the §19 diff-guard assertion (Q2) and the `Private/`-never-accessed assertion.
- **Depends on**: nothing new (shared contract; freeze first).

### Module 6: Ingest orchestrator (§27, chronological)
- **Path**: `parrot/flows/wiki_ingest/runner.py`, `.../nodes/__init__.py`
- **Responsibility**: the §27 ordered pipeline; **sort bundles oldest→newest by `meeting_date`** (G5); read operating context (§12); on §34 failure roll back compiled changes (never raw), queue a review item, write no success registry/log entry; print the §35 change summary; trigger the GraphIndex rebuild (Module 13).
- **Depends on**: Modules 2–5, 7–13.

### Module 7: Summary-first classification (§15)
- **Path**: `parrot/flows/wiki_ingest/nodes/classify.py`
- **Responsibility**: read Fireflies summary first; `invoke(output_type=Classification, model=<strong>)`; confidence; transcript-fallback ladder (§15.4); low-confidence → `Uncategorized/` + `review_required` (§15.5).
- **Depends on**: Modules 3, 5; `AbstractClient.invoke`.

### Module 8: Canonical meeting source page (§17)
- **Path**: `parrot/flows/wiki_ingest/nodes/meeting_page.py`
- **Responsibility**: `invoke(output_type=MeetingExtraction, model=<cheap>)` then render the §17 page (Executive Summary … Action Items table … Verified Quotes only when transcript read) under `Wiki/Sources/Meetings/`.
- **Depends on**: Modules 5, 7.

### Module 9: Project page reconciler (§19, diff-guarded)
- **Path**: `parrot/flows/wiki_ingest/nodes/project_reconcile.py`
- **Responsibility**: **typed section-merge** (no free-form whole-page regen) with `invoke(model=<strong>)`; the Q2 diff-guard — *no claim dropped while a live source still supports it*; chronological supersession (§19 rule 10); preserve `## Human Notes`; queue if `locked: true`.
- **Depends on**: Modules 5, 8.

### Module 10: Entity + concept resolvers (§20/§21)
- **Path**: `parrot/flows/wiki_ingest/nodes/entities.py`, `.../nodes/concepts.py`
- **Responsibility**: match-before-create (search filenames/titles/ids/aliases); create/update entity (§20) and concept (§21) pages; no over-creation.
- **Depends on**: Modules 5, 8; GraphIndex retrieval (Module 13) for §6 matching.

### Module 11: Contradiction protocol (§22)
- **Path**: `parrot/flows/wiki_ingest/nodes/contradictions.py`
- **Responsibility**: detect materially incompatible claims vs current knowledge **before** updating; create/update contradiction pages; link from every affected page; severity; never resolve by recency.
- **Depends on**: Modules 5, 9; GraphIndex retrieval.

### Module 12: Daily diary + indexes/overview + review queue + log
- **Path**: `parrot/flows/wiki_ingest/nodes/{daily,indexes,review_queue,log}.py`
- **Responsibility**: §23 daily synthesis (not concatenation); §24 index/overview maintenance; §26 Review Queue (allowed types minus `source-revision`); §33 append-only log (ops minus `revision-detected`).
- **Depends on**: Module 5.

### Module 13: GraphIndex derived rebuild + Query (§28)
- **Path**: `parrot/flows/wiki_ingest/graph.py`, `.../nodes/query.py`
- **Responsibility**: build the wiki toolkit (PageIndex + GraphIndex) and `ingest_obsidian_vault(incremental=True)` after each ingest; §28 query — **GraphIndex/PageIndex retrieval (primary) → read Obsidian pages** for the answer + provenance; save synthesis on request.
- **Depends on**: `LLMWikiToolkit`, `build_graph_memory_toolkit`, `PageIndexToolkit`.

### Module 14: Health / Lint / Archive / Graph workflows (§29–§32)
- **Path**: `parrot/flows/wiki_ingest/nodes/{health,lint,archive,graph_report}.py`
- **Responsibility**: §29 fast health; §30 lint (+`--fix` safe repairs); §31 archive with the **configurable active window (default 14 days)** (D7); §32 derived graph reports.
- **Depends on**: Modules 4, 5, 13.

### Module 15: Email digests (retained, disabled)
- **Path**: `parrot/flows/wiki_ingest/nodes/email.py`
- **Responsibility**: port the daily/weekly digest machinery from `agents/fireflies_wiki.py` behind `FIREFLIES_WIKI_EMAIL_ENABLED` (default false); render from the daily notes / overview delta.
- **Depends on**: Module 12.

### Module 16: Contract-conformance test suite (QA oracle)
- **Path**: `tests/integration/test_wiki_kb_contract.py`
- **Responsibility**: executable checks mapping contract §34/§36 to assertions over a fixture vault; the acceptance oracle for §5.
- **Depends on**: all.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fetch_gate_skips_known_id` | M2 | A processed `source_id` is skipped without an MCP fetch |
| `test_fetch_gate_watermark` | M2 | `from_date` derives from `suggest_from_date()` |
| `test_raw_immutable_move` | M3 | Pre/post-move SHA-256 match; raw bytes unchanged |
| `test_reseen_id_is_skip_not_revision` | M3 | Differing hash for a known id → `duplicate-skip`, never a revision |
| `test_frontmatter_primary_project_invariant` | M5 | `primary_project ∉ projects` fails validation (D2) |
| `test_raw_provenance_plain_paths` | M5 | `raw_transcript`/`raw_summary` are plain paths, not wikilinks (D1) |
| `test_validation_private_never_accessed` | M5 | §34 asserts no `Private/` access |
| `test_classify_low_confidence_routes_uncategorized` | M7 | Low confidence → `Uncategorized/` + `review_required` |
| `test_project_reconcile_diff_guard` | M9 | A claim with a live source is never dropped (Q2) |
| `test_project_reconcile_chronological` | M9 | Older late-arriving meeting does not overwrite newer state (§19 r10) |
| `test_contradiction_not_resolved_by_recency` | M11 | Both claims preserved + linked |
| `test_registry_mirror_regenerated` | M4 | `processed-sources.md` matches the DB after ingest (R1) |
| `test_link_fixup_after_move` | M4 | Backlinks rewritten after `move_note` (§8.1) |
| `test_query_graphindex_primary` | M13 | Query retrieves via GraphIndex then verifies against Obsidian pages |
| `test_email_disabled_by_default` | M15 | Digests do not send unless `FIREFLIES_WIKI_EMAIL_ENABLED` |

### Integration Tests
| Test | Description |
|---|---|
| `test_ingest_end_to_end` | Raw/Incoming bundle → canonical page + project + entities + concepts + daily + indexes + registry mirror + GraphIndex rebuild; §34 passes |
| `test_ingest_chronological_batch` | Multi-meeting batch processed oldest→newest; project state reflects the latest meeting |
| `test_ingest_validation_failure_rolls_back` | §34 failure → compiled rollback, review item, no log/registry entry, raw untouched |
| `test_contract_conformance` | M16 — assertions mapping §34/§36 over a fixture vault |

### Test Data / Fixtures
```python
@pytest.fixture
def fixture_vault(tmp_path):
    # a minimal contract-structured vault (Raw/, Wiki/, Projects/, Diary/, Private/)
    ...
@pytest.fixture
def sample_bundle():
    # transcript + Fireflies summary + metadata (with a fireflies meeting id)
    ...
```

---

## 5. Acceptance Criteria

> Complete when ALL hold. The operating contract is the oracle — each criterion
> cites the section it enforces.

- [ ] **Dedup (§14/§25, G2):** re-ingesting a processed meeting id is a no-op skip — no new/changed pages, no MCP transcript fetch.
- [ ] **Immutability (§14.3, G4):** a re-seen `source_id` with a differing hash is skipped and logged `duplicate-skip`; no revision artifacts exist anywhere.
- [ ] **Chronological (§2 r16 / §19 r10, G5):** a batch is processed oldest→newest; a late-arriving older meeting integrates as history and never overwrites newer current-state.
- [ ] **Raw immutability (§14.2):** pre/post-move hashes match; no raw file is edited, overwritten, or deleted.
- [ ] **Provenance (§10/§17, D1):** every material claim links to a source page; raw provenance uses plain relative paths, never wikilinks.
- [ ] **`primary_project ∈ projects` (D2)** enforced by §34 validation.
- [ ] **GraphIndex primary query (§28, D3/G6):** query retrieves via GraphIndex/PageIndex, then answers from the Obsidian pages with provenance; GraphIndex output is never quoted as authority. Vault remains content source-of-truth.
- [ ] **Registry authority + mirror (R1):** `MeetingRegistry` is the gate; `processed-sources.md` is regenerated from the DB every ingest and matches it.
- [ ] **Project reconcile diff-guard (§19, Q2):** no claim is dropped while a live source still supports it; `## Human Notes` and `locked: true` pages are preserved/queued.
- [ ] **Contradictions (§22):** materially incompatible claims produce a linked contradiction page; never resolved by recency.
- [ ] **Boundaries (§2 #1):** `Private/` is never read/listed/traversed; `.obsidian/` untouched; §34 asserts both.
- [ ] **Post-op gate (§34):** no registry/log success entry is written unless validation passes; failures roll back compiled changes only.
- [ ] **Contract conformance suite** (Module 16) passes — the §34/§36 oracle.
- [ ] **Email disabled (G9):** digests present but do not send unless `FIREFLIES_WIKI_EMAIL_ENABLED=true`.
- [ ] All unit + integration tests pass (`pytest tests/ -v`); `ruff`/`mypy` clean on changed files.
- [ ] No breaking change to FEAT-472 `MeetingRegistry` or the wiki `sources` schema.

---

## 6. Codebase Contract

> **Anti-Hallucination Anchor.** Every entry verified this session at the cited
> `file:line`. Implementation agents MUST NOT reference imports/attributes/methods
> not listed here without re-verifying.

### Verified Imports
```python
from parrot.agents.meeting_registry import MeetingRegistry, normalise_transcript, fingerprint  # verified: packages/ai-parrot/src/parrot/agents/meeting_registry.py:167/69/91
from parrot.agents.obsidian import FirefliesObsidianAgent, FirefliesFilters                     # verified: .../agents/obsidian.py:151/50
from parrot.tools.obsidian import ObsidianToolkit                                               # verified: .../tools/obsidian.py:78
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                                         # verified: .../knowledge/wiki/toolkit.py:54
from parrot.knowledge.wiki.models import WikiConfig                                              # verified: .../knowledge/wiki/models.py:52
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit                       # verified: .../knowledge/graphindex/factory.py:203
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                                   # verified: .../knowledge/pageindex/toolkit.py:50
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter                            # verified: .../knowledge/pageindex/llm_adapter.py:42
from parrot.registry import register_agent
from parrot.scheduler import ScheduleType, schedule
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/agents/meeting_registry.py   (FEAT-472 — reuse, do not rebuild)
def normalise_transcript(text: str) -> str:            # line 69
def fingerprint(text: str) -> str:                     # line 91  (sha256 of normalised transcript)
class MeetingRegistry:                                  # line 167
    def __init__(self, registry_dir, *, manager: SourceCollectionManager | None = None) -> None
    async def classify(self, item, *, fetch, fetch_summary, force_refetch=False) -> Classified   # line 253
    async def suggest_from_date(self, *, overlap_days: int) -> str | None                          # line 370
    # + record_synced, pending_analysis, mark_analyzed, mark_wiki_ingested, repair_path,
    #   backfill_from_vault, merge_duplicates, forget(reject=True), unique_slug, available

# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):                 # line 78
    async def read_note(self, path, include_content=True)                    # line 212
    async def list_notes(self, folder=…, recursive=…)                        # line 257
    async def search_notes(self, query, limit=20)                            # line 300
    async def create_note(self, path, content, frontmatter=None)             # line 439
    async def update_note(self, path, content, preserve_frontmatter=True)    # line 471
    async def delete_note(self, path)                                        # line 522
    async def move_note(self, source, destination) -> Dict[str, Any]         # line 538  (reports affected_backlinks; does NOT rewrite links)

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    async def invoke(self, prompt, *, output_type: Optional[type]=None,
                     structured_output=None, model: Optional[str]=None,
                     system_prompt=None, max_tokens=4096, temperature=0.0,
                     use_tools=False, tools=None) -> InvokeResult              # line 1747

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                  # line 54
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit,
                 config: WikiConfig, agent_id="agent", store=None, **kwargs)   # line 83
    async def ingest_obsidian_vault(self, wiki_name, vault_path, incremental=False,
                                    extract_entities=False, granularity="standard")  # line 295

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
async def build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent",
                                     run_id=None, embedder=None, client=None,
                                     dimension=…) -> GraphIndexToolkit          # line 203
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FetchGate` (M2) | `MeetingRegistry.classify` / `suggest_from_date` | method call | `agents/meeting_registry.py:253/370` |
| `RawBundle` (M3) | `fingerprint` | function call | `agents/meeting_registry.py:91` |
| `Classify`/`Reconcile` (M7/M9) | `AbstractClient.invoke(output_type=, model=)` | method call | `clients/base.py:1747` |
| `VaultAccess` (M4) | `ObsidianToolkit.move_note` + link-fixup | method call | `tools/obsidian.py:538` |
| `GraphIndexRebuild`/`Query` (M13) | `LLMWikiToolkit.ingest_obsidian_vault` | method call | `knowledge/wiki/toolkit.py:295` |

### Does NOT Exist (Anti-Hallucination)
- ~~auto-link-rewrite inside `ObsidianToolkit.move_note`~~ — `move_note` reports `affected_backlinks` but does **not** rewrite them; §8.1 link-fixup is new (Module 4).
- ~~`Raw/`-layer drop in `FirefliesObsidianAgent.sync_fireflies_transcripts`~~ — current sink writes a compiled note into `meetings/`; the `Raw/Incoming/` drop is new (Module 3).
- ~~server-side "exclude processed" on `fireflies_get_transcripts`~~ — MCP exposes filters + `limit` + `skip` only; dedup is client-side (Module 2).
- ~~a Markdown `processed-sources.md` writer in FEAT-472~~ — FEAT-472 stores the registry in `wiki.db` only; the §25 mirror is new (Module 4).
- ~~contradiction/entity/concept/project-reconciliation/daily-diary/lint/health/archive logic in the current Fireflies agents~~ — none exists; all new (Modules 7–14).
- ~~a revision workflow~~ — deliberately absent (R3); do not add `Revisions/`, `source-revision`, or `revision-detected`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first; `uv`-managed; Pydantic v2 for all structured data; Google-style docstrings + strict type hints; `self.logger`, never `print`.
- Model the flow subsystem on `parrot/flows/dev_loop/` (`definition.py`/`factories.py`/`nodes/`/`runner.py`).
- Deterministic nodes hold NO LLM calls; semantic nodes use `invoke(output_type=…, model=…)` only.
- **Re-check the reserved `toolmanager-tooldefinition-enforcement` feature** before finalizing how the agent declares its tools (Q1 note).
- Freeze Module 5 (schemas + §34 validator) first — it is the shared contract that unblocks parallel fan-out.

### Known Risks / Gotchas
- **Per-meeting cost/latency (§27):** the pipeline touches many pages per meeting with strong-model reasoning — bound with model tiering (G7) and batching; do not run the whole pipeline on the cheap model.
- **Project-page rewrite is the highest-risk step:** enforce the Q2 diff-guard (typed section-merge + "no live-sourced claim dropped") in §34 — never free-form whole-page regeneration.
- **Chronological correctness:** always sort by `meeting_date` before processing; a late-arriving older meeting must not regress newer state.
- **Prompt injection:** transcripts are untrusted (§2 #11) — classification/links derived from them are re-validated against the untrusted-source rule; `Private/` links are rejected.
- **GraphIndex derived, never the gate:** a lost/stale GraphIndex or `processed-sources.md` mirror must never cause a re-download or wrong skip — the DB is the authority.
- **`LLMWikiToolkit._config_for` raises on `wiki_name` mismatch** — one toolkit per wiki plane.
- **`move_note` does not rewrite backlinks** — always run link-fixup after a move/rename.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` (already required) | §10 schemas + `invoke` output types |
| `python-frontmatter` | already used by `ObsidianToolkit` | parse/preserve YAML frontmatter |
| `hashlib` (stdlib) | — | SHA-256 raw provenance (aligns with FEAT-472 `fingerprint`) |
| `PyYAML` (already used) | — | frontmatter render |

No new third-party dependencies.

---

## 8. Open Questions

> All resolved before spec. Recorded for the decision trail (owner: Arturo Martinez).

- [x] Runner model? — *Resolved in brainstorm*: a single Parrot agent (Option B — contract-as-pipeline), hybrid deterministic spine + structured-LLM semantics.
- [x] R1 — Registry authority + mirror cadence? — *Resolved*: `MeetingRegistry` (`wiki.db`) is authoritative; `processed-sources.md` regenerated from the DB every ingest. *(contract amended §25/§12/§14.2)*
- [x] R2 — Vault migration? — *Resolved*: no migration; target the existing contract-structured vault and produce into it; legacy backfill optional/out-of-scope.
- [x] R3 — Revise policy? — *Resolved*: transcripts immutable; no revision workflow; re-seen id = permanent skip. *(contract amended §2 r16/§14.3/§4/§26/§30/§33)*
- [x] D1 — Raw provenance links? — *Resolved*: plain relative paths, never wikilinks. *(contract amended §10.1/§17)*
- [x] D2 — `primary_project ∈ projects[]`? — *Resolved*: invariant added; §34 asserts it. *(contract amended §10.1)*
- [x] D3 — Graph primacy? — *Resolved*: GraphIndex/PageIndex primary query graph; Obsidian graph secondary; vault = content SoT. *(contract amended §4/§28/§32)*
- [x] D4 — Authoritative id? — *Resolved*: `source_id: "fireflies:<id>"` (= FEAT-472 `external_id`).
- [x] D5 — Fingerprint fields? — *Resolved*: FEAT-472 `sha256(normalise_transcript(text))`, summary hashed separately.
- [x] D6 — Embeddings vs groundedness? — *Resolved*: internal indexes over repo content are not "external knowledge". *(contract amended §2 r15/§28)*
- [x] D7 — Active window? — *Resolved*: configurable, default 14 days. *(contract amended §18/§27/§30/§31)*
- [x] D8 — Query read path? — *Resolved*: GraphIndex retrieval → Obsidian verify (via D3, §28).
- [x] NEW — Chronological order? — *Resolved*: oldest→newest by `meeting_date`; late older meeting never overwrites newer state. *(contract amended §2 r16/§27/§19)*
- [x] Q1 — Agent home? — *Resolved*: new flow subsystem `parrot/flows/wiki_ingest/`.
- [x] Q2 — §19 diff-guard? — *Resolved*: typed section-merge + "no live-sourced claim dropped" §34 assertion.
- [x] Q3 — Fetch watermark? — *Resolved*: FEAT-472 `suggest_from_date()`.
- [x] Q4 — Scheduling/email flag? — *Resolved*: `@schedule` `ingest`; `FIREFLIES_WIKI_EMAIL_ENABLED` default false.

---

## Worktree Strategy

- **Default isolation unit**: **mixed**.
- **Foundation phase (sequential, one worktree `feat-481-fireflies-wiki-knowledgebase-agent`)**: Module 1 (scaffolding/config) → Module 5 (schemas + §34 validator) → Modules 2–4 (fetch-gate, raw-bundle, vault access). These define the shared contract and the deterministic spine; freeze before fan-out.
- **Fan-out phase (parallelizable once Module 5 is frozen)**: the semantic compilers (M7 meeting page, M9 project reconcile, M10 entities/concepts, M11 contradictions) and the read-only workflows (M13 query, M14 health/lint/archive/graph) are largely independent; M12 (daily/indexes/review/log), M15 (email), M16 (conformance suite) likewise.
- **Cross-feature dependencies**: **FEAT-472 (merged)** — hard dependency, satisfied. No in-flight spec targets the shared files (`obsidian.py`, `ObsidianToolkit`); re-verify at `/sdd-task`. Coordinate with the reserved `toolmanager-tooldefinition-enforcement` before finalizing the tool surface.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Arturo Martinez | Initial draft from brainstorm (Option B); all decisions resolved; contract amended R1–R3/D1–D8 + chronological |
