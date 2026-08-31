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
- **G7** **Provider-agnostic, tiered LLMs.** Two clients built from `provider:model`
  config strings via `LLMFactory` — a *strong* tier (reconciliation, ambiguous
  classification, contradiction reasoning) and a *cheap* tier (bulk extraction,
  summary-first reads). Defaults to **Google/Gemini** (GOOGLE API is configured),
  overridable to **Claude** (`anthropic:…`) or **Codex** (`openai-codex:…`) — any
  `SUPPORTED_CLIENTS` provider. Same-provider tiers may additionally use
  `invoke(model=…)`.
- **G8** **Contract-conformance QA**: an executable checklist derived from §34/§36
  verifies the agent's output against the contract, section by section.
- **G9** Email digests retained but **shipped disabled** behind a feature flag.
- **G10** **Short-interval scheduling with catch-up.** Runs on a configurable cron
  (default **hourly**), so each iteration processes a small batch. The
  `suggest_from_date` watermark makes a run after downtime automatically fetch the
  backlog; a manual `ingest(since=…|lookback_days=…, limit=…, force_refetch=…)`
  widens the window for a large reconciliation, processed **chronologically**.
- **G11** **Additive-only.** A net-new agent that reuses existing code by import /
  inheritance / composition — it modifies no existing agent, toolkit, or their
  tests.

### Non-Goals (explicitly out of scope)

- **Modifying any existing agent, toolkit, or their behavior.** This is a NET-NEW
  agent that reuses existing code by **import / inheritance / composition only** —
  no edits to `agents/obsidian.py`, `agents/fireflies_wiki.py`,
  `tools/obsidian.py`, or the FEAT-472 files. Existing agents keep their current
  behavior; their test suites must stay green.
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

**Execution model.** The agent holds two LLM clients built from `provider:model`
config strings via `LLMFactory` (strong + cheap tier, G7), defaulting to
Google/Gemini. It runs on a configurable cron (default hourly, G10): each run
fetches only meetings newer than the `MeetingRegistry` watermark, so iterations
stay small; a run after downtime, or a manual wide-window `ingest`, simply carries
a larger (still chronological) batch. **Additive-only** (G11): all reuse is by
import/inheritance/composition — the new agent instantiates its own
`ObsidianToolkit` and inherits `add_fireflies_mcp_server` from `MCPEnabledMixin`,
editing no existing file.

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
| `parrot/agents/obsidian.py::FirefliesObsidianAgent` | reuse (**no edits**) | import `FirefliesFilters`; mirror the fetch/pagination *pattern* in the new agent's own loop — do NOT modify this file |
| `parrot/mcp/integration.py::MCPEnabledMixin.add_fireflies_mcp_server` | inherit (**no edits**) | `BasicAgent` already mixes it in; the new agent calls it directly |
| `parrot/tools/obsidian.py::ObsidianToolkit` | reuse (**no edits**) | the new agent creates its **own** instance with `allowed_operations` incl. `move`/`delete` (constructor arg — no class change); §8.1 link-fixup is a **new** helper in `wiki_ingest/vault.py` |
| `parrot/clients/factory.py::LLMFactory` | reuse | build the strong/cheap tier clients from `provider:model` strings (`create`/`parse_llm_string`) |
| `parrot/clients/base.py::AbstractClient.invoke` | reuse | structured extraction (`output_type=`) + optional same-provider `model=` tiering |
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
- **Path**: `parrot/flows/wiki_ingest/{__init__,agent,definition,factories,runner,conf}.py` (**own `conf.py` — do NOT touch `parrot/agents/conf.py`**)
- **Responsibility**: `parrot/flows/wiki_ingest/` package (dev_loop-shaped); `@register_agent("fireflies_wiki_kb")` façade (`Agent` subclass) with the six intents; a self-contained `conf.py`: `WIKI_KB_VAULT_PATH` (external vault), `WIKI_KB_PARTICIPANTS` (fetch allowlist), `WIKI_KB_LLM_STRONG` / `WIKI_KB_LLM_CHEAP` (`provider:model` strings; default `google:gemini-2.5-pro` / `google:gemini-2.5-flash`, exact ids via env; may be set to `anthropic:…` or `openai-codex:…`), `WIKI_KB_INGEST_CRON` (default `"0 * * * *"`, hourly), `WIKI_KB_INGEST_LIMIT` (per-run cap), `WIKI_KB_MAX_CATCHUP_DAYS` (large-backlog guard), `FIREFLIES_SYNC_OVERLAP_DAYS` (reuse FEAT-472), `WIKI_KB_ACTIVE_WINDOW_DAYS=14`, `WIKI_KB_RAW_ROOT`, `FIREFLIES_WIKI_EMAIL_ENABLED=false`.
- **Depends on**: `parrot.registry`, `parrot.scheduler` (`add_cron`/`@schedule`), `LLMFactory`, FEAT-472 conf (imported, not edited).

### Module 2: Fetch-gate + scheduling (reuse FEAT-472, additive)
- **Path**: `parrot/flows/wiki_ingest/nodes/fetch_gate.py`
- **Responsibility**: the new agent's **own** fetch loop — inherits `add_fireflies_mcp_server` (`MCPEnabledMixin`), imports `FirefliesFilters` (participant allowlist), defines its own small `_call_fireflies_tool` helper (does NOT modify `obsidian.py`). Gate = `MeetingRegistry.suggest_from_date()` watermark + `MeetingRegistry.classify()` (∪ a `Raw/` id scan) → fetch only unknown meetings; `force_refetch` / `since` / `lookback_days` override for wide-window catch-up. **No revisions** — a known id is a permanent skip. Hourly cron keeps each run small; a post-downtime run naturally spans a larger window (bounded by `WIKI_KB_MAX_CATCHUP_DAYS`).
- **Depends on**: `MeetingRegistry` (FEAT-472), `MCPEnabledMixin`, `FirefliesFilters`.

### Module 3: Raw bundle layer (§13/§14/§27 spine)
- **Path**: `parrot/flows/wiki_ingest/nodes/raw_bundle.py`
- **Responsibility**: drop `transcript`/`summary`/`metadata` into `Raw/Incoming/`; pair by strongest key (§13); SHA-256 hash (§14.2); immutable move to `Raw/Processed/<client>/<project>/YYYY/MM/<source-id>/` with pre/post hash verify; `Duplicates/`/`Uncategorized/` routing (§14.3/§15.5). Raw bytes never edited.
- **Depends on**: Module 2.

### Module 4: Vault access layer + §11 init + §25 mirror (own toolkit instance)
- **Path**: `parrot/flows/wiki_ingest/vault.py`
- **Responsibility**: owns its **own** `ObsidianToolkit(vault_path=WIKI_KB_VAULT_PATH, allowed_operations={read,list,search,create,update,move,delete})` — a constructor arg, **no edit to `tools/obsidian.py`**; **§8.1 link-fixup** after `move_note`/rename (new helper — `move_note` reports `affected_backlinks` but does not rewrite them); §11 initialization (create missing control files without overwriting); regenerate `Wiki/Registry/processed-sources.md` mirror from the DB **every ingest** (R1).
- **Depends on**: `ObsidianToolkit` (own instance), `MeetingRegistry`.

### Module 5: §10 frontmatter schemas + §34 validation (QA oracle)
- **Path**: `parrot/flows/wiki_ingest/models.py`, `parrot/flows/wiki_ingest/validation.py`
- **Responsibility**: Pydantic models for every §10 page type (incl. D1 plain-path provenance, D2 `primary_project ∈ projects` validator, D4 `source_id` identity); the §34 Post-Operation Validation checklist as an executable function returning `ValidationResult`, incl. the §19 diff-guard assertion (Q2) and the `Private/`-never-accessed assertion.
- **Depends on**: nothing new (shared contract; freeze first).

### Module 6: Ingest orchestrator (§27, chronological, catch-up-aware)
- **Path**: `parrot/flows/wiki_ingest/runner.py`, `.../nodes/__init__.py`
- **Responsibility**: the §27 ordered pipeline; **sort the whole batch oldest→newest by `meeting_date`** (G5) — so an hourly run and a large post-downtime catch-up both reconcile in temporal order; process in bounded chunks (`WIKI_KB_INGEST_LIMIT`) so a big backlog spans several runs without one giant transaction; read operating context (§12); on §34 failure roll back compiled changes (never raw), queue a review item, write no success registry/log entry; print the §35 change summary; trigger the GraphIndex rebuild (Module 13).
- **Depends on**: Modules 2–5, 7–13.

### Module 7: Summary-first classification (§15)
- **Path**: `parrot/flows/wiki_ingest/nodes/classify.py`
- **Responsibility**: read Fireflies summary first; **strong-tier client** `invoke(output_type=Classification)`; confidence; transcript-fallback ladder (§15.4); low-confidence → `Uncategorized/` + `review_required` (§15.5).
- **Depends on**: Modules 3, 5; `AbstractClient.invoke`.

### Module 8: Canonical meeting source page (§17)
- **Path**: `parrot/flows/wiki_ingest/nodes/meeting_page.py`
- **Responsibility**: **cheap-tier client** `invoke(output_type=MeetingExtraction)` then **deterministically render** the exact §17 template (Executive Summary … Action Items table … Verified Quotes only when transcript read) under `Wiki/Sources/Meetings/` — see §3.1.
- **Depends on**: Modules 5, 7.

### Module 9: Project page reconciler (§19, diff-guarded)
- **Path**: `parrot/flows/wiki_ingest/nodes/project_reconcile.py`
- **Responsibility**: **typed section-merge** (no free-form whole-page regen) with the **strong-tier client**; the Q2 diff-guard — *no claim dropped while a live source still supports it*; chronological supersession (§19 rule 10); preserve `## Human Notes`; queue if `locked: true`.
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

## 3.1 Contract Operationalization

> This section answers "where are the contract's per-section rules, page
> templates, and workflows implemented?" — every section of
> `obsidian-wiki-operating-contract.md` maps to a module/node here.

**Page templates are rendered deterministically.** Every contract page template
(§17 meeting, §19 project, §20 entity, §21 concept, §22 contradiction, §23 daily,
and the §10 frontmatter blocks) is implemented as a Python **renderer** in
`parrot/flows/wiki_ingest/render/` that reproduces the template's **exact heading
structure verbatim**. The LLM never emits page markdown directly: it returns a
validated Pydantic model (via `invoke(output_type=…)`) whose typed fields the
renderer places into the fixed structure. This guarantees structural fidelity
(headings, section order, tables), makes conformance testable heading-by-heading
(§36 / Module 16), and confines the LLM to *content*, not *layout*. Human-authored
regions (`## Human Notes`, `locked: true` pages) are read and re-emitted unchanged.

**Contract §-section → implementation map** (every section is covered):

| Contract § | What it defines | Handled by | How |
|---|---|---|---|
| §2 Non-Negotiable Rules | 16 hard rules | M5 validator + all nodes | each rule → a §34 assertion (Private/ boundary, immutable Raw, chronological, untrusted-source, no-double-process, contradiction-preserve, immutability/no-revision) |
| §3 Ownership & Permissions | who may write where | M4 vault layer | writes scoped to `Wiki//Projects//Diary/`; never `Private//.obsidian/` |
| §4 Repository Layout | the vault tree | M4 (§11 init) + renderers | create missing dirs without overwrite; renderers write to the exact paths |
| §5 Core Knowledge Layers | raw→meeting→project→wiki→diary | M3 / M8 / M9 / M10–M11 / M12 | one module per layer |
| §6 Supported User Intents | plain-English commands | M1 agent façade | `ingest`/`query`/`health`/`lint`/`archive`/`graph` |
| §7 Safe Tool Use | scoped tools | M4 + deterministic nodes | path-scoped reads/writes; no source-script execution |
| §8 Obsidian Conventions | links/filenames/tags/dates | renderers + M4 link-fixup | filename helpers; ISO dates; wikilinks for pages, plain paths for raw (D1) |
| §9 Page Protection / Human Notes | `locked`, `## Human Notes` | M9 + all renderers | read-and-preserve verbatim; queue locked-page updates |
| §10 Required Frontmatter | 7 frontmatter schemas | **M5 Pydantic models** + renderers | one model per page type; renderers emit the YAML block |
| §11 Initialization | create control files | M4 | idempotent; no overwrite |
| §12 Startup Context | read index/overview/registry/review | M6 | first steps of the pipeline |
| §13 Bundle Discovery & Pairing | pair transcript/summary/metadata | M3 | strongest-key pairing; incomplete → review item |
| §14 Deduplication & Identity | source_id, hashes, outcomes | M2 (gate) + M3 (hash/move) + M4 (mirror) | immutable skip; no revisions (R3) |
| §15 Classification Rules | summary-first, confidence, fallback | **M7** | `invoke(output_type=Classification)` |
| §16 New Project Creation | when/how to create a project | M9 | create project structure in the same ingest |
| §17 Meeting Source Page | page template | **M8 renderer** | exact §17 headings; Verified Quotes only if transcript read |
| §18 Project Meeting Indexes | active + archive index | M9 + M12 | windowed active list; archive by YYYY/MM |
| §19 Project Page | template + update rules | **M9 renderer + reconciler** | typed section-merge + Q2 diff-guard + chronological supersession |
| §20 Entity Page | template | **M10 renderer** | match-before-create |
| §21 Concept Page | template | **M10 renderer** | material concepts only |
| §22 Contradiction Protocol | template + mandatory rules | **M11 renderer** | first-class records; linked; never recency-resolved |
| §23 Daily Note | template | **M12 renderer** | synthesis, not concatenation |
| §24 Index & Overview | navigation + living overview | M12 | update after every write |
| §25 Processed Source Registry | grep-friendly mirror | M4 | regenerated from the DB every ingest (R1) |
| §26 Review Queue | human-judgment queue | M12 | allowed types minus `source-revision` |
| §27 Ingest Workflow | the 24 ordered steps | **M6 orchestrator** | each step → a node call, oldest→newest |
| §28 Query Workflow | retrieval + synthesis | **M13** | GraphIndex retrieval → Obsidian verify (D3/D8) |
| §29 Health | fast operational check | M14 | read-only |
| §30 Lint (+`--fix`) | integrity scan | M14 | safe auto-fixes only |
| §31 Archive | rolling window | M14 | configurable window, default 14 (D7) |
| §32 Graph | derived reports | M13 + M14 | GraphIndex primary; `Wiki/Graph/` derived-only |
| §33 Log Format | append-only op log | M12 | ops minus `revision-detected` |
| §34 Post-Op Validation | the integrity checklist | **M5 validator** | the executable QA oracle; gates registry/log writes |
| §35 Change Summary | required final report | M6 | printed after each operation |
| §36 Quality Standard | health definition | **M16 conformance suite** | the acceptance oracle for §5 |

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
- [ ] **Additive-only (G11):** no existing agent/toolkit file is modified; the existing suites for `agents/obsidian.py`, `agents/fireflies_wiki.py`, and `tools/obsidian.py` stay green.
- [ ] **Scheduling + catch-up (G10):** default cron is hourly; a run after simulated downtime ingests the missed meetings in `meeting_date` order; a manual wide-window `ingest(lookback_days=…)` reconciles a large backlog chronologically in bounded chunks.
- [ ] **Provider-agnostic LLM (G7):** model tiers are `provider:model` config strings; the agent runs on Google by default and on Claude/Codex when configured, with no code change.
- [ ] **Page-template fidelity (§3.1):** rendered pages match the contract's exact §17/§19/§20/§21/§22/§23 heading structure verbatim; the LLM supplies only field content.
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
from parrot.scheduler import ScheduleType, schedule   # @schedule(ScheduleType.CRON, …); 5-field cron via add_cron — verified: scheduler/inprocess.py:83
from parrot.clients.factory import LLMFactory         # verified: clients/factory.py SUPPORTED_CLIENTS — google:127, claude/anthropic:108-109, openai-codex:146-147; LLMFactory.create/parse_llm_string
from parrot.mcp.integration import MCPEnabledMixin     # verified: mcp/integration.py:1341; add_fireflies_mcp_server:1447 — inherited by BasicAgent, no edit needed
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
- Deterministic nodes hold NO LLM calls; semantic nodes call the strong/cheap **tier clients** (`invoke(output_type=…)`) only. **Page markdown is rendered by Python, never emitted by the LLM** (§3.1).
- **Additive-only (G11):** reuse existing code by import/inheritance/composition; **never edit** `agents/obsidian.py`, `agents/fireflies_wiki.py`, `tools/obsidian.py`, or FEAT-472 files. All new behavior lives under `parrot/flows/wiki_ingest/`.
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
| `google-genai` (already installed) | — | default Google/Gemini tier via `GoogleGenAIClient` |

No new third-party dependencies — provider SDKs (Google / Anthropic / OpenAI-Codex) already ship with ai-parrot; the model tier is a config string, not a new import.

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
