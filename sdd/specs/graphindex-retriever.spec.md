---
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Retrieval Layer

**Feature ID:** FEAT-435
**Package:** `parrot.knowledge.retrieval`
**Status:** pending review
**Author:** Jesus Lara (jlara@trocglobal.com)
**Created:** 2026-08-20
**Depends on:** `parrot.knowledge.graphindex` (L0), `rustworkx`, FAISS, SQLite FTS5
**Supersedes:** ad-hoc `GRAPH_REPORT.md` injection via `KNOWLEDGE_LAYER`

> **Numbering note.** This spec predates the `sdd/templates/spec.md` scaffold and
> keeps its own §1–§11 numbering, because §3.5/§5.0/§9/§11 are cross-referenced
> throughout the body and by the task table. The template's mandatory sections
> are present under the numbers below:
>
> | Template section | Here |
> |---|---|
> | 1. Motivation & Business Requirements | §1 Scope |
> | 2. Architectural Design | §2 Layer model, §3 Core contracts, §3.5 Derivation layer |
> | 3. Module Breakdown | §4–§6 (classifier, policies, WikiCache) |
> | 4. Test Specification | §7 Evaluation harness + **§12** |
> | 5. Acceptance Criteria | **§13** |
> | 6. Codebase Contract | **§14** (evidence gathered in §11) |
> | 7. Implementation Notes & Constraints | §11.1 + **§14.4** |
> | 8. Open Questions | §9 (resolved) + §9.1 (RQ-1…RQ-4, resolved) |
> | Worktree Strategy | **§15** |

---

## 1. Scope

### 1.1 In scope

- A retrieval layer (**L2**) that turns a natural-language question into a bounded, attributable `ContextBundle` over the existing structural code graph.
- A synthesis cache (**L1**, "wiki") of LLM-generated pages anchored to L0 node identities, with deterministic invalidation.
- A `QueryClassifier` that routes each request to the cheapest sufficient retrieval policy, with an escalation ladder instead of pessimistic routing.

### 1.2 Out of scope (this spec)

- Changes to L0 extraction (tree-sitter pipeline, `OdooCodeExtractor`, persistence backends). L0 is consumed read-only.
- The cross-corpus bridge (code ↔ docs/legal/ADR ontology). Reserved for a follow-up spec; contracts here must not preclude it — see §9.
- Agent-facing tool surface (`@tool_schema` wrappers). A separate `GraphRetrieverToolkit` consumes this layer.

### 1.3 Non-goals

- **No LLM-induced edges.** L0 edges remain parser-derived and exact. The LLM never proposes graph structure, only prose anchored to existing structure.
- **No global re-index on write.** Every artifact in L1 must be independently invalidatable.

---

## 2. Layer model and invariants

```
L0  Structural graph      deterministic, exact, cheap        tree-sitter → rustworkx → ArangoDB/SQLite
L1  Synthesis cache       LLM-written, lazy, invalidatable   WikiPage keyed by NodeRef + digest
L2  Retrieval             pure routing + traversal + assembly
```

**INV-1 (Anchoring).** Every `WikiPage` and every retrieved unit references at least one L0 `NodeRef`. Free-floating chunks are not representable in this layer.

**INV-2 (Digest closure).** A `WikiPage` is valid iff the multiset of
`(node_id, digest)` pairs it declares as sources matches the digests **derived**
from the pinned source at request time (§3.5). Any mismatch marks the page
`STALE`; it is never silently served as fresh. Digests are computed, not stored
in L0 — every digest carries the `DigestScope` it was computed at, so closure is
always evaluated at a declared granularity rather than an assumed one.

**INV-3 (Determinism of routing).** `QueryClassifier.classify()` is a pure function of `(query_text, GraphStats, RetrievalBudget)`. No I/O, no LLM, no clock. Same inputs → same `RoutingDecision`, always replayable offline.

**INV-4 (Attribution).** Every unit in a `ContextBundle` carries `Evidence`
sufficient to reconstruct provenance to `file:line_span` at a specific
`git_rev`. A bundle that cannot be attributed is a bug, not a degraded result.
Two L0 realities bound this (§11.1): `line_span` is `None` for `RATIONALE`-kind
evidence until the extractor emits linenos for tagged comments, and `git_rev`
comes from admission-time resolution (§3.5.3), not from the index.

**INV-5 (Budget honesty).** Policies are interruptible and must return the best partial result within `RetrievalBudget.deadline_ms` rather than overrun. Partial results are flagged, never disguised.

---

## 3. Core contracts

### 3.1 Node identity — `parrot-graph://` URI scheme

Consistent with the `parrot-session:/` scheme already established in `dev_loop`.

```
parrot-graph://{repo}@{rev}/{path}#{kind}:{qualname}

parrot-graph://ai-parrot@a1b2c3d/parrot/outputs/a2ui.py#Function:EnvelopeProducer.emit
parrot-graph://fieldsync@9f8e7d6/domain/payrate.py#Class:PayRateEngine
```

`rev` is mandatory. Retrieval is always point-in-time; `HEAD` is resolved to a concrete SHA at request admission and pinned for the whole request — and, for cross-repo requests, for every repo in the workspace (§3.4).

```python
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

class NodeRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    rev: str                      # concrete SHA, never a symbolic ref
    path: str
    kind: NodeKind                # real L0 enum: SYMBOL|RATIONALE|SECTION|CONCEPT|...
    symbol_type: str | None       # 'module'|'class'|'function' — L0 keeps this in
                                  #   domain_tags, NOT in NodeKind (§11.1)
    qualname: str                 # DERIVED (§3.5.2), not read from L0

    @property
    def uri(self) -> str: ...

    @classmethod
    def parse(cls, uri: str) -> "NodeRef": ...
```

### 3.2 Evidence and bundle

```python
class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node: NodeRef
    digest: str                        # content hash of the L0 node at `rev`
    line_span: tuple[int, int] | None
    edge_path: tuple[EdgeRef, ...] = ()   # how we reached it from the seed set
    origin: EvidenceOrigin
    score: float                       # policy-local relevance, NOT comparable across policies


class EvidenceOrigin(StrEnum):
    """Closed set, widened pre-emptively for the cross-corpus bridge.

    L2_* members are RESERVED: declared now so the union is stable, but no
    policy may emit them until the bridge spec lands. Emitting a reserved
    origin is a contract violation, caught in tests.
    """
    L0_SOURCE = "l0_source"
    L1_WIKI = "l1_wiki"
    L1_RATIONALE = "l1_rationale"
    L2_DOC = "l2_doc"        # RESERVED — ADRs, SDD specs, tickets
    L2_NORM = "l2_norm"      # RESERVED — legal/regulatory clauses (Fieldsync)
    L2_EXTERNAL = "l2_external"  # RESERVED — third-party dependency docs

class ContextUnit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str                          # source excerpt or wiki prose
    evidence: Evidence
    token_estimate: int

class ContextBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1     # persisted + traced; do not repeat the
                                       # EventEnvelope omission
    units: tuple[ContextUnit, ...]
    decision: RoutingDecision          # the full routing trace, for replay
    truncated: bool                    # INV-5: budget exhausted before completion
    stale_sources: tuple[NodeRef, ...] = ()   # INV-2: pages served with staleness marker
    token_total: int
    elapsed_ms: float
```

### 3.3 Request and budget

```python
class RetrievalBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deadline_ms: int = 800
    max_tokens: int = 12_000
    max_llm_calls: int = 0             # 0 = synthesis-free path; >0 permits L1 lazy fill
    max_expansion_nodes: int = 400
    allow_stale: bool = True           # serve stale wiki with marker vs fall back to L0

class RetrievalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    workspace: WorkspacePin            # replaces scalar repo/rev — see §3.4
    budget: RetrievalBudget = RetrievalBudget()
    policy_override: RetrievalPolicy | None = None   # escape hatch, logged
```

### 3.4 `WorkspacePin` — the cross-repo unit of coherence

Cross-repo anchors mean a request is no longer scoped to one `(repo, rev)`. The
retrieval universe is a **frozen set of pins**, resolved once at admission.

```python
class WorkspacePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    primary: str                            # repo name; anchors relative resolution
    pins: Mapping[str, str]                 # repo -> concrete SHA, never symbolic
    pinned_at: datetime
    weight_table_version: str               # §5.3 — stamped for replay

    def rev_of(self, repo: str) -> str: ...
```

`pins` is a `Mapping`, not `dict` — validated to `frozen` semantics so the whole
request stays hashable and cacheable.

**Pin lifecycle (resolves OQ-1).** A `dev_loop` session resolves its
`WorkspacePin` at session open and holds it for the session's lifetime. HEAD
moving underneath does **not** change retrieval results. Advancing is an
explicit `RefreshWorkspace` action in the session reducer, producing a new
frozen state — consistent with the existing discriminated-union action model.

Two failure modes the implementation must handle, because pinning creates them:

- **Unreachable pin.** A pinned SHA can be garbage-collected (force-push,
  branch delete). Admission verifies reachability; on failure the request fails
  loudly with `StalePinError` rather than silently resolving to HEAD.
- **Index/pin incoherence.** L0 does not record the rev it was built from, so
  admission corroborates the pin against a bounded sample of the `files` table
  rather than verifying it. Mismatch raises `IndexPinMismatchError`, or serves
  with an `index_pin_mismatch` marker under `allow_stale`. See §3.5.3.
- **Pin drift vs L1.** The wiki cache is indexed by `(node, digest)`, not by
  rev, so a pinned-old session still gets correct staleness answers. But a
  long-lived session pinned far behind HEAD will see most pages `STALE` and
  regenerate them against old source. That is correct behaviour, and it is also
  expensive — `WorkspacePin.pinned_at` older than `stale_pin_warning_days`
  emits a warning on the trace.

---

### 3.5 Derivation layer — satisfying INV-2/INV-4 without writing to L0

**Decision (2026-08-20): derive, don't store.** L0 records neither `repo`/`rev`
nor per-node digests, and `§1.2` keeps L0 read-only. Rather than weaken the
invariants or block on an L0 spec, everything the invariants need is *computed*
at request time from material L0 already has. This preserves §1.2 exactly and
costs one hash per retrieved node plus a bounded number of git calls per
request.

### 3.5.1 Derived digests — `DigestScope`

`Evidence.digest` is computed over the **bytes actually served**, so INV-2
closure holds by construction over the returned unit rather than trusting an
index field. Not every node has a span, so the granularity is declared:

```python
class DigestScope(StrEnum):
    SPAN = "span"        # sha256 of the node's source bytes — the strong case
    FILE = "file"        # the files-table sha1; node has no line span
    SUMMARY = "summary"  # sha256 of title+summary; synthetic node, no file
```

- `SPAN` applies to `symbol_type in {class, function}`: `domain_tags["lineno"]`
  / `["end_lineno"]` exist (`extractors/code.py:296-299, 365-369`) and
  `SQLiteGraphReader._read_span()` already reads exactly that range.
- `FILE` is the fallback for `RATIONALE` nodes (no linenos, `code.py:500`) and
  module nodes, reusing the per-file sha1 already in the `files` table
  (`persist_sqlite.py`).
- `SUMMARY` covers `CONCEPT`/`WIKI_PAGE` nodes with no source file at all.

A `FILE`-scoped digest invalidates more coarsely than a `SPAN` one. That is a
real weakening of §6.1's section-level invalidation for rationale-heavy pages,
it is visible in the evidence rather than hidden, and it is fixed by the
one-line L0 change requested in RQ-4 — at which point those nodes silently
upgrade to `SPAN` with no contract change.

### 3.5.2 `DerivedSymbolIndex` — replacing the trie that does not exist

§4.2's premise was false (`graphindex/resolve.py` is an embedding-similarity
stage, not a symbol table). The index is instead built in-process at load time,
from nodes that are already resident in the `rustworkx.PyDiGraph`:

- **qualname** = the `parent_id` chain's `title`s joined with `.`, walked to the
  module root. L0's own `domain_tags["qualified_name"]` (`code.py:351`) is only
  one level deep (`{parent.title}.{name}`) and is emitted by `code.py` but not
  `odoo_code.py`, so it seeds the index but is not authoritative.
- **lookup** = exact match on qualname and on trailing segments (`resolve`,
  `PayRateEngine.resolve`), plus the `symbol_type` filter.
- Ambiguous trailing-segment hits return **all** candidates; `anchor_count`
  in §4.2 counts distinct resolved anchors, so ambiguity naturally pushes a
  query toward `COMPARATIVE`/`RELATIONAL` instead of guessing.

This is a new index (task T3b), but a derived, in-memory one — no L0 write, no
new persistence.

### 3.5.3 Pin coherence — `rev` without a stored rev

L0 does not record the rev it was built from, so a pin cannot be *verified*
against the index, only *corroborated*:

1. At admission, per repo: `rev = git rev-parse <ref>`; reachability failure
   raises `StalePinError` (§3.4).
2. **Content is read at the pinned rev**, not from the working tree, so served
   bytes and `Evidence.digest` always agree with the pin.
3. **Coherence check.** For a bounded sample (`pin_verification_sample`, default
   16) of the `files` table, hash the path's content at the pinned rev with the
   builder's own hash function and compare to the stored `sha1`. Exhaustive
   checking would cost O(files) git calls per request and is not done.
4. On mismatch, the index does not correspond to the pin: raise
   `IndexPinMismatchError`, or — when `budget.allow_stale` — serve with an
   `index_pin_mismatch` marker on the bundle.

**Stated honestly:** stored line spans were computed at index time, so a pin far
from the index's build rev can point a span at the wrong code. The sampled check
makes that likely to be caught, not guaranteed — a false pass is possible. This
is strictly weaker than storing the build rev in L0, and it is the price of
keeping L0 read-only. If T13 shows the sample missing real drift, the fix is one
column in the `files` table, and §3.5.3 collapses to a direct comparison.

---

## 4. QueryClassifier

This is the latency lever. Design principle: **the classifier must never be the thing that costs latency.** It is a pure, non-LLM function over cheap lexical + symbol-table features.

### 4.1 Query taxonomy

| Class | Shape | Example | Default policy |
|---|---|---|---|
| `DIRECT_SYMBOL` | names a resolvable symbol, wants its definition | "muéstrame `PayRateEngine.resolve`" | `DirectSymbolPolicy` |
| `LOCAL_FACT` | single-hop, one place answers it | "¿qué devuelve `resolve()`?" | `VectorSeedPolicy` |
| `RELATIONAL` | multi-hop over real edges | "¿quién llama a `NoApplicableRule`?" | `PersonalizedPageRankPolicy` |
| `RATIONALE` | intent/design/why | "¿por qué el rate se congela en clock-out?" | `RationalePolicy` (L1 + `Rationale` nodes) |
| `GLOBAL_SUMMARY` | aggregation over a subtree | "¿cómo funciona el módulo de outputs?" | `AncestrySummaryPolicy` (L1 wiki) |
| `COMPARATIVE` | two anchors, needs both neighbourhoods | "diferencia entre el bus viejo y `navigator-eventbus`" | `SteinerTreePolicy` |
| `UNKNOWN` | no confident signal | — | `VectorSeedPolicy` + escalation armed |

### 4.2 Feature extraction (pure, ~sub-millisecond)

```python
class QueryFeatures(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resolved_symbols: tuple[NodeRef, ...]   # exact hits in the L0 symbol table (trie lookup)
    anchor_count: int                       # distinct resolved anchors
    has_relational_verb: bool               # calls|uses|imports|depends|extends|quién llama...
    has_causal_marker: bool                 # why|por qué|rationale|razón|decisión
    has_aggregation_marker: bool            # overview|cómo funciona|arquitectura|resumen|todos los
    has_code_literal: bool                  # backticks, snake_case, CamelCase, dotted paths
    token_count: int
    interrogative: Interrogative            # WHAT|WHERE|WHO|WHY|HOW|NONE
```

Symbol resolution uses the `DerivedSymbolIndex` (§3.5.2), built in-process from
resident L0 nodes — L0 has no symbol trie and `resolve.py` is not one. Markers are locale-aware (ES/EN), sourced from a frozen `MarkerLexicon` so the classifier stays declarative and testable.

### 4.3 Decision rules

Ordered, first-match-wins. Deliberately a decision list, not a model — auditable, zero warm-up, zero drift.

```
R1  anchor_count == 1 and token_count <= 6 and not has_relational_verb
      → DIRECT_SYMBOL
R2  has_causal_marker
      → RATIONALE
R3  anchor_count >= 2
      → COMPARATIVE
R4  has_relational_verb and anchor_count >= 1
      → RELATIONAL
R5  has_aggregation_marker and not has_code_literal
      → GLOBAL_SUMMARY
R6  anchor_count >= 1 or has_code_literal
      → LOCAL_FACT
R7  otherwise
      → UNKNOWN
```

```python
class RoutingDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query_class: QueryClass
    policy: RetrievalPolicy
    matched_rule: str                       # "R4" — replayable
    features: QueryFeatures
    escalations: tuple[EscalationStep, ...] = ()
```

### 4.4 Escalation ladder (where the latency actually gets saved)

Pessimistic routing — sending everything through traversal because *some* queries need it — is the failure mode we are avoiding. Instead: **route optimistically, escalate on measured insufficiency.**

```
DIRECT_SYMBOL   ──insufficient──▶ LOCAL_FACT ──insufficient──▶ RELATIONAL ──▶ GLOBAL_SUMMARY
```

A result is `insufficient` when, deterministically:

- `SufficiencyCheck.coverage`: fewer than `min_units` units survived pruning, **or**
- `SufficiencyCheck.margin`: the seed score distribution is flat (top-1 / top-k ratio below `margin_threshold`) — the retriever found nothing that stands out, **or**
- `SufficiencyCheck.dangling`: a returned unit references symbols not present in the bundle (call target missing) — a structural signal only a code graph can give us, and the strongest escalation trigger.

Each escalation step is recorded in `RoutingDecision.escalations` with its trigger and elapsed cost. Budget is decremented across steps; escalation stops at `deadline_ms`.

**Escalation mode (resolves OQ-4).**

```python
class EscalationMode(StrEnum):
    SEQUENTIAL = "sequential"     # default
    SPECULATIVE = "speculative"   # budget-gated
    OFF = "off"                   # single policy, no escalation — for benchmarking
```

Speculation is **not** "run everything in parallel". It exploits a structural
fact: `PersonalizedPageRankPolicy.seed()` is exactly `VectorSeedPolicy.seed()`.
The seed stage is the expensive one (BM25 ∥ dense ∥ RRF); expansion over an
in-memory rustworkx subgraph is comparatively cheap. So running LOCAL_FACT and
RELATIONAL speculatively costs **one seed plus one extra expansion**, not two
full retrievals.

This is enforced structurally, not by convention:

```python
class SpeculationGroup(BaseModel):
    """Policies that MAY be speculated together — must share a seed stage."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    seed_signature: str                       # policies must agree on this
    members: tuple[RetrievalPolicy, ...]
```

Admission rules:

- Speculation is permitted only within a `SpeculationGroup` (shared seed).
- Speculation requires `budget.max_llm_calls == 0`. Never speculate on a path
  that may hit the LLM — that turns a latency optimisation into a cost
  multiplier.
- The loser is cancelled on `SufficiencyCheck` resolution, not awaited.
- `RoutingDecision.escalations` records the speculative branch and whether it
  was used, so wasted-work ratio (§7) stays measurable.

Default stays `SEQUENTIAL`. `SPECULATIVE` ships behind a flag and is promoted
only if the harness shows a p95 win that justifies the extra expansion cost.

**Expected effect.** Under the GraphRAG-Bench distribution, simple fact retrieval is roughly a tie between chunk and graph retrieval, so the graph traversal is pure overhead on that segment; the graph's advantage concentrates in multi-hop reasoning and contextual summarization. If the fact/relational split in real traffic resembles that benchmark, R1/R6 short-circuiting removes traversal from the majority of requests. **This is a hypothesis to measure, not an assumption** — see §7.

### 4.5 Escape hatches

- `policy_override` on the request bypasses classification but is logged with `matched_rule="OVERRIDE"`.
- A `shadow_mode` flag runs the classifier and logs the decision without acting on it, for offline calibration against a golden set before enabling routing in production.

---

## 5. Retrieval policies

### 5.0 Relationship to the shipped `GraphExpandedRetriever`

**Decision (2026-08-20): parallel layer, deprecation gated on measurement.**
FEAT-217's `GraphExpandedRetriever` (seed → expand → community → assemble) and
FEAT-379's `GraphIndexOrigin` remain in place, untouched and supported. This
layer is built independently under `parrot.knowledge.retrieval` and does **not**
refactor them.

- Nothing that ships today changes behaviour or loses tests. `GraphIndexOrigin`
  keeps its current dependency.
- Two expansion implementations coexist deliberately: FEAT-217's
  signal-relevance exponential decay (`signals.relevance_neighborhood`) and this
  layer's `PersonalizedPageRankPolicy` (§5.3). They are **competing
  strategies**, not layers.
- **T13 benchmarks both on the same golden set.** Deprecating FEAT-217 is a
  separate, later decision gated on that comparison — not assumed here. If PPR
  does not beat decay expansion, the honest outcome is that this layer keeps the
  classifier and the attribution model and adopts FEAT-217's expander.
- **Naming:** `RoutingDecision` is already taken by
  `parrot/bots/mixins/intent_router.py`. This layer's model is
  `RetrievalRoutingDecision`; §4.3 is to be read with that name.

Discriminated union, closed set. Adding a policy is a spec change, not a config change.

```python
RetrievalPolicy = Annotated[
    DirectSymbolPolicy
    | VectorSeedPolicy
    | PersonalizedPageRankPolicy
    | SteinerTreePolicy
    | AncestrySummaryPolicy
    | RationalePolicy,
    Field(discriminator="kind"),
]
```

All policies implement the same four-stage protocol; stages are individually skippable but never reordered.

```python
class RetrievalPolicyProtocol(Protocol):
    async def seed(self, req, graph) -> tuple[Seed, ...]: ...
    async def expand(self, seeds, graph, budget) -> Subgraph: ...
    async def prune(self, subgraph, budget) -> Subgraph: ...
    async def assemble(self, subgraph, budget) -> ContextBundle: ...
```

### 5.1 `DirectSymbolPolicy`
Symbol-table lookup → node body + immediate `Rationale` children. No vector search, no traversal, no LLM. Target p50 **< 15 ms**.

### 5.2 `VectorSeedPolicy`
Hybrid seeding: BM25 ∥ dense, fused with Reciprocal Rank Fusion (reuse
`pageindex/hybrid_search.py::_rrf_fuse`). `expand` limited to depth 1
(containment edges only).

**Decision (2026-08-20): T6 seeds over what exists; T6b earns the index.**

- **Lexical leg** — SQLite FTS5 `nodes_fts` via
  `SQLiteGraphReader.search_symbols()`, real today. Caveat: it indexes
  **title + summary only, not bodies**, and exists only on the SQLite backend,
  not ArangoDB.
- **Dense leg (T6)** — the in-process `faiss.IndexFlatL2`
  (`graphindex/embed.py:51`). `_persist_to_pgvector()` is a stub
  (`embed.py:193-206`); there is no pgvector read path and no HNSW anywhere, so
  the earlier "pgvector HNSW" wording is struck.
- **T6b (v1.1, conditional)** — durable pgvector + HNSW, replacing the stub.
  Gated on T13 showing `FlatL2` misses the latency target.

`FlatL2` is exhaustive, so **p50 < 120 ms is provisional, not committed** — it
is a target T13 measures, in keeping with §4.4's own "hypothesis to measure, not
an assumption" stance. Recording it as achieved-by-design would be exactly the
error this spec warns about elsewhere.

### 5.3 `PersonalizedPageRankPolicy`
Seeds from §5.2 become the restart distribution; PPR runs in-memory on rustworkx over the workspace-pinned subgraph. This is the HippoRAG-family single-pass multi-hop approach, but over parser-exact edges rather than LLM-extracted ones — the noise term that degrades multi-hop propagation in text graphs does not apply here.

**`EdgeWeightTable` is per-repo, layered (resolves OQ-3).**

```python
class EdgeWeightTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str                              # stamped into WorkspacePin
    default: Mapping[EdgeKind, float]         # global fallback
    per_repo: Mapping[str, Mapping[EdgeKind, float]] = {}

    def weight(self, repo: str, kind: EdgeKind) -> float:
        """per_repo[repo][kind] -> default[kind] -> 1.0"""
```

Per-repo is justified: `EXTENDS` in an Odoo codebase carries far more signal
than in ai-parrot, because `_inherit` is the primary composition mechanism
there and `OdooCodeExtractor` already emits it as a first-class edge kind.
A single global table would either under-weight Odoo inheritance or
over-weight ordinary Python subclassing.

**Boundary-edge resolution rule.** A cross-repo edge belongs to two repos with
possibly different tables. Rule: **the weight is taken from the table of the
repo owning the edge's *source* node**, since the dependency direction is the
one that carries intent. Deterministic, no averaging, no ambiguity.

**Does tuning violate INV-3?** No — and the distinction matters. INV-3
constrains the *classifier* to be a pure function. The weight table is **data**,
not routing logic: a frozen, versioned artifact loaded at startup. Fitting it
offline against the golden set is legitimate. What would violate INV-3 is
learning it online, or letting the classifier read it. Neither is permitted.
`weight_table_version` is stamped into `WorkspacePin` so a replayed trace
reproduces exactly.

**Do not reuse `SignalRelevanceConfig.edge_kind_weights`.** That field
(`signals.py:104`) is already a global edge-kind weight table, but its validator
enforces that the weights **sum to 1.0** (`signals.py:123-133`) because it feeds
a normalised signal scorer. `EdgeWeightTable` imposes no such constraint and is
consumed as PPR edge weights. They are different quantities with the same shape;
`EdgeWeightTable` is a new model, and §5.3.1's "strictly below any intra-repo
edge kind" rule is unrepresentable under a sum-to-one constraint anyway.

### 5.3.1 Cross-repo edges (resolves OQ-2)

Intra-repo edges come from the AST. Cross-repo edges cannot — an `import
navigator_eventbus` statement names a *distribution*, not a repo. Resolution is
a separate, lower-confidence derivation:

```
import statement → distribution name → PackageRepoMap → (repo, rev in workspace)
```

`PackageRepoMap` is built from `pyproject.toml` dependency declarations plus an
explicit override table for the ecosystem repos (ai-parrot, navigator-eventbus,
navigator-auth, asyncdb, navconfig, Flowtask).

Consequences that must be honoured:

- Cross-repo edges carry `derivation="package_metadata"`, distinguishing them
  from `derivation="ast"`. This is visible in `Evidence.edge_path`.
- They are weighted **strictly below** any intra-repo edge kind. A boundary
  crossing is a real relationship but a weak retrieval signal; without this,
  PPR floods into dependency internals on every query.
- A repo absent from `WorkspacePin.pins` terminates traversal at the boundary.
  The bundle records a `boundary_truncation` marker rather than pretending the
  subgraph was complete.
- **Precondition — now MET (verified 2026-08-20).**
  `packages/ai-parrot/pyproject.toml:133` declares `navigator-eventbus>=0.2.1`
  (plus a `navigator-eventbus[grpc]` extra at line 492), it is imported across
  `parrot/core/events/` and `parrot/core/hooks/`, and no vendored bus remains
  under `parrot/`. `PackageRepoMap` can resolve that edge from metadata with no
  hardcoded override, so T8b's stated blocker no longer exists — its v1.1
  placement is now a sequencing choice, not a dependency.

### 5.4 `SteinerTreePolicy`
Prize-Collecting Steiner Tree over the union neighbourhood of ≥2 anchors:
maximise node prize (relevance) minus edge cost (hops) subject to `max_tokens`.
Approximation via GW primal-dual; exact solve is not required and must not be
attempted.

**Sizing correction.** `rustworkx` 0.18.1 offers only
`steiner_tree(graph, terminal_nodes, weight_fn)` — a *metric minimum* Steiner
approximation with no node prizes. PCST is not available off the shelf and GW
must be written by hand. T12 is v1.1, so this is a sizing correction rather than
a blocker, but it is not the one-liner the original wording implied.

### 5.5 `AncestrySummaryPolicy`
Walks *up* the containment hierarchy from seeds and serves `WikiPage` bodies instead of source. This is the cheap substitute for Leiden community summaries: the code graph already has ground-truth communities (package → module → class), so we do not run community detection at all.

### 5.6 `RationalePolicy`
Restricts seeding to `Rationale` nodes and wiki `## Rationale` sections, then expands to the code nodes they annotate. Falls back to `VectorSeedPolicy` when the rationale corpus is sparse — a signal worth surfacing to the user ("no documented rationale found; showing implementation").

---

## 6. WikiCache (L1)

### 6.1 Page model

Splitting is a **retrieval-time selection over addressable sections**, not a
generation-time page-splitting heuristic (resolves OQ-5). A page is a structured
document; sections are the addressable unit.

```python
class SectionKind(StrEnum):
    OVERVIEW = "overview"       # what this scope is, one paragraph
    CONTRACTS = "contracts"     # public surface: signatures, models, invariants
    RATIONALE = "rationale"     # why it is this way — sourced from Rationale nodes
    USAGE = "usage"             # call patterns observed in-repo
    GOTCHAS = "gotchas"         # known sharp edges, deviations, TODO-tagged debt
    DEPENDENCIES = "dependencies"   # cross-repo boundary summary (§5.3.1)


class WikiSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SectionKind
    body: str                           # markdown
    sources: tuple[SourceDigest, ...]   # INV-2, scoped to THIS section
    token_estimate: int
    generated_at: datetime
    generator: GeneratorInfo
    state: Literal["FRESH", "STALE", "REGENERATING"]


class WikiPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page_id: str                        # stable: hash of (repo, scope_uri)
    scope: NodeRef                      # the subtree this page summarizes
    sections: Mapping[SectionKind, WikiSection]
```

**Retrieval args.** `AncestrySummaryPolicy` and `RationalePolicy` take a
selector rather than pulling whole pages:

```python
class SectionSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    include: tuple[SectionKind, ...]
    max_tokens_per_section: int = 1_200
    fill_order: tuple[SectionKind, ...]   # greedy fill when budget is tight
```

The `QueryClassifier` supplies the selector — this is where §4's class taxonomy
pays off a second time. `RATIONALE` queries request
`(RATIONALE, OVERVIEW)`; `GLOBAL_SUMMARY` requests
`(OVERVIEW, CONTRACTS, DEPENDENCIES)`. A hot module no longer produces an
unusable 8k-token page, because nobody ever asks for the whole page.

**Unplanned upside: invalidation gets finer.** Because each section declares its
own `sources`, a change to one method invalidates the `CONTRACTS` section of its
class page while `RATIONALE` and `GOTCHAS` stay `FRESH`. Under the original
whole-page model, any edit anywhere invalidated everything. This materially
reduces regeneration cost on active repos, and it was not the reason for the
change — it fell out of it. Worth noting because it strengthens the case for
this design over the generation-time split I originally proposed.

**Cost, stated honestly.** Section-level generation means more, smaller LLM
calls instead of one large one, so per-page cold-start cost goes up. The bet is
that steady-state regeneration cost dominates cold-start on a repo under active
development. If a repo is mostly static, the original model would have been
cheaper. T13 should measure this rather than assume it.

### 6.2 Invalidation

On each L0 re-index, compute the digest delta. For each **section**, if any
`SourceDigest.digest` no longer matches L0 → transition `FRESH → STALE`.
**Never eager-regenerate.** A section is regenerated only when a request
actually selects it and `budget.max_llm_calls > 0`.

Staleness is scoped on two axes now:

- **Vertical:** a change to one method invalidates the corresponding section of
  its class page and of every ancestor page, but not siblings. Ancestor
  invalidation is the expensive direction — cap with `max_ancestor_depth` and
  mark deeper ancestors `STALE` without cascading further.
- **Horizontal:** only sections whose declared sources actually moved. Most
  edits touch `CONTRACTS` and `USAGE` while leaving `RATIONALE` intact.

Single-flight (§6.3) is keyed on `(page_id, section_kind)`, not `page_id`, so
two requests needing different sections of the same hot page do not serialise.

### 6.3 Serving stale pages

| `allow_stale` | `max_llm_calls` | Behaviour |
|---|---|---|
| `True` | `0` | Serve stale body; record in `stale_sources`; **caller must surface the marker** |
| `True` | `>0` | Single-flight regenerate; on deadline miss, serve stale + marker |
| `False` | `0` | Skip L1 entirely; fall back to L0 source excerpts |
| `False` | `>0` | Block on regeneration up to deadline; then fall back to L0 |

Regeneration is guarded by single-flight keyed on `(page_id, section_kind)`
(§6.2) to prevent thundering herd on a hot module after a large merge.
**No such lock exists to reuse** — the eventbus integration has none. The
available primitives are redis-py's `.lock()` as used in
`auth/oauth2_base.py:519` and `auth/jira_oauth.py:523`, and the file-based
`wiki_write_lock()` (`knowledge/wiki/project.py:47`). Building the Redis
single-flight is in-scope new code for T9, not an integration.

### 6.4 Anti-requirement

Wiki pages are **not** authoritative. Where a wiki page and L0 source disagree, source wins and the page is a bug. The bundle must make origin (`l1_wiki` vs `l0_source`) visible to the consuming agent so it can weight accordingly.

---

## 7. Evaluation harness

Routing decisions are worthless without measurement. Ship the harness with the feature, not after.

- **Golden set**: ≥150 queries over ai-parrot + Fieldsync, hand-labelled with `QueryClass` and a reference answer node set.
- **Routing metrics**: per-class precision/recall of the decision list; escalation rate; wasted-work ratio (cost of escalated path ÷ cost of correct-first-time path).
- **Retrieval metrics**: node-set recall@k against the reference, **reference-based, not LLM-judged**. LLM-as-judge evaluation in this literature suffers documented position, length, and trial biases severe enough to flip reported win rates; narrow margins from such judging are not evidence.
- **Latency**: p50/p95/p99 per `QueryClass`, and the headline number — **fraction of traffic answered without any traversal or LLM call**.
- **Regression gate**: a routing rule change that improves one class must not degrade another beyond a set tolerance.

---

## 8. Observability

Emit one `RetrievalTrace` per request onto `navigator-eventbus`:
`query_class`, `matched_rule`, `policy.kind`, escalation chain, per-stage timings, `token_total`, `truncated`, `stale_sources` count, cache hit/miss.

`RoutingDecision` is fully serializable — offline replay of production traffic against a modified decision list requires no re-execution of retrieval.

---

## 9. Resolved decisions

| # | Question | Resolution | Where |
|---|---|---|---|
| OQ-1 | `rev` pinning across a session | **Pinned.** `WorkspacePin` frozen at session open; advancing is an explicit `RefreshWorkspace` reducer action | §3.4 |
| OQ-2 | Cross-repo anchors | **Yes.** Resolved via `PackageRepoMap`, marked `derivation="package_metadata"`, weighted below all intra-repo edges | §5.3.1 |
| OQ-3 | `EdgeWeightTable` scope | **Per-repo, layered** over a global default. Boundary edges take the source repo's table. Offline fitting does not violate INV-3 | §5.3 |
| OQ-4 | Escalation vs speculation | **Both, gated.** `SEQUENTIAL` default; `SPECULATIVE` permitted only within a shared-seed `SpeculationGroup` and only when `max_llm_calls == 0` | §4.4 |
| OQ-5 | Wiki page granularity | **Retrieval-time section selection**, not generation-time splitting. `SectionSelector` supplied by the classifier | §6.1 |
| OQ-6 | Ontology bridge forward-compat | **Widened pre-emptively.** `EvidenceOrigin` declares `L2_*` as RESERVED; `schema_version` added to `ContextBundle` | §3.2 |
| OQ-7 | L0 lacks `repo`/`rev` and per-node digests, but L0 is read-only (§1.2) | **Derive, don't store.** Digests computed over served bytes with a declared `DigestScope`; qualnames from a `DerivedSymbolIndex`; `rev` resolved at admission and corroborated by a sampled index-coherence check | §3.5 |
| OQ-8 | Relationship to shipped FEAT-217 / FEAT-379 | **Parallel layer.** Build independently; FEAT-217 untouched; PPR and decay expansion compete on T13's golden set; deprecation is a later, measured decision. Rename to `RetrievalRoutingDecision` | §5.0 |
| OQ-9 | Dense seeding leg — no pgvector, no HNSW exists | **T6 over FAISS `FlatL2`; T6b adds durable pgvector/HNSW, gated on T13.** p50 < 120 ms is provisional, not committed | §5.2 |

## 9.1 Remaining open questions — RESOLVED (verified against code 2026-08-20)

| # | Question | Resolution |
|---|---|---|
| RQ-1 | `PackageRepoMap` authority | **Built per-index-run from the pinned revs, materialized as a versioned artifact.** The dichotomy is false. |
| RQ-2 | Section regeneration coherence | **Mixed freshness is acceptable.** Bundle carries `mixed_freshness`; all-fresh-or-none is rejected. |
| RQ-3 | Speculation under cross-repo | **Disable speculation when `len(pins) > 1` in v1.** |
| RQ-4 | `GOTCHAS` provenance | **Comments only for v1.** Commit messages need a new L0 extractor (out of scope, §1.2). |

### RQ-1 — `PackageRepoMap` authority

Per-index-run **and** debuggable: build the map from the pinned revs during
the index run, then persist it as an addressable artifact stamped with
`package_map_version`, mirroring how `weight_table_version` is stamped into
`WorkspacePin` (§3.4). Per-run gives correctness; the persisted artifact gives
diffability, so nothing is traded away.

Evidence: no component reads `pyproject.toml` dependency declarations today
(`parrot/observability/setup.py` is the only file that touches the filename),
so both options are equally new code — cost is not a tiebreaker. The L0 index
is *already* a per-run snapshot: `SQLitePersistence` keys the `files` table by
`(source_uri, mtime, sha1)` and `is_stale()` compares against it
(`persist_sqlite.py:463`), so per-run derivation is the grain the index already
uses. Deferred with T8b to v1.1; does not block the v1 cut.

### RQ-2 — Section regeneration coherence

Mixed freshness within a page is **acceptable and must be surfaced**, not
prevented. Requiring all-fresh-or-none re-imposes exactly the whole-page
invalidation that §6.1 removed, and would serialise regeneration of the hottest
pages behind one lock — the failure §6.2's per-`(page_id, section_kind)`
single-flight exists to avoid.

Rule to implement: each `WikiSection` already declares its own `sources`
(INV-2). Add a `coherence_group: str` = digest of that section's
`(node_id, digest)` multiset, and set `ContextBundle.mixed_freshness: bool`
when the selected sections do not share one. This is consistent with INV-5
("partial results are flagged, never disguised") and with §6.4 (L1 is not
authoritative; origin is visible so the consuming agent can weight
`l1_wiki` below `l0_source`). A bundle whose sections describe different code
states is therefore honest, not silently wrong.

### RQ-3 — Speculation under cross-repo

`SpeculationGroup` admission gains a third rule: **`len(workspace.pins) == 1`**.

Evidence: the shared-seed guarantee is per-store, and the stores are not
shared across pins. The dense leg is a single in-process
`faiss.IndexFlatL2` (`graphindex/embed.py:51`); the lexical leg is a
**per-tenant** SQLite file (`SQLitePersistence._db_path(ctx)`,
`persist_sqlite.py:161`) whose FTS5 `nodes_fts` table is local to that file. A
multi-pin workspace therefore fans the seed stage across N files with N
independent latency profiles — the same divergence that forced a per-adapter
`timeout` onto `SearchOrigin` in MultiStoreSearch. Under fan-out the seed stage
stops being the single cheap thing that speculation amortises, so the §4.4
cost argument ("one seed plus one extra expansion") no longer holds.

Cost of the rule is zero in v1: T7b (speculation) and T8b (cross-repo) are
both deferred to v1.1, so the intersection is empty. The rule is written now so
the contract is decided before either lands.

### RQ-4 — `GOTCHAS` provenance

**Comments only in v1**, sourced entirely from existing L0.

Evidence: `CodeExtractor._DEFAULT_TAGS = {"NOTE", "WHY", "HACK", "TODO",
"FIXME", "XXX"}` (`extractors/code.py:29`) already emits one
`NodeKind.RATIONALE` node per tagged comment, carrying `domain_tags["tag"]`
and an `EdgeKind.EXPLAINS` edge to the nearest enclosing symbol
(`code.py:494-512`). `GOTCHAS` is therefore a **filter** over material L0
already produces — `tag in {HACK, TODO, FIXME, XXX}` — with `NOTE`/`WHY`
routing to `RATIONALE` instead. No new extraction.

Commit messages and reverted diffs are out of reach: `extractors/` contains
only `code`, `llm`, `loader`, `odoo_code`, `skill` — there is no VCS-history
extractor, and adding one is an L0 change that §1.2 puts out of scope.

**One L0 defect this exposes.** Rationale nodes are constructed with
`domain_tags={"tag": tag}` and **no** `lineno`/`end_lineno`
(`code.py:500`), unlike class and function nodes which carry both
(`code.py:296-299`, `365-369`). So `Evidence.line_span` is unavoidably `None`
for precisely the nodes `GOTCHAS` and `RationalePolicy` are built from,
weakening INV-4 where rationale matters most. Resolution: request the
two-field L0 fix (it is a one-line change at the emission site) and, until it
lands, accept `line_span=None` for `RATIONALE`-kind evidence rather than
degrade the invariant silently — the bundle already distinguishes origins.

## 10. Task decomposition (input to `/sdd-task`)

| # | Task | Depends on |
|---|---|---|
| T1 | `NodeRef` (incl. `symbol_type`) + URI parse/serialize + property tests | — |
| T1b | `WorkspacePin` + admission-time pin resolution + `StalePinError` | T1 |
| **T1c** | **Pin coherence check + `IndexPinMismatchError` + `index_pin_mismatch` marker (§3.5.3)** | **T1b** |
| T2 | `Evidence`, `EvidenceOrigin`, `ContextUnit`, `ContextBundle`, `RetrievalBudget` | T1 |
| T2b | Reserved-origin contract test (no policy may emit `L2_*`) | T2 |
| **T2c** | **`DigestScope` + derived-digest computation over served bytes (§3.5.1)** | **T2** |
| T3 | `QueryFeatures` extractor + `MarkerLexicon` (ES/EN) | T1 |
| **T3b** | **`DerivedSymbolIndex` — in-process qualname index over resident L0 nodes (§3.5.2)** | **T1** |
| T4 | `RetrievalRoutingDecision` decision list + replay tests | T3, T3b |
| T4b | `SectionSelector` derivation from `QueryClass` | T4 |
| T5 | `DirectSymbolPolicy` | T2, T3b |
| T6 | `VectorSeedPolicy` — FTS5 ∥ FAISS `FlatL2`, RRF | T2, T2c |
| **T6b** | **Durable pgvector + HNSW dense leg, replacing `_persist_to_pgvector` stub** | **T6, T13** |
| T7 | `SufficiencyCheck` + sequential escalation driver | T5, T6 |
| T7b | `SpeculationGroup` + speculative mode behind flag (single-pin only, RQ-3) | T7 |
| T8 | `PersonalizedPageRankPolicy` + layered `EdgeWeightTable` (new model, §5.3) | T6 |
| T8b | `PackageRepoMap` + cross-repo boundary edges + `boundary_truncation` | T1b, T8 |
| T9 | `WikiSection`/`WikiPage` + per-section invalidation + Redis single-flight (new code) | T1, T2c |
| T10 | `AncestrySummaryPolicy` (section-selective) | T9, T4b |
| T11 | `RationalePolicy` | T6, T9 |
| T12 | `SteinerTreePolicy` — hand-written PCST/GW, not `rustworkx.steiner_tree` | T8 |
| T13 | Golden set + eval harness + routing regression gate + **head-to-head vs `GraphExpandedRetriever`** | T4, T6 |
| T14 | `RetrievalTrace` emission to navigator-eventbus | T2 |

**Revised v1 cut:** T1, T1b, **T1c**, T2, T2b, **T2c**, T3, **T3b**, T4, T4b,
T5, T6, T7, T9, T13.

Four tasks were added by the 2026-08-20 code verification, all consequences of
"derive, don't store" (OQ-7) — none of them touch L0:

- **T1c / T2c** make INV-2 and INV-4 evaluable at all. Without them the
  invariants are aspirational, since L0 supplies neither digests nor a rev.
- **T3b** replaces the symbol trie §4.2 assumed already existed. It is
  load-bearing for R1/R3/R4/R6 and for `DirectSymbolPolicy`, so it cannot be
  deferred — T4 and T5 now depend on it.
- **T6b** is the pgvector/HNSW work, split out of T6 and gated on T13 rather
  than assumed.

Deferred to v1.1 with rationale:
- **T7b (speculation)** — an optimisation with no baseline to justify it yet.
  Needs T13 data first. Restricted to single-pin workspaces when it lands (RQ-3).
- **T8b (cross-repo)** — its stated blocker is gone (`navigator-eventbus` is a
  declared dependency, §5.3.1), so this is now a sequencing choice: it depends
  on `PackageRepoMap`, which RQ-1 resolves as per-index-run derivation, and
  neither is on the v1 critical path. `WorkspacePin` ships in v1 so the contract
  is stable.
- **T6b (pgvector/HNSW)** — conditional on T13 showing `FlatL2` misses the
  latency target. Building it first would be optimising an unmeasured path.
- **T10/T11/T12** — land once the golden set shows where they actually pay.
  T12 additionally needs a hand-written PCST (§5.4).

Note that T9 moved *into* v1 while T10 stayed out. The section model is now a
core contract (`SectionSelector` is on the retrieval path), so it cannot be
deferred even though the policy that consumes it can.

---

## 11. Verification against the current codebase (2026-08-20)

Audited on `dev` @ `575e00245`. **Implementation status: none.** The package
`parrot.knowledge.retrieval` does not exist and 0 of the 25 contract symbols
named in this spec are present under `packages/`. This spec is also an
untracked draft: no frontmatter, no reserved `FEAT-` id, no
`sdd/tasks/index/*.json`, and no predecessor brainstorm/proposal. Run it
through `/sdd-spec` before `/sdd-task`.

**All findings below are now dispositioned.** §11.1's corrections are folded
into the spec body by OQ-7 (§3.5), OQ-8 (§5.0) and OQ-9 (§5.2); §11.3's overlap
is dispositioned by OQ-8. This section is kept as the audit record — the
evidence for why those decisions were taken — not as an outstanding list.

### 11.1 L0 claims that did not hold — corrected

These were load-bearing. Each row's **Disposition** names where the spec now
says something true instead.

| § | Claim as written | Actual code | Disposition |
|---|---|---|---|
| §4.2 | "Symbol resolution uses the L0 symbol trie already built for `Resolve` — no new index." | `graphindex/resolve.py` is a **cross-domain embedding-similarity** stage that emits `mentions` edges with `Provenance.INFERRED`. There is no trie and no symbol table anywhere in `parrot/`. The only qualname-like datum is the one-level `domain_tags["qualified_name"]` on function nodes (`code.py:351`), absent from classes, modules, and `odoo_code.py`. | **Fixed.** §4.2 now cites the `DerivedSymbolIndex` (§3.5.2), built in-process from resident nodes; new task **T3b**, and T4/T5 depend on it. Correction: function nodes *do* carry `domain_tags["qualified_name"]` (`code.py:351`), but only one level deep and only in `code.py`, so it seeds the index without being authoritative. |
| §3.1 | `kind: NodeKind  # reuse L0 enum: Module\|Class\|Function\|Rationale` | `NodeKind` = `DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL, WIKI_PAGE, RUN, CLAIM`. Module/class/function granularity lives in `domain_tags["symbol_type"]`, not in the enum. | **Fixed.** `NodeRef` now carries `kind: NodeKind` plus `symbol_type: str \| None` (§3.1). |
| §3.1 | `repo` and `rev` (mandatory, concrete SHA) | Neither exists on `UniversalNode`, in `UniversalEdge`, in the SQLite schema, or anywhere in the pipeline. No stage captures a git rev. Persistence is partitioned by **tenant**, not repo (`_db_path(ctx)`). | **Resolved by OQ-7 — derive, don't store.** `rev` is resolved at admission via `git rev-parse` and corroborated by a sampled coherence check against the `files` table (§3.5.3); content is read *at* the pinned rev. §1.2 stands unchanged. New task **T1c**. The residual weakness — a sampled check can false-pass — is stated in §3.5.3 rather than hidden. |
| INV-2 | per-node `(node_id, digest)` closure | Digests exist only at **file** granularity: `files(source_uri, mtime, sha1)` + `is_stale()` (`persist_sqlite.py:463`). `UniversalNode` has no digest field. The existing L1 wiki is the same — `SourceManifestEntry.file_hash` is a per-file SHA-1. | **Resolved by OQ-7.** Digests are computed over the bytes actually served, tagged with a `DigestScope` of `SPAN`/`FILE`/`SUMMARY` (§3.5.1). Symbol nodes get full `SPAN` strength; `RATIONALE` nodes fall back to `FILE` until the extractor emits linenos (RQ-4), so §6.1's section-level win holds everywhere except rationale-sourced sections — visibly, not silently. New task **T2c**. |
| §5.2 | "dense (pgvector HNSW)" | `GraphIndexEmbedder` uses `faiss.IndexFlatL2` in-process (`embed.py:51`). `_persist_to_pgvector()` is a logging stub — *"not yet implemented"* (`embed.py:193-206`). There is no pgvector read path. | **Resolved by OQ-9 — T6/T6b split.** §5.2 now names FAISS `FlatL2` as the v1 dense leg, marks p50 < 120 ms **provisional**, and defers durable pgvector/HNSW to **T6b**, gated on T13 measuring the miss. |
| §5.4 | "Approximation via GW primal-dual" | `rustworkx` 0.18.1 provides `steiner_tree(graph, terminal_nodes, weight_fn)` — a metric **minimum** Steiner approximation with no node prizes. Prize-collecting is not available. | **Recorded in §5.4.** T12 stays v1.1 with the hand-written-GW cost stated. |
| §6.3 | "Redis lock via the existing eventbus infra" | No Redis lock exists in `knowledge/` or in the eventbus integration. The available primitives are redis-py `.lock()` as used in `auth/oauth2_base.py:519` / `auth/jira_oauth.py:523`, and the file-based `wiki_write_lock()` (`knowledge/wiki/project.py:47`). | **Fixed.** §6.3 now names redis-py `.lock()` (`auth/oauth2_base.py:519`) and `wiki_write_lock()` as the available primitives and marks the Redis single-flight as in-scope new code for T9. |
| §5.3.1 | "**Precondition, currently unmet:** ai-parrot … does not declare `navigator-eventbus` as a dependency." | **Stale — in the spec's favour.** `packages/ai-parrot/pyproject.toml:133` declares `navigator-eventbus>=0.2.1`, plus a `navigator-eventbus[grpc]` extra (line 492), and it is imported across `parrot/core/events/` and `parrot/core/hooks/`. No vendored bus remains under `parrot/`. | **Re-evaluated.** §5.3.1 now records the precondition as met. T8b stays v1.1, but as a sequencing choice off the critical path — not a dependency. |

### 11.2 L0 claims that hold

- **FTS5/BM25** — real: `nodes_fts` virtual table (`persist_sqlite.py:78`), queried by `SQLiteGraphReader.search_symbols()` via `bm25(nodes_fts)` (`sqlite_reader.py:323-344`). Two caveats: it indexes **title + summary only, not bodies**, and it exists only on the SQLite backend, not ArangoDB.
- **RRF** — real and reusable: `knowledge/pageindex/hybrid_search.py::_rrf_fuse` (line 277) and `interfaces/vector.py:211-223`.
- **PPR on rustworkx** — viable: the graph is a `rustworkx.PyDiGraph` (`assemble.py:37`) and `rustworkx.pagerank()` accepts `personalization=`.
- **Line spans** — present for symbol nodes as `domain_tags["lineno"/"end_lineno"]` (`code.py:296-299`, `365-369`), readable via `SQLiteGraphReader._read_span()`. Absent for `RATIONALE` nodes — see RQ-4.
- **Odoo `EXTENDS`** — real: `odoo_code.py:339` emits `EdgeKind.EXTENDS` per `_inherit`/`_inherits`. §5.3's per-repo weighting justification is factually correct.
- **Session pinning precedent** — real: `parrot-session:/<run_id>` (`dev_loop/session_state.py:97`) over a reducer with a discriminated union of action classes (`session_state.py:397+`). `RefreshWorkspace` itself is new but fits the existing model.
- **Eventbus for §8** — real and already imported for lifecycle events.
- **Supersedes** — accurate: `GRAPH_REPORT.md` is produced by `graphindex/builder.py` + `projection.py` and injected through `KNOWLEDGE_LAYER` (`bots/prompts/layers.py:181`).

### 11.3 Overlap with shipped work — dispositioned by OQ-8

A four-phase graph retriever already shipped. §5.0 now declares the
relationship explicitly: **parallel layer, deprecation gated on T13.**

- **FEAT-217 `graph-expanded-retrieval`** — complete (TASK-1565…1569 all `done`, `completed_at` 2026-06-16). `GraphExpandedRetriever.search()` in `knowledge/graphindex/retriever.py` runs seed → expand → community-annotate → assemble, with `ExpansionConfig` (`max_hops`, `decay_base`, `min_signal_threshold`, `max_expanded_nodes`, `allowed_edge_kinds`), `BudgetConfig` (`max_tokens`, `tokens_per_node_estimate`), `ScoredNode`, `GraphRetrievalResult`. Tests: `tests/knowledge/graphindex/test_retriever.py`.
- **FEAT-379 `GraphIndexOrigin`** — already exposes that pipeline as a MultiStoreSearch origin with an optional FTS leg and per-adapter timeout, i.e. part of the "`GraphRetrieverToolkit`" §1.2 defers.
- **`SignalRelevanceConfig.edge_kind_weights: dict[EdgeKind, float]`** (`signals.py:104`) is already an edge-weight table — global and unversioned, and its validator **enforces that weights sum to 1.0** (`signals.py:123-133`). `EdgeWeightTable` (§5.3) imposes no such constraint, so it cannot be dropped into the existing signal scorer unchanged.

Consequences, as resolved in §5.0:

1. FEAT-217 and FEAT-379 are **untouched**; this layer is built independently
   under `parrot.knowledge.retrieval`. Nothing that ships today changes
   behaviour or loses tests.
2. `PersonalizedPageRankPolicy` (§5.3) and the shipped signal-relevance decay
   expansion are **competing strategies**, benchmarked head-to-head in T13.
   Deprecating either is a later, measured decision. If PPR does not win, this
   layer keeps the classifier and the attribution model and adopts FEAT-217's
   expander.
3. `EdgeWeightTable` is a **new model**, not a reuse of
   `SignalRelevanceConfig.edge_kind_weights` — the latter's sum-to-1.0
   validator (`signals.py:123-133`) is incompatible with §5.3.1's
   "strictly below any intra-repo edge kind" rule (§5.3).
4. **Name collision resolved:** this layer's model is
   `RetrievalRoutingDecision`; `RoutingDecision` stays with
   `parrot/bots/mixins/intent_router.py`.

The accepted cost of a parallel layer is two expansion implementations
coexisting until T13 adjudicates. That is deliberate: it buys zero risk to
shipped, tested code, and T13 was already a v1 task.


---

## 12. Test Specification

Beyond §7's evaluation harness (which measures *quality*), these are the
correctness tests each v1 task must ship. They are deliberately weighted toward
the invariants, because every invariant in §2 is now enforced by derived
machinery (§3.5) rather than by L0 guarantees.

### Unit tests

| Target | Test |
|---|---|
| T1 | `NodeRef.parse(uri).uri == uri` round-trip (property test, hypothesis); rejects symbolic `rev` (`HEAD`, `main`, branch names); `symbol_type` preserved |
| T1b | `WorkspacePin` is hashable and frozen; `pins` rejects mutation; `rev_of()` raises on an unpinned repo |
| T1c | Unreachable SHA → `StalePinError`; sampled `files`-table mismatch → `IndexPinMismatchError`; same mismatch under `allow_stale=True` → bundle carries `index_pin_mismatch` and does **not** raise |
| T2 | `ContextBundle` frozen, `extra="forbid"`, `schema_version == 1` survives round-trip through `model_dump_json` |
| T2b | **Contract test:** no policy emits `L2_DOC`/`L2_NORM`/`L2_EXTERNAL`; parametrised over every member of the `RetrievalPolicy` union so a new policy cannot skip it |
| T2c | `DigestScope.SPAN` digest changes when one line inside the span changes and does **not** change when a line outside it changes; `RATIONALE` node yields `FILE` scope; `CONCEPT` node yields `SUMMARY` scope |
| T3 | `MarkerLexicon` matches ES and EN markers symmetrically (`why`/`por qué`, `overview`/`cómo funciona`); `QueryFeatures` is pure — same input twice, identical output, no I/O |
| T3b | Full qualname built from a `parent_id` chain (module→class→method); trailing-segment lookup `resolve` returns **all** candidates; one-level `domain_tags["qualified_name"]` agrees with the derived name where present, and derivation wins where it does not |
| T4 | **INV-3 replay:** every rule R1–R7 has a fixture that matches it and `matched_rule` names it; classifying the same `(query, GraphStats, RetrievalBudget)` twice is byte-identical; `policy_override` yields `matched_rule == "OVERRIDE"` |
| T4b | `RATIONALE` → `(RATIONALE, OVERVIEW)`; `GLOBAL_SUMMARY` → `(OVERVIEW, CONTRACTS, DEPENDENCIES)` |
| T5 | `DirectSymbolPolicy` performs no vector search and no traversal (assert via spies on the seeder and expander) |
| T6 | RRF fusion matches the reference formula (mirror `tests/knowledge/pageindex/test_hybrid_search.py::test_rrf_formula_matches_reference`); FTS-only and dense-only degradation paths both return results |
| T7 | Each `SufficiencyCheck` trigger (`coverage`, `margin`, `dangling`) fires in isolation; escalation stops at `deadline_ms` and sets `truncated=True` |
| T9 | Editing one method marks that class page's `CONTRACTS` `STALE` while `RATIONALE`/`GOTCHAS` stay `FRESH`; single-flight on `(page_id, section_kind)` lets two different sections of one page regenerate concurrently |

### Integration tests

- **End-to-end on a real index.** Build a GraphIndex over a small fixture repo,
  then assert one query per `QueryClass` returns a bundle whose every unit
  attributes to a real `file:line_span` (INV-4), with `RATIONALE`-kind evidence
  allowed `line_span=None` per §3.5.1.
- **INV-5 budget honesty.** With `deadline_ms=1`, every policy returns a bundle
  with `truncated=True` rather than overrunning or raising.
- **INV-2 closure.** Mutate a source file, re-run retrieval, assert the affected
  section flips to `STALE` and appears in `stale_sources`; assert an untouched
  sibling section stays `FRESH`.
- **Coexistence (OQ-8).** `GraphIndexOrigin` and
  `GraphExpandedRetriever.search()` keep their current behaviour with this layer
  installed — run the existing `tests/knowledge/graphindex/test_retriever.py`
  and `packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py`
  unchanged.

### Fixtures

- A committed fixture repo (≥2 modules, ≥1 class hierarchy, ≥3 tagged comments
  covering `TODO`/`WHY`/`HACK`) with a **pinned rev**, so digest and pin tests
  are reproducible.
- A prebuilt SQLite GraphIndex over that fixture, checked in or built in a
  session-scoped fixture, so tests do not depend on tree-sitter timing.
- `WorkspacePin` factory pinning that rev, plus a deliberately-drifted pin for
  T1c.

---

## 13. Acceptance Criteria

- [ ] `parrot.knowledge.retrieval` exists and imports cleanly with no
      dependency on `parrot.knowledge.graphindex` write paths — L0 is consumed
      read-only (§1.2), verified by an import-graph assertion.
- [ ] **INV-1:** every `ContextUnit` in every bundle carries ≥1 `NodeRef`; a
      free-floating unit is unconstructible (Pydantic-enforced, not checked).
- [ ] **INV-2:** digest closure is evaluable for every served unit, with an
      explicit `DigestScope`; a mutated source flips the affected section to
      `STALE` and it is never served as `FRESH`.
- [ ] **INV-3:** `QueryClassifier.classify()` performs zero I/O and no LLM call
      (enforced by a test that patches the network and filesystem to raise), and
      is byte-identical across repeated runs.
- [ ] **INV-4:** every unit attributes to `file:line_span` at a concrete rev,
      except `RATIONALE`-kind evidence, which may carry `line_span=None` until
      the L0 lineno fix lands (§3.5.1 / RQ-4).
- [ ] **INV-5:** no policy overruns `deadline_ms`; partial results set
      `truncated=True`.
- [ ] Every rule R1–R7 is reachable and named in `matched_rule`; the golden set
      (§7) exercises all seven.
- [ ] `RetrievalRoutingDecision` round-trips through JSON and replays offline
      with no retrieval re-execution (§8).
- [ ] No policy emits a RESERVED `L2_*` origin (T2b).
- [ ] Speculation is refused when `max_llm_calls > 0` or `len(pins) > 1`
      (§4.4, RQ-3).
- [ ] `RetrievalTrace` is emitted once per request to navigator-eventbus with
      the §8 field set.
- [ ] **No regression:** `tests/knowledge/graphindex/` and
      `packages/ai-parrot-tools/tests/multistoresearch/` pass unchanged (OQ-8).
- [ ] `pytest packages/ai-parrot/tests/knowledge/retrieval/ -v` green;
      `ruff check` and `mypy` clean on the new package.

**Explicitly NOT an acceptance criterion:** the §5.1/§5.2 latency targets
(p50 < 15 ms / < 120 ms). Per OQ-9 they are provisional and measured by T13;
gating v1 on an unbudgeted number derived from an exhaustive `FlatL2` scan would
be exactly the kind of unmeasured claim §7 exists to prevent.

---

## 14. Codebase Contract (anti-hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. §11 carries the narrative audit; this
section is the machine-checkable surface an implementing agent must not deviate
from.

### 14.1 Verified imports

```python
# L0 — consume read-only
from parrot.knowledge.graphindex.schema import (          # schema.py
    NodeKind, EdgeKind, Provenance, UniversalNode, UniversalEdge, stable_edge_id,
)
from parrot.knowledge.graphindex.assemble import GraphAssembler        # assemble.py:25
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader  # sqlite_reader.py:47
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder      # embed.py:25
from parrot.knowledge.graphindex.signals import (
    relevance_neighborhood, SignalRelevanceConfig,                    # signals.py:92
)
# reuse — do not reimplement
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # _rrf_fuse:277
```

### 14.2 Existing signatures (exact, verified)

```python
# parrot/knowledge/graphindex/schema.py
class NodeKind(str, Enum):
    DOCUMENT SECTION SYMBOL CONCEPT RATIONALE SKILL WIKI_PAGE RUN CLAIM
class EdgeKind(str, Enum):
    CONTAINS REFERENCES DEFINES MENTIONS EXPLAINS EXTENDS PRODUCED ABOUT \
    SUPPORTED_BY CONTRADICTS
class UniversalNode(BaseModel):
    node_id: str; kind: NodeKind; title: str; source_uri: str
    content_ref: Optional[str]; summary: Optional[str]; embedding_ref: Optional[str]
    domain_tags: dict; parent_id: Optional[str]
    provenance: Provenance = Provenance.EXTRACTED
    assertion: Optional[AssertionMeta] = None
    # NOTE: no repo, no rev, no digest, no line_span, no qualname fields.

# parrot/knowledge/graphindex/sqlite_reader.py
class SQLiteGraphReader:
    def get_node(self, node_id: str) -> Optional[dict]              # :180
    def children(self, ...)                                         # :203
    def who_extends(self, ...)                                      # :239
    def find_model(self, model_name: str) -> Optional[dict]         # :276
    #   Odoo-specific exact lookup — NOT a general symbol table
    #   search_symbols(...) -> FTS5/BM25 over title + summary ONLY  # :323
    @staticmethod
    def _read_span(path: Path, lineno: int, end: int) -> Optional[str]  # :404

# parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder:
    self.index: faiss.IndexFlatL2 = faiss.IndexFlatL2(dimension)    # :51
    async def search_similar(self, query_text: str, top_k: int = 10) # :122
    async def _persist_to_pgvector(self, node_id, embedding) -> None # :193 — STUB, no-op

# parrot/knowledge/graphindex/signals.py
class SignalRelevanceConfig(BaseModel):
    edge_kind_weights: dict[EdgeKind, float]                        # :104
    #   validator ENFORCES weights sum to 1.0                       # :123-133
```

**Node metadata contract — read from `domain_tags`, never invent fields:**

| Key | On | Emitted at |
|---|---|---|
| `symbol_type` (`"module"`/`"class"`/`"function"`) | SYMBOL nodes | `extractors/code.py:155, 297, 366` |
| `lineno`, `end_lineno` | class + function nodes only | `code.py:296-299, 365-369` |
| `qualified_name` (one level: `{parent.title}.{name}`) | **function nodes only**, `code.py` only | `code.py:351, 367` |
| `tag` (`NOTE\|WHY\|HACK\|TODO\|FIXME\|XXX`) | RATIONALE nodes | `code.py:29, 500` |

### 14.3 Does NOT exist (do NOT reference)

The most important subsection. Every line was searched for and confirmed absent:

- `parrot.knowledge.retrieval` — the entire package. Nothing to extend.
- `NodeRef`, `Evidence`, `ContextUnit`, `ContextBundle`, `RetrievalBudget`,
  `WorkspacePin`, `QueryClassifier`, `QueryFeatures`, `MarkerLexicon`,
  `SectionSelector`, `SpeculationGroup`, `SufficiencyCheck`, `EdgeWeightTable`,
  `PackageRepoMap`, `WikiSection`, `SectionKind`, `RetrievalTrace`,
  `StalePinError`, and all six `*Policy` classes — **0 occurrences** under
  `packages/`.
- **`RoutingDecision` — EXISTS, but is not ours.** It belongs to
  `parrot/bots/mixins/intent_router.py:378`. Use
  `RetrievalRoutingDecision` (§5.0).
- **No symbol trie / symbol table.** `graphindex/resolve.py` is a cross-domain
  embedding-similarity stage (`ResolutionConfig`, `_get_extractor_domain`) that
  emits `mentions` edges — it is **not** a resolver of names. Build T3b.
- **No `qualname` field** anywhere in `parrot/knowledge/` — only the one-level
  `domain_tags["qualified_name"]` above.
- **No node-level digest.** Digests exist only per file, in the SQLite `files`
  table via `SQLitePersistence.is_stale(ctx, source_uri, mtime, sha1)`.
- **No `repo` / `rev` / git-SHA capture** in any node, edge, or table.
  Persistence partitions by **tenant** (`_db_path(ctx)`), not repo.
- **No pgvector read path and no HNSW.** `_persist_to_pgvector` is a logging
  stub.
- **No PCST.** `rustworkx` 0.18.1 exposes only
  `steiner_tree(graph, terminal_nodes, weight_fn)` (metric minimum Steiner).
  `rustworkx.pagerank(..., personalization=...)` **does** exist — PPR is fine.
- **No Redis single-flight lock** in `knowledge/` or the eventbus integration.
  Precedent to copy: `parrot/auth/oauth2_base.py:519`, `auth/jira_oauth.py:523`.
  Unrelated: `wiki_write_lock()` (`knowledge/wiki/project.py:47`) is a
  file-based store lock.
- **No VCS-history extractor.** `extractors/` = `code`, `llm`, `loader`,
  `odoo_code`, `skill`. Commit messages are unindexed (RQ-4).
- **No `WikiPage`/`WikiSection` model.** `knowledge/wiki/models.py` has
  `WikiPageCategory` (SUMMARY/ENTITY/CONCEPT/COMPARISON/OVERVIEW/SYNTHESIS/
  ANSWER/ARCHIVE) and `SourceManifestEntry` (file-level `file_hash` + `mtime`).
  These are a **different taxonomy** from `SectionKind` — the two coexist; do
  not conflate or "unify" them.

### 14.4 Patterns to follow

- Frozen Pydantic v2 throughout: `model_config = ConfigDict(frozen=True,
  extra="forbid")`, as every model in §3 already declares.
- `async`/`await` end to end; `aiosqlite` for SQLite (never blocking `sqlite3`),
  matching `persist_sqlite.py`.
- `self.logger = logging.getLogger(__name__)`; never `print`.
- Discriminated unions via `Field(discriminator="kind")` for the policy union —
  the same shape `dev_loop/session_state.py:397+` uses for its action union.
- New concrete tools/toolkits belong in **`parrot_tools`**, not core
  `parrot/tools/` — so a future `GraphRetrieverToolkit` (§1.2, out of scope
  here) lands there alongside `parrot_tools/multistoresearch/`.

---

## 15. Worktree Strategy

**Isolation unit: per-spec.** One worktree, tasks sequential.

```bash
git worktree add -b feat-435-graphindex-retriever \
  .claude/worktrees/feat-435-graphindex-retriever HEAD
```

Rationale: the v1 cut is a contract-first chain, not a fan-out. T1→T2→T2c and
T1b→T1c are strictly serial, and **T3b is on the critical path for both T4 and
T5** (§10), so the dependency graph has a narrow waist rather than independent
lanes. Parallel worktrees would spend their isolation budget on tasks that
cannot start.

Genuinely parallelizable once the contracts land (T1, T1b, T2, T2c exist):
**T3 ∥ T3b**, then **T5 ∥ T6** (different policies, no shared state), and **T14**
at any point after T2. All are small enough that sequential execution in one
worktree is cheaper than the coordination.

**Cross-feature dependencies:** none must merge first. FEAT-217 and FEAT-379 are
untouched by design (§5.0) — this feature adds a package and does not modify
theirs. The one soft coupling is the L0 lineno fix for `RATIONALE` nodes
(RQ-4 / §3.5.1): it is a separate one-line change to
`extractors/code.py`, is **not** a blocker, and when it lands those nodes
upgrade from `FILE` to `SPAN` digest scope with no contract change here.

---

## Revision History

| Date | Change |
|---|---|
| 2026-08-20 | Verified the entire spec against `dev` @ `575e00245`; corrected §3.1/§4.2/§5.2/§5.3.1/§5.4/§6.3; added §11 audit. Resolved RQ-1…RQ-4 (§9.1). |
| 2026-08-20 | Resolved OQ-7 (derive-don't-store, §3.5), OQ-8 (parallel layer, §5.0), OQ-9 (T6/T6b dense split, §5.2). Added T1c/T2c/T3b/T6b; revised v1 cut (§10). |
| 2026-08-20 | Reserved **FEAT-435**; added frontmatter, §12 tests, §13 acceptance criteria, §14 codebase contract, §15 worktree strategy. |
