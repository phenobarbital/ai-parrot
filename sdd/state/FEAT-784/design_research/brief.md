<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
**Option A** remains recommended: it extends the canonical decision plane and
keeps consumer, producer and verifier on one authority model. Its advantage is
lower integration duplication, not exclusive access to a consumer/producer
design. B/C could also consume projections of those records.

The corrected v1 provides explicit-conflict checking plus advisory structural
signals. It does not prove conservativity, semantic consistency or implementation
compliance. Certificates, drift jobs and backfill remain later phases. A rich
dossier, multi-entry ingestion and approval snapshots are new contracts, so
the earlier “one service and one parser extension” estimate is withdrawn.


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

### Verified code anchors (paths only — open them yourself)
.claude/agents/sdd-coder.md
.claude/agents/sdd-worker.md
.claude/commands/sdd-spec.md
.claude/commands/sdd-task.md
docs/adr/
docs/adrs/
docs/decisions/
packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/review.py
packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/structural/operations.py
packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
packages/navrules/src/navrules/policies.py
packages/navrules/src/navrules/ruleset.py
scripts/sdd/check_spec_consequences.py
scripts/sdd/check_task_graph.py
sdd/specs/domain-experts.spec.md
sdd/templates/spec.md

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
