---
id: FEAT-601
title: Procedure Graph — field-training agent over equipment assembly manuals
slug: training-agent
type: feature
mode: enrichment
status: discussion
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-24
  summary_oneline: Procedure Graph — field-training agent over assembly manuals (ManualCard → procedures ontology → ProceduresToolkit), figures + video as graph nodes
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations, ai-parrot-loaders]
tags: [knowledge-graph, ontology, manuals, procedures, figures, video, media-delivery, guided-mode]
research_state: sdd/state/FEAT-601/
created: 2026-09-24
updated: 2026-09-24
---

# FEAT-601 — Procedure Graph — field-training agent over equipment assembly manuals

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/training-agent.brainstorm.md` (Option B, recommended by the brainstorm)
> **Audit**: [`sdd/state/FEAT-601/`](../state/FEAT-601/)

---

## 0. Origin

The source is the accepted brainstorm `sdd/proposals/training-agent.brainstorm.md` (2026-09-24, Option B recommended). Full copy at `sdd/state/FEAT-601/source.md`.

> Field technicians need to ask "how do I assemble equipment X?" and get back the **ordered** steps, what to have ready before starting, the safety warnings, the figure that goes with each step, the segment of the training video that shows it, and the tips other technicians left. […] Plain RAG over chunked manuals is the wrong shape for this content […] `knowledge/contracts/` shipped exactly the pattern this needs (a per-document card with per-field provenance, a deterministic `ContractGraphLoader` into the ArangoDB ontology store, a `ContractsToolkit` with one action per tool, an answer model whose citations are never model-authored). The manual case is that pattern plus two things the contracts case did not need: **figures** and **video segments** as first-class graph nodes.

**Initial signals** (extracted, not interpreted):
- Verbs: assemble, ingest, extract, pair, align, re-link, render, guide
- Named entities: ManualCard, procedures.ontology.yaml, ManualGraphLoader, ProceduresToolkit, ProcedureAnswer, ContractGraphLoader, ContractsToolkit, PageIndexToolkit, pymupdf4llm, TaskMemoryToolsMixin, AIMessage.images
- Components / labels: knowledge/contracts, knowledge/ontology, knowledge/pageindex, parrot_tools/contracts, integrations (Teams/Slack/Telegram/WhatsApp), parrot_loaders (video)
- Acceptance criteria provided: yes — a 4-item **Spike Gate** (figure→step pairing ≥90 %/≥80 %, media round-trip, video alignment ≥70 %, tip survival) plus 11 open questions

---

## 1. Synthesis Summary

The request is to build a procedure knowledge graph over vendor assembly manuals and serve it to field technicians through a domain toolkit, copying the `knowledge/contracts` + `parrot_tools/contracts` architecture (card → deterministic graph loader → one-action-per-tool toolkit → verified answer). Research confirms every reuse target exists and is line-anchored (`knowledge/contracts/models.py`, `carding.py`, `graph_loader.py`, `library.py`, `parrot_tools/contracts/retrieval.py`, `toolkit.py`, `agent.py`), but six claims the brainstorm made about that template are wrong and change the design: `ContractGraphLoader.publish` is whole-catalog reconciliation with no `origin` filter to extend; `ContractsAgent` does not use `structured_output` (answers are released by `ContractsAnswerService`); there is no `parrot contracts` CLI; presigned URLs cannot travel through `AIMessage.images` at all (Path coercion plus an `exists()` filter in `integrations/parser.py`); `YoutubeLoader` lives in `youtube.py`; and dropping `procedures.ontology.yaml` into `defaults/domains/` only works through a dedicated `TenantOntologyManager`. Figure extraction is confirmed net-new (no PDF image code anywhere) but fully supported by the pinned `pymupdf4llm`. Recommendation: proceed to `/sdd-spec` with Option B, encode the corrections in §2.2/§3, and keep the brainstorm's four spikes as the spec's first milestone since none of them is answerable from the repo.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-601/findings/` (F001–F031). Paths are shortened: `knowledge/…` = `packages/ai-parrot/src/parrot/knowledge/…`, `parrot_tools/…` = `packages/ai-parrot-tools/src/parrot_tools/…`, `integrations/…` = `packages/ai-parrot-integrations/src/parrot/integrations/…`, `parrot_loaders/…` = `packages/ai-parrot-loaders/src/parrot_loaders/…`. Verified at `dev` @ `4025699ed` (2026-09-24).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `knowledge/contracts/models.py` | `Evidence / Extracted[T] / FieldProvenance / trim_quote / MAX_QUOTE_CHARS` | 88-111, 160-175, 205-311 | generic evidence primitives a ManualCard imports as-is | F001 |
| 2 | `knowledge/contracts/models.py` | `ContractVersion / Citation / ContractAnswer._check_kind_invariants / derive_provenance` | 417-475, 701-818 | contract-bound models to COPY (contract_id field, AnswerKind literal) into manuals/models.py | F001 |
| 3 | `knowledge/contracts/carding.py` | `select_header_nodes / select_obligation_nodes / deontic_density / _quote_supported / _validate_extracted / draft_contract / similarity` | 216-354, 456-483, 678-786, 868-892 | bounded 1+N structured-output carding pass with verbatim-quote validation — template for the three-pass manual carding | F002 |
| 4 | `knowledge/contracts/graph_loader.py` | `EdgeSpec / ContractGraphLoader.publish_all / _reconcile_edges / publish / retract` | 106-154, 471-548, 594-675 | whole-catalog reconciliation loader — template for ManualGraphLoader; publish(card) only delegates to publish_all() | F003 |
| 5 | `knowledge/contracts/library.py` | `TreeIndexer / ContractLibrary.add_contract / _to_markdown / _extract_pdf_pages / _ingest` | 96-115, 516-607, 910-970, 1000-1030 | sha-dedup → markdown → staged PageIndex tree → card → catalog upsert; PDF path is text-only | F004 |
| 6 | `knowledge/contracts/catalog.py` | `ContractCatalogStore (ABC) / search / verification_queue` | 292-436, 631-681 | catalog protocol (40 abstract methods) to cut down to ManualCatalogStore | F005 |
| 7 | `knowledge/contracts/catalog_postgres.py` | `PostgresContractCatalog.search / verification_queue / upsert` | 85-119, 531-560, 914-944, 998-1060 | jsonb card + generated English tsvector FTS; jsonb_each verification queue works for any card with field_provenance | F005 |
| 8 | `knowledge/contracts/datasource.py` | `ContractCardDataSource.infer_entity / snapshot / extract / register` | 55-64, 144-192, 380-455 | ExtractDataSource that infers the entity from key fields (ENTITY_ROUTING_ORDER) — template for ManualCardDataSource | F006, F012 |
| 9 | `knowledge/contracts/evidence.py` | `EvidenceRef / StagingArea / EvidenceArchive.resolve` | 78-95, 145-158, 462-497 | release-time verbatim/version/page check; EvidenceRef hardcodes contract_id | F006 |
| 10 | `knowledge/ontology/defaults/domains/contracts.ontology.yaml` | `entities.Party / relations.signed_by / relations.is_employee / traversal_patterns.contracts_requiring_standard / search_views` | 1-4, 141-167, 276-310, 444-508 | YAML shapes for procedures.ontology.yaml: edge properties, base-layer Employee link via field_match, per-pattern authorization | F008 |
| 11 | `knowledge/ontology/schema.py` | `PropertyDef / EntityDef / RelationDef / AuthorizationRule / TraversalPattern / OntologyDefinition` | 18-37, 40-77, 114-136, 176-226, 261-295, 419-446 | extra=forbid schema; list/dict props untyped; typed edge properties declarable; five rule kinds | F009 |
| 12 | `knowledge/ontology/graph_store.py` | `OntologyGraphStore.upsert_nodes / create_edges / soft_delete_nodes / query_documents / edges_incident / remove_edge_by_triple` | 311-486, 517-559, 697-736, 764-827 | write/read seams; create_edges upserts on (_from,_to) with UPDATE {}; soft-delete is key-list only | F010 |
| 13 | `knowledge/ontology/tenant.py` | `TenantOntologyManager.__init__ / resolve` | 48-131 | domain YAML is looked up under ontology_dir/domains only; cache keyed by tenant_id | F011 |
| 14 | `knowledge/ontology/refresh.py` | `OntologyRefreshPipeline.run / _refresh_entity` | 94-143, 158-222 | generic refresh soft-deletes everything absent from an extraction — contracts bypasses it | F012 |
| 15 | `knowledge/pageindex/pdf_to_markdown.py` | `extract_markdown_per_page / build_node_markdown_map` | 35-94, 97-137 | single pymupdf4llm call (page_chunks=True, no image kwargs) — the seam for images_dir | F013, F015 |
| 16 | `knowledge/pageindex/builder.py` | `_extract_node_markdown / build_page_index` | 1545-1551, 1596, 1622-1639 | only caller of extract_markdown_per_page; returns {} for BytesIO input | F013 |
| 17 | `knowledge/pageindex/toolkit.py` | `PageIndexToolkit.import_pdf` | 803-845 | pops _node_markdown sidecars; where an images sidecar would be threaded | F013 |
| 18 | `knowledge/bookstore/carding.py` | `slugify / unique_slug / derive_toc / sample_sections / generate_card_fields` | 49-138, 157-215 | pure helpers reused as-is (slugify collapses non-Latin to 'book') | F014 |
| 19 | `knowledge/bookstore/relations.py` | `candidate_pairs / judge_relations` | 296-413 | one structured call per source, hallucinated ids dropped — pattern for the LLM-judged video-alignment tail | F014 |
| 20 | `knowledge/bookstore/library.py` | `Bookstore.relate_books` | 640-677 | `judged = set() if force else store.judged_pairs(...)` — the --force / judgement-log mechanics | F014 |
| 21 | `parrot_tools/contracts/retrieval.py` | `PATTERNS / _TRIGGERS / classify / ContractRetrieval.plan / execute / execute_graph / _validate_projection` | 66-86, 142-243, 431-494, 535-629, 681-745 | deterministic substring-trigger planner (no LLM); projection validator is contract-shaped | F016 |
| 22 | `parrot_tools/contracts/toolkit.py` | `ContractsToolkit / _gate / verify_card / retire_answer` | 39-107, 305-376 | tool_prefix, confirming_tools, per-tool authorize gate | F017 |
| 23 | `parrot_tools/contracts/agent.py` | `ContractsAgent.__init__ / agent_tools / answer_question / _draft_reply / released_answer` | 232-353 | Agent subclass; draft via super().ask(), answer released by the service (no structured_output) | F017 |
| 24 | `parrot_tools/contracts/service.py` | `ContractsAnswerService.answer` | 105-212 | producer → CitationVerifier → released ContractAnswer gate | F018 |
| 25 | `parrot_tools/contracts/verifier.py` | `CitationVerifier.verify` | 102-206 | citation verification before release | F018 |
| 26 | `parrot_tools/contracts/cli.py` | `build_parser / main` | 58-66, 362-391 | argparse `python -m parrot_tools.contracts`; not a `parrot` subcommand | F018 |
| 27 | `cli/__init__.py` | `cli._lazy_commands / cli._lazy_extras / LazyGroup.get_command` | 71-145 | registration point for a `parrot manuals` click group | F018 |
| 28 | `models/responses.py` | `AIMessage.images/media/files / AgentResponse` | 75-96, 1094-1170 | List[Path] typing; str→Path coercion mangles https:// | F019 |
| 29 | `integrations/parser.py` | `parse_response / ParsedResponse / ChartData.public_url` | 21-38, 83-95, 519-565 | drops images/media/files whose path.exists() is False; data: strings survive only via documents | F019 |
| 30 | `integrations/msteams/wrapper.py` | `MSTeamsAgentWrapper._parse_response / _parsed_to_card_spec` | 1128-1157, 1259-1312 | http(s) images[:3] → ImageSection; data:image/ via documents[:5] | F020 |
| 31 | `integrations/slack/wrapper.py` | `SlackAgentWrapper._build_blocks` | 591-603 | image block per http(s) image, no cap, no data: | F020 |
| 32 | `integrations/telegram/wrapper.py` | `TelegramAgentWrapper._send_attachments` | 2960-2996 | send_photo(FSInputFile(path)) — local files only | F020 |
| 33 | `integrations/whatsapp/wrapper.py` | `WhatsAppAgentWrapper._send_parsed_response` | 286-310 | client.send_image(image=str(p)); charts use public_url | F020 |
| 34 | `tools/working_memory/task_memory/tools.py` | `TASK_TOOL_METHODS / BeginTaskInput / UpdateStepInput / TaskMemoryToolsMixin.begin_task / update_step / set_resume_hint / recall_task` | 91-102, 237-286, 397-435, 529-538, 664, 772-782 | guided-mode primitives; step dict {label,title,description,required,depends_on_labels} | F021 |
| 35 | `tools/working_memory/tool.py` | `WorkingMemoryToolkit` | 47-89, 141-155 | (TaskMemoryToolsMixin, AbstractToolkit) composition, tool_prefix='wm', opt-in when task_memory passed | F021 |
| 36 | `tools/working_memory/task_memory/models.py` | `TaskScope` | 571-587 | (chatbot_id, user_id, session_id) scope — session-bound by default | F021 |
| 37 | `memory/episodic/store.py` | `EpisodicMemoryStore.record_episode / recall_similar` | 106-153, 377-385 | completion history; closed EpisodeCategory/EpisodeOutcome enums | F022 |
| 38 | `memory/episodic/models.py` | `EpisodeOutcome / EpisodeCategory` | 20-38 | closed str-Enums (7 categories); pgvector column is VARCHAR(32) | F022 |
| 39 | `clients:anthropic/anthropic/client.py` | `AnthropicClient.ask_to_image` | 1329-1342 | vision entry point (Path/bytes, system_prompt) | F023 |
| 40 | `clients:google/google/client.py` | `GoogleGenAIClient.ask_to_image` | 5160-5172 | vision entry point (Path/bytes only) | F023 |
| 41 | `clients:google/google/analysis.py` | `GoogleAnalysis.image_understanding / video_understanding` | 208-229, 272-273, 438-452 | detect_objects / structured_output; video offsets=(start,end) only on the client | F023, F025 |
| 42 | `clients:openai/openai/client.py` | `OpenAIClient.ask_to_image` | 1468-1479 | vision entry point | F023 |
| 43 | `clients/base.py` | `AbstractClient` | 254 | has no ask_to_image — capability check required | F023 |
| 44 | `storage/overflow.py` | `OverflowStore.generate_presigned_url` | 119-144 | expires_in capped at 604800 s; delegates to get_file_url(key, expiry=...) | F024 |
| 45 | `interfaces/file/__init__.py` | `re-exports / _LAZY_MANAGERS` | 1-47 | FileManagerInterface, Local/Temp eager; S3/GCS lazy — from navigator.utils.file (navigator-api 4.0.0) | F024 |
| 46 | `parrot_loaders/basevideo.py` | `BaseVideoLoader.transcript_to_blocks / get_whisper_transcript / get_whisperx_transcript` | 860-887, 1002-1209 | blocks with start_seconds/end_seconds; word timestamps only via whisperx | F025 |
| 47 | `parrot_loaders/youtube.py` | `YoutubeLoader.load_video` | 298-395 | video_dialog Documents per block with deeplink ?t=Ns (NOT in video.py) | F025 |
| 48 | `parrot_loaders/videounderstanding.py` | `extract_scenes_from_response / VideoUnderstandingLoader._analyze_video_with_ai` | 51-103, 163-187 | untimed 'Scene N' labels; no offsets, no model= passed | F025 |
| 49 | `parrot_loaders/pdf.py` | `PDFLoader.is_image_only / _load` | 54-61, 221-223, 263-264, 328-335 | image-only pages skipped; to_markdown called without image kwargs | F031, F015 |
| 50 | `parrot_loaders/pdfmark.py` | `PDFMarkdownLoader.__init__ / _convert_to_markdown_pymupdf4llm` | 54, 67, 117-123 | extract_images flag stored, never read | F031 |
| 51 | `packages/ai-parrot/pyproject.toml` | `[graphindex] / [bookstore] / agents extras` | 273-283, 338-345, 431-433 | rapidfuzz only in graphindex+scraping; bm25s/pymupdf/pymupdf4llm only in bookstore/agents/documents extras | F026 |
| 52 | `models/infographic.py` | `ChecklistBlock / StepsBlock` | 933, 962 | display-only models — name collision to avoid in parrot.models | F030 |
| 53 | `sdd/tasks/index/contracts-card-ontology.json` | `FEAT-539` | 1-9 | still open: TASK-3056 in-progress, TASK-3054 done-with-issues | F029 |
| 54 | `sdd/specs/graphindex-core-seams.spec.md` | `FEAT-540 lazy roots` | 141-146, 210 | pending refactor makes knowledge/ontology/__init__.py a PEP 562 lazy root | F029 |
| 55 | `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py` | `FakeGraphStore / FakeTenantManager` | 41-60, 126 | in-memory graph store reproducing the create_edges no-update quirk — reuse for manuals tests | F007 |
| 56 | `packages/ai-parrot/tests/knowledge/contracts/test_carding.py` | `FakeAdapter` | 95-110 | scripted ask_structured double | F007 |
| 57 | `packages/ai-parrot/tests/knowledge/contracts/test_ingestion.py` | `FakeIndexer` | 46-60 | NodeContentStore-backed tree from markdown headings | F007 |

### 2.2 Constraints Discovered

- **ContractGraphLoader.publish(card) delegates to publish_all(): step 2 soft-deletes every owned vertex absent from the snapshot and _reconcile_edges removes every edge in FEATURE_EDGE_COLLECTIONS not in desired_edges(); no `origin` property is read or written anywhere (docstring only).**
  *Implication*: Tip survival is NOT a filter to extend — it is new work: either keep Tip nodes and has_tip/authored_by edges in collections outside the loader's owned set (never touched), or stamp origin in desired_edges and skip origin=='technician' in the obsolete comprehension (L481-485), the edge-removal branch (L522-536) and retract (L656-664).
  *Evidence*: F003, F010

- **OntologyGraphStore.create_edges upserts on {_from,_to} with UPDATE {}: edge properties are never updated and a second edge between the same pair collapses; edges_incident/remove_edge_by_triple address edges by source_id/target_id/kind.**
  *Implication*: Every written edge must carry source_id/target_id/kind (EdgeSpec.document()) and changed properties go through remove+recreate (_reconcile_edges). A (Step, Media) pair with two roles, or a Step requiring the same Part twice, must become one edge with list-valued properties.
  *Evidence*: F010, F003

- **TenantOntologyManager.resolve() looks for domain YAMLs under ontology_dir/domains only (defaults fallback exists for base only), logs a missing domain at debug level, and caches by tenant_id ignoring domain.**
  *Implication*: procedures.ontology.yaml under defaults/domains/ is found only through a dedicated TenantOntologyManager(ontology_dir=OntologyParser.get_defaults_dir()); ManualGraphLoader must copy ContractGraphLoader.context's `missing entities` check (ProceduresDomainNotLoaded) and never share a manager with the contracts domain.
  *Evidence*: F011, F003

- **AIMessage.images/media/files are List[Path]; pydantic coerces 'https://cdn/x.png' to 'https:/cdn/x.png' and parse_response keeps only entries whose path.exists() is True. Teams renders http(s) images[:3] and data:image/ documents[:5]; Slack renders http(s) images only (no cap); Telegram uses FSInputFile (local); WhatsApp passes str(p).**
  *Implication*: Presigned figure URLs cannot travel through AIMessage.images today. The delivery change is in parser.py (keep http(s) strings) plus a URL-capable field, or a per-channel temp download; four duplicate send paths (telegram L3714-3760, telegram/crew, whatsapp/bridge_wrapper, slack/assistant) must change together.
  *Evidence*: F019, F020

- **ContractsAgent does not use structured_output=ContractAnswer; the model drafts via super().ask() and ContractsAnswerService.answer releases the ContractAnswer after CitationVerifier.**
  *Implication*: ProcedureAnswer needs an explicit release path: copy the producer → verifier → service gate (keeps citations/steps model-free) or use structured_output; the brainstorm's `structured_output=ProcedureAnswer` shortcut is not the shipped pattern.
  *Evidence*: F017, F018

- **There is no `parrot contracts` command; contracts/cli.py is argparse behind `python -m parrot_tools.contracts` with an injected factory. The `parrot` console script is a click LazyGroup fed by cli._lazy_commands / _lazy_extras.**
  *Implication*: `parrot manuals` = a click group in parrot_tools/procedures/cli.py + one entry in _lazy_commands and _lazy_extras (core file change); the argparse pattern cannot be mounted as-is.
  *Evidence*: F018

- **PropertyDef.type is a closed Literal (string,int,float,boolean,date,list,dict) with no item schema; RelationDef.properties has the same shape as entity properties; every schema model is extra='forbid'; no top-level authorization block; rule kinds are target_is_self|target_in_management_chain|has_role|same_department|always.**
  *Implication*: Edge props order:int, quantity:int, role:string, confidence:float, t_start/t_end:float are declarable (declaration only, not enforced). versions[]/steps[] are untyped lists — their validation lives in the Pydantic card, not the YAML. Authorization is per traversal pattern with has_role.
  *Evidence*: F009, F008

- **extract_markdown_per_page(pdf_path) has exactly one caller (builder._extract_node_markdown ← build_page_index ← PageIndexToolkit.import_pdf), returns list[tuple[int,str]], and must never pass pages=. ContractLibrary._to_markdown does NOT use it (raw pymupdf page.get_text()). No code anywhere writes or extracts PDF images; PDFMarkdownLoader.extract_images is dead.**
  *Implication*: Figure extraction is net-new. An images_dir kwarg on extract_markdown_per_page is additive but only reaches import_pdf after threading through build_page_index; a manuals library that copies ContractLibrary._to_markdown gets no images unless it calls pymupdf4llm itself. Image metadata needs a sibling structure, not a change to the (page,text) tuple.
  *Evidence*: F013, F015, F031, F004

- **pymupdf4llm==0.0.27 / pymupdf==1.27.1 expose write_images, image_path, image_format, image_size_limit, dpi, page_chunks; pymupdf.Page has get_image_bbox/get_image_info/get_image_rects. rapidfuzz (3.11) is declared only in the [graphindex] and tools [scraping] extras; bm25s (0.2.14) only in [bookstore].**
  *Implication*: No new heavy dependency, but a `manuals`/`procedures` extra (or reuse of graphindex+bookstore) must be declared so a bare install fails clearly (similarity() already raises with a pip hint).
  *Evidence*: F026, F002

- **transcript_to_blocks yields {id,start_time,end_time,start_seconds,end_seconds,text}; YoutubeLoader (youtube.py, not video.py) uses whisper with word_timestamps=False; VideoUnderstandingLoader produces untimed 'Scene N' labels, never passes offsets or model=; offsets/structured_output exist only on GoogleGenAIClient.video_understanding.**
  *Implication*: bm25s step↔block alignment has the timed input it needs from whisper blocks; the Gemini scene path is not usable for timecodes without calling the client directly with structured_output; the loader's model= omission is a latent bug to fix or avoid.
  *Evidence*: F025

- **ask_to_image exists on AnthropicClient, GoogleGenAIClient and OpenAIClient only (ClaudeAgentClient raises NotImplementedError); none accept a URL for image (Path/bytes); AbstractClient has none of these.**
  *Implication*: figures.py must resolve the captioning client by capability (hasattr) and feed local bytes/paths — never AbstractClient typing, never a presigned URL.
  *Evidence*: F023

- **FileManagerInterface.get_file_url(path, expiry=3600) (navigator-api 4.0.0) — not expiry_seconds; OverflowStore caps at 7 days; LocalFileManager returns a file:// URI.**
  *Implication*: Presign per answer with a short expiry; guard non-http(s) schemes before handing URLs to Teams/Slack; local dev needs a temp-download route.
  *Evidence*: F024

- **TaskMemoryToolsMixin step dicts are {label,title,description?,required?,depends_on_labels?}; update_step requires expected_revision and a status in a fixed set, and completing a step passes evidence validation; TaskScope includes session_id.**
  *Implication*: Guided mode maps cleanly onto begin_task/update_step/recall_task, but 'resume tomorrow' across sessions needs select_task/the durable association store, and 'listo' must satisfy the CompletionPolicy (evidence refs) — verify in the spec.
  *Evidence*: F021

- **EpisodicMemoryStore.record_episode takes closed EpisodeCategory/EpisodeOutcome enums (7/4 members) plus free-form metadata; the pgvector column is VARCHAR(32).**
  *Implication*: 'procedure_completed' is either a new enum member (core change) or WORKFLOW_PATTERN + metadata={procedure_id, step_key}; the latter needs no core change.
  *Evidence*: F022

- **OntologyRefreshPipeline._refresh_entity soft-deletes every node missing from an extraction and passes only fields= (no entity); ContractCardDataSource infers the entity from key fields and contracts publishes through its own loader, not the pipeline.**
  *Implication*: ManualCardDataSource needs its own ENTITY_ROUTING_ORDER (step_id → Step, part_id → Part, …, manual_id → Manual) and the graph loader, not the refresh pipeline, is the write path.
  *Evidence*: F012, F006

- **ContractCatalogStore has 40 abstract methods (parties, answers, deltas, relations, outbox); Postgres FTS is 'english'-only; Citation/EvidenceRef hardcode contract_id; test doubles (FakeGraphStore, FakeAdapter, FakeIndexer, InMemoryContractCatalog) live inside test modules.**
  *Implication*: ManualCatalogStore is a cut-down protocol (cards, versions, search, queue, outbox) with a configurable regconfig; evidence/citation models are copied with manual_id unless the generic primitives move to a shared module; test doubles should move to a shared support module before a manuals suite imports them.
  *Evidence*: F005, F001, F006, F007

- **knowledge/contracts had a 20-commit FEAT-539 burst on 2026-09-09/10 and FEAT-539 is still open (TASK-3056); FEAT-540 (13 pending) will make knowledge/ontology/__init__.py a PEP 562 lazy root; FEAT-600 touches only knowledge/wiki; nothing on the FEAT-601 seams changed since the brainstorm's verification point d2244e5.**
  *Implication*: Import ontology symbols from submodules (schema/graph_store/tenant), not the package root; expect the contracts template to still move while FEAT-539 closes; no rebase risk from FEAT-600.
  *Evidence*: F027, F028, F029

- **StepsBlock/ChecklistBlock already exist as display-only infographic models re-exported from parrot.models; every ManualCard/Procedure/ProceduresToolkit/guided symbol is absent.**
  *Implication*: New procedure models must use distinct names (Step, ProcedureStep — not StepsBlock); everything else is greenfield inside existing packages.
  *Evidence*: F030

### 2.3 Recent History (Relevant)

| Area | Window | Activity | Evidence |
|------|--------|----------|----------|
| `knowledge/contracts` | 60 days | 20 commits — the FEAT-539 contracts-card-ontology burst on 2026-09-09/10 (TASK-3025…3040 + fixes + black); nothing since 2026-09-10 | F027 |
| `knowledge/ontology` | 60 days | 12 commits — FEAT-449 legal ontology views (2026-08-23/27), graphindex Arango (2026-08-10/16) | F027 |
| `knowledge/pageindex` | 60 days | 2 commits — quiet | F027 |
| `models/responses.py`, integrations | 90 days | warm — Telegram `/add_mcp` gating (2026-09-23), FEAT-591 speech models, FEAT-551 Teams formdesigner card submits (2026-09-15), a2ui-v1 Adaptive Cards (2026-08-29) | F028 |
| Drift `d2244e5..HEAD` | 15 commits | only `knowledge/wiki/*/bookstore.py` and planogram pipelines touched under `packages/`; no FEAT-601 seam changed since the brainstorm's verification point | F028 |
| In-flight SDD | now | FEAT-539 open (TASK-3056 in-progress, TASK-3054 done-with-issues); FEAT-540 graphindex-core-seams pending (13 tasks, makes `knowledge/ontology/__init__.py` a PEP 562 lazy root); FEAT-600 sql-schema-plane touches only `knowledge/wiki` | F029 |

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- packages/ai-parrot/src/parrot/knowledge/manuals/: models.py (ManualCard, Procedure, Step, PartRef, ToolRef, Hazard, MediaRef, Tip, ManualVersion, ProcedureCitation, ProcedureAnswer — importing Evidence/Extracted/FieldProvenance/trim_quote; copying Citation/Version/Answer with manual_id), carding.py (header pass + procedure pass + deterministic assemble_card; imperative-verb/numbered-list density replaces deontic_density), figures.py (pymupdf4llm write_images + Page.get_image_bbox, caption regex pairing, capability-resolved ask_to_image captioning, FileManagerInterface upload), video.py (transcript_to_blocks → bm25s alignment → judged tail with judgement log/--force), library.py (ManualLibrary copying ContractLibrary's staged tree flow, calling pymupdf4llm directly for figures), catalog.py + catalog_postgres.py (ManualCatalogStore, cut-down protocol, configurable FTS regconfig), datasource.py (ManualCardDataSource with its own ENTITY_ROUTING_ORDER, registered as 'manualcard'), graph_loader.py (ManualGraphLoader: EdgeSpec with origin, owned collections exclude tip/has_tip/authored_by OR origin-filtered obsolete/reconcile/retract; Tip re-link by step_key → content-hash ≥0.9 → orphaned=true)
- packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/procedures.ontology.yaml (extends base; Equipment/Manual/Procedure/Step/Part/Tool/Hazard/Media/Tip; typed edge props; Tip→authored_by→Employee via field_match; per-pattern has_role authorization; procedure_steps / procedure_prerequisites / procedures_for_equipment / step_detail / equipment_sharing_module / procedure_in_force / tips_for_procedure patterns filtering active and _active)
- packages/ai-parrot-tools/src/parrot_tools/procedures/: retrieval.py (ProcedureRetrieval with its own trigger table + hybrid equipment resolution + PageIndex fallback; procedures-shaped _validate_projection), toolkit.py (ProceduresToolkit(TaskMemoryToolsMixin?, AbstractToolkit), tool_prefix='proc', confirming_tools={add_tip, verify_procedure}), service.py + verifier.py (producer → citation/step verifier → released ProcedureAnswer), agent.py (ProceduresAgent(Agent) creating the toolkit before super().__init__), cli.py (click group `manuals` mounted via cli._lazy_commands)
- Media delivery: URL-capable path through parse_response/ParsedResponse (or per-channel temp download) so presigned figure URLs reach Teams/Slack and files reach Telegram/WhatsApp — decided by spike 2 (U1)
- Guided mode over begin_task/update_step/set_resume_hint/recall_task with cross-session resume via select_task/association store; completion episodes via record_episode(category=WORKFLOW_PATTERN or new member, metadata={procedure_id, step_key})
- A `manuals` optional-dependency extra bundling pymupdf/pymupdf4llm/rapidfuzz/bm25s

### What Changes

- packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py — additive images_dir kwarg forwarding write_images/image_path/image_format/dpi; page-image metadata returned via a sibling structure, (page,text) contract untouched, never pages= (F013)
- packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py + toolkit.py — thread images through build_page_index/_extract_node_markdown/import_pdf only if the PageIndex path is used for manuals (F013)
- packages/ai-parrot/src/parrot/models/responses.py — URL-capable media field (image_urls/media_urls) or Path|str widening, behaviour-preserving for Path (F019)
- packages/ai-parrot-integrations/src/parrot/integrations/parser.py — keep http(s) strings in ParsedResponse.images/media; plus msteams/slack/telegram/whatsapp wrappers and their duplicate send paths (F019, F020)
- packages/ai-parrot/src/parrot/cli/__init__.py — `manuals` entries in cli._lazy_commands and cli._lazy_extras (F018)
- packages/ai-parrot/src/parrot/memory/episodic/models.py — optional new EpisodeCategory member (only if U-decision rejects metadata-only) (F022)
- packages/ai-parrot/pyproject.toml — new extra (F026)
- packages/ai-parrot/src/parrot/knowledge/contracts/models.py + carding.py — only if U2 moves the generic primitives (Evidence/Extracted/FieldProvenance/trim_quote/_quote_supported/_validate_extracted) into a shared module and re-exports them (F001, F002)

### What's Untouched (Non-Goals)

- OCR for scanned/image-only manuals (PDFLoader skips such pages; ImageLoader path is a follow-up)
- Exploded-view callout → Part mapping via vision structured output (v2)
- Serial-range applicability on Step (v2)
- Offline/per-device viewer
- Generic OntologyToolkit exposing traversal patterns to any agent
- Re-hosting vendor video; keyframe extraction
- Touching OntologyRefreshPipeline semantics (the loader is the write path, as contracts)
- Admin UI curator view (follow-up, same shape as the contracts verification queue)

### Patterns to Follow

- Bounded 1+N carding: deterministic node selection → ask_structured(temperature=0.0, system_prompt) → verbatim-quote validation → fallback draft (F002)
- EdgeSpec.document() carrying _from/_to + source_id/target_id/kind; remove+recreate on property change; verify read-back before published=True (F003, F010)
- Dedicated TenantOntologyManager(ontology_dir=get_defaults_dir()) + DomainNotLoaded startup check (F011, F003)
- Deterministic substring-trigger planner failing closed to Clarification; per-tool _gate() authorize; confirming_tools for writes (F016, F017)
- producer → CitationVerifier → service.release gate; agent creates its toolkit before super().__init__ (F017, F018)
- Bookstore judgement log + --force for the LLM-judged alignment tail; origin-tagged relations so re-judging replaces only LLM edges (F014)
- Contracts test doubles: FakeGraphStore (create_edges no-update), FakeAdapter, FakeIndexer, corpus/text_pdf/image_only_pdf fixtures (F007)
- ChartData.public_url as the existing URL-media precedent in the channel layer (F019)

### Integration Risks

- Tip loss on re-publish if tips share the loader's owned collections without an origin guard (F003) — spike 4 exercises exactly this
- Edge collapse on (_from,_to) for multi-role illustrated_by / multi-context requires_part (F010)
- Silent base-only ontology if the manager is not built with the defaults dir (debug-level log) (F011)
- Media never reaching channels through AIMessage.images (Path coercion + exists() filter); four duplicate send paths (F019, F020)
- FEAT-540 lazy root refactor of knowledge/ontology/__init__.py and FEAT-539 still open on the contracts template (F027, F029)
- Figure→step pairing fidelity unmeasured (brainstorm spike 1) — nothing in the repo constrains it either way
- Presigned URL lifetime ≤7 days in chat history; LocalFileManager file:// in dev (F024)
- Guided-mode completion policy may require evidence refs for 'done' (F021)

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Evidence/Extracted/FieldProvenance/trim_quote are generic and importable as-is; Citation/ContractVersion/ContractAnswer/EvidenceRef are contract-bound and must be copied | F001, F006 | high | models read with line ranges; contract_id fields cited |
| C2 | ContractGraphLoader.publish is whole-catalog reconciliation with no origin filter; tip survival is new work in three places or via non-owned collections | F003, F010 | high | publish/publish_all/_reconcile_edges/retract read; origin appears only in a docstring |
| C3 | create_edges never updates properties and collapses duplicate (_from,_to) pairs | F010, F007 | high | AQL read; FakeGraphStore reproduces it |
| C4 | procedures.ontology.yaml in defaults/domains/ is only resolved through a manager built with ontology_dir=get_defaults_dir(); resolve cache ignores domain | F011 | high | resolve() chain read; contracts and legal both pass the defaults dir |
| C5 | Presigned figure URLs cannot be delivered via AIMessage.images today; Teams/Slack render http(s), Telegram/WhatsApp send local files | F019, F020 | high | Path coercion checked in venv; parse_response exists() filter and all four wrappers read |
| C6 | ContractsAgent releases answers through ContractsAnswerService + CitationVerifier, not structured_output | F017, F018 | high | agent.py/service.py/verifier.py read |
| C7 | No `parrot contracts` CLI exists; `parrot manuals` mounts through cli._lazy_commands/_lazy_extras | F018 | high | cli.py argparse + parrot/cli/__init__.py LazyGroup read |
| C8 | Typed edge properties are declarable in the ontology YAML; list/dict props are untyped; authorization is per pattern with has_role | F009, F008 | high | schema.py and contracts YAML read |
| C9 | No PDF image extraction exists anywhere; extract_markdown_per_page has one caller and ContractLibrary uses raw pymupdf text | F013, F015, F031, F004 | high | grep absence + call chain read |
| C10 | pymupdf4llm 0.0.27 exposes every kwarg the design needs; Page bbox APIs exist | F026 | high | read-only venv probe of the signature |
| C11 | Whisper blocks carry start/end seconds for bm25s alignment; Gemini video scenes are untimed at the loader level | F025 | high | basevideo/youtube/videounderstanding read |
| C12 | Vision captioning must be capability-resolved (Anthropic/Google/OpenAI only, Path/bytes input) | F023 | high | grep over clients + AbstractClient |
| C13 | Guided mode maps onto TaskMemoryToolsMixin; cross-session resume and completion policy need spec-level verification | F021 | medium | tool signatures read; CompletionPolicy and association store not inspected |
| C14 | Only FEAT-539 (closing) and FEAT-540 (lazy ontology root) overlap; drift since the brainstorm touches no FEAT-601 seam | F027, F028, F029 | high | index JSON tallied; git log d2244e5..HEAD listed |
| C15 | Option B (procedure graph copying contracts) remains the right architecture after re-grounding | F002, F003, F016, F017, F014 | medium | every template exists and is line-anchored, but six brainstorm claims about the template were wrong and figure pairing is unmeasured |
| C16 | Figure→step pairing reaches ≥80% correct primary figure on captioned figures | — | low | asserted by the brainstorm spike gate; no measurement or corpus in the repo |

Distribution: **13** high, **2** medium, **1** low.

> Overall confidence is **medium**, bounded by C15 (the architecture holds, but the template behaved differently from the brainstorm in six places) and C16 (figure→step pairing is unmeasured). The high-confidence claims are all about *what exists*; the medium ones are about *what will work*.

---

## 5. Open Questions

### Resolved (during proposal phase)

_None — this run was autonomous (no interactive gate); nothing was asked._

### Unresolved (defer to spec / implementation)

- [ ] **Media delivery route: extend parse_response/ParsedResponse to keep http(s) strings plus an `image_urls`/`media_urls` field on AIMessage (Path fields untouched), or widen images/media to Path|str, or download each figure to a temp Path per answer (Telegram/WhatsApp only)?** — *Owner*: Jesus
  *Blocks claims*: C5
  *Plausible answers*: a) new URL fields + parse_response keeps http(s) strings; wrappers render URLs (Teams/Slack) or download-then-send (Telegram/WhatsApp) — recommended · b) widen images/media to List[Path|str] and teach parse_response/the four wrappers · c) temp-download only; Teams/Slack get a caption line (no inline figure)

- [ ] **Shared evidence primitives: import Evidence/Extracted/FieldProvenance/trim_quote from knowledge/contracts/models.py, or move them (and promote _quote_supported/_validate_extracted) to a shared knowledge/common module now that there are two consumers, with Citation/EvidenceRef gaining a doc_id?** — *Owner*: Jesus
  *Blocks claims*: C1
  *Plausible answers*: a) import from contracts in v1; move in a separate tiny PR (recommended) · b) move first (own PR), then build manuals on the shared module · c) copy the primitives into manuals/models.py

- [ ] **Tip protection strategy: keep Tip nodes + has_tip/authored_by edges in collections outside ManualGraphLoader's owned set (never reconciled), or stamp origin on every node/edge and add origin guards in the obsolete/reconcile/retract steps?** — *Owner*: Jesus
  *Blocks claims*: C2
  *Plausible answers*: a) non-owned collections for technician content + explicit re-link step by step_key (recommended, smallest loader delta) · b) origin-guarded loader over shared collections · c) both: non-owned collections and origin stamps for auditability

- [ ] **ProcedureAnswer release path: copy the contracts producer → CitationVerifier → AnswerService gate (agent drafts prose only), or use structured_output=ProcedureAnswer with model validators copying steps/media/citations from RetrievalResult?** — *Owner*: Jesus
  *Blocks claims*: C6
  *Plausible answers*: a) copy the service gate (recommended — steps/media/hazards are never model-authored by construction) · b) structured_output with validators · c) hybrid: structured draft, service verifies and releases

- [ ] **Authorization granularity for traversal patterns: tenant-wide has_role: technician on every pattern, or per-Equipment allowlists via an Employee → certified_for → Equipment relation?** — *Owner*: Jesus
  *Blocks claims*: C8
  *Plausible answers*: a) has_role: technician tenant-wide in v1 (recommended) · b) certified_for relation + per-pattern rule from day one · c) has_role in v1 with the relation reserved in the YAML

**Carried over from the brainstorm (not re-asked; go to spec §8 as-is):** card granularity (one `ManualCard` per document with `procedures[]` vs `ProcedureCard`), vision provider for captioning (Anthropic/Google/OpenAI — capability-resolved per F023), figure storage (`S3FileManager` vs overflow store — note the 7-day presign cap, F024), guided-mode state owner (`TaskMemoryToolsMixin` composed into `ProceduresToolkit`), tips moderation, serial/model-year applicability, offline use, exploded-view callouts (v2).

**Follow-up research the spec should do** (answerable from the repo, so not asked here): the task-memory `CompletionPolicy` and association store for cross-session guided resume (F021); `OntologyMerger` behaviour for `extends: base` (F011); `test_dependency_boundary.py` import guards a `knowledge/manuals` package must satisfy (F007); whether Google `image_understanding(images: str)` accepts a URL (F023).

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-601`** — *Rationale*: Every reuse target is line-anchored and Option B was already selected in the brainstorm; the research corrected six template claims (publish semantics, origin filter, structured_output, CLI, media path, YoutubeLoader location) which the spec must encode, and the remaining unknowns (U1–U5) are owner decisions that the spec's Open Questions capture. Keep the brainstorm's spike gate as the spec's first milestone (figure pairing, media round-trip, video alignment, tip survival) since none of the four is answerable from the repo.

The spec should make these six corrections explicit (each contradicts the brainstorm's Code Context):

1. `ManualGraphLoader` does not "extend an `origin=='manual'` filter" — none exists; tips live in non-owned collections or the loader gains origin guards in three places (F003, U3).
2. `ProcedureAnswer` is released by a service gate, not `structured_output` (F017, U4).
3. `parrot manuals` is a click group mounted via `cli._lazy_commands` / `_lazy_extras`, not a copy of the argparse contracts CLI (F018).
4. Media delivery needs a `parser.py` change plus a URL-capable field; the `Path` widening alone does nothing because `parse_response` drops non-existent paths (F019, F020, U1).
5. `procedures.ontology.yaml` needs a dedicated `TenantOntologyManager(ontology_dir=OntologyParser.get_defaults_dir())` and a `ProceduresDomainNotLoaded` startup check (F011).
6. `YoutubeLoader` is in `parrot_loaders/youtube.py`; `VideoUnderstandingLoader` yields untimed scenes, so the video lane is whisper blocks + `bm25s` only, with Gemini `offsets`/`structured_output` called on the client directly if scene timing is wanted (F025).

### Alternatives

- **`/sdd-brainstorm FEAT-601`** — not needed; Options A–D were already weighed and B selected.
- **`/sdd-task FEAT-601`** — no; this is a multi-package, multi-lane feature with a spike gate.
- **Manual review** — only if the owner wants to reconsider Option B in light of the media-delivery cost (C5) before speccing.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-601/state.json` |
| Source (raw) | `sdd/state/FEAT-601/source.md` |
| Research plan | `sdd/state/FEAT-601/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-601/findings/F001-*.md` … `F031-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-601/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (default profile; four parallel read-only research lanes, digests written by the orchestrator):
- Files read: 40 / 40 (raw per-lane total 87, capped at the profile ceiling)
- Grep calls: 25 / 25 (raw 62)
- Git calls: 9 / 10
- Wall time: ~420 s / 300 s (lanes ran concurrently; the ceiling was exceeded by wall clock, not by query count)
- Truncated: **no** — all 31 planned queries executed
- Gates: plan and review gates auto-approved (autonomous session); Q&A skipped, unknowns left in §5

**Mode determination**: `auto` → resolved to `enrichment` (source is an accepted design brainstorm, no defect to localize).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (Claude Fable 5.1, autonomous run) |
