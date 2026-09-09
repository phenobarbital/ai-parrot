---
type: feature
base_branch: dev
---

# Feature Specification: Contracts Card & Ontology

**Feature ID**: FEAT-539
**Date**: 2026-09-09
**Author**: Jesus Lara / Codex
**Status**: draft
**Target version**: Pilot v1 on ai-parrot 1.0.0

Author and target are draft defaults pending review; they do not select a release date.

Inputs: sdd/proposals/contracts-card-ontology.brainstorm.md (authoritative resolved decisions), sdd/proposals/contracts-card-ontology-design.md, sdd/proposals/contracts.ontology.yaml, and sdd/proposals/contracts-agent-definition.md. The resolved brainstorm overrides older SQLite, deferred temporal-plane, single-agent and OCR passages. This spec formalizes those decisions and the verified integration corrections below.

## 1. Motivation & Business Requirements

### Problem Statement

Contract owners cannot reliably answer which agreements require SOC 2, what renews in the next 90 days, who signed an MSA, or which SOWs and amendments belong to it without opening documents individually. Extracted information lacks field-level evidence and a distinction between machine extraction and human verification.

The product is a six-week pilot over 50–100 active English-language contracts. Bob remains the decision maker. Acceptance compares the two initial client questions plus Bob's ten common questions against his answers, with citations and approximately two hours of his review time per week.

### Goals

- Build one durable ContractCard and PageIndex tree per source document, keeping the canonical source in SharePoint, OneDrive, shared storage or mail.
- Extract fields and clause-level obligations with provenance; derive dates, status and parent links deterministically.
- Make contract families, parties, signatories, obligations, standards and effective versions queryable through a contracts ontology.
- Support human verification, corrections, party merges, answer retirement and auditable refresh without silently replacing verified facts.
- Provide both a ReAct chat/MCP agent and a fixed, fail-closed answer flow for API/A2A and scheduled answers, sharing authorization and citation verification.
- Deliver Postgres catalog storage, GraphIndex version publication, O365 delta tools, relation judgements and three scheduler-free watcher jobs in v1.
- Keep retrieval deterministic and LLM-free. LLM calls belong to document indexing/carding, explicit relation judgement, optional pre-retrieval closed-set triage, and answer drafting.

### Non-Goals (explicitly out of scope)

- Legal advice, compliance determinations, redline acceptance, automatic contractual decisions or changes to original documents.
- OCR/scanned-PDF ingestion, bilingual analyzers, SQLite backend, generic card-family refactor or changes to base ontology vocabulary.
- Verification UI: belongs to the separate contracts-verification-ui spec.
- New scheduler infrastructure, scheduler imports in the contracts packages, automatic outbound messages, or a new HTTP/A2A transport. This feature supplies callable services for existing transports.

## 2. Architectural Design

### Overview

Core owns the data plane in packages/ai-parrot/src/parrot/knowledge/contracts/. The tools satellite owns toolkit, agents, answer flow and jobs in packages/ai-parrot-tools/src/parrot_tools/contracts/. ContractCard is a sibling of BookCard, not a subclass.

Postgres is authoritative for cards, obligations, verification, versions, aliases, judgements, answer audit and source cursors. PageIndex stores derived searchable text and historical evidence. ArangoDB is a rebuildable ontology projection. GraphIndex Postgres records the temporal graph; its commit time is distinct from contractual effective dates.

### Component Diagram

~~~text
Source adapters / O365 delta tools
             |
       ContractLibrary --> PageIndex current + versioned evidence
             |
       Postgres catalog --> verification / aliases / answer audit
             |
       durable publication queue
             +--> ContractGraphLoader --> contracts ontology in ArangoDB
             +--> GraphIndex GraphUpdate --> temporal Postgres graph

Authorized deterministic retrieval + evidence dossier
             +--> fixed answer flow (API/A2A/reports)
             +--> ReAct ContractsAgent (chat/MCP)
                         |
               shared citation gate --> audited ContractAnswer
~~~

### Integration Points

| Existing component | Integration | Scope |
|---|---|---|
| Bookstore carding helpers | Import slugify, unique_slug, derive_toc and TocEntry | Keep contract-specific sampling and drafts separate |
| Bookstore DOCX conversion | Extract a public async docx_to_markdown(path) helper in bookstore/library.py; existing private method delegates | Preserve conversion, lazy imports and errors |
| PageIndexToolkit / NodeContentStore | Tree ingestion and exact node-body reads | Tenant storage roots and immutable evidence per version |
| OntologyRefreshPipeline / RelationDiscovery | Full-catalog extraction and deterministic field matching | Contracts-local orchestration handles the gaps listed below |
| OntologyGraphStore | Initialize, upsert, traverse, reconcile owned edges | No generic schema or graph-store API change required |
| AuthorizationChecker | Evaluate YAML rules before protected reads | Shared entry gate across SQL, tools, graph and answer paths |
| PostgresPersistence | apply_update with GraphUpdate | Separate per-tenant schema and recoverable publication |
| O365Tool / O365Client | Two new drive-delta tools | Existing authenticated Graph client; no provider SDK introduced |
| AbstractToolkit / Agent | Contracts-prefixed tools, confirming writes, ReAct answer producer | Tools satellite only |
| Legal librarian flow | Pattern precedent for draft and deterministic verification | Its crew builder is inspection-only; implement a tested executable contracts runner |

### Data Models

Implement Pydantic v2 models with typed fields, closed taxonomies and JSON round trips. The source design §1 and §1.1 supplies the field vocabulary; the following is the normative contract, including corrections.

| Model | Required shape and invariants |
|---|---|
| ContractType | msa, sow, nda, dpa, amendment, order_form, license, sla, other |
| ContractStatus | draft, active, expired, terminated, superseded, unknown |
| PartyRole | customer, vendor, partner, affiliate, us, other |
| ObligationKind | compliance, insurance, data_protection, security, sla, audit_right, reporting, payment, confidentiality, termination, notice, deliverable, other |
| Verification / ProvenanceOrigin | extracted, verified, stale / llm, rule, manual; these are independent axes |
| FieldProvenance | origin; optional node_id, physical page, confidence in [0,1], verified_by, verified_at; quote at most 300 characters; explicit verification state for unambiguous field-state transitions |
| Party | party_id, name, role=other, is_us=false; at most one is_us party on a card |
| Signatory | person_id, name, optional title, signed_on, employee_id; party_id must resolve to a card party |
| TermSpec | effective_date, expiration_date, initial_term_months, auto_renew=false, renewal_period_months, notice_days, notice_deadline, next_renewal_date; nonnegative periods, positive renewal period when supplied |
| Obligation | obligation_id, contract_id, closed kind, obligor=us/counterparty/both, verbatim text, node_id, optional page/standard_id/due_date/recurrence, verification, provenance |
| ContractVersion | n, valid_from inclusive, valid_to exclusive or null, kind=original/amendment/renewal/restatement, optional amended_by, source_sha256, card_snapshot; additionally recorded_at and evidence reference |
| ContractCard | contract_id == tree_name, title, contract_type, derived status, parties, signatories, term, governing_law, parent_contract_id, supersedes_contract_id, obligations, summary, topics, owner_employee_id, department, language, source_uri, optional temporary source_path, source_sha256, source_format=pdf/docx/md/txt, page_count, toc, toc_digest, field_provenance, verification, verified_by/at, stale_fields, card_origin=llm/fallback/manual, versions, added_at, updated_at |
| Evidence / Extracted[T] | Evidence(node_id, quote at most 300 chars, optional page); typed value, optional evidence, confidence in [0,1]. Use typed generics/concrete fields rather than value: object |
| ContractHeaderDraft | Extracted title/type/term facts/governing law/parent title; evidenced party/signatory drafts; summary/topics/language. No derived status, notice_deadline, next_renewal_date or parent_contract_id |
| ObligationsDraft | List of clause drafts with excerpt/node/page, kind, obligor, standard_name, due_date, recurrence, confidence; assembly adds IDs and provenance |
| Citation | contract_id, title, node_id, optional page, nonempty quote, verification; add version_n and source_sha256 so historical node IDs cannot resolve to current text accidentally |
| HandoffBrief | question, why_judgment, located_clauses, related_contracts, suggested_owner |
| ContractAnswer | answer_kind=lookup/interpretation_required/not_found/out_of_scope/denied; optional answer, citations, provenance=verified/mixed/extracted, optional handoff and pattern |
| AnswerRecord | answer_id, asked_at, authenticated user, question, answer_kind, pattern, citations, authorization outcome, retirement actor/time/reason |
| PublicationRecord | tenant-bound contract/version/revision key, immutable payload, target states, receipts, attempts and last error; queue rows are durable |
| DeltaPage / IngestReport | Source item identities and tombstones, next link or final delta link; per-file added/updated/skipped/error outcomes with reasons and publication state |

Every extracted field, including nested party/signatory and obligation fields, has a stable provenance path. An absent or invalid quote caps extraction confidence at 0.5 and prioritizes verification; it cannot substantiate a released citation. Rule-derived fields identify their input paths. Summary prose is not evidence.

CardVersion snapshots omit their own versions list to avoid recursive growth. Initial ingestion creates the original snapshot. Later changes preserve the previous snapshot and add the resulting revision; contractual amendments update the base contract's version history when a verified effective date and parent link exist. Unknown effective dates stay unresolved instead of becoming today's date. Administrative corrections have a new recorded revision and must not fabricate a new contractual effective interval.

### Carding, verification and refresh

1. Validate format and source, obtain bytes in temporary storage, compute SHA-256 and resolve existing source_uri before allocating a slug. Unchanged content returns skipped. In this pilot, duplicate content at another URI resolves to the existing card; retain the original canonical URI and report the duplicate source.
2. Build a PageIndex tree in a staging storage root. Preserve the current published tree until the new card/evidence pair is complete. Do not copy Bookstore's delete-before-reimport refresh behavior.
3. Select cover/preamble, term/duration/renewal/termination/notice/governing-law/definitions/parties/scope nodes and signature block. Fallback selects first, last and three nodes densest in shall/must/agrees to. Header material is capped at 12,000 characters.
4. One structured header call, then at most max_obligation_sections calls (default 12), ordered deterministically by title/body criteria and deontic density. This 1+N bound excludes PageIndex indexing and explicit relate calls.
5. Assemble IDs, standard aliases and derivations in Python. Parent resolution uses same counterparty, compatible governing type (v1 SOW/order_form to MSA; amendment to referenced base) and normalized rapidfuzz similarity at least 0.85; multiple qualifying candidates leave parent null and stale_fields populated.
6. notice_deadline = expiration_date minus notice_days when both exist; next_renewal_date = expiration_date when auto_renew. Status precedence follows D3: incoming supersedes, explicitly human-confirmed termination with elapsed due date, expired non-renewing term, active effective term, unsigned draft, otherwise unknown. Add an explicit manual termination confirmation field; never infer termination merely from a termination clause. Inject today into derivations.
7. No-LLM or failed carding uses filename/type/date heuristics, confidence 0.3, card_origin=fallback and no invented obligations. For TXT/heading-less inputs and text PDFs, provide deterministic sectioning with page anchors when model-dependent indexing is unavailable. No-text PDFs are skipped with a reason, not returned as empty successful cards.
8. verify_card with fields=None verifies the whole current card; a field map verifies/corrects only those fields. Stamp verified_by/at; origin becomes manual only for corrections. Only mark the card verified when required evidence gaps, low-confidence unverified fields and stale_fields have been resolved.
9. On refresh compare SHA-256 of nonempty exact evidence quotes for each previously verified field. Preserve unchanged verified values; changed/missing evidence retains the prior value, records the candidate separately and marks the field stale pending review. Empty quotes never prove unchanged evidence. Rebind unchanged evidence to the new node when valid.
10. Persist card, obligations, version/revision and publication work transactionally. Archive derived evidence by tenant/contract/version/hash so older citations remain checkable. Only discard failed staging data, never current evidence or original documents.

### Postgres catalog and tenancy

ContractCatalogStore is async and tenant-bound at construction; methods never accept model-supplied tenant identifiers. PostgresContractCatalog uses an injected or owned asyncpg pool, idempotent DDL, validated schema identifiers and parameterized values. Use a separate configured schema per tenant for both catalog and temporal plane. A shared bare contracts schema is acceptable only for a single-tenant deployment.

| Table | Data / indexes |
|---|---|
| contracts | contract_id PK, card_json JSONB, unique source_sha256 and source_uri, typed status/type/dates/verification/owner/department, updated_at, revision; English search_vector with GIN; B-tree date/status/verification indexes |
| obligations | obligation_id PK, contract_id FK, kind, standard_id, obligor, due_date, recurrence, verification, text, node_id, page, provenance; replace one contract's set atomically |
| contract_versions | contract_id + version/revision identity, effective interval, recorded_at, amendment/source hash, snapshot and evidence reference; retain prior revisions |
| party_aliases | normalized alias PK, canonical party_id, actor/time; conflicting aliases produce review errors |
| contract_answers | audit record, citations JSONB, authorization JSONB and retirement fields; retain denials and empty answers |
| source_delta_tokens | source_uri PK, committed opaque token/link, timestamp; tenant/source identity is fixed |
| source_items | source + drive + item identity, current URI, contract_id, hash, tombstone; allows rename/deletion handling without guessing |
| relation_judgements / contract_relations | candidate/version hashes, outcome including none, relation kind, confidence, rationale, model/time and origin; preserve judgement history on force |
| publication_outbox | unique contract revision and target, payload, state/receipt/errors; supports retry and crash recovery |

upsert atomically writes the card, replaces its obligation set, appends history and enqueues publication. Optimistic revision checks reject stale verify/refresh writes. Slug uniqueness is enforced in SQL, not only by taken_slugs.

search uses English tsvector, plainto_tsquery and ts_rank. expiring uses inclusive date windows, active cards, and notice deadline with expiration fallback; omit null dates. verification_queue orders missing evidence then low-confidence unresolved fields, then remaining stale cards with stable ID tie-breaks. Reports query SQL and do not require ArangoDB.

Party merge updates current cards, signatories, alias mappings and queued projections in one transaction; preserve historical snapshots and reject invalid self-merges/unknown identities. Rebuild shared Party aliases across all cards.

Retirement suppresses every cited (contract_id, node_id) pair in that tenant from future lookup and handoff evidence, following the resolved design's deliberately broad suppression rule. Version/hash remains audit metadata; a refresh must not evade retirement by merely renumbering an unchanged excerpt. Invalidate answer caches and carry suppressions forward through evidence mapping.

### Ontology projection and verified design corrections

Ship the proposed contracts YAML under ontology/defaults/domains/ with five domain entities, the original eleven relations, ten domain patterns and one English search view. Add conflicts_with (Contract to Contract, symmetric interpretation) and references_obligation (Obligation to Obligation, cross-contract). Both have origin=llm edge properties and no discovery rules. Expected base merge: 8 entities, 16 relations, 13 patterns.

ContractCardDataSource subclasses ExtractDataSource and registers as contractcard. Inject the tenant-bound catalog via source config. Entity inference must test obligation_id first, then person_id, then party_id, then contract_id: the requested field sets overlap, contrary to the brainstorm's disjoint-fields assumption. Reject an unrecognized/ambiguous field request. Return ISO dates, embedded plain version dicts, denormalized counterparty names and catalog-wide Party aliases. Seed all eight ComplianceStandard IDs before discovering requires edges.

The contracts loader retains the legal domain's pipeline architecture with these required corrections:

- publish_all uses a complete, prevalidated catalog snapshot through OntologyRefreshPipeline.run(tenant_id, domain="contracts"). A contracts-local wrapper limits the refresh context to the contracts domain sources, retaining base Employee/Department as existing targets; it must not accidentally refresh unrelated base sources.
- The existing pipeline has no per-card filter argument and soft-deletes anything absent from a full extraction. Therefore v1 publish(card) safely delegates to a full catalog publish under the tenant lock. Standalone datasource filtering remains available, but is never fed as a partial snapshot to the generic diff.
- Pre-extract all domain entities before graph mutation and reject extraction errors. After node synchronization, run a complete deterministic field-match reconciliation so relations to later-loaded targets are discovered on the first publish.
- Reconcile both scalar and property-carrying edge sets. create_edges inserts/skips by endpoints and does not update properties or remove obsolete edges. Changes to owner, parent, party, standard or signatory must remove the old edge before creating the new one.
- Written edges carry _from/_to plus source_id/target_id/kind matching the generic removal helpers. Discovery returns only _from/_to: the loader must normalize those edges before cleanup, and use endpoint-scoped reconciliation for any edges created by the pipeline without the extra fields. All cleanup is restricted to the feature-owned collections and intended source IDs.
- party_to carries role; signed_by carries signed_on/on_behalf_of; amends is only written for an amendment with resolved parent; supersedes requires an explicit supersedes_contract_id. Contract family deduplicates by contract identity, not the entire relation/depth object.
- Retract marks the contract and its obligations inactive, removes incident feature edges and queues temporal tombstones; retain catalog history, audit and evidence. Do not delete shared parties/people still referenced elsewhere.
- All domain AQL patterns filter inactive contracts/obligations/endpoints. The proposal currently lacks these guards. Validate graph-owned card revision against the authoritative catalog before using its answer payload.
- TenantOntologyManager caches by tenant rather than (tenant, domain). Use a dedicated contracts manager with explicitly configured ontology_dir and fail startup if the contracts domain was not loaded.
- Publication errors are observable and retryable. Existing graph helpers and RefreshReport do not provide a transaction across collections. Never claim atomic publication or success based only on an empty errors list: verify the intended node/edge sets before marking a revision published. Queries reject incomplete/stale projections.

LLM relation judgement runs at ingest/relate time only. Candidate sets use shared counterparty/family/obligation kinds; one bounded structured call per source contract per batch; enforce max_candidates and deterministic ordering. Log all outcomes including none; reject unknown/self/cross-tenant endpoints. Canonicalize symmetric conflicts pairs and traverse either way. Refresh invalidates edges based on outdated source hashes; no automatic re-judgement during retrieval. --force creates a new judgement record and replaces the active result.

### Temporal publication

For each card revision publish a GraphUpdate with a stable node_id such as contracts:contract:<contract_id>, kind=NodeKind.DOCUMENT, canonical source_uri and domain_tags containing contract identity, card version/revision, snapshot and effective interval. Use existing enum values; do not add NodeKind.CONTRACT or custom EdgeKind members. Historical values must be present in versioned node content, not only in a mutable external reference.

PostgresPersistence.apply_update owns its own transaction and creates a fresh commit ID; sharing an asyncpg pool does not make it atomic with catalog upsert. Use the durable outbox and a stable run_id per revision, serialize publication per tenant, and recover an acknowledged-or-unknown commit by list_commits(run_id=...) plus get_commit validation before retry. Record the receipt; do not emit duplicate logical versions after a crash.

Use separate schemas per tenant: the existing temporal reads do not enforce isolation merely because a TenantContext is passed. graph_as_of/history/diff show recorded graph history; contract_in_force selects contractual validity from embedded effective intervals. Document the distinction with an amendment recorded after its effective date. No global graph revert is exposed through the contracts toolkit.

### Answering and authorization

Both paths use one ContractsAnswerService and one deterministic retrieval implementation. Closed-set triage precedes retrieval; evaluative/deontic requests such as should we, can we, is X compliant, accept the redline produce interpretation_required. Located clauses may be retrieved after authorization to populate a handoff, but neither agent adjudicates the request.

A structured pre-triage call, when enabled, sees only the question and cannot generate AQL or expand permissions. Retrieval itself receives typed pattern/entity/date parameters and has no LLM client. Rule-based triage handles supported explicit patterns without a model; uncertain classification fails closed.

| Pattern | Explicit values bound by the contracts layer |
|---|---|
| contracts_requiring_standard | standard_id, statuses (default active) |
| expiring_within / notice_deadlines_within | today, until |
| contracts_with_party | party_id |
| contract_family / signatories_of | contract_id |
| obligations_of_contract | contract_id, kind (explicit null when absent) |
| contract_in_force | contract_id, as_of |
| my_contracts | authenticated Employee graph _id |
| search_contracts | query, bounded top_k |

Match the most specific trigger deterministically. Resolve standard aliases over the full question so a trigger containing SOC 2 does not erase the entity. Resolve parties and contract IDs/titles from the authorized catalog with exact/alias/fuzzy matching and optional configured non-generative vector ranking. Ambiguous matches return a clarification response at the service boundary, not an invented new ContractAnswer kind.

Do not use EntityResolver.hybrid_concept_match unchanged: it targets Concept instances/vector namespace and optionally calls an LLM. Do not route contracts through unmodified OntologyRAGMixin.ontology_process: it resolves entities before authorization and passes full _id values to binds where the proposal expects _key. The contracts adapter explicitly maps catalog IDs to the declared collection, supplies every bind and executes only allowlisted YAML patterns. No dynamic AQL or LLM fallback.

Read patterns use YAML contract_reader OR contract_owner, default deny. my_contracts additionally requires an authenticated identity and applies the management-chain restriction to returned contracts and subsequent section reads. All directly callable SQL tools enforce the same read policy; owner-only verify/merge/retire operations require authenticated actor and transport confirmation. Client/model-supplied roles or tenant names never grant access. Scheduler jobs run with a configured service principal and recipient scope.

Before release, load the exact versioned node body; a citation must belong to this request's authorized dossier, not be retired, have nonempty quote found verbatim in that body, and match the stored version/hash/page. Derive citation title/page/verification from evidence rather than trusting model output. Unknown/stale evidence is pruned. Prune the claims supported only by removed citations as well; a free paragraph cannot survive because another unrelated citation passed. Zero surviving lookup citations becomes not_found.

lookup requires answer text and at least one citation; interpretation_required requires a handoff and no judgment answer; denied/out_of_scope/not_found carry no fabricated answer or evidence. Top-level provenance is verified only when all citations are verified, mixed when verified and unverified citations coexist, otherwise extracted; stale citations remain visibly stale. Use extracted for empty evidence as the conservative existing enum value.

Persist every outcome before releasing it, including denied and failed-verification outcomes. If audit persistence is unavailable, return a transport/service failure instead of an unaudited answer. Streaming must buffer any substantive answer until authorization, citation checks and audit complete.

### New Public Interfaces

All interfaces below are NEW; signatures are design contracts, not existing imports.

| Module / interface | Contract |
|---|---|
| core catalog ContractCatalogStore | async upsert(card), get(contract_id), find_by_sha(sha256), find_by_source_uri(uri), list_cards(*, status=None, verification=None), search(query, top_k=8), expiring(*, until, key), verification_queue(*, limit=50), taken_slugs(), remove(contract_id) |
| Additional catalog methods | async merge_parties(keep_party_id, merge_party_id, *, user), party_aliases(party_id), record_answer(record), retire_answer(answer_id, *, user, reason), retired_citations(), get_delta_token(source_uri), set_delta_token(source_uri, token); typed obligation-window, source-item, judgement and outbox operations |
| ContractLibrary | async add_contract(source, *, source_uri, force=False), add_folder(folder, *, recursive=False, force=False), verify_card(contract_id, fields, *, user, expected_revision), refresh_card(contract_id, *, source=None), relate_contracts(contract_ids=None, *, force=False); ingest returns card-or-null + added/updated/skipped and an explicit reason in the report |
| ContractGraphLoader | async publish_all(), publish(card), retract(contract_id); report includes partial/unavailable target state and errors |
| ContractsAnswerService | async answer(question, *, request_context, parameters=None) -> ContractAnswer or typed clarification; async retire_answer(answer_id, *, request_context, reason) |
| ContractsToolkit | name=contracts, tool_prefix=contracts; catalog_search, get_card, get_toc, read_section, obligations, expiring, verification_queue, related_contracts; confirming verify_card and retire_answer |
| verify_card tool | Typed operation for field verification/correction, party merge or owner override; actor from trusted request context |
| ContractsAgent | ReAct producer using the toolkit and shared service release gate; never release its raw model draft |
| answer flow | Executable async runner with deterministic retrieval, enumerated dossier, one stateless structured draft, verifier and audit; build an inspectable crew only if useful, not as a substitute for the runner |
| Watcher jobs | async renewals_report(...), obligations_digest(...), ingest_delta(...); dependencies, principal, dates and source configs injected |
| CLI | python -m parrot_tools.contracts: add, add-folder, refresh, verify, merge-parties, queue, search, relate --force, publish, retire-answer; destructive/admin operations explicit, no automatic sends |

### Delta ingestion and watchers

Add DeltaSharePointFilesTool and DeltaOneDriveFilesTool using O365Tool._execute_graph_operation and the authenticated O365Client.graph_client. Use drive-level delta plus local folder filtering and stable drive/item IDs. Expose typed pages, deleted-item markers and opaque continuation/final links. Follow nextLink until deltaLink and restart enumeration on 410 Gone; these are the Microsoft Graph v1.0 semantics. [Microsoft driveItem delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)

The contracts ingestion consumer advances its committed final cursor only after all items have been durably processed or explicitly recorded as skipped. On failure retain the old cursor for idempotent replay. Record source-item identity for moves/renames; tombstones retract the indexed contract without deleting the original or historical evidence. Unchanged SHA creates no new version. Reset/rescan must not interpret a partial listing as mass deletion. Retry throttling/transient failures with bounded backoff; authenticate continuation requests against the configured Graph endpoint, never an arbitrary supplied host.

renewals_report defaults to daily execution and 30/60/90-day notice/expiration windows with deterministic nonoverlapping buckets. obligations_digest defaults weekly, selecting fixed due dates and recognized recurrence rules in SQL/Python; unrecognized or unanchored recurrence is surfaced for review, not interpreted by an LLM. ingest_delta defaults to deployment scheduling every few hours. Core result sets are deterministic; any natural-language report uses the same fixed draft/verifier/audit flow. The deploying agent handles schedule decorators and send_result callbacks.

## 3. Module Breakdown

All paths are relative to the repository. Each module includes focused tests in its owning package.

| Module | Files to create/modify | Responsibility / dependencies |
|---|---|---|
| M1 Models and standards | packages/ai-parrot/src/parrot/knowledge/contracts/{__init__,models,standards}.py | Core contracts, eight standard IDs/aliases; no tools imports |
| M2 Postgres catalog | packages/ai-parrot/src/parrot/knowledge/contracts/{catalog,catalog_postgres}.py | Async protocol, migrations, transactions, aliases, audit, sources, outbox; M1 |
| M3 Carding and DOCX helper | packages/ai-parrot/src/parrot/knowledge/contracts/carding.py; packages/ai-parrot/src/parrot/knowledge/bookstore/library.py | Typed extraction, deterministic assembly/fallback, public async DOCX helper; M1/M2 protocol |
| M4 Library and evidence | packages/ai-parrot/src/parrot/knowledge/contracts/{library,evidence}.py | Staged ingestion, immutable evidence, refresh/verification, source identity; M1–M3 |
| M5 Ontology integration | packages/ai-parrot/src/parrot/knowledge/contracts/{datasource,graph_loader}.py; packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml | Projection, safe full refresh, edge reconciliation, retract; M2/M4 |
| M6 Temporal publication | packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py | GraphUpdate mapping and recoverable outbox, tenant isolation; M2/M4 |
| M7 Judged relations | packages/ai-parrot/src/parrot/knowledge/contracts/relations.py | Candidates, typed judgement/log, force, invalidation, edge publish; M2/M4/M5 |
| M8 O365 delta | packages/ai-parrot-tools/src/parrot_tools/o365/{delta,sharepoint,onedrive,bundle,__init__}.py | Shared delta models/helper and two tools, exports and bundle registration; independent of contracts |
| M9 Retrieval/tool service | packages/ai-parrot-tools/src/parrot_tools/contracts/{__init__,retrieval,service,toolkit}.py | Authorization, typed binds, SQL fallback, read/admin surfaces; M2/M4/M5 |
| M10 Answer producers | packages/ai-parrot-tools/src/parrot_tools/contracts/{agent,flow,verifier}.py | ReAct and fixed runner, shared citation/claim gate, audit; M9 |
| M11 Jobs and CLI | packages/ai-parrot-tools/src/parrot_tools/contracts/{jobs,cli,__main__}.py | Three jobs, operator commands, transport-ready callables; M6–M10 |
| M12 Packaging/docs | packages/ai-parrot/pyproject.toml; uv.lock; docs/knowledge/contracts.md | rapidfuzz in graphindex extra, installation, source configuration, tenancy, watcher wiring and limitations |

M12 includes regenerating uv.lock for the approved optional dependency. No other dependency or shared-core refactor is preauthorized by this spec.

## 4. Test Specification

### Unit Tests

| Test group | Required cases |
|---|---|
| models | Typed drafts, closed kinds, one us party, tree/card identity, evidence length/confidence, answer-kind validators, nonrecursive snapshots |
| carding | Selection order/caps, one+N calls, no derived fields in prompts, unsupported/empty evidence, deterministic fallback |
| derivations | Notice math, status precedence, manual termination, missing dates, exact expiration boundary, ambiguous parent and rapidfuzz score normalization |
| verification | Partial/all verification, unchanged nonempty quote, empty quote, moved node, changed quote/value, stale candidate retention and concurrent revision rejection |
| datasource | Overlapping entity field sets, ordered routing, all Party aliases, ISO dates, static seeds |
| graph loader | Partial publish does not deactivate other cards, seed-before-discovery, first publish creates every scalar edge, property updates remove old edges, retraction, false-success/readback failure |
| retrieval | All pattern bind sets, _key versus _id, SOC 2 trigger/alias, top_k/status/date validation, ambiguity, inactive filtering, no LLM calls |
| authorization | Missing/forged principal, both read roles separately, owner write role, my_contracts narrowing, direct toolkit bypass attempts, cross-tenant evidence and temporal access |
| citations | Unknown node, wrong version/hash/page, empty/mismatched quote, retired citation, mixed/stale provenance, orphan claim pruning, zero surviving citations, audit failure |
| relation judgement | Candidate membership, symmetric identity, cross-contract obligations, none log, no replay without force, old source hash invalidation |
| delta/jobs | Multipage/empty page, tombstone, duplicate item, rename, 410 rescan, interrupted batch/cursor, retry, no-text skipped report, window boundaries and unknown recurrence |
| agents/CLI | Both producers use same gate; executable flow; confirming tool metadata; no scheduler imports; no send side effects |

### Integration Tests

- Postgres real transactions: card/obligation/version/outbox rollback together; concurrent refresh/verify conflict; aliases merge; retirement suppressions; FTS/date/queue queries; schema isolation.
- PageIndex: MD/TXT/DOCX/text-PDF ingestion, no-LLM fallback, exact physical-page evidence, staged failure preserves old tree; archived citation remains verifiable after refresh.
- ArangoDB: merge/initialize domain and view; execute all ten patterns with real bind values, including first-publish standard links, owner change, retraction, family de-duplication and search results mapped to contracts.
- GraphIndex Postgres: successive versions, late-recorded effective amendment, as_of/history/diff, crash after commit before receipt and recovery without duplicate logical publication; cross-tenant schemas cannot leak.
- End-to-end: fake Graph delta -> carding -> verification -> graph/temporal publish -> both answer shapes -> retire -> refresh -> watcher report.
- Regression: existing bookstore DOCX behavior and O365 bundle tools remain intact.

### Test Data / Fixtures

Synthetic English MSA, SOW, amendment, NDA, contradictory clauses and standard aliases; small PDF/DOCX equivalents, heading-less text and image-only PDF. Two tenants deliberately reuse contract slugs and node IDs. Frozen today/recorded timestamps; fake structured adapters and fake Graph pages; injected failures at each publication boundary.

New tests live under packages/ai-parrot/tests/knowledge/contracts/ and packages/ai-parrot-tools/tests/contracts/, with delta tests in the existing tools test tree. Live Postgres tests use only explicit GRAPHINDEX_PG_DSN and temporary schemas; absent DSN skips only that suite. The existing graphindex test also falls back to default_dsn; this feature deliberately does not silently target that database. Arango integration tests require explicit test configuration. Full feature acceptance requires CI/services to run both live suites, not merely skip them. Store logs in artifacts/logs/.

## 5. Acceptance Criteria

- [ ] AC1 All models and eight standard aliases are validated; no generic BookCard inheritance.
- [ ] AC2 1+N bounded carding, evidence provenance, deterministic derivations, no-LLM fallback and explicit scanned-PDF skip work.
- [ ] AC3 Postgres-only async catalog provides atomic writes, English FTS, SQL windows/queues, tenant isolation and conflict detection.
- [ ] AC4 Verification and refresh never lose verified prior values; historical citations still resolve to immutable evidence.
- [ ] AC5 Domain merges to 8 entities / 16 relations / 13 patterns; all ten contract patterns execute correctly with authorization and inactive guards.
- [ ] AC6 Full and single-card publication reconcile changed/deleted vertices and all relevant edges without deleting unrelated contracts.
- [ ] AC7 Every revision reaches GraphIndex with recoverable commit receipt; recorded-time and effective-time histories are demonstrated separately.
- [ ] AC8 Relations are judged only during explicit ingest/relate, logged including none, invalidated on source changes, and replayed only according to force policy.
- [ ] AC9 O365 delta covers paging, expiry, deletion, rename and retry; interrupted ingest does not advance the committed cursor.
- [ ] AC10 Both answer paths enforce one authorization/evidence/audit gate; invalid/retired/orphaned claims cannot escape through chat, MCP, API, A2A or streaming.
- [ ] AC11 Bob can verify/correct fields, merge parties, override ownership and retire an answer through authorized tool/service/CLI operations with confirmation where applicable.
- [ ] AC12 Three scheduler-free jobs return deterministic scoped data; optional prose passes the fixed answer flow; no implicit delivery occurs.
- [ ] AC13 Focused unit, live integration and affected bookstore/O365 regression suites pass; installation/docs include optional extras and deployment setup.
- [ ] AC14 On a 100-card synthetic fixture, SQL search/queue/window operations have measured warm p95 below 1 second on documented test hardware; record results, excluding network LLM latency.
- [ ] AC15 Pilot acceptance is signed off against Bob's twelve agreed question/answer cases, with citations and explicit handoffs. The operational pilot signoff is distinct from automated test completion.

## 6. Codebase Contract

Verified by source reads on 2026-09-09 at dev a5672c46d (FEAT-539 reservation commit). Paths and signatures below describe existing code only; §2 and §3 explicitly mark new interfaces.

### Verified Imports

These symbols are defined/exported at the cited source locations. Runtime import validation of the ontology parser/merger is recorded separately in the validation log; no claim is made that every optional integration was connected.

| Import | Verified at |
|---|---|
| from parrot.knowledge.bookstore.models import TocEntry | packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:98 |
| from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49 |
| from parrot.knowledge.pageindex.toolkit import PageIndexToolkit | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377 |
| from parrot.knowledge.pageindex.content_store import NodeContentStore | packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197 |
| from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter | packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99 |
| from parrot.knowledge.ontology.parser import OntologyParser | packages/ai-parrot/src/parrot/knowledge/ontology/parser.py:19 |
| from parrot.knowledge.ontology.merger import OntologyMerger | packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:54 |
| from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline, RefreshReport | packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:41 |
| from parrot.knowledge.ontology.discovery import RelationDiscovery | packages/ai-parrot/src/parrot/knowledge/ontology/discovery.py:52 |
| from parrot.knowledge.ontology.graph_store import OntologyGraphStore | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:34 |
| from parrot.knowledge.ontology.authorization import AuthorizationChecker | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:43 |
| from parrot.knowledge.ontology.tenant import TenantOntologyManager | packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92 |
| from parrot_loaders.extractors.base import ExtractDataSource, ExtractedRecord, ExtractionResult | packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:19 |
| from parrot_loaders.extractors.factory import DataSourceFactory | packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:13 |
| from parrot.knowledge.graphindex.schema import GraphUpdate, UniversalNode, UniversalEdge, NodeKind, EdgeKind | packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:233 |
| from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207 |
| from parrot.tools.toolkit import AbstractToolkit | packages/ai-parrot/src/parrot/tools/toolkit.py:257 |
| from parrot.bots import Agent | packages/ai-parrot/src/parrot/bots/__init__.py:2 |
| from parrot_tools.o365.base import O365Tool, O365ToolArgsSchema | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:31 |
| from parrot.interfaces.o365 import O365Client | packages/ai-parrot/src/parrot/interfaces/o365.py:339 |

### Existing Class Signatures and Integration Points

| Existing callable | Exact call shape / constraint | Verified at |
|---|---|---|
| slugify / unique_slug | slugify(text: str) -> str; unique_slug(base: str, taken: set[str]) -> str | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49 |
| derive_toc | derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str] | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:88 |
| Bookstore._docx_to_markdown | async (self, path: Path) -> str; lazy MSWordLoader import, conversion via asyncio.to_thread | packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1073 |
| PageIndexToolkit | async create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]; delete_tree/get_tree take tree_name | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377 |
| insert_markdown | async (self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:692 |
| import_pdf | async (self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None, with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:803 |
| loader_for | (self, tree_name: str) -> Callable[[str], Optional[str]]; synchronous body reader | packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197 |
| ask_structured | async (self, prompt: str, output_type: type, temperature: float = 0.0, system_prompt: Optional[str] = None) -> Any | packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99 |
| OntologyParser.load / OntologyMerger.merge | load(path: Path) -> OntologyDefinition; merge(self, yaml_paths: list[Path]) -> MergedOntology | packages/ai-parrot/src/parrot/knowledge/ontology/parser.py:29; packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:54 |
| ExtractDataSource.extract | async (self, fields: list[str] or None = None, filters: dict[str, Any] or None = None) -> ExtractionResult; list_fields() is async | packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py:70 |
| DataSourceFactory | register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None; get(self, source_name, source_config=None) instantiates name/config | packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py:35 |
| OntologyRefreshPipeline.run | async (self, tenant_id: str, domain: str or None = None) -> RefreshReport; extract(fields=property_names), no filters | packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py:94 |
| RelationDiscovery.discover | async (self, ctx: TenantContext, relation_def: RelationDef, source_data: list[dict[str, Any]], target_data: list[dict[str, Any]]) -> DiscoveryResult | packages/ai-parrot/src/parrot/knowledge/ontology/discovery.py:79 |
| execute_traversal | async (self, ctx: TenantContext, aql: str, bind_vars: dict or None = None, collection_binds: dict[str, str] or None = None) -> list[dict[str, Any]] | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:234 |
| upsert_nodes | async (self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult; copies key field to _key | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:274 |
| create_edges | async (self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int; UPDATE {} on duplicate endpoints | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:372 |
| edges_incident / remove_edge_by_triple | Edges keyed by source_id/target_id/kind, not just _from/_to | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:725; packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:752 |
| AuthorizationChecker.check | async (self, spec: AuthorizationSpec, user_context: dict[str, Any], resolved_entities: dict[str, str], tenant_id: str) -> tuple[bool, str or None]; OR rules | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:62 |
| _check_same_department | DOCUMENT(@target_id).department; matches any target, constructs tenant_id + "_ontology" database | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:293 |
| TenantOntologyManager.resolve | (self, tenant_id: str, domain: str or None = None) -> TenantContext; cache keyed by tenant | packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:92 |
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |
| Toolkit confirmation | tool_prefix: str or None; confirming_tools: frozenset of unprefixed method names; generates requires_confirmation metadata | packages/ai-parrot/src/parrot/tools/toolkit.py:257; packages/ai-parrot/src/parrot/tools/toolkit.py:686 |
| O365Tool._execute_graph_operation | async (self, client: O365Client, **kwargs) -> Any; _execute handles authentication and ToolResult | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:200 |
| O365Client.graph_client | Authenticated GraphServiceClient property | packages/ai-parrot/src/parrot/interfaces/o365.py:339 |
| LegalLibrarianAgent.draft | async (self, enumerated_dossier: str, query: str, as_of: date) -> DraftAnswer; stateless structured output precedent | packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py:79 |
| build_legal_librarian_crew | Inspection artifact; explicitly not executable via run_flow | packages/ai-parrot-tools/src/parrot_tools/legal/librarian/flow.py:494 |
| Bookstore relation patterns | deterministic_relations(cards, *, now, ...), async judge_relations(adapter, card, candidates, *, model_name=""); book-specific models, precedent only | packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py:141; packages/ai-parrot/src/parrot/knowledge/bookstore/relations.py:372 |
| GraphIndexToolkit temporal tools | async graph_as_of(timestamp), graph_concept_history(concept_id), graph_diff(concept_id, t1, t2) | packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:1214 |

### Does NOT Exist (Anti-Hallucination)

- Neither contracts package, its public models/services, nor the installed contracts domain YAML exists before this feature.
- A public bookstore docx_to_markdown helper does not exist yet; the private implementation is async, despite the brainstorm's sync shorthand.
- OntologyRefreshPipeline.run(..., filters=...) and transactional multi-collection publication do not exist.
- EntityResolver.hybrid_concept_match is not a generic Contract resolver: packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py:539.
- OntologyIntentResolver's fast path does not supply dates, statuses, kind or top_k: packages/ai-parrot/src/parrot/knowledge/ontology/intent.py:129.
- Unmodified OntologyRAGMixin does not provide authorization-before-entity-read ordering or automatic _id-to-_key conversion: packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py:159.
- The two delta tool classes, contracts audit, retirement and catalog SQL methods are new. Existing O365 bundle list/search/download registration is at packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py:10.
- PostgresPersistence is not a ContractCatalogStore and TenantContext alone does not scope all temporal reads.
- PropertyDef has no datetime or nested-model type; versions must be list: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:30.
- RelationDef has no symmetric flag. Symmetry is the contracts relation stage's convention: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:114.
- No already-tested guarantee exists that the proposal AQL works merely because its YAML parses.
- No reusable BOE SpanVerifier accepts contract citations unchanged; its payload key/version model is domain-specific: packages/ai-parrot-tools/src/parrot_tools/legal/librarian/verifier.py:70.

## 7. Implementation Notes & Constraints

### Patterns to Follow

Async-first Python with strict hints and Pydantic v2; black/isort conventions, Google-style docstrings, bounded payloads and structured errors. Offload synchronous parsing/content reads from async entrypoints. Import optional dependencies lazily with actionable installation errors. Core must not import parrot_tools or parrot.scheduler. All SQL identifiers derive from validated configuration, and user values are bound parameters.

### Known Risks / Gotchas

- The pilot scope spans two packages and two graph stores. Sequence by the module dependencies and require a first end-to-end fixture before polishing agent behavior.
- The generic refresh may turn extraction/read failures into empty snapshots or error counters. Preflight complete data and verify effects; do not equate return with successful atomic publication.
- Effective-time contract versions and recorded-time GraphIndex ranges answer different questions; expose both dates.
- Historical evidence increases storage but is necessary for citation verification. Store derived index text, not duplicate source binaries.
- Broad node retirement can suppress additional valid quotes from that node. This follows the resolved design and must be visible to reviewers.
- confirmed tool metadata alone does not enforce authorization or human confirmation in every transport; the service/adapter must enforce both.
- Contract/Party field sets overlap and shared aliases are global within one tenant; avoid per-card extraction corrupting global identity.
- Legal-library agent/flow code is a precedent to adapt, not a promise that its crew runner is executable.
- Folder owner rules need deterministic precedence (most specific matching path, otherwise unassigned) and manual overrides must survive later ingestion.
- Documents are untrusted inputs: instructions inside source text never alter tool routing, authorization, standard taxonomy or publication destinations.

### External Dependencies

| Package | Existing declaration / approved change | Reason |
|---|---|---|
| pydantic | 2.12.5, packages/ai-parrot/pyproject.toml:54 | Typed contracts |
| asyncpg / pgvector | >=0.29 / >=0.2, existing graphindex-postgres extra at packages/ai-parrot/pyproject.toml:257 | Catalog and temporal persistence |
| rapidfuzz | >=3.0: add to graphindex extra at packages/ai-parrot/pyproject.toml:250; already tools scraping extra at packages/ai-parrot-tools/pyproject.toml:73 | Approved fuzzy matching dependency |
| ai-parrot-loaders | Existing satellite; lazy dependency for extractor and DOCX paths | Reuse ExtractDataSource and DOCX conversion |
| pymupdf / pymupdf4llm | Existing optional declarations at packages/ai-parrot/pyproject.toml:313 | Text PDF extraction/indexing; install relevant existing extra |
| python-arango-async | 1.2.0, packages/ai-parrot-embeddings/pyproject.toml:71 | Arango graph backend |
| msgraph-sdk / azure-identity | Existing office365 extra at packages/ai-parrot-tools/pyproject.toml:72 | Delta tools via existing O365 client |
| ai-parrot-server | Optional deployment integration only | Scheduler wiring outside contracts modules |

Install documentation must cover ai-parrot[graphindex,graphindex-postgres], the existing PDF/indexing extra, ai-parrot-loaders, ai-parrot-embeddings[arango] and ai-parrot-tools[office365] for enabled features. No SQLite or new scheduler dependency.

### Worktree Strategy

**Isolation: mixed.** Keep one core feature worktree based on dev for M1–M7 and M9–M12, plus an independent short-lived O365 worktree for M8. All work remains under FEAT-539; no second feature identity or separate delta spec is needed. Merge M8 before jobs integration. The tools lane may start against committed M1/M2 interfaces; do not give concurrent workers overlapping files. Assign pyproject/uv.lock and bookstore/library.py to one owner each.

The brainstorm's no-conflicts claim is a dated observation, not a future guarantee. Recheck active worktrees and indexes at task creation. This spec creates no implementation worktree and dispatches no workers.

## 8. Open Questions

### Original brainstorm decisions (verbatim, preserved)

All questions were resolved with the user on 2026-09-09 (four rounds);
one implementer spike remains.

- [x] **Module location** — *Owner: Jesus Lara*: split — core
  `parrot/knowledge/contracts/` (models, carding, catalog, library,
  datasource, loader, standards); `parrot_tools/contracts/` (toolkit,
  ReAct agent, answer crew, watcher jobs).
- [x] **Answer layer shape** — *Owner: Jesus Lara*: both — fail-closed crew
  for scheduled/API answers, ReAct `ContractsAgent` + toolkit for chat/MCP;
  shared `ContractAnswer` and citation check.
- [x] **Obligation granularity** — *Owner: Jesus Lara*: one `Obligation` per
  clause with closed `kind`; aggregation is a query.
- [x] **`ComplianceStandard` seed** — *Owner: Jesus Lara*: full list
  `soc2, iso27001, gdpr, ccpa, hipaa, pci_dss, nist_800_53,
  cyber_insurance`, hand-written with aliases; SOC 2/HIPAA/PCI aliases
  cross-checked against `parrot_tools/security/reports/mappings/`.
- [x] **Party identity / aliases** — *Owner: Jesus Lara*: `party_aliases`
  table in the catalog + party-merge through the confirming `verify_card`
  tool and the CLI; suffix normalisation at carding; datasource unions
  aliases into the `Party` vertex.
- [x] **Owner / department source** — *Owner: Jesus Lara*: configurable
  folder-path rule applied at ingest, manual override in `verify_card`.
- [x] **Postgres from the pilot or after** — *Owner: Jesus Lara*: Postgres
  from day 1; no SQLite backend; async `ContractCatalogStore`; tests skip
  without `GRAPHINDEX_PG_DSN`.
- [x] **`rapidfuzz` dependency** — *Owner: Jesus Lara*: add `rapidfuzz>=3.0`
  to the `graphindex` extra of `packages/ai-parrot/pyproject.toml`
  (also covers the undeclared lazy import in `ontology/discovery.py`);
  contracts imports it lazily and documents `ai-parrot[graphindex]`.
- [x] **DOCX conversion** — *Owner: Jesus Lara*: extract
  `Bookstore._docx_to_markdown` into a public `docx_to_markdown` helper in
  the bookstore package; the private method delegates to it.
- [ ] **`same_department` on a `Contract` target**: verify whether
  `AuthorizationChecker._check_same_department` reads `Contract.department`
  as-is or needs a target-entity hook before the rule is used. — *Owner:
  implementer (spike inside the ontology task)*
- [x] **Bilingual corpus** — *Owner: Jesus Lara*: English only; YAML
  analyzers unchanged.
- [x] **Missing product doc** — *Owner: Jesus Lara*: it exists at
  `sdd/proposals/contracts-agent-definition.md` (the design doc's
  `claude/…` path is stale); reconciled into this brainstorm on 2026-09-09.
- [x] **LLM-judged relations** — *Owner: Jesus Lara*: in v1 as
  bookstore-style judgements (`relations.py` stage, judgement log,
  `--force`) writing `conflicts_with` and `references_obligation` edges;
  YAML gains the two relations and is re-validated.
- [x] **Watchers' home** — *Owner: Jesus Lara*: standalone async job
  functions in `parrot_tools/contracts/jobs.py`; the deploying agent wires
  `@schedule`; no `parrot.scheduler` import in the package. Default
  delivery channel is the deployer's `send_result`.
- [x] **Delta detection** — *Owner: Jesus Lara*: add a Microsoft Graph
  `/delta` tool to `parrot_tools.o365` first; `ingest_delta` consumes it;
  delta token stored in the catalog.
- [x] **Scanned PDFs** — *Owner: Jesus Lara*: excluded from the pilot;
  no-text PDFs skipped with a logged reason.
- [x] **Answer audit + retirement** — *Owner: Jesus Lara*: `contract_answers`
  table in the Postgres catalog, in this spec; retired answers suppress
  their citations.
- [x] **Verification UI** — *Owner: Jesus Lara*: separate spec
  (`contracts-verification-ui`); this spec ships the API/tool surface only.
- [x] **Temporal plane** — *Owner: Jesus Lara*: dual-write each card version
  to the GraphIndex Postgres plane as a `GraphUpdate` commit now, keeping
  embedded `versions[]` for `contract_in_force`.

### Spec research annotations

The original unchecked same_department spike above is preserved deliberately. Source inspection confirms it reads the target's department generically, so a Contract can supply that field; it also constructs a conventional tenant database and uses ANY-target semantics. The ontology task must verify those assumptions with a Contract fixture before enabling the rule. V1 YAML remains role-based plus my_contracts; no user decision blocks implementation.

Metadata defaults are draft / Jesus Lara & Codex / pilot v1 on current 1.0.0. Review may change the release target without changing architecture.

Codebase corrections in §2 supersede the brainstorm's claims about disjoint datasource fields, filtered refresh, atomic graph publication, generic contract hybrid resolution, and an executable legal crew. They preserve the resolved product scope.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-09 | Jesus Lara / Codex | Initial FEAT-539 draft; resolved brainstorm carried forward, live code contracts verified, publication/retrieval/evidence corrections specified |
