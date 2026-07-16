---
type: Wiki Overview
title: OKF Knowledge Layer over PageIndex
id: doc:sdd-proposals-okf-knowledge-layer-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: PageIndex sidecars are **bare markdown** — a node body file (e.g. `0043.md`)
  does
---

---
feature: okf-knowledge-layer
type: brainstorm
base_branch: dev
proposed_feat: FEAT-200   # ⚠️ VERIFY — sibling of the router (proposed FEAT-199); confirm next free numbers
status: brainstorm
related: [FEAT-199, FEAT-150]   # embedding router (content-addressing reuse) + Matryoshka path
# The SOC2/HIPAA corpus (FEAT-199 §7.A) becomes the first OKF bundle and the
# primary grounding substrate for the ComplianceEvidenceAgent.
---

# OKF Knowledge Layer over PageIndex

## 1. Problem statement

PageIndex sidecars are **bare markdown** — a node body file (e.g. `0043.md`) does
not describe itself. Its `type`, `title`, identity, and provenance all live in the
JSON ToC, *separate* from the body. Three things follow:

1. **Nodes are not self-describing artifacts.** A sidecar cannot be read, shared, or
   reasoned about in isolation; it is meaningless without the JSON index.
2. **There is no knowledge graph.** Inter-document references exist only as prose; the
   markdown hyperlinks between sections/documents are not resolved into navigable edges.
3. **Multi-hop retrieval is impossible.** The `ComplianceEvidenceAgent`'s natural queries
   are traversals — "which NIST 800-53 control satisfies this HIPAA safeguard, and what
   evidence proves it" — which flat per-document retrieval cannot answer.

This FEAT adds an **OKF-compatible knowledge layer** over PageIndex (Open Knowledge
Format v0.1, GoogleCloudPlatform/knowledge-catalog). It:

- enriches the **authoritative JSON node** with OKF fields (`concept_id`, `type`,
  `source`, `relates_to`);
- writes a **deterministic frontmatter mirror** onto each sidecar (and an `index.md`
  view) as pure projections of the JSON — single-writer, regenerated on rebuild, so
  drift is structurally impossible;
- resolves markdown hyperlinks + typed `relates_to` edges into an **in-memory knowledge
  graph** keyed by stable `concept_id`;
- ships an **`okf-migrate`** command to retrofit existing trees.

It aligns PageIndex with the LLM-wiki / OKF interchange model without changing the
internal representation: OKF is a *projection and interchange surface*, not the source
of truth.

## 2. Decisions (locked in discussion)

| # | Decision | Rationale |
|---|---|---|
| D1 | **JSON authoritative; frontmatter + `index.md` are deterministic projections.** | "Markdown-as-truth" (OKF/wiki posture) is the eventual end-state, but JSON-authoritative is cheaper now and drift is killed by making the mirror a pure function of the JSON, not an independent source. |
| D2 | **OKF fields live in the JSON node**, not only in frontmatter. | The LLM-derived `type` must be persisted once at ingest so the mirror stays deterministic. Authority and determinism both require it in the JSON. |
| D3 | **`concept_id` (stable slug) ≠ `node_id` (volatile position).** Links target `concept_id`; resolver joins by `concept_id`, never `node_id`. | `reindex_node_ids` rewrites `node_id`s; an id-keyed graph would shatter on every reindex (same lesson as FEAT-199 content-addressing). |
| D4 | **Graph is implicit, resolved in memory** from hyperlinks + `relates_to`. ArangoDB persistence is **phase 2**. | Start simple; no new store dependency. |
| D5 | **Typed edges as an OKF-tolerant superset** (`relates_to` frontmatter block). | OKF links are deliberately untyped; compliance needs `maps_to` / `satisfies` / `supersedes`. Unknown keys are OKF-conformant. |
| D6 | **`okf-migrate` rewrites existing trees** (retroactive, idempotent). Breaking existing trees is acceptable — they are regenerable. | User confirmed trees are reproducible from the structured ingest script. |
| D7 | **Root-level `index.md` only** now; per-folder `index.md` + thematic folder layout are **phase 2**. | The JSON ToC already *is* the progressive-disclosure index; a markdown view is for OKF conformance / human navigation. |
| D8 | **Sidecar filename is `<concept_id>.md`** (was Q1). Content_ref becomes `pageindex://<tree>/<concept_id>`. | Links target `concept_id`, so the file is named by it; `reindex_node_ids` then stops touching filenames (identity-keyed, not position-keyed) — a robustness win. |
| D9 | **`type` is a controlled ontological vocabulary; `tags` remain free namespaces** (was Q2). | A closed enum keeps tool activation reliable (§4); tags carry cross-cutting, open categorization without polluting `type`. |
| D10 | **Migrate resolves only explicit markdown links into `relates_to`** (was Q3). LLM-inferred edges are deferred to a later HITL-gated pass. | Inferred edges are probabilistic; defer until the gated maintenance loop exists. |
| D11 | **Frontmatter `summary` reuses the FEAT-199 embedding target text** (was Q4). | One string is both the mirror's summary and the router's vector input — one embedding target, one source of truth, zero divergence between the two layers. |

## 3. Non-goals

- **Not** making frontmatter authoritative (D1).
- **Not** materializing the graph in ArangoDB (D4 — phase 2).
- **Not** building the thematic folder layout or per-folder `index.md` (D7 — phase 2).
- **Not** the LLM maintenance loop (ingest→query→**lint** write-back, contradiction
  reconciliation). Autonomous mutation of knowledge is a separate concern that must be
  gated through the HITL suite; out of scope here.
- **Not** adopting OKF as the internal model. OKF is a boundary projection / interchange
  format; the internal representation stays the PageIndex tree + `Document`.

## 4. Constraints & invariants

- **Determinism by construction.** Frontmatter and `index.md` are pure functions of the
  authoritative JSON. Regenerating from the same JSON MUST produce byte-identical output.
  No hand-edits; single writer (the projection step).
- **Reproducible enrichment.** `type` classification (LLM) is cached **content-addressed**
  (`sha1(model_id + title + summary)`, mirroring FEAT-199) so re-running ingest/migrate is
  deterministic; structural fallback (`Section`) when classification is unavailable.
- **Stable identity.** `concept_id` survives `reindex_node_ids`, `splice_subtree`,
  `delete_node`. Link resolution and the in-memory graph key on it exclusively.
- **OKF v0.1 conformance.** Every concept `.md` has parseable frontmatter with a non-empty
  `type`; consumers tolerate unknown types/keys and broken links (broken link = not-yet-
  written knowledge, surfaced by lint, never an error).
- **Lean ToC preserved.** The new OKF fields are *light* metadata and stay in the lean ToC;
  `_strip_keys_in_place` continues to strip only heavy fields (`token_count`, `line_num`).
- **Reuse existing seams.** `type` classification rides the existing Two-Step CoT summary
  pass; sidecar writes go through `NodeContentStore`; regeneration uses the dirty-flag
  rebuild pattern.
- **Separate named tools, not a branching `search`.** Each retrieval/traversal capability is
  its own named tool (§6.5). Multi-purpose tools with optional `type=`/`rel=` branching
  activate unreliably in LLMs; dedicated tools activate correctly. No `search(type?, ...)`.
- **Type/`rel` filters are a guide, not a contract.** Where a `type` carries sensitive data
  (e.g. `Evidence`), access restriction lives in the execution layer (`ToolManager` /
  PBAC / the `AuthorizingDataSource` PEP), never in the tool description. LLM adherence to
  `type` is best-effort; enforcement is the PEP's.
- **Deterministic gate before probabilistic ranker.** Type-scoped tools filter the candidate
  set by `type` *exactly* before any hybrid ranking — the filter decides, the ranker
  proposes. The LLM never infers `type` by fuzzy matching. (This is the same cheap pre-filter
  the FEAT-199 router applies before beam-walk/RRF.)
- **Controlled vocabulary in tool schemas.** Type-scoped tools expose the closed `ontology.py`
  enum (Q2) in their schema; free-text `type` arguments reintroduce the activation failure
  this design avoids.

## 5. Codebase Contract

Grep anchors (symbol strings, never line numbers). `⚠️ VERIFY` = not yet confirmed by read.

| File | Anchor | Role |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` | `class NodeContentStore` | Sidecar writer — emit frontmatter + body |
| ″ | `class JSONTreeStore` | Authoritative tree load/save; carries new OKF fields |
| ″ | `_content_ref` / `pageindex://` | ⚠️ VERIFY keying (node_id vs concept_id) → decides filename (Q1) |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/tree_ops.py` | `def reindex_node_ids` / `splice_subtree` / `delete_node` | MUST preserve `concept_id`; trigger re-projection |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | `class PageIndexToolkit` / `import_pdf` / `import_folder` | Ingest writes enriched JSON; classify `type` |
| ″ | Two-Step CoT ingest method ⚠️ VERIFY name | `type` classification rides this existing LLM pass |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | `def _strip_keys_in_place` | Confirm new light fields are NOT stripped |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py` | `find_node_by_id` / `get_nodes` | Tree walk for projection + graph build |
| ″ | `_make_node_id` | SHA-1 prefix pattern; mirror for `concept_id` slug + content-addressed type cache |
| node schema (observed) | `node_id`, `title`, `summary`/`prefix_summary`, `nodes`, `doc_name`, `top_level_sections`/`structure` | Extend with `concept_id`, `type`, `source`, `relates_to` |
| `packages/ai-parrot/src/parrot/loaders/` | `class AbstractLoader` ⚠️ VERIFY path | Phase-2 `OKFLoader`/`OKFSerializer` conform here |
| FEAT-199 | `NodeEmbeddingStore` / `content_key` | Reuse content-addressing for the type cache; `summary` target text shared (Q5) |

## 6. Architecture

### 6.1 Enriched node schema (authoritative, in JSON)

```jsonc
{
  "node_id": "0043",                          // volatile structural position
  "concept_id": "playbooks/aws-incident-response", // STABLE identity + link target + filename
  "type": "Playbook",                          // LLM-classified once; content-addressed cache
  "title": "AWS Incident Response and Compliance Playbook",
  "summary": "Incident-response steps aligned to CC7.x ...",  // already produced by CoT ingest
  "source": {                                  // provenance, citable per node
    "document": "AICPA_SOC2_Compliance_Guide_on_AWS.pdf",
    "pages": [43, 47],
    "url": "https://..."                       // from the corpus manifest (FEAT-199 §7.A)
  },
  "relates_to": [                              // typed edges (OKF-superset)
    { "concept": "controls/nist-800-53-ir-4", "rel": "maps_to" }
  ],
  "nodes": [ /* children */ ]
}
```

### 6.2 Frontmatter projection (deterministic mirror)

The sidecar is `<frontmatter projected from the node>` + `<body>`. Pure function:
`project(node) -> yaml`. Field order fixed; values copied verbatim from the JSON.

```yaml
---
type: Playbook                      # REQUIRED (OKF)
title: AWS Incident Response and Compliance Playbook
id: playbooks/aws-incident-response # concept_id — stable link target
node_id: "0043"                     # mirrored for debugging; NOT a link target
resource: pageindex://soc2_hipaa/playbooks/aws-incident-response
tags: [soc2, aws, incident-response]
timestamp: 2026-06-15T00:00:00Z
summary: >-
  Incident-response steps aligned to CC7.x ...   # D11: this IS the FEAT-199 embedding target text
relates_to:
  - concept: controls/nist-800-53-ir-4
    rel: maps_to
---
```

### 6.3 In-memory knowledge graph (D4)

At load, parse each body for markdown links (`[text](/concept-path)` bundle-relative,
recommended by OKF §5.1) and merge with `relates_to` from the node. Build an adjacency
keyed by `concept_id`. Untyped prose links become `rel: references`; typed edges come from
`relates_to`. Broken links (target concept absent) are tolerated and collected for lint —
never an error (OKF §5.3 / §9). Phase 2 persists this to ArangoDB doc + edge collections.

### 6.4 `index.md` view (D7)

A root-level `index.md` generated as a deterministic listing of the JSON ToC: one entry per
top-level concept (`title` + `description`/`summary`), grouped, with bundle-relative links.
No frontmatter (OKF §6, except optional `okf_version` at root). Per-folder index → phase 2.

### 6.5 Toolkit surface (phase-1, read-only)

The enriched JSON + in-memory graph turn `PageIndexToolkit` from a single `_search_for`
into a typed retrieval/traversal surface. Phase 1 is **read tools only**; agent *writes*
to the knowledge base (create/edit concept, set edge) are the HITL-gated maintenance loop
explicitly deferred in §3. Each is a **separate named tool** (§4), exposing the controlled
`type` enum and accepting `concept_id` (stable) — never `node_id`.

| Tool | Behavior | Enabled by |
|---|---|---|
| `find_by_type(type, query)` | Hybrid search with an **exact `type` pre-filter** on the candidate set, then ranker | `type` field |
| `list_concepts(type?)` | Faceted browse / progressive disclosure over the ToC / `index.md` | `type` + `index.md` |
| `get_concept(concept_id)` | Returns the self-describing unit (frontmatter + body); stable across reindex | `concept_id` |
| `get_related(concept_id, rel?)` | In-memory graph traversal; typed `rel` (`maps_to`, `supersedes`, …) is high-signal | graph + `relates_to` |
| `trace_mapping(concept_id)` | Multi-hop typed chain (e.g. safeguard → controls → evidence) | typed edges |
| `cite(concept_id)` | Per-node provenance: document + page span + URL | `source` field |

**Why this is the payoff.** The `ComplianceEvidenceAgent` query that is impossible today —
"which NIST control satisfies this HIPAA safeguard, and what evidence proves it" —
decomposes into a tool chain: `find_by_type(Safeguard, …)` → `get_related(rel=maps_to)`
scoped to `Control` → `get_related(rel=satisfied_by)` scoped to `Evidence` → `cite`. That is
traversal-based reasoning, which flat `_search_for` cannot do.

**Signal quality caveat.** Untyped prose links degrade to `rel: references` (noise); typed
`relates_to` edges are the gold. `get_related` without `rel` returns a mix; the value of the
graph tools scales with edge-typing quality at ingest/migrate, i.e. with Q3's classification.

## 7. Deliverable artifact — `okf-migrate`

A command that retrofits existing trees (D6). For each tree in the store:

1. Load authoritative JSON.
2. For each node: derive `concept_id` (deterministic slug from `title`, dedup with a
   numeric suffix; stable across runs); classify `type` (LLM, content-addressed cache;
   structural fallback `Section`); build `source` from `doc_name` (+ page span if
   available); parse body markdown links → `relates_to` candidates (`rel: references`).
3. Write the enriched fields back into the JSON (authoritative).
4. Regenerate every sidecar with its projected frontmatter and rename `<node_id>.md` →
   `<concept_id>.md` (D8); rewrite `pageindex://` content_refs to the concept_id form.
5. Generate root `index.md`.
6. Emit a migration report: nodes processed, types assigned (histogram), links resolved
   vs. broken, slug collisions resolved.

**Idempotency:** re-running on an already-migrated tree produces identical output
(content-addressed type cache + deterministic slugging). This is the determinism
acceptance test.

## 8. Module layout

```
packages/ai-parrot/src/parrot/knowledge/pageindex/okf/
  __init__.py
  frontmatter.py     # NEW: ConceptFrontmatter (Pydantic v2); project(node)->yaml; parse/round-trip
  concept_id.py      # NEW: deterministic slug + dedup; stable across runs
  ontology.py        # NEW: controlled `type` vocabulary (compliance) + structural fallback
  graph.py           # NEW: in-memory hyperlink + relates_to graph; resolve by concept_id
  projection.py      # NEW: deterministic JSON -> frontmatter sidecars + root index.md
  migrate.py         # NEW: okf-migrate command (deliverable §7)
  tools.py           # NEW: separate named read tools (§6.5) — find_by_type, get_related, etc.

packages/ai-parrot/src/parrot/knowledge/pageindex/
  store.py           # EDIT: NodeContentStore writes frontmatter+body
  tree_ops.py        # EDIT: reindex/splice/delete preserve concept_id; trigger re-projection
  toolkit.py         # EDIT: ingest classifies type; register §6.5 read tools; type pre-filter
  # node schema EDIT: + concept_id, type, source, relates_to (kept in lean ToC)
```

## 9. Acceptance criteria

1. Every sidecar carries OKF-conformant frontmatter (non-empty `type`) that is a
   **byte-deterministic projection** of its JSON node; regenerating yields identical bytes.
2. `concept_id` is stable across `reindex_node_ids` / `splice_subtree` / `delete_node`;
   links and the in-memory graph resolve by `concept_id` only.
3. The in-memory graph is built from hyperlinks + `relates_to` with **no ArangoDB
   dependency**; broken links are tolerated and reported, never fatal.
4. A root `index.md` is generated as a deterministic view of the JSON ToC.
5. `okf-migrate` rewrites all existing trees **idempotently** and emits a report.
6. `type` classification is content-addressed → migration/rebuild is reproducible.
7. The resulting bundle passes an OKF v0.1 conformance check (§9 of the spec).
8. The §6.5 tools are **separate named tools** exposing the controlled `type` enum;
   type-scoped tools apply `type` as an **exact pre-filter** (deterministic gate) before
   ranking; sensitive-`type` access is enforced in the execution layer, not the tool.

## 10. Verification checklist (before `/sdd-spec`)

- **V1** Map every reader of `_content_ref` / `pageindex://` and confirm whether
  `reindex_node_ids` renames sidecar files today — scopes the D8 switch to concept_id-keyed
  content_refs (the decision is made; this bounds its blast radius).
- **V2** Confirm the Two-Step CoT ingest method name where `type` classification attaches.
- **V3** Confirm `_strip_keys_in_place` will not strip `concept_id` / `type` / `source` /
  `relates_to`.
- **V4** Confirm `AbstractLoader` path (phase-2 `OKFLoader`/`OKFSerializer`).
- **V5** Confirm node-level page-span provenance is available at ingest (for `source.pages`).

## 11. Open questions

**All resolved** — see D8–D11 in §2:

- Q1 (sidecar filename) → **D8**: `<concept_id>.md`, content_ref `pageindex://<tree>/<concept_id>`.
- Q2 (type vocabulary) → **D9**: controlled ontological `type` enum + free `tags` namespaces.
- Q3 (`relates_to` during migrate) → **D10**: explicit markdown links only; LLM-inferred edges deferred to the HITL-gated pass.
- Q4 (shared `summary` target) → **D11**: frontmatter `summary` reuses the FEAT-199 embedding target text.

No open design questions remain. Ready for `/sdd-spec` once the mechanical verifications
V1–V5 (§10) are confirmed against the code.
