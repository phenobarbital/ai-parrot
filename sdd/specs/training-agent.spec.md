---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns (FEAT-576) — carried from the proposal.
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations, ai-parrot-loaders]
# tags: free-form kebab-case keywords (FEAT-576) — carried from the proposal.
tags: [knowledge-graph, ontology, manuals, procedures, figures, video, media-delivery, guided-mode]
---

# Feature Specification: Procedure Graph — field-training agent over equipment assembly manuals

**Feature ID**: FEAT-601 (reserved by `/sdd-proposal` on 2026-09-24, ledger label `training-agent`; reused verbatim — no second reservation)
**Date**: 2026-09-25
**Author**: Jesus Lara (drafted with Claude)
**Status**: approved — all §8 questions resolved 2026-09-25
**Target version**: next minor release
**Exploration**: `sdd/proposals/training-agent.brainstorm.md` (Option B) → `sdd/proposals/training-agent.proposal.md` (FEAT-601, status `review`, U1–U5 resolved) → external review `sdd/state/FEAT-601/review.md` (R1–R4 all CONFIRM)

---

## 1. Motivation & Business Requirements

### Problem Statement

Field technicians need to ask "how do I assemble equipment X?" and get back the **ordered** steps, what to have ready before starting, the safety warnings, the figure that goes with each step, the segment of the training video that shows it, and the tips other technicians left. The source of truth is a set of vendor assembly and maintenance manuals (PDF, some DOCX) that are revised over time.

Plain RAG over chunked manuals is the wrong shape for this content:

1. **Procedures are ordered; chunks are not.** Top-k retrieval returns steps 2, 5 and 9 with no way to know 3, 4 and 6–8 are missing, and the model fills the gaps. For an assembly procedure a silently missing step is the worst possible failure.
2. **Figures are referenced, not embedded.** Nothing in the ingestion path keeps figures: `extract_markdown_per_page` calls `pymupdf4llm.to_markdown(path, page_chunks=True)` with no image output, `PDFLoader.is_image_only` uses `page.get_images()` only to *skip* pages, and `PDFMarkdownLoader.extract_images` is a stored flag nothing reads (proposal F013, F015, F031).
3. **Prerequisites and hazards are cross-cutting.** "What do I need before I start?" is a union across steps; "what other equipment shares this sub-assembly?" is a graph question.
4. **Field knowledge has nowhere to live.** Technician tips either pollute the manual's text or are lost on the next re-ingest.

`knowledge/contracts/` (FEAT-539) already shipped the pattern this needs — a per-document card with per-field provenance, a deterministic graph loader into the ArangoDB ontology store, a domain toolkit with one action per tool, and an answer released only after verification. The manual case is that pattern plus **figures** and **video segments** as first-class graph nodes.

### Goals

- **G1 — LLM proposes, deterministic decides.** Step order, prerequisites, hazards and which media goes with which step come out of the graph by traversal. The LLM extracts at ingest (with evidence) and drafts optional prose at answer time; it never selects or orders steps and never chooses media.
- **G2 — Every extracted fact carries evidence.** `Evidence(node_id, quote, page)` / `Extracted[T]` / `FieldProvenance` reused from the shared provenance module (U2). A step with no verbatim supporting quote is rejected at carding, never stored with low confidence.
- **G3 — Tips survive re-ingest.** Technician content lives in collections the loader never reconciles and is re-linked by immutable step identity, then exact normalized-content equality; anything else becomes a curator candidate (U3, R1).
- **G4 — Media are references.** Figures go to object storage through `FileManagerInterface`; the graph holds storage keys and captions; presigned URLs are minted per answer after release, never stored (U1).
- **G5 — Channel-agnostic, verified answers.** A `ProcedureAnswer` is assembled deterministically from the selected manual revision and released only after completeness verification; ordinary `ask()` on the agent goes through that gate (U4, R2, R3).
- **G6 — Authorization through the ontology, default deny.** Tenant-wide `has_role: technician` reads in v1 on every read path (traversals, catalog search, PageIndex fallback, media signing, tips, guided resume); curator role for verify/publish (U5, R4).
- **G7 — Bitemporal procedure versions.** `Procedure.versions[]` with `valid_from` inclusive / `valid_to` exclusive, `null` = current; a manual revision is a new version of each procedure it touches.
- **G8 — No new heavy dependency.** `pymupdf`/`pymupdf4llm` (pinned), `rapidfuzz`, `bm25s`, ArangoDB via `asyncdb`, and the existing vision entry points.
- **G9 — Validation-first.** The four spikes (figure pairing, media round-trip, video alignment, tip survival) are the first milestone (M0) and gate M5–M9 sign-off.
- **G10 — Applicability by serial / model year (Q7, v1).** A step carries structured `Applicability` (model qualifiers + serial ranges) extracted with evidence; the answer path resolves it against the technician's declared serial and never shows a step that does not apply, nor hides one it cannot decide — undecidable ⇒ the step is shown with an explicit applicability note.
- **G11 — Exploded-view callouts (Q8, v1).** Numbered callouts in an exploded view map to `Part` nodes through a vision structured-output pass (`ask_to_image(structured_output=CalloutMap)`); "which one is part 7?" is a `depicts` traversal. The pass is gated on spike 1 passing for plain figure pairing.
- **G12 — Offline bundle (Q9, v1).** `parrot manuals export <manual_id>` produces a self-contained bundle (manifest, procedures, steps, applicability, hazards, tips, figures as files with captions, video deep links) for a per-device viewer. The viewer itself is not built here.

### Non-Goals (explicitly out of scope)

- OCR for scanned / image-only manuals — refused with a clear message in v1 (`PDFLoader.is_image_only` semantics kept).
- The per-device **viewer** that consumes the export bundle (G12) — the bundle format is in scope, the app is not.
- A generic `OntologyToolkit` exposing traversal patterns to any agent.
- Re-hosting vendor video; keyframe extraction; timecoded Gemini scene parsing at loader level.
- Changing `OntologyRefreshPipeline` semantics — the loader is the write path, as in contracts (proposal F012).
- Admin UI curator view (follow-up, same shape as the contracts verification queue).
- Certification-gated reads: the client confirmed (Q1, 2026-09-25) that equipment certification is **not** an access requirement.
- Renaming `Citation.contract_id` / `EvidenceRef.contract_id` to `doc_id`, generalizing `EvidenceArchive`, or moving `ContractVersion`/`ContractAnswer` (U2 narrowed).
- Unenforced `certified_for` relation "reserved for later" (U5, R4).
- Options A (books + PageIndex only), C (wiki plane) and D (long-context prompt) were rejected in the brainstorm; A survives only as the in-graph fallback retrieval path (`answer_kind="lookup"`).

---

## 2. Architectural Design

### Overview

Copy the contracts architecture one level up: the **document** gets a card (`ManualCard`), the **procedures inside it** become graph entities, and the agent reads the graph through a domain toolkit whose tools are pure traversals. Everything is additive inside existing packages; the only shared-core edits are the provenance extraction (M1), the media-delivery seam (M12) and CLI/packaging registration (M13).

**Ingest** (`parrot manuals add <file> --equipment "Model X" --revision B`): sha256 dedup → markdown (PDF via `pymupdf4llm` **with** `write_images`, DOCX via the existing heading promotion) → staged PageIndex tree (`create_tree` → `insert_markdown` → `get_tree` → `derive_toc`) → figure extraction with bboxes and caption regex → three-pass carding (header, per-procedure, deterministic `assemble_card`) → vision captions for figures (capability-resolved `ask_to_image`) → upload figures via `FileManagerInterface.upload_file` → `ManualCatalogStore.upsert(card, version=…)` → `ManualGraphLoader.publish_all()` → tip re-link report → verification-queue entry.

**Video** (`parrot manuals add-video <url> --manual <id>`): `YoutubeLoader` / `VideoLocalLoader` whisper blocks (`transcript_to_blocks`: `start_seconds`/`end_seconds`/`text`) → `bm25s` step ↔ block alignment with ordinal hints → `Media(kind="video_segment", uri, t_start, t_end)` above threshold; below threshold an LLM-judged tail with a judgement log and `--force` (bookstore `relate_books` pattern). Coverage < 30 % ⇒ procedure-level `role="overview"` only.

**Answer** (any channel): `ProceduresAgent.ask()` → transport adapter → `ProceduresAnswerService.answer()`: `ProcedureRetrieval.authorize` → hybrid entry resolution (catalog FTS on equipment/procedure names with `rapidfuzz`, `Clarification` when ambiguous; PageIndex `search` over the manual tree as fallback) → deterministic trigger-table plan → AQL traversal → **`assemble_procedure`** (ordered steps, prerequisites, hazards, media refs, citations from the selected revision) → **`ProcedureVerifier`** (completeness + evidence; a missing required step or unsupported critical field **blocks** release as a complete procedure) → audit row → presign media → released `ProcedureAnswer` wrapped in an `AIMessage` carrying `image_urls` / `media_urls` (M12) so Teams/Slack render URLs and Telegram/WhatsApp deliver files.

**Guided mode** ("guíame"): `proc_start_guided` calls `begin_task(goal=<procedure title>, steps=[{label: step_id, title, description, required: True, depends_on_labels: [prev]}], plan_complete=True)`; `proc_next_step` / `proc_mark_done` wrap `update_step(expected_revision=…)` / `set_resume_hint`; `proc_resume` uses `recall_task` + `select_task` with the durable `TaskAssociationStore` so "¿dónde me quedé?" works the next day; completion records `record_episode(category=EpisodeCategory.WORKFLOW_PATTERN, metadata={procedure_id, manual_id, revision})` — no core enum change.

**Tips** ("anota que el clip de la rev B va al revés"): `proc_add_tip` (confirming tool) writes a `Tip` node into the technician-owned collection `tech_tip` with `origin="technician"`, `author_employee_id` from the trusted `RequestContext` (never model-supplied), and a `tech_tip_on` edge to the step. Visible from the next answer on (moderation remains an open question, §8).

**Applicability** (Q7): pass 2 captures "for model …" / "from S/N …" / "serial numbers 2024-0001 and later" qualifiers as evidence-backed `Applicability` on each step (`models[]`, `serial_ranges[]` with vendor-format-preserving `SerialRange(start, end, format)`); the technician's serial arrives in the trusted `RequestContext.equipment_serial` (asked once per session when the resolved procedure has any serial-qualified step); `assemble_procedure` filters with `applies(step, …)` and marks undecidable steps (`applicability="unknown"`) instead of dropping them.

**Callouts** (Q8): for every figure whose caption or step evidence mentions callout numbers, M6 runs one `ask_to_image(prompt, image, structured_output=CalloutMap)` call (all three providers accept `structured_output` — §6) and resolves each callout label to a `Part` from the header parts table by part number or `similarity ≥ 0.85`; resolved callouts become `depicts(Media → Part, callouts[])` edges; unresolved ones stay on the media node as `unresolved_callouts[]` and enter the verification queue. `proc_find_part(media_id, callout)` answers "which one is part 7?". The pass runs only when spike 1 passes.

**Export** (Q9): `parrot manuals export <manual_id> --out <dir>` writes `<manual_id>-<revision>.bundle/` (`manifest.json` with manual/revision/generated_at/sha256s, `procedures.json` with steps, applicability, hazards, prerequisites, media roles, active tips, `figures/<media_id>.png` downloaded from storage, `captions.json`, `videos.json` with URIs + `t_start`/`t_end`) and an optional `.zip`; no presigned URLs, no graph internals; authorized as a curator action.

**Re-ingest** (`parrot manuals refresh <manual_id> <file>`): new card revision, `Procedure.versions[]` appended (`valid_from = now`, previous `valid_to = now`), `publish_all()` reconciles only manual-owned collections, then the explicit, idempotent `relink_tips(manual_id)` operation re-attaches `tech_tip_on` edges by `step.source_identity` → exact `content_hash` equality → curator candidates (`rapidfuzz` on *text*, never on hashes); orphans keep `orphaned=true` with their source revision; the publication report carries link-maintenance failures instead of claiming success.

### Component Diagram

```
                     ┌──────────────────────────── ai-parrot (core) ────────────────────────────┐
  manual.pdf ──► ManualLibrary ──► figures.py ──► FileManagerInterface (S3)   knowledge/common/provenance.py
                 │  (M8)            (M6)  ▲                                        (M1: Evidence/Extracted/…)
                 │                        │ pdf_to_markdown.extract_page_images         ▲
                 ├─► carding.py (M5) ─────┘                                              │
                 ├─► video.py   (M7)  ◄── parrot_loaders.basevideo.transcript_to_blocks   │
                 ▼                                                                       │
          ManualCard (M2) ──► ManualCatalogStore/Postgres (M4) ──► ManualCardDataSource ──┤
                 │                                                        (M8)          │
                 ▼                                                                       │
          ManualGraphLoader (M9) ──► OntologyGraphStore (ArangoDB)  ◄── procedures.ontology.yaml (M3)
                 │  owned: equipment/manual/procedure/step/part/tool/hazard/media/edges
                 │  never touched: tech_tip, tech_tip_on, tech_tip_by   ◄── relink_tips (M9)
                 └──────────────────────────────────────────────────────────────────────┘
                                          │ AQL traversal patterns
  ┌──────────────────────── ai-parrot-tools/parrot_tools/procedures ────────────────────────┐
  │ ProcedureRetrieval (M10) ─► assemble_procedure ─► ProcedureVerifier ─► ProceduresAnswerService │
  │        ▲                                                                       │  audit + presign │
  │ ProceduresToolkit (M11, tool_prefix="proc", TaskMemoryToolsMixin for guided mode)│                │
  │ ProceduresAgent(Agent).ask() ── transport adapter ──────────────────────────────┘                │
  └──────────────────────────────────────────────────────────────────────────────────────────────────┘
                                          │ AIMessage(image_urls, media_urls)  (M12)
  ai-parrot-integrations: parse_response ─► ParsedResponse.image_urls ─► Teams/Slack (URL) · Telegram/WhatsApp (download/URL)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `knowledge/contracts/models.py` (`Evidence`, `Extracted`, `FieldProvenance`, `trim_quote`, constants, provenance literals) | **extracts** to `knowledge/common/provenance.py`, re-exported | M1; contracts imports unchanged (U2) |
| `knowledge/contracts/carding.py` (`_quote_supported`, `_validate_extracted`, `load_bodies`) | **extracts** to `knowledge/common/validation.py`, private aliases kept | M1 |
| `knowledge/contracts/{carding,graph_loader,library,catalog,catalog_postgres,datasource,evidence}.py` | **pattern copy** (no modification) | M4, M5, M8, M9 |
| `knowledge/ontology/{schema,tenant,parser,graph_store,authorization}.py` | uses | M3, M9, M10 — import from submodules, never the package root (FEAT-540 lazy root pending) |
| `knowledge/ontology/defaults/domains/procedures.ontology.yaml` | **new** domain | M3 |
| `knowledge/pageindex/pdf_to_markdown.py` | **modifies** (additive `images_dir`; new `extract_page_images`) | M6; the `(page, text)` contract and the "never pass `pages=`" rule are preserved |
| `knowledge/pageindex/toolkit.py::PageIndexToolkit` | uses (`create_tree`, `insert_markdown`, `get_tree`, `search`) | M8, M10 |
| `knowledge/bookstore/carding.py` (`slugify`, `unique_slug`, `derive_toc`) | uses | M5, M8 |
| `FileManagerInterface.download_file` | uses | M14 export (figures pulled from storage) |
| `knowledge/bookstore/relations.py` / `library.py::relate_books` | pattern copy (judgement log + `--force`) | M7 |
| `parrot_loaders/{basevideo,youtube,videolocal}.py` | uses (`transcript_to_blocks`) | M7 (optional import — core must not hard-require the loaders satellite) |
| `parrot_loaders/extractors/{base,factory}.py` (`ExtractDataSource`, `DataSourceFactory`) | uses | M8 (optional import, as `contracts/datasource.py`) |
| Vision: `AnthropicClient.ask_to_image`, `GoogleGenAIClient.ask_to_image`, `OpenAIClient.ask_to_image` | uses via capability check | M6 |
| `interfaces/file` (`FileManagerInterface.upload_file`, `get_file_url(path, expiry=…)`) | uses | M6, M10 |
| `tools/toolkit.py::AbstractToolkit` | extends | M11 |
| `tools/working_memory/task_memory/tools.py::TaskMemoryToolsMixin` | composes | M11 |
| `memory/episodic/store.py::EpisodicMemoryStore.record_episode` | uses (`WORKFLOW_PATTERN`) | M11 |
| `parrot_tools/contracts/{retrieval,service,verifier,agent,toolkit}.py` | pattern copy (no modification) | M10, M11 |
| `bots/__init__.py::Agent` | extends | M11 |
| `models/responses.py::AIMessage`, `AgentResponse` | **modifies** (adds `image_urls`, `media_urls`) | M12 |
| `integrations/parser.py::ParsedResponse`, `parse_response` | **modifies** (carries URL lists separately) | M12 |
| `integrations/{msteams,slack,telegram,whatsapp}/wrapper.py` + `telegram/crew/crew_wrapper.py`, `whatsapp/bridge_wrapper.py`, `slack/assistant.py` | **modifies** (render/download URL media) | M12 |
| `cli/__init__.py` (`cli._lazy_commands`, `cli._lazy_extras`) | **modifies** (adds `manuals`) | M13 |
| `packages/ai-parrot/pyproject.toml` | **modifies** (adds `manuals` extra) | M13 |

### Data Models

```python
# packages/ai-parrot/src/parrot/knowledge/manuals/models.py  (M2 — full skeleton in §3)
class StepIdentity(BaseModel):
    """Immutable identity of a step, independent of display order (R1)."""
    step_id: str            # f"{manual_id}:{procedure_slug}:{uuid4().hex[:12]}" — minted once, never derived from order
    source_identity: str | None   # vendor-stable identity when the manual carries one (e.g. "4.2.3"), else None
    content_hash: str       # sha256 of normalized step text + numeric fields; used for EXACT equality only

class Step(BaseModel):
    identity: StepIdentity
    order: int
    text: Extracted[str]                # evidence required — no quote ⇒ rejected at carding
    torque: Extracted[str] | None
    duration_minutes: Extracted[int] | None
    applicability: Applicability        # Q7: models[] + serial_ranges[]; empty = all; evidence-backed
    figure_refs: list[str]              # "Fig. 3-4" as written, captured in pass 2
    parts: list[PartRef]; tools: list[ToolRef]; hazards: list[Hazard]; media: list[MediaRef]

class Procedure(BaseModel):
    procedure_id: str; slug: str; kind: ProcedureKind; title: Extracted[str]
    steps: list[Step]; estimated_minutes: int | None; skill_level: str | None
    active: bool = True; verification: VerificationState = "extracted"
    versions: list[ManualVersion]       # bitemporal, valid_from inclusive / valid_to exclusive

class ManualCard(BaseModel):
    manual_id: str                      # == PageIndex tree_name
    equipment: list[EquipmentRef]; revision: str; source_uri: str | None; source_sha256: str
    source_format: SourceFormat; toc: list[TocEntry]; toc_digest: str; page_count: int
    procedures: list[Procedure]; global_parts: list[PartRef]; global_tools: list[ToolRef]; global_hazards: list[Hazard]
    figures: list[MediaRef]; field_provenance: dict[str, FieldProvenance]; verification: VerificationState
    versions: list[ManualVersion]; card_origin: CardOrigin

class SerialRange(BaseModel):
    start: str | None; end: str | None; format: str        # vendor format preserved (e.g. "2024-0001"); comparison via normalize_serial()
class Applicability(BaseModel):
    models: list[str] = []; serial_ranges: list[SerialRange] = []; evidence: Evidence | None
class CalloutMap(BaseModel):                                 # Q8 — vision structured output
    callouts: list[Callout]                                  # Callout(label: str, description: str, part_number: str | None, bbox: tuple | None)

class ProcedureAnswer(BaseModel):
    answer_kind: ProcedureAnswerKind    # "procedure" | "step" | "prerequisites" | "lookup" | "clarification" | "not_found" | "out_of_scope" | "denied" | "incomplete"
    answer: str                         # the ONLY model-authored field (optional intro prose)
    procedure: ProcedureView | None; steps: list[StepView]; prerequisites: Prerequisites | None
    hazards: list[HazardView]; media: list[MediaView]; tips: list[TipView]; citations: list[ProcedureCitation]
    provenance: AnswerProvenance; pattern: str | None; reason: str | None; manual_revision: str | None
    # model_validator: kind invariants (procedure ⇒ ≥1 step & ≥1 citation & no omitted required step;
    # incomplete ⇒ reason names the missing step/field, no steps released; provenance = derive_provenance(citations))
```

### New Public Interfaces

```python
from parrot.knowledge.common.provenance import Evidence, Extracted, FieldProvenance, trim_quote
from parrot.knowledge.manuals import ManualCard, Procedure, Step, ManualLibrary, ManualGraphLoader, ManualCatalogStore
from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog
from parrot.knowledge.manuals.figures import extract_figures, pair_figures, caption_figures, upload_figures
from parrot.knowledge.manuals.video import align_video
from parrot.knowledge.manuals.tips import relink_tips
from parrot.knowledge.manuals.export import export_bundle
from parrot_tools.procedures import ProcedureRetrieval, ProceduresToolkit, ProceduresAgent, ProceduresAnswerService, ProcedureAnswer
# CLI: parrot manuals {add, add-video, refresh, verify, queue, relink-tips, export, spike}
```

---

## 3. Module Breakdown

All paths are relative to the repository. Each module ships focused tests in its owning package.

| Module | Files to create/modify | Responsibility / dependencies |
|---|---|---|
| M0 Spike harness | `packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py` | Measured reports for the four spikes; gates M5–M9 sign-off; M5/M6/M7/M9/M12 |
| M1 Shared provenance | `packages/ai-parrot/src/parrot/knowledge/common/{__init__,provenance,validation}.py`; `knowledge/contracts/{models,carding}.py` (re-exports) | U2: extract generic primitives, keep contracts imports byte-compatible |
| M2 Manual models | `packages/ai-parrot/src/parrot/knowledge/manuals/{__init__,models}.py` | Card, procedure, immutable step identity, media/tip refs, answer model + invariants; M1 |
| M3 Procedures ontology | `knowledge/ontology/defaults/domains/procedures.ontology.yaml`; `knowledge/manuals/domain.py` | Vocabulary, patterns, per-pattern authorization; dedicated tenant manager + domain check; M2 |
| M4 Manual catalog | `knowledge/manuals/{catalog,catalog_postgres}.py` | Cut-down ABC + Postgres jsonb/FTS (configurable regconfig), verification queue, outbox; M2 |
| M5 Carding | `knowledge/manuals/carding.py` | Header pass, procedure pass, deterministic assembly; imperative-density selection; M1, M2 |
| M6 Figures | `knowledge/manuals/figures.py`; `knowledge/pageindex/pdf_to_markdown.py` | Image + bbox extraction, caption regex pairing, vision captioning, upload; M2 |
| M7 Video alignment | `knowledge/manuals/video.py` | Whisper blocks → bm25s → judged tail; segment media; M2 |
| M8 Library + datasource | `knowledge/manuals/{library,datasource}.py` | Staged ingest, refresh/verify, `manualcard` ExtractDataSource; M2, M4, M5, M6, M7 |
| M9 Graph loader + tips | `knowledge/manuals/{graph_loader,tips}.py` | Owned-collection reconciliation, versions, relink op, orphan reporting; M2, M3, M4 |
| M10 Retrieval + release | `parrot_tools/procedures/{__init__,retrieval,assembly,verifier,service}.py` | Authorize, resolve, plan, traverse, assemble, verify (blocking), audit, presign; M2, M3, M4, M9 |
| M11 Toolkit + agent + guided | `parrot_tools/procedures/{toolkit,agent,guided}.py` | One action per tool, confirming writes, transport adapter, task-memory guided mode, episodes; M10 |
| M12 Media delivery | `models/responses.py`; `integrations/parser.py`; four wrappers + three duplicate senders | `image_urls`/`media_urls` end to end; Path behaviour untouched; independent |
| M13 CLI + packaging + docs | `parrot_tools/procedures/{cli,__main__}.py`; `cli/__init__.py`; `pyproject.toml`; `docs/knowledge/manuals.md` | click group, lazy registration, `manuals` extra, operator docs; M8, M10, M11, M14 |
| M14 Export bundle | `knowledge/manuals/export.py` | Q9: self-contained per-manual bundle (manifest, procedures, figures, captions, videos); M2, M4, M6 |

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0 | no | — | needs the owner's spike corpus and hand counts; design of thresholds decided, execution is human-in-loop |
| M1 | yes | pure move + re-export; symbol list fixed in §3 M1; `test_dependency_boundary`-style guard | — |
| M2 | yes | field list and validators fixed in §2/§3; copies `ContractAnswer._check_kind_invariants` shape | — |
| M3 | yes | entity/relation/pattern list fixed; YAML shapes copied from `contracts.ontology.yaml` anchors | — |
| M4 | yes | ABC method list fixed; DDL mirrors `catalog_postgres.py` with `manual_id` and `search_regconfig` | — |
| M5 | no | — | prompt wording and section-selection thresholds are tuned against spike 1 |
| M6 | partly | extraction/upload/captioning contracts fixed; caption regex fixed | pairing heuristics (distance scaling) tuned by spike 1 |
| M7 | partly | block ingestion + bm25s + judgement log fixed | thresholds tuned by spike 3 |
| M8 | yes | copies `ContractLibrary` flow with the M5–M7 hooks named | — |
| M9 | yes | owned collections, `EdgeSpec` with `origin`, relink algorithm order fixed | — |
| M10 | no | — | trigger table and `assemble_procedure` completeness rules need the thinking model |
| M11 | yes | tool names, prefixes, confirming set, adapter shape fixed | — |
| M12 | yes | field names, parser semantics, per-channel behaviour fixed in §3 M12 | — |
| M13 | yes | command names, lazy registration lines, extra composition fixed | — |
| M14 | yes | bundle layout and manifest fields fixed in §3 M14 | — |

### Module 0: Spike harness
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py`
- **Responsibility**: turn the brainstorm's spike gate into repeatable, reported measurements over an owner-supplied corpus (`MANUALS_SPIKE_CORPUS` directory with `expected.json` hand counts). Invoked by `parrot manuals spike {figures,media,video,tips}`. Pass thresholds: figures ≥ 90 % steps in order with no missing required step and ≥ 80 % correct primary figure on captioned figures; video ≥ 70 % of steps get a segment containing the demonstrated action; tips 3/3 re-link outcomes exactly as expected; media one figure delivered on Teams, WhatsApp and Telegram.
- **Depends on**: M5, M6, M7, M9, M12
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/spikes.py  (new)
  class SpikeReport(BaseModel):
      """One spike's measured numbers, thresholds and pass/fail; serialised under artifacts/logs/."""
      name: Literal["figures", "media", "video", "tips"]; measurements: dict[str, float]
      thresholds: dict[str, float]; passed: bool; notes: list[str]

  async def spike_figures(corpus_dir: Path, *, adapter: Any, expected: dict[str, Any]) -> SpikeReport:
      """Run M6 extraction + M5 pass 2 over each manual; compare against expected.json hand counts."""

  async def spike_video(corpus_dir: Path, *, adapter: Any, expected: dict[str, Any]) -> SpikeReport:
      """Run M7 alignment; score t_start/t_end precision and coverage per step."""

  async def spike_tips(graph_store: Any, catalog: ManualCatalogStore, *, revisions: tuple[Path, Path]) -> SpikeReport:
      """Publish rev A, add three tips, publish rev B (one renumbered, one reworded, one removed); assert relink outcomes."""

  async def spike_media(answer: ProcedureAnswer, *, channels: Sequence[str]) -> SpikeReport:
      """Deliver one presigned figure through the named channel wrappers; record render/send outcome per channel."""
  ```

### Module 1: Shared provenance primitives
- **Path**: `packages/ai-parrot/src/parrot/knowledge/common/{__init__,provenance,validation}.py`; re-exports in `knowledge/contracts/models.py` and `knowledge/contracts/carding.py`
- **Responsibility**: U2 (narrowed). Move the domain-neutral primitives out of `contracts` so `manuals` does not import `contracts`. Preserve every old import path, serialized payload and validation behaviour (the 0.5 unsubstantiated cap, verbatim-quote check). No `doc_id` rename; `Citation`, `EvidenceRef`, `ContractVersion`, `ContractAnswer` stay in contracts. Importing `knowledge.common` must need no tools satellite or database.
- **Depends on**: — (first lane; M2 and M5 import it)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/common/provenance.py  (new — moved verbatim from contracts/models.py)
  MAX_QUOTE_CHARS = 300                       # verified: knowledge/contracts/models.py:88
  UNSUBSTANTIATED_CONFIDENCE_CAP = 0.5        # verified: knowledge/contracts/models.py:111
  VerificationState = Literal["extracted", "verified", "stale"]   # verified: models.py:161
  ProvenanceOrigin = Literal["llm", "rule", "manual"]             # verified: models.py:162
  AnswerProvenance = Literal["verified", "mixed", "extracted"]    # verified: models.py:175
  def trim_quote(value: Any) -> Any: ...                          # verified: models.py:91
  class Evidence(BaseModel): ...                                  # verified: models.py:205-229 (node_id, quote, page, substantiates())
  class Extracted(BaseModel, Generic[T]): ...                     # verified: models.py:235-262 (value, evidence, confidence; cap validator)
  class FieldProvenance(BaseModel): ...                           # verified: models.py:265-311 (origin, verification, node_id, page, quote, confidence, verified_by/at, derived_from, candidate)

  # packages/ai-parrot/src/parrot/knowledge/common/validation.py  (new — promoted from contracts/carding.py)
  def normalize_whitespace(text: str) -> str: ...                 # verified: carding.py (private _normalize_whitespace, used at 456-483)
  def quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool: ...   # verified: carding.py:456
  def validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]: ...  # verified: carding.py:471
  async def load_bodies(loader: Callable[[str], str | None], node_ids: Sequence[str]) -> dict[str, str]: ...    # verified: carding.py:185-213

  # knowledge/contracts/models.py  (modifies models.py:88 — replace the block 87-111 and 159-162, 175 with re-exports)
  from parrot.knowledge.common.provenance import (MAX_QUOTE_CHARS, UNSUBSTANTIATED_CONFIDENCE_CAP, VerificationState,
      ProvenanceOrigin, AnswerProvenance, trim_quote, Evidence, Extracted, FieldProvenance)  # noqa: F401 — compatibility
  # knowledge/contracts/carding.py  (modifies carding.py:456, 471 — bodies replaced by aliases)
  _quote_supported = quote_supported; _validate_extracted = validate_extracted; _normalize_whitespace = normalize_whitespace
  ```
  Acceptance: `parrot.knowledge.contracts.models.Evidence is parrot.knowledge.common.provenance.Evidence`; `packages/ai-parrot/tests/knowledge/contracts/` passes unchanged; a new `tests/knowledge/common/test_boundary.py` asserts `knowledge/common` imports nothing from `contracts`, `parrot_tools`, `asyncpg` or `arango`.

### Module 2: Manual models
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/{__init__,models}.py`
- **Responsibility**: the card family and the answer model. `manual_id == PageIndex tree_name`. Step identity is immutable and order-independent (R1). Names must not collide with `parrot.models.infographic.StepsBlock/ChecklistBlock` (proposal F030) — nothing here is exported into `parrot.models`.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/models.py  (new)
  from parrot.knowledge.common.provenance import Evidence, Extracted, FieldProvenance, trim_quote, MAX_QUOTE_CHARS, VerificationState, ProvenanceOrigin, AnswerProvenance
  from parrot.knowledge.bookstore.models import TocEntry     # verified: knowledge/contracts/models.py:22 (same import)

  ProcedureKind = Literal["assembly", "disassembly", "maintenance", "inspection", "troubleshooting"]
  MediaKind = Literal["figure", "photo", "video_segment"]
  MediaRole = Literal["primary", "secondary", "overview"]
  HazardSeverity = Literal["caution", "warning", "danger"]
  TipOrigin = Literal["manual", "technician", "memory"]
  SourceFormat = Literal["pdf", "docx", "md", "txt"]        # mirrors contracts/models.py:164
  CardOrigin = Literal["llm", "fallback", "manual"]         # mirrors contracts/models.py:165
  ProcedureAnswerKind = Literal["procedure", "step", "prerequisites", "lookup", "clarification", "not_found", "out_of_scope", "denied", "incomplete"]

  def mint_step_id(manual_id: str, procedure_slug: str) -> str:
      """Return f"{manual_id}:{procedure_slug}:{uuid4().hex[:12]}"; Arango `_key`-safe (proposal F010 note)."""
  def content_hash(text: str, *, torque: str | None = None, duration_minutes: int | None = None, applies_to: Sequence[str] = ()) -> str:
      """sha256 over normalized text + numeric/qualifier fields — equality only, never similarity (R1)."""

  class StepIdentity(BaseModel): step_id: str; source_identity: str | None = None; content_hash: str
  class PartRef(BaseModel): part_id: str; part_number: str | None; name: Extracted[str]; quantity: int | None; resolved: bool
  class ToolRef(BaseModel): tool_id: str; name: Extracted[str]; spec: str | None
  class Hazard(BaseModel): hazard_id: str; severity: HazardSeverity; text: Extracted[str]; applies_to: list[str]
  class MediaRef(BaseModel):
      media_id: str; kind: MediaKind; storage_key: str | None; uri: str | None; page: int | None
      bbox: tuple[float, float, float, float] | None; sha256: str | None; caption: str | None; label: str | None
      t_start: float | None; t_end: float | None; origin: TipOrigin = "manual"
      callouts: list[CalloutLink] = []; unresolved_callouts: list[Callout] = []      # Q8
      # validator: figure/photo ⇒ storage_key; video_segment ⇒ uri and t_start < t_end; never an http(s) URL in storage_key
  class MediaLink(BaseModel): media_id: str; role: MediaRole; confidence: float; origin: Literal["manual", "llm"]
  class SerialRange(BaseModel): start: str | None; end: str | None; format: str          # Q7
  class Applicability(BaseModel): models: list[str] = []; serial_ranges: list[SerialRange] = []; evidence: Evidence | None = None
      # validator: any serial_ranges ⇒ evidence required (a serial qualifier is a critical field, G2)
  def normalize_serial(value: str, *, format: str) -> tuple[int, ...]: ...   # deterministic key for range comparison; ValueError when the value does not match the format
  def applies(step: "Step", *, model: str | None, serial: str | None) -> Literal["yes", "no", "unknown"]:
      """Pure. models[] mismatch ⇒ no; serial_ranges present and serial None ⇒ unknown; serial outside every range ⇒ no; else yes."""
  class Callout(BaseModel): label: str; description: str; part_number: str | None; bbox: tuple[float, float, float, float] | None   # Q8
  class CalloutMap(BaseModel): callouts: list[Callout]                                    # vision structured output
  class CalloutLink(BaseModel): media_id: str; part_id: str; callout: str; confidence: float; origin: Literal["vision"]
  class Step(BaseModel):
      identity: StepIdentity; order: int; text: Extracted[str]; torque: Extracted[str] | None = None
      duration_minutes: Extracted[int] | None = None; applicability: Applicability = Applicability(); figure_refs: list[str] = []
      parts: list[PartRef] = []; tools: list[ToolRef] = []; hazards: list[Hazard] = []; media: list[MediaLink] = []
      cross_refs: list[str] = []          # "before step N" / "§4.2" phrases, evidence-backed, resolved by assembly
      # validator: text.evidence is required and substantiates() — otherwise ValueError (G2)
  class ManualVersion(BaseModel):         # mirrors ContractVersion shape (contracts/models.py:417-475) with manual semantics
      n: int; revision: str; valid_from: date | None; valid_to: date | None; source_sha256: str; card_snapshot: dict[str, Any]
      recorded_at: datetime; evidence_ref: str | None
      def in_force(self, as_of: date) -> bool: ...
  class Procedure(BaseModel): procedure_id: str; slug: str; kind: ProcedureKind; title: Extracted[str]; steps: list[Step]
      estimated_minutes: int | None; skill_level: str | None; active: bool = True; verification: VerificationState = "extracted"
      versions: list[ManualVersion] = []; supersedes: str | None = None
  class EquipmentRef(BaseModel): equipment_id: str; model: str; family: str | None; revision: str | None; aliases: list[str]
  class Tip(BaseModel): tip_id: str; text: str; origin: TipOrigin; author_employee_id: str | None; created_at: datetime
      active: bool = True; orphaned: bool = False; source_revision: str; attached_step_id: str | None; history: list[dict[str, Any]]
  class ManualCard(BaseModel): ...        # fields per §2 Data Models; model_validator: manual_id == tree_name rule, procedures[].slug unique
  class ProcedureCitation(BaseModel):     # mirrors Citation (contracts/models.py:701-737) with manual_id
      manual_id: str; node_id: str; quote: str = Field(..., min_length=1, max_length=MAX_QUOTE_CHARS); page: int | None
      verification: VerificationState; version_n: int; source_sha256: str
      def key(self) -> tuple[str, str]: ...
  def derive_provenance(citations: Sequence[ProcedureCitation]) -> AnswerProvenance: ...   # same rule as contracts/models.py:800-818
  class ProcedureAnswer(BaseModel): ...   # §2 Data Models; @model_validator(mode="after") _check_kind_invariants
  ```

### Module 3: Procedures ontology domain
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml`; `packages/ai-parrot/src/parrot/knowledge/manuals/domain.py`
- **Responsibility**: the vocabulary (`extends: base`), typed edge properties, base-layer `Employee` link via `field_match`, per-pattern `has_role` authorization (five fixed rule kinds — no invented ones, R4), and the dedicated tenant manager that makes the packaged YAML resolvable (proposal F011). Technician-owned collections are declared in the YAML so `initialize_tenant` creates them, but they are **absent** from the loader's owned set (M9).
- **Depends on**: M2 (property names match model fields)
- **Interface Skeleton**:
  ```yaml
  # procedures.ontology.yaml  (new; shapes verified against contracts.ontology.yaml:1-4, 141-167, 276-310, 466-508)
  name: procedures
  version: "1.0"
  extends: base
  entities:
    Equipment:  {collection: equipment, source: manualcard, key_field: equipment_id, properties: [...model, family, revision, aliases(list)], vectorize: [model]}
    Manual:     {collection: manual,    source: manualcard, key_field: manual_id, properties: [...revision, source_sha256, active(boolean), versions(list)]}
    Procedure:  {collection: procedure, source: manualcard, key_field: procedure_id, properties: [...kind(enum), title, estimated_minutes(int), skill_level, active(boolean), verification(enum), versions(list)], vectorize: [title]}
    Step:       {collection: step,      source: manualcard, key_field: step_id, properties: [...order(int), source_identity, content_hash, text, torque, duration_minutes(int), applies_models(list), applies_serial_ranges(list), node_id, page(int), active(boolean)]}
    Part:       {collection: part,      source: manualcard, key_field: part_id, properties: [...part_number, name]}
    Tool:       {collection: tool,      source: manualcard, key_field: tool_id, properties: [...name, spec]}
    Hazard:     {collection: hazard,    source: manualcard, key_field: hazard_id, properties: [...severity(enum), text]}
    Media:      {collection: media,     source: manualcard, key_field: media_id, properties: [...kind(enum), storage_key, uri, page(int), caption, label, t_start(float), t_end(float), origin], vectorize: [caption]}
    Tip:        {collection: tech_tip,  key_field: tip_id,   properties: [...text, origin, author_employee_id, created_at(date), active(boolean), orphaned(boolean), source_revision, attached_step_id]}   # no `source:` ⇒ refresh pipeline skips it (contracts.ontology.yaml:248-250 precedent)
  relations:
    documents:      {from: Manual,    to: Procedure, edge_collection: documents}
    assembles:      {from: Procedure, to: Equipment, edge_collection: assembles}
    has_step:       {from: Procedure, to: Step,      edge_collection: has_step,      properties: [order(int)]}
    precedes:       {from: Step,      to: Step,      edge_collection: precedes,      properties: [kind(string)]}     # "order" | "explicit"
    requires_part:  {from: Step,      to: Part,      edge_collection: requires_part, properties: [quantity(int), contexts(list)]}   # one edge per pair (create_edges collapses duplicates — F010)
    requires_tool:  {from: Step,      to: Tool,      edge_collection: requires_tool}
    warns:          {from: Step,      to: Hazard,    edge_collection: warns}
    illustrated_by: {from: Step,      to: Media,     edge_collection: illustrated_by, properties: [roles(list), confidence(float), origin(string)]}   # roles is a LIST for the same reason
    overview_media: {from: Procedure, to: Media,     edge_collection: overview_media}
    depicts:        {from: Media,     to: Part,      edge_collection: depicts,        properties: [callouts(list), confidence(float), origin(string)]}   # Q8; one edge per (media, part), callout labels as a list (F010)
    shares_module:  {from: Equipment, to: Equipment, edge_collection: shares_module, properties: [module(string)]}
    supersedes:     {from: Procedure, to: Procedure, edge_collection: supersedes}
    tech_tip_on:    {from: Tip,       to: Step,      edge_collection: tech_tip_on,   properties: [linked_by(string), linked_at(date)]}     # technician-owned
    tech_tip_by:    {from: Tip,       to: Employee,  edge_collection: tech_tip_by, discovery: {strategy: field_match, rules: [{source_field: author_employee_id, target_field: employee_id, match_type: exact}]}}   # copies is_employee (contracts.ontology.yaml:300-310)
  traversal_patterns:   # every query_template filters `active != false AND _active != false` (contracts precedent 466-508); authorization: {rules: [{rule: has_role, role: technician}, {rule: has_role, role: manual_curator}], default_deny: true}
    procedure_steps, procedure_prerequisites, procedures_for_equipment, step_detail, equipment_sharing_module, procedure_in_force, tips_for_procedure, part_for_callout (Q8: Media → depicts → Part by callout label), verification_queue_procedures (curator only)
  ```
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/domain.py  (new)
  PROCEDURES_DOMAIN = "procedures"
  OWNED_VERTEX_COLLECTIONS: tuple[str, ...] = ("equipment", "manual", "procedure", "step", "part", "tool", "hazard", "media")
  OWNED_EDGE_COLLECTIONS: tuple[str, ...] = ("documents", "assembles", "has_step", "precedes", "requires_part", "requires_tool", "warns", "illustrated_by", "overview_media", "depicts", "shares_module", "supersedes")
  TECHNICIAN_COLLECTIONS: tuple[str, ...] = ("tech_tip", "tech_tip_on", "tech_tip_by")   # never reconciled by M9
  TECHNICIAN_ROLE = "technician"; CURATOR_ROLE = "manual_curator"
  class ProceduresDomainNotLoaded(RuntimeError): ...          # mirrors ContractsDomainNotLoaded, verified: contracts/graph_loader.py:102
  def default_tenant_manager(ontology_dir: str | Path | None = None) -> TenantOntologyManager:
      """TenantOntologyManager(ontology_dir=ontology_dir or OntologyParser.get_defaults_dir()) — verified pattern: contracts/graph_loader.py:215-245; never share a manager with another domain (resolve cache keyed by tenant_id only, tenant.py:92-106)."""
  def resolve_context(manager: TenantOntologyManager, tenant_id: str) -> TenantContext:
      """resolve(tenant_id, domain=PROCEDURES_DOMAIN); raise ProceduresDomainNotLoaded if {"Procedure","Step","Media","Tip"} - entities."""
  ```

### Module 4: Manual catalog
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/{catalog,catalog_postgres}.py`
- **Responsibility**: cut-down protocol (cards, versions, search, verification queue, answers audit, outbox — no parties/deltas/relations) and the Postgres backend copying `catalog_postgres.py` (jsonb card, denormalized columns, generated tsvector with a **configurable regconfig**, `FOR UPDATE` revision check, sha/URI clash check, history rows). Tenant-scoped like `ContractCatalogStore(tenant_id, schema, principal)`.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/catalog.py  (new; shape verified: contracts/catalog.py:188-223, 292-436, 631-681)
  class SearchHit(BaseModel): card: ManualCard; rank: float = 0.0; matched: Literal["manual", "procedure", "equipment", "caption"]
  class UpsertResult(BaseModel): manual_id: str; revision: int; created: bool; version_n: int; queued: list[PublicationRecord]
  class VerificationQueueEntry(BaseModel): card: ManualCard; reason: Literal["unpaired_figure", "low_confidence_step", "orphaned_tip", "missing_evidence", "stale"]; items: list[str]
  class ManualCatalogStore(ABC):
      def __init__(self, *, tenant_id: str, schema: str = "manuals", principal: Optional[str] = None, search_regconfig: str = "english") -> None: ...
      async def upsert(self, card: ManualCard, *, expected_revision: Optional[int] = None, version: Optional[ManualVersion] = None) -> UpsertResult: ...
      async def get(self, manual_id: str) -> Optional[ManualCard]: ...
      async def find_by_sha(self, sha256: str) -> Optional[ManualCard]: ...
      async def find_by_source_uri(self, uri: str) -> Optional[ManualCard]: ...
      async def list_cards(self, *, verification: Optional[VerificationState] = None, active_only: bool = True) -> list[ManualCard]: ...
      async def search(self, query: str, top_k: int = 8) -> list[SearchHit]: ...                 # FTS over title + procedure titles + equipment aliases + figure captions
      async def resolve_equipment(self, query: str, *, limit: int = 5) -> list[EquipmentRef]: ...  # deterministic; rapidfuzz on aliases (similarity(), contracts/carding.py:868-892)
      async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]: ...
      async def record_answer(self, record: AnswerRecord) -> None: ...                           # audit row per released/blocked answer
      async def enqueue_publication(...) / pending_publications / claim_publication / complete_publication / fail_publication  # outbox, as contracts/catalog.py:631-681
      async def setup(self) -> None: ...; async def close(self) -> None: ...
  # packages/ai-parrot/src/parrot/knowledge/manuals/catalog_postgres.py  (new; DDL mirrors contracts/catalog_postgres.py:85-119 with `search_regconfig` interpolated after validate_sql_identifier-style validation; search mirrors 914-944; verification_queue mirrors 998-1060 over card_json->'field_provenance' plus card_json->'procedures')
  class PostgresManualCatalog(ManualCatalogStore):
      def __init__(self, dsn: Optional[str] = None, *, pool: Any = None, tenant_id: str, schema: str = "manuals", principal: Optional[str] = None, search_regconfig: str = "english", now: Callable[[], datetime] = _utcnow) -> None: ...
  ```

### Module 5: Carding
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/carding.py`
- **Responsibility**: bounded 1 + N structured-output extraction copying `draft_contract` (deterministic node selection → `adapter.ask_structured(prompt, Model, temperature=0.0, system_prompt=…)` → verbatim-quote validation → fallback), with manual semantics: header categories (cover, specifications, parts list, tools required, safety), procedure candidates by title keywords **or** imperative/numbered-list density, and a deterministic `assemble_card` (part-number resolution via `similarity ≥ 0.85` else literal + flag; `precedes` from order and evidence-backed "before/after step N"; `estimated_minutes` as the sum of durations; `mint_step_id` + `content_hash` per step; `source_identity` captured when the manual numbers steps).
- **Depends on**: M1, M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/carding.py  (new; pattern verified: contracts/carding.py:85-99, 216-354, 399-448, 486-604, 644-670, 678-786)
  HEADER_CATEGORIES: dict[str, tuple[str, ...]]        # cover/specifications/parts/tools/safety title keywords
  PROCEDURE_TITLE_MARKERS: tuple[str, ...] = ("assembly", "installation", "disassembly", "removal", "replacement", "maintenance", "inspection", "procedure", "step", "montaje", "instalación", "desmontaje", "mantenimiento")
  IMPERATIVE_MARKERS: tuple[str, ...]                 # verb-initial line markers used by imperative_density
  FIGURE_REF_RE = re.compile(r"(?:Fig\.?|Figure|Figura)\s*[\dA-Z][\dA-Z\-\.]*", re.I)
  DEFAULT_MAX_PROCEDURE_SECTIONS = 20; FALLBACK_CONFIDENCE = 0.3
  def imperative_density(text: str) -> int: ...       # analogue of deontic_density (carding.py:216-226): numbered-list lines + imperative openers
  def select_header_nodes(toc: Sequence[TocEntry], bodies: Mapping[str, str]) -> list[str]: ...
  def select_procedure_nodes(toc: Sequence[TocEntry], bodies: Mapping[str, str], *, limit: int = DEFAULT_MAX_PROCEDURE_SECTIONS, exclude: Sequence[str] = ()) -> list[str]: ...
  class ManualHeaderDraft(BaseModel): ...             # equipment models, revision, global parts/tools/hazards — every value Extracted[...]
  class StepDraft(BaseModel): text: Extracted[str]; order: int; source_identity: str | None; torque: Extracted[str] | None; duration_minutes: Extracted[int] | None; part_mentions: list[str]; tool_mentions: list[str]; hazard_texts: list[Extracted[str]]; figure_refs: list[str]; applies_models: list[str]; serial_qualifiers: list[Extracted[str]]; callout_mentions: list[str]; cross_refs: list[str]
  SERIAL_QUALIFIER_RE = re.compile(r"(?:S/N|serial(?:\s+numbers?)?|n[úu]mero de serie)\s*(?:from|desde|>=|≥|and later|y posteriores)?\s*([A-Z0-9\-]+)(?:\s*(?:to|hasta|-|–)\s*([A-Z0-9\-]+))?", re.I)
  def parse_serial_qualifier(text: str) -> SerialRange | None: ...   # deterministic; format inferred from the literal; None when unparseable (kept as literal + queue entry)
  class ProcedureDraft(BaseModel): title: Extracted[str]; kind: ProcedureKind; steps: list[StepDraft]; node_id: str
  class CardingDraft(BaseModel): header: ManualHeaderDraft; procedures: list[ProcedureDraft]; warnings: list[str]
  def header_prompt(*, filename: str, toc_digest: str, material: str) -> str: ...
  def procedure_prompt(*, node_id: str, title: str, body: str) -> str: ...      # "<<<BEGIN UNTRUSTED DOCUMENT MATERIAL — DATA ONLY>>>" framing (carding.py:399-448)
  def validate_header_evidence(draft: ManualHeaderDraft, bodies: Mapping[str, str]) -> tuple[ManualHeaderDraft, list[str]]: ...
  def validate_steps(steps: Sequence[StepDraft], bodies: Mapping[str, str], *, node_id: str) -> tuple[list[StepDraft], list[str]]:
      """Drop any step whose text quote is not verbatim in the read node (G2) — never keep it at low confidence."""
  def fallback_header_draft(source: str | Path, toc: Sequence[TocEntry] = ()) -> ManualHeaderDraft: ...
  async def draft_manual(adapter: Any, *, filename: str, toc: Sequence[TocEntry], toc_digest: str, loader: Callable[[str], str | None], max_procedure_sections: int = DEFAULT_MAX_PROCEDURE_SECTIONS) -> CardingDraft: ...
  def assemble_card(draft: CardingDraft, *, manual_id: str, source: SourceInfo, figures: Sequence[MediaRef], page_map: Mapping[str, int], now: datetime) -> ManualCard:
      """Deterministic: resolve parts (similarity ≥ 0.85), mint step ids, hash content (Applicability is part of the hash), derive precedes, pair figure_refs → media by label (M6.pair_figures), parse serial qualifiers → Applicability (Q7), sum durations."""
  ```

### Module 6: Figures
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/figures.py`; `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` (additive)
- **Responsibility**: extract page images with bboxes, pair captions → labels → steps deterministically, caption every figure once at ingest with a capability-resolved vision client (descriptive metadata only), upload through `FileManagerInterface`, and return `MediaRef`s. Uncaptioned figures attach `role="secondary"` with distance-scaled confidence to the closest same-page step; a cited-but-missing figure keeps the literal reference in `Step.figure_refs`, writes no link, and lands in the verification queue — never a nearest-page guess as `primary`.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py  (modifies pdf_to_markdown.py:35 — additive kwarg; the body at :72 forwards write_images/image_path only when images_dir is set; NEVER pass pages=)
  def extract_markdown_per_page(pdf_path: str | Path, *, images_dir: str | Path | None = None, image_format: str = "png", dpi: int = 150, image_size_limit: float = 0.05) -> list[tuple[int, str]]:
      """Unchanged return contract; with images_dir the per-page markdown carries ![](…) refs in reading order (pymupdf4llm 0.0.27 kwargs verified: proposal F026)."""
  class PageImage(BaseModel): page: int; index: int; path: Path; bbox: tuple[float, float, float, float]; width: int; height: int; sha256: str
  def extract_page_images(pdf_path: str | Path, images_dir: str | Path, *, dpi: int = 150, min_area_ratio: float = 0.05) -> list[PageImage]:
      """Sibling function: pymupdf Page.get_image_info(xrefs=True) + get_image_bbox per page (verified: F026 probe); keeps the (page, text) tuple contract of extract_markdown_per_page intact."""

  # packages/ai-parrot/src/parrot/knowledge/manuals/figures.py  (new)
  CAPTION_RE = re.compile(r"^\s*(?:Fig\.?|Figure|Figura)\s*([\dA-Z][\dA-Z\-\.]*)\s*[:.\-–]?\s*(.*)$", re.I | re.M)
  class FigureCandidate(BaseModel): image: PageImage; label: str | None; caption_text: str | None; caption_distance: float | None
  def extract_figures(pdf_path: Path, work_dir: Path, *, page_texts: Mapping[int, str]) -> list[FigureCandidate]:
      """extract_page_images + caption pairing: the text block immediately below the bbox matching CAPTION_RE."""
  def pair_figures(steps: Sequence[StepDraft], figures: Sequence[FigureCandidate], *, page_of_step: Mapping[int, int]) -> list[tuple[int, MediaLink]]:
      """Deterministic: label cited in Step.figure_refs ⇒ role=primary, confidence=1.0; else same-page closest by vertical distance ⇒ role=secondary, confidence scaled; returns (step_index, MediaLink)."""
  class VisionCaptioner(Protocol):
      async def caption(self, image: Path, *, context: str) -> str: ...
  def resolve_captioner(client: Any) -> VisionCaptioner:
      """hasattr(client, "ask_to_image") ⇒ adapter over it (Anthropic/Google/OpenAI verified: proposal F023; input is Path/bytes, never a URL); ClaudeAgentClient raises NotImplementedError ⇒ treated as absent; otherwise raise CaptioningUnavailable."""
  async def caption_figures(figures: Sequence[FigureCandidate], captioner: VisionCaptioner, *, concurrency: int = 4) -> list[FigureCandidate]: ...
  class CalloutMapper(Protocol):                                                                 # Q8
      async def map_callouts(self, image: Path, *, context: str) -> CalloutMap: ...
  def resolve_callout_mapper(client: Any) -> CalloutMapper:
      """client.ask_to_image(prompt, image, structured_output=CalloutMap) — structured_output verified on Anthropic (client.py:1329+), Google (client.py:5160+) and OpenAI (client.py:1468+); same capability rule as resolve_captioner."""
  def is_exploded_view(figure: FigureCandidate, steps: Sequence[StepDraft]) -> bool: ...        # caption/step evidence mentions ≥ 2 callout numbers
  async def map_callouts(figures: Sequence[FigureCandidate], mapper: CalloutMapper, *, parts: Sequence[PartRef], steps: Sequence[StepDraft]) -> tuple[list[CalloutLink], list[Callout]]:
      """One structured call per exploded view; label → Part by part_number (exact) else similarity(description, part.name) ≥ 0.85; else unresolved (queue). Runs only when settings.callouts_enabled (flipped by spike 1 passing)."""
  async def upload_figures(figures: Sequence[FigureCandidate], fm: Any, *, prefix: str) -> list[MediaRef]:
      """fm.upload_file(...) (FileManagerInterface, navigator-api 4.0.0 — verified: proposal F024); MediaRef.storage_key = returned key; no URL stored."""
  async def presign(fm: Any, storage_key: str, *, expiry: int = 900) -> str:
      """fm.get_file_url(storage_key, expiry=expiry) — parameter is `expiry`, not `expiry_seconds` (F024); raise MediaUnavailable when the result is not http(s) (LocalFileManager returns file://)."""
  ```

### Module 7: Video alignment
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/video.py`
- **Responsibility**: turn whisper transcript blocks into `Media(kind="video_segment")` per step. Deterministic first (`bm25s` over step text vs block text, plus ordinal hints "step three"/"next"), then an LLM-judged tail for blocks under the threshold with a judgement log and `--force` (copying `relate_books`, proposal F014). A step with no segment gets none. Gemini `VideoUnderstandingLoader` is **not** used (untimed scenes, proposal F025); if scene timing is ever wanted it is a direct `GoogleGenAIClient.video_understanding(offsets=…, structured_output=…)` call, out of v1.
- **Depends on**: M2 (optional import of `parrot_loaders`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/video.py  (new)
  class TranscriptBlock(BaseModel): id: int; start_seconds: float; end_seconds: float; text: str   # shape verified: parrot_loaders/basevideo.py:860-887 (transcript_to_blocks output keys)
  def blocks_from_transcript(transcript: Mapping[str, Any]) -> list[TranscriptBlock]:
      """Wrap BaseVideoLoader.transcript_to_blocks(transcript) output (dict input despite the `str` hint — F025)."""
  class SegmentAlignment(BaseModel): step_id: str; block_ids: list[int]; t_start: float; t_end: float; score: float; method: Literal["bm25", "ordinal", "judged"]
  def align_deterministic(steps: Sequence[Step], blocks: Sequence[TranscriptBlock], *, threshold: float = 0.35) -> tuple[list[SegmentAlignment], list[Step]]:
      """bm25s retrieval per step + monotonic ordinal constraint; returns (aligned, unaligned)."""
  class AlignmentJudgement(BaseModel): step_id: str; block_ids: list[int]; confidence: float; model: str; judged_at: datetime
  async def judge_alignment(adapter: Any, steps: Sequence[Step], blocks: Sequence[TranscriptBlock], *, judged: set[str], model_name: str = "") -> list[AlignmentJudgement]:
      """One structured call for the unaligned tail; drops any step_id/block_id not in the candidates (judge_relations pattern, bookstore/relations.py:372-413)."""
  async def align_video(card: ManualCard, *, uri: str, transcript: Mapping[str, Any], adapter: Any | None, judgement_log: JudgementLog, force: bool = False) -> tuple[list[MediaRef], list[MediaLink], AlignmentReport]:
      """Deterministic pass, then judged tail unless already judged (force resets); coverage < 0.30 ⇒ single overview MediaRef on the procedure."""
  ```

### Module 8: Library and datasource
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/{library,datasource}.py`
- **Responsibility**: `ManualLibrary` copies `ContractLibrary` (sha dedup → `_to_markdown` → staged PageIndex tree → `derive_toc` → carding → assemble → evidence archive → `catalog.upsert(card, version=…)` → promote), inserting the M6/M7 hooks. PDF markdown is produced by `extract_markdown_per_page(images_dir=…)` (not the contracts `page.get_text()` path — proposal F013) so figure refs survive; image-only PDFs are refused with a clear message (v1). `ManualCardDataSource` is the `manualcard` `ExtractDataSource` with its own routing order (most specific key first).
- **Depends on**: M2, M4, M5, M6, M7
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/library.py  (new; flow verified: contracts/library.py:96-115, 481-512, 516-607, 653-770, 787-816, 910-970, 1000-1030, 1222-1226)
  class TreeIndexer(Protocol): ...                      # identical 4-method protocol (library.py:96-115); default factory builds PageIndexToolkit(adapter=…, storage_dir=…) (library.py:1222-1226)
  class IngestResult(BaseModel): card: ManualCard; status: Literal["created", "updated", "unchanged", "refused"]; procedures: int; steps: int; figures_paired: int; figures_unpaired: int; hazards: int; tips_relinked: int; tips_orphaned: int; queue_entries: list[str]; warnings: list[str]
  class ManualLibrary:
      def __init__(self, *, catalog: ManualCatalogStore, storage_root: str | Path, evidence_root: str | Path, adapter: Any = None,
                   file_manager: Any, vision_client: Any | None = None, indexer_factory: Optional[Callable[[Path, Any], TreeIndexer]] = None,
                   graph_loader: Optional["ManualGraphLoader"] = None, max_procedure_sections: int = 20, now: Callable[[], datetime] = _utcnow) -> None: ...
      async def add_manual(self, source: str | Path, *, equipment: Sequence[str], revision: str, source_uri: Optional[str] = None, force: bool = False) -> IngestResult: ...
      async def add_folder(self, folder: str | Path, *, recursive: bool = False, force: bool = False) -> list[IngestResult]: ...
      async def add_video(self, manual_id: str, *, uri: str, transcript: Mapping[str, Any] | None = None, local_path: Optional[Path] = None, force: bool = False) -> AlignmentReport: ...
      async def refresh(self, manual_id: str, source: str | Path, *, revision: str) -> IngestResult:
          """New card revision + ManualVersion append; publish; relink_tips; report changed/relinked/orphaned."""
      async def verify_procedure(self, manual_id: str, procedure_id: str, *, user: str, expected_revision: Optional[int] = None) -> ManualCard:
          """Flip verification → verified (verified_by/at), freeze the current ManualVersion."""
      async def _to_markdown(self, path: Path, source_format: SourceFormat, *, images_dir: Path) -> tuple[str, dict[int, int]]:
          """PDF: extract_markdown_per_page(path, images_dir=images_dir) joined as '## Page N' sections (pdf_markdown, library.py:205-220); DOCX/TXT: same helpers as ContractLibrary; image-only ⇒ ImageOnlyManual error."""

  # packages/ai-parrot/src/parrot/knowledge/manuals/datasource.py  (new; verified pattern: contracts/datasource.py:26-40, 55-64, 144-192, 380-455)
  SOURCE_NAME = "manualcard"
  ENTITY_ROUTING_ORDER = (("step_id", "Step"), ("media_id", "Media"), ("hazard_id", "Hazard"), ("part_id", "Part"), ("tool_id", "Tool"), ("procedure_id", "Procedure"), ("equipment_id", "Equipment"), ("manual_id", "Manual"))
  class ManualCardDataSource(ExtractDataSource):   # ExtractDataSource verified: parrot_loaders/extractors/base.py:50-90 (optional import, falls back to object)
      def __init__(self, name: str = SOURCE_NAME, config: Optional[dict[str, Any]] = None) -> None: ...   # config["catalog"] must be a ManualCatalogStore
      def infer_entity(self, fields: Sequence[str] | None) -> str: ...
      async def records_for(self, entity: str, *, filters: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]: ...
      async def snapshot(self, *, filters: Optional[dict[str, Any]] = None) -> dict[str, list[dict[str, Any]]]: ...
      async def extract(self, fields: list[str] | None = None, filters: dict[str, Any] | None = None) -> ExtractionResult: ...
  def register() -> None: ...                       # DataSourceFactory.register_api_source(SOURCE_NAME, ManualCardDataSource) at import (datasource.py:447-455 precedent)
  ```

### Module 9: Graph loader and tip maintenance
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/{graph_loader,tips}.py`
- **Responsibility**: `ManualGraphLoader` copies `ContractGraphLoader` (`startup_check`, `desired_edges`, `publish_all`, `publish`, `retract`, `_reconcile_edges`, `_verify`) over `OWNED_*` collections only; every `EdgeSpec.document()` carries `_from/_to + source_id/target_id/kind + origin="manual"`; duplicate `(_from,_to)` pairs are merged into one edge with list properties before writing (proposal F010). `TECHNICIAN_COLLECTIONS` are never read for reconciliation and never soft-deleted or edge-pruned. `tips.py` owns the explicit, idempotent re-link operation and the orphan report (U3, R1).
- **Depends on**: M2, M3, M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/graph_loader.py  (new; verified template: contracts/graph_loader.py:50-68, 106-154, 157-179, 197-249, 254-408, 471-548, 594-675)
  class EdgeSpec(BaseModel):            # same shape as contracts EdgeSpec (106-154) + origin
      collection: str; source_collection: str; source_key: str; target_collection: str; target_key: str; properties: dict[str, Any]; origin: Literal["manual"] = "manual"
      def document(self) -> dict[str, Any]: ...   # {_from, _to, source_id, target_id, kind, origin, **properties}
  class GraphPublicationReport(BaseModel): published: bool = False; nodes_upserted: dict[str, int]; edges_created: int; edges_removed: int; deactivated: dict[str, list[str]]; missing_nodes: list[str]; missing_edges: list[str]; errors: list[str]; tip_relink: Optional["RelinkReport"] = None
      def complete(self) -> bool: ...   # also False when tip_relink.failed is non-empty
  class ManualGraphLoader:
      def __init__(self, *, catalog: ManualCatalogStore, graph_store: Any, tenant_manager: Any = None, datasource: Optional[ManualCardDataSource] = None, ontology_dir: str | Path | None = None, domain: str = PROCEDURES_DOMAIN) -> None: ...
      def context(self) -> TenantContext: ...                 # domain.resolve_context (raises ProceduresDomainNotLoaded)
      async def startup_check(self) -> None: ...
      @staticmethod
      def desired_edges(snapshot: dict[str, list[dict[str, Any]]]) -> list[EdgeSpec]:
          """Deterministic, sorted; merges duplicate (collection, source, target) into one EdgeSpec with list-valued props (roles/contexts)."""
      async def publish_all(self) -> GraphPublicationReport: ...   # owned collections only; then tips.relink_tips for every manual whose revision changed
      async def publish(self, card: ManualCard) -> GraphPublicationReport: ...   # v1 delegates to publish_all (as contracts 594-609) — documented
      async def retract(self, manual_id: str) -> GraphPublicationReport:
          """Soft-delete owned vertices + remove owned edges incident to them; tech_tip* untouched (tips become orphaned via relink)."""
      async def _reconcile_edges(self, ctx: TenantContext, wanted: Sequence[EdgeSpec], report: GraphPublicationReport) -> None: ...   # only OWNED_EDGE_COLLECTIONS
      async def _verify(self, ctx: TenantContext, snapshot: Mapping[str, Any], wanted: Sequence[EdgeSpec], report: GraphPublicationReport) -> None: ...

  # packages/ai-parrot/src/parrot/knowledge/manuals/tips.py  (new)
  class RelinkOutcome(BaseModel): tip_id: str; previous_step_id: str | None; new_step_id: str | None; method: Literal["source_identity", "content_hash", "unchanged", "candidate", "orphaned"]; candidates: list[tuple[str, float]] = []
  class RelinkReport(BaseModel): manual_id: str; relinked: list[RelinkOutcome]; orphaned: list[RelinkOutcome]; candidates: list[RelinkOutcome]; failed: list[str]
  async def relink_tips(graph_store: Any, ctx: TenantContext, *, manual_id: str, previous_steps: Sequence[Step], current_steps: Sequence[Step], linked_by: str = "manuals.relink", now: Callable[[], datetime] = _utcnow) -> RelinkReport:
      """Idempotent. For each active tech_tip attached (tech_tip_on) to a previous step of this manual: (1) same source_identity among current steps ⇒ relink; (2) exact content_hash equality ⇒ relink; (3) rapidfuzz token_sort_ratio on TEXT ≥ 0.85 ⇒ candidate only (tip stays orphaned=true, candidates recorded for the curator); else orphaned=true. Never crosses manuals/tenants; appends to Tip.history; writes tech_tip_on edges with linked_by/linked_at; retries per tip, collecting failures instead of raising."""
  async def add_tip(graph_store: Any, ctx: TenantContext, *, step_id: str, text: str, author_employee_id: str, source_revision: str, now: Callable[[], datetime] = _utcnow) -> Tip: ...
  async def retire_tip(graph_store: Any, ctx: TenantContext, *, tip_id: str, by: str) -> None: ...
  ```

### Module 10: Retrieval, assembly, verification, release
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/procedures/{__init__,retrieval,assembly,verifier,service}.py`
- **Responsibility**: the release pipeline (U4): authorize → resolve → plan → traverse → assemble → verify (blocking) → audit → presign → release. `ProcedureRetrieval` copies `ContractRetrieval` (deterministic ordered trigger table failing closed to `Clarification`; per-pattern `authorize`; `execute_graph` via `OntologyGraphStore.execute_traversal` with `collection_binds`), with a procedures-shaped `_validate_projection`. The tenant gate is **tightened**: a missing tenant on the request is a denial (contracts only rejects a *mismatched* tenant — `retrieval.py:283-318`). `assemble_procedure` is pure and total over the traversal rows for one manual revision; `ProcedureVerifier` replaces the drop-unsupported semantics of `CitationVerifier` (R2).
- **Depends on**: M2, M3, M4, M9 (runtime: graph content)
- **Interface Skeleton**:
  ```python
  # parrot_tools/procedures/retrieval.py  (new; template verified: parrot_tools/contracts/retrieval.py:66-86, 142-243, 261-278, 282-319, 323-413, 431-494, 535-629, 681-745)
  READ_ROLES = frozenset({"technician", "manual_curator"}); CURATOR_ROLE = "manual_curator"
  PATTERNS: tuple[str, ...] = ("procedure_steps", "procedure_prerequisites", "procedures_for_equipment", "step_detail", "equipment_sharing_module", "procedure_in_force", "tips_for_procedure", "part_for_callout", "lookup")
  _TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...]   # ordered; es/en phrases ("cómo ensamblo", "how do i assemble", "qué necesito", "what do i need", "paso", "step", "next", "siguiente", …)
  class RequestContext(BaseModel): authenticated: bool; tenant_id: str; user_id: str; employee_id: str | None; roles: frozenset[str]; channel: str | None; session_id: str | None; equipment_serial: str | None = None; equipment_model: str | None = None   # Q7: from the session (asked once), never from model output
      # trusted only — constructed by the transport adapter from the platform session, never from model output
  class AuthorizationDenied(PermissionError): ...
  class Clarification(BaseModel): reason: str; candidates: list[EquipmentRef | ProcedureRef]; pattern: str | None
  class PatternPlan(BaseModel): pattern: str; bind_vars: dict[str, Any]; manual_id: str | None; procedure_id: str | None; step_order: int | None; as_of: date | None
  class RetrievalResult(BaseModel): pattern: str; rows: list[dict[str, Any]]; manual: ManualCard | None; revision: ManualVersion | None; fallback_sections: list[dict[str, Any]] = []
  def classify(question: str) -> str | None: ...
  class ProcedureRetrieval:
      def __init__(self, *, catalog: ManualCatalogStore, graph_store: Any, tenant_context: Any, ontology: Any, authorization: Any, pageindex: Any | None = None, today: Callable[[], date] = date.today) -> None: ...
      def authorize(self, context: RequestContext, *, pattern: Optional[str] = None, curator_only: bool = False) -> None:
          """Deny on: not authenticated; missing OR mismatched tenant; no READ_ROLES (or no CURATOR_ROLE when curator_only). Applied before EVERY protected read (traversal, catalog search, PageIndex fallback, media presign, tips, guided resume)."""
      async def resolve_equipment(self, text: str, context: RequestContext) -> EquipmentRef | Clarification: ...
      async def resolve_procedure(self, text: str, equipment: EquipmentRef | None, context: RequestContext) -> ProcedureRef | Clarification: ...
      async def plan(self, question: str, context: RequestContext) -> PatternPlan | Clarification: ...
      async def execute(self, plan: PatternPlan, context: RequestContext) -> RetrievalResult: ...
      async def execute_graph(self, plan: PatternPlan, context: RequestContext) -> list[dict[str, Any]]: ...
      async def fallback_lookup(self, question: str, manual_id: str, context: RequestContext) -> RetrievalResult:
          """PageIndexToolkit.search over the manual tree (verified: pageindex/toolkit.py search/retrieve) → answer_kind="lookup" with page citations and the 'not a verified procedure' line."""
      def aql_for(self, pattern: str) -> str: ...
      @staticmethod
      def _validate_projection(rows: Sequence[Mapping[str, Any]], *, pattern: str) -> None: ...

  # parrot_tools/procedures/assembly.py  (new)
  class AssembledProcedure(BaseModel): procedure: ProcedureView; steps: list[StepView]; prerequisites: Prerequisites; hazards: list[HazardView]; media: list[MediaView]; tips: list[TipView]; citations: list[ProcedureCitation]; revision: ManualVersion; missing_required: list[str]; unsupported_fields: list[str]; filtered_by_serial: list[str]; needs_serial: bool
  # StepView carries applicability: Literal["yes", "unknown"] — steps with applies()=="no" are excluded and listed in filtered_by_serial; needs_serial=True when any step is "unknown" because context.equipment_serial is None (the agent asks for the serial once, then re-plans)
  def assemble_procedure(result: RetrievalResult, *, kind: ProcedureAnswerKind, step_order: int | None = None, include_tips: bool = True) -> AssembledProcedure:
      """Pure. Applies models.applies(step, model=context.equipment_model, serial=context.equipment_serial) (Q7). Orders steps by has_step.order, checks precedes consistency, unions prerequisites (dedup by _key — FEAT-539 lesson), inlines hazards, picks media by roles (primary first; overview at procedure level), excludes tech_tip rows with orphaned=true or inactive targets, builds citations from step evidence (node_id/page/quote) for the selected revision; a single-step answer still carries that step's prerequisites and hazards. Records gaps in missing_required/unsupported_fields — it never fills them."""

  # parrot_tools/procedures/verifier.py  (new; replaces CitationVerifier semantics — verified: parrot_tools/contracts/verifier.py:102-206)
  class VerificationOutcome(BaseModel): answer: ProcedureAnswer; rejected: list[RejectedCitation]; blocked_reason: str | None
  class ProcedureVerifier:
      def __init__(self, *, catalog: ManualCatalogStore, evidence: Any, allowed_revision: ManualVersion) -> None: ...
      async def verify(self, assembled: AssembledProcedure, *, draft_prose: str, kind: ProcedureAnswerKind, pattern: str | None) -> VerificationOutcome:
          """Every citation must resolve verbatim in the archived revision (EvidenceArchive.resolve pattern, contracts/evidence.py:462-497). Completeness: missing_required or unsupported_fields non-empty ⇒ answer_kind="incomplete" with reason, NO steps released (R2). Prose is the only model-authored text and is dropped if it names a step/value not in the assembly."""

  # parrot_tools/procedures/service.py  (new; boundary verified: parrot_tools/contracts/service.py:68-105, 105-212, 214-232)
  class AnswerProducer(Protocol):
      async def draft(self, question: str, assembled: AssembledProcedure, *, context: RequestContext) -> str: ...   # optional intro prose only
  class AnswerOutcome(BaseModel): answer: ProcedureAnswer; audit_id: str; image_urls: list[str]; media_urls: list[str]
  class ProceduresAnswerService:
      def __init__(self, *, retrieval: ProcedureRetrieval, verifier_factory: Callable[[ManualVersion], ProcedureVerifier], catalog: ManualCatalogStore, file_manager: Any, presign_expiry: int = 900, producer: Optional[AnswerProducer] = None) -> None: ...
      async def answer(self, question: str, *, request_context: RequestContext, producer: Optional[AnswerProducer] = None) -> AnswerOutcome | Clarification:
          """authorize → plan → execute → assemble → (producer.draft) → verify → record_answer (audit BEFORE release; failed audit ⇒ no release) → presign media (figures.presign) → AnswerOutcome. Raw producer output never leaves this method."""
      async def stream_answer(self, question: str, *, request_context: RequestContext, producer: Optional[AnswerProducer] = None) -> AsyncIterator[str]:
          """Buffers everything until answer() has released (service.py:214-232 pattern)."""
  ```

### Module 11: Toolkit, agent, guided mode
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/procedures/{toolkit,agent,guided}.py`
- **Responsibility**: `ProceduresToolkit(TaskMemoryToolsMixin, AbstractToolkit)` with `tool_prefix="proc"`, one action per tool, per-tool `_gate()` running `retrieval.authorize`, `confirming_tools={"add_tip", "verify_procedure", "retire_tip"}`; `ProceduresAgent(Agent)` creates the toolkit **before** `super().__init__` (contracts `agent.py:232-268`) and implements the **transport adapter** (R3): `ask()`/`ask_stream()`/`invoke()` build a trusted `RequestContext` from the platform session kwargs, call the service, and return an `AIMessage` whose `output` is the released prose + rendered steps, `structured_output=ProcedureAnswer`, `image_urls`/`media_urls` from the outcome — never the ReAct loop's raw output. Guided mode composes task memory; episodes use `WORKFLOW_PATTERN`.
- **Depends on**: M10 (and M12 for the `AIMessage` URL fields)
- **Interface Skeleton**:
  ```python
  # parrot_tools/procedures/toolkit.py  (new; AbstractToolkit attrs verified: tools/toolkit.py:231-272; tool generation 547-590; TaskMemoryToolsMixin verified: tools/working_memory/task_memory/tools.py:91-102, 397-435, 529-538, 664, 687, 772-782; composition precedent: tools/working_memory/tool.py:47-89, 141-155)
  class ProceduresToolkit(TaskMemoryToolsMixin, AbstractToolkit):
      name = "procedures"; tool_prefix = "proc"; confirming_tools = {"add_tip", "verify_procedure", "retire_tip"}; exclude_tools = ("get_tools", "get_tools_sync")
      def __init__(self, *, service: ProceduresAnswerService, request_context: RequestContext, library: Any | None = None, task_memory: Any | None = None, episodic: Any | None = None) -> None: ...
      async def find_procedure(self, query: str, equipment: Optional[str] = None) -> dict: ...
      async def get_steps(self, procedure_id: str) -> dict: ...
      async def get_step(self, procedure_id: str, order: int) -> dict: ...
      async def prerequisites(self, procedure_id: str) -> dict: ...
      async def media_for_step(self, step_id: str) -> dict: ...
      async def tips_for_step(self, step_id: str) -> dict: ...
      async def related_equipment(self, equipment_id: str) -> dict: ...
  async def find_part(self, media_id: str, callout: str) -> dict: ...                    # Q8: part_for_callout traversal
  async def set_equipment_serial(self, serial: str) -> dict: ...                          # Q7: stores on the session-bound RequestContext (validated with normalize_serial against the resolved manual's formats)
      async def add_tip(self, step_id: str, text: str) -> dict: ...                 # author = request_context.employee_id (trusted); confirming
      async def retire_tip(self, tip_id: str) -> dict: ...                          # curator; confirming
      async def verification_queue(self, limit: int = 20) -> dict: ...              # curator
      async def verify_procedure(self, procedure_id: str) -> dict: ...              # curator; confirming
      async def start_guided(self, procedure_id: str) -> dict: ...                  # begin_task(goal, steps=[{label: step_id, title, description, required: True, depends_on_labels: [prev]}], plan_complete=True)
      async def next_step(self, task_id: str) -> dict: ...                          # recall_task → first pending step → get_step view with media
      async def mark_done(self, task_id: str, step_id: str, note: Optional[str] = None) -> dict: ...   # update_step(expected_revision=current, status="completed", evidence_refs=[f"procedure:{procedure_id}@{revision}"]) — Q10: synthetic evidence ref satisfies the default CompletionPolicy (models.py:683); no task-memory change
      async def resume_guided(self) -> dict: ...                                    # TaskAssociationStore (association.py:316) + select_task (tools.py:687); scope (chatbot_id,user_id,session_id) (models.py:571-587)
  # parrot_tools/procedures/guided.py  (new)
  def task_steps_for(procedure: AssembledProcedure) -> list[dict[str, Any]]: ...
  async def record_completion(episodic: Any, *, namespace: Any, procedure: AssembledProcedure, user_id: str) -> None:
      """EpisodicMemoryStore.record_episode(category=EpisodeCategory.WORKFLOW_PATTERN, outcome=SUCCESS, metadata={procedure_id, manual_id, revision}) — verified: memory/episodic/store.py:106-153, models.py:29-36."""
  # parrot_tools/procedures/agent.py  (new; template verified: parrot_tools/contracts/agent.py:29-37, 214, 232-268, 270-326, 338-353)
  from parrot.bots import Agent                       # verified: parrot_tools/contracts/agent.py:29
  PROCEDURES_SYSTEM_PROMPT: str
  class ProceduresAgent(Agent):
      def __init__(self, *, service: ProceduresAnswerService, context_factory: Callable[[dict[str, Any]], RequestContext], **kwargs: Any) -> None: ...
      def agent_tools(self) -> list[Any]: ...
      async def ask(self, question: str, *args: Any, **kwargs: Any) -> AIMessage:
          """Transport adapter: context = context_factory(kwargs) (user_id/session_id/tenant from the platform session — never from the model); outcome = service.answer(...); return AIMessage(output=render(outcome), structured_output=outcome.answer, image_urls=outcome.image_urls, media_urls=outcome.media_urls). Clarification ⇒ AIMessage with the candidates. Never raises UngatedAnswerRefused for ask()."""
      async def ask_stream(self, question: str, *args: Any, **kwargs: Any) -> AsyncIterator[str]: ...   # service.stream_answer
      async def invoke(self, *args: Any, **kwargs: Any) -> Any: ...            # gated like ask(); or raise UngatedAnswerRefused("invoke") when no context can be built
  ```

### Module 12: Media delivery
- **Path**: `packages/ai-parrot/src/parrot/models/responses.py`; `packages/ai-parrot-integrations/src/parrot/integrations/parser.py`; `integrations/{msteams,slack,telegram,whatsapp}/wrapper.py`; `integrations/telegram/crew/crew_wrapper.py`; `integrations/whatsapp/bridge_wrapper.py`; `integrations/slack/assistant.py`
- **Responsibility**: U1 (option a). Add `image_urls: list[str]` and `media_urls: list[str]` (validated http(s), no `data:` here) to **both** `AIMessage` and `AgentResponse`, synced in `sync_documents_and_paths`; `ParsedResponse` gains `image_urls`/`media_urls` carried separately from its `Path` lists, and `parse_response` never routes a URL through the `exists()` filter. Channel behaviour: Teams renders `image_urls[:3]` as `ImageSection` entries and links the overflow with their labels; Slack renders every URL as an image block; Telegram downloads each URL to a bounded temp file (allowlisted hosts from `PARROT_MEDIA_URL_HOSTS`, redirect validation, size/time caps, cleanup) and reuses `send_photo(FSInputFile)`; WhatsApp passes the URL straight to `client.send_image(image=url)` (the `chart.public_url` precedent, `whatsapp/wrapper.py:303`) and falls back to download on provider rejection. Existing `Path` attachments are untouched byte-for-byte.
- **Depends on**: — (independent lane)
- **Interface Skeleton**:
  ```python
  # models/responses.py  (modifies responses.py:90 — insert after `media`; and :1112 — insert after AgentResponse.media; :1157 sync_documents_and_paths copies image_urls/media_urls from self.response)
  class AIMessage(BaseModel):
      image_urls: List[str] = Field(default_factory=list, description="Remote http(s) image URLs (presigned figures); rendered by URL-capable channels")
      media_urls: List[str] = Field(default_factory=list, description="Remote http(s) media URLs (video/audio) deliverable as-is")
      @field_validator("image_urls", "media_urls")
      def _only_http(cls, v: List[str]) -> List[str]: ...   # ValueError unless every item startswith http:// or https://
  class AgentResponse(BaseModel): image_urls: List[str]; media_urls: List[str]   # same validator; validate_assignment=True kept (responses.py:1123-1131)

  # integrations/parser.py  (modifies parser.py:92 — add fields after `media`; and :519 — new block before "# Extract images")
  @dataclass
  class ParsedResponse:
      image_urls: List[str] = field(default_factory=list); media_urls: List[str] = field(default_factory=list)
  def parse_response(response: Any) -> ParsedResponse:
      """Existing Path logic unchanged; additionally copies response.image_urls / response.media_urls (and the same on response.response for AgentResponse) into the new lists — no exists() check, no Path() coercion."""

  # integrations/msteams/wrapper.py  (modifies wrapper.py:1259 `_parsed_to_card_spec`): image_entries from parsed.images[:3] http(s) strings (existing) THEN parsed.image_urls; cap 3 total; overflow rendered as labelled links
  # integrations/slack/wrapper.py    (modifies wrapper.py:591 `_build_blocks`): one image block per parsed.image_urls entry
  # integrations/telegram/wrapper.py (modifies wrapper.py:2960 `_send_attachments` and the duplicate sender at :3714): download_to_temp(url) → send_photo(FSInputFile)
  # integrations/whatsapp/wrapper.py (modifies wrapper.py:286 `_send_parsed_response`): client.send_image(to=…, image=url) per parsed.image_urls; on failure download_to_temp then existing path
  # integrations/telegram/crew/crew_wrapper.py:351, whatsapp/bridge_wrapper.py:260 (via _send_parsed_response), slack/assistant.py:184/237 (via _build_blocks): covered by the shared helpers — tests assert each path renders a URL
  # integrations/media_download.py  (new)
  async def download_to_temp(url: str, *, allowed_hosts: Sequence[str], max_bytes: int = 10 * 1024 * 1024, timeout_s: float = 15.0) -> Path:
      """aiohttp GET with redirect validation against allowed_hosts, size/time caps; caller removes the file (context manager variant provided)."""
  ```

### Module 13: CLI, packaging, docs
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/procedures/{cli,__main__}.py`; `packages/ai-parrot/src/parrot/cli/__init__.py`; `packages/ai-parrot/pyproject.toml`; `docs/knowledge/manuals.md`
- **Responsibility**: a **click** group `manuals` (not the contracts argparse — proposal F018) with `add`, `add-video`, `refresh`, `verify`, `queue`, `relink-tips`, `export` (Q9), `spike {figures,media,video,tips}`; registered lazily in `cli._lazy_commands` with an install hint in `cli._lazy_extras`; a `manuals` extra that self-references `ai-parrot[graphindex,bookstore]` (rapidfuzz stays declared **only** in `graphindex` — `tests/knowledge/contracts/test_dependency_boundary.py` asserts `holders == ["graphindex"]`); operator docs (install, tenancy, storage, spike gate, limitations).
- **Depends on**: M8, M10, M11, M14
- **Interface Skeleton**:
  ```python
  # parrot_tools/procedures/cli.py  (new)
  @click.group(name="manuals")
  def manuals() -> None: """Manuals: ingest assembly manuals, align videos, curate procedures."""
  @manuals.command("add")     # --equipment (multiple) --revision --source-uri --force --tenant --dsn
  @manuals.command("add-video")  # <url> --manual --transcript <json> --force
  @manuals.command("refresh")    # <manual_id> <file> --revision
  @manuals.command("verify")     # <manual_id> <procedure_id> --user
  @manuals.command("queue")      # --limit
  @manuals.command("relink-tips")  # <manual_id>
  @manuals.command("export")     # <manual_id> --out <dir> --zip/--no-zip --include-tips/--no-include-tips  (curator)
  @manuals.command("spike")      # {figures,media,video,tips} --corpus <dir>
  def build_library(*, dsn: str, tenant: str, storage_root: Path, evidence_root: Path, adapter: Any | None) -> ManualLibrary: ...   # injected factory, as contracts main(factory=)
  # parrot/cli/__init__.py  (modifies cli/__init__.py:109 `cli._lazy_commands = {` — add `"manuals": "parrot_tools.procedures.cli",`; and :139 `cli._lazy_extras = {` — add `"manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot[manuals]",`)
  # packages/ai-parrot/pyproject.toml  (modifies pyproject.toml:341 — insert after the `bookstore` extra)
  # manuals = ["ai-parrot[graphindex,bookstore]"]     # self-reference precedent: pyproject.toml:334
  ```

### Module 14: Export bundle
- **Path**: `packages/ai-parrot/src/parrot/knowledge/manuals/export.py`
- **Responsibility**: Q9. Build a self-contained, offline-consumable bundle for one manual revision from the catalog card and object storage — never from presigned URLs and never exposing graph internals. Curator-only (`authorize(curator_only=True)` when invoked through the toolkit/CLI service factory). Deterministic output (sorted keys, stable file names) so bundles are diffable across revisions.
- **Depends on**: M2, M4, M6
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/manuals/export.py  (new)
  BUNDLE_SCHEMA_VERSION = "1.0"
  class BundleManifest(BaseModel): schema_version: str; manual_id: str; revision: str; version_n: int; generated_at: datetime; source_sha256: str; files: dict[str, str]   # relative path → sha256
  class ExportReport(BaseModel): bundle_dir: Path; zip_path: Path | None; procedures: int; steps: int; figures: int; figures_missing: list[str]; tips: int; bytes: int
  async def export_bundle(card: ManualCard, *, file_manager: Any, out_dir: Path, include_tips: bool = True, zip_bundle: bool = True, tips: Sequence[Tip] = ()) -> ExportReport:
      """Writes <manual_id>-<revision>.bundle/{manifest.json, procedures.json, captions.json, videos.json, figures/<media_id>.png}; figures via file_manager.download_file(storage_key) (FileManagerInterface, navigator-api 4.0.0 — F024); missing storage objects are listed, not fatal; optional zip. procedures.json carries steps with applicability, hazards, prerequisites, media roles/callouts and active non-orphaned tips."""
  def render_procedures(card: ManualCard, tips: Sequence[Tip]) -> dict[str, Any]: ...   # pure; sorted; no URLs
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_common_reexports_identity` | M1 | `contracts.models.Evidence is common.provenance.Evidence`; `_quote_supported is quote_supported` |
| `test_common_import_boundary` | M1 | `knowledge/common` imports no `contracts`, `parrot_tools`, `asyncpg`, `arango` (AST scan, as `test_dependency_boundary.py`) |
| `test_step_requires_substantiated_evidence` | M2 | `Step(text=Extracted(value=…, evidence=None))` ⇒ `ValueError` |
| `test_step_identity_order_independent` | M2 | renumbering steps leaves `step_id`/`content_hash` unchanged; text change changes `content_hash` |
| `test_content_hash_numeric_fields` | M2 | different torque ⇒ different hash |
| `test_procedure_answer_kind_invariants` | M2 | `procedure` needs steps+citations; `incomplete` carries reason and no steps; `denied` carries nothing |
| `test_media_ref_never_stores_url` | M2 | `storage_key="https://…"` rejected |
| `test_procedures_yaml_parses_extra_forbid` | M3 | `OntologyParser.load` validates; entity/relation names match `OWNED_*`/`TECHNICIAN_COLLECTIONS` |
| `test_domain_resolves_only_with_defaults_dir` | M3 | `default_tenant_manager()` resolves `procedures`; a manager on a foreign dir raises `ProceduresDomainNotLoaded` |
| `test_patterns_authorization_has_role` | M3 | every traversal pattern has `default_deny` and a `has_role` rule; curator-only patterns exclude `technician` |
| `test_catalog_contract_inmemory` | M4 | in-memory `ManualCatalogStore` double passes the ABC contract suite (search, queue ordering, outbox) |
| `test_postgres_catalog_regconfig` | M4 | DDL uses the configured regconfig; identifier validated (live `pg_pool`, skipped without DSN) |
| `test_select_procedure_nodes_density` | M5 | numbered-list density ranks a headingless procedure above prose |
| `test_validate_steps_drops_unsupported` | M5 | a step whose quote is not verbatim is dropped, not kept at low confidence |
| `test_assemble_card_resolves_parts_and_precedes` | M5 | `similarity ≥ 0.85` resolves; "before step 3" adds an explicit `precedes` edge with evidence |
| `test_extract_markdown_per_page_unchanged_without_images_dir` | M6 | call signature/return identical; `pages=` never passed (mock `to_markdown`) |
| `test_extract_page_images_bbox` | M6 | synthetic PDF with two images ⇒ two `PageImage`s with bboxes and sha256 |
| `test_pair_figures_primary_by_label_secondary_by_distance` | M6 | label match ⇒ primary/1.0; uncaptioned same-page ⇒ secondary with scaled confidence; missing label ⇒ no link + queue entry |
| `test_resolve_captioner_capability` | M6 | client with `ask_to_image` ⇒ adapter; `ClaudeAgentClient`-like `NotImplementedError` ⇒ `CaptioningUnavailable` |
| `test_presign_rejects_non_http` | M6 | `file://` from a local manager ⇒ `MediaUnavailable`; `expiry=` kwarg used |
| `test_align_deterministic_monotonic` | M7 | bm25s + ordinal constraint yields non-overlapping monotonic segments; unaligned steps returned |
| `test_judge_alignment_drops_hallucinated_ids` | M7 | judged ids outside candidates dropped; `force` resets `judged` |
| `test_align_video_low_coverage_overview` | M7 | coverage < 0.30 ⇒ one overview `MediaRef`, no per-step segments |
| `test_add_manual_pipeline_fake_indexer` | M8 | `FakeIndexer`/`FakeAdapter` doubles (copied from contracts tests) ⇒ card, figures, queue entries; image-only PDF refused |
| `test_refresh_appends_version_and_relinks` | M8 | rev B ⇒ `versions[]` appended with `valid_from/valid_to`, relink report attached |
| `test_datasource_routing_order` | M8 | `step_id` routes to Step before `manual_id`; unknown field ⇒ error |
| `test_desired_edges_merges_duplicate_pairs` | M9 | two `(step, media)` links with roles primary+secondary ⇒ one `EdgeSpec` with `roles=[…]` |
| `test_publish_all_never_touches_technician_collections` | M9 | `FakeGraphStore` (contracts `test_graph_loader.py:41-60`) with pre-seeded `tech_tip*` ⇒ untouched after publish and retract |
| `test_edges_carry_origin_and_triple` | M9 | every written edge has `source_id/target_id/kind/origin` |
| `test_relink_tips_matrix` | M9 | inserted, renumbered, reworded, duplicated, deleted steps; changed torque ⇒ candidate not relink; repeated run idempotent; failure collected not raised; no cross-manual relink |
| `test_authorize_tightened_tenant_gate` | M10 | missing tenant ⇒ denied (contracts allowed it); mismatched ⇒ denied; no role ⇒ denied; curator_only enforced |
| `test_classify_triggers_fail_closed` | M10 | unknown phrasing ⇒ `Clarification`; es/en triggers map to patterns |
| `test_assemble_procedure_complete_and_gaps` | M10 | ordered steps + union prerequisites dedup by key; orphaned tips excluded; missing `has_step` order ⇒ `missing_required` |
| `test_verifier_blocks_incomplete` | M10 | `missing_required` ⇒ `answer_kind="incomplete"`, zero steps released (contrast with contracts drop semantics) |
| `test_verifier_prose_cannot_add_steps` | M10 | prose naming an unknown step/value is dropped |
| `test_service_audit_before_release` | M10 | failing `record_answer` ⇒ no `AnswerOutcome`, no presign call |
| `test_stream_answer_buffers` | M10 | nothing yielded before release |
| `test_toolkit_tool_names_and_confirming` | M11 | names `proc_*`; confirming set; `_gate` denies without role |
| `test_agent_ask_is_gated` | M11 | `ask()` returns `AIMessage` with `structured_output` + `image_urls`; raw draft never in `output` |
| `test_guided_roundtrip` | M11 | `start_guided` → `next_step` → `mark_done` (with `expected_revision`) → `resume_guided` across a new session via association store |
| `test_completion_records_workflow_pattern_episode` | M11 | `record_episode` called with `WORKFLOW_PATTERN` and procedure metadata |
| `test_aimessage_url_fields_validate` | M12 | `image_urls=["https://…"]` ok; `["/tmp/x.png"]` ⇒ `ValueError`; Path fields unchanged |
| `test_parse_response_keeps_urls_and_paths` | M12 | URL lists survive; non-existent Paths still dropped; `AgentResponse` round-trip via `sync_documents_and_paths` |
| `test_teams_renders_image_urls_cap3_with_overflow_links` | M12 | 4 URLs ⇒ 3 `ImageSection` + 1 link with label |
| `test_slack_renders_image_urls` | M12 | one image block per URL |
| `test_telegram_downloads_then_send_photo` | M12 | allowlisted host ⇒ temp file → `send_photo`; foreign host/redirect/oversize ⇒ refused, cleanup verified; both sender paths |
| `test_whatsapp_direct_url_then_fallback` | M12 | `send_image(image=url)`; provider error ⇒ download path |
| `test_applies_matrix` | M2 | model mismatch ⇒ no; ranges present + no serial ⇒ unknown; inside/outside ranges; unparseable serial ⇒ ValueError from normalize_serial |
| `test_applicability_requires_evidence` | M2 | serial_ranges without evidence ⇒ ValueError |
| `test_parse_serial_qualifier` | M5 | "from S/N 2024-0001", "serial numbers A100 to A250", Spanish forms; unparseable ⇒ None + queue entry |
| `test_map_callouts_structured_output` | M6 | fake mapper returns CalloutMap; part_number exact and similarity resolution; unresolved listed; disabled when callouts_enabled is False |
| `test_assemble_filters_by_serial_and_flags_unknown` | M10 | steps outside range excluded + listed; unknown kept with note; needs_serial when serial absent |
| `test_find_part_traversal` | M11 | proc_find_part returns the Part for a callout label via part_for_callout |
| `test_set_equipment_serial_validates` | M11 | serial validated against the manual's formats; stored on the trusted context only |
| `test_export_bundle_layout_and_manifest` | M14 | manifest sha256s match files; procedures.json sorted/deterministic; no http(s) strings anywhere; missing figure listed not fatal; zip optional |
| `test_export_excludes_orphaned_tips` | M14 | orphaned/inactive tips absent from the bundle |
| `test_cli_export_is_curator_only` | M13 | technician context ⇒ AuthorizationDenied |
| `test_cli_group_registered_lazily` | M13 | `cli._lazy_commands["manuals"]` resolves; missing satellite ⇒ install hint |
| `test_manuals_extra_self_reference` | M13 | `pyproject` `manuals` extra equals `["ai-parrot[graphindex,bookstore]"]`; rapidfuzz holders still `["graphindex"]` |

### Integration Tests
| Test | Description |
|---|---|
| `test_ingest_publish_answer_roundtrip` | corpus PDF → `ManualLibrary.add_manual` → `ManualGraphLoader.publish_all` (`FakeGraphStore`) → `ProceduresAnswerService.answer("how do I assemble X")` ⇒ `procedure` answer with ordered steps, primary figures, citations |
| `test_tip_survives_revision` | spike 4 in-process: rev A + 3 tips → rev B ⇒ 1 relinked by identity, 1 by hash, 1 orphaned; answer excludes the orphan |
| `test_live_arango_publish` | `arango_params` fixture (skipped without env): real `initialize_tenant` + publish + traversal patterns return rows |
| `test_live_postgres_catalog` | `pg_pool`/`temp_schema` fixtures: upsert/search/queue against Postgres |
| `test_channel_delivery_matrix` | Teams/Slack/Telegram/WhatsApp wrappers with a mocked transport: one presigned URL delivered per channel contract |

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/knowledge/manuals/conftest.py
@pytest.fixture()
def manual_pdf(tmp_path) -> Path: ...          # 6-page synthetic manual: cover, parts table, one assembly procedure with 5 numbered steps, two figures with "Fig. 1"/"Fig. 2" captions, one hazard box
@pytest.fixture()
def manual_pdf_rev_b(tmp_path) -> Path: ...    # same with step 3 renumbered, step 4 reworded, step 5 removed
@pytest.fixture()
def image_only_pdf(tmp_path) -> Path: ...      # refused path
@pytest.fixture()
def fake_graph_store(): ...                    # promoted copy of tests/knowledge/contracts/test_graph_loader.py:41-60 (create_edges never updates; soft-deleted hidden) into tests/knowledge/_support/graph.py
@pytest.fixture()
def fake_adapter(): ...                        # scripted ask_structured (contracts test_carding.py:95-110 shape)
@pytest.fixture()
def fake_file_manager(): ...                   # upload_file records keys; get_file_url returns https://fake/… with expiry echo
@pytest.fixture()
def request_context() -> RequestContext: ...   # authenticated technician, tenant "t1"
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1** Spike gate reports exist under `artifacts/logs/FEAT-601/` and pass their thresholds (figures ≥ 90 % ordered/no missing required, ≥ 80 % correct primary figure; video ≥ 70 % coverage without precision loss from the judged tail; tips 3/3 expected outcomes; media 1 figure rendered/sent on Teams, WhatsApp, Telegram). Below threshold on figures, the design switches to procedure-level figures + per-step vision pass **before** M6/M10 are marked done (G9).
- [ ] **AC2** `from parrot.knowledge.common.provenance import Evidence, Extracted, FieldProvenance, trim_quote` works; every existing contracts import resolves to the same objects; `packages/ai-parrot/tests/knowledge/contracts/` passes unchanged (U2).
- [ ] **AC3** A `Step` cannot be constructed or stored without a verbatim, substantiating `Evidence`; `validate_steps` drops rather than down-weights (G2).
- [ ] **AC4** `StepIdentity.step_id` is minted once and independent of `order`; `content_hash` is used for exact equality only; no hash "similarity" exists anywhere in the code (R1).
- [ ] **AC5** `ManualGraphLoader.publish_all` / `retract` never read, soft-delete or prune `tech_tip`, `tech_tip_on`, `tech_tip_by`; every owned edge carries `source_id/target_id/kind/origin`; duplicate `(_from,_to)` links are merged before write (U3, F010).
- [ ] **AC6** `relink_tips` is idempotent and covers the matrix (insert, renumber, reword, duplicate, delete, changed numeric, repeated run, concurrent tip, failed relink + retry, retract, no cross-manual); orphans keep source revision + history; retrieval excludes orphaned/inactive tips; publication reports link failures (U3).
- [ ] **AC7** `ProcedureVerifier` blocks release (`answer_kind="incomplete"`, zero steps) when a required step or critical field is missing or unsupported; prose can never add a step, value or citation (U4, R2).
- [ ] **AC8** `ProceduresAgent.ask()` returns an `AIMessage` containing only released content and `image_urls`/`media_urls`; Slack/WhatsApp/Telegram wrappers deliver a procedure answer end to end in the channel matrix test; no raw producer output reaches chat, MCP, HTTP, streaming or memory history (U4, R3).
- [ ] **AC9** `authorize` denies missing identity, missing **or** mismatched tenant, insufficient role, unauthorized writes and forged attribution; the same gate guards catalog search, PageIndex fallback, media presign, tips and guided resume (U5).
- [ ] **AC10** `procedures.ontology.yaml` validates under `extra="forbid"`; every pattern has `default_deny` + `has_role`; curator-only patterns exclude `technician`; no `certified_for` relation exists (R4).
- [ ] **AC11** `procedures` resolves only through `default_tenant_manager()`; a foreign-dir manager raises `ProceduresDomainNotLoaded` at `startup_check` (F011).
- [ ] **AC12** `extract_markdown_per_page(path)` without `images_dir` is byte-identical in behaviour; `pages=` is never passed; `extract_page_images` returns bboxes for a synthetic PDF (F013).
- [ ] **AC13** Figure captioning resolves the client by capability; never receives a URL; `presign` uses `expiry=` and rejects non-http(s) results; no URL is ever persisted in a `MediaRef` or graph node (G4, F023, F024).
- [ ] **AC14** `AIMessage`/`AgentResponse` gain validated `image_urls`/`media_urls`; `parse_response` keeps them without `exists()`; Teams caps at 3 with labelled overflow links; Slack renders all; Telegram downloads with host allowlist, redirect validation, size/time caps and cleanup; WhatsApp direct URL then fallback; all seven send paths covered; existing `Path` behaviour unchanged (U1).
- [ ] **AC15** Guided mode round-trips across sessions via `TaskAssociationStore`/`select_task`; `mark_done` passes `expected_revision`; completion records a `WORKFLOW_PATTERN` episode with procedure metadata; `EpisodeCategory` is not modified.
- [ ] **AC16** `parrot manuals --help` lists the seven commands; `cli._lazy_extras["manuals"]` gives an install hint when the satellite is missing; the `manuals` extra self-references `ai-parrot[graphindex,bookstore]` and `test_dependency_boundary.py` still passes.
- [ ] **AC17** Ontology imports use submodules (`parrot.knowledge.ontology.schema/graph_store/tenant/parser`), never the package root (FEAT-540 lazy-root compatibility).
- [ ] **AC18** No new third-party dependency; `ruff check` (TID251) and `black --check` pass; `docs/knowledge/manuals.md` documents install, tenancy, storage, the spike gate and v1 limitations (OCR, callouts, serials, offline).
- [ ] **AC20** Serial applicability (Q7): `Applicability` with evidence on every serial-qualified step; `applies()` matrix passes; answers never show a step that does not apply, never hide an undecidable one, and ask for the serial once when needed.
- [ ] **AC21** Callouts (Q8): exploded views get one structured vision call; resolved callouts become `depicts` edges; unresolved ones enter the verification queue; `proc_find_part` answers by label; the pass is disabled until spike 1 passes.
- [ ] **AC22** Export (Q9): `parrot manuals export` produces a deterministic bundle with a sha256 manifest, figures as files, captions, applicability, hazards, active tips and video deep links; no presigned URLs or graph internals; curator-only.
- [ ] **AC19** `pytest packages/ai-parrot/tests/knowledge/manuals packages/ai-parrot/tests/knowledge/common packages/ai-parrot-tools/tests/procedures packages/ai-parrot-integrations/tests -q` passes; live Arango/Postgres tests skip cleanly without credentials.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified on `dev` @ `55e01d496` (2026-09-25); line numbers come from the FEAT-601 research digests `sdd/state/FEAT-601/findings/F001–F031` (all re-read 2026-09-24/25) plus the edit-site pass below. Implementation agents MUST NOT reference imports, attributes or methods not listed here without `grep`/`read` verification.

### Verified Imports
```python
from parrot.knowledge.contracts.models import Evidence, Extracted, FieldProvenance, trim_quote, MAX_QUOTE_CHARS, UNSUBSTANTIATED_CONFIDENCE_CAP  # verified: knowledge/contracts/models.py:88, 91, 111, 205, 235, 265 (moved to knowledge/common by M1; re-exported)
from parrot.knowledge.contracts.models import VerificationState, ProvenanceOrigin, AnswerProvenance, Citation, ContractVersion, ContractAnswer, derive_provenance  # verified: models.py:161, 162, 175, 701, 417, 750, 800
from parrot.knowledge.contracts.carding import select_header_nodes, select_obligation_nodes, deontic_density, draft_contract, validate_header_evidence, fallback_header_draft, similarity  # verified: carding.py:235, 291, 216, 678, 486, 644, 868
from parrot.knowledge.contracts.graph_loader import ContractGraphLoader, EdgeSpec, GraphPublicationReport, ContractsDomainNotLoaded  # verified: graph_loader.py:197, 106, 157, 102
from parrot.knowledge.contracts.library import ContractLibrary, TreeIndexer, pdf_markdown  # verified: library.py:481, 96, 205
from parrot.knowledge.contracts.catalog import ContractCatalogStore, SearchHit, UpsertResult, VerificationQueueEntry  # verified: catalog.py:292, 188-223
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog  # verified: catalog_postgres.py:294
from parrot.knowledge.contracts.datasource import ContractCardDataSource, SOURCE_NAME, ENTITY_ROUTING_ORDER  # verified: datasource.py:144, 55, 58
from parrot.knowledge.contracts.evidence import EvidenceRef, StagingArea, EvidenceArchive, normalize_quote  # verified: evidence.py:78, 145, 462; agent.py:30
from parrot.knowledge.bookstore.models import TocEntry  # verified: contracts/models.py:22
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc, sample_sections, generate_card_fields  # verified: bookstore/carding.py:49, 73, 88, 193, 157
from parrot.knowledge.bookstore.relations import candidate_pairs, judge_relations  # verified: bookstore/relations.py:296, 372
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page, build_node_markdown_map  # verified: pdf_to_markdown.py:35, 97
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # verified: contracts/library.py:1222-1226
from parrot.knowledge.ontology.schema import OntologyDefinition, EntityDef, PropertyDef, RelationDef, TraversalPattern, AuthorizationSpec, AuthorizationRule  # verified: ontology/schema.py:419, 40, 18, 114, 261, 212, 176
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # verified: ontology/tenant.py:48
from parrot.knowledge.ontology.parser import OntologyParser  # verified: ontology/parser.py:29, 93
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # verified: ontology/graph_store.py:91-827
from parrot.knowledge.ontology.authorization import AuthorizationChecker  # verified: ontology/authorization.py:62 (check)
from parrot.tools.toolkit import AbstractToolkit  # verified: tools/toolkit.py:231-272
from parrot.tools.working_memory.task_memory.tools import TaskMemoryToolsMixin  # verified: task_memory/tools.py:91-102, 397, 529, 664, 687, 772
from parrot.tools.working_memory.task_memory.association import TaskAssociationStore  # verified: task_memory/association.py:316
from parrot.tools.working_memory.task_memory.models import TaskScope, CompletionPolicy  # verified: task_memory/models.py:571, 683
from parrot.memory.episodic.store import EpisodicMemoryStore  # verified: memory/episodic/store.py:106
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome  # verified: memory/episodic/models.py:29, 20-38 (WORKFLOW_PATTERN at :36)
from parrot.bots import Agent  # verified: parrot_tools/contracts/agent.py:29
from parrot.models.responses import AIMessage, AgentResponse  # verified: models/responses.py:75-96, 1094-1131
from parrot.interfaces.file import FileManagerInterface, LocalFileManager, TempFileManager  # verified: interfaces/file/__init__.py:1-23 (S3FileManager/GCSFileManager lazy via __getattr__ :34-47)
from parrot.storage.overflow import OverflowStore  # verified: storage/overflow.py:20, 119-144
from parrot_tools.contracts.retrieval import ContractRetrieval, RequestContext, AuthorizationDenied, Clarification, PatternPlan, RetrievalResult, classify  # verified: parrot_tools/contracts/retrieval.py:261, 142-214, 222
from parrot_tools.contracts.toolkit import ContractsToolkit  # verified: parrot_tools/contracts/toolkit.py:39
from parrot_tools.contracts.service import AnswerProducer, AnswerOutcome, ContractsAnswerService  # verified: service.py:68, 95, 105
from parrot_tools.contracts.verifier import CitationVerifier  # verified: verifier.py:102
from parrot_tools.contracts.agent import ContractsAgent, UngatedAnswerRefused  # verified: agent.py:232, 214
from parrot_tools.contracts.flow import ContractsDraftProducer  # verified: flow.py:121
from parrot_loaders.basevideo import BaseVideoLoader  # verified: parrot_loaders/basevideo.py:860 (transcript_to_blocks)
from parrot_loaders.youtube import YoutubeLoader  # verified: parrot_loaders/youtube.py:30 (NOT video.py — F025)
from parrot_loaders.extractors.base import ExtractDataSource, ExtractedRecord, ExtractionResult  # verified: extractors/base.py:18-48, 50-90
from parrot_loaders.extractors.factory import DataSourceFactory  # verified: extractors/factory.py:35-80
from parrot.integrations.parser import parse_response, ParsedResponse, ChartData  # verified: integrations/parser.py:83, 519, 21-38
import pymupdf, pymupdf4llm, rapidfuzz, bm25s  # verified in venv: pymupdf 1.27.1, pymupdf4llm 0.0.27, rapidfuzz 3.11.0, bm25s 0.2.14 (F026)
```

### Existing Class Signatures
```python
# knowledge/contracts/models.py
class Evidence(BaseModel):                       # 205: node_id: str (min_length=1); quote: str (max_length=MAX_QUOTE_CHARS); page: Optional[int] ge=1; def substantiates(self) -> bool
class Extracted(BaseModel, Generic[T]):          # 235: value: Optional[T]; evidence: Optional[Evidence]; confidence: float 0..1; validator caps at 0.5 without a quote
class FieldProvenance(BaseModel):                # 265: origin: ProvenanceOrigin="llm"; verification: VerificationState="extracted"; node_id/page/quote/confidence; verified_by/verified_at; derived_from: list[str]; candidate
class ContractVersion(BaseModel):                # 417: n, revision, valid_from, valid_to, kind: VersionKind, amended_by, source_sha256, card_snapshot, recorded_at, evidence_ref; def in_force(self, as_of: date) -> bool
class Citation(BaseModel):                       # 701: contract_id (required), node_id, quote (1..300), page, verification, version_n, source_sha256; def key(self) -> tuple[str, str]
class ContractAnswer(BaseModel):                 # 750: answer_kind: AnswerKind; @model_validator _check_kind_invariants; provenance = derive_provenance(citations) (800-818)

# knowledge/contracts/carding.py
def deontic_density(text: str) -> int                                                   # 216
def select_header_nodes(toc: Sequence[TocEntry], bodies: Mapping[str, str]) -> list[str]  # 235
def select_obligation_nodes(toc, bodies, *, limit=12, exclude=()) -> list[str]          # 291
def _quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool   # 456
def _validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]  # 471
async def draft_contract(adapter, *, filename, toc, toc_digest, loader, max_obligation_sections=12) -> CardingDraft  # 678 — adapter.ask_structured(prompt, Model, temperature=0.0, system_prompt=SYSTEM_PROMPT)
def similarity(left: str, right: str) -> float                                          # 868 — rapidfuzz.fuzz.token_sort_ratio / 100; RuntimeError with pip hint

# knowledge/contracts/graph_loader.py
class EdgeSpec(BaseModel):            # 106: collection, source_collection, source_key, target_collection, target_key, properties; document() -> {_from,_to,source_id,target_id,kind,**properties}
class ContractGraphLoader:            # 197: __init__(*, catalog, graph_store, tenant_manager=None, datasource=None, ontology_dir=None, domain="contracts")
    def context(self) -> TenantContext                       # 227-249: resolve(tenant_id, domain); ContractsDomainNotLoaded on missing entities
    @staticmethod def desired_edges(snapshot) -> list[EdgeSpec]   # 254-408
    async def publish_all(self) -> GraphPublicationReport      # 471-488 soft-deletes owned vertices absent from snapshot
    async def _reconcile_edges(...)                            # 502-548 removes every owned edge not wanted / with stale props, then create_edges
    async def publish(self, card) -> GraphPublicationReport    # 594-609 delegates to publish_all
    async def retract(self, contract_id) -> GraphPublicationReport  # 611-675

# knowledge/contracts/library.py
class TreeIndexer(Protocol): create_tree / insert_markdown / get_tree / delete_tree     # 96-115
class ContractLibrary:  # 481: __init__(*, catalog, storage_root, evidence_root, adapter=None, indexer_factory=None, content_store_factory=None, owner_rules=(), max_obligation_sections=12, max_candidates=8, relation_stage=None, relate_on_ingest=False, now=_utcnow, today=_today)
    async def add_contract(self, source, *, source_uri=None, force=False) -> IngestResult   # 516
    async def _to_markdown(self, path, source_format) -> tuple[str, dict[int, int]]           # 910 — PDF via _extract_pdf_pages (raw page.get_text, 949-970) + pdf_markdown (205)

# knowledge/contracts/catalog.py
class ContractCatalogStore(ABC):  # 292: __init__(*, tenant_id, schema="contracts", principal=None); upsert(card, *, expected_revision=None, version=None, targets=…) 339; get/find_by_sha/find_by_source_uri/list_cards 367-396; search(query, top_k=8) 398; verification_queue(*, limit=50) 430; outbox 631-681

# knowledge/contracts/datasource.py
class ContractCardDataSource(ExtractDataSource):  # 144: __init__(name="contractcard", config=None) requires config["catalog"]; infer_entity(fields) 162; snapshot() 380; extract(fields=None, filters=None) -> ExtractionResult 405; register() 447

# knowledge/ontology/schema.py
class PropertyDef(BaseModel):   # 18: type: Literal["string","int","float","boolean","date","list","dict"]; required; unique; default; enum; description; extra="forbid"
class RelationDef(BaseModel):   # 114: from_entity (alias "from"); to_entity (alias "to"); edge_collection; properties: list[dict[str, PropertyDef]]; discovery: DiscoveryConfig
class AuthorizationRule(BaseModel):  # 176: rule: Literal["target_is_self","target_in_management_chain","has_role","same_department","always"]; role
class TraversalPattern(BaseModel):   # 261: description; trigger_intents; query_template; post_action; entity_extraction; authorization: AuthorizationSpec | None; tool_call

# knowledge/ontology/tenant.py
class TenantOntologyManager:  # 48: __init__(ontology_dir=None, base_file=None, domains_dir=None, clients_dir=None, …); resolve(tenant_id, domain=None) 92-131 — cache keyed by tenant_id; domain file only under ontology_dir/domains

# knowledge/ontology/graph_store.py
class OntologyGraphStore:
    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None) -> list[dict]   # 271
    async def upsert_nodes(self, ctx, collection, nodes, key_field) -> UpsertResult                     # 311
    async def create_edges(self, ctx, edge_collection, edges) -> int                                    # 411 — UPSERT {_from,_to} … UPDATE {}
    async def soft_delete_nodes(self, ctx, collection, keys) -> None                                    # 517
    async def query_documents(self, ctx, collection, filters=None, sort_desc=None, limit=None) -> list[dict]  # 697
    async def edges_incident(self, ctx, collection, node_id) -> list[dict]                              # 764 — matches source_id/target_id
    async def remove_edge_by_triple(self, ctx, collection, source_id, target_id, kind) -> bool          # 791

# knowledge/ontology/authorization.py
class AuthorizationChecker: async def check(self, spec, user_context, resolved_entities, tenant_id) -> tuple[bool, str | None]  # 62 — OR semantics, first match grants

# knowledge/pageindex/pdf_to_markdown.py
def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]   # 35; to_markdown(path, page_chunks=True) at 72; caller builder._extract_node_markdown 1622-1639

# tools/toolkit.py
class AbstractToolkit: return_direct / exclude_tools / tool_prefix / prefix_separator="_" / confirming_tools  # 231-272; tools from public async methods 547-590

# tools/working_memory/task_memory/tools.py
class TaskMemoryToolsMixin:
    async def begin_task(self, goal: str, constraints=None, steps: Optional[List[dict]]=None, plan_complete: bool=False) -> dict   # 397 — step dict: label, title, description?, required?, depends_on_labels?
    async def update_step(self, task_id, step_id, expected_revision: int, status: str, evidence_refs=None, note=None, reason=None)   # 529
    async def set_resume_hint(self, task_id, next_action, step_id=None) -> dict   # 664
    async def select_task(self, task_id: str) -> dict                             # 687
    async def recall_task(self, task_id=None, max_tokens=2500, recent_calls_limit=8) -> dict   # 772

# memory/episodic/store.py
class EpisodicMemoryStore: async def record_episode(self, namespace, situation, action_taken, outcome: EpisodeOutcome, outcome_details=None, error_type=None, error_message=None, category: EpisodeCategory = TOOL_EXECUTION, importance=None, related_tools=None, related_entities=None, metadata=None, generate_reflection=True, ttl_days=None) -> EpisodicMemory  # 106-122

# models/responses.py
class AIMessage(BaseModel):     # 75-96: images: Optional[List[Path]] (87); media: Optional[List[Path]] (90); files: Optional[List[Path]]; documents: Optional[List[Any]]; structured_output (148-150)
class AgentResponse(BaseModel): # 1094-1131: images (1109); media (1112); validate_assignment=True (1123-1131); @model_validator sync_documents_and_paths (1156-1170)

# integrations/parser.py
@dataclass class ParsedResponse: text; images: List[Path]; documents: List[Path]; media: List[Path]; charts: List[ChartData]   # 83-95
def parse_response(response) -> ParsedResponse   # 519-565 — keeps images/media/files only when path.exists(); data: strings via documents (556-557)

# parrot_tools/contracts/retrieval.py
class RequestContext(BaseModel); class Clarification; class PatternPlan; class RetrievalResult   # 142-214
def classify(question: str) -> str | None                                                        # 222-243 — ordered substring triggers, fails closed
class ContractRetrieval:  # 261: __init__(*, catalog, graph_store, tenant_context, ontology, authorization, today, ranker)
    def authorize(self, context, *, pattern=None, owner_only=False) -> None   # 282-319 — rejects tenant only when supplied AND mismatched
    async def plan(self, question, context) -> PatternPlan | Clarification   # 431-494
    async def execute(self, plan, context) -> RetrievalResult                # 535-629
    def aql_for(self, pattern) -> str; async def execute_graph(...)          # 681-725

# parrot_tools/contracts/service.py / verifier.py / agent.py / toolkit.py
class AnswerProducer(Protocol)  # service.py:68;  class AnswerOutcome(BaseModel) # 95;  class ContractsAnswerService # 105 — answer() 146-212; stream_answer() 214-232 buffers
class CitationVerifier:  async def verify(...)  # verifier.py:102, 156-206 — drops claims without a surviving citation; no completeness check
class UngatedAnswerRefused(PermissionError)  # agent.py:214
class ContractsAgent(Agent):  # agent.py:232 — toolkit created before super().__init__; ask/ask_stream/invoke RAISE UngatedAnswerRefused (338-353)
class ContractsToolkit(AbstractToolkit):  # toolkit.py:39 — tool_prefix="contracts"; confirming_tools={"verify_card","retire_answer"}; _gate() 84

# parrot_loaders
class BaseVideoLoader: def transcript_to_blocks(self, transcript) -> list   # basevideo.py:860-887 — dict input; output keys id, start_time, end_time, start_seconds, end_seconds, text
class YoutubeLoader(VideoLoader): async def load_video(...)                 # youtube.py:30, 298-395 — whisper, word_timestamps=False, deeplink ?t=Ns
class PDFLoader: def is_image_only(self, page) -> bool                     # pdf.py:54-61; skip at 328-335
class PDFMarkdownLoader: extract_images stored at pdfmark.py:67, never read
class ImageUnderstandingLoader._analyze_image_with_ai → GoogleGenAIClient.image_understanding(...)   # imageunderstanding.py:162-187

# vision entry points (per provider — NOT on AbstractClient, clients/base.py:254)
AnthropicClient.ask_to_image(prompt, image: Path|bytes|Image, …, structured_output: Union[type, StructuredOutputConfig] = None, count_objects=False)   # ai-parrot-client-anthropic/.../anthropic/client.py:1329-1342
GoogleGenAIClient.ask_to_image(prompt, image: Path|bytes, …, structured_output: Union[type, StructuredOutputConfig] = None, count_objects=False) # ai-parrot-client-google/.../google/client.py:5160-5172 ; image_understanding analysis.py:438-452 ; video_understanding analysis.py:208-229 (offsets, structured_output)
OpenAIClient.ask_to_image(prompt, image: Path|bytes|Image, …, structured_output: Optional[type] = None)      # ai-parrot-client-openai/.../openai/client.py:1468-1479 (parsed → AIMessage.structured_output)
ClaudeAgentClient.ask_to_image # claude_agent.py:1036-1040 — raises NotImplementedError

# storage / file managers (navigator-api 4.0.0)
OverflowStore.generate_presigned_url(key, *, expires_in=604800)   # storage/overflow.py:119-144 — caps at 7 days; calls get_file_url(key, expiry=…)
FileManagerInterface.get_file_url(self, path: str, expiry: int = 3600) -> str ; upload_file(...)   # .venv navigator/utils/file/abstract.py:67-92 — LocalFileManager returns file:// (local.py:160-172)

# cli/__init__.py
cli._lazy_commands = {...}   # 109 — name → module path; LazyGroup.get_command imports and reads attr cmd_name.replace("-","_") (71-100)
cli._lazy_extras = {...}     # 139 — install hints
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `knowledge/common/provenance.py` | `contracts/models.py` re-exports | import + `# noqa: F401` | `models.py:88, 205, 235, 265` |
| `ManualCard` / `Step` | `Evidence`, `Extracted`, `FieldProvenance` | import from `knowledge.common` | M1 |
| `procedures.ontology.yaml` | `OntologyParser.load` → `OntologyDefinition` (`extra="forbid"`) | file drop + `default_tenant_manager()` | `parser.py:29-62, 93-99`; `tenant.py:107-131` |
| `ManualGraphLoader` | `OntologyGraphStore.upsert_nodes / create_edges / soft_delete_nodes / get_all_edges / remove_edge_by_triple / edges_incident` | method calls (contracts pattern) | `graph_store.py:311, 411, 517, 764, 791`; `contracts/graph_loader.py:471-548, 611-675` |
| `relink_tips` | `OntologyGraphStore.query_documents(filters={"attached_step_id": …})` + `create_edges` on `tech_tip_on` | method calls | `graph_store.py:697-736` |
| `ManualCardDataSource` | `DataSourceFactory.register_api_source("manualcard", …)` | import-time `register()` | `extractors/factory.py:35-80`; `contracts/datasource.py:447-455` |
| `ManualLibrary._to_markdown` | `extract_markdown_per_page(path, images_dir=…)` | call | `pdf_to_markdown.py:35, 72` (M6 kwarg) |
| `figures.extract_page_images` | `pymupdf.Page.get_image_info / get_image_bbox` | call | F026 probe |
| `figures.resolve_captioner` / `resolve_callout_mapper` | `client.ask_to_image(prompt, image, …, structured_output=…)` | `hasattr` capability check | F023 anchors above (structured_output verified 2026-09-25) |
| `export.export_bundle` | `FileManagerInterface.download_file(storage_key, …)` | call | `navigator/utils/file/abstract.py` (F024 re-export) |
| `figures.upload_figures / presign` | `FileManagerInterface.upload_file / get_file_url(path, expiry=…)` | call | `navigator/utils/file/abstract.py:67-92` |
| `video.blocks_from_transcript` | `BaseVideoLoader.transcript_to_blocks` | call (optional import) | `basevideo.py:860-887` |
| `ProcedureRetrieval.execute_graph` | `OntologyGraphStore.execute_traversal(ctx, aql, bind_vars, collection_binds)` | call | `graph_store.py:271-309` |
| `ProcedureRetrieval.fallback_lookup` | `PageIndexToolkit.search / retrieve` | call | `pageindex/toolkit.py` (F013 caller chain) |
| `ProceduresAnswerService.answer` | `ManualCatalogStore.record_answer` (audit before release) | call | mirrors `contracts/service.py:146-212` |
| `ProceduresToolkit` | `AbstractToolkit` tool generation (`proc_<method>`) | inheritance | `tools/toolkit.py:547-590` |
| `ProceduresToolkit.start_guided / mark_done / resume_guided` | `TaskMemoryToolsMixin.begin_task / update_step / select_task / recall_task` | inherited calls | `task_memory/tools.py:397, 529, 687, 772` |
| `guided.record_completion` | `EpisodicMemoryStore.record_episode(category=WORKFLOW_PATTERN)` | call | `episodic/store.py:106-122`; `models.py:36` |
| `ProceduresAgent.ask` | `Agent` (super) + `ProceduresAnswerService.answer` | override + call | `contracts/agent.py:232-268, 338-353` (refusal pattern NOT copied for ask) |
| `AIMessage.image_urls` | `parse_response` → `ParsedResponse.image_urls` | new fields | `responses.py:87-90`; `parser.py:83-95, 519-523` |
| `ParsedResponse.image_urls` | `_parsed_to_card_spec` / `_build_blocks` / `_send_attachments` / `_send_parsed_response` | wrapper edits | `msteams/wrapper.py:1259`; `slack/wrapper.py:591`; `telegram/wrapper.py:2960, 3714`; `whatsapp/wrapper.py:287` |
| `parrot manuals` | `cli._lazy_commands["manuals"]` → `parrot_tools.procedures.cli:manuals` | lazy click group | `cli/__init__.py:71-100, 109, 139` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.common`~~ — does not exist yet (M1 creates it).
- ~~`parrot.knowledge.manuals`, `ManualCard`, `ManualLibrary`, `ManualGraphLoader`, `ManualCatalogStore`, `procedures.ontology.yaml`, `ProceduresToolkit`, `ProcedureRetrieval`, `ProcedureAnswer`, `ProceduresAgent`, `relink_tips`~~ — all new (F030).
- ~~An `origin` property read or written by `ContractGraphLoader`~~ — only a docstring mention (`graph_loader.py:115`); no filter to extend (F003).
- ~~Per-card deletion in `ContractGraphLoader.publish`~~ — it delegates to `publish_all` (F003).
- ~~`structured_output=ContractAnswer` on `ContractsAgent`~~ — answers are released by `ContractsAnswerService` (F017).
- ~~A `parrot contracts` CLI subcommand~~ — contracts CLI is argparse behind `python -m parrot_tools.contracts` (F018).
- ~~`AIMessage.image_urls` / `media_urls`, or any URL-typed media field~~ — `images`/`media`/`files` are `List[Path]` (F019); M12 adds them.
- ~~URL pass-through in `parse_response`~~ — entries are dropped when `path.exists()` is False (F019).
- ~~`data:` image support in Slack; a cap on Slack images~~ — Slack renders http(s) only, uncapped (F020).
- ~~`YoutubeLoader` in `parrot_loaders/video.py`~~ — it is in `youtube.py:30`; `video.py` holds the abstract `VideoLoader` (F025).
- ~~Timecoded scenes from `VideoUnderstandingLoader`~~ — "Scene N" labels only; `offsets`/`structured_output` exist only on `GoogleGenAIClient.video_understanding` (F025).
- ~~`ask_to_image` on `AbstractClient`; URL input to any `ask_to_image`~~ — per-provider, Path/bytes only (F023).
- ~~`get_file_url(path, expiry_seconds)`~~ — the parameter is `expiry` (F024).
- ~~PDF image extraction anywhere (`write_images`, `Pixmap`, `extract_image`, `get_image_bbox` callers)~~ — none; `PDFMarkdownLoader.extract_images` is dead (F015, F031).
- ~~`extract_markdown_per_page` used by `ContractLibrary`~~ — contracts uses raw `page.get_text()` (F013).
- ~~Domain YAML auto-discovery from `defaults/domains/`~~ — only through `ontology_dir=OntologyParser.get_defaults_dir()` (F011).
- ~~A `certified_for` rule kind or generic AND composition in `AuthorizationChecker`~~ — five fixed OR-evaluated kinds (R4).
- ~~`EpisodeCategory.PROCEDURE_COMPLETED`~~ — not added; use `WORKFLOW_PATTERN` + metadata (F022).
- ~~`rapidfuzz` in any core extra other than `graphindex`~~ — `test_dependency_boundary.py` asserts it (holders == `["graphindex"]`).
- ~~Shared test doubles in `tests/knowledge/contracts/conftest.py`~~ — `FakeGraphStore`/`FakeAdapter`/`FakeIndexer` live inside test modules (F007); M-tests copy them into `tests/knowledge/_support/`.
- ~~A `step_key` derived from `slug:order`; content-hash "similarity"~~ — rejected by R1; identity is minted, hash is equality-only.
- ~~A serial-number parser, `Applicability` model, `depicts` edge, `CalloutMap`, or bundle exporter anywhere in the tree~~ — all new (M2, M3, M6, M14).

### Edit Sites (Blueprint Anchors)

Verified against: `55e01d496` (2026-09-25). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/common/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/common/provenance.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/common/validation.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` | MODIFY | `MAX_QUOTE_CHARS = 300` | `models.py:88` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` | MODIFY | `class Evidence(BaseModel):` | `models.py:205` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` | MODIFY | `class Extracted(BaseModel, Generic[T]):` | `models.py:235` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/contracts/models.py` | MODIFY | `class FieldProvenance(BaseModel):` | `models.py:265` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py` | MODIFY | `def _quote_supported(evidence: Optional[Evidence], bodies: Mapping[str, str]) -> bool:` | `carding.py:456` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py` | MODIFY | `def _validate_extracted(field: Extracted[Any], bodies: Mapping[str, str]) -> tuple[Extracted[Any], bool]:` | `carding.py:471` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/manuals/{__init__,models,domain,catalog,catalog_postgres,carding,figures,video,library,datasource,graph_loader,tips,export,spikes}.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py` | MODIFY | `def extract_markdown_per_page(pdf_path: str \| Path) -> list[tuple[int, str]]:` | `pdf_to_markdown.py:35` | 1 |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | `media: Optional[List[Path]] = Field(default_factory=list, description="List of media files generated by the model")` (AIMessage; preceded by the 3-line `images:` field at 87-89) | `responses.py:90` | 1 |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | `document_path: Optional[str] = Field(default=None, description="Path to any document generated during session")` (AgentResponse; followed by `images: Optional[List[Path]] = Field(` at 1109) | `responses.py:1108` | 1 |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | `def sync_documents_and_paths(self):` | `responses.py:1157` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/parser.py` | MODIFY | `media: List[Path] = field(default_factory=list)  # Videos, audio` | `parser.py:92` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/parser.py` | MODIFY | `# Extract images` (inside `def parse_response`, preceding `if hasattr(response, 'images') and response.images:`) | `parser.py:519-520` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/media_download.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `image_entries: list[ImageEntry] = []` | `wrapper.py:1259` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `for img in parsed.images:` (inside `_build_blocks`) | `wrapper.py:591` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `async def _send_attachments(self, chat_id: int, parsed: ParsedResponse) -> None:` | `wrapper.py:2960` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `if image_path.exists():` followed by `await self.bot.send_photo(` / `photo=FSInputFile(image_path),` (second sender) | `wrapper.py:3713-3716` | 2 (ambiguous — attach with the 3-line context quoted) |
| `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/wrapper.py` | MODIFY | `# Send images` followed by `for image_path in parsed.images:` | `wrapper.py:286-287` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/crew/crew_wrapper.py` | MODIFY | `for image_path in parsed.images:` followed by `await self.bot.send_photo(` | `crew_wrapper.py:351-353` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/bridge_wrapper.py` | MODIFY (verify only — routed through `_send_parsed_response`) | `parsed = parse_response(response)` | `bridge_wrapper.py:260` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/assistant.py` | MODIFY (verify only — routed through `_build_blocks`) | `blocks = self.wrapper._build_blocks(parsed)` | `assistant.py:185, 238` | 2 |
| `packages/ai-parrot-tools/src/parrot_tools/procedures/{__init__,retrieval,assembly,verifier,service,toolkit,agent,guided,cli,__main__}.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `cli._lazy_commands = {` | `cli/__init__.py:109` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `cli._lazy_extras = {` | `cli/__init__.py:139` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `bookstore = [` | `pyproject.toml:341` | 1 |
| `docs/knowledge/manuals.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/{common,manuals,_support}/…`, `packages/ai-parrot-tools/tests/procedures/…`, `packages/ai-parrot-integrations/tests/test_media_urls.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Bounded 1+N carding** (`contracts/carding.py:678-786`): deterministic node selection → `ask_structured(temperature=0.0, system_prompt)` → verbatim-quote validation → fallback draft. Untrusted-material framing in prompts (`carding.py:399-448`).
- **Loader reconciliation** (`contracts/graph_loader.py:471-548, 611-675`): `EdgeSpec.document()` with `source_id/target_id/kind` (+ `origin`); remove + recreate on property change; `_verify` read-back before `published=True`. Owned collections are an explicit tuple; technician collections are simply not in it.
- **Dedicated tenant manager + domain check** (`contracts/graph_loader.py:215-249`): `TenantOntologyManager(ontology_dir=OntologyParser.get_defaults_dir())`, `ProceduresDomainNotLoaded`.
- **Deterministic trigger planner failing closed** (`parrot_tools/contracts/retrieval.py:222-243, 431-494`); per-tool `_gate()` (`toolkit.py:84`); `confirming_tools` for writes.
- **Release gate** (`parrot_tools/contracts/service.py:146-232`): audit before release, streaming buffered; **but** procedure verification blocks instead of dropping (R2) and the agent's `ask()` is a gated adapter instead of a refusal (R3).
- **Judgement log + `--force`** (`bookstore/library.py:640-677`, `relations.py:372-413`) for the video tail; origin-tagged links so re-judging replaces only LLM links.
- **Contracts test doubles** (`tests/knowledge/contracts/test_graph_loader.py:41-60`, `test_carding.py:95-110`, `test_ingestion.py:46-60`) copied into `tests/knowledge/_support/` — never imported from `tests.knowledge.contracts.test_*`.
- **`ChartData.public_url`** (`integrations/parser.py:21-38`, `whatsapp/wrapper.py:303`) is the existing URL-media precedent M12 generalises.
- Import ontology symbols from submodules; never `from parrot.knowledge.ontology import …` (FEAT-540 lazy root pending).
- Language split: identifiers, YAML, CLI verbs and docs in English; trigger tables and answers bilingual (es/en) — the agent answers in the technician's language.

### Known Risks / Gotchas
- **Tip loss on re-publish** if a tip edge ever lands in an owned collection — guarded by `TECHNICIAN_COLLECTIONS` being disjoint from `OWNED_*` (test `test_publish_all_never_touches_technician_collections`) and by spike 4.
- **Edge collapse on `(_from,_to)`** (`graph_store.py:411-486`): `desired_edges` merges duplicates into list-valued properties before writing; `_reconcile_edges` handles list props in its stale-property comparison.
- **Silent base-only ontology** when the manager is built on a foreign dir (debug-level log only, `tenant.py:107-131`) — `startup_check` raises `ProceduresDomainNotLoaded`.
- **`create_edges` returns an inflated count** (`NEW ? 1 : 0` on no-op updates, F010 note) — reports must not treat it as "created".
- **Positional step identity** (R1) — `step_id` minted once; `assemble_card` on refresh must carry forward identities for steps matched by `source_identity`/`content_hash` so tips relink without a graph round-trip.
- **Verifier drop semantics** (R2) — do not copy `CitationVerifier.verify` loop; `incomplete` is a first-class answer kind.
- **Channel `ask()` refusal** (R3) — Slack `wrapper.py:539`, WhatsApp `wrapper.py:212`, Telegram `wrapper.py:1505` all call `agent.ask`; the adapter must build `RequestContext` from the platform session only.
- **OR-only authorization** (R4) — if the client later requires certification, it is an explicit policy check in `authorize`, plus expiry/revocation semantics; never a YAML rule.
- **Presigned URL lifetime** — ≤ 7 days at the store (`overflow.py:119-144`), 15 min by default here; chat history keeps stale URLs — the answer renders "figure expired, ask again" on 403 and never re-signs from history. `LocalFileManager` yields `file://` in dev — `presign` rejects it; dev uses `TempFileManager` + the Telegram download path.
- **Downloads** (Telegram/WhatsApp fallback) — host allowlist, redirect validation, 10 MB / 15 s caps, temp cleanup; never follow to non-allowlisted hosts.
- **Guided completion policy** (`task_memory/models.py:683`) may require evidence refs — `mark_done` supplies `evidence_refs=[f"procedure:{procedure_id}@{revision}"]` or the policy is configured `lenient` for the guided task; verified in `test_guided_roundtrip`.
- **`slugify` collapses non-Latin titles to "book"** (`bookstore/carding.py:49-70`) — `ManualLibrary` derives slugs from `equipment` + revision and requires an explicit `--slug` when the result is empty.
- **FTS regconfig** — English-only in contracts; `search_regconfig` is validated as an identifier and defaults to `english`; Spanish corpora set `spanish` per tenant.
- **In-flight overlap** — FEAT-539 still open (TASK-3056); FEAT-540 restructures `knowledge/ontology/__init__.py`; land M1 first and small; rebase M3/M9 if FEAT-540 merges mid-flight.
- **Scanned manuals** — refused with a clear message; do not attempt OCR in v1.
- **Serial formats vary per vendor** (Q7) — `SerialRange.format` is inferred per literal; a serial that does not match any format of the resolved manual ⇒ `unknown`, never a silent "applies". Ask the technician once per session; store only on the trusted context.
- **Callout pass cost and fidelity** (Q8) — one vision call per exploded view at ingest; gated behind `callouts_enabled` until spike 1 passes; unresolved callouts are queue items, never guessed `depicts` edges.
- **Bundle freshness** (Q9) — a bundle is a snapshot of one revision; the manifest carries `version_n`/`source_sha256` so a viewer can detect staleness; tips exported are those active at export time.
- **`transcript_to_blocks` type hint is wrong** (`str` vs dict, F025) — pass the whisper dict.
- **`VideoUnderstandingLoader` model bug** (does not pass `model=`, F025) — not used by M7; do not "fix" it in this feature.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pymupdf` | `==1.27.1` (pinned) | page text, `Page.get_image_info` / `get_image_bbox` |
| `pymupdf4llm` | `==0.0.27` (pinned) | `to_markdown(write_images, image_path, image_format, dpi, image_size_limit, page_chunks)` |
| `rapidfuzz` | `>=3.0` (already in `graphindex`) | part-number / equipment alias / relink candidate similarity on **text** |
| `bm25s` | `>=0.2` (already in `bookstore`) | step ↔ transcript-block alignment |
| `asyncdb[arangodb]` | existing | `OntologyGraphStore` |
| `asyncpg` | existing (`graphindex-postgres`) | `PostgresManualCatalog` |
| `navigator-api` | `4.0.0` (installed) | `FileManagerInterface` / `S3FileManager` |
| `aiohttp` | existing | `media_download.download_to_temp` |
| `yt-dlp`, `whisperx` | existing loaders extras | video transcripts (optional) |

No new third-party package. New extra: `manuals = ["ai-parrot[graphindex,bookstore]"]`.

---

## 8. Open Questions

### Resolved (carried from the proposal §5 — adopted review recommendations, 2026-09-24)

- [x] **U1 — Media delivery route** — *Resolved in proposal*: option (a) refined — `image_urls`/`media_urls` on both `AIMessage` and `AgentResponse`, carried separately through `ParsedResponse`; Teams/Slack render URLs, Telegram bounded temp download, WhatsApp direct URL first; signed after release from media ids, never stored. → §3 M12, §5 AC14.
- [x] **U2 — Shared evidence primitives** — *Resolved in proposal*: option (b) narrowed — `knowledge/common/provenance.py` + shared validation helpers with re-exports; no `doc_id` rename, no archive/version/answer move. → §3 M1, §5 AC2.
- [x] **U3 — Tip protection** — *Resolved in proposal*: option (c) — exclusive technician collections + origin/author stamps; immutable step identity; relink by source identity → exact content equality → curator candidates; explicit idempotent relink op; orphans kept. → §3 M2/M9, §5 AC4–AC6.
- [x] **U4 — Answer release path** — *Resolved in proposal*: option (a) — retrieval → deterministic assembly → blocking completeness verification → audit → release via `ProceduresAnswerService`; `ProceduresAgent.ask()` transport adapter. → §3 M10/M11, §5 AC7–AC8.
- [x] **U5 — Authorization granularity** — *Resolved in proposal*: option (a) conditional — tenant-wide technician reads in v1 provided the client confirms certification is not required; trusted matching tenant; policy on every read path; technician vs curator actions; no unenforced `certified_for`. → §3 M3/M10, §5 AC9–AC10.

### Resolved 2026-09-25 (owner Q&A in the `/sdd-spec` follow-up)

- [x] **Q1 — Equipment certification as an access requirement** — *Resolved*: **No** — tenant-wide technician reads; curators verify/publish. → §1 Non-Goals, §3 M3/M10, AC9–AC10.
- [x] **Q2 — Card granularity** — *Resolved*: one `ManualCard` per document with `procedures[]` embedded; `manual_id == tree_name`. → §2 Data Models, §3 M2/M4.
- [x] **Q3 — Vision client for captioning** — *Resolved*: capability-resolved at runtime (`resolve_captioner` / `resolve_callout_mapper` over any client with `ask_to_image`). → §3 M6, AC13.
- [x] **Q4 — Figure storage** — *Resolved*: tenant S3 bucket via `S3FileManager` (injected `FileManagerInterface`), 15-min presign per answer; dev uses `TempFileManager` + the download path. → §3 M6/M12, §7 Risks.
- [x] **Q5 — Guided-mode state owner** — *Resolved*: `TaskMemoryToolsMixin` composed into `ProceduresToolkit`. → §3 M11, AC15.
- [x] **Q6 — Tips moderation** — *Resolved*: visible immediately, attributed, retirable by curators; `Tip.history` is the audit trail. → §2 Overview (Tips), §3 M9/M11.
- [x] **Q7 — Serial / model-year applicability** — *Resolved*: **include in v1** — `Applicability(models[], serial_ranges[])` with evidence on `Step`, `RequestContext.equipment_serial`, `applies()` filter in assembly, `proc_set_equipment_serial`. → G10, §3 M2/M5/M10/M11, AC20.
- [x] **Q8 — Exploded-view callouts → Part** — *Resolved*: **include in v1** — `ask_to_image(structured_output=CalloutMap)` per exploded view, `depicts(Media → Part, callouts[])` edges, `proc_find_part`; enabled once spike 1 passes. → G11, §3 M2/M3/M6/M11, AC21.
- [x] **Q9 — Offline field use** — *Resolved*: **include a graph export in v1** — `parrot manuals export` bundle (M14); the per-device viewer stays out of scope. → G12, §3 M13/M14, AC22.
- [x] **Q10 — Guided completion policy** — *Resolved*: synthetic evidence ref per step (`procedure:{procedure_id}@{revision}`) satisfies the default `CompletionPolicy`; no task-memory change. → §3 M11, AC15.

### Unresolved

_None._

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec). Model: `gpt-5.6-luna` · **Status: skipped (exploration doc not `accepted`: brainstorm `Status: exploration`, proposal `status: review`)** · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

An equivalent independent codex review of the proposal (`sdd/state/FEAT-601/review.md`, against `ab9f97a82`) was triaged in proposal §9 on 2026-09-24: R1–R4 all CONFIRM (folded into §1 Goals, §2 Overview, §3 M2/M9/M10/M11, §5 AC4–AC10, §7 Risks) and its U1–U5 recommendations were adopted (§8 resolved).

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-601 (`feat-FEAT-601-training-agent`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import or contract dependency, with evidence):
  - M2 → M1 (`manuals/models.py` imports `knowledge.common.provenance`)
  - M3 → M2 (YAML property names must equal model field names; `domain.py` imports `PROCEDURES_DOMAIN` consumers)
  - M4 → M2 (`ManualCatalogStore` signatures take `ManualCard`/`ManualVersion`)
  - M5 → M1, M2 (`quote_supported`, `Extracted`; `assemble_card` returns `ManualCard`)
  - M6 → M2 (`MediaRef`, `MediaLink`, `StepDraft` from M5 is a type-only import — keep it in `TYPE_CHECKING`)
  - M7 → M2 (`Step`, `MediaRef`)
  - M8 → M2, M4, M5, M6, M7 (`ManualLibrary` orchestrates all)
  - M9 → M2, M3, M4 (`OWNED_*`, `resolve_context`, catalog snapshot)
  - M10 → M2, M3, M4, M9 (`ProcedureAnswer`, patterns, catalog, graph content)
  - M11 → M10 (+ M12 field names on `AIMessage`)
  - M13 → M8, M10, M11, M14
  - M14 → M2, M4, M6 (`export_bundle` reads `ManualCard`, catalog, storage keys)
  - M0 → M5, M6, M7, M9, M12
  - **No edge**: M12 is independent of everything (runs concurrently from day one); M4, M6, M7 are mutually independent after M2; M3 and M4 are independent.
- **Shared files**: none between modules. `contracts/models.py` and `contracts/carding.py` are touched by M1 only; `responses.py`/`parser.py`/wrappers by M12 only; `cli/__init__.py`/`pyproject.toml` by M13 only.
- **Exclusive resources**: `packages/ai-parrot/pyproject.toml` (+ `uv.lock` regeneration if the extra requires it) — M13's packaging task is `parallel: false`. Live Arango/Postgres tests share the `arango_params`/`pg_pool` fixtures — mark their tasks `parallel: false`.
- **Cross-feature dependencies**: none blocking. FEAT-539 (open, contracts) — M1 touches `contracts/models.py`/`carding.py` behaviour-preservingly; land M1 first. FEAT-540 (pending) — if it merges mid-flight, rebase M3/M9 imports (already submodule-only, AC17).
- **Suggested lanes**: Lane A = M1 → M2 → {M3, M4} ; Lane B = M12 (immediately) ; then {M5, M6, M7} ‖ M9 ‖ M14 ; then M8, M10 ; then M11, M13 ; M0 last (needs the owner's corpus).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-25 | Jesus Lara (with Claude) | Initial draft from brainstorm (Option B) + proposal FEAT-601 (U1–U5 resolved, R1–R4 confirmed) |
| 0.2 | 2026-09-25 | Jesus Lara (with Claude) | Status approved by owner; Q1–Q10 resolved; Q7/Q8/Q9 widen v1 (Applicability, callouts, export bundle M14) |
