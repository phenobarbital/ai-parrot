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
**Status**: accepted
**Recommended Option**: A (accepted 2026-10-31; owner decisions below resolved on the owner's instruction, conservative defaults from the audit)

---

## Problem Statement

The SDD flow reviews *code* (`/sdd-codereview`, `sdd-secondopinion`, the GitHub
reviewer) but lacks the unified approval-time decision gate proposed here.
Existing ADR lint and architectural tests cover narrower checks.
A code review asks "is this diff good?".
An audit asks: which decision was taken, under which constraints that were
already in force, does it contradict a decision accepted earlier, does the
implementation honor it, and does it still honor it today. That chain —
provenance, consistency, re-verifiability — lives today only in prose:
`CLAUDE.md`, `.agent/CONTEXT.md`, Completion Notes, review markdown. Those sources are not yet joined into a single approval-time decision contract;
existing ADR APIs, lint rules and regression tests cover parts of the problem.

Concrete symptoms:

- Hard architectural rules ("clients are memory-less", "`AbstractBot` is the
  sole writer of conversation history", "never `httpx`", "concrete tools live
  in `parrot_tools`") exist as paragraphs. Some are enforced mechanically: `TID251` and the FEAT-524 memory/history
  ownership regression tests. There is no unified decision-consistency gate.
- One documented design audit was done **by hand**
  (`sdd/proposals/plan-then-execute-design-drift.findings.md`, 2026-09-20):
  a section-by-section comparison of a design document against `dev`. Its conclusions are tied to that snapshot and need revalidation for current code.
- FEAT-578 built a complete ADR "decision plane"
  (`parrot.knowledge.wiki.decisions`: `DecisionRecord`, hashed `EvidenceRef`,
  freshness `current|stale|missing|unverified`, attributed review) and then
  declared **as a non-goal**: "Automatic architectural compliance/drift
  verdicts". The infrastructure for an audit exists; the audit was deliberately
  left out.
- The plane is **empty** in this repository: `docs/adr/`, `docs/adrs/` and
  `docs/decisions/` (the three `adr_globs`) do not exist, and a local decision-plane query with history included independently returned
  no records during the audit. Missing directories alone would not prove emptiness.
- Even where records exist, **nothing in the SDD authoring lane consumes
  them**: `/sdd-spec`, `/sdd-task`, `sdd-coder` and `sdd-worker` never call
  `wiki_decision_why` / `wiki_decisions_for_symbol`. The Codebase Contract
  tells a spec author *what exists*; nobody tells them *what was decided and
  why*. FEAT-778 (domain-experts) designed exactly that consumer — a
  `KnowledgeResolver` with an `adr` source that loads accepted decisions
  through `DecisionService` under a token budget, as a fixed prompt layer —
  for runtime expert agents. All 22 tasks are now done, and `KnowledgeResolver`
  and `ADRSource` exist; their lexical, budgeted output is not a complete gate input.
- Retrieval is the ceiling: a `DecisionRecord` is found by symbol link or by
  token overlap. There is no filter by component, subsystem or capability
  (no `tags`, FEAT-778 finding F043), so "what is decided about conversation
  memory?" — the question a spec author actually asks — can only use lexical retrieval today; explicit domain filtering and coverage
  guarantees are absent.

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

Recorded discovery constraints (Rounds 0–2, owner Jesús); the audit clarifications
below are proposed contract corrections, not new owner answers:

- Flow: `feature` on `dev`.
- **Assertion**: decisions enter the graph only from a structured, human-approved
  section of the spec. No LLM inference on the critical path.
- **Granularity**: two layers — architecture rules at module/package level,
  task contracts at symbol level. v1 ships the first layer; the second is the
  task-certificate phase.
- **v1 core**: consequence preview in `/sdd-spec`. Task certificates, drift
  job and retroactive inference are later phases.
- **Checks in v1**: contradictions with accepted decisions; blast radius of the
  symbols the spec touches; possible undeclared supersession (advisory, not formal conservativity); evidence
  gaps (accepted decisions whose evidence is already stale/missing inside the
  spec's radius).
- **Verdict**: a `## Consequences` section is written into the spec (auditable
  in git). Only an *unresolved contradiction* with an accepted decision blocks
  approval among complete evaluations; malformed inputs and incomplete audits
  also prevent approval. Other findings remain advisory.
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
  guarantees this for ordinary decision reads, not explicit generation; the preview must keep it).
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

**Contract correction, 2026-10-31:** incorporates F01–F10 from
`sdd-decision-audit.findings.md`. These are proposed design corrections, not
additional discovery answers attributed to the owner. The document remains
`exploration`; approval integration and optional delivery scope remain open.

The v1 service checks **consistency of declared decisions**, not whether code
implements prose rules. It has two outputs over one complete, versioned input
inventory: a budgeted dossier for authoring and an unbudgeted evaluation for
approval. No lexical match or LLM judgment establishes applicability or a
blocking contradiction.

0. **Authoritative inventory before presentation.** Introduce a shared read
   contract over `DecisionRepository` that returns complete records, revisions,
   source provenance and diagnostics from a consistent snapshot. A record is
   eligible when `origin == documented`, `source_status == accepted`,
   `review_status != rejected`, and it is effective under the validated
   supersession graph. An accepted documented ADR may remain `unreviewed`;
   double acceptance is not required. Inferred records remain suggestions.
   New spec/seed records additionally require a verified approval batch.
   Filtering happens before ranking/packing. Inventory overflow, decode
   failures or unstable reads mean `incomplete`, never an empty clean result.

1. **Governing dossier.** Retrieve by explicit `about` concepts and structural
   scope, union/deduplicate by canonical ID, then render under a token budget.
   A versioned mapping connects `projects` and recognized `tags` to subsystem
   concepts; arbitrary tags do not silently become concepts. Unknown mappings
   are shown to the author; authored `about` values must be valid taxonomy IDs.
   Load full records for rationale/context, consequences and supersession
   references. Rejected alternatives are shown only when explicitly recorded;
   missing fields say “not recorded”, never inferred. List omitted IDs and
   domains separately from “no accepted records”. Budget truncation affects
   presentation only. Presence of a dossier is not proof that a human read it.

2. **Structured producer.** A dedicated parser reads a versioned YAML block
   inside `## Decisions`, containing `schema_version`, a stable `document_id`
   and an `entries` list. Each entry has an immutable local `id`, `statement`,
   `relation` in `{constrains, forbids, requires}`, nonempty `about` and
   `targets` lists, and optional `contradicts` and `supersedes` lists of
   `{decision_id, revision}` references. `supersedes` is a lifecycle link, not a normative
   relation. Optional rationale and rejected-alternative text is authored.
   Canonical IDs use `adr:spec:<document_id>#<entry_id>`; both components are
   immutable repository-unique/document-local identifiers respectively, limited
   to lowercase ASCII letters, digits, hyphens and underscores. IDs derive from
   the stable document ID plus entry ID, not only the path;
   source paths/spans remain provenance. Duplicate IDs, unknown fields and
   dangling references fail validation. New entries can reference one another
   via their canonical IDs and proposed revisions; unresolved intra-proposal
   conflicts also block. New entries start at revision 1; edits preserve ID,
   increment revision and explicitly pin their previous revision. Updating a
   record is a revision transition, not a self-referential supersedes edge.
   This is new parsing/identity work: `parse_adr()` currently yields one
   path-identified record per document. Preserve ordinary ADR v1 parsing.

3. **Typed targets and scope.** A new resolver validates exact local `sym:`,
   `file:` and `dir:` IDs against confined repository paths and structural
   records. `StructuralService.lookup()` is for name suggestions only;
   `DecisionService._resolve_symbol()` is not an existence validator.
   A symbol target covers that symbol; a file target covers its file/symbols;
   a directory target covers path-segment descendants recursively. Consult
   ancestor scope when collecting governing decisions. Directory expansion
   must prove completeness against the declared scan inventory. Unsupported
   files may be governed at file scope, but must not imply complete symbol
   impact analysis. v1 targets must exist: decisions about future components
   anchor to an existing container and state that scope explicitly. The gate
   never invents a future node. A later phase may add typed proposed targets.

4. **Deterministic findings.** Blocking `contradiction` requires an explicit
   `contradicts` reference between the proposal and an effective accepted
   record, or between proposed entries. Either direction establishes the
   declared conflict, independently of target overlap. Sharing a target with
   opposite `forbids`/`requires` relations yields advisory `potential-conflict`;
   sharing a target and relation yields advisory `possible-supersession`.
   Neither proves semantic disagreement or conservativity. `blast-radius`
   reports impacted dependents; `evidence-gap` reports stale/missing/unverified
   evidence. Impact does not propagate normative applicability. Absent
   declarations, semantic contradictions may remain undetected in v1.

5. **Approval and supersession.** A proposed `supersedes` link names an exact
   active predecessor revision and represents full replacement in v1. Validate
   existence, local identity, acyclicity, identical canonical target sets and absence
   of competing effective successors. No implicit partial replacement or
   exception. Historical targets yield a diagnostic with their active heads;
   do not silently retarget the author's link. The prospective replacement
   resolves only the conflict with that predecessor, and becomes effective
   only when the same proposal batch receives human approval.
   Optional conflict waivers live in a separate authored block, with stable
   finding fingerprint, participating decision revisions, actor, reason and
   verifiable approval reference. Generated markdown cannot authorize a waiver.
   Any changed participant invalidates it. The trust adapter must verify actor,
   scope and approval against versioned evidence; its concrete mechanism must
   be chosen before implementation. No adapter means no ingestion or waiver
   acceptance, not a fallback to trusting `status: approved`.

6. **Publication and evidence.** Extend ingestion with a spec-entry adapter
   and approval-batch manifest. Parse/validate all entries, then publish one
   effective batch only after its complete manifest and approval are valid.
   Per-record CAS remains the write primitive; it is not a multi-record
   transaction. Partial/retried writes must never expose half an approved
   proposal. Edits require a new approved batch; removed entries require an
   explicit retirement, not silent deletion. Preserve prior approved revisions
   and review history. Store declaration/approval provenance separately from
   target applicability and optional implementation evidence. A hash proves
   source freshness, not compliance. Spec/seed approval sets documented source
   acceptance; review events remain attributed and are not manufactured by sync.

7. **Seed, persistence and compatibility.** Prefer ADR Markdown under
   `docs/decisions/` for the seed; the existing glob only handles discovery.
   Extended metadata and approval still require code. Add explicit `about`
   and `targets` fields to the canonical decision model, keeping `supported_by`
   for evidence. Project ABOUT/normative edges as rebuildable caches; retrieval
   validates canonical records. Use a new schema version for extended records:
   new readers support legacy v1 and the extended schema; old readers must
   fail explicitly, so readers upgrade before writers. Legacy records retain
   their IDs. Migration, rollback and all consumers' compatibility are part of
   the spec, not a claim that optional fields are universally nonbreaking.

8. **Surfaces and scope.** `ConsequenceService` exposes one typed evaluation
   shared by CLI, MCP and `scripts/sdd/check_spec_consequences.py`. `/sdd-spec`
   retrieves before design and verifies before approval. Three sections:
   `Governing Decisions`, `Decisions`, `Consequences`; approval/waiver metadata
   is authored separately. Rendering is explicit and idempotent; checking
   never rewrites files. CI and task-dossier propagation are optional v1 delivery
   items pending owner scope, not prerequisites silently assumed to exist.

✅ **Pros:**
- Reuses record persistence, source hashing, review provenance and transports
  without introducing a second authoritative decision plane.
- One shared authority/scope contract feeds complete checks and bounded author
  context. Offline results are reproducible for the same versioned inputs.
- Existing ADR discovery and FEAT-778 consumers provide integration points.

❌ **Cons:**
- New identity/parser, scope resolver, snapshot/approval protocol and schema
  migration are substantial work; this is not “mostly wiring”.
- Explicit conflict declarations provide no automatic semantic completeness.
- Taxonomy, stable IDs and approval provenance require maintained artifacts.
- FEAT-778 is already implemented (22/22 tasks done). Its current `ADRSource`
  uses lexical `why()` and emits title/decision only; it is not a drop-in
  implementation of the strict domain dossier. Share authority/retrieval
  primitives through an explicit adapter contract, without requiring an
  unrelated runtime refactor in this feature.

📊 **Effort:** Medium–High; estimate after approval/snapshot contracts are frozen.

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` ≥ 2 | versioned reports, validation and model evolution | existing core dependency |
| `wikitoolkit` | local decision/structural planes and transport | existing infrastructure |
| `PyYAML` | structured entries and extended seed metadata | direct core dependency |

🔗 **Existing code to reuse, with boundaries:**
- `decisions/models.py`, `repository.py`, `codec.py`: canonical records and
  CAS; extend schemas/identity and complete snapshot reads explicitly.
- `decisions/parser.py`, `ingest.py`: legacy ADR parser/discovery; add a
  separate multi-entry spec adapter and approval-aware batch publication.
- `decisions/evidence.py`: freshness only, not a compliance verifier.
- `decisions/service.py`, `render.py`: presentation patterns; their budgeted
  `why()`/`for_symbol()` outputs must not be gate inputs.
- `structural/service.py`: impact traversal, with explicit freshness and
  completeness checks; a typed target resolver is new work.
- `experts/knowledge/resolver.py`, `experts/knowledge/sources/adr.py`:
  implemented FEAT-778 consumer; compatibility target, not a future dependency.
- `wiki/transport.py`, `scripts/sdd/check_task_graph.py`: transport/report shape.
- `ledger/sdd_meta.py`, `okf/ontology.py`: coarse taxonomy and ABOUT vocabulary;
  exact subsystem mapping and authoritative fields are new work.

Paths above are relative to `packages/ai-parrot/src/parrot/knowledge/` except
`experts/`, which is relative to `packages/ai-parrot/src/parrot/`; `decisions/`
and `structural/` are under `knowledge/wiki/`.

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

**Option A** remains recommended: it extends the canonical decision plane and
keeps consumer, producer and verifier on one authority model. Its advantage is
lower integration duplication, not exclusive access to a consumer/producer
design. B/C could also consume projections of those records.

The corrected v1 provides explicit-conflict checking plus advisory structural
signals. It does not prove conservativity, semantic consistency or implementation
compliance. Certificates, drift jobs and backfill remain later phases. A rich
dossier, multi-entry ingestion and approval snapshots are new contracts, so
the earlier “one service and one parser extension” estimate is withdrawn.

## Feature Description

### User-Facing Behavior

1. Before design, `/sdd-spec` generates `## Governing Decisions` from the
   complete eligible inventory for the declared domains and existing targets.
   Entries cite provenance and freshness; omitted entries remain enumerable.
2. The author declares structured entries in `## Decisions`. Targets use
   explicit scope; `contradicts` and `supersedes` name exact canonical records.
3. Preview generates `## Consequences` with input/evaluation digests, coverage,
   blocking conflicts and advisory findings. JSON retains the full result;
   shortening Markdown never removes a finding from the verdict.
4. Fix invalid inputs/incomplete checks first; resolve declared conflicts by
   revising the proposal, a validated prospective replacement, or an approved
   waiver. Editing generated findings or adding an unverified owner string
   cannot change the result.
5. Approval requires a current passing report and verified human approval of
   that exact proposal batch. A status edit alone cannot activate decisions.
   Ingestion publishes the complete batch, then future specs can consume it.
6. CLI/MCP share the evaluator. The CLI has explicit render and read-only check
   modes; check fails when persisted generated sections are absent or stale.
   A future CI job uses the same check mode with a reproducible local snapshot.

### Internal Behavior

**Snapshot and baseline.** Build a manifest from versioned decision sources,
approval/retirement events, taxonomy/mapping, evaluator/config versions and a
structural index tied to the evaluated repository content. SQLite is a derived
cache, not the only source of approval history. Record source-byte hashes for
every observed freshness check and a complete inventory manifest so additions
and removals invalidate results. A consistent read transaction or a revision
recheck/retry must prevent mixed reads; exhaustion returns `incomplete`.

For initial approval, compare the proposal with the current approved baseline.
For a revision, retain the prior approved entries as baseline, deduplicate
unchanged entries and evaluate changed entries as replacements. For replay of
an approved batch, use its recorded pre-publication baseline; do not compare a
decision against its newly ingested self. Distinguish historical replay from
a fresh preview against today's governing inventory in the report.

**Parse and resolve.** Validate entries, identities, taxonomy, target scope,
links and approval metadata before judging. Resolve exact IDs by type; name
lookup may suggest corrections only. New components use existing containers
in v1. Collect governing records by explicit domain and ancestor structural
scope, with no dependence on a projected edge alone. Empty directories can be
valid scopes; missing/unsupported index coverage is reported explicitly.

**Impact and collection.** Compute reverse dependency radius over the resolved
symbols, default depth 2 and `calls/extends/implements/uses`. Include tests;
exclude inferred edges from the required traversal, with optional inferred
impact labeled separately. Completeness is relative to these declared bounds,
not a claim of whole-program impact. Caps, missing source coverage or stale
index state in the required traversal return `incomplete`. Collect the entire
eligible decision set before any token budget. Inspect explicit cross-domain
references too. Scope eligibility and impact are separate fields.

**Judge.** Emit stable findings keyed by rule/version, participant IDs and
revisions, and relevant scope:

| Kind | Meaning | Effect |
|---|---|---|
| `contradiction` | explicit unresolved `contradicts` link | blocks |
| `potential-conflict` | overlapping scope, opposing normative labels | advisory |
| `possible-supersession` | overlapping scope, same normative label, no declared replacement | advisory; not conservativity |
| `blast-radius` | impacted dependent with governing decisions not mentioned by the proposal | advisory |
| `evidence-gap` | accepted record has stale/missing/unverified evidence | advisory; no compliance verdict |

Validate a prospective supersession against the predecessor revision and batch
approval requirements; suppress only that resolved predecessor conflict.
Validate waivers against finding fingerprints and trusted approval evidence.
No chain traversal silently alters authored IDs or scope. A source read that
legitimately shows missing evidence is an advisory gap; a failure to enumerate
the authoritative inventory is an incomplete audit.

**Digest and render.** Canonicalize authored spec content, entries, waiver
payloads and configuration with deterministic ordering and normalized encoding;
exclude generated sections, generated approval receipts and the workflow status
marker whose transition is separately verified by the approval adapter. Other
authored changes invalidate approval. Define an input
digest over that payload plus the snapshot manifest, and an evaluation digest
over the input digest plus canonical findings. Approval receipts bind these
digests externally; waiver approval binds participant revisions/fingerprints
before the full evaluation digest is computed, avoiding self-reference.
Render sections in stable order without volatile timestamps. Re-rendering
unchanged inputs must be byte-identical. Check recomputes and compares both
digests and generated content. Changed source bytes, inventory membership,
taxonomy, structural edges, rules or config invalidate the prior report.

**Gate result contract.** Separate evaluation completeness from findings:

| Status / exit | Condition | Approval |
|---|---|---|
| `pass` / 0 | complete, valid, current; no unresolved declared conflict | eligible, still requires human approval |
| `conflict` / 1 | complete evaluation with unresolved declared conflict | refused |
| `invalid` / 2 | malformed input, invalid target/link/taxonomy, missing or stale persisted report in check mode | refused |
| `incomplete` / 3 | unavailable/inconsistent inventory, unsupported schema, incomplete required structural coverage or cap | refused |

Operational failures must never map to exit 0. If several conditions occur,
`invalid` takes precedence over `incomplete`, then `conflict`; retain all
diagnostics. Advisory findings and presentation truncation do not change a
complete result to failure. An empty complete plane is explicitly labeled and
may pass; the approved seed is a separate rollout prerequisite.

**Publish.** Recheck snapshot revisions and verified approval immediately before
activating the batch. Reject stale approval or partial batches; retries are
idempotent. Effective supersession/retirement is derived from approved events,
without silently rewriting source ADR text. A later batch failure cannot leave
old decisions retired while successors are invisible. Projected edges may be
rebuilt after publication and are never used as sole authority.

### Edge Cases & Error Handling

- Missing/ambiguous/foreign targets, unknown authored taxonomy IDs, duplicate
  entry IDs, missing referenced decisions and supersession cycles are `invalid`.
- A superseded predecessor produces active-head suggestions; the author must
  choose explicitly. Partial replacement and competing successors are invalid
  in v1. Removing an entry without an explicit retirement request is invalid.
- A no-decision spec still validates its Codebase Contract and computes impact;
  it does not bypass input/completeness checks.
- Accepted legacy ADRs without taxonomy/targets retain their documented links
  and remain visible as unmapped records. Report their coverage gap explicitly;
  do not claim exhaustive legacy rule coverage. The seed supplies explicit scope.
- A missing dossier field/alternative says “not recorded”. Over-budget dossiers
  list omissions; the gate still evaluates full records.
- Approval/waiver evidence cannot be verified: activation is refused. The
  preview may still report findings with approval pending.
- Missing or stale generated content fails check mode; render mode is the
  explicit repair operation. Generated content never stores authoritative
  conflict resolution metadata.
- FEAT-778 is already present; any shared adapter must preserve its existing
  runtime behavior and tests while meeting this feature's stricter read contract.

### Required Contract Examples

These are acceptance scenarios for the future implementation, not tests claimed
to pass today:

| Scenario | Required outcome |
|---|---|
| Forbid httpx and require aiohttp on the same file | at most advisory potential-conflict; no automatic contradiction |
| Explicit conflict is the 51st matching record | evaluated and blocking despite dossier limits |
| Legacy documented accepted ADR is unreviewed | eligible unless rejected or no longer effective |
| Two entries share one spec file | distinct stable IDs, independent revisions; rename preserves identity |
| Rule targets a directory, proposal targets a descendant symbol | ancestor rule is collected; caller outside scope receives impact only |
| An unresolved new symbol is named as an existing target | invalid; author must anchor to an existing container in v1 |
| Explicit conflict points to a different domain | checked even without shared targets/about values |
| Supersession cycle, changed predecessor revision or partial scope replacement | invalid, never silently repaired |
| Forged owner string or changed finding participants | waiver rejected; contradiction remains blocking |
| Identical inputs rendered twice | identical bytes and digests |
| New accepted record or changed source bytes/structural edges | previous check becomes stale, even if consulted page hashes were unchanged |
| Record writes succeed but batch publication fails | no partial activation or premature predecessor retirement |
| Index cap, decode error or unsupported schema | incomplete/invalid as defined, never pass |
| Old reader sees extended schema | explicit unsupported-schema failure; no silent data loss |
| Already-approved batch is replayed | recorded baseline used; no self-conflict introduced by ingestion |

---

## Capabilities

### New Capabilities
- `sdd-decision-audit`: complete inventory evaluation, bounded governing
  dossier, structured spec entries, explicit-conflict gate, reproducible
  snapshots and approval-aware publication; versioned seed and taxonomy.

### Modified Capabilities
- FEAT-578 decision plane: versioned model evolution, multi-entry ingestion,
  authoritative domain/target fields and approved lifecycle events. v1 ADR
  records remain readable; compliance proof stays outside this feature.
- `/sdd-spec` and template: three generated/authored sections and shared
  validation across Claude, Codex and Antigravity entry points.
- FEAT-778: existing consumer to assess for shared retrieval/authority
  primitives; its current ADRSource is not a complete gate/dossier adapter.

Conditional v1 delivery (owner scope still open): `/sdd-task` dossier
propagation and CI integration. Neither is claimed shipped or mandatory here.

Later phases: task certificates with independent verification; scheduled
evidence drift to the ledger; human-reviewed historical backfill. These can
reuse the plane but may require their own schema evolution.

## Impact & Integration

Core paths below are relative to `packages/ai-parrot/src/parrot/`.

| Affected component | Required change |
|---|---|
| `knowledge/wiki/decisions/models.py`, `codec.py` | extended versioned records, stable entry IDs, domain/scope and lifecycle metadata; legacy reader compatibility |
| `knowledge/wiki/decisions/parser.py` and new spec adapter | preserve single-ADR parsing; validate structured multi-entry specs and seed metadata |
| `knowledge/wiki/decisions/repository.py`, `ingest.py` | complete snapshot contract, approval-batch publication, explicit retirement and retry semantics |
| `knowledge/wiki/decisions/` new consequence service | evaluator, typed target/scope resolver, findings, canonical digests, dossier rendering |
| `knowledge/wiki/structural/service.py` | reused impact traversal; expose/compose exact resolution and completeness contract as needed |
| `knowledge/wiki/transport.py` and CLI | same typed service, read-only check and explicit render; update shared test inventory `_tool_surface.py` |
| `knowledge/okf/ontology.py` | stable normative vocabulary; ABOUT and CONTRADICTS already exist |
| `scripts/sdd/check_spec_consequences.py` | JSON report and defined exit-code matrix |
| `.claude/commands/sdd-spec.md`, `.agents/skills/sdd-spec/SKILL.md`, `.agent/workflows/sdd-spec.md` | equivalent retrieve/render/check/approval handoff |
| `sdd/templates/spec.md` | three sections plus separate authored waiver/approval references |
| versioned taxonomy, mapping and approval manifests | exact locations/authority adapter frozen in spec before implementation |
| `docs/decisions/*.md` | curated seed with explicit scope and verified approval; existing discovery glob only |
| `experts/knowledge/sources/adr.py`, `resolver.py` | evaluate adapter compatibility against implemented FEAT-778; no automatic unrelated refactor |
| SDD task entry points and CI workflows | conditional scope; if included, use identical snapshot and verdict semantics |

Compatibility is directional: upgraded readers accept legacy records, but old
strict readers cannot consume extended records. Upgrade readers first; migration
and rollback must preserve legacy IDs and approved history. CAS protects each
page, while the new batch protocol controls when a set becomes authoritative.

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

The signatures below describe the existing implementation inspected in the
audit. They are reuse boundaries, not signatures of the proposed extended API.

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
- `DecisionConfig.adr_globs` includes `docs/decisions/**/*.md`: discovery is reused; extended metadata and approval ingestion require new code (models.py:67).
- `DecisionLink.relation` is a closed Literal `explains|supported_by|supersedes` (models.py:144); extended links/fields require versioned compatibility, including explicit conflict and domain semantics.
- `parser.FRONTMATTER_KEYS` keeps only known scalar keys; multiline YAML lists yield a non-flat diagnostic, while unknown inline keys may be ignored. Neither form supplies target semantics today.
- MCP tool specs live in `transport.py` (`wiki_blast_radius` :168, `wiki_decisions_for_symbol` :192, `wiki_decision_why` :197).
- `/sdd-spec` hook points: `.claude/commands/sdd-spec.md` §5 "Scaffold the Spec" (:444) and §6 "Commit the Spec" (:580).
- `sdd/templates/spec.md` has `## 5. Acceptance Criteria` (:230) and `## 6. Codebase Contract` (:243); no Decisions/Consequences sections today.
- Related completed features: FEAT-578 (20/20), FEAT-675 `decisions-cli-fixes` (1/1), FEAT-760 `adr-prefixed-aliases` (8/8). Recheck worktree ownership at implementation start.
- Ledger status verified 2026-10-31: `36a652416160` is closed (FEAT-700 centralized expected tools in `_tool_surface.py`; new tools still update it); `b084239103d7` remains open (document-level `[text](sym:…)` citation extraction from FEAT-578 spec §2/§3 appears unimplemented — the Decisions section should not depend on it).
- FEAT-778 contract to share (`sdd/specs/domain-experts.spec.md`): G6 "ADR as consumer and producer" (:62); `adr` source calls `DecisionService.why()` / `for_symbol()` with `budget_tokens`, accepted only (:145); prompt layer order ends in `accepted ADRs` (:132); `KnowledgeSource.ADR = "adr"` with `filter: {"status": ["accepted"]}` (:209, :217).
- `RelationType.ABOUT = "about"` exists (okf/ontology.py, work-lineage relations) and is the natural record → subsystem-concept edge; `DocTaxonomy.projects` / `KNOWN_PROJECTS` (sdd_meta.py:45, :220) are the coarse subsystem axis every SDD doc already declares.

### Does NOT Exist (Anti-Hallucination)
- ~~`docs/adr/`, `docs/adrs/`, `docs/decisions/`~~ — none of the three default directories exist; the independent local-plane query also returned zero records during the audit.
- ~~`RelationType.CONSTRAINS` / `FORBIDS` / `REQUIRES`~~ — not in `okf/ontology.py`; to be added.
- ~~`ConsequenceService` / `ConsequenceReport`~~ — nothing under `parrot/knowledge/wiki/` by that name.
- ~~`scripts/sdd/check_spec_consequences.py`~~ — does not exist; `check_task_graph.py` is the shape to copy.
- ~~`## Decisions` / `## Consequences` sections in `sdd/templates/spec.md`~~ — not present.
- ~~`targets:` frontmatter key in the ADR parser~~ — not read; only `id/title/status/supersedes`.
- ~~`DecisionRecord.tags`~~ — no tag/component filter on records (FEAT-778 finding F043); retrieval is by symbol link or token overlap only.
- ~~any decision-plane call in the SDD authoring lane~~ — `.claude/commands/sdd-spec.md`, `.claude/commands/sdd-task.md`, `.claude/agents/sdd-coder.md`, `.claude/agents/sdd-worker.md` contain zero references to `wiki_decision_why` / `wiki_decisions_for_symbol` (grep, 2026-10-31).
- `KnowledgeResolver` **exists** under `parrot/experts/knowledge/resolver.py`; FEAT-778 has 22/22 tasks done. What does not exist is the complete, domain-scoped decision adapter required by Option A.
- ~~`parrot.knowledge.ontology.concept_catalog` as the subsystem taxonomy~~ — it exists, but it is FEAT-159's per-tenant *topic* ontology in Postgres (content concepts, `is_a` taxonomy); it is not a taxonomy of code subsystems and should not be reused as one without a separate decision.
- ~~a CI workflow step for `check_task_graph` / `check_e2e_closeout`~~ — grep of `.github/workflows/*.yml` found no reference; those gates run from the commands, not CI. The new gate's CI wiring is therefore new, not a copy.

---

## Parallelism Assessment

- Freeze identity, authority/scope, snapshot and approval-batch contracts before
  splitting implementation. Parser/model/repository changes are coupled; they
  are not a small independent vocabulary bump.
- After those contracts, candidate lanes are ingestion/publication, evaluator
  and surfaces/docs. Templates can be drafted early, but final adapters depend
  on the frozen report and approval protocol. This is design guidance, not
  authorization to spawn implementation agents during this correction.
- FEAT-778 is implemented. Check current file ownership/worktrees when starting
  implementation; do not rely on the brainstorm's older no-collision claim.
- Recommended isolation: one feature worktree with explicit ownership of shared
  model, transport and SDD entry-point files.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesús*: feature on `dev`.
- [x] Who asserts a decision — *Owner: Jesús*: a structured, human-approved section of the spec; no LLM inference on the critical path.
- [x] Granularity — *Owner: Jesús*: two layers; module-level architecture rules in v1, symbol-level task contracts in the certificate phase.
- [x] v1 core — *Owner: Jesús*: consequence preview in `/sdd-spec`; task certificate, drift job and backfill are later phases.
- [x] Checks in v1 — *Owner: Jesús*: contradictions, blast radius, undeclared supersedes, evidence gaps (all four).
- [x] Verdict semantics — *Owner: Jesús*: `## Consequences` written into the spec; only an unresolved contradiction is a blocking finding. Contract clarification: invalid inputs and incomplete audits cannot authorize approval either.
- [x] Target resolution — *Owner: Jesús*: explicit `sym:`/`file:`/`dir:` ids; unresolved target is a spec error.
- [x] Seed — *Owner: Jesús*: curated architecture-rules file(s), approved once, ingested as accepted.

### Proposed technical resolutions from the audit

These resolve implementation ambiguity in Option A without asserting new owner approval.

- Normative vocabulary: `constrains/forbids/requires`; `contradicts` and
  `supersedes` are separate explicit ID links. Only explicit conflicts block;
  an `allows` or partial-exception calculus is deferred.
- Authority: accepted documented, non-rejected, effective records; managed
  spec/seed records must belong to a verified approved batch. No double-review
  requirement on legacy documented ADRs.
- Targets/domain: explicit canonical fields, not `supported_by`. Exact local
  resolution and ancestor scope; future nodes use existing containers in v1.
- Retrieval: full inventory for judgment, token budget only for rendering.
- Versioning: extended schema plus legacy readers/migration; not a silent v1 bump.
- Output: explicit deterministic render and read-only check; frozen approval
  evidence binds the evaluated inputs/results. No mutable generated `resolved-by`.
- Impact defaults: depth 2, calls/extends/implements/uses, tests included,
  inferred edges optional/advisory; coverage and cap failures remain visible.
- FEAT-778: integrate against existing code; no “wait for M5” dependency.

### Owner decisions still required before the implementation spec

- [x] Approval trust adapter: which versioned, attributable approval event is authoritative for specs, seed batches, retirement and waivers? Choose the mechanism and its actor/revision verification before implementing ingestion. — *Owner: Jesús*: the authoritative event is the git commit on `base_branch` that sets the spec `**Status**: approved` (or lands a seed batch), recorded in an append-only versioned manifest `sdd/decisions/approvals.jsonl` (spec path, entry ids, sha256 of the canonical Decisions block, approving commit sha, actor = commit author; signed commits recommended). Ingestion only trusts a block whose digest matches a manifest entry; an edit without a new entry turns its records `unverified`, never authoritative. Retirement and waivers are new manifest entries with the same attribution.
- [x] Confirm the conservative v1 explicit-conflict boundary, or expand scope to a structured proposition language with independently defined semantics. — *Owner: Jesús*: conservative boundary confirmed for v1: only explicit `contradicts` / `supersedes` ID links can block; target/polarity coincidences are rendered as advisory *possible conflicts*. A structured proposition language (subject/predicate/object/polarity) is deferred to a follow-up spec.
- [x] Seed packaging: preferred ADR Markdown with extended metadata, or a separate structured seed source? Both require approval-aware ingestion. — *Owner: Jesús*: ADR Markdown under `docs/decisions/` with the extended metadata (`about`, `targets`), one file per rule, approved as a batch entry in the same approval manifest. No separate seed source in v1.
- [x] Taxonomy/mapping and approval-manifest locations and curator ownership. — *Owner: Jesús*: taxonomy at `sdd/taxonomy/subsystems.yaml` (id, title, description, parent, mapped `projects`), approval manifest at `sdd/decisions/approvals.jsonl`; both curated by the repo owner through ordinary PRs to `base_branch`. Ingestion projects each subsystem as a `concept:<id>` page so `about` links resolve.
- [x] CI in v1 or a later delivery? If included, reconstruct the same snapshot from versioned inputs and use read-only check; no dependence on local SQLite. — *Owner: Jesús*: later delivery. v1 runs the gate from `/sdd-spec` only and ships the read-only check script; the CI job (snapshot reconstructed from versioned inputs, no local SQLite dependence) is a follow-up spec.
- [x] `/sdd-task` dossier propagation in v1 or later? If included, update all supported task entry points using the same authority/scope contract. — *Owner: Jesús*: later; v1 is `/sdd-spec` only. `/sdd-task` propagation ships with the task-certificate phase under the same authority/scope contract.
- [x] Is generation of Governing Decisions mandatory for authoring approval, beyond the mandatory complete evaluation? It cannot prove the author read it. — *Owner: Jesús*: the *complete evaluation* is mandatory for approval (no truncation, no incomplete inventory); the rendered `## Governing Decisions` section is always produced but makes no claim that the author read it. Approval records the evaluation digest, not a reading attestation.
- [x] Extend the preview to `/sdd-brief` in v1, or retain `/sdd-spec` only? — *Owner: Jesús*: `/sdd-spec` only in v1; `/sdd-brief` is a follow-up once the hotfix lane has an approval event to bind to.
- [x] Optional external verifier spike after the plane has content, or defer until task certificates? No external proof guarantee is assumed by Option A. — *Owner: Jesús*: defer until task certificates exist. Option A assumes no external proof guarantee; Option C stays an exploration note.

The owner answer recorded on 2026-10-31 remains: decisions should feed authoring
as curated knowledge as well as gate proposals, using domain and structural axes.
