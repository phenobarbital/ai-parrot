---
type: Wiki Overview
title: 'FEAT-215: GraphIndex/PageIndex as LLM-Wiki Platform — Gap Analysis & Enhancement
  Roadmap'
id: doc:sdd-proposals-graphindex-pageindex-llmwiki-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Three external references frame this investigation:'
---

---
id: FEAT-215
title: "GraphIndex/PageIndex as LLM-Wiki Platform — Gap Analysis & Enhancement Roadmap"
type: feature
base_branch: dev
mode: investigation
status: discussion
source:
  kind: inline
  jira_key: null
confidence: high
research_state: sdd/state/FEAT-215/
related:
  - FEAT-190 (graphindex-signal-relevance)
  - FEAT-191 (graphindex-louvain-communities)
  - FEAT-192 (graphindex-toolkit-write-and-signals)
  - FEAT-237 (pageindex-embedding-router)
  - FEAT-238 (okf-knowledge-layer)
---

# FEAT-215: GraphIndex/PageIndex as LLM-Wiki Platform — Gap Analysis & Enhancement Roadmap

**Date**: 2026-06-16
**Author**: Jesus Lara (via `/sdd-proposal`)
**Mode**: investigation
**Overall Confidence**: high

---

## §0 Origin

Three external references frame this investigation:

1. **nashsu/llm_wiki** (Tauri + React desktop app) — the most feature-complete
   open-source implementation of the LLM-Wiki pattern. Ships a 4-signal
   relevance model, Louvain community detection with cohesion scoring, graph
   insights (surprising connections, knowledge gaps, bridge nodes), and a
   multi-phase retrieval pipeline (tokenized → vector → graph expansion →
   budget control).

2. **Karpathy's LLM Wiki gist** — the foundational design pattern: raw sources
   → LLM-maintained wiki (markdown + `[[wikilinks]]` + YAML frontmatter) →
   schema. Three core operations: **ingest** (new source → update 10-15 wiki
   pages), **query** (search → synthesize → optionally file answer back), **lint**
   (contradictions, stale claims, orphans, missing cross-refs).

3. **Google Open Knowledge Format (OKF) v0.1** (June 2026) — an open spec for
   portable, vendor-neutral knowledge representation. Markdown files + YAML
   frontmatter (`type` required, everything else optional) + directory hierarchy
   + markdown links forming an implicit graph. Design principles: minimally
   opinionated, producer/consumer independence, format not platform.

**Question**: Can AI-Parrot's GraphIndex + PageIndex + OKF layer (FEAT-238)
supersede OKF as a **platform** and absorb the best ideas from nashsu/llm_wiki?

---

## §1 Synthesis Summary

**Answer: Yes — AI-Parrot already exceeds all three references in most dimensions.**
The platform has a persistent graph store (ArangoDB), multi-domain extraction
(code + docs + skills), a 5-signal relevance model (vs nashsu's 4), and an
OKF-compatible knowledge layer. Six targeted enhancements would close the
remaining gaps and position GraphIndex/PageIndex as a superset of both OKF
and the LLM-Wiki pattern.

### What AI-Parrot already has that the references don't:

| Capability | AI-Parrot | nashsu/llm_wiki | Google OKF |
|---|---|---|---|
| Persistent graph DB (ArangoDB) | **Yes** (FEAT-189) | No (in-memory only) | No (format only) |
| Multi-domain extraction (code + docs + skills) | **Yes** (3 extractors) | No (docs only) | No |
| 5-signal relevance model | **Yes** (FEAT-190) | 4 signals (no embedding) | No |
| Louvain community detection | **Yes** (FEAT-191) | Yes | No |
| Embedding-guided tree walk | **Yes** (FEAT-237) | Partial (LanceDB similarity) | No |
| OKF-compatible frontmatter + concept_id | **Yes** (FEAT-238) | Ad-hoc frontmatter | Spec-defined |
| Universal meta-ontology (6 kinds, 5 edges) | **Yes** | Ad-hoc types | `type` field only |
| Agent-facing toolkits (19 + 20 tools) | **Yes** | Local HTTP API | N/A |
| Cross-domain edge inference | **Yes** (cosine + confidence) | N/A | N/A |
| Soft-delete audit trail | **Yes** (`_active` flag) | No | No |

### What the references have that AI-Parrot lacks (the gaps):

| Gap | Source | Priority | Effort |
|---|---|---|---|
| G1: Knowledge Gap Detection | nashsu | **High** | Medium |
| G2: Composite Surprise Scoring | nashsu | **High** | Low |
| G3: Lint Operations | Karpathy | **High** | Medium |
| G4: OKF Bundle Import/Export | Google OKF | **Medium** | Medium |
| G5: Graph-Expanded Retrieval Pipeline | nashsu | **High** | High |
| G6: Insight Dismissal/Review State | nashsu | **Low** | Low |

---

## §2 Codebase Findings

### §2.1 Localization

| Module | Path | Role | Findings |
|---|---|---|---|
| GraphIndex signals | `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` (593 LOC) | 5-signal relevance model | FEAT-190 complete. 5 signals: direct links, source overlap, Adamic-Adar, type affinity, embedding similarity. Configurable weights summing to 1.0. `SignalRelevance` returns decomposed scores. |
| GraphIndex communities | `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py` (441 LOC) | Louvain detection | FEAT-191 complete. `detect_communities()` runs Louvain via networkx, computes per-community cohesion + global modularity. Writes `community_id` to `domain_tags`. Optional signal-weighted edges. |
| GraphIndex analytics | `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` (363 LOC) | God-nodes, surprising connections | Has betweenness/eigenvector centrality + inferred-edge ranking. **Missing**: isolated nodes, sparse communities, bridge nodes, composite surprise scoring. |
| OKF knowledge graph | `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/graph.py` | In-memory concept graph | `KnowledgeGraph` class with adjacency structure, `trace()` for multi-hop traversal. Collects broken links for lint. **Missing**: systematic lint operations. |
| OKF projection | `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py` | Sidecar + index.md generation | `project_sidecars()`, `generate_index_md()`. Deterministic projections from JSON. **Missing**: OKF bundle export (tarball/directory) as interchange format. |
| GraphIndex toolkit | `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` (1048 LOC) | Agent-facing tools | 19 tools including `list_communities()`, `find_community()`, `relevance()`, `neighborhood_by_relevance()`. **Missing**: gap detection tools, lint tools, graph-expanded retrieval. |
| PageIndex hybrid search | `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` (462 LOC) | BM25 + vec_rank + embedding walk | FEAT-237 hybrid search. **Missing**: graph expansion phase (seed → signal relevance → 2-hop decay). |

### §2.2 Constraints

- FEAT-190, FEAT-191, FEAT-192, FEAT-237, FEAT-238 are all **implemented and merged**.
  Any enhancement builds on top of working code, not specs-in-progress.
- GraphIndex uses `rustworkx.PyDiGraph` for hot reads and `networkx` for algorithms
  that rustworkx doesn't ship (Louvain, Adamic-Adar). This dual-graph pattern is
  established and shouldn't change.
- OKF (FEAT-238) treats frontmatter as a **projection** of the authoritative JSON,
  not the source of truth. Any OKF bundle export must maintain this invariant.
- The `analytics.py` module already has an optional `CommunitiesResult` parameter,
  so gap detection features naturally extend the analytics stage.

### §2.3 Recent History

FEAT-238 (OKF Knowledge Layer) was completed on 2026-06-15 — the day before this
proposal. The OKF subpackage (`pageindex/okf/`) is fresh and stable, making this
the right moment to plan the next layer of enhancements.

---

## §3 Hypothesis & Proposed Scope

### Hypothesis

GraphIndex + PageIndex + OKF layer already constitutes a **superset platform** of
both Google OKF and the LLM-Wiki pattern. Six targeted features would close all
remaining gaps and establish AI-Parrot as a complete LLM-Wiki platform that can
both **produce and consume OKF bundles**, detect knowledge gaps, lint knowledge
bases, and perform graph-expanded retrieval.

### Proposed Feature Set (6 enhancements)

#### Enhancement 1: Knowledge Gap Detection (G1)
**Priority**: High | **Effort**: Medium | **Module**: `analytics.py`

Add three gap-detection algorithms to the analytics stage, inspired by nashsu:

- **Isolated nodes**: Nodes with `degree ≤ 1` (excluding structural nodes like
  root documents). Indicates pages with insufficient cross-references.
- **Sparse communities**: Communities with `cohesion < 0.15` and `≥ 3` members.
  Indicates knowledge areas with weak internal linking.
- **Bridge nodes**: Nodes connecting `≥ 3` distinct communities (high inter-community
  betweenness). Identifies critical junction points whose removal would fragment
  the knowledge graph.

These feed into `AnalyticsResult` and `GRAPH_REPORT.md`. New toolkit tools:
`find_isolated_nodes()`, `find_sparse_communities()`, `find_bridge_nodes()`.

#### Enhancement 2: Composite Surprise Scoring (G2)
**Priority**: High | **Effort**: Low | **Module**: `analytics.py`

Replace the current confidence-only ranking of surprising connections with a
composite score inspired by nashsu:

| Signal | Points | Description |
|---|---|---|
| Cross-community edge | +3 | Source and target in different Louvain communities |
| Cross-type edge | +1 to +2 | Different `NodeKind`; distant pairs (e.g. SKILL↔DOCUMENT) score +2 |
| Peripheral-to-hub coupling | +2 | Low-degree node (≤ 2) linked to high-degree node (≥ 50th percentile) |
| Weak-but-present | +1 | Edge weight or confidence below threshold |
| High confidence inferred | +1 | Existing confidence-based score (current behavior) |

Threshold: `score ≥ 3` to surface. Composable with FEAT-190 signal relevance
for a fully decomposed "why is this surprising?" explanation.

#### Enhancement 3: Knowledge Lint Operations (G3)
**Priority**: High | **Effort**: Medium | **Module**: new `lint.py` in pageindex/okf/

Implement Karpathy's lint pattern for the OKF knowledge graph:

- **Orphan detection**: Concept nodes with zero inbound `relates_to` edges
  (isolated in the concept graph, not just the universal graph).
- **Broken link audit**: Already partially implemented (`KnowledgeGraph._broken`);
  surface as a structured report.
- **Missing concept pages**: Concepts referenced in `relates_to` or wikilinks
  but lacking their own concept node. Already collected; needs a tool surface.
- **Stale claims detection** (stretch): Flag concepts whose `timestamp` is
  older than a configurable threshold, or whose source documents have been
  updated since the concept was last projected.

New toolkit tool: `lint_knowledge_base()` returning a structured `LintReport`.

#### Enhancement 4: OKF Bundle Import/Export (G4)
**Priority**: Medium | **Effort**: Medium | **Module**: new `bundle.py` in pageindex/okf/

Enable interchange with the Google OKF ecosystem:

- **Export**: Package a PageIndex tree's OKF sidecars + index.md into a
  directory structure that complies with OKF v0.1 (directory hierarchy
  matching concept types, proper `type` field in frontmatter, standard
  markdown links instead of `pageindex://` URIs).
- **Import**: Read an OKF bundle directory, create PageIndex nodes from the
  markdown files, resolve frontmatter metadata into the authoritative JSON,
  and build `relates_to` edges from markdown links.
- **Round-trip fidelity**: Export → Import should preserve concept_id, type,
  relates_to edges, and body content. AI-Parrot-specific extensions
  (`node_id`, `resource` with `pageindex://` scheme) are stripped on export
  and regenerated on import.

New toolkit tools: `export_okf_bundle(tree_name, output_dir)`,
`import_okf_bundle(input_dir, tree_name)`.

#### Enhancement 5: Graph-Expanded Retrieval Pipeline (G5)
**Priority**: High | **Effort**: High | **Module**: new retrieval coordinator

Unify PageIndex hybrid search (FEAT-237) with GraphIndex's signal model
(FEAT-190) into a multi-phase retrieval pipeline inspired by nashsu:

```
Phase 1: Keyword + Vector Search (existing)
  → PageIndex hybrid_search or GraphIndex FAISS
  → Top-K seed nodes

Phase 2: Graph Expansion (new)
  → For each seed node, compute signal_relevance() to 2-hop neighbors
  → Decay factor per hop (configurable, default 0.7)
  → Merge expanded results, deduplicate by node_id
  → Re-rank by combined (search_score × decay × signal_relevance)

Phase 3: Community Context (new)
  → For each result node, include community_id and cohesion
  → Optionally expand to include community centroids
  → Budget control: cap total tokens, allocate proportionally

Phase 4: Result Assembly
  → Ranked node list with decomposed scores
  → Community context annotations
  → Source citations traced to findings
```

This requires a new `GraphExpandedRetriever` class that composes
`HybridPageIndexSearch` (or FAISS) + `signal_relevance()` + `detect_communities()`.

#### Enhancement 6: Insight Review/Dismiss State (G6)
**Priority**: Low | **Effort**: Low | **Module**: `analytics.py` + persistence

Allow agents to mark insights (surprising connections, knowledge gaps) as
"reviewed" or "dismissed" so they don't reappear:

- Store review state in `domain_tags` (edges) or a sidecar JSON file.
- `dismiss_insight(insight_id)` and `list_unreviewed_insights()` tools.
- Filter dismissed insights from `GRAPH_REPORT.md` generation.

---

## §4 Confidence Map

| # | Claim | Confidence | Evidence |
|---|---|---|---|
| C1 | AI-Parrot's 5-signal model (FEAT-190) supersedes nashsu's 4-signal model | **High** | signals.py implements all 4 nashsu signals + embedding similarity as 5th. Configurable weights, decomposed scores. |
| C2 | Louvain community detection (FEAT-191) matches nashsu's implementation | **High** | communities.py uses same algorithm (networkx Louvain), same cohesion metric. AI-Parrot adds optional signal-weighted edges. |
| C3 | OKF layer (FEAT-238) can produce OKF-compliant output | **High** | frontmatter.py projects YAML with `type`, `title`, `id`, `tags`, `timestamp`, `relates_to`. Matches OKF v0.1 required + optional fields. |
| C4 | Knowledge gap detection is absent from current analytics | **High** | analytics.py has god-nodes + surprising connections only. No isolated-node, sparse-community, or bridge-node detection. |
| C5 | Graph-expanded retrieval is not yet implemented | **High** | hybrid_search.py does BM25 + vec_rank + embedding_walk within a single tree. No cross-tree or cross-domain graph expansion via signal model. |
| C6 | Lint operations are partially present but not surfaced | **High** | KnowledgeGraph._broken collects broken links. No structured lint report, no orphan detection tool, no stale-claims check. |
| C7 | OKF bundle export requires URI rewriting | **Medium** | projection.py generates `pageindex://` URIs in `resource` field. OKF bundles need standard relative paths. Rewriting is straightforward. |
| C8 | Composite surprise scoring is a low-effort enhancement | **Medium** | analytics.py already computes surprising connections by confidence. Adding community, type, and degree signals requires ~50-80 lines of new scoring logic. |
| C9 | Graph-expanded retrieval is the highest-effort enhancement | **Medium** | Requires new coordinator class composing HybridPageIndexSearch + signal_relevance + communities. Estimated 300-500 LOC new code + integration with existing toolkits. |
| C10 | Insight dismissal can use domain_tags without schema changes | **Medium** | domain_tags is already a free-form dict on UniversalNode. Adding `_dismissed_insights: [insight_id, ...]` is backward-compatible. |
| C11 | The platform can serve as both OKF producer and consumer | **Low** | Import path (OKF → PageIndex) is speculative. Mapping arbitrary OKF `type` values to ConceptType enum requires a configurable mapping or extension mechanism. |

---

## §5 Open Questions

### Resolved by research:

- [x] **Does AI-Parrot's signal model cover nashsu's 4 signals?**
  Yes — FEAT-190 implements all 4 (direct links, source overlap, Adamic-Adar,
  type affinity) plus embedding similarity as a 5th signal.

- [x] **Does FEAT-191 match nashsu's Louvain implementation?**
  Yes — same algorithm, same cohesion metric. AI-Parrot additionally supports
  signal-weighted edges for community detection.

- [x] **Is the OKF layer compatible with Google OKF v0.1?**
  Yes at the field level — `type`, `title`, `description`, `resource`, `tags`,
  `timestamp` are all present. Bundle-level directory structure compliance
  requires Enhancement 4.

### Unresolved (require design decisions):

- [ ] **Q1: Should OKF bundle import support arbitrary `type` values?**
  OKF v0.1 only requires `type` but doesn't constrain its values. AI-Parrot
  uses `ConceptType` enum. Import could either: (a) map unknown types to a
  generic `OTHER` kind, or (b) dynamically extend the enum. Recommendation: (a).

- [ ] **Q2: Should graph-expanded retrieval be a separate class or integrated
  into existing hybrid_search.py?**
  Recommendation: separate `GraphExpandedRetriever` class that composes existing
  components, to keep concerns cleanly separated.

- [ ] **Q3: What decay function for graph expansion hops?**
  nashsu uses linear decay. Alternatives: exponential (`score × 0.7^hop`),
  signal-weighted (`score × signal_relevance.combined`). Recommendation:
  configurable, default exponential.

---

## §6 Recommended Next Step

### Primary recommendation: `/sdd-spec FEAT-215`

The enhancements are well-scoped, the codebase is thoroughly mapped, and
confidence is high. A spec can decompose these 6 enhancements into tasks
immediately.

**Suggested spec structure**: One spec covering all 6 enhancements as a
cohesive "LLM-Wiki Platform" feature. Alternatively, split into 2-3 specs:
- FEAT-215a: Knowledge Gap Detection + Composite Surprise Scoring + Lint (analytics layer)
- FEAT-215b: OKF Bundle Import/Export (interchange layer)
- FEAT-215c: Graph-Expanded Retrieval Pipeline (retrieval layer)

### Rationale

Overall confidence is **high** — all 6 enhancements build on verified,
implemented foundations (FEAT-190, FEAT-191, FEAT-237, FEAT-238). No
architectural unknowns; the main design decisions (Q1-Q3) are tractable
and don't block spec creation.

---

## §7 Research Audit

| Metric | Value |
|---|---|
| Files read | 18 |
| Grep calls | 8 |
| External URLs fetched | 3 |
| Findings generated | 6 |
| Budget profile | loose |
| Truncated | No |
| State directory | `sdd/state/FEAT-215/` |

### External Sources Analyzed

1. **nashsu/llm_wiki** — Full Tauri + React desktop app. Key contributions to
   this analysis: 4-signal relevance model (`graph-relevance.ts`), Louvain
   communities (`wiki-graph.ts`), graph insights with composite surprise scoring
   (`graph-insights.ts`), multi-phase retrieval pipeline.

2. **Karpathy's LLM Wiki gist** — Abstract design pattern. Key contributions:
   three-layer architecture (raw → wiki → schema), three operations (ingest →
   query → lint), `index.md` + `log.md` convention.

3. **Google OKF v0.1** — Open format specification. Key contributions:
   minimal schema (`type` required only), producer/consumer independence,
   markdown + YAML frontmatter + directory hierarchy as interchange format.

### Comparison Matrix: AI-Parrot vs. External References

| Dimension | AI-Parrot (current) | nashsu/llm_wiki | Google OKF | Gap? |
|---|---|---|---|---|
| Graph persistence | ArangoDB + pgvector | In-memory only | N/A (format) | **AI-Parrot leads** |
| Signal relevance | 5 signals (FEAT-190) | 4 signals | None | **AI-Parrot leads** |
| Community detection | Louvain + cohesion (FEAT-191) | Louvain + cohesion | None | **Parity** |
| Knowledge gap detection | None | Isolated + sparse + bridge | None | **Gap (G1)** |
| Surprise scoring | Confidence-only | Composite (5 factors) | None | **Gap (G2)** |
| Lint operations | Partial (broken links) | None formal | None | **Gap (G3)** |
| OKF interchange | Internal projection | N/A | Spec-defined | **Gap (G4)** |
| Graph-expanded retrieval | Separate tools | Integrated pipeline | N/A | **Gap (G5)** |
| Insight review state | None | Dismissable | N/A | **Gap (G6)** |
| Multi-domain extraction | Code + docs + skills | Docs only | N/A | **AI-Parrot leads** |
| Agent toolkit | 39 tools (19 + 20) | Local HTTP API | N/A | **AI-Parrot leads** |
| Embedding integration | FAISS + pgvector + FEAT-237 | LanceDB | N/A | **AI-Parrot leads** |
| Frontmatter schema | OKF-compatible (FEAT-238) | Ad-hoc | Standardized | **Parity** |

### Verdict

AI-Parrot's GraphIndex + PageIndex platform **already supersedes** both the
LLM-Wiki pattern and OKF v0.1 in structural capability. The 6 proposed
enhancements close the remaining feature gaps (primarily in analytics,
retrieval integration, and interchange) to make the platform a complete,
standards-compliant LLM-Wiki implementation that can both produce and consume
knowledge in the OKF format.
