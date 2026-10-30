---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, sdd-tooling]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [sdd, decisions, ontology, audit, wiki, drift]
---

# Brainstorm: SDD Decision Audit — consequence preview over the decision plane

**Date**: 2026-10-30
**Author**: Jesús Lara (with Claude Fable 5.1)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The SDD flow reviews *code* (`/sdd-codereview`, `sdd-secondopinion`, the GitHub
reviewer) but never audits *decisions*. A code review asks "is this diff good?".
An audit asks: which decision was taken, under which constraints that were
already in force, does it contradict a decision accepted earlier, does the
implementation honor it, and does it still honor it today. That chain —
provenance, consistency, re-verifiability — lives today only in prose:
`CLAUDE.md`, `.agent/CONTEXT.md`, Completion Notes, review markdown. None of it
is machine-queryable or refutable.

Concrete symptoms:

- Hard architectural rules ("clients are memory-less", "`AbstractBot` is the
  sole writer of conversation history", "never `httpx`", "concrete tools live
  in `parrot_tools`") exist as paragraphs. Only one of them (`TID251`) is
  enforced mechanically.
- The one real decision audit this repo has was done **by hand**
  (`sdd/proposals/plan-then-execute-design-drift.findings.md`, 2026-09-20):
  a section-by-section comparison of a design document against `dev`. It took
  a full session and is already stale.
- FEAT-578 built a complete ADR "decision plane"
  (`parrot.knowledge.wiki.decisions`: `DecisionRecord`, hashed `EvidenceRef`,
  freshness `current|stale|missing|unverified`, attributed review) and then
  declared **as a non-goal**: "Automatic architectural compliance/drift
  verdicts". The infrastructure for an audit exists; the audit was deliberately
  left out.
- The plane is **empty** in this repository: `docs/adr/`, `docs/adrs/` and
  `docs/decisions/` (the three `adr_globs`) do not exist, so there are zero
  documented decisions to audit against.
- Even where records exist, **nothing in the SDD authoring lane consumes
  them**: `/sdd-spec`, `/sdd-task`, `sdd-coder` and `sdd-worker` never call
  `wiki_decision_why` / `wiki_decisions_for_symbol`. The Codebase Contract
  tells a spec author *what exists*; nobody tells them *what was decided and
  why*. FEAT-778 (domain-experts) designed exactly that consumer — a
  `KnowledgeResolver` with an `adr` source that loads accepted decisions
  through `DecisionService` under a token budget, as a fixed prompt layer —
  but for runtime expert agents only, and none of its 22 tasks has started.
- Retrieval is the ceiling: a `DecisionRecord` is found by symbol link or by
  token overlap. There is no filter by component, subsystem or capability
  (no `tags`, FEAT-778 finding F043), so "what is decided about conversation
  memory?" — the question a spec author actually asks — cannot be answered
  by the plane today.

Inspiration: `fabio-rovai/open-ontologies` (MIT, Rust). Its loop is *plan a
change → see every consequence before applying → certify → watch drift →
roll back*. The transferable ideas are independent of RDF: (1) consequences
computed **before** the change lands, (2) a **conservativity** check (do the
new axioms alter consequences that already held?), (3) a derivation
**certificate** re-checked by a verifier that is independent of the engine
that produced it, (4) a digest that binds the certificate to the state it was
computed over, so drift is detectable.

The decision plane therefore has to serve **two modes over the same
records**: as *curated input* while a spec is being written (consumer), and
as *verifier* of what the spec proposes (gate). This brainstorm covers both;
the gate alone would only detect collisions on shared symbols, the consumer
alone would never enforce anything.

**Affected**: spec authors (Jesús, Claude/Codex seats running `/sdd-spec`),
`sdd-worker`/`sdd-coder` seats that inherit decisions as contracts, and the
maintainer doing post-hoc audits.

## Constraints & Requirements

Resolved in discovery (Rounds 0–2, owner Jesús):

- Flow: `feature` on `dev`.
- **Assertion**: decisions enter the graph only from a structured, human-approved
  section of the spec. No LLM inference on the critical path.
- **Granularity**: two layers — architecture rules at module/package level,
  task contracts at symbol level. v1 ships the first layer; the second is the
  task-certificate phase.
- **v1 core**: consequence preview in `/sdd-spec`. Task certificates, drift
  job and retroactive inference are later phases.
- **Checks in v1**: contradictions with accepted decisions; blast radius of the
  symbols the spec touches; undeclared supersedes (conservativity); evidence
  gaps (accepted decisions whose evidence is already stale/missing inside the
  spec's radius).
- **Verdict**: a `## Consequences` section is written into the spec (auditable
  in git). Only an *unresolved contradiction* with an accepted decision blocks
  approval; everything else is advisory.
- **Target resolution**: explicit `sym:<rel>#<qualname>` / `file:<rel>` /
  `dir:<rel>` ids in the spec's Decisions section. A target that does not
  resolve is a spec error. No lexical guessing in the verdict.
- **Seed**: a curated, versioned file of architecture rules transcribed from
  `CLAUDE.md` / `CONTEXT.md`, approved once, ingested as accepted.
- **Producer/consumer loop** (added 2026-10-31): a spec *consumes* accepted
  decisions while it is written and *produces* its own on approval. Every
  decision carries two axes — an ontological one (`about: <subsystem>`, for
  retrieval by domain) and a structural one (`targets: <graph ids>`, for
  verification). The same curation feeds both modes.

Non-negotiable technical constraints:

- Read path is deterministic and offline: zero LLM calls (FEAT-578 AC5 already
  guarantees this for `DecisionService`; the preview must keep it).
- Reuse `DecisionRecord` / `EvidenceRef` / `DecisionLink`; do not fork a second
  decision model. New relations are additive (`RelationType` values must stay
  stable strings — FEAT-239 design note).
- Must work on the SQLite plane (`wikitoolkit`) and through the MCP tools.
- Gate scripts follow the `scripts/sdd/check_*.py` pattern (Pydantic report,
  exit code, JSON output) so CI and `/sdd-spec` share one implementation.
- No `clients/base.py` changes. No new HTTP stack.

---

## Options Explored

### Option A: Governing-decisions dossier + consequence service over the existing decision plane

Add a `consequences` capability next to `parrot.knowledge.wiki.decisions`,
and make `/sdd-spec` both a consumer and a producer of the plane:

0. **Governing decisions (consumer).** Before Section 2 of a spec is
   written, `/sdd-spec` resolves the accepted decisions that govern the
   spec's domain and pulls them into a generated `## Governing Decisions`
   section: a budgeted dossier (`DecisionService.why()` / `for_symbol()`,
   `source_status == accepted`, history excluded) retrieved on two axes —
   by **subsystem** (the frontmatter `projects` / `tags` the spec already
   declares, matched against each record's `about` concepts) and by
   **symbol** (the ids in the Codebase Contract). Each entry carries the
   decision statement, its rationale/consequences, the `supersedes` chain
   and the rejected alternatives, so a new spec does not re-derive an
   option that was already discarded. This is the same resolver shape
   FEAT-778 specifies for expert agents (`adr` source, accepted-only
   filter, token budget, fixed layer order); the SDD lane is one more
   consumer of it, not a second implementation.
1. **Decisions section in the spec template (producer).** A structured block
   (one entry per decision) with `id`, `statement`, `relation` ∈
   {`constrains`, `forbids`, `requires`, `supersedes`}, `about` (one or more
   subsystem concepts from a curated taxonomy), explicit `targets` (graph
   ids) and optional `supersedes: <decision-id>`. The ADR parser already reads
   flat frontmatter keys `id/title/status/supersedes`; this extends the
   vocabulary with `about` and `targets` lists and the new relations.
2. **Ingestion.** Approving a spec (status `approved`) runs the existing
   `refresh_decisions()` path over the spec's Decisions block, producing
   `DecisionRecord`s with `origin="documented"`, `source_status="accepted"`,
   `source_path=<spec>`, and `EvidenceRef`s pointing at the target spans
   (hashed by `source_sha1`, exactly as ADR evidence today).
3. **Seed.** `docs/decisions/*.md` is one of the three `adr_globs` already
   configured. The architecture rules become ADR-style markdown files there
   with the extended `about:` + `targets:` frontmatter — so the seed is
   ingested by the code that exists, with no new loader. Because every
   seeded rule is anchored to a subsystem, the seed is also the first layer
   of curated knowledge the consumer step returns, not just a list of
   prohibitions.
3b. **Subsystem taxonomy.** A small, versioned list of code-subsystem
   concepts (memory, clients, tools, flows, skills, knowledge/wiki, server,
   sdd-tooling, …) that `about` values must come from. It is the ontological
   spine for retrieval by domain; `KNOWN_PROJECTS` (frontmatter `projects`)
   is the coarse layer that already exists, the taxonomy is the finer one.
   Records link to concepts with `RelationType.ABOUT`, which already exists.
4. **Preview.** A `ConsequenceService` takes a spec path, resolves every
   target through `StructuralService.lookup()`, computes
   `StructuralService.blast_radius()` per target, pulls accepted records via
   `DecisionService.for_symbol()`, and emits a `ConsequenceReport` with four
   finding kinds: `contradiction`, `undeclared-supersedes`, `blast-radius`,
   `evidence-gap`. Freshness reuses `verify_freshness()`.
5. **Gate.** `scripts/sdd/check_spec_consequences.py` renders the report into
   the spec's `## Consequences` section and exits non-zero only on an
   unresolved `contradiction`. `/sdd-spec` runs it between "Scaffold" and
   "Commit"; CI runs it on PRs touching `sdd/specs/`.
6. **Surface.** One MCP tool `wiki_spec_consequences` (and `wikitoolkit spec
   consequences <path>`) so Codex seats and humans get the same report.

✅ **Pros:**
- Reuses the whole FEAT-578 stack (models, CAS persistence, review,
  freshness, dossier rendering, MCP transport). The new code is one service,
  one gate script, two template sections, one parser extension.
- Closes the loop: a spec reads accepted decisions, declares its own, the
  preview checks consistency, approval feeds the next spec. With the `about`
  axis the preview can also say "you are legislating about memory without
  having read what is decided about memory", which a symbol-only check
  never can.
- Deterministic and offline by construction; the only LLM in the loop is the
  human-approved spec author. The consumer step is retrieval + rendering,
  zero generation.
- The seed path is zero-code: `docs/decisions/` is already an `adr_glob`.
- Aligns with FEAT-778 instead of competing with it: same `DecisionService`
  calls, same accepted-only filter, same budget semantics.
- Each phase after v1 (task certificate, drift job, retroactive inference)
  plugs into the same records without a model change.

❌ **Cons:**
- `RelationType` and `DecisionLink.relation` need new values
  (`constrains/forbids/requires`); `DecisionLink` is a strict Literal, so this
  is a model bump (schema_version stays 1 if purely additive, but tests pin
  the literal set).
- Spec authors must write explicit graph ids. Friction is real; mitigated by
  `wikitoolkit symbols lookup` and by making the gate report *suggested* ids
  for unresolved targets.
- "Contradiction" in v1 is structural (same target, opposing relation, or an
  explicit `contradicts` link), not semantic. Two prose statements that
  contradict each other without sharing a target are not detected — but the
  `about` axis narrows the miss: two decisions on the same subsystem are at
  least surfaced side by side in the dossier.
- A subsystem taxonomy is one more curated artifact to keep honest. Too
  coarse and every spec pulls everything; too fine and authors guess.
- Sequencing with FEAT-778: if its `KnowledgeResolver` lands first the SDD
  consumer reuses it; if not, the consumer is built directly on
  `DecisionService` (which already has `budget_tokens`) and migrated later.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` ≥ 2 | `ConsequenceReport`, finding models | already a core dep |
| `wikitoolkit` (in-repo) | graph plane, structural + decision services, MCP transport | FEAT-540/578/760 |
| `PyYAML` | frontmatter `targets:` list (ADR parser reads flat scalars only today) | already a dep via navconfig; or extend the flat parser with a list form |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` — `DecisionRecord`, `EvidenceRef`, `DecisionLink`, `ReviewRequest`, `DecisionConfig.adr_globs`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py` — `DecisionService.for_symbol()` / `.why()`, `HISTORICAL_STATUSES`, symbol-link scoring.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` — `discover_adr_sources()`, `refresh_decisions()`, `project_links()`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py` — `verify_freshness()`, `build_evidence()`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` — `parse_frontmatter()`, `resolve_status()`; extend `FRONTMATTER_KEYS`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` — `StructuralService.lookup()`, `.blast_radius()`, `BlastRadiusOutput`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` — MCP `_Spec` registry (`wiki_decision_why`, `wiki_blast_radius` as templates).
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `compare_and_swap_page()` for record writes.
- `scripts/sdd/check_task_graph.py` — `Finding`/`GraphReport`/`main()` shape for the new gate script.
- `.claude/commands/sdd-spec.md` §5 "Scaffold the Spec" / §6 "Commit the Spec" — hook point for the preview.
- `sdd/templates/spec.md` — gains `## Governing Decisions` (generated, consumer), `## Decisions` (authored, producer) and `## Consequences` (generated, gate).
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` — `DocTaxonomy.projects/tags` + `KNOWN_PROJECTS`: the coarse subsystem axis a spec already declares.
- `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` — `RelationType.ABOUT` for record → subsystem-concept edges.
- `sdd/specs/domain-experts.spec.md` (FEAT-778) — G6 "ADR as consumer and producer" and the `adr` knowledge source (`DecisionService.why/for_symbol`, accepted only, budgeted) as the resolver contract to share.

---

### Option B: Ontology-first shapes engine (OKF nodes + `navrules`)

Model every rule as OKF graph content — `Policy`/`Control` nodes, `satisfies`
/ `contradicts` / `implements` edges from `parrot.knowledge.okf.ontology` —
and evaluate a rule set over graph facts with `navrules` (`RuleSet`,
`Policy.ALL_MATCH`, Rust backend when the conditions are declarative). A spec
is "planned" by projecting its proposed edges into a scratch namespace and
re-running the rule set; the diff of matched rules is the consequence report.
This is the closest analogue to SHACL shapes over an RDF store.

✅ **Pros:**
- Rules are generic graph constraints, not tied to the decision model;
  reusable for any OKF index (PageIndex compliance docs included).
- `navrules` already exists in the workspace with a Rust hot path; large rule
  sets stay cheap.
- Natural fit for the "two layers" granularity: module rules and symbol rules
  are just rules with different subjects.

❌ **Cons:**
- Duplicates what `DecisionRecord` already carries (status, evidence,
  review) in a second representation; two sources of truth for "what was
  decided".
- `navrules` evaluates "subject + environment vs N rules" (first-match /
  all-match over a context dict). Graph traversal (blast radius, transitive
  supersedes) has to be flattened into the context first, which is where the
  real work is anyway.
- Nothing in it is human-approved by construction; the review workflow of
  FEAT-578 would have to be rebuilt on OKF nodes.
- Highest effort of the three for the same v1 output.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navrules` (workspace) | declarative rule evaluation, optional Rust backend | `packages/navrules`, `RuleSet(backend="auto")` |
| `parrot.knowledge.okf.ontology` | `ConceptType.POLICY/CONTROL/EVIDENCE`, `RelationType.CONTRADICTS/SATISFIES` | already in core |

🔗 **Existing Code to Reuse:**
- `packages/navrules/src/navrules/ruleset.py` — `RuleSet`; `policies.py` — `Policy`.
- `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` — vocabulary.
- `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py` — fact extraction.

---

### Option C: External verifier — export the plane to RDF and use `open-ontologies` itself

Project the structural graph + decision records to RDF/OWL (one class per
`ConceptType`, one property per `RelationType`, decisions as named
individuals with `constrains/forbids` properties), then drive
`open-ontologies` through its MCP server: `onto_conservative_check` for
undeclared supersedes, its blast-radius report for impact, and its derivation
certificates (`asserted.tsv` / `derivations.tsv`, re-checked by the Lean
`oo-cert` checker) as the audit artifact. The unconventional option.

✅ **Pros:**
- Proof-grade certificates and an engine-independent checker for free; the
  "only independent leg" property that motivated this brainstorm.
- Zero reasoning code in our tree; our job is the RDF projection.
- Conservativity and satisfiability are solved problems there, not
  approximations.

❌ **Cons:**
- An external Rust + Lean toolchain in the SDD critical path; `/sdd-spec` can
  no longer run offline in a bare worktree without it.
- The projection is lossy and must be maintained alongside two evolving
  vocabularies; "contradiction" in OWL terms (unsatisfiable class) is not the
  same as "two SDD decisions disagree".
- The certificate binds to the exported store bytes, not to our SQLite plane
  or git tree; the digest-to-world gap the README itself warns about moves to
  our side.
- Young project (edition-2024 Rust, Oxigraph 0.5); API stability unknown.

📊 **Effort:** High (Medium if used only as an optional cross-check behind a flag)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `open-ontologies` | reasoning, conservativity, certificates, MCP server | MIT, Rust; Lean checkers `oo-cert`/`oo-horn` |
| `rdflib` ≥ 7 or `pyoxigraph` | RDF projection of the plane | new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` — the vocabulary to project.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` — `project_links()` is the edge projection to mirror.

---

### Option D: LLM-judge audit (rejected as core)

An adversarial agent (`sdd-secondopinion` style) reads the spec, the
`DecisionService.why()` dossiers for every symbol it names, and renders a
verdict. Lowest effort; it is essentially what exists today. Rejected as the
core because it is non-deterministic, it cannot be re-derived, and an LLM
auditing LLM-authored specs is the "two engines sharing an algorithm" trap.
Kept as a *complement*: the LLM reads the deterministic report and explains
it, never produces it.

📊 **Effort:** Low

---

## Recommendation

**Option A** is recommended because:

- It is the only option whose v1 is mostly wiring. FEAT-578 already solved
  persistence (CAS pages), evidence hashing, freshness, attributed review,
  budgeted rendering, CLI and MCP transport. The brainstorm's four ideas map
  onto that stack with one new service and one gate script.
- It honors every discovery answer directly: human-asserted (spec section),
  two layers (module rules now, symbol contracts next), explicit targets,
  curated seed via an existing glob, advisory-with-one-blocking-rule verdict.
- It is the only option that treats the plane as curated knowledge *for
  writing* specs and not only for checking them. The consumer step costs
  little (retrieval + a rendered section) and is what turns the seeded
  architecture rules into something an author reads before designing.
- The seed costs no code: `docs/decisions/` is already an `adr_glob`.
- Phases 2–4 (task certificate + independent checker, drift job to the
  ledger, retroactive inference via `generation.py`) attach to the same
  records. Option C stays available as an *optional external cross-check*
  once the plane has content; Option B's Rust hot path becomes relevant only
  if rule counts ever make the Python walk slow, which the current graph size
  does not suggest.

Traded away: semantic contradiction detection (v1 is structural), and the
proof-grade certificate (Option C). Both are acceptable for a first gate whose
value is "the spec author sees, in git, what the proposal collides with
before anyone writes code".

---

## Feature Description

### User-Facing Behavior

0. **Reading before designing.** When `/sdd-spec` scaffolds a spec it fills a
   generated `## Governing Decisions` section: the accepted decisions that
   govern the subsystems the spec declares (`projects` / `tags`) and the
   symbols its Codebase Contract names. Each entry shows statement,
   rationale, consequences, what it superseded and why alternatives were
   rejected, with its evidence freshness. If the subsystem has no accepted
   decisions, the section says so explicitly. The author writes Section 2
   against that dossier; the same dossier is what `/sdd-task` hands to coder
   seats as part of the task contract.
1. **Authoring.** `sdd/templates/spec.md` gains a `## Decisions` section.
   Each entry declares an id, a one-line statement, a relation
   (`constrains` / `forbids` / `requires` / `supersedes`), one or more
   `about` subsystem concepts, explicit targets (`sym:…`, `file:…`, `dir:…`)
   and, when it replaces an earlier decision, the superseded id.
2. **Preview.** During `/sdd-spec` (between scaffold and commit) the command
   runs the consequence gate. The output is written into the spec as a
   `## Consequences` section with four sub-blocks: *Contradictions*,
   *Undeclared supersedes*, *Blast radius*, *Evidence gaps*. Each finding
   cites the accepted decision id, its source path, and the evidence span
   (path:lines, freshness).
3. **Verdict.** The spec cannot move to `approved` while a contradiction is
   unresolved. Resolving means either adding `supersedes: <id>` to the new
   decision, or marking the finding `resolved-by: <owner>: <reason>` in the
   Consequences block. Everything else is informational.
4. **On approval.** The spec's decisions are ingested as accepted
   `DecisionRecord`s (origin `documented`, source path = the spec, `about`
   edges to the subsystem concepts). From then on they are visible through
   `wiki_decisions_for_symbol` / `wiki_decision_why` to every coder seat,
   they appear in the next spec's `## Governing Decisions` for the same
   subsystem, and they are what the next spec's preview is checked against.
5. **Seed.** A one-time curated set of architecture rules lives in
   `docs/decisions/` as ADR-style markdown with explicit targets, reviewed and
   committed once. The preview is useful from day one.
6. **CLI / MCP.** `wikitoolkit spec consequences <spec>` and the
   `wiki_spec_consequences` MCP tool return the same report for humans, Codex
   seats and CI.

### Internal Behavior

- **Retrieve (consumer).** From the spec frontmatter (`projects`, `tags`)
  and the Codebase Contract ids, build two query sets: subsystem concepts
  and symbol ids. Collect accepted records via `DecisionService.for_symbol()`
  for the symbols and via `about`-edge lookup for the concepts
  (`why()` as a lexical fallback only to *suggest*, never to include).
  Rank documented+current+accepted first (the existing `_group_rank`), pack
  under `budget_tokens`, render as `## Governing Decisions` with per-entry
  freshness. Zero LLM calls.
- **Parse.** The Decisions block is parsed with the ADR parser's flat
  frontmatter rules extended by list-valued `about` and `targets` keys and
  the new relation vocabulary. `about` values must belong to the subsystem
  taxonomy. Malformed entries are `DecisionDiagnostic`s, never silent.
- **Resolve.** Every target goes through `StructuralService.lookup()`
  (exact `sym:` / `file:` / `dir:` ids; name-based disambiguation is only
  used to *suggest* an id in the diagnostic, never to accept one).
- **Radius.** For each resolved symbol target, `blast_radius()` (default
  relations, depth 2) yields the impacted set; module/dir targets expand to
  their contained symbols first (the `contains` relation).
- **Collect.** `DecisionService.for_symbol()` over the targets and the
  impacted set, filtered to `source_status == "accepted"` and
  `review_status == "accepted"`, history excluded.
- **Judge (deterministic rules):**
  - *contradiction*: an accepted record with an opposing relation on an
    overlapping target (`forbids` vs `requires`, `constrains` vs an explicit
    `contradicts` link), or any accepted record the new decision names in a
    `contradicts` link.
  - *undeclared-supersedes*: the new decision shares a target and relation
    with an accepted record and does not declare `supersedes` for it.
  - *blast-radius*: impacted symbols that carry accepted decisions the spec
    does not mention.
  - *evidence-gap*: accepted records in scope whose `verify_freshness()` is
    `stale` or `missing`.
- **Render + persist.** The `ConsequenceReport` is rendered to markdown and
  spliced into the spec's `## Consequences` section (replacing the previous
  one), with a header line carrying the report's input digest (spec body
  hash + plane `content_hash`es consulted) so a later run can say whether the
  section is current.
- **Gate.** Exit code non-zero iff any `contradiction` lacks a
  `resolved-by`. JSON output for `/sdd-spec` and CI.
- **Ingest on approval.** `refresh_decisions(paths=[spec])` with the spec
  added to the discovery inventory when its status is `approved`;
  `project_links()` rebuilds navigation edges, including the `about` edges
  to subsystem concepts that make the next retrieval-by-domain possible. Records are written via
  `compare_and_swap_page`, so a concurrent edit is a visible conflict, not a
  lost update.

### Edge Cases & Error Handling

- **Unresolvable target** → diagnostic with up to N suggested ids from
  name lookup; the decision is skipped from the verdict and the gate reports
  `spec-error` (blocking: an unresolved target means the audit is
  incomplete, which must not read as "clean").
- **Empty plane** (no accepted records) → report says so explicitly; never
  silently "no findings".
- **Spec revised after preview** → the digest in the Consequences header no
  longer matches; `check_spec_consequences` flags `consequences-stale` and
  `/sdd-spec` re-runs the preview before commit.
- **Decision that supersedes a record which is itself superseded** → walk the
  `supersedes` chain; report the head of the chain, not the first hop.
- **Cross-namespace targets** (federated wiki) → v1 refuses targets outside
  the local namespace with a clear diagnostic (`DecisionService` already
  rejects `all`).
- **Approval without the gate having run** → the ingest step refuses to
  ingest a spec whose Consequences section is missing or stale.
- **Spec that declares no decisions** → allowed; the report still computes
  blast radius for symbols named in Codebase Contract, advisory only.
- **Subsystem with no accepted decisions** → `## Governing Decisions` states
  it explicitly ("no accepted decisions about `memory`"); an empty section
  must never read as "nothing governs this".
- **Unknown `about` value** → spec error with the closest taxonomy entries
  suggested; the decision is skipped from ingestion until fixed.
- **Dossier over budget** → truncation is marked (`truncated: true`, as
  `DecisionDossier` already does) and the section says which subsystems were
  cut, so the author knows to query the rest by hand.
- **FEAT-778 lands mid-flight** → the SDD consumer is an adapter over
  `DecisionService`; swapping it for the shared `KnowledgeResolver` `adr`
  source is a wiring change, not a model change.

---

## Capabilities

### New Capabilities
- `sdd-decision-audit`: (consumer) a budgeted dossier of accepted decisions
  governing a spec's subsystems and symbols, generated into the spec before
  design; (producer) a structured Decisions section ingested on approval;
  (gate) a consequence preview persisted into the spec and enforced as a
  one-rule gate; a seeded, subsystem-anchored set of architecture rules and
  the subsystem taxonomy they attach to.

### Modified Capabilities
- `sdd-spec-wiki-adr` (FEAT-578): the "no compliance/drift verdicts" non-goal
  is reopened for the *preview* case; `DecisionLink.relation` and the ADR
  frontmatter vocabulary gain `constrains/forbids/requires` + `targets`;
  discovery inventory accepts approved specs in addition to `adr_globs`.
- `sdd-spec` command and `sdd/templates/spec.md`: new generated section
  (`## Governing Decisions`, before Section 2), new authored section
  (`## Decisions`) and generated section (`## Consequences`); gate between
  scaffold and commit.
- `sdd-task` / coder contracts: the governing dossier for a task's files is
  carried into the task's Codebase Contract so coder seats inherit decisions
  as constraints, not only signatures.
- `domain-experts` (FEAT-778): shares the accepted-only, budgeted ADR
  consumer; whichever lands first defines the adapter the other reuses.

Later phases (separate specs, not this one):
- `sdd-task-certificate`: per-task asserted facts + derivations (AC → test →
  commit → symbol), re-derived by an independent deterministic checker in
  `/sdd-done` (symbol-level layer).
- `sdd-decision-drift`: scheduled re-hash of accepted records' evidence;
  `stale`/`missing` opens a ledger issue (`LedgerService.open_issue`,
  kind `tech_debt`, `discovered_from: decision:<id>`).
- `sdd-decision-backfill`: bounded `generation.py` candidates over historical
  approved specs, human-reviewed.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/decisions/models.py` | modifies | additive relations on `DecisionLink`; optional `targets` on `DecisionRecord` (or carried as `supported_by` links with `provenance="asserted"`) |
| `parrot/knowledge/wiki/decisions/parser.py` | modifies | `FRONTMATTER_KEYS` + list-valued `targets`; new relation vocabulary |
| `parrot/knowledge/wiki/decisions/ingest.py` | extends | approved specs join the discovery inventory |
| `parrot/knowledge/wiki/decisions/` (new `consequences.py`) | extends | `ConsequenceService`, `ConsequenceReport`, finding models |
| `parrot/knowledge/wiki/structural/service.py` | depends on | `lookup()`, `blast_radius()` unchanged |
| `parrot/knowledge/wiki/transport.py` | extends | `wiki_spec_consequences` MCP spec; the exact-set MCP tests (ledger issue `36a652416160`) will need their expected set bumped |
| `parrot/knowledge/okf/ontology.py` | modifies | `RelationType.CONSTRAINS / FORBIDS / REQUIRES` (additive, stable strings) |
| `scripts/sdd/check_spec_consequences.py` (new) | extends | gate script, `check_task_graph.py` shape |
| `.claude/commands/sdd-spec.md` + `.agent/workflows/sdd-spec.md` | modifies | retrieve the governing dossier in §4 (before §5 scaffolds Section 2); run gate between §5 and §6; refuse approval on blocking findings |
| `.claude/commands/sdd-task.md` | modifies | carry the per-file governing dossier into each task's Codebase Contract |
| `sdd/templates/spec.md` | modifies | `## Governing Decisions` (generated), `## Decisions` (authored), `## Consequences` (generated) |
| subsystem taxonomy (new, versioned; location open) | extends | the `about` vocabulary; `KNOWN_PROJECTS` is the coarse layer above it |
| `sdd/specs/domain-experts.spec.md` (FEAT-778, 0/22 started) | depends on / shares | same `DecisionService` consumer contract; sequencing is an open question |
| `docs/decisions/*.md` (new) | extends | seeded architecture rules, already an `adr_glob` |
| `.github/workflows/*` | extends | run the gate on PRs touching `sdd/specs/` |
| `wikitoolkit` CLI | extends | `spec consequences <path>` |

No breaking changes to existing records: `schema_version` stays 1 if the new
fields are optional; existing ADR files without `targets` keep parsing.

---

## Code Context

### User-Provided Code

None. The user provided the reference repository
`https://github.com/fabio-rovai/open-ontologies` (MIT; Rust core on
Oxigraph 0.5, `rmcp` MCP server, Lean 4 checkers `oo-cert`/`oo-horn`;
concepts: plan/apply/drift/certify/rollback, derivation certificates as
`asserted.tsv` + `derivations.tsv`, `onto_conservative_check`, blast radius,
`asserted.sha256` digest).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:107
class EvidenceRef(_Strict):
    page_id: str; rel_path: str; start_line: int; end_line: int
    source_sha1: str                       # line 114
    kind: Literal["adr", "code", "comment", "document"]   # line 116

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:140
class DecisionLink(_Strict):
    target_id: str
    relation: Literal["explains", "supported_by", "supersedes"]   # line 144 — to extend
    provenance: Literal["extracted", "inferred", "asserted"]      # line 145
    evidence_indexes: list[int]

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:172
class DecisionRecord(_Strict):
    schema_version: Literal[1] = 1
    decision_id: str; revision: int = 1
    source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"] = "unknown"  # line 182
    origin: Literal["documented", "inferred"]                      # line 184
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"   # line 185
    source_path: str | None; evidence: list[EvidenceRef]; links: list[DecisionLink]
    review_history: list[ReviewEvent]; content_fingerprint: str = ""

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:299
class ReviewRequest(_Strict):
    decision_id: str; expected_revision: int
    action: Literal["accept", "reject", "revise", "link"]; actor: str

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:63
class DecisionConfig(_Strict):
    adr_globs: list[str]   # default ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]
    generation_enabled: bool = False   # line 71

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py:96
class DecisionService:
    def __init__(self, store: BaseWikiStore, root: Path | None, config: DecisionConfig,
                 structural: StructuralService | None = None, client: AbstractClient | None = None) -> None  # line 99
    async def for_symbol(self, symbol: str, *, include_history: bool = False, limit: int = 10,
                         budget_tokens: int = 3000) -> DecisionDossier   # line 193
    async def why(self, question: str, *, include_history: bool = False, limit: int = 10,
                  budget_tokens: int = 3000) -> DecisionDossier         # line 276
    async def sync(self, paths: list[str] | None = None) -> SyncResult   # line 371
    async def review(self, request: ReviewRequest) -> DecisionRecord    # line 473
HISTORICAL_STATUSES = frozenset({"rejected", "deprecated", "superseded"})   # line 73

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]            # line 43
async def refresh_decisions(store: BaseWikiStore, root: Path, config: DecisionConfig,
                            paths: list[str] | None = None) -> SyncResult            # line 252
async def project_links(store: BaseWikiStore, records: list[DecisionRecord]) -> int  # line 380

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py:226
async def verify_freshness(root: Path | None, evidence: EvidenceRef) -> tuple[str, DecisionDiagnostic | None]

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py
FRONTMATTER_KEYS = ("id", "title", "status", "supersedes")   # line 28 — flat scalars only
def parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], int, list[DecisionDiagnostic]]   # line 132
def resolve_status(frontmatter_status: str, section_status: str) -> tuple[str, str, list[DecisionDiagnostic]]  # line 186

# From packages/ai-parrot/src/parrot/knowledge/wiki/decisions/review.py:86
def apply_review(record: DecisionRecord, request: ReviewRequest) -> DecisionRecord

# From packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
class BlastRadiusOutput(BaseModel):            # line 93
    root: SymbolHit | None; impacted: list[ImpactedSymbol]; files: list[str]; truncated: bool
class StructuralService:                     # line 130
    async def lookup(...)                      # line 182
    async def outline(...)                     # line 264 — accepts file:<rel> or sym:<rel>#<qualname> (line 274)
    async def blast_radius(self, symbol: str, *, relations: list[str] | None = None, depth: int = 2,
                           include_inferred: bool = True, include_tests: bool = True) -> BlastRadiusOutput  # line 360

# From packages/ai-parrot/src/parrot/knowledge/wiki/structural/operations.py:44
class BlastRadiusInput(BaseModel):
    symbol: str
    relations: list[Literal["calls","extends","implements","uses","references","contains"]] | None
    depth: int = 2  # ge=1, le=5

# From packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
class RelationType(str, Enum):   # line 85
    REFERENCES = "references"    # line 96
    SATISFIES = "satisfies"      # line 98
    SUPERSEDES = "supersedes"    # line 100
    IMPLEMENTS = "implements"    # line 102
    CONTRADICTS = "contradicts"  # line 116
    SUPPORTED_BY = "supported_by"  # line 121

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:243
class LedgerService:
    async def open_issue(self, title: str, body: str, kind: IssueKind = "bug", severity: str = "minor",
                         discovered_from: str = "", about: list[str] | None = None,
                         actor: str = "agent:sdd") -> str

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py:51
class SDDGraphIngest:
    def __init__(self, store: "LedgerStore", shared_root: Path) -> None
    async def ingest_all(self) -> dict[str, int]      # line 66 — spec:/task: nodes, implements/blocks/touches edges

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
class FlowMeta(BaseModel): type: Literal["feature","hotfix"]; base_branch: str   # line 101
class DocTaxonomy(BaseModel): projects: list[str]; tags: list[str]              # line 220
KNOWN_PROJECTS: frozenset[str]                                                   # line 45

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:824 (and :1865 in the SQLite impl)
async def compare_and_swap_page(...)

# From scripts/sdd/check_task_graph.py
class Finding(BaseModel)        # line 77
class GraphReport(BaseModel)    # line 86
def check_graph(index_path: Path, root: Path) -> GraphReport   # line 499
def main(argv: list[str] | None = None) -> int                 # line 651

# From packages/navrules/src/navrules/ruleset.py:20 (Option B only)
class RuleSet(Generic[T]):
    def __init__(self, rules=(), *, policy: Policy = Policy.ALL_MATCH, default=None,
                 backend: Backend = "auto", loader=None) -> None
# From packages/navrules/src/navrules/policies.py:14
class Policy(str, Enum)
```

#### Verified Imports
```python
from parrot.knowledge.wiki.decisions import DecisionService, DecisionRecord, EvidenceRef, ReviewRequest, DecisionConfig  # lazy PEP 562 exports, decisions/__init__.py:52-87
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions, project_links, discover_adr_sources
from parrot.knowledge.wiki.decisions.evidence import verify_freshness
from parrot.knowledge.wiki.structural import StructuralService
from parrot.knowledge.wiki.structural.operations import BlastRadiusInput
from parrot.knowledge.okf.ontology import RelationType, ConceptType
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.sdd_meta import FlowMeta, DocTaxonomy, KNOWN_PROJECTS
```

#### Key Attributes & Constants
- `DecisionConfig.adr_globs` default includes `docs/decisions/**/*.md` → the seed location needs no new loader (models.py:67).
- `DecisionLink.relation` is a closed Literal `explains|supported_by|supersedes` (models.py:144) → must be extended for `constrains/forbids/requires`.
- `parser.FRONTMATTER_KEYS` reads only flat scalars; a list-valued `targets:` line currently raises `ADR_PARSE_FAILED` "non-flat-scalar line" (parser.py:180).
- MCP tool specs live in `transport.py` (`wiki_blast_radius` :168, `wiki_decisions_for_symbol` :192, `wiki_decision_why` :197).
- `/sdd-spec` hook points: `.claude/commands/sdd-spec.md` §5 "Scaffold the Spec" (:444) and §6 "Commit the Spec" (:580).
- `sdd/templates/spec.md` has `## 5. Acceptance Criteria` (:230) and `## 6. Codebase Contract` (:243); no Decisions/Consequences sections today.
- Related closed features touching this code (no open worktrees): FEAT-578 (20/20), FEAT-675 `decisions-cli-fixes` (1/1), FEAT-760 `adr-prefixed-aliases` (8/8).
- Related open ledger issues: `36a652416160` (MCP tests pin the exact tool set — adding a tool breaks them), `b084239103d7` (document-level `[text](sym:…)` citation extraction from FEAT-578 spec §2/§3 appears unimplemented — the Decisions section should not depend on it).
- FEAT-778 contract to share (`sdd/specs/domain-experts.spec.md`): G6 "ADR as consumer and producer" (:62); `adr` source calls `DecisionService.why()` / `for_symbol()` with `budget_tokens`, accepted only (:145); prompt layer order ends in `accepted ADRs` (:132); `KnowledgeSource.ADR = "adr"` with `filter: {"status": ["accepted"]}` (:209, :217).
- `RelationType.ABOUT = "about"` exists (okf/ontology.py, work-lineage relations) and is the natural record → subsystem-concept edge; `DocTaxonomy.projects` / `KNOWN_PROJECTS` (sdd_meta.py:45, :220) are the coarse subsystem axis every SDD doc already declares.

### Does NOT Exist (Anti-Hallucination)
- ~~`docs/adr/`, `docs/adrs/`, `docs/decisions/`~~ — none of the three `adr_globs` directories exist in this repo; the decision plane has **zero** documented records today.
- ~~`RelationType.CONSTRAINS` / `FORBIDS` / `REQUIRES`~~ — not in `okf/ontology.py`; to be added.
- ~~`ConsequenceService` / `ConsequenceReport`~~ — nothing under `parrot/knowledge/wiki/` by that name.
- ~~`scripts/sdd/check_spec_consequences.py`~~ — does not exist; `check_task_graph.py` is the shape to copy.
- ~~`## Decisions` / `## Consequences` sections in `sdd/templates/spec.md`~~ — not present.
- ~~`targets:` frontmatter key in the ADR parser~~ — not read; only `id/title/status/supersedes`.
- ~~`DecisionRecord.tags`~~ — no tag/component filter on records (FEAT-778 finding F043); retrieval is by symbol link or token overlap only.
- ~~any decision-plane call in the SDD authoring lane~~ — `.claude/commands/sdd-spec.md`, `.claude/commands/sdd-task.md`, `.claude/agents/sdd-coder.md`, `.claude/agents/sdd-worker.md` contain zero references to `wiki_decision_why` / `wiki_decisions_for_symbol` (grep, 2026-10-31).
- ~~`KnowledgeResolver`~~ — specified by FEAT-778 (`sdd/specs/domain-experts.spec.md`) but not in the tree; `sdd/tasks/index/domain-experts.json` shows 0 of 22 tasks done.
- ~~`parrot.knowledge.ontology.concept_catalog` as the subsystem taxonomy~~ — it exists, but it is FEAT-159's per-tenant *topic* ontology in Postgres (content concepts, `is_a` taxonomy); it is not a taxonomy of code subsystems and should not be reused as one without a separate decision.
- ~~a CI workflow step for `check_task_graph` / `check_e2e_closeout`~~ — grep of `.github/workflows/*.yml` found no reference; those gates run from the commands, not CI. The new gate's CI wiring is therefore new, not a copy.

---

## Parallelism Assessment

- **Internal parallelism**: three independent lanes after the model bump:
  (a) parser + models + ingest extension (`decisions/`), (b) the
  `ConsequenceService` + MCP/CLI surface (depends on (a) only for the new
  relation literals), (c) the gate script + `/sdd-spec` + template +
  `docs/decisions/` seed (depends on (b) for the report shape). (c)'s template
  and seed files can start in parallel with (a).
- **Cross-feature independence**: every feature that touched
  `parrot/knowledge/wiki/decisions/` is closed (FEAT-578, FEAT-675, FEAT-760)
  and no worktree is open on it. FEAT-778 (domain-experts, 0/22) will *read*
  `DecisionService` through its `adr` source; it does not modify the plane,
  so the collision risk is on the adapter shape, not on files. Shared surfaces to watch: `transport.py`
  (any in-flight feature adding MCP tools collides on the exact-set tests),
  `sdd/templates/spec.md` and `.claude/commands/sdd-spec.md` (frequently
  edited by SDD-tooling features; rebase early).
- **Recommended isolation**: `mixed` — one feature worktree, with the
  seed/template lane allowed as a parallel sub-worktree.
- **Rationale**: the model/parser change is small and must land first; the
  service and the SDD-tooling lane are otherwise disjoint file sets.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesús*: feature on `dev`.
- [x] Who asserts a decision — *Owner: Jesús*: a structured, human-approved section of the spec; no LLM inference on the critical path.
- [x] Granularity — *Owner: Jesús*: two layers; module-level architecture rules in v1, symbol-level task contracts in the certificate phase.
- [x] v1 core — *Owner: Jesús*: consequence preview in `/sdd-spec`; task certificate, drift job and backfill are later phases.
- [x] Checks in v1 — *Owner: Jesús*: contradictions, blast radius, undeclared supersedes, evidence gaps (all four).
- [x] Verdict semantics — *Owner: Jesús*: `## Consequences` written into the spec; only an unresolved contradiction blocks.
- [x] Target resolution — *Owner: Jesús*: explicit `sym:`/`file:`/`dir:` ids; unresolved target is a spec error.
- [x] Seed — *Owner: Jesús*: curated architecture-rules file(s), approved once, ingested as accepted.
- [ ] Decisions vocabulary: are `constrains / forbids / requires / supersedes` enough, or is an `allows` (explicit exception) relation needed so a spec can carve out an exemption without superseding the rule? — *Owner: Jesús*
- [ ] Seed format: ADR-style markdown under `docs/decisions/` (reuses `adr_globs`, one file per rule) vs a single `sdd/decisions.yaml` (needs a new loader but is easier to review as one diff)? — *Owner: Jesús*
- [ ] Where `targets` live on the record: a new optional `targets: list[str]` field on `DecisionRecord`, or reuse `DecisionLink(relation="supported_by", provenance="asserted")` pointing at the symbol page ids (no model change beyond the relation literals)? — *Owner: spec author*
- [ ] Is the `## Consequences` section regenerated on every `/sdd-spec` run, or frozen at approval with its digest and only refreshed on demand? — *Owner: Jesús*
- [ ] Gate execution: `/sdd-spec` only, or also a CI job on PRs touching `sdd/specs/`? (No CI wiring exists for the current `check_*` gates.) — *Owner: Jesús*
- [ ] Blast-radius defaults for the preview: depth 2 with `calls/extends/implements/uses`, and should `include_tests` be off to keep reports short? — *Owner: spec author*
- [ ] Should the preview also run for `/sdd-brief` (hotfix) specs, which never pass through `/sdd-spec`? — *Owner: Jesús*
- [ ] Option C as an optional external cross-check (`--verifier open-ontologies`) once the plane has content: worth a spike, or out of scope until the task-certificate phase? — *Owner: Jesús*
- [x] Should the plane also feed spec *authoring*, not only gate it? — *Owner: Jesús*: yes — decisions are curated ontological knowledge consumed by `/sdd-spec` (generated `## Governing Decisions`) and produced by it; retrieval needs a subsystem axis (`about`) besides symbols (2026-10-31).
- [ ] Where does the subsystem taxonomy live and who curates it: a versioned file under `sdd/` (reviewed like the seed), an extension of `KNOWN_PROJECTS` in `sdd_meta.py`, or OKF concept pages in the wiki plane itself? — *Owner: Jesús*
- [ ] Sequencing with FEAT-778: build the SDD consumer directly on `DecisionService` now and migrate to the shared `KnowledgeResolver` `adr` source later, or wait for FEAT-778's M5 to land first? — *Owner: Jesús*
- [ ] Is `## Governing Decisions` mandatory for approval (a spec cannot be approved without having read its domain), or advisory in v1? — *Owner: Jesús*
- [ ] Does `/sdd-task` carry the governing dossier into every task contract in v1, or only `/sdd-spec` in v1 and tasks in the certificate phase? — *Owner: spec author*
