# Legal LLM Wiki — Design skeleton on ai-parrot (brainstorm → pre-proposal)

> Context: one or more "brains" (LLM Wikis) for a Spanish lawyer, fed with Spanish + EU legislation and case law, stored as knowledge graphs in ArangoDB via `GraphIndex`, with CENDOJ used only as a verification/enrichment toolkit. Goal: answers that are **citable against primary sources with temporal validity**, never model memory.
>
> Status: skeleton. Every `⚠️ VERIFY` must be grepped against `main` before `/sdd-proposal`. Items marked `[assumed]` are design choices pending discussion, not facts about the repo.

---

## 0. Reuse inventory (what already exists, to be confirmed)

| Piece | Where (`⚠️ VERIFY`) | Role here |
|---|---|---|
| Knowledge graph | `parrot/knowledge/graphindex/` + `GraphIndexToolkit` (`ground_claim`, `traverse`, `find_references`) | Core store for norms + case law |
| Ontology layer | `parrot/knowledge/ontology/` (OntoGraph) | Legal concept vocabulary, Materia taxonomy |
| KB routing | `KnowledgeRouter` (FEAT-200; deterministic concept vocabulary + embedding fallback + namespaced `concept_id`) | Ontological router: query → domain graph(s) |
| Vector store | PgVector (`VectorStoreSearchTool`) | Chunk-level semantic retrieval per domain |
| Loaders | `parrot_loaders` (`PDFMarkdownLoader`, `HTMLLoader`, `WebLoader`, `MarkdownLoader`) | BOE/EUR-Lex/TC/HUDOC ingestion |
| Structured outputs | `StructuredOutputConfig` / `ask(structured_output=Model)` | Mandatory citations |
| Anti-hallucination | `GroundednessReport`, deterministic-first + LLM-as-judge | Citation grounding against retrieved nodes |
| Toolkit pattern | `AbstractToolkit` (independent named tools, not branching single tools) | Every source = toolkit |
| Scheduler | `parrot/scheduler` (`@schedule`) | Daily incremental sync |
| Orchestration | `AgentCrew.run_flow`, `ToolNode` | Deterministic retrieval → LLM synthesis DAG |

Does NOT exist (to be created): any legal-domain toolkit, ECLI/BOE-id parsing utilities, temporal-validity traversal, `LegalAnswer` contract.

---

## 1. Governing principles

1. **Bulk only where the license allows.** BOE, EUR-Lex/CELLAR, TC, datos.gob.es → bulk + incremental. HUDOC → tolerated JSON endpoint, throttled. **CENDOJ → never bulk**; on-demand, human-paced, cached.
2. **Identifiers are canonical keys, not text.** `ECLI:ES:TS:2023:1234`, `BOE-A-2015-10566`, CELEX `32016R0679`. Every node `_key` derives from one of them. No node without a stable public id.
3. **Temporal validity is a graph property.** `modifica`/`deroga` edges carry `from_date`/`to_date`; the question "which version of art. X applied on date D" is a deterministic traversal, not an LLM guess.
4. **Deterministic retrieval, LLM synthesis.** Router, traversal, validity filtering, source precedence: code. The LLM explains, compares and drafts over already-retrieved, already-verified material.
5. **Every legal statement carries a citation to a retrieved node**, and every case-law citation carries `verified: bool`. Unverified ⇒ rendered as "pendiente de confirmación", never silently dropped nor silently trusted.
6. **Read-only agents.** Ingestion toolkits (writers) and advisory agents (readers) are never mounted together. `cendoj_fetch` is the single sanctioned write path from an agent, and it writes through the ingestion pipeline, not raw upserts.

---

## 2. Sources and toolkits

Each source is an independent toolkit. Writers live in ingestion scripts/schedules; readers are mounted on agents.

### 2.1 `BOEToolkit` (writer + reader)
- `boe_sync_consolidated(since: date)` — API/XML dump, legislación consolidada. Emits `Norma`, `Artículo` (one node per article, per version), `modifica`/`deroga` edges with dates.
- `boe_get_norm(boe_id)` — reader; returns metadata + article list.
- `boe_get_article(boe_id, article, as_of: date)` — reader; returns the version in force on `as_of` (deterministic).

### 2.2 `EURLexToolkit` (writer + reader)
- `eurlex_sync(celex_prefix | sector, since)` — SPARQL on CELLAR. CELLAR is already RDF: Work/Expression/Manifestation + `cites`/`amends`/`repeals` map 1:1 to graph edges. Prefer the Work level as `Norma`, Expression (language=ES) as text source.
- `eurlex_get(celex)` — reader.
- `curia_get(ecli)` — CJEU judgments, ECLI:EU:C:… (same CELLAR, different sector).

### 2.3 `TCToolkit` (writer + reader)
- `tc_sync(since)` — Tribunal Constitucional HJ database; manageable volume.
- `tc_get(ecli)` — reader.

### 2.4 `HUDOCToolkit` (reader, lazy-ingest)
- `hudoc_search(query, articles?, respondent="ESP", max=5)`
- `hudoc_get(ecli | itemid)` — fetch + lazy ingest into the graph.
- Throttled, circuit-breaker on 429. `[assumed]` no bulk in v1.

### 2.5 `CENDOJToolkit` (reader, lazy-ingest, **verification role**)
- `cendoj_verify(ecli | roj) -> CendojVerification` — confirms existence, court, date, ponente; returns official URL and `mismatches: list[str]`. This is the anti-hallucination gate for Spanish case law.
- `cendoj_search(query, tribunal?, materia?, fecha_desde?, fecha_hasta?, max<=5)` — discovery of judgments missing from the graph. Hard cap enforced in code.
- `cendoj_fetch(ecli | roj) -> Sentencia` — full text; **ingests into the graph** via the standard pipeline (node + LLM-extracted `cita`/`aplica_artículo` edges, all marked `extraction="llm"`).
- Cross-cutting: single shared client (one semaphore for the whole process, ~1 req / 3–5 s with jitter), persistent cache in Arango (judgments are immutable; TTL effectively infinite), circuit breaker on captcha/429 → returns `verifiable=False`, never retries aggressively. Raw HTML stored alongside parsed text (markup drifts).
- Legal posture: point queries at human pace, equivalent to a lawyer's own use. Document this in the toolkit docstring.

#### 2.5.1 `CENDOJToolkit` — detailed design

**Package / layout** `[assumed]`: `ai-parrot-tools` → `parrot_tools/legal/cendoj/` with `client.py` (shared HTTP client), `parser.py`, `models.py`, `toolkit.py`. Shared identifier utils in `parrot_tools/legal/ids.py` (ECLI/ROJ/BOE/CELEX regex + normalisation), reused by every legal toolkit.

**Contracts (Pydantic v2, `parrot.interfaces.legal` `[assumed]`)**
```python
class CaseRef(BaseModel):
    ecli: str | None; roj: str | None
    court: str; chamber: str | None; date: date; ponente: str | None
    url: str

class CendojVerification(BaseModel):
    verifiable: bool            # False ⇒ source unavailable (captcha/429/timeout), not "does not exist"
    verified: bool              # True only if found AND no mismatches
    found: CaseRef | None
    mismatches: list[str]       # e.g. "date: graph=2021-03-02 cendoj=2021-03-09"
    from_cache: bool; checked_at: datetime

class CendojSearchHit(BaseModel):
    ref: CaseRef; snippet: str; in_graph: bool

class CendojDocument(BaseModel):
    ref: CaseRef; text: str; raw_html_ref: str; ingested: bool; graph_key: str | None
```

**Tools** (three independent named tools; never one branching tool)

| Tool | Signature | Behaviour |
|---|---|---|
| `cendoj_verify` | `(ecli: str \| None, roj: str \| None, expected: CaseRef \| None)` | Cache → graph → CENDOJ by id. Compares court/date/ponente against `expected` (taken from the graph node if omitted). Writes `verified`, `verified_at`, `verifier="cendoj"` on the `sentencia` node. Budget: 1 request. |
| `cendoj_search` | `(query: str, tribunal: Literal[...] \| None, materia: str \| None, fecha_desde: date \| None, fecha_hasta: date \| None, max: int = 5)` | `max` clamped to 5 in code. Annotates each hit with `in_graph`. Never ingests. |
| `cendoj_fetch` | `(ecli: str \| None, roj: str \| None)` | Cache → CENDOJ. Stores raw HTML + parsed text, then hands the document to the **ingestion pipeline** (node + regex edges; LLM edges optional, flagged). Returns `graph_key`. |

**Shared client (one per process, not per agent)**
- `asyncio.Semaphore(1)` + min interval 3–5 s with jitter; shared across agents/Wikis (`[assumed]` process-level singleton registered in the ToolManager, like other shared resources).
- Circuit breaker: on HTTP 429, captcha page, or 3 consecutive timeouts → open for 15 min; tools return `verifiable=False` immediately while open.
- Cache in Arango collection `cendoj_cache` keyed by normalised ECLI/ROJ; judgments are immutable ⇒ no TTL. Negative results cached 24 h only (a judgment may be published later).
- User-Agent identifying the firm; no parallel sessions; honour any `Retry-After`.
- `permission_context` required: the tool records which user triggered the request (AuditLedger entry) — consultation pattern must be attributable to a lawyer, not a crawler.

**Parser**
- Tolerant HTML parser; on failure keeps raw HTML and returns `text=None` with error, never silently empty.
- ECLI/ROJ extracted from the document header and cross-checked with the requested id (mismatch ⇒ `verified=False`).

**Agent policy (instructions + post-check)**
- `LegalAnswerAgent` may call `cendoj_verify` freely within a budget (`[assumed]` 5 per execution), `cendoj_search` at most 2 times, `cendoj_fetch` at most 2 times. Budgets enforced in code via the ToolManager, not by prompt.
- No Spanish case-law citation reaches `confidence="verified"` without a `verified=True` node (from this or a previous execution).

#### Spike OQ3 — CENDOJ checklist
- [ ] Locate the search endpoint and parameters (form POST) and the per-document URL pattern by ROJ; confirm ECLI lookup path.
- [ ] Measure the real throttle threshold: run 20 sequential requests at 5 s, 3 s, 2 s intervals from one IP; record first 429/captcha.
- [ ] Confirm date/court/materia filters actually filter server-side (compare result counts).
- [ ] Confirm the document page exposes ECLI, ROJ, court, chamber, date, ponente in stable markup; save 5 samples as parser fixtures.
- [ ] Check robots.txt and the current terms of use text; store a copy with date in the spec.
- Exit criterion: `verify` and `fetch` work for 10 known TS/AP judgments with zero captchas at the chosen interval; `search` filters confirmed or dropped from v1.

### 2.6 Optional commercial backends
`VLexToolkit` / `AranzadiToolkit` implementing the same `verify/search/fetch` contract if the firm holds a license. Same interface, different backend → router treats them as higher-trust verifiers.

---

## 3. Graph model (GraphIndex, ArangoDB)

### 3.1 Layering — several graphs per knowledge domain
- **L0 — Ontology (shared):** `Concepto` (legal concepts, synonyms, ES/EN/EU-term aliases), `Materia` taxonomy (civil, mercantil, laboral, penal, administrativo, constitucional, UE, DDHH), `Tribunal`.
- **L1 — Norms (shared):** `Norma`, `Artículo` (versioned), `Norma_UE`. Shared because one norm spans many materias.
- **L2 — Case law, one named graph per Materia:** `Sentencia` nodes + domain-specific edges. Each L2 graph is a separate GraphIndex namespace (`legal:civil`, `legal:laboral`, …) so an LLM Wiki can mount one or several.
- **Decided (OQ1):** a single ArangoDB database; L0/L1 and every L2 are GraphIndex namespaces (`legal:core`, `legal:civil`, `legal:laboral`, …) over shared collections, discriminated by a `namespace` attribute and exposed as Arango named graphs. Tenancy (if ever needed) is a second discriminator, not a second DB.

### 3.2 Collections (vertices)
| Collection | `_key` | Key fields |
|---|---|---|
| `norma` | BOE id / CELEX | title, rank (ley orgánica/ley/RD/…), publisher, publication_date, entry_into_force, status |
| `articulo` | `{norma}:{art}` | number, norma_ref, current_version, `versions[]` = `{n, text, valid_from, valid_to, modified_by (norma key), kind, source, derived}` — **single node with embedded version history (OQ2 decided)**; see §3.5 |
| `sentencia` | ECLI (fallback ROJ) | court, chamber, date, ponente, roj, ecli, summary, verified, verified_at, source, raw_html_ref |
| `tribunal` | slug | name, level, jurisdiction |
| `concepto` | namespaced `concept_id` (FEAT-200 convention) | label, aliases[], materia_refs[] |
| `materia` | slug | label, parent |
| `chunk` | `{parent_key}:{version_n}:{n}` | text, embedding ref, parent_ref, version_n, valid_from, valid_to, offset — chunks are per article version so vector retrieval can filter by `as_of` |

### 3.3 Edge collections
| Edge | From → To | Attributes |
|---|---|---|
| `modifica` | norma → articulo | version_n (target version created), from_date, kind (redacción/adición/supresión) — mirrors `versions[].modified_by` |
| `deroga` | norma → norma/articulo | date, scope (total/parcial) |
| `cita` | sentencia → sentencia/norma/articulo | extraction (regex/llm), confidence |
| `aplica_articulo` | sentencia → articulo | as_of (date of facts), version_n (resolved from as_of at ingest), extraction, confidence |
| `interpreta` | sentencia → concepto | extraction, confidence |
| `confirma` / `revoca` | sentencia → sentencia | instance chain |
| `transpone` | norma → norma_UE | — |
| `pertenece_a` | sentencia/norma → materia | weight |
| `trata` | articulo/sentencia → concepto | weight |

Edges extracted by regex (ECLI/ROJ/BOE/CELEX/article patterns) are `extraction="regex", confidence=1.0`; LLM-extracted ones are explicitly lower confidence and excluded from "verified" answers unless corroborated.

### 3.4 Key deterministic traversals (no LLM)
- `article_in_force(articulo, as_of)` — O(1): select `versions[]` entry with `valid_from <= as_of < valid_to` (no traversal needed); returns `derived` so the answer layer can flag "vigencia estimada por consolidado". `modifica` edges are kept for provenance/traversal from the amending norm, not for validity resolution.
- `case_chain(sentencia)` — `confirma`/`revoca` up to Supreme/TC.
- `what_applies(concepto, materia, as_of)` — concepto → `trata` → articulo in force → `aplica_articulo` ← sentencia (verified first).

### 3.5 Version derivation per source

Same `versions[]` shape everywhere; only the derivation differs.

**BOE — legislación consolidada (authoritative, Sprint 1).** The consolidated XML already splits each article into dated wording blocks and the norm's "análisis" metadata carries `modifica`/`deroga` relations with BOE ids.
```
versions[n] = {
  n, text,
  valid_from  = block.fecha_vigencia,
  valid_to    = versions[n+1].valid_from | null,
  modified_by = BOE-A-… of amending norm (null for n=0),
  kind        = redacción | adición | supresión,   # supresión ⇒ text=null
  source      = "boe_consolidada",
  derived     = false
}
```

**EUR-Lex / CELLAR — consolidated texts (derived by diff, spike OQ4).** CELLAR has no per-article versions; it has whole-norm consolidated texts, each with its own dated CELEX (`02016R0679-20160504`: leading `0` = consolidated). `amends`/`repeals` exist at Work level with amending act + date but do not say which article changed.
1. SPARQL: list all consolidated CELEX ids + dates for a Work (`⚠️ VERIFY` exact predicate, e.g. `cdm:work_consolidates` / `consolidated_by`).
2. Download each consolidated Expression (lang=ES) in Formex XML (HTML fallback); parse into articles.
3. Diff article text between consecutive consolidations; a change creates `versions[n+1]` with `valid_from` = consolidation date and `modified_by` = amending act whose `amends` date matches.
4. `source="cellar_diff", derived=true` — the real entry-into-force date may differ from the consolidation date.

**Case law (TC/TS/TJUE/TEDH).** Immutable; no `versions[]`.

**Answer layer.** A citation whose resolved version is `derived=true` is rendered with "vigencia estimada por consolidado" and never upgrades a claim to `verified` on its own.

#### Spike OQ4 — CELLAR checklist (confirmed as a spike)
- [ ] SPARQL returns the full list of consolidated CELEX ids with dates for 3 Works: RGPD `32016R0679`, Directiva 2019/1158 (conciliación), Reglamento Bruselas I bis `32012R1215`.
- [ ] Formex XML is retrievable for every consolidation in ES; article segmentation is stable across consolidations (numbering, bis/ter).
- [ ] Article-level diff yields a plausible number of versions (manual check against the "amended by" list on EUR-Lex).
- [ ] `amends` edges at Work level carry a date that can be matched to consolidation dates (tolerance window to define).
- [ ] Rate limits / batch size for CELLAR downloads; incremental strategy (`since` on consolidation date).
- Exit criterion: for the 3 Works, `article_in_force(as_of)` returns the expected wording on 5 hand-picked dates each.

---

## 4. Ontological router and retrieval

### 4.1 Router (deterministic-first, per FEAT-200)
1. Concept vocabulary match (L0 aliases) → `Materia` candidates and `concept_id`s.
2. Embedding fallback (`Qwen3-Embedding-0.6B` `[assumed]` per existing recommendation) only when vocabulary match is empty/ambiguous.
3. Output: `RoutingDecision { materias[], concept_ids[], graphs[], verifiers[], as_of: date | None }`. `as_of` is extracted from the query (date of facts) or defaults to today and is **stated back to the user**.

### 4.2 Retrieval DAG (AgentCrew, `ToolNode`s before any agent)
```
query
  → ToolNode route            (RoutingDecision)
  → ToolNode graph_retrieve   (L1 articles in force as_of + L2 sentencias via traversals)
  → ToolNode vector_retrieve  (chunks, filtered by materia + as_of)
  → ToolNode verify           (cendoj_verify on every ES sentencia lacking verified=True; budget-capped)
  → ToolNode merge            (source precedence + dedupe by id)
  → LegalAnswerAgent          (structured_output=LegalAnswer, read-only toolkits)
  → ToolNode ground           (GroundednessReport: every citation must map to a retrieved id)
```

### 4.3 Source precedence (merge, deterministic)
1. Norm text in force on `as_of` (BOE/EUR-Lex) — authoritative.
2. TC / CJEU / ECtHR judgments (official sources, bulk-ingested).
3. TS / AN / TSJ / AP judgments **verified** via CENDOJ (or commercial backend).
4. Same, **unverified** (graph-only, LLM-extracted edges) — allowed only as "pendiente de confirmación".
5. Secondary/doctrinal material (if ever added) — never as sole support.
Conflicts between levels: higher wins and the conflict is surfaced, not resolved by the LLM.

---

## 5. Output contract

```python
class SourceRef(BaseModel):
    kind: Literal["norma", "articulo", "sentencia"]
    id: str                       # BOE id / CELEX / ECLI
    title: str
    url: str
    as_of: date | None            # version in force used
    verified: bool                # CENDOJ/TC/EUR-Lex confirmed
    verifier: str | None          # "cendoj" | "eurlex" | "tc" | "hudoc" | "vlex"
    snippet: str                  # retrieved text, not paraphrase

class LegalClaim(BaseModel):
    statement: str
    references: list[SourceRef] = Field(min_length=1)
    confidence: Literal["verified", "pending_verification"]

class LegalAnswer(BaseModel):
    as_of: date
    materias: list[str]
    claims: list[LegalClaim]
    pending: list[SourceRef]      # unverified citations, surfaced explicitly
    gaps: list[str]               # "no primary source retrieved for X"
    disclaimer: str               # not legal advice; review by the lawyer
```
Post-check: each `SourceRef.id` must be in the retrieval set of this execution; `confidence="verified"` requires `verified=True` on all its references. Violations ⇒ retry capped at 1, then return with the claim moved to `gaps`.

---

## 6. Open questions (close before `/sdd-proposal`)
- ~~OQ1~~ **Closed:** single Arango DB, GraphIndex namespaces. `⚠️ VERIFY` that current GraphIndex supports multiple namespaces over shared collections or needs a `namespace` filter added.
- ~~OQ2~~ **Closed:** single `articulo` node with embedded `versions[]`; chunks per version; `aplica_articulo` stores `version_n`.
- **OQ3** → **spike confirmed**, checklist in §2.5.1. `verify`/`fetch` can be specced in parallel; `search` is gated on the filter check.
- **OQ4** → **spike confirmed**, checklist in §3.5. Blocks EUR-Lex ingestion in Sprint 1; BOE is not blocked.
- **OQ5** Where does `as_of` extraction live: router (deterministic date parsing) or a tiny structured LLM call? Proposal: regex first, LLM only if none found.
- **OQ6** Lazy ingestion from `cendoj_fetch`: synchronous within the request, or enqueued (qworker) after answering?

---

## 7. Roadmap
1. **Spikes:** CENDOJ rate/captcha behaviour; CELLAR amends/repeals availability; GraphIndex namespace model.
2. **Sprint 1 — Norms graph, zero LLM.** BOE + EUR-Lex ingestion, `article_in_force` traversal, tests on known amendment chains (e.g. LOPDGDD vs RGPD transposition).
3. **Sprint 2 — Case law bulk.** TC + CJEU + HUDOC lazy; regex-only edges.
4. **Sprint 3 — CENDOJ toolkit + verification gate.** `verify` first, `fetch` with lazy ingest, `search` last.
5. **Sprint 4 — Router + retrieval DAG + `LegalAnswer`.** Single materia (pick the firm's main one), then multi-graph.
6. **Sprint 5 — LLM-extracted edges + groundedness.** Only after verified citations work end-to-end.

## External sources
- BOE datos abiertos / API: https://www.boe.es/datosabiertos/
- EUR-Lex SPARQL (CELLAR): https://eur-lex.europa.eu/content/help/data-reuse/webservice.html
- Tribunal Constitucional HJ: https://hj.tribunalconstitucional.es/
- CENDOJ: https://www.poderjudicial.es/search/
- HUDOC: https://hudoc.echr.coe.int/
- ECLI: https://e-justice.europa.eu/ecli
