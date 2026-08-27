# Legal LLM Wiki — Design skeleton on ai-parrot (brainstorm → pre-proposal)

> Context: one or more "brains" (LLM Wikis) for a Spanish lawyer, fed with Spanish + EU legislation and case law, stored as knowledge graphs in ArangoDB via `GraphIndex`, with CENDOJ used only as a verification/enrichment toolkit. Goal: answers that are **citable against primary sources with temporal validity**, never model memory.
>
> Status: skeleton. Every `⚠️ VERIFY` must be grepped against `main` before `/sdd-proposal`. Items marked `[assumed]` are design choices pending discussion, not facts about the repo.
>
> **Revision 2026-08-27** — revisited after an external design discussion. Sprint 1 (BOE
> norms graph, FEAT-449) is already implemented; this revision hardens the answer layer
> around three ideas the original skeleton under-specified: (a) the agent is a
> **librarian, not an oracle** — the returned payload is the evidence itself, the LLM's
> reading is a secondary, span-anchored section; (b) an **epistemic fail-closed
> invariant** — no assertion about the corpus without a verifiable span reference, hash
> included; (c) the **roadmap is reordered** — the librarian answer layer ships next,
> over the norms-only corpus, before any case-law ingestion. See §1 (principles 7–8),
> §5 (evidence model), §7 (roadmap), and the decision log at the end.

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

### 0.1 Verified against the repo — 2026-08-27

Sprint 1 landed (FEAT-449, `sdd/specs/legal-norms-graph-boe.spec.md`, 8/8 tasks done):

| Piece | Where (verified) | Note |
|---|---|---|
| BOE toolkit tree | `packages/ai-parrot-tools/src/parrot_tools/legal/boe/` (`models.py`, `parser.py`, `datasource.py`, `sync.py`, `queries.py`) + `legal/ids.py` | exists |
| `ArticleVersion` | `parrot_tools/legal/boe/models.py` | `n, text, valid_from, valid_to, modified_by, kind, source, derived` — **no `content_hash` field today** ⇒ retrofit required (§5.1) |
| Legal ontology | `parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml` | exists |
| Audit ledger | `parrot/security/audit_ledger.py:80` `AuditLedgerEntry`, `:296` `AuditLedger`, `:338` `async append()` | target for span-suppression records |
| Groundedness | `parrot/security/groundedness/evidence.py:31` `EvidenceIndex`, `scorer.py:74` `score()` | **atom-based** (money/percent/number/date/identifier), detection-only — it is NOT a span verifier; the quote/offset/hash verifier of §5 is new machinery, groundedness stays as a complementary numeric/identifier check |

### 0.2 Persona rationale (from the external discussion)

The lawyer is the **business persona**, not a demo persona: (1) the pain is acute and
billable — associate hours spent hunting case law; (2) professional secrecy turns
local-first from preference into obligation (client files cannot go to a RAG SaaS —
deontology, and in many jurisdictions regulation); (3) firms already pay heavily for
worse tools (Westlaw/vLex), so budget exists. The hardest persona's requirements —
mandatory citation, confidentiality, typed graph — harden the product for every other
persona: honest "no encontré" and page-level citations benefit the student and the
clerk too. FTS (and flat vector RAG) returns a repealed precedent with the same
confidence as a live one because they are textually equally similar to the query; only
a typed graph (`cita`, `revoca`, `confirma`, `distingue`) with court hierarchy and
temporal validity can answer "current precedents from higher courts on this issue".

---

## 1. Governing principles

1. **Bulk only where the license allows.** BOE, EUR-Lex/CELLAR, TC, datos.gob.es → bulk + incremental. HUDOC → tolerated JSON endpoint, throttled. **CENDOJ → never bulk**; on-demand, human-paced, cached.
2. **Identifiers are canonical keys, not text.** `ECLI:ES:TS:2023:1234`, `BOE-A-2015-10566`, CELEX `32016R0679`. Every node `_key` derives from one of them. No node without a stable public id.
3. **Temporal validity is a graph property.** `modifica`/`deroga` edges carry `from_date`/`to_date`; the question "which version of art. X applied on date D" is a deterministic traversal, not an LLM guess.
4. **Deterministic retrieval, LLM synthesis.** Router, traversal, validity filtering, source precedence: code. The LLM explains, compares and drafts over already-retrieved, already-verified material.
5. **Every legal statement carries a citation to a retrieved node**, and every case-law citation carries `verified: bool`. Unverified ⇒ rendered as "pendiente de confirmación", never silently dropped nor silently trusted. *(Revised 2026-08-27: `verified` here is **authority** verification — CENDOJ/TC/EUR-Lex confirming the source. **Existence** verification — the quoted span exists byte-for-byte in the stored payload with that hash — is a separate, mandatory gate that applies to every citation, including "pendiente de confirmación" ones. See §5.)*
6. **Read-only agents.** Ingestion toolkits (writers) and advisory agents (readers) are never mounted together. `cendoj_fetch` is the single sanctioned write path from an agent, and it writes through the ingestion pipeline, not raw upserts.
7. **The agent is a librarian, not an oracle. The LLM proposes, the evidence disposes.** The primary payload of every answer is the retrieved evidence itself — "these N documents contain relevant passages; here are the exact spans; go read them". The librarian's own reading (ranking/reading order, conflict flagging, corpus-scoped absence statements, temporal/procedural context narrated from deterministic traversals) is a clearly-labelled **secondary** section in which every sentence anchors to at least one span. An opinion may be *part of* the answer; it is never *the* answer. Conflicts between sources are flagged, never resolved by the LLM — resolution belongs to the lawyer.
8. **Epistemic fail-closed (the one-line invariant).** *The system cannot assert anything about the corpus without a verifiable span reference; without a citation, the answer is "no encontré".* Generation is stochastic; verification is deterministic: either the quoted span exists in the stored payload with that hash, or it does not. A librarian sentence that cannot be anchored is **suppressed and the suppression recorded** (count in the answer + `AuditLedger` entry) — never emitted silently, never rendered as "unverified". By construction the system can fail to find law; it cannot invent it. For a lawyer that asymmetry is everything: a false negative costs hours, a false positive costs the licence. Absence statements are always corpus-scoped ("not found in the consulted corpus for this query") — never ontological ("no case law exists on X"). This is the epistemic sibling of the fail-closed egress posture.

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
| `articulo` | `{norma}:{art}` | number, norma_ref, current_version, `versions[]` = `{n, text, valid_from, valid_to, modified_by (norma key), kind, source, derived, content_hash}` — **single node with embedded version history (OQ2 decided)**; `content_hash` = sha256 of the normalized version text, sealed at ingest (rev. 2026-08-27; see §5.1); see §3.5 |
| `sentencia` | ECLI (fallback ROJ) | court, chamber, date, ponente, roj, ecli, summary, verified, verified_at, source, raw_html_ref |
| `tribunal` | slug | name, level, jurisdiction |
| `concepto` | namespaced `concept_id` (FEAT-200 convention) | label, aliases[], materia_refs[] |
| `materia` | slug | label, parent |
| `chunk` | `{parent_key}:{version_n}:{n}` | text, embedding ref, parent_ref, version_n, valid_from, valid_to, offset, content_hash — chunks are per article version so vector retrieval can filter by `as_of`; `offset` + parent `content_hash` make every chunk a resolvable span into its parent payload (rev. 2026-08-27) |

### 3.3 Edge collections
| Edge | From → To | Attributes |
|---|---|---|
| `modifica` | norma → articulo | version_n (target version created), from_date, kind (redacción/adición/supresión) — mirrors `versions[].modified_by` |
| `deroga` | norma → norma/articulo | date, scope (total/parcial) |
| `cita` | sentencia → sentencia/norma/articulo | extraction (regex/llm), confidence |
| `aplica_articulo` | sentencia → articulo | as_of (date of facts), version_n (resolved from as_of at ingest), extraction, confidence |
| `interpreta` | sentencia → concepto | extraction, confidence |
| `confirma` / `revoca` | sentencia → sentencia | instance chain |
| `distingue` | sentencia → sentencia | the citing judgment distinguishes (limits, declines to apply) the cited precedent — added rev. 2026-08-27; extraction, confidence. Together with `revoca` this is what lets retrieval demote a textually-similar but distinguished/overruled precedent — the query FTS cannot answer |
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
  → LegalLibrarianAgent       (structured_output=LegalAnswer, read-only toolkits; §5.2)
  → ToolNode span_verify      (existence gate + anchor integrity + suppression ledger; §5.3)
  → ToolNode ground           (GroundednessScorer atoms over the surviving guide; §5.3.3)
```
*(rev. 2026-08-27: the agent formerly called `LegalAnswerAgent` is renamed
`LegalLibrarianAgent` to match §1.7; the budget rules in §2.5.1 apply to it unchanged.)*

### 4.3 Source precedence (merge, deterministic)
1. Norm text in force on `as_of` (BOE/EUR-Lex) — authoritative.
2. TC / CJEU / ECtHR judgments (official sources, bulk-ingested).
3. TS / AN / TSJ / AP judgments **verified** via CENDOJ (or commercial backend).
4. Same, **unverified** (graph-only, LLM-extracted edges) — allowed only as "pendiente de confirmación".
5. Secondary/doctrinal material (if ever added) — never as sole support.
Conflicts between levels: higher wins and the conflict is surfaced, not resolved by the LLM.

---

## 5. Evidence model and output contract (rev. 2026-08-27 — librarian)

> This section supersedes the original `LegalClaim`-centric contract. The original made
> the LLM's *statement* the vehicle and the citation its support; the librarian model
> inverts it: **the evidence is the payload, the LLM's reading is annotation.**

### 5.1 Span references — the unit of evidence

Every citation is a **span reference**: a pointer into a stored, hashed payload that a
deterministic verifier can check without any LLM.

```python
class SpanRef(BaseModel):
    kind: Literal["norma", "articulo", "sentencia"]
    id: str                        # BOE id / CELEX / ECLI — canonical key (§1.2)
    version_n: int | None          # article version the span indexes into (None for sentencias)
    start: int                     # half-open char offsets into the stored
    end: int                       #   normalized payload of (id, version_n)
    quote: str                     # exact text — must equal payload[start:end] byte-for-byte
    content_hash: str              # sha256 of the stored normalized payload (sealed at ingest)
    title: str
    url: str
    as_of: date | None             # version-in-force date used to resolve version_n
    verified: bool                 # AUTHORITY verification (CENDOJ/TC/EUR-Lex) — see §1.5
    verifier: str | None           # "cendoj" | "eurlex" | "tc" | "hudoc" | "vlex"
    basis: Literal["retrieval", "traversal"]   # how it entered the dossier
```

Two orthogonal verification gates:

| Gate | Question | How | When it fails |
|---|---|---|---|
| **Existence** (mandatory, deterministic) | does the quoted span exist? | payload for `(id, version_n)` exists with `content_hash`, and `payload[start:end] == quote` | span is removed; any librarian sentence anchored only to it is suppressed and recorded |
| **Authority** (tier, per §4.3) | is the source confirmed by its official verifier? | CENDOJ/TC/EUR-Lex verification (§2.5) | span stays, tiered as "pendiente de confirmación" |

Existence verification requires `content_hash` sealed at ingest. **Retrofit decided:**
`ArticleVersion` (Sprint 1, `parrot_tools/legal/boe/models.py`) gains a `content_hash`
field (sha256 over the normalized version text) and the BOE corpus is **re-ingested**
via `sync_boe()` — the corpus is fully reproducible from source, so re-ingest beats
hash-on-read backfill (single origin of truth for hashes). Chunks carry the parent
version's hash + their offsets (§3.2). The normalization applied before hashing is
frozen (OQ7 closed): Unicode NFC + newline normalization only, sealed with
`hash_norm_version: 1` — see §6.

The existing groundedness subsystem (`EvidenceIndex`/`GroundednessScorer`,
`parrot/security/groundedness/`) is **atom-based** (money/percent/number/date/
identifier) — it is not a span verifier. It remains as a complementary deterministic
check over the reading guide (numbers and identifiers quoted by the librarian must
appear in the dossier); the span verifier of this section is new machinery.

### 5.2 The answer — a dossier plus a reading guide

```python
class ConflictNote(BaseModel):
    span_a: str                    # SpanRef ids (id:version_n:start-end)
    span_b: str
    note: str                      # what appears to conflict — flagged, NEVER resolved

class ReadingNote(BaseModel):
    text: str                      # ONE sentence of the librarian's reading
    spans: list[str] = Field(min_length=1)   # anchors — SpanRef ids from the dossier
    basis: Literal["deterministic", "llm"]
    # "deterministic": narration of a traversal result (article_in_force, case_chain)
    # "llm": the librarian's judgement (relevance, emphasis) — still span-anchored

class LegalAnswer(BaseModel):
    as_of: date                    # stated back to the user (§4.1)
    materias: list[str]
    dossier: list[SpanRef]         # PRIMARY payload — precedence-ordered (§4.3)
    reading_order: list[str]       # librarian's suggested order (SpanRef ids) — "start with these"
    conflicts: list[ConflictNote]  # signalled; resolution belongs to the lawyer
    reading_guide: list[ReadingNote]  # SECONDARY — every sentence anchored, or absent
    not_found: list[str]           # corpus-scoped absence: "no span for X in the consulted
                                   #   corpus (materias=…, as_of=…)" — never ontological
    suppressed_count: int          # sentences dropped by the fail-closed gate (§1.8)
    pending: list[str]             # SpanRef ids at authority tier "pendiente de confirmación"
    disclaimer: str                # not legal advice; review by the lawyer
```

What the librarian's reading MAY contain (decided 2026-08-27): reading order / ranking
(precedence + hierarchy, deterministic base + judgement on top); conflict flagging;
corpus-scoped absence statements; temporal/procedural context narrated from
deterministic traversals ("this version governed at the date of the facts; amended
by…" — `basis="deterministic"`). What it may NOT contain: any sentence without a span
anchor; resolution of conflicts; ontological absence claims; upgraded confidence on
`pending` sources.

### 5.3 Post-check pipeline (deterministic, after the LLM)

1. **Span existence** — every `SpanRef` in `dossier` and every anchor in
   `reading_guide`/`conflicts` passes the existence gate against this execution's
   retrieval set. Fail ⇒ span removed.
2. **Anchor integrity** — every `ReadingNote` retains ≥1 surviving anchor. Fail ⇒ the
   sentence is **removed from the output**, `suppressed_count += 1`, and an
   `AuditLedger` entry (`audit_ledger.py:338 append()`) records the suppressed text,
   its claimed anchors, and the failure reason. No retry re-emits the sentence — the
   lawyer sees *that* pruning happened without seeing unverifiable prose.
3. **Groundedness atoms** — `GroundednessScorer.score()` over the surviving guide with
   the dossier as evidence; contradicted numeric/identifier atoms ⇒ same suppression
   path.
4. **Empty-dossier rule** — if `dossier` is empty after the gates, the answer IS "no
   encontré": `not_found` describes what was searched (materias, concepts, `as_of`),
   `reading_guide` is empty. A first-class, honest outcome — not an error.

---

## 6. Open questions (all decidable OQs closed 2026-08-27)
- ~~OQ1~~ **Superseded by proposal D1** (FEAT-449). The original "Closed: single Arango DB, GraphIndex namespaces over shared collections" was **refuted against the repo**: GraphIndex has no namespace concept; the only isolation unit is `TenantContext` (one ArangoDB database per tenant). Standing decision: **one ontology tenant per materia**, wiki namespaces (FEAT-450) above for brain selection. Recorded here so this skeleton stops contradicting the proposal.
- ~~OQ2~~ **Closed:** single `articulo` node with embedded `versions[]`; chunks per version; `aplica_articulo` stores `version_n`.
- **OQ3** → **remains a spike** (checklist §2.5.1) — it resolves by running, not by discussion. With the reordered roadmap (§7) it blocks **Sprint 4 only**, not Sprints 1.5–2. `verify`/`fetch` can be specced in parallel; `search` is gated on the filter check.
- **OQ4** → **remains a spike** (checklist §3.5) — blocks EUR-Lex ingestion only; BOE and the answer layer are not blocked.
- ~~OQ5~~ **Closed (2026-08-27): regex first, LLM fallback.** Deterministic date parsing in the router; only when no date is found, one structured micro-call (single field `date | null`). No date at all ⇒ default to today. In every case the `as_of` actually used is stated back in the answer (already part of the `LegalAnswer` contract).
- ~~OQ6~~ **Closed (2026-08-27): fully synchronous within the request.** `cendoj_fetch` → parse → atomic graph ingest (`replace_document_slice`) before the answer is produced. Rationale: simplest and idempotent; with the §2.5.1 budgets (max 2 fetches per execution) latency is bounded; and the existence gate needs the sealed hash in the store before the answer can cite the document — synchronous ingest guarantees that ordering by construction. The autonomous orchestrator (non-idempotent re-enqueue, C13) is deliberately NOT used here.
- ~~OQ7~~ **Closed (2026-08-27): NFC + newline normalization, versioned.** Canonical transform = Unicode NFC + newline normalization (`\r\n`/`\r` → `\n`) and nothing else — **no whitespace collapse**, so offsets index text identical to what the lawyer is shown. Every hashed payload carries `hash_norm_version: 1` alongside `content_hash`; any future change of the transform bumps the version and forces re-seal, never silent reinterpretation. Frozen before the Sprint 1.5 re-ingest.
- ~~OQ8~~ **Closed (2026-08-27): structured-first, pruned guide returned as-is.** The librarian emits via `ask(structured_output=LegalAnswer)` with the dossier's span ids enumerated in the prompt; each `ReadingNote` carries its anchors — no free text, no post-hoc alignment (that would reintroduce stochastic matching exactly where the invariant demands determinism). After suppression the guide is returned as-is in v1, whatever remains; the dossier (primary payload) is never affected by pruning. Regeneration-on-heavy-pruning is explicitly deferred as tuning, not correctness.

---

## 7. Roadmap (reordered 2026-08-27 — the fail-closed answer layer IS the product)

Original order deferred the answer layer to Sprint 4, behind case-law ingestion. The
external discussion inverted that: the librarian contract + evidence model is what
converts a stochastic toy into a professional tool, so it ships next, over the
norms-only corpus that already exists. Case law then *inherits* an already-hardened
contract instead of retrofitting one.

1. ~~**Sprint 1 — Norms graph, zero LLM.**~~ **DONE** (FEAT-449,
   `sdd/specs/legal-norms-graph-boe.spec.md`, 8/8 tasks, 2026-08-23): BOE ingestion,
   `versions[]`, `article_in_force`. EUR-Lex was deferred (spike OQ4 still open).
2. **Sprint 1.5 — Evidence retrofit.** `content_hash` sealing in the BOE pipeline
   (`ArticleVersion` + chunks), normalization per OQ7 (closed: NFC + newlines,
   `hash_norm_version: 1`), full re-run of `sync_boe()`. Small, blocking for
   everything below.
3. **Sprint 2 — Librarian answer layer over norms only.** `SpanRef` / `LegalAnswer` /
   `ReadingNote` contracts, the deterministic span verifier, the fail-closed
   suppression gate + `AuditLedger` records, minimal router (single materia), retrieval
   DAG of §4.2 without the CENDOJ verify stage. Demonstrates the one-line invariant
   end-to-end: ask about a norm ⇒ dossier + anchored guide; ask about case law ⇒
   honest "no encontré en el corpus consultado".
4. **Sprint 3 — Case law bulk.** TC + CJEU + HUDOC lazy; regex-only edges (`cita`,
   `confirma`/`revoca`); sentencias enter the same hashed-payload evidence model.
5. **Sprint 4 — CENDOJ toolkit + authority gate.** `verify` first, `fetch` with
   synchronous in-request ingest (OQ6 closed), `search` last. Adds the authority tier
   on top of the existing existence gate. Gated on the OQ3 spike.
6. **Sprint 5 — LLM-extracted edges.** `interpreta`, `aplica_articulo`, `distingue` —
   only after verified citations work end-to-end; LLM edges stay excluded from the
   verified tier unless corroborated.

---

## 8. Decision log — revision 2026-08-27

Provenance: external design discussion (colleague review of the librarian/anti-
hallucination framing), ratified by the operator on 2026-08-27.

| # | Decision |
|---|---|
| R1 | The agent is a **librarian**: evidence (dossier of spans) is the primary payload; the LLM's reading is a secondary, fully span-anchored section. Opinions may be part of the answer, never the answer. (§1.7, §5.2) |
| R2 | **Epistemic fail-closed invariant** adopted verbatim: no assertion about the corpus without a verifiable span reference; without citation ⇒ "no encontré". (§1.8) |
| R3 | Evidence model = **spans + payload hashes + ledger** (full model, not substring-only): deterministic existence gate, `AuditLedger` records for every suppression. (§5.1, §5.3) |
| R4 | Fail-closed granularity: an unanchorable librarian sentence is **removed and the removal recorded** (`suppressed_count` + ledger) — not silently dropped, not shown as "unverified". (§5.3) |
| R5 | Librarian reading may contain: reading order, conflict flagging (never resolution), corpus-scoped absence statements, traversal-derived temporal/procedural context. (§5.2) |
| R6 | **Roadmap reordered**: answer layer ships next over the norms-only corpus (Sprints 1.5 + 2), before any case-law ingestion. (§7) |
| R7 | Sprint 1 BOE corpus is **re-ingested** with sealed hashes (reproducible from source) rather than hash-on-read backfill. (§5.1) |
| R8 | `distingue` added to the typed-edge vocabulary alongside `confirma`/`revoca`. (§3.3) |

OQ-closure round (same day, operator decisions):

| # | Decision |
|---|---|
| R9 | OQ5: `as_of` extraction is regex-first in the router with a structured LLM micro-call (`date \| null`) only as fallback; default today; the `as_of` used is always stated back. (§6) |
| R10 | OQ6: `cendoj_fetch` ingests **synchronously within the request** (atomic `replace_document_slice`), so the sealed hash exists in the store before the answer cites it; budgets bound the latency. Autonomous-orchestrator enqueueing rejected (non-idempotent re-enqueue). (§6) |
| R11 | OQ7: hash normalization = Unicode NFC + newline normalization only, no whitespace collapse; sealed with `hash_norm_version: 1`; frozen before the Sprint 1.5 re-ingest. (§5.1, §6) |
| R12 | OQ8: librarian output is structured-first (`structured_output=LegalAnswer`, anchors per `ReadingNote`); post-hoc alignment rejected; the pruned guide is returned as-is in v1 (dossier never affected by pruning). (§5.2, §6) |
| R13 | OQ1's original closure formally superseded in this document by proposal decision D1 (tenant per materia; FEAT-450 namespaces above). (§6) |

## External sources
- BOE datos abiertos / API: https://www.boe.es/datosabiertos/
- EUR-Lex SPARQL (CELLAR): https://eur-lex.europa.eu/content/help/data-reuse/webservice.html
- Tribunal Constitucional HJ: https://hj.tribunalconstitucional.es/
- CENDOJ: https://www.poderjudicial.es/search/
- HUDOC: https://hudoc.echr.coe.int/
- ECLI: https://e-justice.europa.eu/ecli
