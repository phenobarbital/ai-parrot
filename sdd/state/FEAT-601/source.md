---
kind: file
jira_key: null
file_path: sdd/proposals/training-agent.brainstorm.md
fetched_at: 2026-09-24T21:15:07+00:00
summary_oneline: Procedure Graph — field-training agent over assembly manuals (ManualCard → procedures ontology → ProceduresToolkit), figures + video as graph nodes
---

---
# SDD flow type and base branch (FEAT-TBD).
type: feature
base_branch: dev
---

# Brainstorm: Procedure Graph — field-training agent for equipment assembly manuals

**Date**: 2026-09-24
**Author**: Jesus Lara (drafted with Claude)
**Status**: exploration
**Recommended Option**: B
**Related**: `claude/contracts-card-ontology-design.md` (FEAT-539 — card → deterministic graph loader → domain toolkit, the template this copies), `claude/contracts-agent-definition.md`, `claude/schema-plane.brainstorm.md` (authored-content-survives-reingest policy), `knowledge/ontology/defaults/domains/{contracts,legal,field_services}.ontology.yaml`

---

## Problem Statement

Field technicians need to ask "how do I assemble equipment X?" and get back the **ordered** steps, what to have ready before starting, the safety warnings, the figure that goes with each step, the segment of the training video that shows it, and the tips other technicians left. The source of truth is a set of vendor/vendor-derived assembly and maintenance manuals (PDF, some DOCX), which are revised over time.

Plain RAG over chunked manuals is the wrong shape for this content, for four concrete reasons:

1. **Procedures are ordered; chunks are not.** A top-k retrieval over a 60-page manual returns steps 2, 5 and 9 with no guarantee that 3, 4 and 6–8 are present, and no way to know they are missing. The model then fills the gaps. For an assembly procedure a silently missing step is the worst possible failure.
2. **Figures are referenced, not embedded.** Manuals say "see Fig. 3-4" and "tighten the four M6 bolts shown in the exploded view". Today nothing in the ingestion path keeps figures at all: `pageindex/pdf_to_markdown.py::extract_markdown_per_page` calls `pymupdf4llm.to_markdown(path, page_chunks=True)` with no image output, `PDFLoader.is_image_only` uses `page.get_images(full=True)` only to *skip* image-only pages, and `PDFMarkdownLoader.extract_images` is a stored flag that is never read. The best photo in the manual is unreachable to the agent.
3. **Prerequisites and hazards are cross-cutting.** "What do I need before I start?" is the union of parts, tools and warnings across all steps of a procedure; "what other equipment uses this same sub-assembly?" is a graph question. Neither is answerable from chunk similarity.
4. **Field knowledge has nowhere to live.** The valuable content after month two is what technicians learned ("the clip on rev B is reversed", "use the short bit or you'll strip it"). In a chunk store that knowledge either pollutes the manual's text or is lost on the next re-ingest.

Who is affected: field technicians (consumers, through WhatsApp / Teams / Telegram / web), the training/ops owner who curates manuals and tips, and — internally — the same `knowledge/` stack that already carries `bookstore` and `contracts`. Why now: `knowledge/contracts/` shipped exactly the pattern this needs (a per-document card with per-field provenance, a deterministic `ContractGraphLoader` into the ArangoDB ontology store, a `ContractsToolkit` with one action per tool, an answer model whose citations are never model-authored). The manual case is that pattern plus two things the contracts case did not need: **figures** and **video segments** as first-class graph nodes.

## Constraints & Requirements

- **LLM proposes, deterministic decides.** Step order, prerequisites, hazards and which figure goes with which step come out of the graph by traversal. The LLM extracts at ingest (with evidence) and writes prose at answer time; it never selects or orders steps, and never chooses media. Same invariant as `ContractAnswer.provenance` ("always derived from the surviving citations, never taken from model output").
- **Every extracted fact carries evidence.** Reuse `Evidence(node_id, quote, page)` / `Extracted[T]` / `FieldProvenance` from `knowledge/contracts/models.py` as-is. A step with no supporting quote in the source node is rejected at carding, not stored with low confidence — a wrong step is worse than a missing one.
- **Tips survive re-ingest.** Manual revision 2 replaces every node the loader wrote from revision 1 (`origin="manual"`, keyed by `source_sha256`); nodes with `origin="technician"` / `"memory"` are re-linked by stable `step_key`, never deleted. This is the `replace_source_slice` policy from `knowledge/wiki/store.py`, applied to the ontology graph.
- **Media are references, never copies in the graph.** Figures extracted at ingest go to object storage through the existing `FileManagerInterface` (`upload_file`, `get_file_url(path, expiry_seconds)`); the graph node holds the storage key and a caption. Videos are external URIs plus `t_start`/`t_end`; the platform never re-hosts vendor video.
- **Channel-agnostic answer.** The agent returns a structured `ProcedureAnswer`; each channel renders it with what it supports (Telegram/WhatsApp send files, Teams/Slack render http(s) or `data:` URLs — see the `Path`-typed pitfall in §Code Context).
- **Authorization through the ontology, default deny.** `AuthorizationSpec` on every traversal pattern, as in `contracts.ontology.yaml`. Training content is usually open to every technician of the tenant, so the default rule is `has_role: technician`; per-equipment restriction is an open question.
- **Versions are bitemporal, embedded.** `Procedure.versions[]` follows `ContractVersion` / `legal.Articulo.versions` (`valid_from` inclusive, `valid_to` exclusive, `null` = current). A manual revision is a new version of each procedure it touches, not a new procedure.
- **No new heavy dependency.** `pymupdf` / `pymupdf4llm` (pinned), ArangoDB via `asyncdb`, `rapidfuzz`, `bm25s` and the Google/Anthropic/OpenAI vision entry points are all already in the tree.
- **Language split:** identifiers, page ids, CLI verbs and docs in English; the agent answers in the technician's language.
- **Validation-first:** spikes (§Spike Gate) before `/sdd-spec`. Figure-to-step pairing is the unproven piece.

---

## Options Explored

### Option A: Manuals as books — `Bookstore.add_book` + `pageindex_search`, no graph

Ingest each manual with `Bookstore.add_book` (sha256 → `create_tree` → `import_pdf` → `derive_toc` → `BookCard` → `catalog.upsert`) and give the agent `BookstoreToolkit` + `PageIndexToolkit.search`/`retrieve`. The PageIndex tree already keeps `start_index`/`end_index` per node, so answers can cite pages.

✅ **Pros:**
- Zero new code; works this afternoon for text-only questions ("what torque for the M8 bolts?").
- PageIndex's hierarchical tree is already far better than flat chunks at keeping a section whole.

❌ **Cons:**
- A "section" is not a "procedure": the tree splits on headings, and a procedure's steps routinely span sub-sections, tables and a figure page. Ordering and completeness are still the model's guess.
- No figures (see Problem 2), no video, no prerequisites/hazards aggregation, no cross-equipment edges.
- Tips would be `pageindex.add_node` entries inside the manual's tree — overwritten on re-import, and invisible to another equipment's manual.
- No progress tracking; "guided mode" is impossible.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pymupdf4llm` | PDF → markdown | already used by PageIndex |

🔗 **Existing Code to Reuse:**
- `knowledge/bookstore/library.py::Bookstore.add_book`, `knowledge/pageindex/toolkit.py::PageIndexToolkit`.

*(Kept as the **fallback path** of Option B: when the graph cannot resolve a question to a `Procedure`, the agent falls back to PageIndex search over the manual tree and says so.)*

---

### Option B: **Procedure graph** — `ManualCard` → `procedures.ontology.yaml` → `ManualGraphLoader` → `ProceduresToolkit` — *recommended*

Copy the contracts architecture one level up: the **document** gets a card (`ManualCard`, sibling of `BookCard` / `ContractCard`), the **procedures inside it** become graph entities, and the agent reads the graph through a domain toolkit whose tools are pure traversals.

**Domain vocabulary** (`knowledge/ontology/defaults/domains/procedures.ontology.yaml`, `extends: base`; shape identical to `contracts.ontology.yaml`: `entities` with `collection`/`key_field`/`properties`/`vectorize`, `relations` with `edge_collection` and optional `discovery: field_match`, `traversal_patterns` with AQL `query_template`, `entity_extraction`, `authorization`):

```yaml
entities:
  Equipment:   {collection: equipment,  key_field: equipment_id}   # model, family, revision, aliases[]
  Manual:      {collection: manual,     key_field: manual_id}      # == PageIndex tree_name; source_sha256, revision, versions[]
  Procedure:   {collection: procedure,  key_field: procedure_id}   # kind: assembly|disassembly|maintenance|inspection|troubleshooting
                                                                   # title, estimated_minutes, skill_level, active, versions[], verification
  Step:        {collection: step,       key_field: step_id}        # order, step_key (stable across revisions), text, torque, duration, node_id, page
  Part:        {collection: part,       key_field: part_id}        # part_number, name, quantity (edge property)
  Tool:        {collection: tool,       key_field: tool_id}        # name, spec (e.g. "torque wrench 10–50 Nm")
  Hazard:      {collection: hazard,     key_field: hazard_id}      # severity: caution|warning|danger, text, applies_to
  Media:       {collection: media,      key_field: media_id}       # kind: figure|photo|video_segment; storage_key|uri; page; caption; t_start; t_end; origin
  Tip:         {collection: tip,        key_field: tip_id}         # text, origin: manual|technician|memory, author, created_at, active
relations:
  documents:        {from: Manual,     to: Procedure}
  assembles:        {from: Procedure,  to: Equipment}
  has_step:         {from: Procedure,  to: Step,      properties: [order]}
  precedes:         {from: Step,       to: Step}                   # written from order; explicit "before step N" cross-refs become extra edges
  requires_part:    {from: Step,       to: Part,      properties: [quantity]}
  requires_tool:    {from: Step,       to: Tool}
  warns:            {from: Step,       to: Hazard}
  illustrated_by:   {from: Step,       to: Media,     properties: [role: primary|secondary, confidence, origin]}
  has_tip:          {from: Step,       to: Tip}
  shares_module:    {from: Equipment,  to: Equipment, properties: [module]}   # deterministic: same Part set ⊂ both, or declared
  supersedes:       {from: Procedure,  to: Procedure}              # revision lineage
  authored_by:      {from: Tip,        to: Employee}               # base-layer link, discovery: field_match on employee_id
```

**Traversal patterns** (all metadata/graph walks, no LLM in the query): `procedure_steps` (ordered `has_step`, each step hydrated with `illustrated_by`, `warns`, `has_tip`), `procedure_prerequisites` (union of `requires_part` / `requires_tool` / `warns` across steps, de-duplicated by `_key` — the FEAT-539 lesson), `procedures_for_equipment` (by model/alias, `active` only), `step_detail` (one step + its media/tips/hazards + `precedes` neighbours), `equipment_sharing_module`, `procedure_in_force(as_of)` (walks `versions[]` like `article_in_force`), `tips_for_procedure`.

**Card and carding** (`knowledge/manuals/`): `ManualCard` carries the document-level fields (`manual_id == tree_name`, `equipment_ids[]`, `revision`, `source_uri`, `source_sha256`, `source_format`, `toc`, `toc_digest`, `field_provenance`, `verification`, `versions[]`, `card_origin`) and `procedures: list[ProcedureDraft→Procedure]`, each with `steps: list[Step]`. Carding is a **three-pass** structured-output extraction, mirroring `contracts/carding.py::draft_contract` (header pass + per-section obligations pass), with deterministic node selection:

1. *Header pass* — cover/front matter + "specifications" / "parts list" / "tools required" sections (title-keyword selection as `select_header_nodes`) → `ManualHeaderDraft`: equipment models, revision, global parts/tools tables, global hazards.
2. *Procedure pass* — per candidate section (titles matching `assembly|installation|disassembly|removal|replacement|maintenance|inspection|procedure|step`, or bodies with numbered-list density ≥ threshold, the analogue of `deontic_density`) → `ProcedureDraft` with `steps[]`, each step an `Extracted[str]` with `Evidence(node_id, quote, page)`, plus the raw part numbers, tool mentions, hazard boxes and **figure references as written** (`"Fig. 3-4"`, `"see illustration"`) that the step text cites.
3. *Assembly (deterministic, `assemble_card`)* — resolve part numbers against the header parts table (`rapidfuzz` ≥ 0.85, else keep the literal and flag), map figure references to extracted figures (below), build `step_key = f"{procedure_slug}:{order}"` plus a content hash so a re-carding can re-link tips even if a step moves, derive `precedes` from order and from explicit "before/after step N" phrases (regex, evidence-backed), compute `estimated_minutes` as the sum of step durations when present.

**Figure extraction** (`knowledge/manuals/figures.py`, the new piece): at `_to_markdown` time, run `pymupdf4llm.to_markdown(path, page_chunks=True, write_images=True, image_path=<tmp>, image_format="png", dpi=150, image_size_limit=0.05)` (all keywords verified on the pinned `pymupdf4llm==0.0.27`; `page_chunks=True` returns a list of per-page dicts rather than a string), so the per-page markdown carries `![](…)` references in reading order, and separately `page.get_images(full=True)` + `page.get_image_bbox` to keep each image's bbox. Pair figure → caption → step deterministically: caption text is the text block immediately below the bbox matching `(Fig\.?|Figure|Figura)\s*[\dA-Z\-\.]+` (mirrors what `ocr/layoutlm.py` calls the `figure`/`caption` labels); a step cites a figure by that label (pass 2 captured it verbatim); uncaptioned figures attach to the step whose evidence quote is on the same page and closest by vertical distance, with `confidence` scaled by distance and `role="secondary"`. Every figure is captioned once at ingest with the provider's `ask_to_image` (Anthropic/Google/OpenAI clients all implement it) so `media.caption` is FTS-searchable ("the photo with the red connector"); the caption is descriptive metadata, never a step. Upload via `FileManagerInterface.upload_file`; the node stores `storage_key`, `page`, `bbox`, `sha256`, `caption`, `origin="manual"`. Presign at answer time with `get_file_url(path, expiry_seconds)`, never at ingest.

**Video alignment** (`knowledge/manuals/video.py`): a training video is ingested with the existing `YoutubeLoader` / `VideoLocalLoader` (`BaseVideoLoader.transcript_to_blocks` gives `start`/`end` per block) and optionally `VideoUnderstandingLoader` (Gemini `video_understanding`, timecoded scene captions). Alignment step ↔ transcript block is **deterministic first** — `bm25s` over step text vs. block text, plus ordinal hints ("step three", "next") — producing `Media(kind="video_segment", uri, t_start, t_end)` with `illustrated_by(confidence)`; blocks under the threshold go to an **LLM-judged pass with a judgement log and `--force`**, exactly `bookstore/relations.py::judge_relations`. A step with no segment gets none; the answer never links a whole video as if it were a segment.

**Graph loader** (`knowledge/manuals/graph_loader.py::ManualGraphLoader`): copy of `ContractGraphLoader` — `desired_edges(snapshot) -> list[EdgeSpec]`, `publish(card)`, `publish_all()`, `retract(manual_id)`, `_reconcile_edges`, `startup_check` — with one addition: `publish` deletes/soft-deletes only nodes and edges whose `origin == "manual"` **and** `manual_id` matches, then re-links surviving `Tip` nodes by `step_key` (falling back to step content-hash similarity ≥ 0.9; unresolvable tips are kept, marked `orphaned=true`, and surfaced in the curator queue — never dropped).

**Retrieval + answer** (`ai-parrot-tools/parrot_tools/procedures/`): `ProcedureRetrieval` mirrors `contracts/retrieval.py::ContractRetrieval` (`authorize`, `resolve_equipment` — catalog FTS over model/aliases with `rapidfuzz`, `Clarification` when ambiguous —, `plan(question) -> PatternPlan | Clarification`, `execute`, `execute_graph`). Entry resolution is **hybrid**: catalog FTS on procedure/equipment names first, then PageIndex `search` over the manual tree as the fallback of Option A. `ProcedureAnswer(answer_kind: Literal["procedure","step","prerequisites","lookup","clarification","not_found","out_of_scope","denied"], answer, steps[], media[], hazards[], tips[], citations[], provenance, pattern)` with the same model-validator discipline as `ContractAnswer`: `steps`, `media`, `hazards` and `citations` are copied from `RetrievalResult`, `answer` is the only model-authored field.

**Toolkit** (`ProceduresToolkit(AbstractToolkit)`, `tool_prefix="proc"`, one action per tool): `find_procedure(query, equipment=None)`, `get_steps(procedure_id)`, `get_step(procedure_id, order)`, `prerequisites(procedure_id)`, `media_for_step(step_id)`, `tips_for_step(step_id)`, `add_tip(step_id, text)` (in `confirming_tools`, writes `origin="technician"`, `authored_by` the caller), `related_equipment(equipment_id)`, `verification_queue(limit)` (curator), `verify_procedure(procedure_id)` (curator, flips `verification` and freezes the version). **Guided mode** is not new machinery: `start_guided(procedure_id)` calls `TaskMemoryToolsMixin.begin_task(goal=<procedure title>, steps=[{label: step_key, title, description, required: true, depends_on_labels: [previous]}], plan_complete=True)`; `next_step(task_id)` / `mark_done(task_id, step_id)` wrap `update_step(...)` / `set_resume_hint(...)`; `recall_task` recovers "where was I" after the technician comes back the next day. Completed guided runs are recorded as episodes (`EpisodicMemoryStore.record_episode`) so "which procedures has this technician completed" is a query, not a feeling.

✅ **Pros:**
- Every question the owner listed maps to a traversal pattern; ordering, completeness and media choice are deterministic and citable to page + figure.
- Tips are a node kind with their own `origin`; the re-ingest policy protects them by construction.
- The card/loader/toolkit/answer structure is a proven copy of `knowledge/contracts` + `parrot_tools/contracts` — the spec can cite grep anchors for almost every module.
- Guided mode and progress fall out of `TaskMemoryToolsMixin` + episodic memory; no new state store.
- Video and figures are the same `Media` node kind; the channel renderer does not care which.

❌ **Cons:**
- Figure → step pairing is heuristic on real manuals (exploded views with numbered callouts, figures on the page after the step). This is the spike.
- Two new packages' worth of modules (`knowledge/manuals/`, `parrot_tools/procedures/`) plus an ontology domain; medium effort even with the template.
- Scanned manuals need an OCR path before carding (`PDFLoader` skips image-only pages); out of v1 unless the spike corpus has them.
- Answer media reach the channels through `AIMessage.images: List[Path]`, which mangles `https://` (see §Code Context) — a small but real change in `models/responses.py` or the integrations parser.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pymupdf==1.27.1`, `pymupdf4llm==0.0.27` | page markdown + figure extraction + bboxes | pinned in `packages/ai-parrot/pyproject.toml` |
| `rapidfuzz` | part-number / equipment alias resolution | already used by `contracts/carding.py::similarity` |
| `bm25s` | step ↔ transcript-block alignment | already a bookstore dependency ("no-LLM lexical in-book search") |
| `asyncdb` (ArangoDB) | `OntologyGraphStore` | existing |
| `navigator.utils.file` (`S3FileManager`) | figure storage + presigned URLs | re-exported in `interfaces/file/*` |
| `yt_dlp`, whisper/whisperx | video transcript with timestamps | `parrot_loaders/basevideo.py` |

🔗 **Existing Code to Reuse:**
- `knowledge/contracts/models.py::Evidence, Extracted, FieldProvenance, ContractVersion, ContractAnswer` — evidence, provenance, versions and the answer-invariant pattern (reuse the first three as-is; copy the last two).
- `knowledge/contracts/carding.py::select_header_nodes, select_obligation_nodes, deontic_density, draft_contract, validate_header_evidence, fallback_header_draft, similarity` — node selection, evidence validation, fallback.
- `knowledge/contracts/graph_loader.py::ContractGraphLoader, EdgeSpec, GraphPublicationReport` — the loader template.
- `knowledge/contracts/library.py::ContractLibrary.add_contract / add_folder / verify_card / refresh_card / _to_markdown / _extract_pdf_pages` — ingestion skeleton incl. `page_hints`.
- `knowledge/contracts/catalog_postgres.py::PostgresContractCatalog` (`ContractCatalogStore` ABC) — catalog template.
- `knowledge/bookstore/carding.py::slugify, unique_slug, derive_toc, sample_sections`; `bookstore/relations.py::judge_relations` (judgement log, `--force`).
- `knowledge/pageindex/toolkit.py::PageIndexToolkit.create_tree / import_pdf / insert_markdown / get_tree / search / retrieve`; `pageindex/schemas.py::PageIndexNode` (`start_index`, `end_index`).
- `knowledge/pageindex/pdf_to_markdown.py::extract_markdown_per_page` — extend with image output.
- `knowledge/ontology/{schema,parser,tenant,graph_store,authorization,refresh,discovery}.py` — `OntologyDefinition`, `TenantOntologyManager.resolve`, `OntologyGraphStore.execute_traversal / upsert_nodes / create_edges / soft_delete_nodes`, `AuthorizationChecker.check`.
- `ai-parrot-tools/parrot_tools/contracts/{retrieval,toolkit,agent,service,verifier}.py` — retrieval planner, toolkit shape, agent wiring, verification queue.
- `tools/working_memory/task_memory/tools.py::TaskMemoryToolsMixin.begin_task / update_step / set_resume_hint / recall_task` — guided mode.
- `memory/episodic/store.py::EpisodicMemoryStore.record_episode` — completion history.
- `parrot_loaders/basevideo.py::BaseVideoLoader.transcript_to_blocks`, `video.py::YoutubeLoader`, `videolocal.py::VideoLocalLoader`, `videounderstanding.py::VideoUnderstandingLoader` — video ingest.
- Vision: `ask_to_image(prompt, image, ..., structured_output=None)` on the Anthropic / Google / OpenAI clients; `GoogleGenAIClient.image_understanding`.
- `interfaces/file/*::FileManagerInterface.upload_file / get_file_url`; `storage/overflow.py::OverflowStore.generate_presigned_url` — media storage.
- `models/responses.py::AIMessage / AgentResponse` (`images`, `media`, `documents`) and `ai-parrot-integrations/.../integrations/parser.py::parse_response` — delivery.

---

### Option C: Procedures as a **wiki plane** (`knowledge/wiki/`, `procedure:` / `step:` pages in SQLite)

Model procedures as `WikiPageRecord`s (`category="procedure"|"step"|"media"`) in a dedicated plane, edges through the wiki store, tips as `origin="authored"` pages via `WikiRememberTool`, served by `wiki_*` MCP tools.

✅ **Pros:**
- Re-ingest safety is native (`replace_source_slice` keeps other `source_id`s); FTS and `neighbors()` exist; runs offline on SQLite for the dev loop.
- Tips-as-authored-pages is exactly the pattern the schema plane adopted.

❌ **Cons:**
- No tenant model, no `AuthorizationSpec`, no AQL traversals with typed edge properties (`order`, `quantity`, `t_start`) — the wiki edge is `(src, dst, rel[, provenance])`. Ordered steps and media roles would be encoded in page bodies, which is the chunk problem again in a nicer coat.
- The consumers are field technicians on WhatsApp/Teams under a tenant, not coders in a worktree; the wiki's strengths (offline, worktree-local, MCP for Claude Code) do not apply.
- Diverges from the `knowledge/contracts` lineage the team just built for the same client family.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` | plane store | existing |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/store.py::SQLiteWikiStore.replace_source_slice`, `wiki/tools.py::WikiRememberTool`.

*(Its one idea — authored content survives ingested content — is adopted in Option B as the `origin` rule on `Tip` nodes.)*

---

### Option D: Long-context "manual in the prompt", no index

For each question, pick the manual by name and put its whole markdown (plus figure captions) in the context of a 200k-token model; let the model answer with page citations.

✅ **Pros:**
- Nothing to build beyond `_to_markdown` and a prompt; good answers on small manuals.

❌ **Cons:**
- Per-question cost scales with manual size; a 120-page manual on every WhatsApp message is not viable at fleet scale.
- Ordering/completeness still the model's; figures still unreachable; no tips, no guided mode, no cross-equipment edges, no versions.
- Violates the design invariant (the model both retrieves and decides).

📊 **Effort:** Low

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `ContractLibrary._to_markdown`.

---

## Recommendation

**Option B.** It is the only option that gives ordered, complete, citable steps with their figures and video segments by construction, keeps technician tips safe across manual revisions, and does it by copying `knowledge/contracts` + `parrot_tools/contracts` — an architecture that already shipped for a sibling use case — rather than inventing one. Option A survives as the fallback retrieval path inside B; Option C contributes the `origin`-based protection of authored content; Option D is rejected on cost and on the proposes/decides invariant.

What we trade: figure → step pairing is heuristic and must be measured on real manuals before speccing (spike 1); the video alignment is deterministic-first with an LLM-judged tail (spike 3); and the answer path needs a small fix so channels can render presigned URLs (spike 2). Scanned manuals are explicitly out of v1.

---

## Feature Description

### User-Facing Behavior

- **Ingest a manual** (curator, CLI or admin UI): `parrot manuals add <file.pdf> --equipment "Model X" --revision B` → tree + card + figures + graph; prints procedures found, steps per procedure, figures paired / unpaired, hazards, and the verification queue entry. `parrot manuals add-video <url> --manual <id>` aligns a training video to the manual's steps and reports coverage. `parrot manuals refresh <manual_id> <file>` re-cards a revision and reports which steps changed, which tips were re-linked, which are orphaned.
- **Ask** (technician, any channel): "¿cómo ensamblo el Model X?" → `ProcedureAnswer(kind="procedure")`: short intro, the ordered steps (each with its primary figure, hazards inline, tips marked as *from technicians*), prerequisites block first (parts with quantities, tools, danger-level hazards), video segments as deep links with timestamps, and page citations. "¿qué necesito antes de empezar?" → `kind="prerequisites"`. "Paso 4" / "the next one" → `kind="step"`. "Model X" ambiguous between X-100 and X-200 → `kind="clarification"` with the candidates, never a guess.
- **Guided mode**: "guíame" → the agent opens a task with the procedure's steps, sends step 1 with its figure, waits for "listo"/"done", records completion, and can resume tomorrow ("¿dónde me quedé?").
- **Leave a tip**: "anota que el clip de la rev B va al revés" → `proc_add_tip` (confirming tool), stored as `origin="technician"`, attributed, visible to everyone on that step from the next answer on; curator can retire it.
- **Curate** (training owner): verification queue per manual (unpaired figures, low-confidence steps, orphaned tips); `verify_procedure` freezes the version; answers on unverified procedures say so in one line.

### Internal Behavior

1. `knowledge/manuals/` (new): `models.py` (`ManualCard`, `Procedure`, `Step`, `PartRef`, `ToolRef`, `Hazard`, `MediaRef`, `Tip`, `ManualVersion`, `ProcedureAnswer`; reuses `Evidence`/`Extracted`/`FieldProvenance`), `carding.py` (three passes + `assemble_card`), `figures.py` (extraction, caption pairing, vision captioning, upload), `video.py` (transcript blocks → segments, bm25 + judged alignment), `library.py` (`ManualLibrary.add_manual / add_video / refresh / verify`), `catalog.py` + `catalog_postgres.py` (`ManualCatalogStore` ABC, Postgres backend, FTS over procedure titles / equipment aliases / captions), `graph_loader.py` (`ManualGraphLoader`), `datasource.py` (`ManualCardDataSource(ExtractDataSource)` for `OntologyRefreshPipeline`).
2. `knowledge/ontology/defaults/domains/procedures.ontology.yaml` — entities, relations, traversal patterns, `AuthorizationSpec` per pattern.
3. `knowledge/pageindex/pdf_to_markdown.py::extract_markdown_per_page` gains an optional `images_dir` argument (returns image refs per page alongside the markdown); behaviour unchanged when unset.
4. `ai-parrot-tools/parrot_tools/procedures/` (new): `retrieval.py` (`ProcedureRetrieval`, `RequestContext`, `PatternPlan`, `Clarification`, `RetrievalResult`), `toolkit.py` (`ProceduresToolkit`), `agent.py` (agent wiring, prompt from `PromptBuilder`, `structured_output=ProcedureAnswer`), `service.py`, `cli.py`.
5. Media delivery: `ProcedureAnswer.media[]` is materialised into the response as presigned URLs (`get_file_url`, short expiry) placed where each channel renders them: Teams/Slack take http(s) URLs (`ImageSection` cards); Telegram/WhatsApp get a temp download + `send_photo` / `send_image`. Requires either widening `AIMessage.images` / `media` to accept `str` URLs or adding an `image_urls` field — see Open Questions.
6. Guided mode: `ProceduresToolkit` composes `TaskMemoryToolsMixin` (same shape as `WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)`), mapping `Step` → task step (`label=step_key`, `depends_on_labels=[prev]`); completion → `EpisodicMemoryStore.record_episode`.
7. Re-ingest: `ManualGraphLoader.publish(card)` soft-deletes `origin="manual"` nodes for that `manual_id`, upserts the new ones, re-links `Tip` by `step_key` → content-hash similarity → orphan; `Procedure.versions[]` appended with `valid_from = now`, previous `valid_to = now`.
8. Scheduler (optional, `ai-parrot-server/scheduler/manager.py::schedule`): weekly `manuals_digest` (orphaned tips, unverified procedures, videos with < 50 % step coverage).

### Edge Cases & Error Handling

- **Figure cited but not found** ("see Fig. 3-4" with no matching caption) → step keeps the literal reference in `text`, `illustrated_by` is not written, entry in the verification queue. Never attach a nearest-page guess as `primary`.
- **Figure with numbered callouts (exploded view)** → one `Media` node attached to the *procedure* (`role="overview"`) and to every step that names a callout number in its evidence; callout → part mapping is v2 (needs the parts-table + vision pass).
- **Manual covers several models** → one `Manual`, one `Procedure` per model variant only when the text branches ("for X-200 skip steps 5–6"); otherwise one procedure with `applies_to: [models]` on the steps that differ. The carding pass captures "for model …" qualifiers as evidence; unqualified = all.
- **Manual without headings** → `deterministic_sections` (as `ContractLibrary._to_markdown` does for DOCX/TXT) before carding; procedure detection then relies on numbered-list density only.
- **Scanned / image-only PDF** → refused in v1 with a clear message (`PDFLoader.is_image_only`); OCR path (`ImageLoader`) is a follow-up.
- **Equipment ambiguity** → `Clarification` with candidates (`ambiguity_strategy: ask_user`, as contracts); the agent never picks.
- **Cross-reference to another procedure** ("first complete the base assembly, §4.2") → `precedes` edge between procedures when the target resolves uniquely by title similarity ≥ 0.85; else the sentence stays in `text` and is flagged.
- **Tip on a step that disappears in the next revision** → `orphaned=true`, kept, shown in the curator queue, never returned to technicians until re-linked or retired.
- **Presigned URL expiry** → URLs are generated per answer (minutes, not days); the graph never stores a URL. Video deep links are the vendor's stable URI + `#t=`.
- **Video with no usable transcript** (music only) → `VideoUnderstandingLoader` captions only; if alignment coverage < 30 % the video is linked at procedure level with `role="overview"` and no per-step segments.
- **Unauthorized technician / equipment out of tenant** → `kind="denied"` / `out_of_scope`, no partial content (same invariants as `ContractAnswer`).
- **Graph resolution fails but the manual exists** → fallback to PageIndex `search` over that manual's tree, answer `kind="lookup"` with page citations and an explicit "not a verified procedure" line.

---

## Capabilities

### New Capabilities
- `manuals-card`: `ManualCard` family, three-pass carding with evidence, deterministic `assemble_card`, Postgres catalog + FTS.
- `manuals-figures`: figure extraction with bboxes, caption pairing, vision captioning, object-storage upload, `Media` nodes.
- `manuals-video`: transcript-block ingestion, deterministic + judged step alignment, `video_segment` media.
- `procedures-ontology`: `procedures.ontology.yaml`, `ManualGraphLoader`, `ManualCardDataSource`, origin-aware re-publish with tip re-linking.
- `procedures-toolkit`: `ProcedureRetrieval`, `ProceduresToolkit` (one action per tool), `ProcedureAnswer`, agent wiring, guided mode over `TaskMemoryToolsMixin`.
- `manuals-cli`: `parrot manuals {add,add-video,refresh,verify,queue}`.

### Modified Capabilities
- `pageindex-pdf`: `extract_markdown_per_page(images_dir=None)` — additive.
- `agent-response-media`: `AIMessage` / `AgentResponse` accept URL media (or gain `image_urls`); integrations parser passes them through to Teams/Slack cards and downloads for Telegram/WhatsApp.
- `ontology-defaults`: one more domain YAML; `TenantOntologyManager.resolve(domain="procedures")`.
- `episodic-memory`: new episode kind `procedure_completed` (data only; no API change).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/manuals/` (new) | new | models, carding, figures, video, library, catalog, graph loader, datasource |
| `knowledge/ontology/defaults/domains/procedures.ontology.yaml` (new) | new | domain vocabulary + patterns + authorization |
| `knowledge/pageindex/pdf_to_markdown.py` | extends | optional image output; default unchanged |
| `knowledge/contracts/models.py` | none (import) | `Evidence`, `Extracted`, `FieldProvenance` imported, not modified — consider moving them to `knowledge/common/` (Open Questions) |
| `ai-parrot-tools/parrot_tools/procedures/` (new) | new | retrieval, toolkit, agent, service, cli |
| `models/responses.py` | modifies | URL-capable media fields (behaviour-preserving for `Path`) |
| `ai-parrot-integrations/.../parser.py` + channel wrappers | modifies | render URL media; Telegram/WhatsApp temp-download |
| `tools/working_memory/task_memory/` | none (compose) | `TaskMemoryToolsMixin` reused as-is |
| `memory/episodic/` | none (data) | new episode kind |
| `ai-parrot-server/scheduler` | optional | `manuals_digest` |
| Admin UI (Svelte 5) | follow-up | curator queue view (same shape as the contracts verification queue) |

No breaking API changes. Everything is opt-in behind the new domain and toolkit; the `AIMessage` widening must keep every existing `Path` consumer working.

---

## Code Context

### User-Provided Code
_None — requirement given in prose: an agent over a knowledge graph (not RAG) that, from assembly manuals, lets any field technician ask how to assemble equipment and get steps, tips, photographs and video references._

### Verified Codebase References
_Paths relative to `packages/ai-parrot/src/parrot/` unless noted; verified against `main` @ `d2244e5` on 2026-09-24. Grep anchors, not line numbers._

#### Classes & Signatures
```python
# knowledge/ontology/schema.py  (every model extra="forbid")
class OntologyDefinition(BaseModel)   # name, version, extends, description, entities: dict[str, EntityDef], relations: dict[str, RelationDef], traversal_patterns: dict[str, TraversalPattern], search_views
class EntityDef(BaseModel)            # collection, source, key_field, properties: list[dict[str, PropertyDef]], vectorize: list[str], extend: bool
class PropertyDef(BaseModel)          # type: Literal["string","int","float","boolean","date","list","dict"], required, unique, default, enum, description
class RelationDef(BaseModel)          # from_ (alias "from"), to, edge_collection, properties, discovery: DiscoveryConfig | None
class DiscoveryConfig(BaseModel)      # strategy: Literal["field_match","ai_assisted","composite"], rules: list[DiscoveryRule]
class TraversalPattern(BaseModel)     # description, trigger_intents, query_template (AQL, @param/@@collection), post_action, entity_extraction, authorization: AuthorizationSpec | None, tool_call
class AuthorizationSpec(BaseModel)    # rules: list[AuthorizationRule], default_deny=True; rule ∈ target_is_self|target_in_management_chain|has_role|same_department|always

# knowledge/ontology/tenant.py / parser.py / graph_store.py / refresh.py
class TenantOntologyManager: def resolve(self, tenant_id, domain=...)   # loads defaults/domains/{domain}.ontology.yaml (+ tenant overlay), OntologyMerger.merge
class OntologyParser: def load(path); def get_defaults_dir()
class OntologyGraphStore:   # ArangoDB via asyncdb.AsyncDB, one DB per tenant
    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None) -> list[dict]
    async def upsert_nodes(self, ctx, collection, nodes, key_field) -> UpsertResult
    async def create_edges(self, ctx, edge_collection, edges)     # each edge needs _from/_to
    async def soft_delete_nodes(...); get_all_nodes; get_all_edges; edges_incident; remove_edge_by_triple; ensure_collection; initialize_tenant
class OntologyRefreshPipeline: async def run(self, tenant_id, domain)   # ExtractDataSource per EntityDef.source → RelationDiscovery.discover → store
# knowledge/ontology/mixin.py: class OntologyRAGMixin: async def ontology_process(query, user_context, tenant_id, domain=None) -> ContextEnvelope

# knowledge/ontology/defaults/domains/contracts.ontology.yaml — the template (8 entities / 16 relations / 13 patterns merged with base)
#   entities: Contract{collection: contract, source: contractcard, key_field: contract_id, properties[...], vectorize}
#   traversal_patterns.contracts_requiring_standard: trigger_intents[], query_template (FOR std IN @@compliance_standard ... RETURN {contract, obligation}),
#     post_action: none, entity_extraction.standard{type, resolver: exact_id_match, scope: same_tenant, ambiguity_strategy: ask_user}, authorization.rules[has_role]
# knowledge/ontology/defaults/domains/field_services.ontology.yaml — Employee(extend) → assigned_to → Project → has_portal → Portal (small; base-layer link pattern)
# knowledge/ontology/defaults/base.ontology.yaml — Employee, Department, Role

# knowledge/contracts/models.py
class Evidence(BaseModel)             # node_id: str, quote: str (max MAX_QUOTE_CHARS), page: Optional[int] ge=1
class Extracted(BaseModel, Generic[T])# value: Optional[T], evidence: Optional[Evidence], confidence: float 0..1
class FieldProvenance(BaseModel)      # origin: ProvenanceOrigin="llm", verification: VerificationState="extracted", node_id, page, quote, confidence, verified_by, verified_at, derived_from: list[str], candidate
class ContractVersion(BaseModel)      # n, revision, valid_from, valid_to, kind: VersionKind, amended_by, card_snapshot: dict, recorded_at, evidence_ref
class ContractCard(BaseModel)         # contract_id, tree_name, title, ..., obligations: list[Obligation], summary, topics, owner_employee_id, ... field_provenance, verification, versions[]
class ContractAnswer(BaseModel)       # answer_kind: AnswerKind, answer, citations: list[Citation], provenance: AnswerProvenance, handoff, pattern, reason
    @model_validator(mode="after") def _check_kind_invariants(self)   # lookup needs answer+citations; not_found/out_of_scope/denied carry nothing; provenance = derive_provenance(citations)

# knowledge/contracts/carding.py
class CardingDraft(BaseModel); def deontic_density(text) -> int; def select_header_nodes(...); def select_obligation_nodes(...)
def header_prompt(*, filename, toc_digest, material) -> str; def obligations_prompt(*, node_id, title, body) -> str
def validate_header_evidence(...); def validate_obligation_clauses(...); def fallback_header_draft(source, toc=()) -> ContractHeaderDraft
async def draft_contract(...); def similarity(left, right) -> float; def derive_status(...); def resolve_parent(...)

# knowledge/contracts/graph_loader.py
class EdgeSpec(BaseModel)             # source_id, target_id, triple(), document()
class GraphPublicationReport(BaseModel)  # complete
class ContractGraphLoader:
    def __init__(self, *, catalog: ContractCatalogStore, graph_store, tenant_manager=None, datasource: Optional[ContractCardDataSource]=None, ontology_dir=None, domain=CONTRACTS_DOMAIN)   # datasource defaults to ContractCardDataSource("contractcard", {"catalog": catalog})
    async def startup_check(self); @staticmethod def desired_edges(snapshot) -> list[EdgeSpec]
    async def publish_all(self) -> GraphPublicationReport; async def publish(self, card: ContractCard); async def retract(self, contract_id)
    async def _reconcile_edges(...); async def _verify(...)

# knowledge/contracts/library.py
class TreeIndexer(Protocol): create_tree(tree_name, doc_name=None); insert_markdown(...); get_tree(tree_name); delete_tree(tree_name)
class ContractLibrary:
    async def add_contract(...); async def add_folder(...); async def verify_card(...); async def refresh_card(...); async def apply_amendment_history(...); async def relate_contracts(...)
    async def _to_markdown(self, path, source_format) -> tuple[str, dict[int, int]]   # (markdown, page_hints) — PDF via _extract_pdf_pages (pymupdf) + pdf_markdown; docx via docx_to_markdown + promote_numbered_headings/deterministic_sections
# knowledge/contracts/catalog_postgres.py: class PostgresContractCatalog(ContractCatalogStore)

# knowledge/bookstore
# models.py: class TocEntry(node_id, title, depth=1, start_page, end_page); class BookCard (book_id == tree_name, toc, toc_digest, source_sha256, source_format, page_count, card_origin)
# carding.py: _CARD_PROMPT; def slugify(text); def unique_slug(base, taken); def derive_toc(tree, max_depth=2) -> (list[TocEntry], digest); async def generate_card_fields(adapter, *, filename, doc_description, toc_digest, samples)  # adapter.ask_structured(prompt, CardDraft)
# library.py: class Bookstore: async def add_book(file_path, scope="project", title=None, authors=None, topics=None, force=False, *, relate=False) -> (BookCard, status)
# relations.py: deterministic_relations, candidate_pairs, judge_relations, build_book_graph
# catalog.py: class CatalogStore(db_path)  # SQLite + FTS

# knowledge/pageindex
# toolkit.py: class PageIndexToolkit(AbstractToolkit): tool_prefix="pageindex"; create_tree(tree_name, doc_name=None); import_pdf(tree_name, pdf_path, parent_node_id=None, with_summaries=True, with_doc_description=False); insert_markdown(tree_name, markdown, parent_node_id=None, doc_name=None); get_tree; delete_tree; search; retrieve; add_node; update_node_content; tag_node
# schemas.py: class PageIndexNode  # title, node_id, start_index, end_index (physical pages), summary, prefix_summary, text, line_num, nodes; extra="allow"
# pdf_to_markdown.py: def extract_markdown_per_page(pdf_path) -> list[tuple[int, str]]   # pymupdf4llm.to_markdown(path, page_chunks=True); no images
# store.py: JSONTreeStore; content_store.py: NodeContentStore.save/load/loader_for

# models/responses.py
class AIMessage(BaseModel)   # images: Optional[List[Path]], media: Optional[List[Path]], files: Optional[List[Path]], documents, data, structured_output
class AgentResponse(BaseModel)  # images, media, documents (same typing)

# tools/toolkit.py: class AbstractToolkit  # tool_prefix: str | None, prefix_separator="_", exclude_tools, confirming_tools, llm_dependent_tools, return_direct; public async methods → tools "{prefix}_{method}"; get_tools()
# tools/abstract.py: class AbstractTool(EventEmitterMixin, ABC)  # name, description, args_schema, return_direct, async _execute(**kwargs)

# tools/working_memory/task_memory/tools.py
class TaskMemoryToolsMixin:
    async def begin_task(self, goal: str, constraints=None, steps: Optional[List[dict]]=None, plan_complete: bool=False) -> dict   # step dict: label, title, description, required, depends_on_labels
    async def update_step(self, task_id, step_id, expected_revision: int, status: str, evidence_refs=None, note=None, reason=None)   # status ∈ pending|running|blocked|completed|failed|cancelled|superseded
    async def set_resume_hint(self, task_id, next_action, step_id=None) -> dict
    async def recall_task(self, task_id=None, max_tokens=2500, recent_calls_limit=8) -> dict
# tools/working_memory/tool.py: class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit): tool_prefix="wm"
# memory/episodic/store.py: class EpisodicMemoryStore: record_episode, record_tool_episode, recall_similar, get_failure_warnings, get_user_preferences

# bots/base.py / bots/abstract.py: async def ask(..., structured_output: Type[BaseModel] | StructuredOutputConfig = None); async def invoke(..., response_model=None)  → AIMessage.structured_output

# ai-parrot-tools/src/parrot_tools/contracts/retrieval.py
class RequestContext(BaseModel); class AuthorizationDenied(PermissionError); class Clarification(BaseModel); class PatternPlan(BaseModel); class RetrievalResult(BaseModel)
class ContractRetrieval:
    def authorize(...); async def resolve_contract(...); async def resolve_party(...); async def plan(self, question, context) -> PatternPlan | Clarification
    async def retrieve(self, question, context) -> RetrievalResult | Clarification; async def execute(self, plan, context) -> RetrievalResult; def aql_for(self, pattern) -> str; async def execute_graph(...); async def _validate_projection(rows)
# ai-parrot-tools/src/parrot_tools/contracts/toolkit.py
class ContractsToolkit(AbstractToolkit): tool_prefix = "contracts"   # catalog_search, get_card, get_toc, read_section, obligations, expiring, verification_queue, related_contracts, verify_card, retire_answer
# also: contracts/{agent,service,verifier,jobs,flow,cli}.py

# ai-parrot-loaders/src/parrot_loaders
# pdf.py: class PDFLoader  # fitz; is_image_only() uses page.get_images(full=True) to SKIP image-only pages
# pdfmark.py: class PDFMarkdownLoader(..., extract_images: bool = False)  # stored (self.extract_images) and never used
# imageunderstanding.py: class ImageUnderstandingLoader(AbstractLoader)  # _analyze_image_with_ai → GoogleGenAIClient.image_understanding
# basevideo.py: class BaseVideoLoader  # get_whisper_transcript(audio_path, chunk_length=30, word_timestamps=False), get_whisperx_transcript, transcript_to_vtt, audio_to_srt, def transcript_to_blocks(self, transcript) -> list  (SRT timestamps per block)
# video.py: YoutubeLoader (yt_dlp → whisper); videolocal.py: VideoLocalLoader; videounderstanding.py: class VideoUnderstandingLoader(BaseVideoLoader)  # Gemini video_understanding → timecoded scenes
# ocr/layoutlm.py: LayoutLMv3 label set includes "figure" and "caption"

# Vision entry points (per provider, NOT on AbstractClient):
# ai-parrot-client-anthropic/.../anthropic/client.py, ai-parrot-client-google/.../google/client.py, ai-parrot-client-openai/.../openai/client.py:
#   async def ask_to_image(self, prompt, image, reference_images=None, ..., structured_output=None, count_objects=False, history=None, no_memory=False) -> AIMessage
# google/analysis.py: image_understanding(prompt, images, model, ..., detect_objects=False, structured_output=None); video_understanding(prompt, ..., video=..., offsets=...)

# Storage: interfaces/file/*.py re-export S3FileManager, GCSFileManager, LocalFileManager, TempFileManager (navigator.utils.file; FileManagerInterface: upload_file, create_from_bytes, get_file_url(path, expiry_seconds), download_file, exists, get_file_metadata)
# storage/overflow.py: OverflowStore.generate_presigned_url(key, *, expires_in=604800); storage/s3_overflow.py: S3OverflowManager; tools/filemanager.py: FileManagerToolkit (tool_prefix="fs")

# Channels (ai-parrot-integrations/src/parrot/integrations/): parser.py::parse_response(response) -> ParsedResponse(text, images, documents, media, charts)
#   telegram/wrapper.py::_send_attachments → bot.send_photo/send_video/send_document(FSInputFile)   (local files)
#   msteams/handler.py::MessageHandler.send_image(url, turn_context, mimetype), send_card; wrapper renders ImageSection/ImageEntry (parrot.outputs.cards) for http(s) or data:image/ only, max 3; local paths → text line
#   whatsapp/wrapper.py: client.send_image(to=..., image=str(p)) (pywa);  slack/wrapper.py: image blocks for http(s) URLs only

# ai-parrot-server/src/parrot/scheduler/manager.py: def schedule(schedule_type=ScheduleType.DAILY, *, success_callback, send_result, callbacks, **schedule_config); schedule_daily_report; class AgentSchedulerManager
# knowledge/wiki/store.py: class WikiPageRecord (origin: "ingest"|"authored"|"memory", source_id, ...); BaseWikiStore.replace_source_slice(source_id, pages, edges=None)  — the "authored survives re-ingest" precedent
```

#### Verified Imports
```python
from parrot.knowledge.contracts.models import Evidence, Extracted, FieldProvenance, ContractVersion, ContractAnswer, ContractCard
from parrot.knowledge.contracts.graph_loader import ContractGraphLoader, EdgeSpec, GraphPublicationReport
from parrot.knowledge.contracts.library import ContractLibrary
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc, sample_sections
from parrot.knowledge.bookstore.models import TocEntry
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.pdf_to_markdown import extract_markdown_per_page
from parrot.knowledge.ontology.schema import OntologyDefinition, TraversalPattern, AuthorizationSpec
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory.task_memory.tools import TaskMemoryToolsMixin
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.models.responses import AIMessage, AgentResponse
from parrot_tools.contracts.retrieval import ContractRetrieval, RequestContext, PatternPlan, Clarification, RetrievalResult
from parrot_tools.contracts.toolkit import ContractsToolkit
from parrot_loaders.basevideo import BaseVideoLoader
from parrot_loaders.video import YoutubeLoader
from parrot_loaders.videounderstanding import VideoUnderstandingLoader
import pymupdf, pymupdf4llm   # packages/ai-parrot/pyproject.toml: "pymupdf>=1.27", "pymupdf4llm>=0.0.27" (locked: pymupdf==1.27.1, pymupdf4llm==0.0.27)
```

#### Key Attributes & Constants
- `ContractCard.contract_id == PageIndex tree_name` — same identity rule for `ManualCard.manual_id`.
- `TocEntry.start_page` / `end_page` come from `PageIndexNode.start_index` / `end_index` — page citations are free; figures are not.
- `Path("https://bucket/a.png")` stringifies to `https:/bucket/a.png` — any presigned URL placed in `AIMessage.images` / `media` (typed `List[Path]`) fails the `startswith("https://")` checks in the Teams and Slack wrappers. Confirmed in Python during verification.
- `ContractsToolkit` uses `confirming_tools` for writes (`verify_card`, `retire_answer`) — `proc_add_tip` / `proc_verify_procedure` follow.
- The Google client is the only one with `video_understanding`; `ask_to_image` exists on Anthropic, Google and OpenAI clients but not on `AbstractClient` — `figures.py` must resolve the client by capability, not by protocol.
- `OntologyRefreshPipeline` matches `ExtractDataSource` by `EntityDef.source` — `procedures.ontology.yaml` entities declare `source: manualcard` and `ManualCardDataSource` feeds them, as `ContractCardDataSource` does today.
- `bookstore/relations.py::judge_relations` keeps a judgement log and re-runs with `--force` — the pattern for the LLM-judged tail of video alignment.

### Does NOT Exist (Anti-Hallucination)
- ~~Figure / image extraction from PDFs anywhere in ingestion~~ — `extract_markdown_per_page` writes no images; `PDFMarkdownLoader.extract_images` is an unused flag; no `Pixmap` / `extract_image` / `write_images` call in `parrot_loaders` or `pageindex`.
- ~~Captioning of figures inside PDFs at load time~~ — only standalone image files via `ImageUnderstandingLoader`.
- ~~Image or figure references on `PageIndexNode`, `TocEntry`, `BookCard` or `ContractCard`~~.
- ~~`knowledge/manuals/`, `ManualCard`, `ManualGraphLoader`, `ManualLibrary`, `procedures.ontology.yaml`, `ProceduresToolkit`, `ProcedureRetrieval`, `ProcedureAnswer`~~ — all new.
- ~~A generic `OntologyToolkit` exposing traversal patterns to any agent~~ — only domain toolkits (`ContractsToolkit`) and `GraphIndexToolkit` (rustworkx + FAISS, not the ontology store).
- ~~Any guided-procedure / checklist / step-by-step / training / quiz tool or agent~~ — the only related code is display-only (`models/infographic.py::StepsBlock, StepItem, ChecklistBlock`).
- ~~Video keyframe extraction or timestamped clip linking~~ — transcripts with timestamps exist (`transcript_to_blocks`), nothing maps them to document sections. No `youtube_transcript_api`.
- ~~A URL-typed media field on `AIMessage` / `AgentResponse`~~ — `images`, `media`, `files` are `List[Path]`.
- ~~Local-file image upload in the Slack and Teams wrappers~~ — those two render http(s) / `data:` URLs only.
- ~~OCR path for image-only PDFs in `PDFLoader`~~ — such pages are skipped; OCR lives in `ImageLoader` for image files.
- ~~`ask_to_image` on `AbstractClient`~~ — per-provider only.
- ~~Shared `knowledge/common/` for `Evidence` / `Extracted` / `FieldProvenance`~~ — they live in `knowledge/contracts/models.py`.

---

## Spike Gate (before `/sdd-spec`)

1. **Figure → step pairing fidelity** (the gate). Three real manuals from the client (or, failing that, three public vendor assembly manuals of comparable layout, PDF, 20–120 pages, with numbered figures). Run `extract_markdown_per_page` with image output + bbox capture + caption regex + step carding (pass 2). Hand-count per manual: procedures found / expected, steps in correct order / expected, steps with the correct **primary** figure / steps that cite a figure, figures left unpaired. Pass = ≥ 90 % of steps in order with no missing required step, ≥ 80 % correct primary figure on captioned figures. Below that, the design changes to "figures at procedure level + vision pass per step" before speccing.
2. **Media delivery round-trip.** Put a presigned S3 URL for one extracted figure into an agent answer and deliver through Teams, WhatsApp and Telegram. Confirm the `Path`-typing failure, then prototype the smallest fix (widen to `Path | str` vs. `image_urls`) and check the three channels render/send it. Decides the `models/responses.py` change.
3. **Video alignment.** One training video (≥ 10 min, with speech) + its manual: `YoutubeLoader`/`VideoLocalLoader` transcript blocks → `bm25s` alignment to the carded steps; hand-score precision of `t_start`/`t_end` per step, and coverage. Pass = ≥ 70 % of steps get a segment whose window contains the demonstrated action; the judged tail must add coverage without lowering precision.
4. **Tip survival across revisions.** Publish manual rev A to a throwaway ArangoDB tenant, add three tips, publish rev B with one step renumbered, one reworded, one removed; assert re-link by `step_key`, re-link by content hash, and one `orphaned=true`. Exercises `ManualGraphLoader.publish` + the `versions[]` append.

---

## Parallelism Assessment

- **Internal parallelism**: yes, after the models lane. Lane 1 (`manuals/models.py`, `procedures.ontology.yaml`, `ManualCatalogStore` ABC + Postgres) is the contract. Lane 2 (`figures.py` + `pdf_to_markdown` image output), Lane 3 (`carding.py` + `library.py`), Lane 4 (`video.py`), Lane 5 (`graph_loader.py` + `datasource.py`) and Lane 6 (`parrot_tools/procedures/` retrieval + toolkit + agent + guided mode) are independent once `ManualCard` / `Procedure` / `Step` / `MediaRef` are frozen. Lane 7 (`responses.py` widening + integrations) is orthogonal and small.
- **Cross-feature independence**: touches `models/responses.py` and the integrations parser (shared with every channel — land once, behaviour-preserving); imports from `knowledge/contracts/models.py` (read-only unless the shared-module move in Open Questions is taken, which should then be its own tiny PR).
- **Recommended isolation**: `mixed` — one worktree for Lane 1, then per-lane worktrees; Lane 7 as a separate small feature.
- **Rationale**: the foundation is Pydantic models plus one YAML; everything else is additive modules that mirror an existing package file-for-file.

---

## Open Questions

- [ ] **Card granularity**: one `ManualCard` per document with embedded `procedures[]` (recommended — mirrors `ContractCard.obligations[]`), or one `ProcedureCard` per procedure with a thin `Manual` node? The latter makes cross-manual procedures cleaner but breaks the "card == document == tree_name" identity. — *Owner: Jesus*
- [ ] **Shared evidence models**: import `Evidence` / `Extracted` / `FieldProvenance` from `knowledge/contracts/models.py`, or move them to `knowledge/common/provenance.py` now that there are two consumers (the "generalize when there are two" rule from FEAT-539 D1)? — *Owner: Jesus*
- [ ] **Media in the answer path**: widen `AIMessage.images` / `media` to `List[Path | str]` (and teach `parse_response` to keep URLs) vs. add `image_urls: list[str]` / `media_urls` and leave `Path` fields untouched. Spike 2 decides; the second is safer for existing channel code. — *Owner: Jesus*
- [ ] **Authorization granularity**: tenant-wide `has_role: technician` on every pattern (recommended for v1), or per-`Equipment` allowlists (some clients restrict procedures to certified staff)? Per-equipment needs an `Employee → certified_for → Equipment` relation in the domain. — *Owner: Jesus / client*
- [ ] **Vision at ingest — which client?** Figure captioning needs `ask_to_image`; Google additionally offers `image_understanding` with `detect_objects`. Pick one provider for captioning (cost, determinism) or resolve by capability at runtime. — *Owner: Jesus*
- [ ] **Exploded-view callouts (v2?)**: map numbered callouts to `Part` nodes via a vision structured-output pass (`ask_to_image(structured_output=CalloutMap)`). Valuable ("which one is part 7?") but only after spike 1 shows the plain pairing works. — *Owner: Jesus*
- [ ] **Where figures live**: tenant S3 bucket through `S3FileManager` (recommended) vs. the overflow store (`S3OverflowManager`, 7-day presign default — wrong lifetime for training assets). — *Owner: Jesus*
- [ ] **Guided-mode state owner**: `TaskMemoryToolsMixin` composed into `ProceduresToolkit` (recommended, one toolkit) vs. the agent also carrying `WorkingMemoryToolkit` and the procedure toolkit only emitting the step list. — *Owner: Jesus*
- [ ] **Tips moderation**: technician tips visible immediately (recommended — attributed, retirable) vs. curator approval before visibility. Client policy question. — *Owner: client*
- [ ] **Applicability by serial / model year**: `versions[]` on `Procedure` covers manual revisions; serial-range applicability ("from S/N 2024-0001 use the new clip") would need `applies_to` ranges on `Step` and a resolver at answer time. v2 unless the spike corpus shows it. — *Owner: Jesus*
- [ ] **Offline field use**: technicians without connectivity are out of scope for this agent (channels are online); if it becomes a requirement, the graph export for a per-device viewer is a separate feature. — *Owner: client*
