---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Contracts Card & Ontology — a Contract Intelligence agent over ContractCard + `contracts.ontology.yaml`

**Date**: 2026-09-09
**Author**: Jesus Lara (design inputs) / Claude (codebase research)
**Status**: exploration
**Recommended Option**: A

> **Inputs.** This brainstorm consolidates two committed design documents and
> verifies every codebase claim they make against `dev` (commit `9f26dccc4`):
>
> - `sdd/proposals/contracts-card-ontology-design.md` — the `ContractCard`
>   data model (D1–D8), the two-pass carding pipeline, the
>   `ContractCatalogStore` protocol, the agent answer contract and the v1
>   task cut.
> - `sdd/proposals/contracts.ontology.yaml` — the domain vocabulary
>   (5 entities, 11 relations, 1 search view, 10 traversal patterns).
>   **Verified 2026-09-09**: `OntologyParser.load()` accepts it and
>   `OntologyMerger().merge([base, contracts])` yields 8 entities /
>   14 relations / 13 patterns with no integrity error.
> - `sdd/proposals/contracts-agent-definition.md` — the product definition
>   (what the client brochure promises: index-don't-move, cite-or-not_found,
>   Bob stays the judge, contract card + map, **scheduled watchers**,
>   guardrails, 6-week pilot) and its "need → existing piece → gap" mapping.
>   Its mapping table was re-verified on `dev`; corrections are recorded in
>   *Code Context* below.
>
> **Reconciliation.** Where the product definition and the card/ontology
> design disagree, the later card/ontology design wins (it was written
> against the live schema). The renames to carry into the spec:
>
> | Product definition | Card / ontology design (authoritative) |
> |---|---|
> | provenance origin `llm \| manual \| verified` | `FieldProvenance.origin ∈ llm \| rule \| manual` **plus** card/field `verification ∈ extracted \| verified \| stale` |
> | entity `ComplianceRequirement` | entity `ComplianceStandard` (+ `Obligation.standard_id`) |
> | pattern `requires_compliance` | pattern `contracts_requiring_standard` |
> | bookstore-style relations `same_counterparty`, `same_type` | traversals over `party_to` / `Contract.contract_type` (no stored edge) |
> | LLM-judged relations `conflicts_with`, `references_obligation` | **not in the YAML** — open question |
> | temporal via graphindex Postgres plane (FEAT-520) | embedded `Contract.versions[]` (D6); the plane is deferred |
> | Postgres catalog "decide before writing the card" | `ContractCatalogStore` protocol first, SQLite v1, Postgres phase 2 (D8) |
>
> **Discovery rounds.** The two interactive rounds were replaced by the
> design documents (the user supplied them as the answers). Round 0
> defaulted to `type: feature`, `base_branch: dev`. Everything the
> documents leave open is listed under *Open Questions* for `/sdd-spec`
> to resolve with the user.

---

## Problem Statement

A company keeps hundreds of signed agreements (MSAs, SOWs, NDAs, DPAs,
amendments, order forms) as PDFs/DOCX in SharePoint. Nobody can answer,
quickly and defensibly, questions such as *"which agreements require SOC 2?"*,
*"what renews in the next 90 days and by when must we give notice?"*,
*"who signed the Acme MSA and which SOWs hang under it?"*, or *"what did the
contract say before the 2024 amendment?"*. Today the answer is a person
("Bob") opening documents one by one.

The pain is threefold:

1. **No structured card per contract.** Dates, parties, obligations and
   governing law live only inside the document. Nothing is queryable.
2. **No graph.** SOW→MSA, amendment→base, obligation→standard, and
   signatory→party relations are implicit. "Contract family" and
   "which contracts require X" are traversals nobody can run.
3. **No provenance.** Any LLM-extracted value is indistinguishable from a
   human-verified one. Without per-field evidence (node, page, verbatim
   quote) and a verification state, the system is not auditable and Bob
   cannot trust it.

Affected users: contract owners and their managers (self-service lookups),
legal/ops staff (verification queue, renewal radar), and the agent
developer who must ship this on the existing bookstore + ontology stack.

The product definition frames the first delivery as a **6-week pilot** over
50–100 active contracts from the main repository, answering the two
questions from the client's email (SOC 2 requirements, upcoming renewals)
plus Bob's ten most common ones. Success is "the agent's answers match
Bob's, with citations", on roughly two hours of Bob's time per week. The
brochure also promises three **scheduled watchers** (renewal radar daily
with 30/60/90-day windows keyed on the notice deadline, obligations
calendar weekly, new-and-changed contracts every few hours feeding Bob's
verification queue) — a requirement the card/ontology design does not
cover and this brainstorm adds.

The framework already has the two halves this needs — the **bookstore**
(one PageIndex tree + one catalog card per document, SQLite + FTS,
structured-output carding with a no-LLM fallback) and the **ontology
module** (YAML-declared entities/relations, `field_match` discovery,
declarative authorization, AQL traversal patterns with intent fast path).
What is missing is the contract-specific card, the deterministic
projection of that card into the graph, and the agent answer contract
that keeps every lookup citable.

## Constraints & Requirements

- **Zero LLM in retrieval.** Every traversal pattern is a metadata query
  (dates, parties, standards); the LLM is used only at carding time and
  for answer drafting. Same rule as `legal.ontology.yaml`.
- **Per-field provenance is mandatory.** Every extracted value carries
  `FieldProvenance` (`origin`, `node_id`, `page`, `quote ≤ 300 chars`,
  `confidence`). Card-level state is `extracted → verified → stale`.
- **Derived fields are never asked of the LLM.** `status`,
  `notice_deadline`, `next_renewal_date`, `parent_contract_id` are pure
  functions computed in Python (D3).
- **A lookup answer must carry ≥ 1 citation** (`ContractAnswer`
  validator). Questions with deontic/evaluative verbs (*should we, can we,
  is X compliant, accept the redline*) are routed to a hand-off brief, never
  answered.
- **Ontology schema limits (verified):** `PropertyDef.type` is the closed
  `Literal["string","int","float","boolean","date","list","dict"]` — no
  `datetime`, no nested models (`versions: list`, shape enforced in
  Python). `AuthorizationRule.rule` admits only `target_is_self |
  target_in_management_chain | has_role | same_department | always`.
  `SearchViewField.path` allows one nesting level. `field_match` discovery
  matches scalar fields only, so edges with properties (`party_to.role`,
  `signed_by.signed_on`) must be written by a loader.
- **Documents are never copied.** `source_uri` points at SharePoint/
  OneDrive/mail; `source_sha256` is the refresh trigger. A local
  `source_path` is a temporary cache at most.
- **Re-carding must not silently overwrite verified values.** Old-vs-new
  `hash(quote)` comparison decides keep vs. mark `stale`; the previous
  card is preserved in `versions[-1].card_snapshot`.
- **Bitemporal versions** follow the legal convention already in
  production: `valid_from` inclusive, `valid_to` exclusive, `null` = in
  force (`article_in_force` pattern copied as `contract_in_force`).
- **Authorization declared in YAML**, not in prompts: roles
  `contract_reader` / `contract_owner` with `default_deny: true`;
  `my_contracts` is `always` and filters by the `reports_to` management
  chain from the base layer.
- **Async-first, Pydantic v2, Google docstrings, `uv`, `pytest` after any
  logic change** (project rules).
- **No new hard dependency without a decision**: `rapidfuzz` is in the
  venv (3.11.0) but is only declared in the `ai-parrot-tools[scraping]`
  extra; the title-similarity step for `parent_contract_id` must either
  add it to core or use `difflib`.
- **Scheduled watchers are part of the promise.** Renewal radar (daily,
  30/60/90 on `notice_deadline`, falling back to `expiration_date`),
  obligations calendar (weekly, `Obligation.due_date`/`recurrence`) and
  new-and-changed contracts (every few hours → carding → verification
  queue). They must run from the catalog's SQL (`expiring()`,
  `verification_queue()`), never from an LLM, and hook into the existing
  `@schedule` / `schedule_daily_report` / `schedule_weekly_report`
  decorators of `ai-parrot-server` (persisted in `navigator.agents_scheduler`).
- **Guardrails evaluated before retrieval, in the client's tenant, with an
  audit trail.** Authorization runs on the pattern's rules before any
  traversal; every answer records the `pattern` used and the citations
  returned. Bob must be able to correct a card and retire an answer.
- **Pilot scale and success metric**: 50–100 contracts, scanned PDFs
  included ("contract locations & counts incl. scans" is a pilot input), and
  agreement with Bob's answers as the acceptance test.

---

## Options Explored

### Option A: Sibling-card domain module + deterministic graph loader (the design documents as written)

A new `parrot/knowledge/contracts/` package that is a **sibling** of
`bookstore/`, not a subclass (D1): `models.py` (`ContractCard`, `Obligation`,
`FieldProvenance`, `ContractVersion`, the LLM drafts), `carding.py`
(targeted node selection, two structured-output passes, deterministic
`assemble_card` with derivations, no-LLM fallback), `catalog.py`
(`ContractCatalogStore` protocol + SQLite backend with `expiring()` and
`verification_queue()` as SQL), `library.py` (`ContractLibrary.add_contract /
add_folder / verify_card / refresh_card`, reusing `PageIndexToolkit` and the
bookstore carding helpers), `graph_loader.py` (`ContractGraphLoader`: card →
vertices + property-carrying edges via `OntologyGraphStore.upsert_nodes /
create_edges`; the scalar edges are left to `field_match` discovery), the
domain YAML dropped into `ontology/defaults/domains/`, a read-only
`ContractsToolkit(AbstractToolkit)` with `tool_prefix="contracts"` plus one
`confirming_tools` write tool (`verify_card`), and a `ContractsAgent` built on
`Agent` + `OntologyRAGMixin` that emits the `ContractAnswer` contract with a
closed-set intent triage before retrieval.

The three watchers are `@schedule`-decorated methods on the agent
(`renewals_report` daily via `schedule_daily_report`, `obligations_digest`
weekly via `schedule_weekly_report`, `ingest_delta` every few hours via
`@schedule(ScheduleType.INTERVAL…)`), each a thin wrapper over the catalog's
SQL queries plus `ContractLibrary.add_folder`/`refresh_card`, delivering
through the scheduler's `send_result`/`callbacks`. Ingestion sources reuse
the existing `parrot_tools.o365` download tools (SharePoint, OneDrive, mail
attachments) and `parrot_loaders` (PDF, DOCX, OCR backend for scans).

Postgres catalog backend, the SharePoint **delta** loop (no delta query
exists in `parrot_tools.o365` today) and the verification page in the
Svelte admin UI are an explicit **phase 2** (D8, §7.7).

✅ **Pros:**
- Every building block already exists and is verified (see *Code Context*):
  carding helpers, PageIndex import, SQLite+FTS catalog shape, ontology
  merge/validate, graph store upsert, intent fast path, entity resolvers,
  declarative authorization, `AbstractToolkit` prefixing and confirmation.
- The YAML is already valid against the live schema and merges with `base`.
- Provenance, verification and bitemporal versions are first-class from day
  one; nothing has to be retrofitted.
- Renewal radar (`expiring`, `verification_queue`) is plain SQL — works
  without ArangoDB, so the pilot can run CLI-only.
- No change to bookstore, ontology core, or any shared module: purely
  additive, lowest merge risk.

❌ **Cons:**
- Duplicates the bookstore ingestion skeleton (sha → tree → carding →
  upsert) and the SQLite catalog shape instead of generalising them. A
  later "card family" refactor is deferred, not avoided.
- Two carding passes, 1 + N structured-output calls per contract (N capped
  at `max_obligation_sections`, default 12): slower and costlier than
  bookstore's single call.
- `Bookstore._docx_to_markdown` is private; DOCX support needs either a
  small public helper extracted from bookstore or a direct call into
  `parrot_loaders`.
- `parent_contract_id` resolution by title similarity needs a fuzzy library
  decision (`rapidfuzz` vs `difflib`).

📊 **Effort:** High (6 v1 tasks + 1 phase-2 task; the design doc's §7 cut)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | Card, drafts, answer contract | already core |
| `sqlite3` (stdlib) + FTS5 | `ContractCatalogStore` SQLite backend | same degrade-to-`LIKE` rule as `bookstore/catalog.py` |
| `python-docx==1.1.2` / `mammoth>=1.8` | DOCX → markdown | declared in `ai-parrot` and `ai-parrot-tools` / loaders `document` extra |
| `rapidfuzz>=3.0` | title similarity for `parent_contract_id` (≥ 0.85) | **not a core dep** — only in `ai-parrot-tools[scraping]`; decide core-add vs `difflib.SequenceMatcher` |
| `python-arango-async==1.2.0` | ArangoDB graph (`OntologyGraphStore`) | via `ai-parrot-embeddings` |
| `asyncpg>=0.29` | phase-2 Postgres catalog backend | already core |
| `ai-parrot-server` scheduler (`parrot.scheduler`) | `@schedule`, `schedule_daily_report`, `schedule_weekly_report`, `register_bot_schedules`, `send_result`/`callbacks` | core `parrot/scheduler/__init__.py` lazily re-exports from the server package; watchers need the server distribution at runtime |
| `ai-parrot-tools` o365 (`parrot_tools.o365`) | list/search/download files from SharePoint, OneDrive, mail attachments | per-user OAuth (`oauth_toolkit.py`); **no delta query** |
| `ai-parrot-loaders` (`parrot_loaders`) | `pdf.py`, `pdfmark.py`, `docx.py`, `ocr/` backend factory | OCR is wired only into `image.py` today |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/bookstore/carding.py` — `slugify`, `unique_slug`,
  `derive_toc`, the `_CARD_PROMPT` "using ONLY the material below" style,
  and `generate_card_fields` as the structured-output call shape.
- `parrot/knowledge/bookstore/library.py` — `Bookstore.add_book` (sha256
  skip/update, `create_tree` → `import_pdf`/`insert_markdown`, tree
  cleanup on error), `_draft_card` fallback-on-exception, `iter_folder_files`,
  `add_folder`, `refresh_card`.
- `parrot/knowledge/bookstore/catalog.py` — `CatalogStore` DDL/FTS/`_ADDED_COLUMNS`
  migration idiom, `upsert`/`find_by_sha`/`search`/`taken_slugs`.
- `parrot/knowledge/bookstore/_llm.py` — `resolve_adapter` (env-driven
  adapter construction, coding-agent auto-detect, degraded mode).
- `parrot/knowledge/bookstore/toolkit.py` — `BookstoreToolkit` as the
  read-only, funnel-shaped toolkit template (`name`, `tool_prefix`).
- `parrot/knowledge/pageindex/toolkit.py` + `content_store.py` —
  `PageIndexToolkit.create_tree/import_pdf/insert_markdown/insert_content/get_tree/delete_tree/search`,
  `NodeContentStore.loader_for(tree_name)`.
- `parrot/knowledge/ontology/` — `OntologyParser`, `OntologyMerger`,
  `OntologyGraphStore.upsert_nodes/create_edges/execute_traversal`,
  `OntologyIntentResolver` (trigger-intent fast path), `EntityResolver`
  (`fuzzy_name_match`, `hybrid_concept_match`), `AuthorizationChecker`,
  `OntologyRAGMixin`, `TenantOntologyManager` domain resolution
  (`{ontology_dir}/domains/{domain}.ontology.yaml`).
- `parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` —
  `article_in_force` pattern and `versions[*]` search-view path.
- `parrot/knowledge/ontology/defaults/base.ontology.yaml` — `Employee`
  (`employee_id`), `Department` (`department_id`), `reports_to`, `belongs_to`.
- `parrot_tools/security/reports/mappings/{soc2,hipaa,pci_dss}_controls.yaml`
  — seed material for the `ComplianceStandard` taxonomy and alias table.
- `parrot/tools/toolkit.py` — `AbstractToolkit.tool_prefix`,
  `confirming_tools`, `get_tools`.
- `parrot_tools/legal/librarian/models.py` — `SpanRef` / `LegalAnswer` as
  the precedent for a citation-carrying answer model.
- `parrot_tools/legal/librarian/models.py` — `SuppressionRecord` as the
  precedent for "retire an answer" (append-only suppression log).
- `ai-parrot-server/src/parrot/scheduler/manager.py` — `schedule(...)`,
  `schedule_daily_report`, `schedule_weekly_report`, `register_bot_schedules`.
- `parrot_tools/o365/{sharepoint,onedrive,mail}.py` — `ListSharePointFilesTool`,
  `SearchSharePointFilesTool`, `DownloadSharePointFileTool`,
  `DownloadOneDriveFileTool`, `DownloadAttachmentTool` for the ingestion
  fetch step.
- `parrot_loaders/ocr/` — `get_ocr_backend` for the scanned-PDF path.

---

### Option B: Generalise the bookstore into a "card family" and make contracts a card kind

Refactor `bookstore/` into a generic document-library core (`DocumentCard`
base, pluggable `CardKind` with its own draft model, prompt, catalog
columns and FTS fields) and then implement `ContractCard` as one kind.
Contracts would inherit the CLI, the MCP server, `add_folder`, relations
and wiki export for free.

✅ **Pros:**
- One ingestion pipeline, one catalog engine, one CLI/MCP surface; the
  design doc's D1 explicitly names this as the eventual end state.
- Future card kinds (invoices, policies, SOPs) become cheap.

❌ **Cons:**
- Touches every bookstore module (`models`, `catalog`, `library`, `cli`,
  `mcp_server`, `relations`, `wiki_export`) and their tests; `catalog.py` is
  hard-coupled to `books`/`books_fts` and to `Genre`/`traditions`/`period`
  columns. High regression risk on a shipped feature (FEAT-533).
- Contract-specific needs (per-field provenance, verification state,
  obligations as child rows, bitemporal versions, `expiring()` SQL) do not
  fit the flat `BookCard` row; the abstraction would be designed around
  one real consumer plus one hypothetical one.
- Delays the pilot by the refactor time; D1 rejected this precisely because
  there is only one other consumer today.

📊 **Effort:** High (refactor) + Medium (contracts on top)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| same as Option A | — | plus no new ones; the cost is refactor risk, not deps |

🔗 **Existing Code to Reuse:**
- Everything in `parrot/knowledge/bookstore/` — but as a **refactor
  target**, not a reuse.

---

### Option C: Graph-native extraction through GraphIndex (no catalog, no card)

Skip the card and the SQLite catalog. Feed each document through the
GraphIndex pipeline (`GraphIndexBuilder` → `UniversalNode`/`UniversalEdge`
→ `PostgresPersistence`), let the LLM extract `Contract`/`Party`/
`Obligation` concepts directly as nodes and use the FEAT-520 temporal plane
(`replace_document_slice`, `apply_update`, commits/reverts) for
amendments and "as of" queries. The ontology YAML would still declare the
vocabulary; the graph would be the single store.

✅ **Pros:**
- One store, versioned by commit, with revert; temporal queries come from
  the plane instead of an embedded `versions[]` array.
- No duplicated ingestion or catalog code.
- Uses the newest graph machinery in the repo rather than the SQLite-era
  bookstore pattern.

❌ **Cons:**
- Breaks the "deterministic projection from the card" rule (D5): the LLM
  writes the graph. Provenance per field, verification state and
  `stale_fields` have no natural home on a `UniversalNode`.
- The renewal radar (`expiring`, `notice_deadlines_within`,
  `verification_queue`) becomes a graph/Postgres query instead of a plain
  SQL over an indexable card; the CLI-only pilot loses its no-database mode.
- GraphIndex's concept graph and the ontology module's Arango graph are
  different planes; the ten traversal patterns in the YAML target the
  latter. Either the patterns are rewritten or a second projection is
  needed — the very duplication this option tries to avoid.
- `PostgresPersistence` is built for `UniversalNode` graphs, not for a
  contract catalog; it is not a drop-in `ContractCatalogStore` backend.

📊 **Effort:** High, with the highest design uncertainty

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg>=0.29` | `PostgresPersistence` pool | already core |
| GraphIndex pipeline (`parrot/knowledge/graphindex/`) | extraction + persistence | in-repo |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/graphindex/persist_postgres.py` — `PostgresPersistence`
  (`persist_graph`, `replace_document_slice`, `is_stale`, `apply_update`,
  `revert_commit`).
- `parrot/knowledge/graphindex/meta_ontology.py` — universal meta-ontology.

---

### Option D (unconventional): Fail-closed librarian crew instead of a ReAct agent for the answer layer

Keep Option A's data plane, but do **not** build the answer layer as a
tool-using ReAct `Agent`. Port the legal librarian flow from
`parrot_tools/legal/librarian/`: deterministic retrieval nodes (intent fast
path → traversal → section reads) build an enumerated dossier; a single
stateless structured-output draft (`LegalLibrarianAgent.draft` pattern)
produces the answer; a `SpanVerifier`-style check confirms every quoted
citation actually equals the stored node text before the answer is
released, otherwise the citation is suppressed and logged. `ContractAnswer`
then carries only verified citations by construction, and
`interpretation_required` hand-offs are decided in Python from the intent
class, not by the model.

✅ **Pros:**
- Strongest guarantee for "every lookup is citable": citations are checked
  against the PageIndex node content, not trusted from the model.
- Predictable cost (fixed number of LLM calls per question) and a fully
  auditable path (`pattern` + suppression log), which is what an audit of
  contract answers needs.
- Reuses a pattern already in production for the legal domain (verifier,
  suppression records, crew wiring via `AgentCrew`).

❌ **Cons:**
- Less flexible than a tool-using agent for multi-hop, exploratory
  questions ("compare the SLA terms across all Acme SOWs").
- `SpanRef` and `SpanVerifier` are BOE-specific (norma/articulo, char
  offsets over a normalised payload); porting means re-implementing the
  verifier over `(contract_id, node_id, quote)`, not importing it.
- Two agent shapes to maintain if the ReAct variant is also wanted for the
  MCP/interactive path.

📊 **Effort:** Medium on top of Option A's data plane

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | `AgentCrew` and `AbstractTool` are core |

🔗 **Existing Code to Reuse:**
- `parrot_tools/legal/librarian/flow.py` — `build_legal_librarian_crew`,
  `dossier_build`, `ground`, `answer` as the crew shape.
- `parrot_tools/legal/librarian/verifier.py` — `SpanVerifier.verify` as the
  fail-closed idea (re-implemented over PageIndex nodes).
- `parrot_tools/legal/librarian/agent.py` — `LegalLibrarianAgent`
  (`system_prompt` literal, `agent_tools() -> []`, stateless `draft`).

---

## Recommendation

**Option A** is recommended, with one rule borrowed from Option D.

- It is the only option whose every dependency is verified to exist today,
  and its ontology file already passes `OntologyParser.load` and merges
  cleanly with `base`. The design documents were written against the live
  schema constraints (closed `PropertyDef.type`, five authorization rule
  kinds, scalar-only `field_match`), so no ontology-core change is needed.
- It keeps the two non-negotiables intact: **zero LLM in retrieval** and
  **per-field provenance with a three-state verification**. Option C
  sacrifices both; Option B postpones the pilot for a refactor whose second
  consumer does not exist yet.
- The trade-off accepted is code duplication with the bookstore (ingest
  skeleton and SQLite catalog shape). That is a contained, mechanical
  duplication; the "card family" generalisation (Option B) stays on the
  table for when a third card kind appears, and this design makes it easier
  by keeping the same helper functions and catalog idioms.
- From Option D, adopt the **citation check as an acceptance rule** for the
  answer layer: before a `lookup` answer is returned, each `Citation.quote`
  must be found in the content of `(contract_id, node_id)` via
  `NodeContentStore.loader_for`; a citation that fails is dropped and, if
  none survive, the answer degrades to `not_found`. This costs one
  deterministic string check per citation and gives the auditability the
  client asked for without committing to the full crew port. Whether the
  answer layer is a ReAct `Agent` or a fixed crew is left as an open
  question for the spec.
- **Decisions taken on 2026-09-09 with the user:**
  - *DOCX*: extract `Bookstore._docx_to_markdown` into a public helper
    (module-level `docx_to_markdown(path) -> str` in the bookstore package,
    with the private method delegating to it). A small, behaviour-preserving
    bookstore edit; `bookstore-indexed-library` is listed as modified.
  - *Fuzzy matching*: add `rapidfuzz>=3.0` to the **`graphindex` extra** of
    `packages/ai-parrot/pyproject.toml`. This also declares the dependency
    that `parrot/knowledge/ontology/discovery.py` already imports lazily
    (`from rapidfuzz import fuzz`, lines 248 and 400) without any extra
    listing it. The contracts package imports it lazily with the same
    explicit error, and its docs name `ai-parrot[graphindex]` as the
    install requirement. The pyproject change is a task in the spec, not
    applied by this brainstorm.
  - *Graph loader*: designed above (`ContractCardDataSource` +
    `ContractGraphLoader` over `OntologyRefreshPipeline`), so the
    "no direct ancestor" gap is closed by reusing the legal domain's shape.
- Phase the delivery exactly as the design doc's §7: v1 = models →
  carding → SQLite catalog → library → ontology + graph loader → toolkit +
  agent; phase 2 = Postgres backend + SharePoint delta loop.

---

## Feature Description

### User-Facing Behavior

**Ingestion (CLI / library API, not an agent tool).** An operator points
`ContractLibrary.add_contract(source, source_uri=…)` or `add_folder()` at
PDF/DOCX/MD/TXT files. For each file the system computes the sha256, skips
unchanged documents, builds a PageIndex tree named after the contract slug,
runs two carding passes (header, then obligations), assembles a
`ContractCard` with per-field provenance, derives `status`,
`notice_deadline`, `next_renewal_date` and (when unambiguous)
`parent_contract_id`, and upserts the card. Without an LLM the card is a
`fallback` card (title from filename, type/dates by regex, confidence 0.3,
no obligations). The operator sees `(card, "added" | "updated" | "skipped")`.

**Sources.** Files are fetched, never moved: SharePoint/OneDrive documents
and mail attachments come through the existing `parrot_tools.o365`
download tools into a temporary `source_path`; `source_uri` keeps the
canonical location. Scanned PDFs go through the `parrot_loaders` OCR
backend before PageIndex import (path to be wired; see open questions).

**Scheduled watchers.** Three agent methods registered with the server
scheduler: `renewals_report` (daily) lists contracts whose
`notice_deadline` (fallback `expiration_date`) falls in 30/60/90-day
windows; `obligations_digest` (weekly) lists obligations with a
`due_date` or `recurrence` hitting the coming period; `ingest_delta`
(every few hours) re-scans the configured sources, cards new documents and
refreshes changed ones (sha mismatch), pushing every new or `stale` card
into the verification queue. Results go out through the scheduler's
`send_result`/`callbacks` (email, Teams, etc.), never through the LLM.

**Verification queue.** `verification_queue()` lists cards ordered by
lowest-confidence and un-evidenced fields first, then `stale`. Bob calls
`verify_card(contract_id, fields=None | {...}, user)`: verified fields get
`origin="manual"` when corrected, `verified_by/at` always; the card becomes
`verified` only when no field remains below the confidence threshold and
`stale_fields` is empty.

**Refresh.** When the source sha changes, `refresh_card` re-cards into a new
draft, keeps every verified field whose `hash(quote)` is unchanged, marks
the rest `stale`, snapshots the previous card into a new `ContractVersion`
(`amendment` or `restatement`) and never discards a verified value.

**Graph publish.** `ContractGraphLoader.publish(card)` writes
`Contract`/`Party`/`Person`/`Obligation` vertices and the property-carrying
edges (`party_to.role`, `signed_by.signed_on/on_behalf_of`, `amends`,
`supersedes`); the scalar edges (`governed_by`, `imposed_by`, `requires`,
`represents`, `is_employee`, `owned_by`, `managed_by`) are produced by the
ontology's `field_match` discovery. `ComplianceStandard` is a static seed.

**Agent surface.** A read-only `contracts_*` toolkit (`catalog_search`,
`get_card`, `get_toc`, `read_section`, `obligations`, `expiring`,
`verification_queue`) plus a confirming `verify_card`. The agent answers
with a `ContractAnswer`: `lookup` (answer + ≥ 1 citation, each with
`contract_id`, `node_id`, `page`, verbatim `quote` and its verification
state), `interpretation_required` (a `HandoffBrief` with the located
clauses and a suggested owner), `not_found`, `out_of_scope`, or `denied`.
The `provenance` field summarises the citations (`verified | mixed |
extracted`) so the reader always knows whether they are looking at
AI-extracted or human-verified facts. Every released answer is written to
an audit record (user, question, `answer_kind`, `pattern`, citations,
authorization outcome) and Bob can **retire** an answer, which suppresses
its citations from future lookups the way the legal librarian's
`SuppressionRecord` does. Typical questions map to the ten
YAML traversal patterns: contracts requiring a standard, expiring within a
window, notice deadlines, contracts with a party, contract family,
signatories, obligations of a contract, version in force as of a date,
"my contracts", and lexical search.

### Internal Behavior

1. **Node selection for carding** (`select_carding_nodes`): first node
   (cover/preamble), nodes whose ToC title matches
   `term|duration|renewal|termination|notice|governing law|definitions|parties|scope`,
   and the signature block (last node or first containing
   `IN WITNESS WHEREOF|signed|by:|title:|date:`). Fallback: first + last +
   three densest nodes by `shall|must|agrees to`.
2. **Pass 1** → `ContractHeaderDraft` (title, type, parties, signatories,
   dates, term, governing law, parent title, language, summary, topics).
   Every value is an `Extracted{value, evidence{node_id, quote, page},
   confidence}`; a value without evidence is accepted with confidence
   capped at 0.5 and goes first in the verification queue.
3. **Pass 2** → `ObligationsDraft`, one call per candidate section
   (deontic-verb density above threshold or title/body match on
   `compliance|SOC|ISO|GDPR|insurance|audit|security|SLA|service level|data protection|confidential`),
   bounded by `max_obligation_sections`.
4. **Assembly** (`assemble_card`, pure Python): slugs via `slugify`
   (`party_id`, `person_id`), `standard_name → standard_id` through the
   `ComplianceStandard` alias table, derivations (D3), `parent_contract_id`
   resolved against the catalog (same counterparty + governing type +
   title similarity ≥ 0.85; ambiguous → `None` + `stale_fields`).
5. **Persistence** behind `ContractCatalogStore` (SQLite v1: `contracts`,
   `contracts_fts`, `obligations`, `contract_versions`; `card_json` column +
   indexable columns `status`, `expiration_date`, `notice_deadline`,
   `verification`, `source_sha256`, `source_uri`).
6. **Graph projection** via `OntologyGraphStore.upsert_nodes(ctx,
   collection, nodes, key_field)` and `create_edges(ctx, edge_collection,
   edges)`; `versions[]` embedded on the `Contract` vertex.
7. **Answering**: closed-set intent triage (structured output over a
   `Literal`) **before** retrieval; deontic/evaluative intents → hand-off.
   Otherwise `OntologyIntentResolver` fast path over `trigger_intents`,
   `EntityResolver` for `Party`/`ComplianceStandard` (fuzzy) and `Contract`
   (hybrid), `AuthorizationChecker` on the pattern's rules, traversal, then
   section reads through `NodeContentStore` for the quotes, and the
   citation check before the answer is released.

### `ContractGraphLoader` design (resolved 2026-09-09)

The loader is **not** a bespoke Arango writer. It reproduces the legal
domain's shape one-to-one, so the generic ontology machinery does the
node sync and the loader only adds what that machinery cannot do:

1. **`ContractCardDataSource(ExtractDataSource)`** — the `source:
   contractcard` declared on `Contract`, `Party`, `Person` and
   `Obligation` in the YAML. Registered with
   `DataSourceFactory.register_api_source("contractcard", …)` so
   `OntologyRefreshPipeline` resolves it by name. Its `extract(fields,
   filters)` reads the catalog (`ContractCatalogStore.list_cards()`, or one
   card when `filters={"contract_id": …}`) and infers the target entity from
   the requested `fields` exactly as `BOEDataSource._target_entity` does
   (the four key fields `contract_id` / `party_id` / `person_id` /
   `obligation_id` are disjoint). Projection rules:
   - `Contract` record = the YAML property list; dates as ISO-8601 strings
     (ArangoDB has no date type; the legal domain compares ISO strings and
     the AQL patterns `>= @today` rely on that), `counterparty_names`
     denormalised from non-`us` parties, `versions[]` embedded as a list of
     plain dicts, `verification`/`verified_by` copied from the card.
   - `Party` record = one per distinct `party_id` **across the whole
     catalog**, with `aliases` = union of every spelling seen on any card.
     Computing the union at extraction time avoids a read-modify-write on
     the graph and keeps the datasource pure.
   - `Person` record = one per `person_id` (slug of name + party), carrying
     `party_id` and `employee_id` so `represents` / `is_employee` are
     discovered by `field_match`.
   - `Obligation` record = one per card obligation, `contract_id` and
     `standard_id` present so `imposed_by` / `requires` are discovered.
   - `ComplianceStandard` has no `source:` in the YAML; it is a **static
     seed table** (`standards.py`: id, name, aliases) that the loader upserts
     once per publish (idempotent). The same table is the alias map
     `assemble_card` uses for `standard_name → standard_id`, so there is a
     single source of truth.
2. **`ContractGraphLoader`** — the orchestrator, with three operations:
   - `publish_all()` runs `OntologyRefreshPipeline.run(tenant_id,
     domain="contracts")` (extract → diff → `upsert_nodes` → soft-delete
     vanished keys → `field_match` rediscovery for `governed_by`,
     `imposed_by`, `requires`, `represents`, `is_employee`, `owned_by`,
     `managed_by`), then `_sync_card_edges()` writes the four
     property-carrying edges the pipeline cannot derive — `party_to{role}`,
     `signed_by{signed_on, on_behalf_of}`, `amends{effective_date}`,
     `supersedes` — through `OntologyGraphStore.create_edges`, building
     `_from`/`_to` from the merged ontology's `collection` names the same
     way `_sync_provenance_edges` does for `modifica`/`deroga`.
   - `publish(card)` is the single-card variant (datasource `filters`).
   - `retract(contract_id)` soft-deletes the `Contract` vertex and its
     `Obligation` vertices and hard-removes the incident property edges
     (`edges_incident` + `remove_edge_by_triple`).
   - **Set-replace rule for edges**: `create_edges` de-duplicates on
     `(_from, _to)` but never deletes, so before writing a card's
     `party_to`/`signed_by` edges the loader removes the existing ones for
     that contract. `amends` is written only when `contract_type ==
     "amendment"` and the parent resolved; `supersedes` only when
     `supersedes_contract_id` is set. An amendment therefore carries both
     `governed_by` (discovered from `parent_contract_id`) and `amends`
     (with `effective_date`); `contract_family` uses `DISTINCT`, so the
     redundancy is harmless and intentional.
   - **Publication policy**: every card is published regardless of
     `verification`; the vertex carries the state and the answer layer
     labels provenance. Nothing is hidden from the graph, nothing is
     presented as verified that is not.
   - **No scheduler import** (same deployment note as `sync_boe`): the
     `ingest_delta` watcher and the CLI call the loader; the loader never
     imports `parrot.scheduler`, so the contracts package does not depend
     on the server satellite.
   - **Failure semantics**: the pipeline's `RefreshReport.errors` carry
     per-entity failures; a card whose projection raises is skipped and
     reported, never half-written; edge sync errors are appended to the
     same report.
   - Tenant context comes from `TenantOntologyManager.resolve(...)` for
     `domain="contracts"`; the YAML must be reachable under
     `{ontology_dir}/domains/contracts.ontology.yaml`.

### Edge Cases & Error Handling

- **Unsupported format / missing file** → `ContractLibraryError` before any
  tree is created; a failed import deletes the half-built tree (same
  cleanup as `Bookstore.add_book`).
- **LLM failure during carding** → warning + `fallback` card; ingest never
  blocks on the model.
- **Two `is_us` parties** → validation error on the card (D-model
  validator).
- **Ambiguous parent contract** → `parent_contract_id=None`, field listed in
  `stale_fields`; no false `governed_by` edge is ever written.
- **Party identity collisions** ("Acme Corp" vs "Acme Corporation") →
  suffix normalisation (`Inc|Corp|Corporation|Ltd|LLC|S.L.|S.A.`) plus a
  curable alias table; unresolved → separate `Party` rows flagged for
  review.
- **Re-carding a verified card** → verified values with unchanged quote
  hash are kept; changed ones go `stale`, never overwritten silently.
- **Citation whose quote is not in the node content** → dropped; zero
  surviving citations → `not_found`, never a bare `lookup`.
- **Authorization denied** → `answer_kind="denied"` with no citations
  (`default_deny: true` on every role-gated pattern).
- **No ArangoDB** → catalog, carding, verification queue and renewal radar
  keep working (SQL); only traversal patterns are unavailable.
- **FTS5 unavailable** → catalog search degrades to `LIKE`, as in bookstore.
- **Dates before the first version** in `contract_in_force` → empty result
  (documented in the pattern).
- **Contracts with no notice period** → `notice_deadlines_within` falls back
  to `expiration_date` (`LET key_date = …` in the pattern).

---

## Capabilities

### New Capabilities
- `contracts-card-ontology`: `ContractCard` model with per-field provenance
  and verification state; two-pass carding with deterministic assembly and
  no-LLM fallback; `ContractCatalogStore` protocol + SQLite backend
  (`expiring`, `verification_queue`); `ContractLibrary`
  (`add_contract/add_folder/verify_card/refresh_card`);
  `contracts.ontology.yaml` in `ontology/defaults/domains/` +
  `ContractGraphLoader`; `ContractsToolkit` (read-only + confirming
  `verify_card`); `ContractsAgent` emitting `ContractAnswer` with citation
  check and hand-off triage; the three scheduled watchers
  (`renewals_report`, `obligations_digest`, `ingest_delta`) over the
  catalog SQL; answer audit record + answer retirement. Phase 2 (same
  spec, later tasks): Postgres catalog backend, SharePoint/OneDrive delta
  loop, OCR wiring for scanned PDFs.
- `contracts-verification-ui` (proposed, **separate spec**): Bob's
  verification-queue page in the Svelte 5 admin UI
  (`ai-parrot-server/ui`, currently Home/Login/Dashboard/Agents only),
  consuming `verification_queue()` / `verify_card`.

### Modified Capabilities
- `bookstore-indexed-library`: `Bookstore._docx_to_markdown` is extracted
  into a public `docx_to_markdown` helper (no behaviour change).
- `ontological-graph-rag`: no requirement change; `rapidfuzz` becomes a
  declared dependency (graphindex extra) for the fuzzy `field_match`
  strategy that `discovery.py` already uses.
- `base.ontology.yaml` is unchanged (the domain `extends: base`).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/contracts/` (new) | new package | models, carding, catalog, library, graph_loader, toolkit, agent |
| `parrot/knowledge/ontology/defaults/domains/contracts.ontology.yaml` | new file | copied from `sdd/proposals/contracts.ontology.yaml`; loaded by `TenantOntologyManager` for `domain="contracts"` |
| `parrot/knowledge/bookstore/carding.py` | depends on (import) | `slugify`, `unique_slug`, `derive_toc`; no edits |
| `parrot/knowledge/bookstore/library.py` | small extension | `_docx_to_markdown` extracted into a public `docx_to_markdown` helper (decided) |
| `parrot/knowledge/ontology/refresh.py`, `discovery.py` | depends on | `OntologyRefreshPipeline.run(tenant_id, domain)` drives node sync + `field_match` rediscovery; `RelationDiscovery` fuzzy strategy needs `rapidfuzz` |
| `parrot_loaders/extractors/{base,factory}.py` | depends on | `ContractCardDataSource(ExtractDataSource)` registered via `DataSourceFactory.register_api_source` |
| `parrot/knowledge/pageindex/` | depends on | `PageIndexToolkit`, `NodeContentStore`, `PageIndexLLMAdapter.ask_structured` |
| `parrot/knowledge/ontology/graph_store.py` | depends on | `upsert_nodes`, `create_edges`, `execute_traversal` |
| `parrot/knowledge/ontology/{intent,entity_resolver,authorization,mixin}.py` | depends on | intent fast path, resolvers, `AuthorizationChecker`, `OntologyRAGMixin` |
| `parrot/tools/toolkit.py` | depends on | `AbstractToolkit.tool_prefix`, `confirming_tools` |
| `parrot/bots/agent.py` | depends on | `Agent` base for `ContractsAgent` |
| `parrot_tools/security/reports/mappings/*.yaml` | reference data | seed for `ComplianceStandard` ids/aliases (soc2, hipaa, pci_dss present) |
| `parrot_tools/o365/{sharepoint,onedrive,mail}.py` | depends on | list/search/download tools for the fetch step; **no delta query** — phase-2 delta loop must poll `List*`/`Search*` or add Graph `/delta` |
| `parrot_loaders/{pdf,pdfmark,docx}.py`, `parrot_loaders/ocr/` | depends on | OCR backend factory exists but only `image.py` calls it; scanned-PDF path is new wiring |
| `ai-parrot-server/src/parrot/scheduler/manager.py` | depends on | `@schedule`, `schedule_daily_report`, `schedule_weekly_report`, `register_bot_schedules`; rows in `navigator.agents_scheduler` |
| `ai-parrot-server/ui` (Svelte 5) | separate spec | verification-queue page does not exist |
| `parrot/interfaces/sharepoint.py`, `parrot/core/hooks/sharepoint.py` | not used | upload-oriented `SharepointClient`; superseded by `parrot_tools.o365` for reads |
| `packages/ai-parrot/pyproject.toml` | new optional dep | `rapidfuzz>=3.0` added to the `graphindex` extra (decided) |
| `packages/ai-parrot/tests/knowledge/contracts/` (new) | tests | synthetic MSA + SOW markdown fixtures, fake adapter, no-LLM fallback path |
| CI / deployment | none | additive; no migration of existing stores |

Breaking changes: none.

---

## Code Context

### User-Provided Code

The full model, draft, catalog-protocol and answer-contract definitions
are in `sdd/proposals/contracts-card-ontology-design.md` §1, §1.1, §3, §5
(user-provided design, not yet in the codebase). The load-bearing pieces,
verbatim:

```python
# Source: sdd/proposals/contracts-card-ontology-design.md §1 (user-provided design)
ContractType = Literal["msa", "sow", "nda", "dpa", "amendment", "order_form", "license", "sla", "other"]
ContractStatus = Literal["draft", "active", "expired", "terminated", "superseded", "unknown"]
PartyRole = Literal["customer", "vendor", "partner", "affiliate", "us", "other"]
ObligationKind = Literal[
    "compliance", "insurance", "data_protection", "security", "sla", "audit_right",
    "reporting", "payment", "confidentiality", "termination", "notice", "deliverable", "other",
]
Obligor = Literal["us", "counterparty", "both"]
Verification = Literal["extracted", "verified", "stale"]
ProvenanceOrigin = Literal["llm", "rule", "manual"]   # rule = derivación determinista


class FieldProvenance(BaseModel):
    origin: ProvenanceOrigin
    node_id: Optional[str] = None       # nodo PageIndex (tree = contract_id)
    page: Optional[int] = None
    quote: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None


class Obligation(BaseModel):
    obligation_id: str                  # f"{contract_id}:{seq}"
    contract_id: str
    kind: ObligationKind
    obligor: Obligor = "us"
    text: str                           # excerpt verbatim — la cita
    node_id: str
    page: Optional[int] = None
    standard_id: Optional[str] = None   # ComplianceStandard (soc2, gdpr, ...)
    due_date: Optional[date] = None
    recurrence: Optional[str] = None
    verification: Verification = "extracted"
    provenance: FieldProvenance


class ContractVersion(BaseModel):
    n: int
    valid_from: date
    valid_to: Optional[date] = None     # exclusivo; None = vigente
    kind: Literal["original", "amendment", "renewal", "restatement"] = "original"
    amended_by: Optional[str] = None
    source_sha256: str
    card_snapshot: dict = Field(default_factory=dict)


class ContractCard(BaseModel):
    contract_id: str                    # == PageIndex tree_name
    tree_name: str
    title: str
    contract_type: ContractType = "other"
    status: ContractStatus = "unknown"              # derivado (rule)
    parties: list[Party] = Field(default_factory=list)
    signatories: list[Signatory] = Field(default_factory=list)
    term: TermSpec = Field(default_factory=TermSpec)
    governing_law: Optional[str] = None
    parent_contract_id: Optional[str] = None
    supersedes_contract_id: Optional[str] = None
    obligations: list[Obligation] = Field(default_factory=list)
    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    owner_employee_id: Optional[str] = None
    department: Optional[str] = None
    language: Optional[str] = None
    source_uri: str                                 # nunca una copia
    source_path: Optional[str] = None
    source_sha256: str
    source_format: Literal["pdf", "docx", "md", "txt"]
    page_count: Optional[int] = None
    toc: list["TocEntry"] = Field(default_factory=list)     # bookstore.models.TocEntry
    toc_digest: str = ""
    field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    verification: Verification = "extracted"
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    stale_fields: list[str] = Field(default_factory=list)
    card_origin: Literal["llm", "fallback", "manual"] = "llm"
    versions: list[ContractVersion] = Field(default_factory=list)
    added_at: str
    updated_at: str
    # validator: at most one party with is_us=True; brief() -> compact dict
```

```python
# Source: sdd/proposals/contracts-card-ontology-design.md §3 (user-provided design)
class ContractCatalogStore(Protocol):
    def upsert(self, card: ContractCard) -> None: ...
    def get(self, contract_id: str) -> ContractCard | None: ...
    def find_by_sha(self, sha256: str) -> ContractCard | None: ...
    def find_by_source_uri(self, uri: str) -> ContractCard | None: ...
    def list_cards(self, *, status: ContractStatus | None = None, verification: Verification | None = None) -> list[ContractCard]: ...
    def search(self, query: str, top_k: int = 8) -> list[tuple[ContractCard, float]]: ...   # FTS
    def expiring(self, *, until: date, key: Literal["expiration_date", "notice_deadline"]) -> list[ContractCard]: ...
    def verification_queue(self, *, limit: int = 50) -> list[ContractCard]: ...
    def taken_slugs(self) -> set[str]: ...
    def remove(self, contract_id: str) -> bool: ...
```

```python
# Source: sdd/proposals/contracts-card-ontology-design.md §5 (user-provided design)
class Citation(BaseModel):
    contract_id: str; title: str; node_id: str; page: Optional[int] = None
    quote: str; verification: Verification

class HandoffBrief(BaseModel):
    question: str
    why_judgment: str
    located_clauses: list[Citation]
    related_contracts: list[str] = Field(default_factory=list)
    suggested_owner: Optional[str] = None

class ContractAnswer(BaseModel):
    answer_kind: Literal["lookup", "interpretation_required", "not_found", "out_of_scope", "denied"]
    answer: Optional[str] = None               # sólo en lookup
    citations: list[Citation] = Field(default_factory=list)
    provenance: Literal["verified", "mixed", "extracted"]
    handoff: Optional[HandoffBrief] = None
    pattern: Optional[str] = None
    # validator: answer_kind == "lookup" requires >= 1 citation
```

The domain vocabulary is `sdd/proposals/contracts.ontology.yaml`
(`name: contracts`, `version: "0.1"`, `extends: base`; entities `Contract`,
`Party`, `Person`, `Obligation`, `ComplianceStandard`; relations `party_to`,
`signed_by`, `represents`, `is_employee`, `governed_by`, `amends`,
`supersedes`, `imposed_by`, `requires`, `owned_by`, `managed_by`; view
`contracts_view`; patterns `contracts_requiring_standard`, `expiring_within`,
`notice_deadlines_within`, `contracts_with_party`, `contract_family`,
`signatories_of`, `obligations_of_contract`, `contract_in_force`,
`my_contracts`, `search_contracts`). Validated 2026-09-09 as described in
the header note.

### Verified Codebase References

All paths are relative to `packages/ai-parrot/src/` unless prefixed with
`parrot_tools/` (then `packages/ai-parrot-tools/src/`).

#### Classes & Signatures
```python
# From parrot/knowledge/bookstore/models.py
class TocEntry(BaseModel):                                  # line 98
    node_id: str; title: str; depth: int = 1
    start_page: Optional[int] = None; end_page: Optional[int] = None
class CardDraft(BaseModel):                                 # line 117 — bookstore's LLM draft (title/authors/year/language/topics/summary/genre/traditions/period)
class BookCard(BaseModel):                                  # line 152
    book_id: str; title: str; ...; tree_name: str; source_path: str; source_sha256: str
    source_format: Literal["pdf","md","txt","epub","mobi","docx"]; added_at: str
    card_origin: Literal["llm","fallback","manual"] = "llm"
    def brief(self) -> dict:                                # line 183

# From parrot/knowledge/bookstore/carding.py
def slugify(text: str) -> str:                              # line 49 — NFKD, ascii, ≤64 chars, fallback "book"
def unique_slug(base: str, taken: set[str]) -> str:         # line 73
def derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str]:   # line 88
def fallback_card_fields(file_path: Path, toc_entries: list[TocEntry]) -> CardDraft:      # line 141
async def generate_card_fields(adapter: Any, *, filename: str, doc_description: str,
                               toc_digest: str, samples: list[str]) -> CardDraft:         # line 157 — adapter.ask_structured(prompt, CardDraft)
def sample_sections(content_loader: Any, node_ids: list[str], max_samples: int = 2) -> list[str]:  # line 193

# From parrot/knowledge/bookstore/catalog.py
class CatalogStore:                                         # line 163 — SQLite, WAL, FTS5 with LIKE fallback
    def __init__(self, db_path: Path | str) -> None:        # line 171
    def _ensure_schema(self, conn) -> None:                 # line 197 — _BOOKS_DDL + _ADDED_COLUMNS ALTER migration idiom
    def _ensure_fts_schema(self, conn) -> None:             # line 220 — drop/rebuild on column drift
    def upsert(self, card: BookCard) -> None:               # line 300
    def get(self, book_id: str) -> Optional[BookCard]:      # line 374
    def find_by_sha(self, sha256: str) -> Optional[BookCard]:   # line 380
    def list_cards(self) -> list[BookCard]:                 # line 386
    def taken_slugs(self) -> set[str]:                      # line 392
    def search(self, query: str, top_k: int = 8) -> list[tuple[BookCard, float]]:   # line 398

# From parrot/knowledge/bookstore/library.py
class Bookstore:                                            # line 133
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
                 lightweight_model: Optional[str] = None) -> None:                  # line 147
    def _toolkit(self, scope: str) -> PageIndexToolkit:     # line 188 — PageIndexToolkit(adapter=…, storage_dir=loc.trees_dir, lightweight_model=…)
    def _content_store(self, scope: str) -> NodeContentStore:   # line 199
    async def add_book(self, file_path, scope="project", title=None, authors=None, topics=None,
                       force=False, *, relate=False) -> tuple[BookCard, str]:       # line 888 — sha→skip/update→create_tree→import→carding→upsert
    async def _draft_card(self, path, tree_name, scope, doc_description, toc_digest, toc_entries) -> CardDraft:   # line 1047 — fallback on exception
    async def _docx_to_markdown(self, path: Path) -> str:   # line 1073 — PRIVATE
    @staticmethod
    def iter_folder_files(folder, recursive=False) -> tuple[list[Path], list[Path]]:   # line 1133
    async def add_folder(self, folder, scope="project", recursive=False, force=False, *, relate=False) -> dict[str, Any]:   # line 1163
    async def refresh_card(self, book_id: str) -> BookCard: # line 1248

# From parrot/knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                    # line 29
    name = "bookstore"; tool_prefix = "bookstore"
    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None:   # line 39

# From parrot/knowledge/bookstore/_llm.py
def resolve_adapter(llm_spec: Optional[str] = None, lightweight_model: Optional[str] = None
                    ) -> tuple[Optional[Any], Optional[str], Optional[Any]]:   # line 42 — env PARROT_BOOKSTORE_LLM / _LIGHT

# From parrot/knowledge/pageindex/llm_adapter.py
class PageIndexLLMAdapter:                                  # line 42
    async def ask_structured(self, prompt: str, output_type: type, temperature: float = 0.0,
                             system_prompt: Optional[str] = None) -> Any:   # line 99

# From parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]:   # line 377
    async def delete_tree(self, tree_name: str) -> dict[str, Any]:                                  # line 398
    async def get_tree(self, tree_name: str) -> dict[str, Any]:                                     # line 410
    async def search(...)                                                                           # line 414
    async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None,
                              doc_name: Optional[str] = None) -> dict[str, Any]:                    # line 692
    async def insert_content(...)                                                                   # line 760
    async def import_pdf(self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None,
                         with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any]:   # line 803

# From parrot/knowledge/pageindex/content_store.py
class NodeContentStore:                                     # line 37
    def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:   # line 197

# From parrot/knowledge/ontology/schema.py
class PropertyDef(BaseModel):                               # line 18
    type: Literal["string", "int", "float", "boolean", "date", "list", "dict"]   # line 30
class EntityDef(BaseModel):                                 # line 40
class DiscoveryRule(BaseModel):                             # line 80
class DiscoveryConfig(BaseModel):                           # line 100
class RelationDef(BaseModel):                               # line 114
class EntityExtractionRule(BaseModel):                      # line 142
    resolver: Literal["exact_id_match", "fuzzy_name_match", "ai_assisted", "hybrid_concept_match"]
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
class AuthorizationRule(BaseModel):                         # line 176
    rule: Literal["target_is_self", "target_in_management_chain", "has_role", "same_department", "always"]   # lines 185-191
    role: str | None = None
class AuthorizationSpec(BaseModel):                         # line 212
class TraversalPattern(BaseModel):                          # line 261
    description: str; trigger_intents: list[str]; query_template: str
    post_action: Literal["vector_search", "tool_call", "none"] = "none"; post_query: str | None
    entity_extraction: dict[str, EntityExtractionRule]; authorization: AuthorizationSpec | None; tool_call: ToolCallSpec | None
class SearchViewField(BaseModel):                           # line 298 — path: str (≤ 1 nesting level), analyzers: list[str]
class OntologyDefinition(BaseModel):                        # line 419 — name, version, extends, description, entities, relations, traversal_patterns, search_views; extra="forbid"
class MergedOntology(BaseModel):                            # line 452
class TenantContext(BaseModel):                             # line 529

# From parrot/knowledge/ontology/parser.py
class OntologyParser:                                       # line 19
    @staticmethod
    def load(path: Path) -> OntologyDefinition:             # line 29
    @staticmethod
    def get_defaults_dir() -> Path:                         # line 93

# From parrot/knowledge/ontology/merger.py
class OntologyMerger:                                       # line 29
    def merge(self, yaml_paths: list[Path]) -> MergedOntology:   # line 54
    def _validate_integrity(self, merged: MergedOntology) -> None:   # line 419

# From parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:                                   # line 34
    def __init__(self, arango_client: Any = None) -> None:  # line 50
    async def execute_traversal(self, ctx: TenantContext, aql: str, bind_vars: dict | None = None,
                                collection_binds: dict[str, str] | None = None) -> list[dict]:   # line 234
    async def upsert_nodes(self, ctx: TenantContext, collection: str, nodes: list[dict], key_field: str) -> UpsertResult:   # line 274
    async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict]) -> int:   # line 372 — edges need _from/_to

# From parrot/knowledge/ontology/intent.py
class OntologyIntentResolver:                               # line 48
    async def resolve(...)                                  # line 97
    def _try_fast_path(...)                                 # line 129 — trigger_intents keyword match

# From parrot/knowledge/ontology/entity_resolver.py
class EntityResolver:                                       # line 93
    async def extract_and_resolve(...)                      # line 135
    async def _fuzzy_name_match(...)                        # line 388
    async def _resolve_hybrid_concept_match(...)            # line 539

# From parrot/knowledge/ontology/authorization.py
class AuthorizationChecker:                                 # line 43
    async def check(...)                                    # line 62
    async def _check_same_department(...)                   # line 293

# From parrot/knowledge/ontology/mixin.py
class OntologyRAGMixin:                                     # line 79
    def __init__(self, tenant_manager=None, graph_store=None, vector_store=None, cache=None,
                 llm_client=None, tool_manager=None, **kwargs) -> None:   # line 117
    async def ontology_process(self, query: str, user_context: dict, tenant_id: str,
                               domain: str | None = None) -> ContextEnvelope:   # line 159

# From parrot/knowledge/ontology/tenant.py (lines 129-132 / 295-298)
# domain layer path = f"{ontology_dir}/{domains_dir}/{domain}.ontology.yaml"  (domains_dir default "domains")

# From parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                 # line 206
    tool_prefix: str | None = None                          # line 257
    confirming_tools: frozenset = frozenset()               # line 275
    def get_tools(...)                                      # line 486

# From parrot/clients/base.py
    async def ask(..., structured_output: Union[type, StructuredOutputConfig, None] = None, ...)   # line 1662 / 1671

# From parrot/knowledge/graphindex/persist_postgres.py
class PostgresPersistence:                                  # line 207 — UniversalNode/UniversalEdge graphs, commits, revert (NOT a catalog store)

# From parrot_tools/legal/boe/datasource.py
class BOEDataSource(ExtractDataSource):                     # line 33 — parrot_loaders ExtractDataSource; extract_relations() line 130
# From parrot_tools/legal/librarian/models.py
class SpanRef(BaseModel):                                   # line 36
class LegalAnswer(BaseModel):                               # line 120
# From parrot_tools/legal/librarian/verifier.py
class SpanVerifier:                                         # line 37; verify() line 70
# From parrot_tools/legal/librarian/agent.py
class LegalLibrarianAgent(Agent):                           # line 47 — literal system_prompt, agent_tools() -> [], async draft(...) line 79
# From parrot_tools/legal/librarian/flow.py
def build_legal_librarian_crew(agent, store, ctx, log) -> AgentCrew:   # line 494
# From parrot_tools/legal/librarian/models.py
class SuppressionRecord(BaseModel):                         # line 149 — append-only "retire" precedent

# From packages/ai-parrot-server/src/parrot/scheduler/manager.py
def schedule(schedule_type: ScheduleType = ScheduleType.DAILY, *, success_callback: Optional[Callable] = None,
             send_result: Optional[Dict[str, Any]] = None, callbacks: Optional[List[Dict[str, Any]]] = None,
             **schedule_config):                            # line 90 — decorator for agent methods
schedule_daily_report = _report_decorator_factory("daily", ScheduleType.DAILY.value)     # line 173
schedule_weekly_report = _report_decorator_factory(...)     # next to it
class AgentScheduler:  def register_bot_schedules(self, bot: Any) -> int:   # line 1146
# packages/ai-parrot-server/src/parrot/scheduler/models.py:12 — CREATE TABLE navigator.agents_scheduler (callbacks JSONB …)
# packages/ai-parrot/src/parrot/scheduler/__init__.py:15-16 — lazy re-export map to parrot.scheduler.manager (server package)

# From parrot_tools/o365/sharepoint.py
class ListSharePointFilesTool(O365Tool):                    # line 41
class SearchSharePointFilesTool(O365Tool):                  # line 232
class DownloadSharePointFileTool(O365Tool):                 # line 369
class UploadSharePointFileTool(O365Tool):                   # line 523
# From parrot_tools/o365/onedrive.py
class ListOneDriveFilesTool(O365Tool):                      # line 34
class SearchOneDriveFilesTool(O365Tool):                    # line 147
class DownloadOneDriveFileTool(O365Tool):                   # line 242
# From parrot_tools/o365/mail.py
class SearchEmailTool(O365Tool):                            # line 211
class ListMessagesTool(O365Tool):                           # line 578
class GetMessageTool(O365Tool):                             # line 747
class DownloadAttachmentTool(O365Tool):                     # line 901
# (per-user OAuth in parrot_tools/o365/oauth_toolkit.py; bundle.py groups SharePoint/OneDrive toolkits)

# From parrot_tools/graphindex/toolkit.py (FEAT-520 temporal plane — deferred by D6)
class GraphIndexToolkit(AbstractToolkit):                   # line 110
    async def graph_as_of(self, timestamp: str) -> dict:                       # line 1214
    async def graph_concept_history(self, concept_id: str) -> dict:            # line 1246
    async def graph_diff(self, concept_id: str, t1: str, t2: str) -> dict:     # line 1270

# From packages/ai-parrot-loaders/src/parrot_loaders/
#   pdf.py, pdfmark.py, docx.py, basepdf.py (OCR language attr at line 34), ocr/__init__.py (OCRBackend, get_ocr_backend)
#   ocr.get_ocr_backend is called only from image.py
# From packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py
class ExtractDataSource(ABC):                               # line 50
    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:   # line 62
    async def extract(self, fields: list[str] | None = None, filters: dict[str, Any] | None = None) -> ExtractionResult:   # line 70
    async def list_fields(self) -> list[str]:               # line 91
# From packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py
class DataSourceFactory:                                    # line 13 — _api_registry line 32
    @classmethod
    def register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None:   # line 35
    def get(self, source_name: str, source_config: dict[str, Any] | None = None) -> ExtractDataSource:   # line 46

# From parrot/knowledge/ontology/refresh.py
class RefreshReport(BaseModel):                             # line 41
class OntologyRefreshPipeline:                              # line 61
    def __init__(self, tenant_manager, graph_store, discovery: RelationDiscovery, datasource_factory,
                 cache: OntologyCache, vector_store=None, source_configs=None) -> None:   # line 76
    async def run(self, tenant_id: str, domain: str | None = None) -> RefreshReport:     # line 94
    # _refresh_entity (line 145): factory.get(entity_def.source, cfg) → source.extract(fields=property_names)
    #   → graph_store.upsert_nodes → soft_delete_nodes(vanished) → discovery.discover(...) per field_match relation
# From parrot/knowledge/ontology/discovery.py
class RelationDiscovery:                                    # line 52 — __init__(llm_client=None, review_dir=None) line 71
    async def discover(self, ctx: TenantContext, relation_def: RelationDef,
                       source_data: list[dict], target_data: list[dict]) -> DiscoveryResult:   # line 79
    # lazy `from rapidfuzz import fuzz` at lines 248 and 400 — UNDECLARED dependency today
# From parrot/knowledge/ontology/graph_store.py (additional)
    async def soft_delete_nodes(self, ctx, collection: str, keys: list[str]) -> None:        # line 478 — sets _active=false
    async def edges_incident(self, ctx, collection: str, node_id: str) -> list[dict]:         # line 725
    async def remove_edge_by_triple(self, ctx, collection: str, source_id: str, target_id: str, kind: str) -> bool:   # line 752
# From parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:
    def resolve(...)                                        # line 92 — builds TenantContext (base + domains/<domain>.ontology.yaml)
# From parrot/knowledge/ontology/schema.py
class TenantContext(BaseModel):                             # line 529 — tenant_id, arango_db, pgvector_schema, ontology: MergedOntology
# From parrot_tools/legal/boe/sync.py — the orchestration shape the loader copies
async def sync_boe(tenant_id: str, since: date | None = None) -> RefreshReport:   # line 24 — pipeline.run("legal") then edge bridge; no scheduler import
async def _sync_provenance_edges(ctx, graph_store, boe_source) -> tuple[dict[str, DiscoveryStats], list[str]]:   # line 106 — property edges via create_edges
# From parrot_tools/legal/boe/datasource.py
    def _target_entity(self, fields: list[str] | None) -> str:   # line 170 — infer entity from requested fields
```

#### Verified Imports
```python
from parrot.knowledge.bookstore.models import BookCard, CardDraft, TocEntry          # bookstore/models.py
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc, sample_sections, generate_card_fields, fallback_card_fields
from parrot.knowledge.bookstore.catalog import CatalogStore                          # bookstore/catalog.py:163
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError             # bookstore/library.py:133 / 100
from parrot.knowledge.bookstore.config import LibraryLocation, resolve_locations    # bookstore/config.py:31 / 78
from parrot.knowledge.bookstore._llm import resolve_adapter                          # bookstore/_llm.py:42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                      # used by bookstore/library.py:28
from parrot.knowledge.pageindex.content_store import NodeContentStore                # used by bookstore/library.py:27
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter               # pageindex/llm_adapter.py:42
from parrot.knowledge.ontology.parser import OntologyParser                          # ontology/parser.py:19
from parrot.knowledge.ontology.merger import OntologyMerger                          # ontology/merger.py:29
from parrot.knowledge.ontology import OntologyGraphStore, OntologyRAGMixin, TenantOntologyManager, TenantContext, MergedOntology   # ontology/__init__.py:2-7
from parrot.knowledge.ontology.schema import OntologyDefinition, TraversalPattern, AuthorizationRule, PropertyDef
from parrot.knowledge.ontology.authorization import AuthorizationChecker             # ontology/authorization.py:43
from parrot.knowledge.ontology.entity_resolver import EntityResolver                 # ontology/entity_resolver.py:93
from parrot.knowledge.ontology.intent import OntologyIntentResolver                  # ontology/intent.py:48
from parrot.tools.toolkit import AbstractToolkit                                     # tools/toolkit.py:206
from parrot.bots.agent import Agent                                                  # used by parrot_tools/legal/librarian/agent.py
from parrot_tools.legal.librarian.models import SpanRef, LegalAnswer                 # precedent only
```

#### Key Attributes & Constants
- `AbstractToolkit.tool_prefix` → `str | None` (tools/toolkit.py:257); prefixed name is `f"{tool_prefix}{prefix_separator}{method}"`, idempotent.
- `AbstractToolkit.confirming_tools` → `frozenset[str]` of **method names** (tools/toolkit.py:275, used at :686); stable regardless of prefix.
- `PropertyDef.type` → closed `Literal[...]` of 7 values (ontology/schema.py:30).
- `EntityExtractionRule.resolver` → 4 values (ontology/schema.py:142 block).
- `AuthorizationRule.rule` → 5 values (ontology/schema.py:185-191).
- `TraversalPattern.post_action` → `"vector_search" | "tool_call" | "none"` (ontology/schema.py:289).
- `base.ontology.yaml`: `Employee.key_field = employee_id` (line 11), `Department.key_field = department_id` (line 42), relations `reports_to` (79), `belongs_to` (91), `has_role` (103); patterns `find_manager`, `find_department`, `find_team`.
- `legal.ontology.yaml`: `article_in_force` pattern (line 158), `versions[*].text` view path (line 150) — the copied conventions.
- `bookstore/_llm.py`: `ENV_LLM = "PARROT_BOOKSTORE_LLM"`, `ENV_LLM_LIGHT = "PARROT_BOOKSTORE_LLM_LIGHT"` (lines 36-37) — a `PARROT_CONTRACTS_LLM` analogue is expected.
- `BookCard.source_format` → `Literal["pdf","md","txt","epub","mobi","docx"]`; `ContractCard` narrows to `pdf|docx|md|txt`.
- Compliance seeds: `parrot_tools/security/reports/mappings/soc2_controls.yaml`, `hipaa_controls.yaml`, `pci_dss_controls.yaml` (no `iso27001`, `gdpr`, `ccpa`, `nist_800_53`, `cyber_insurance` mapping files exist — those ids need a hand-written seed).
- Dependencies (workspace pyprojects): `python-docx==1.1.2` (ai-parrot, ai-parrot-tools, ai-parrot-loaders), `mammoth` (loaders `document` extra, tools), `asyncpg>=0.29` (ai-parrot), `python-arango-async==1.2.0` (ai-parrot-embeddings), `rapidfuzz>=3.0` (**only** `ai-parrot-tools[scraping]`; 3.11.0 installed in the venv).
- Tests convention: `packages/ai-parrot/tests/knowledge/{bookstore,ontology,pageindex,graphindex}/` and `packages/ai-parrot-tools/tests/legal/`.
- Admin UI: `packages/ai-parrot-server/ui/` is Svelte `^5.55.7` (`package.json`), pages `Home`, `Login`, `Dashboard`, `Agents` only.
- Scheduler: `ScheduleType` enum and the `@schedule` decorator live in the **server** package; `parrot.scheduler` in core is a lazy re-export shim (`packages/ai-parrot/src/parrot/scheduler/__init__.py`).

### Does NOT Exist (Anti-Hallucination)
- ~~`claude/contracts-agent-definition.md`~~ — the path cited in the design doc header is wrong; the product definition lives at **`sdd/proposals/contracts-agent-definition.md`** (resolved).
- ~~`parrot/knowledge/contracts/`~~ and every symbol in it (`ContractCard`, `Obligation`, `FieldProvenance`, `ContractVersion`, `ContractHeaderDraft`, `ObligationsDraft`, `ContractCatalogStore`, `ContractLibrary`, `ContractGraphLoader`, `ContractsToolkit`, `ContractsAgent`, `ContractAnswer`, `Citation`, `HandoffBrief`, `select_carding_nodes`, `assemble_card`, `verify_card`, `refresh_card` for contracts) — all **to be created**.
- ~~`ontology/defaults/domains/contracts.ontology.yaml`~~ — the file lives only in `sdd/proposals/`; it must be copied into the defaults dir (or an `ontology_dir` configured) for `TenantOntologyManager` to find `domain="contracts"`.
- ~~`parrot.knowledge.legal.BOEDataSource`~~ — it is `parrot_tools.legal.boe.datasource.BOEDataSource`, an `ExtractDataSource`. The graph-writing precedent is the pair `OntologyRefreshPipeline` + `sync_boe/_sync_provenance_edges`; `ContractGraphLoader` is designed on that pair (see *Feature Description*), not as a bespoke writer.
- ~~`rapidfuzz` declared anywhere in `ai-parrot`~~ — `ontology/discovery.py` imports it lazily; no extra lists it (to be fixed by the decided `graphindex` extra addition).
- ~~`PropertyDef.type == "datetime"`~~ / nested model property types — not allowed; `versions` must be `list`.
- ~~`CatalogStore.expiring()` / `CatalogStore.verification_queue()` / `find_by_source_uri()`~~ — not on the bookstore store; new to `ContractCatalogStore`.
- ~~a public `docx_to_markdown` helper in bookstore~~ — only the private `Bookstore._docx_to_markdown` (library.py:1073).
- ~~a generic "card family" / `DocumentCard` base~~ — bookstore has none (Option B would create it).
- ~~`PostgresPersistence` as a catalog backend~~ — it persists `UniversalNode` graphs (graphindex), not cards; the phase-2 Postgres catalog is new code that may only borrow its pool/DDL idioms.
- ~~`rapidfuzz` as a core dependency~~ — only in an ai-parrot-tools extra.
- ~~a SharePoint/OneDrive **delta** query~~ — `parrot_tools.o365` has list/search/download/upload tools (verified) but no `/delta` support anywhere (grep on `delta` returns nothing in `sharepoint.py`, `onedrive.py`, `base.py`); the "new & changed every few hours" watcher must poll `List*`/`Search*` + sha compare, or add a Graph delta tool in phase 2. `parrot/interfaces/sharepoint.py` (`SharepointClient`) is upload-oriented and is not the reuse target.
- ~~an OCR path for scanned PDFs in `parrot_loaders.pdf`/`basepdf`~~ — the OCR backend factory exists (`parrot_loaders/ocr/`) but only `image.py` calls it; scanned-PDF ingestion is new wiring.
- ~~a verification-queue page in the admin UI~~ — `ai-parrot-server/ui` has only Home/Login/Dashboard/Agents pages.
- ~~an ontology-level audit log~~ — `OntologyRAGMixin`/`AuthorizationChecker` contain no audit persistence (grep `audit` finds only `graph_store.py` and `concept_catalog/service.py` in the ontology package); the "full audit log" needs a new answer-audit record.
- ~~`schedule_daily_report` in core~~ — defined in `ai-parrot-server` (`parrot/scheduler/manager.py:173`); core only re-exports lazily. Watchers require the server distribution.
- ~~`conflicts_with` / `references_obligation` relations, `ComplianceRequirement` entity, `requires_compliance` pattern~~ — named in the product definition, absent from `contracts.ontology.yaml` (see the reconciliation table).
- ~~`graph_as_of` on the contracts graph~~ — `GraphIndexToolkit.graph_as_of/graph_concept_history/graph_diff` exist (parrot_tools/graphindex/toolkit.py:1214-1270) but operate on the GraphIndex concept plane, not on the ontology's Arango graph; D6 keeps contract versions embedded in `versions[]`.
- ~~`SpanVerifier` reusable as-is for contracts~~ — it is bound to BOE `SpanRef` (norma/articulo, char offsets over a normalised payload); the contracts citation check must be re-implemented over `(contract_id, node_id, quote)`.
- ~~`same_department` proven to work with a `Contract` target~~ — `AuthorizationChecker._check_same_department` exists (authorization.py:293) but was written for Employee-shaped targets; whether it reads `Contract.department` without change is **unverified** (open question).
- ~~ISO 27001 / GDPR / CCPA / NIST 800-53 compliance mapping files~~ — only SOC 2, HIPAA, PCI DSS mappings exist under `parrot_tools/security/reports/mappings/`.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. The dependency chain is `models` →
  {`carding`, `catalog`} → `library` → `toolkit`/`agent`. The
  ontology YAML + `ContractGraphLoader` + merge test only need `models` and
  can run in a second lane while `carding`/`catalog`/`library` proceed.
  Phase-2 tasks (Postgres backend, SharePoint delta) depend on `catalog`
  and `library` respectively and can be separate worktrees later.
- **Cross-feature independence**: no in-flight feature touches
  `parrot/knowledge/bookstore/`, `parrot/knowledge/ontology/` or
  `parrot/tools/toolkit.py` (open features on 2026-09-09: FEAT-481
  fireflies-wiki-knowledgebase-agent, FEAT-526 meta-llm-client, plus
  done-with-issues voice/avatar features). The only shared surface is the
  new file under `ontology/defaults/domains/`, which nothing else edits.
  This feature does not modify any existing module.
- **Recommended isolation**: `per-spec` — one worktree
  `feat-<id>-contracts-card-ontology` from `dev`, tasks in dependency order;
  optionally `mixed` for the ontology+loader lane if two workers are
  available.
- **Rationale**: the feature is additive and self-contained, so a single
  worktree carries no merge risk with `dev`; splitting into many worktrees
  would only pay off for the one independent lane (YAML + loader).

---

## Open Questions

- [ ] **Module location**: everything in core `parrot/knowledge/contracts/`
  (bookstore precedent, and it imports bookstore/pageindex helpers), or the
  toolkit + agent + graph loader in `parrot_tools/contracts/` per the
  CLAUDE.md "concrete toolkits live in ai-parrot-tools" rule (legal
  precedent)? — *Owner: Jesus Lara*
- [ ] **Answer layer shape**: ReAct `ContractsAgent(OntologyRAGMixin, Agent)`
  with the `contracts_*` toolkit (Option A) or a fixed fail-closed crew
  (Option D)? The citation check is adopted either way. — *Owner: Jesus Lara*
- [ ] **Obligation granularity**: one `Obligation` per clause (proposed) or
  one per `kind` per contract? — *Owner: Jesus Lara*
- [ ] **`ComplianceStandard` seed list and aliases**: proposed
  `soc2, iso27001, gdpr, ccpa, hipaa, pci_dss, nist_800_53, cyber_insurance`;
  only SOC 2 / HIPAA / PCI DSS have mapping files in
  `parrot_tools/security/reports/mappings/`. Hand-write the rest? — *Owner: Jesus Lara*
- [ ] **Party identity**: suffix normalisation list
  (`Inc|Corp|Corporation|Ltd|LLC|S.L.|S.A.`) plus a curable alias table —
  where does Bob edit aliases (CLI, `verify_card`, catalog table)? — *Owner: Jesus Lara*
- [ ] **Owner / department source**: SharePoint folder rule, library metadata
  (`Author`, custom columns), or manual assignment in the verification
  queue? Neither is in the document text. — *Owner: Jesus Lara*
- [ ] **Postgres from the pilot or after**: D8 says Postgres from day 1 if the
  pilot has ≥ 3 concurrent users with roles. How many pilot users? — *Owner: Jesus Lara*
- [x] **`rapidfuzz` dependency** — *Owner: Jesus Lara*: add `rapidfuzz>=3.0`
  to the `graphindex` extra of `packages/ai-parrot/pyproject.toml`
  (also covers the undeclared lazy import in `ontology/discovery.py`);
  contracts imports it lazily and documents `ai-parrot[graphindex]`.
- [x] **DOCX conversion** — *Owner: Jesus Lara*: extract
  `Bookstore._docx_to_markdown` into a public `docx_to_markdown` helper in
  the bookstore package; the private method delegates to it.
- [ ] **`same_department` on a `Contract` target**: verify whether
  `AuthorizationChecker._check_same_department` reads `Contract.department`
  as-is or needs a target-entity hook before the rule is used in phase 2. — *Owner: implementer (spike in TASK for ontology)*
- [ ] **Bilingual corpus**: add `text_es` analyzers to `contracts_view` as in
  `legal_articulos_view`, or English-only for the pilot? — *Owner: Jesus Lara*
- [x] **Missing product doc** — *Owner: Jesus Lara*: it exists at
  `sdd/proposals/contracts-agent-definition.md` (the design doc's
  `claude/…` path is stale); reconciled into this brainstorm on 2026-09-09.
- [ ] **LLM-judged relations** (`conflicts_with`, `references_obligation`
  from the product definition): in scope for v1 as bookstore-style
  `relations.py` judgements written as extra edges, or dropped in favour
  of the deterministic graph only? — *Owner: Jesus Lara*
- [ ] **Watchers' home**: `@schedule` methods on `ContractsAgent` (needs
  `ai-parrot-server` at runtime) or a standalone scheduled job class?
  Where should `renewals_report` deliver by default (`send_result` email /
  Teams)? — *Owner: Jesus Lara*
- [ ] **Delta detection for "new & changed"**: poll `List*/Search*` + sha
  compare for the pilot, or add a Microsoft Graph `/delta` tool to
  `parrot_tools.o365` first? — *Owner: Jesus Lara*
- [ ] **Scanned PDFs in the pilot**: wire `parrot_loaders.ocr` into the PDF
  path in this spec, or exclude scans from the 50–100 pilot set? — *Owner: Jesus Lara*
- [ ] **Answer audit + retirement**: new `contract_answers` table in the
  catalog (question, user, `answer_kind`, `pattern`, citations,
  authorization outcome, `retired_by`) — in this spec or a shared
  answer-audit facility? — *Owner: Jesus Lara*
- [ ] **Verification UI**: confirm it is a separate spec
  (`contracts-verification-ui`) against the Svelte admin UI, with this spec
  exposing only the API/tool surface. — *Owner: Jesus Lara*
- [ ] **Temporal plane**: keep D6 (embedded `versions[]`) for the pilot and
  revisit FEAT-520 `graph_as_of` once the ontology graph and GraphIndex
  plane converge? — *Owner: Jesus Lara*
- [x] **Flow type / base branch** — *Owner: Claude*: defaulted to
  `type: feature`, `base_branch: dev` (no hotfix semantics; additive
  feature work).
