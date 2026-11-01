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

# Feature Specification: SDD Decision Audit — governing dossier and consequence gate over the decision plane

**Feature ID**: FEAT-784
**Date**: 2026-10-31
**Author**: Jesús Lara (with Claude Fable 5.1)
**Status**: approved
**Target version**: next minor

Input: `sdd/proposals/sdd-decision-audit.brainstorm.md` (Option A, accepted
2026-10-31) and its adversarial audit `sdd/proposals/sdd-decision-audit.findings.md`
(F01–F10, all folded into the accepted brainstorm). Every brainstorm answer is
carried forward verbatim in §8; this spec adds the frozen contracts (identity,
authority, scope, snapshot, approval batch, exit matrix) that the audit required
before implementation.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The SDD flow reviews *code* (`/sdd-codereview`, `sdd-secondopinion`, the GitHub
reviewer) but has no approval-time gate over *decisions*. An audit asks: which
decision was taken, under which constraints already in force, does it contradict
a decision accepted earlier, and is that chain re-verifiable later. That chain
lives today in prose (`CLAUDE.md`, `.agent/CONTEXT.md`, Completion Notes, review
markdown); some rules are enforced mechanically (`TID251`, the FEAT-524
memory/history ownership regression tests), but nothing joins them into one
decision-consistency contract.

FEAT-578 built a complete ADR decision plane (`parrot.knowledge.wiki.decisions`:
`DecisionRecord`, hashed `EvidenceRef`, freshness `current|stale|missing|unverified`,
attributed review, CAS page writes) and declared automatic compliance/drift
verdicts a non-goal. The plane is empty in this repository (none of the three
`adr_globs` directories exist; a local `wiki_decision_why` with history returned
no records), and nothing in the SDD authoring lane (`/sdd-spec`, `/sdd-task`,
`sdd-coder`, `sdd-worker`) ever reads it. FEAT-778 shipped a runtime consumer
(`KnowledgeResolver` + `ADRSource`, lexical `why()` under a token budget) for
expert agents; its budgeted output is not a complete gate input and carries no
domain axis. Retrieval today is by symbol link or token overlap: "what is decided
about conversation memory?" has no explicit domain filter and no coverage
guarantee.

The plane therefore has to serve two modes over the same records: curated
**input** while a spec is written (consumer), and **verifier** of what the spec
proposes (gate). The gate alone only detects collisions on shared symbols; the
consumer alone never enforces anything.

### Goals

- G1 — **Governing dossier.** Before Section 2 of a spec is drafted, `/sdd-spec`
  renders `## Governing Decisions`: every eligible decision governing the spec's
  declared subsystems and existing targets, with rationale, consequences,
  supersession and freshness, from the complete inventory, budgeted only for
  presentation (omissions enumerable).
- G2 — **Structured producer.** Specs declare decisions in a versioned YAML
  block (`## Decisions`): stable `adr:spec:<document_id>#<entry_id>` identity,
  normative relation, `about` subsystems, explicit typed targets, explicit
  `contradicts` / `supersedes` references.
- G3 — **Deterministic consequence evaluation.** `## Consequences` is generated
  from a consistent snapshot: blocking `contradiction` only on an explicit
  unresolved `contradicts` link; advisory `potential-conflict`,
  `possible-supersession`, `blast-radius`, `evidence-gap`. Zero LLM calls.
- G4 — **Verifiable approval and publication.** Decisions become authoritative
  only through an approval batch bound to a git commit on `base_branch` and
  recorded in `sdd/decisions/approvals.jsonl`; publication is all-or-nothing per
  batch, retries idempotent, retirement explicit.
- G5 — **Reproducible gate.** `scripts/sdd/check_spec_consequences.py` exposes
  the exit matrix `pass/0 · skipped/0 · conflict/1 · invalid/2 · incomplete/3`;
  render and check modes are byte-stable for identical inputs; a stale
  persisted report fails check mode.
- G8 — **Portability.** The SDD flow runs in repositories that will never
  author ADRs, build the wiki plane or curate a taxonomy. A repository with no
  decision-audit configuration gets `skipped` (exit 0) with a one-line note;
  `/sdd-task` never refuses a spec for lacking a report and only warns when an
  existing report is contrary.
- G6 — **Seed and taxonomy.** A curated subsystem taxonomy
  (`sdd/taxonomy/subsystems.yaml`) and a seeded set of architecture rules
  (`docs/decisions/*.md`, extended metadata, approved as one batch) make the
  preview useful from day one.
- G7 — **Compatibility.** Legacy schema-1 ADR records keep their ids and stay
  readable; FEAT-778's `ADRSource` keeps its runtime behaviour and tests.

Confirmed brainstorm answers, carried forward verbatim (owner Jesús): flow
`feature` on `dev`; decisions asserted only from a structured, human-approved
spec section (no LLM inference on the critical path); two layers (module-level
rules in v1, symbol-level task contracts later); v1 core is the consequence
preview in `/sdd-spec`; all four checks in v1; only an unresolved contradiction
blocks (invalid/incomplete also refuse approval); explicit `sym:`/`file:`/`dir:`
targets; curated seed approved once.

### Non-Goals (explicitly out of scope)

- Proving that *code* complies with a decision. v1 checks consistency of
  declared decisions; a source hash proves freshness, not compliance.
- Semantic contradiction detection without an explicit link; a structured
  proposition language (subject/predicate/object/polarity) is a follow-up.
- `allows` / partial-exception calculus; partial supersession; competing
  successors (all `invalid` in v1).
- CI job for the gate; `/sdd-task` dossier *propagation* (the advisory check
  in `/sdd-task` is in scope, Q3); `/sdd-brief` preview (deferred, §8).
- Making decision audit a prerequisite of the SDD flow in other repositories:
  an unconfigured repository is `skipped`, never blocked (G8).
- Task certificates, scheduled evidence-drift job, historical backfill via
  `generation.py` (later phases).
- External verifier (open-ontologies / RDF projection) — brainstorm Option C,
  deferred until certificates exist. Ontology-first `navrules` engine
  (Option B) and LLM-judge (Option D) rejected — see the brainstorm.
- Refactoring FEAT-778's `KnowledgeResolver` / `ADRSource`; changing
  `clients/base.py`; any new HTTP stack.
- Document-level `[text](sym:…)` citation extraction (ledger `b084239103d7`,
  still open) — the Decisions block never depends on it.

---

## 2. Architectural Design

### Overview

One authority model, three surfaces. The existing `DecisionRepository` /
`DecisionRecord` plane is extended to **schema version 2** with explicit
domain (`about`), typed `targets`, a normative relation, explicit
`contradicts` / `supersedes` references, lifecycle and approval-batch metadata.
A spec's `## Decisions` YAML block is parsed by a dedicated multi-entry parser
(not the single-record `parse_adr()`), and each entry gets the immutable id
`adr:spec:<document_id>#<entry_id>`.

Reads go through a new **inventory snapshot**: the complete bounded repository
inventory (`DecisionRepository.inventory()`, overflow ⇒ `incomplete`), the
taxonomy, the approvals manifest and the structural index, hashed into a
**snapshot manifest**. Eligibility is one predicate: `origin == documented`,
`source_status == accepted`, `review_status != rejected`, effective under the
validated supersession graph, and — for spec/seed records — member of a
verified approval batch. Filtering precedes ranking and packing; the token
budget touches presentation only.

A **typed target resolver** validates `sym:` / `file:` / `dir:` ids against
the structural plane and confined repository paths (name lookup only suggests);
scope is symbol → symbol, file → file and its symbols, dir → path-segment
descendants, with ancestor scope consulted when collecting governing records.
Impact is `StructuralService.blast_radius()` (depth 2, `calls/extends/
implements/uses`, tests included, inferred edges reported separately) and never
propagates applicability.

The **`ConsequenceService`** evaluates a spec into a `ConsequenceReport`:
status `pass | conflict | invalid | incomplete`, stable findings keyed by
rule/version, participants and revisions, an **input digest** (canonical
authored content, excluding generated sections and the status marker, plus the
snapshot manifest) and an **evaluation digest** (input digest plus canonical
findings). It also renders the **governing dossier**. A separate renderer writes
`## Governing Decisions` / `## Consequences` deterministically (render mode) or
recomputes and compares them (check mode, read-only).

**Approval** is bound to the git commit on `base_branch` that sets the spec
`**Status**: approved` (or lands a seed batch): an append-only
`sdd/decisions/approvals.jsonl` entry records spec path, `document_id`, entry
ids and revisions, the canonical block sha256, the approving commit sha and the
actor (commit author). The `GitCommitApprovalAdapter` verifies the commit exists,
is an ancestor of `origin/<base_branch>`, and the spec blob at that commit
re-hashes to the recorded digest. **Publication** rechecks snapshot and approval,
then writes the batch's records through the existing per-record CAS with a
batch marker that keeps a half-written batch invisible to the eligibility
predicate; retirement is an explicit manifest event; supersession becomes
effective only with the approved batch.

Surfaces: `wikitoolkit spec governing|consequences render|consequences check|
decisions publish`, MCP `wiki_spec_consequences`, and
`scripts/sdd/check_spec_consequences.py` with the exit matrix; `/sdd-spec`
(Claude command, Antigravity workflow, Codex skill) retrieves before §5 and
checks before §6; `/sdd-task` runs check mode in **advisory** form.

**Portability principle (owner, 2026-10-31).** Decision audit is
*configured* in a repository when `sdd/taxonomy/subsystems.yaml` or
`sdd/decisions/approvals.jsonl` exists. When neither exists **and** the spec
has no `## Decisions` block, every surface returns status `skipped` (exit 0),
renders a single line ("decision audit not configured in this repository")
instead of the two sections, and `/sdd-spec` proceeds normally. A spec that
declares decisions in an unconfigured repository is `invalid` (it asked for an
audit nobody can run). `/sdd-task` never refuses decomposition: with no report
it stays silent; with a report that is `conflict`, `invalid`, `incomplete` or
stale it prints a warning and continues. Only `/sdd-spec`'s `approved`
transition is refused, and only on `conflict` / `invalid` / `incomplete`.

### Component Diagram

```
sdd/specs/<slug>.spec.md ──► SpecDecisionsParser (M2) ──► entries + waivers
        │                                                   │
        │  projects/tags ──► Taxonomy (M3) ─────────────────┤
        │  Codebase Contract ids ──► TargetResolver (M4) ───┤
        ▼                                                   ▼
 sdd/decisions/approvals.jsonl ──► ApprovalAdapter (M3) ──► InventorySnapshot (M5)
                                                            │   ▲
 DecisionRepository.inventory() ────────────────────────────┘   │ StructuralService.blast_radius()
                                                                │
                                   ConsequenceService (M6) ─────┘
                                     │            │
                 GoverningDossier ◄──┘            └──► ConsequenceReport
                        │                                   │
                SectionRenderer (M7) ── render / check ─────┘
                        │
   ┌────────────────────┼─────────────────────────┐
   ▼                    ▼                         ▼
wikitoolkit CLI    MCP wiki_spec_consequences   scripts/sdd/check_spec_consequences.py   (M9)
                                                           ▲
/sdd-spec (claude · antigravity · codex) ──────────────────┘ (M10)

approved batch ──► BatchPublisher (M8) ──► DecisionRepository.save (CAS) ──► project_links()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.wiki.decisions.models` (`DecisionRecord`, `DecisionLink`, `_Strict`) | extends | schema 2 fields; schema 1 still parses; `extra="forbid"` kept |
| `parrot.knowledge.wiki.decisions.codec` | extends | `spec_decision_id()`, envelope v2 marker, `decision_from_page` fails explicitly on unsupported schema |
| `parrot.knowledge.wiki.decisions.parser.parse_adr` | unchanged | legacy single-ADR parsing preserved byte-for-byte; seed metadata read by M2 |
| `parrot.knowledge.wiki.decisions.repository.DecisionRepository` | uses / extends | `inventory()` is the only read root; `save()` CAS is the only write primitive |
| `parrot.knowledge.wiki.decisions.ingest` (`refresh_decisions`, `project_links`) | extends | approved specs join discovery; `project_links` projects `about` / normative edges as rebuildable cache |
| `parrot.knowledge.wiki.decisions.evidence.verify_freshness` | uses | evidence-gap finding; freshness only |
| `parrot.knowledge.wiki.decisions.service.DecisionService` | uses | `for_symbol()` / `why()` stay the budgeted agent surface; never a gate input |
| `parrot.knowledge.wiki.structural.StructuralService` | uses | `blast_radius()` for impact; `lookup()` for suggestions only |
| `parrot.knowledge.wiki.store.BaseWikiStore` | uses | `get_page` / `list_pages` / `compare_and_swap_page` |
| `parrot.knowledge.wiki.transport` + `tests/knowledge/wiki/_tool_surface.py` | extends | new `wiki_spec_consequences` tool, expected-tool inventory updated |
| `parrot.knowledge.wiki.cli` | extends | new `spec` command group next to `adr` |
| `parrot.knowledge.okf.ontology.RelationType` | extends | `CONSTRAINS`, `FORBIDS`, `REQUIRES` (additive; `ABOUT`, `CONTRADICTS`, `SUPERSEDES` exist) |
| `parrot.knowledge.wiki.ledger.sdd_meta` (`DocTaxonomy`, `KNOWN_PROJECTS`) | uses | coarse project axis; taxonomy maps subsystems → projects |
| `parrot.experts.knowledge.sources.adr.ADRSource` (FEAT-778) | compatibility | unchanged runtime; equivalence test against the shared eligibility predicate |
| `scripts/sdd/check_task_graph.py` | pattern | `Finding` / report / `main()` shape copied for the new gate script |
| `.claude/commands/sdd-spec.md`, `.agent/workflows/sdd-spec.md`, `.agents/skills/sdd-spec/SKILL.md`, `sdd/templates/spec.md` | modifies | retrieve → §4/§5, check → §6; three new sections |

### Data Models

```python
# parrot/knowledge/wiki/decisions/models.py  (schema 2 — additive; schema 1 records keep parsing)
class DecisionRef(_Strict):
    decision_id: str                 # canonical id (adr:doc:…, adr:spec:<doc>#<entry>)
    revision: int                    # ge=1 — exact revision referenced

class DecisionTarget(_Strict):
    target_id: str                   # sym:<rel>#<qualname> | file:<rel> | dir:<rel>
    kind: Literal["symbol", "file", "dir"]

class DecisionRecord(_Strict):
    schema_version: Literal[1, 2] = 1
    # … all schema-1 fields unchanged (models.py:172-194) …
    normative: Literal["constrains", "forbids", "requires"] | None = None
    about: list[str] = []            # taxonomy subsystem ids
    targets: list[DecisionTarget] = []
    contradicts: list[DecisionRef] = []
    supersedes_refs: list[DecisionRef] = []     # lifecycle; full replacement in v1
    document_id: str | None = None   # spec/seed document id
    entry_id: str | None = None
    batch_id: str | None = None      # approval batch that made it authoritative
    lifecycle: Literal["active", "retired"] = "active"
    rationale: str = ""              # authored; "" renders as "not recorded"
    rejected_alternatives: list[str] = []

# parrot/knowledge/wiki/decisions/spec_entries.py
class SpecDecisionEntry(_Strict):
    id: str; statement: str; relation: Literal["constrains", "forbids", "requires"]
    about: list[str]; targets: list[str]; revision: int = 1; previous_revision: int | None = None
    contradicts: list[DecisionRef] = []; supersedes: list[DecisionRef] = []
    rationale: str = ""; rejected_alternatives: list[str] = []
class SpecDecisionsBlock(_Strict):
    schema_version: Literal[1]; document_id: str; entries: list[SpecDecisionEntry]
class ConflictWaiver(_Strict):
    finding_fingerprint: str; participants: list[DecisionRef]; actor: str; reason: str; approval_ref: str

# parrot/knowledge/wiki/decisions/approvals.py
class ApprovalEntry(_Strict):
    kind: Literal["spec", "seed", "retirement", "waiver"]; batch_id: str; spec_path: str
    document_id: str; entries: list[DecisionRef]; block_sha256: str; commit: str; actor: str; recorded_at: str

# parrot/knowledge/wiki/decisions/consequences.py
class Finding(_Strict):
    kind: Literal["contradiction", "potential-conflict", "possible-supersession", "blast-radius", "evidence-gap"]
    rule_version: int; fingerprint: str; participants: list[DecisionRef]; scope: list[str]
    blocking: bool; waived_by: str | None = None; message: str
class ConsequenceReport(_Strict):
    status: Literal["pass", "skipped", "conflict", "invalid", "incomplete"]; exit_code: int   # skipped = not configured
    input_digest: str; evaluation_digest: str; snapshot: SnapshotManifest
    findings: list[Finding]; diagnostics: list[DecisionDiagnostic]; coverage: CoverageSummary
```

### New Public Interfaces

```python
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService
report  = await ConsequenceService(store, root, config, structural).evaluate(Path("sdd/specs/x.spec.md"))
dossier = await ConsequenceService(...).governing(Path("sdd/specs/x.spec.md"), budget_tokens=3000)

from parrot.knowledge.wiki.decisions.publish import BatchPublisher
result  = await BatchPublisher(store, root, config, approvals).publish(batch_id)

# CLI
wikitoolkit spec governing <spec>              # render-only dossier to stdout
wikitoolkit spec consequences render <spec>    # writes ## Governing Decisions + ## Consequences
wikitoolkit spec consequences check <spec>     # read-only; exit matrix
wikitoolkit decisions publish --batch <id>     # approved batch → plane
python -m scripts.sdd.check_spec_consequences sdd/specs/<slug>.spec.md [--json] [--render]
# MCP
wiki_spec_consequences(spec_path, mode="check"|"governing", budget_tokens)
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Schema 2 models + codec | yes | fields, literals, `spec_decision_id`, envelope marker v2, explicit `ADR_UNSUPPORTED_SCHEMA` | — |
| M2: Spec Decisions parser | yes | YAML block grammar, id charset, validation error codes fixed below | — |
| M3: Taxonomy + approvals adapter | yes | file formats, `GitCommitApprovalAdapter` checks fixed | — |
| M4: Target resolver + scope | no (owner-confirmed 2026-10-31) | scope-completeness contract against the scan inventory needs a design pass on `repo_scan` coverage | coverage semantics |
| M5: Inventory snapshot + eligibility | yes | predicate, supersession validation rules, manifest hash inputs fixed | — |
| M6: Consequence evaluator | no (owner-confirmed 2026-10-31) | finding fingerprint canonicalization and baseline/replay rules need the thinking model | digest/baseline semantics |
| M7: Section renderer + check | yes | section markers, byte-stable rendering, check comparison fixed | — |
| M8: Batch publisher + ingest extension | no (owner-confirmed 2026-10-31) | batch-visibility marker on top of per-record CAS is a concurrency design | partial-batch invisibility |
| M9: Surfaces (CLI, MCP, gate script) | yes | names, exit matrix, `_tool_surface.py` update fixed | — |
| M10: SDD entry points, template, taxonomy, seed, docs | yes | section names and step placement fixed; seed content transcribed from `CLAUDE.md` / `CONTEXT.md` | — |
| M11: FEAT-778 compatibility tests | yes | equivalence test on fixtures; no runtime change | — |

### Module 1: Schema 2 models and codec
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`, `codec.py`, `__init__.py`
- **Responsibility**: additive schema-2 fields on `DecisionRecord`; `DecisionRef`, `DecisionTarget`; `DecisionLink.relation` gains `"contradicts"` and `"about"` for the projected cache only; `spec_decision_id()`; envelope marker `<!-- parrot-adr:v2 -->` written for schema-2 records while `v1` is still read; `decision_from_page` raises `DecisionError(ADR_UNSUPPORTED_SCHEMA)` on a schema it does not know (old readers fail explicitly).
- **Depends on**: existing `_Strict` (models.py:57), `DecisionRecord` (models.py:172), `documented_decision_id` (codec.py:104).
- **Interface Skeleton**:
  ```python
  # decisions/models.py  (modifies models.py:144, :172-194)
  class DecisionRef(_Strict):           # _Strict verified: models.py:57
      """Exact (id, revision) reference to another decision."""
      decision_id: str; revision: int
  class DecisionTarget(_Strict):
      """Typed structural target; kind derived from the id prefix at validation."""
      target_id: str; kind: Literal["symbol", "file", "dir"]
  class DecisionRecord(_Strict):        # verified: models.py:172
      schema_version: Literal[1, 2] = 1
      normative: Literal["constrains", "forbids", "requires"] | None = None
      about: list[str]; targets: list[DecisionTarget]; contradicts: list[DecisionRef]
      supersedes_refs: list[DecisionRef]; document_id: str | None; entry_id: str | None
      batch_id: str | None; lifecycle: Literal["active", "retired"] = "active"
      rationale: str = ""; rejected_alternatives: list[str]
      # invariant: schema_version == 1 ⇒ every schema-2 field is at its default (validator)
  # decisions/codec.py  (modifies codec.py:34, :104, :191)
  ENVELOPE_MARKER_V2 = "<!-- parrot-adr:v2 -->"
  def spec_decision_id(document_id: str, entry_id: str) -> str:
      """``adr:spec:<document_id>#<entry_id>``; both parts ``[a-z0-9_-]+``; raises DecisionError(ADR_INVALID_ID)."""
  def decision_from_page(page: dict[str, Any]) -> DecisionRecord:   # verified: codec.py:191
      """Accept v1 and v2 envelopes; raise DecisionError(ADR_UNSUPPORTED_SCHEMA) otherwise."""
  ```

### Module 2: Spec Decisions block parser
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_entries.py` (new)
- **Responsibility**: locate `## Decisions` and optional `## Decision Waivers` in a spec, parse their fenced ```yaml blocks with `yaml.safe_load`, validate `SpecDecisionsBlock` / `list[ConflictWaiver]`; canonical bytes of the block for digests; same grammar reused for a seed ADR's `## Decision Metadata` block (single entry). Error codes: `SPEC_BLOCK_MISSING`, `SPEC_BLOCK_INVALID_YAML`, `SPEC_DUPLICATE_ENTRY_ID`, `SPEC_INVALID_ID`, `SPEC_UNKNOWN_FIELD`, `SPEC_DANGLING_REF`, `SPEC_EMPTY_ABOUT`, `SPEC_EMPTY_TARGETS`.
- **Depends on**: M1 models.
- **Interface Skeleton**:
  ```python
  # decisions/spec_entries.py  (new)
  DECISIONS_HEADING = "## Decisions"; WAIVERS_HEADING = "## Decision Waivers"; SEED_HEADING = "## Decision Metadata"
  def extract_block(text: str, heading: str) -> tuple[str | None, int, int]:
      """Return (yaml_source, start_line, end_line) of the first fenced yaml block under ``heading``."""
  def canonical_block_bytes(block: SpecDecisionsBlock) -> bytes:
      """Deterministic JSON (sorted keys, UTF-8, no volatile fields) used by approvals and digests."""
  def parse_spec_decisions(text: str, *, source_path: str) -> tuple[SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic]]:
      """Parse and validate; never raises — all failures are diagnostics with stable codes."""
  def entries_to_records(block: SpecDecisionsBlock, *, source_path: str, batch_id: str | None) -> list[DecisionRecord]:
      """Map entries to schema-2 records (origin='documented', source_status='accepted', lifecycle='active')."""
  ```

### Module 3: Subsystem taxonomy and approval adapter
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/taxonomy.py`, `approvals.py` (new)
- **Responsibility**: load/validate `sdd/taxonomy/subsystems.yaml` (`id`, `title`, `description`, `parent`, `projects`), expose `Taxonomy.ids()`, `closest(id)` for suggestions, `project_pages()` → `concept:<id>` `WikiPageRecord`s; load `sdd/decisions/approvals.jsonl` (append-only), and the `ApprovalAdapter` protocol with `GitCommitApprovalAdapter.verify(entry)` (commit exists, ancestor of `origin/<base_branch>` or local base when offline with a diagnostic, spec blob at that commit re-hashes to `block_sha256`, actor == commit author).
- **Depends on**: M1, M2 (`canonical_block_bytes`), `KNOWN_PROJECTS` (sdd_meta.py:45).
- **Interface Skeleton**:
  ```python
  # decisions/taxonomy.py  (new)
  class Subsystem(_Strict): id: str; title: str; description: str = ""; parent: str | None = None; projects: list[str]
  class Taxonomy:
      @classmethod
      def load(cls, path: Path) -> "Taxonomy": """Raise DecisionError(TAXONOMY_INVALID) on unknown parent/project or duplicate id."""
      def ids(self) -> frozenset[str]
      def closest(self, raw: str, limit: int = 3) -> list[str]: """Suggestions only; never auto-corrects."""
      def map_projects(self, projects: list[str], tags: list[str]) -> list[str]: """Versioned mapping projects/tags → subsystem ids; unknown tags are reported, not mapped."""
      def project_pages(self) -> list[WikiPageRecord]: """concept:<id> pages for ABOUT edges."""
      def digest(self) -> str
  # decisions/approvals.py  (new)
  class ApprovalManifest:
      @classmethod
      def load(cls, path: Path) -> "ApprovalManifest": """JSONL, append-only; malformed line ⇒ DecisionError(APPROVAL_MANIFEST_INVALID)."""
      def for_document(self, document_id: str) -> list[ApprovalEntry]
      def digest(self) -> str
  class ApprovalAdapter(Protocol):
      async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]: ...
  class GitCommitApprovalAdapter:
      def __init__(self, root: Path, base_branch: str) -> None
      async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]:
          """commit exists · ancestor of base · blob at commit hashes to block_sha256 · actor matches author."""
  ```

### Module 4: Typed target resolver and scope
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/scope.py` (new)
- **Responsibility**: validate exact `sym:` / `file:` / `dir:` ids: existence in the structural plane (`store.get_page`) and confined repository path (`_resolve_confined`, evidence.py:205 pattern); directory expansion to descendants by path segments over the structural inventory with a completeness check against the declared scan coverage; ancestor chain for a target (`dir:` ancestors + `file:`); name lookup via `StructuralService.lookup()` only to populate suggestions.
- **Depends on**: `StructuralService` (structural/service.py:130), `BaseWikiStore.get_page` (store.py:765).
- **Interface Skeleton**:
  ```python
  # decisions/scope.py  (new)
  class ResolvedTarget(_Strict):
      target: DecisionTarget; page_id: str | None; ancestors: list[str]; descendants: list[str]
      state: Literal["resolved", "missing", "unsupported", "stale", "incomplete"]   # S5: never infer from an empty outline
  class TargetResolver:
      def __init__(self, store: BaseWikiStore, root: Path, structural: StructuralService) -> None   # verified: structural/service.py:130
      async def resolve(self, target_id: str) -> tuple[ResolvedTarget | None, list[DecisionDiagnostic]]:
          """Exact id only; missing ⇒ TARGET_UNRESOLVED (+ suggestions); foreign/outside root ⇒ TARGET_FOREIGN."""
      async def ancestors_of(self, page_id: str) -> list[str]: """file: then every dir: ancestor up to the repo root."""
      async def expand_dir(self, dir_id: str) -> tuple[list[str], bool]: """(descendant page ids, complete) — complete=False when scan coverage is partial."""
  ```

### Module 5: Inventory snapshot and eligibility
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` (new)
- **Responsibility**: single read root over `DecisionRepository.inventory()` (repository.py:63; overflow/decode ⇒ `incomplete`), taxonomy, approvals manifest and structural index revision; the eligibility predicate; supersession-graph validation (existence, acyclicity, identical canonical target sets, no competing effective successors, exact predecessor revision) producing `effective_heads`; `SnapshotManifest` (inventory membership + content hashes, taxonomy digest, approvals digest, structural revision, rules version, config digest) and a revision recheck so mixed reads become `incomplete`.
- **Depends on**: M1, M3, `DecisionRepository` (repository.py:26).
- **Interface Skeleton**:
  ```python
  # decisions/inventory.py  (new)
  RULES_VERSION = 1
  class SnapshotManifest(_Strict): inventory: dict[str, str]; taxonomy_digest: str; approvals_digest: str; structural_revision: str; rules_version: int; config_digest: str
  def is_eligible(record: DecisionRecord, *, approved_batches: frozenset[str]) -> bool:
      """documented ∧ source_status=='accepted' ∧ review_status!='rejected' ∧ lifecycle=='active' ∧ (legacy adr:doc ∨ batch_id ∈ approved_batches)."""
  class InventorySnapshot:
      @classmethod
      async def take(cls, repo: DecisionRepository, taxonomy: Taxonomy, approvals: ApprovalManifest, adapter: ApprovalAdapter, structural_revision: str) -> "InventorySnapshot":
          """Two-phase read with revision recheck; raises DecisionError(ADR_INVENTORY_LIMIT|SNAPSHOT_UNSTABLE) ⇒ incomplete."""
      eligible: list[DecisionRecord]; manifest: SnapshotManifest; diagnostics: list[DecisionDiagnostic]
      def effective_head(self, decision_id: str) -> DecisionRef | None
      def governing(self, about: set[str], scope_ids: set[str]) -> list[DecisionRecord]: """union by canonical id; explicit cross-domain refs included."""
  ```

### Module 6: Consequence evaluator
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py` (new)
- **Responsibility**: `ConsequenceService.evaluate()` — parse (M2) → validate taxonomy/targets/links/waivers (M3/M4) → snapshot (M5) → baseline selection (initial / revision / replay with recorded pre-publication baseline) → impact (`StructuralService.blast_radius`, depth 2, `calls/extends/implements/uses`, tests included, inferred separate) → judge → digests → report; `governing()` — the budgeted dossier from the same snapshot (full records loaded; omissions enumerable). Finding fingerprint = sha256 of `(kind, rule_version, sorted participants (id, revision), sorted scope)`.
- **Depends on**: M2, M3, M4, M5, `StructuralService.blast_radius` (structural/service.py:360), `verify_freshness` (evidence.py:226).
- **Structural snapshot (S6)**: the evaluator constructs its `StructuralService` with `read_repair=False` (structural/service.py:138) so a gate run never rescans or mutates the plane; `BlastRadiusOutput.truncated`, the `_BLAST_RADIUS_NODE_CAP = 500` cap (structural/service.py:42) or dangling nodes in the required traversal make `coverage.impact_complete = False` and the status `incomplete`; the structural revision recorded in the snapshot manifest is the plane's content hash at evaluation time.
- **Interface Skeleton**:
  ```python
  # decisions/consequences.py  (new)
  class CoverageSummary(_Strict): subsystems: list[str]; unmapped_tags: list[str]; targets_resolved: int; targets_total: int; impact_complete: bool; inventory_complete: bool; omitted_ids: list[str]
  class GoverningDossier(_Strict): entries: list[GoverningEntry]; omitted_ids: list[str]; searched_subsystems: list[str]; empty_plane: bool; truncated: bool; snapshot: SnapshotManifest
  class ConsequenceService:
      def __init__(self, store: BaseWikiStore, root: Path, config: DecisionConfig, structural: StructuralService, *, taxonomy_path: Path, approvals_path: Path, adapter: ApprovalAdapter) -> None
      async def evaluate(self, spec_path: Path, *, mode: Literal["preview", "replay"] = "preview") -> ConsequenceReport:
          """Never raises for spec/content faults: status invalid|incomplete carries diagnostics. Precedence invalid > incomplete > conflict > pass; `skipped` only when the repo is unconfigured and no block is declared."""
      async def governing(self, spec_path: Path, *, budget_tokens: int = 3000) -> GoverningDossier:
          """Full eligible set collected first; budget applies to rendering only."""
  def input_digest(canonical_spec: bytes, block: bytes, waivers: bytes, config_digest: str, manifest: SnapshotManifest) -> str
  def evaluation_digest(input_digest: str, findings: list[Finding]) -> str
  def canonicalize_spec(text: str) -> bytes:
      """Strip generated sections (## Governing Decisions, ## Consequences) and the **Status** marker line; normalize newlines/encoding."""
  ```

### Module 7: Section renderer and check
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences_render.py` (new)
- **Responsibility**: deterministic Markdown for `## Governing Decisions` and `## Consequences` (stable ordering, no timestamps, header line carries `input_digest` / `evaluation_digest` / `rules_version`; JSON tail retains the full report; shortened Markdown never drops a finding); `render(spec_path, report, dossier)` splices sections idempotently (byte-identical on unchanged inputs); `check(spec_path)` recomputes and compares both digests and content, read-only; reports `consequences-stale` / `consequences-missing`.
- **Depends on**: M6.
- **Interface Skeleton**:
  ```python
  # decisions/consequences_render.py  (new)
  GOVERNING_HEADING = "## Governing Decisions"; CONSEQUENCES_HEADING = "## Consequences"
  def render_governing(dossier: GoverningDossier, *, budget_tokens: int) -> str
  def render_consequences(report: ConsequenceReport) -> str
  def splice_sections(text: str, governing_md: str, consequences_md: str) -> str: """Replace or insert both sections at fixed positions (before §2, before §8)."""
  class CheckResult(_Strict): status: Literal["current", "stale", "missing"]; report: ConsequenceReport
  async def render_spec(service: ConsequenceService, spec_path: Path, *, budget_tokens: int) -> ConsequenceReport
  async def check_spec(service: ConsequenceService, spec_path: Path) -> CheckResult: """Never writes."""
  ```

### Module 8: Batch publisher and ingest extension
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/publish.py` (new); `ingest.py` (modify)
- **Responsibility**: `BatchPublisher.publish(batch_id)` — reload snapshot, verify approval via adapter, re-evaluate with the recorded baseline (must be `pass`), write records with `DecisionRepository.save()` carrying `batch_id` and a `pending` marker page `adr:batch:<id>` that `is_eligible` consults (half-written batches invisible), flip the marker to `published` last, idempotent retries, explicit retirement entries set `lifecycle='retired'` on predecessors only after the successor batch is published; `discover_adr_sources` extended with approved specs listed in the manifest; `project_links` projects `about` (→ `concept:` pages) and normative edges (→ target pages) as rebuildable cache.
- **Depends on**: M1, M2, M3, M5, M6; `refresh_decisions` (ingest.py:252), `project_links` (ingest.py:380), `DecisionRepository.save` (repository.py:96).
- **Interface Skeleton**:
  ```python
  # decisions/publish.py  (new)
  class PublishResult(_Strict): batch_id: str; written: int; retired: int; skipped: int; status: Literal["published", "already-published", "refused"]; diagnostics: list[DecisionDiagnostic]
  class BatchPublisher:
      def __init__(self, store: BaseWikiStore, root: Path, config: DecisionConfig, service: ConsequenceService, approvals: ApprovalManifest, adapter: ApprovalAdapter) -> None
      async def publish(self, batch_id: str) -> PublishResult:
          """Refuse on stale approval, non-pass replay, or partial batch; retries converge to the same result."""
  # decisions/ingest.py  (modifies ingest.py:43, :252, :380)
  def discover_adr_sources(root: Path, config: DecisionConfig, *, approved_specs: list[str] | None = None) -> list[str]   # verified: ingest.py:43
  async def project_links(store: BaseWikiStore, records: list[DecisionRecord]) -> int   # verified: ingest.py:380 — adds about/normative edges
  ```

### Module 9: Surfaces — CLI, MCP, gate script
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py`, `cli.py`, `transport.py`, `packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py` (modify); `scripts/sdd/check_spec_consequences.py` (new)
- **Responsibility**: `op_spec_consequences` operation + `SpecConsequencesInput`; MCP spec `wiki_spec_consequences` in the `decisions` group; `wikitoolkit spec governing|consequences render|consequences check` and `wikitoolkit decisions publish --batch`; the gate script with `--json` / `--render` / `--advisory` and the exit matrix (`pass`=0, `skipped`=0, `conflict`=1, `invalid`=2, `incomplete`=3; operational failure never 0 except under `--advisory`, which downgrades 1/2/3 to a printed warning for `/sdd-task`).
- **Depends on**: M6, M7, M8.
- **Interface Skeleton**:
  ```python
  # decisions/operations.py  (modifies operations.py — after op_decision_generate)
  class SpecConsequencesInput(BaseModel): spec_path: str; mode: Literal["check", "governing"] = "check"; budget_tokens: int = DEFAULT_BUDGET_TOKENS
  async def op_spec_consequences(store: Any, params: SpecConsequencesInput, **context: Any) -> OperationResult
  # transport.py  (modifies transport.py:202, :362)
  "wiki_spec_consequences": _Spec("decisions", SpecConsequencesInput, "Evaluate a spec's declared decisions against the accepted decision plane …")
  # scripts/sdd/check_spec_consequences.py  (new; shape: check_task_graph.py:651)
  def main(argv: list[str] | None = None) -> int: """0 pass|skipped · 1 conflict · 2 invalid · 3 incomplete; --json emits the ConsequenceReport; --advisory prints a warning on 1/2/3 and returns 0 (the /sdd-task form)."""
  ```

### Module 10: SDD entry points, template, taxonomy, seed and docs
- **Path**: `sdd/templates/spec.md`, `.claude/commands/sdd-spec.md`, `.agent/workflows/sdd-spec.md`, `.agents/skills/sdd-spec/SKILL.md`, `.claude/commands/sdd-task.md`, `.agent/workflows/sdd-task.md`, `.agents/skills/sdd-task/SKILL.md` (modify); `sdd/taxonomy/subsystems.yaml`, `sdd/decisions/approvals.jsonl`, `docs/decisions/*.md`, `docs/sdd/decision-audit.md` (new)
- **Responsibility**: template gains `## Governing Decisions` (generated, before §2), `## Decisions` + optional `## Decision Waivers` (authored, after §7), `## Consequences` (generated, before §8); the three `/sdd-spec` entry points get "§4b Retrieve governing decisions" (render governing) before §5 and "§5b Consequence gate" (`check_spec_consequences --render` then `check`) before §6, refusing `approved` on non-zero exit or stale/missing sections (never on `skipped`); the three `/sdd-task` entry points get one advisory step (`check_spec_consequences --advisory <spec>` before decomposition: silent when no report, warning when contrary, never a refusal — owner Q3); the initial taxonomy (memory, clients, bots, tools, flows, skills, knowledge-wiki, knowledge-graphindex, server, integrations, config, auth, sdd-tooling, dev-loop, each mapped to `KNOWN_PROJECTS`); the seed: one `docs/decisions/<rule>.md` per architecture rule transcribed from `CLAUDE.md` / `.agent/CONTEXT.md` / `codebase-conventions.md`, each with `## Decision Metadata`; the first `approvals.jsonl` seed batch; a docs page.
  Seed rules (owner-corrected 2026-10-31):
  1. `clients-memoryless` — *forbids* `dir:packages/ai-parrot/src/parrot/clients`: clients neither load nor persist conversation history (FEAT-524).
  2. `history-single-writer` — *requires* `file:packages/ai-parrot/src/parrot/bots/abstract.py`: `AbstractBot.save_conversation_turn()` is the only writer of conversation history.
  3. `non-blocking-async-stack` — *forbids* blocking I/O in async code (`requests`, `time.sleep`, sync DB drivers) across `dir:packages`; rationale states explicitly that `httpx` is excluded for **stack consistency, not because it blocks** — it supports async; the project standardizes on aiohttp + asyncio + uvloop.
  4. `http-stack-aiohttp` — *requires* aiohttp for HTTP client and server, served by gunicorn's aiohttp worker; *forbids* ASGI stacks (`uvicorn`, `starlette`, `fastapi`) as a consequence of the asyncio/uvloop choice.
  5. `config-core-navconfig` — *requires* `navconfig` as the configuration core (no ad-hoc env parsing or settings frameworks) across `dir:packages`.
  6. `auth-platform-navigator-auth` — *requires* `navigator-auth` as the authentication, authorization, ABAC and PBAC platform (no custom auth middleware) for `dir:packages/ai-parrot-server`.
  7. `tools-live-in-parrot-tools` — *requires* `dir:packages/ai-parrot-tools/src/parrot_tools` for concrete tool implementations; `parrot/tools/` holds base machinery only.
  8. `no-langchain` — *forbids* `langchain*`, `langgraph`, `langsmith` across `dir:packages` (parrot primitives instead).
  9. `clients-base-protected` — *constrains* `file:packages/ai-parrot/src/parrot/clients/base.py`: not modified without an explicit spec decision.
  The TID251 ban list in `ruff` is unchanged by this feature; aligning the literal "never `httpx`" wording of `codebase-conventions.md` (three byte-identical copies) with rule 3's intent is a one-line follow-up outside this spec.
- **Depends on**: M2 (block grammar), M3 (formats), M9 (script names).
- **Interface Skeleton**: documents only — section names and step ids as above; seed file shape:
  ```markdown
  ---
  id: ADR-SEED-0001
  title: Clients are memory-less
  status: accepted
  ---
  ## Context … ## Decision … ## Consequences …
  ## Decision Metadata
  ```yaml
  schema_version: 1
  document_id: seed-clients-memoryless
  entries:
    - id: rule
      statement: AbstractClient subclasses neither load nor persist conversation history.
      relation: forbids
      about: [clients, memory]
      targets: [dir:packages/ai-parrot/src/parrot/clients]
  ```
  ```

### Module 11: FEAT-778 compatibility
- **Path**: `packages/ai-parrot/tests/experts/test_sources_inline.py` (extend), `packages/ai-parrot/tests/knowledge/wiki/decisions/test_feat778_compat.py` (new)
- **Responsibility**: no runtime change to `ADRSource` (experts/knowledge/sources/adr.py:16); a test proving that, on fixtures with schema-1 and schema-2 records, `ADRSource.layers()` still accepts exactly the records `is_eligible()` accepts among those `why()` returns, and that schema-2 envelopes round-trip through `DecisionService.why()` without diagnostics.
- **Depends on**: M1, M5.
- **Interface Skeleton**: tests only.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_schema1_record_parses_unchanged` | M1 | existing v1 fixtures load; schema-2 fields at defaults; invariant validator rejects v1 with v2 fields |
| `test_unsupported_schema_fails_explicitly` | M1 | `decision_from_page` on `schema_version: 3` ⇒ `ADR_UNSUPPORTED_SCHEMA`, no partial record |
| `test_spec_decision_id_charset` | M1 | valid/invalid `document_id` / `entry_id` |
| `test_parse_spec_block_happy_and_errors` | M2 | every error code; duplicate ids; dangling refs; unknown field |
| `test_canonical_block_bytes_stable` | M2 | reordered keys ⇒ identical bytes |
| `test_taxonomy_load_and_suggest` | M3 | unknown parent/project rejected; `closest()` suggestions |
| `test_git_commit_approval_adapter` | M3 | temp repo: commit on base passes; wrong digest, non-ancestor, wrong actor fail |
| `test_resolver_exact_only` | M4 | unresolved ⇒ `TARGET_UNRESOLVED` with suggestions; foreign path ⇒ `TARGET_FOREIGN`; dir expansion completeness |
| `test_eligibility_predicate` | M5 | legacy unreviewed accepted ⇒ eligible; rejected ⇒ not; spec record without approved batch ⇒ not |
| `test_supersession_graph_validation` | M5 | cycle, changed predecessor revision, competing successors, partial target set ⇒ invalid |
| `test_snapshot_unstable_is_incomplete` | M5 | revision changes between phases ⇒ `incomplete` |
| `test_explicit_conflict_blocks_beyond_limit` | M6 | conflict on the 51st record still blocks |
| `test_polarity_overlap_is_advisory` | M6 | forbid httpx + require aiohttp on same file ⇒ `potential-conflict` only |
| `test_ancestor_scope_collected` | M6 | dir rule collected for descendant symbol target; dependent outside scope gets impact only |
| `test_status_precedence` | M6 | invalid > incomplete > conflict > pass, all diagnostics retained |
| `test_digests_exclude_generated_sections` | M6 | re-rendering does not change `input_digest`; status marker edit does not either |
| `test_waiver_binding` | M6 | forged owner string / changed participants ⇒ waiver rejected |
| `test_render_byte_identical` | M7 | two renders of identical inputs ⇒ identical bytes |
| `test_check_detects_stale_and_missing` | M7 | changed inventory/source bytes ⇒ `stale`; absent section ⇒ `missing` |
| `test_publish_all_or_nothing` | M8 | injected save failure mid-batch ⇒ no eligible record from the batch, retry converges |
| `test_retirement_after_successor` | M8 | predecessor retired only after successor batch published |
| `test_replay_uses_recorded_baseline` | M8 | already-approved batch replay yields no self-conflict |
| `test_gate_exit_matrix` | M9 | 0/1/2/3 mapping; `--json` shape; operational failure never 0 |
| `test_mcp_tool_registered` | M9 | `_tool_surface.py` inventory includes `wiki_spec_consequences` |
| `test_template_sections_and_entry_points` | M10 | template contains the three headings; three `/sdd-spec` files mention the gate step |
| `test_seed_batch_valid` | M10 | seed files parse; approvals seed entry verifies on the committed tree |
| `test_adr_source_equivalence` | M11 | `ADRSource` acceptance == `is_eligible` on mixed fixtures |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_preview_and_publish` | spec with two entries → render → check pass → approval entry → publish → next spec's governing dossier lists both |
| `test_conflict_resolution_paths` | declared conflict blocks; prospective supersession of exact predecessor resolves only that conflict; approved waiver resolves; unapproved does not |
| `test_backend_parity_schema2` | SQLite and memory/file stores round-trip schema-2 records identically (extends `test_backend_parity.py`) |
| `test_evaluation_parity_backends` | `evaluate()` yields identical `evaluation_digest` on SQLite and memory stores for the same fixtures; configured live backends report gaps explicitly (S11) |
| `test_cli_mcp_json_equivalence` | `wikitoolkit spec consequences check --json`, `wiki_spec_consequences(mode="check")` and `check_spec_consequences.py --json` emit the same `ConsequenceReport` (S11) |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_codec.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_repository.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_service_retrieval.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_namespace_and_offline.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_tools.py
- packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli.py
- packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py
- packages/ai-parrot/tests/knowledge/wiki/test_transport_descriptors.py
- packages/ai-parrot/tests/experts/test_sources_inline.py
- packages/ai-parrot/tests/knowledge/okf/test_ontology.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def decision_plane(tmp_path):
    """Memory store seeded with: 2 legacy schema-1 accepted ADRs (one unreviewed), 1 rejected,
    1 superseded chain (A1 -> A2), and N>50 filler records so limit/budget truncation is exercised."""

@pytest.fixture
def spec_with_decisions(tmp_path):
    """A spec file with a valid ## Decisions block (2 entries), one explicit contradicts ref,
    frontmatter projects/tags mapping to two taxonomy subsystems."""

@pytest.fixture
def git_base_repo(tmp_path):
    """Temp git repo with a `dev` branch, one approval commit by a known author, and
    sdd/decisions/approvals.jsonl + sdd/taxonomy/subsystems.yaml committed."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1 — Read path is offline and deterministic: `evaluate()`, `governing()`, render and check make zero `AbstractClient` calls (asserted by the offline fixture pattern of `test_namespace_and_offline.py`).
- [ ] AC2 — Schema-1 records parse unchanged with identical ids; a schema the reader does not know fails with `ADR_UNSUPPORTED_SCHEMA`, never silent data loss.
- [ ] AC3 — Two entries in one spec get distinct stable ids `adr:spec:<doc>#<entry>`; renaming the spec file preserves identity; revisions pin their previous revision.
- [ ] AC4 — Blocking `contradiction` arises only from an explicit unresolved `contradicts` reference (either direction), independent of target overlap; forbid-httpx + require-aiohttp on one file is at most advisory.
- [ ] AC5 — An explicit conflict on the 51st matching record is evaluated and blocks; budget/limit affect rendering only.
- [ ] AC6 — Legacy accepted documented ADR with `review_status == unreviewed` is eligible; `rejected` or `retired` is not; a spec record without a verified approval batch is not.
- [ ] AC7 — Targets resolve exactly or the report is `invalid` with suggestions; a `dir:` rule governs a descendant symbol target; a dependent outside scope receives impact only.
- [ ] AC8 — Supersession cycle, changed predecessor revision, partial target replacement or competing successors ⇒ `invalid`, never silently repaired; historical predecessor ⇒ diagnostic with active heads.
- [ ] AC9 — Forged owner strings or changed finding participants invalidate a waiver; the contradiction stays blocking.
- [ ] AC10 — Identical inputs render byte-identical sections and digests; new accepted record, changed source bytes, taxonomy, structural edges, rules or config version make the previous check `stale` even when consulted page hashes are unchanged.
- [ ] AC11 — Exit matrix: `pass`=0, `conflict`=1, `invalid`=2, `incomplete`=3; inventory overflow, decode error, unsupported schema, snapshot instability or incomplete required impact coverage are never 0; precedence invalid > incomplete > conflict.
- [ ] AC12 — Publication is all-or-nothing per batch: a mid-batch write failure exposes no eligible record from it and no premature retirement; retries are idempotent; replay of an approved batch uses its recorded baseline and introduces no self-conflict.
- [ ] AC13 — Approval is trusted only through the manifest + git commit verification; editing the Decisions block after approval makes its records non-authoritative until a new entry is recorded.
- [ ] AC14 — `## Governing Decisions` is always rendered (explicitly empty with the searched subsystems when the plane has none); omissions are enumerable; missing fields render "not recorded".
- [ ] AC15 — `sdd/templates/spec.md` and the three `/sdd-spec` entry points carry the retrieve and gate steps; `approved` is refused on non-zero gate exit or stale/missing sections.
- [ ] AC16 — Taxonomy and seed are committed; the seed batch verifies through the adapter on `dev`; `_tool_surface.py` lists `wiki_spec_consequences`; all tests in the Validation Contract pass; `ruff check` clean on touched files.
- [ ] AC17 — FEAT-778 `ADRSource` behaviour and tests unchanged; equivalence test passes.
- [ ] AC18 — `docs/sdd/decision-audit.md` documents block grammar, exit matrix, approval flow and seed procedure.
- [ ] AC19 — Portability: in a repository with neither `sdd/taxonomy/subsystems.yaml` nor `sdd/decisions/approvals.jsonl`, a spec without a `## Decisions` block yields `skipped` (exit 0) on every surface and `/sdd-spec` proceeds; `/sdd-task` never refuses decomposition and prints a warning only when an existing report is `conflict` / `invalid` / `incomplete` / stale (`--advisory`).
- [ ] AC20 — The nine seed rules of M10 parse, resolve their targets on `dev`, and rule 3's rationale states that `httpx` is excluded for stack consistency, not for blocking.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

All references below were re-verified on 2026-10-31 against `dev` @ `56b24d87db` by the
`sdd-contract-probe` sheet of the brainstorm (41/45 found; the four "missing"
import probes were re-run inline and import cleanly through PEP 562 lazy exports).

### Verified Imports
```python
from parrot.knowledge.wiki.decisions import DecisionService, DecisionRecord, EvidenceRef, ReviewRequest, DecisionConfig  # verified: decisions/__init__.py:52-87 (lazy map :72-87)
from parrot.knowledge.wiki.decisions.models import DecisionLink, DecisionDiagnostic, DecisionError, DecisionDossier, DecisionHit, _Strict  # verified: models.py:47,57,107,140,215,224,240
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions, project_links, discover_adr_sources  # verified: ingest.py:252,380,43
from parrot.knowledge.wiki.decisions.evidence import verify_freshness, build_evidence  # verified: evidence.py:226,190
from parrot.knowledge.wiki.decisions.repository import DecisionRepository  # verified: repository.py:26
from parrot.knowledge.wiki.decisions.codec import documented_decision_id, decision_to_page, decision_from_page, canonical_json, ENVELOPE_MARKER  # verified: codec.py:104,160,191,47,34
from parrot.knowledge.wiki.decisions.parser import parse_adr, parse_frontmatter, FRONTMATTER_KEYS  # verified: parser.py:252,132,28
from parrot.knowledge.wiki.decisions.render import pack_dossier, render_dossier_text, DEFAULT_BUDGET_TOKENS, MAX_LIMIT  # verified: render.py:109,179,19,18
from parrot.knowledge.wiki.decisions.operations import DecisionWhyInput, DecisionsForSymbolInput, op_decision_why  # verified: operations.py (API outline)
from parrot.knowledge.wiki.structural import StructuralService  # verified inline import 2026-10-31; lazy export structural/__init__.py:20,43,80
from parrot.knowledge.wiki.structural.service import BlastRadiusOutput  # verified: structural/service.py:93
from parrot.knowledge.wiki.structural.operations import BlastRadiusInput  # verified: structural/operations.py:44
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord  # verified: store.py (compare_and_swap_page :824 abstract, :1865 sqlite)
from parrot.knowledge.wiki.operations import OperationResult  # verified: used by decisions/operations.py
from parrot.knowledge.okf.ontology import RelationType, ConceptType  # verified: okf/ontology.py:85,32
from parrot.knowledge.wiki.ledger.sdd_meta import DocTaxonomy, FlowMeta, KNOWN_PROJECTS, parse_taxonomy  # verified: sdd_meta.py:220,101,45,249
from parrot.experts.knowledge.sources.adr import ADRSource, ADR_LIMIT, ADR_BUDGET_TOKENS  # verified: experts/knowledge/sources/adr.py:16,13,12
from parrot.experts.knowledge.resolver import KnowledgeResolver  # verified: experts/knowledge/resolver.py:28
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class _Strict(BaseModel):                     # line 57 — model_config = ConfigDict(extra="forbid")  (line 60)
class DecisionConfig(_Strict):                # line 63
    adr_globs: list[str]                      # line 67 — default includes docs/decisions/**/*.md
    max_records: int = 10_000                 # line 70
    generation_enabled: bool = False          # line 71
class EvidenceRef(_Strict):                   # line 107 — page_id, rel_path, start_line, end_line, source_sha1 (114), excerpt, kind (116)
class DecisionLink(_Strict):                  # line 140
    target_id: str                            # line 143
    relation: Literal["explains", "supported_by", "supersedes"]   # line 144
    provenance: Literal["extracted", "inferred", "asserted"]      # line 145
class ReviewEvent(_Strict):                   # line 149
class DecisionRecord(_Strict):                # line 172
    schema_version: Literal[1] = 1            # line 175
    decision_id: str; revision: int = 1       # lines 176-177
    source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"] = "unknown"  # line 182
    origin: Literal["documented", "inferred"] # line 184
    review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"  # line 185
    source_path: str | None = None            # line 186
    evidence: list[EvidenceRef]; links: list[DecisionLink]   # lines 188-189
    content_fingerprint: str = ""             # line 194
class DecisionDiagnostic(_Strict):            # line 215
class DecisionHit(_Strict):                   # line 224 — review_status (232)
class DecisionDossier(_Strict):               # line 240
class ReviewRequest(_Strict):                 # line 299

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py
ENVELOPE_MARKER = "<!-- parrot-adr:v1 -->"    # line 34
def canonical_json(record) -> str             # line 47
def documented_decision_id(rel_path: str) -> str   # line 104 — "adr:doc:<sha1(normalized path)>"
def decision_to_page(record) -> WikiPageRecord     # line 160 — concept_id = decision_id, category ADR_CATEGORY, content_hash = sha1(envelope)
def decision_from_page(page: dict[str, Any]) -> DecisionRecord   # line 191

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py
FRONTMATTER_KEYS = ("id", "title", "status", "supersedes")   # line 28
SECTION_NAMES = ("context", "decision", "consequences", "status")   # line 31
def parse_frontmatter(lines) -> tuple[dict[str, str], int, list[DecisionDiagnostic]]   # line 132 — non-flat line ⇒ ADR_PARSE_FAILED (180)
def parse_adr(…)                              # line 252 — one record per document

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
class DecisionRepository:                     # line 26
    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None   # line 29
    async def get(self, decision_id: str) -> tuple[DecisionRecord, str | None] | None   # line 45
    async def inventory(self) -> list[DecisionRecord]   # line 63 — list_pages(limit=max_records+1); overflow ⇒ ADR_INVENTORY_LIMIT; decode errors → last_diagnostics
    async def save(self, record, expected_content_hash: str | None) -> DecisionRecord   # line 96 — per-record CAS

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
HISTORICAL_STATUSES = frozenset({"rejected", "deprecated", "superseded"})   # line 73
class DecisionService:                        # line 96 — __init__(store, root, config, structural=None, client=None)  line 99
    async def for_symbol(self, symbol, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier   # line 193
    async def why(self, question, *, include_history=False, limit=10, budget_tokens=3000) -> DecisionDossier       # line 276
    async def sync(self, paths=None) -> SyncResult   # line 371
    async def review(self, request: ReviewRequest) -> DecisionRecord   # line 473

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/render.py
DEFAULT_LIMIT = 10; MAX_LIMIT = 50; DEFAULT_BUDGET_TOKENS = 3000   # lines 16-19
def pack_dossier(…)                           # line 109 — may omit records / shorten text (presentation only)

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py
def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]   # line 43
async def refresh_decisions(store, root, config, paths=None) -> SyncResult   # line 252
async def project_links(store, records) -> int   # line 380 — rebuildable navigation projection

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py
def _resolve_confined(root: Path, rel_path: str) -> Path   # line 205
async def verify_freshness(root: Path | None, evidence: EvidenceRef) -> tuple[str, DecisionDiagnostic | None]   # line 226

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
class BlastRadiusOutput(BaseModel): root, impacted, files, truncated   # line 93
class StructuralService:                      # line 130
    async def lookup(…)                       # line 182 — names/qualnames, lexical
    async def outline(…)                      # line 264 — accepts file:<rel> or sym:<rel>#<qualname> (274)
    async def blast_radius(self, symbol, *, relations=None, depth=2, include_inferred=True, include_tests=True) -> BlastRadiusOutput   # line 360

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore:  async def upsert_pages(pages) -> int (744); async def get_page(concept_id, include_body=True) (765); async def list_pages(… ) (768); async def compare_and_swap_page(…) (824)

# packages/ai-parrot/src/parrot/knowledge/wiki/transport.py
"wiki_decisions_for_symbol": _Spec("decisions", DecisionsForSymbolInput, …)   # line 192
"wiki_decision_why": _Spec("decisions", DecisionWhyInput, …)                   # line 197
"wiki_decision_generate": _Spec("decisions", DecisionGenerateInput, …)         # line 202
elif name == "wiki_decision_why":             # line 362 — dispatch pattern (service_factory=decisions)

# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
class RelationType(str, Enum):                # line 85 — SUPERSEDES (100), CONTRADICTS (116), SUPPORTED_BY (121), ABOUT (work-lineage block)

# packages/ai-parrot/src/parrot/experts/knowledge/sources/adr.py
ADR_BUDGET_TOKENS = 3000; ADR_LIMIT = 10      # lines 12-13
class ADRSource:                              # line 16 — layers() calls service.why(description, limit, budget) (48); keeps hit if source_status in allowed and review_status != "rejected" (52)

# scripts/sdd/check_task_graph.py
class Finding(BaseModel)  # 77;  class GraphReport(BaseModel)  # 86;  def main(argv=None) -> int  # 651 (argparse, --json, exit 1 on errors)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InventorySnapshot.take` | `DecisionRepository.inventory()` | direct call | `repository.py:63` |
| `BatchPublisher.publish` | `DecisionRepository.save()` | CAS write | `repository.py:96` |
| `ConsequenceService.evaluate` | `StructuralService.blast_radius()` | impact traversal | `structural/service.py:360` |
| `ConsequenceService.evaluate` | `verify_freshness()` | evidence-gap | `evidence.py:226` |
| `TargetResolver.resolve` | `BaseWikiStore.get_page()` | exact id existence | `store.py:765` |
| `project_links` (extended) | `RelationType.ABOUT` / new normative values | edge projection | `okf/ontology.py:85` |
| `op_spec_consequences` | `transport._Spec` registry + dispatch | MCP | `transport.py:202,362` |
| `discover_adr_sources` (extended) | `ApprovalManifest.for_document` | approved spec list | new |
| `GitCommitApprovalAdapter` | `git cat-file` / `git merge-base --is-ancestor` / `git show <sha>:<path>` | subprocess (async) | new |
| `ADRSource` (unchanged) | `is_eligible` | equivalence test only | `experts/knowledge/sources/adr.py:52` |

### Does NOT Exist (Anti-Hallucination)
- ~~`docs/adr/`, `docs/adrs/`, `docs/decisions/`~~ — none exist; the plane holds zero records (local query confirmed).
- ~~`RelationType.CONSTRAINS` / `FORBIDS` / `REQUIRES`~~ — to be added by M1.
- ~~`ConsequenceService`, `ConsequenceReport`, `InventorySnapshot`, `TargetResolver`, `BatchPublisher`, `Taxonomy`, `ApprovalManifest`, `DecisionRef`, `DecisionTarget`~~ — all new in this spec.
- ~~`scripts/sdd/check_spec_consequences.py`~~, ~~`sdd/taxonomy/`~~, ~~`sdd/decisions/`~~ — do not exist.
- ~~`## Governing Decisions` / `## Decisions` / `## Consequences` in `sdd/templates/spec.md`~~ — not present.
- ~~`targets:` / `about:` keys in the ADR parser~~ — `FRONTMATTER_KEYS` reads only `id/title/status/supersedes`; a multiline YAML list is a non-flat diagnostic. The seed therefore carries its metadata in a fenced block (M2), not in frontmatter.
- ~~`DecisionRecord.tags`~~ — no tag/component filter on records.
- ~~multi-record transactions on `BaseWikiStore`~~ — `compare_and_swap_page` protects one page; batch atomicity is M8's marker protocol.
- ~~`StructuralService.lookup()` as an id validator~~ — lexical name lookup; `DecisionService._resolve_symbol()` (service.py:171) accepts a `sym:` prefix without existence check.
- ~~a CI step running `check_task_graph` / `check_e2e_closeout`~~ — no reference in `.github/workflows/*.yml`; CI wiring for this gate is deferred anyway (§8).
- ~~any decision-plane call in `/sdd-spec`, `/sdd-task`, `sdd-coder`, `sdd-worker`~~ — zero references today.
- ~~`parrot.knowledge.ontology.concept_catalog` as the subsystem taxonomy~~ — FEAT-159 per-tenant topic ontology in Postgres; not reused.
- `KnowledgeResolver` / `ADRSource` **exist** (FEAT-778, 22/22 done); what does not exist is a domain-scoped, complete-inventory decision adapter.
- Ledger `36a652416160` is **closed** (FEAT-700 centralized the expected MCP tool set in `tests/knowledge/wiki/_tool_surface.py`); `b084239103d7` remains open.

### Edit Sites (Blueprint Anchors)

Verified against: `56b24d87db`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | MODIFY | `    relation: Literal["explains", "supported_by", "supersedes"]` | `models.py:144` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | MODIFY | `class DecisionRecord(_Strict):` | `models.py:172` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | MODIFY | `    schema_version: Literal[1] = 1` | `models.py:175` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` | MODIFY | `ENVELOPE_MARKER = "<!-- parrot-adr:v1 -->"` | `codec.py:34` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` | MODIFY | `def documented_decision_id(rel_path: str) -> str:` | `codec.py:104` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py` | MODIFY | `def decision_from_page(page: dict[str, Any]) -> DecisionRecord:` | `codec.py:191` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/__init__.py` | MODIFY | `    "DecisionService": "parrot.knowledge.wiki.decisions.service",` | `__init__.py:82` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | `def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]:` | `ingest.py:43` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | `async def project_links(store: BaseWikiStore, records: list[DecisionRecord]) -> int:` | `ingest.py:380` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py` | MODIFY | `async def op_decision_generate(store: Any, params: DecisionGenerateInput, **context: Any) -> OperationResult:` | `operations.py` (API outline) | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    "wiki_decision_generate": _Spec(` | `transport.py:202` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    elif name == "wiki_decision_why":` | `transport.py:362` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `        name="adr",` | `cli.py:2663` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/_tool_surface.py` | MODIFY | `        "wiki_decisions_for_symbol",` | `_tool_surface.py:21` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | MODIFY | `    SUPPORTED_BY = "supported_by"` | `ontology.py:121` | 1 |
| `sdd/templates/spec.md` | MODIFY | `## 2. Architectural Design` | `spec.md:52` | 1 |
| `sdd/templates/spec.md` | MODIFY | `## 8. Open Questions` | `spec.md` (template) | 1 |
| `.claude/commands/sdd-spec.md` | MODIFY | `### 5. Scaffold the Spec` | `sdd-spec.md:444` | 1 |
| `.claude/commands/sdd-spec.md` | MODIFY | `### 6. Commit the Spec` | `sdd-spec.md:580` | 1 |
| `.agent/workflows/sdd-spec.md` | MODIFY | `### 5. Scaffold the Spec` | `sdd-spec.md:448` | 1 |
| `.agent/workflows/sdd-spec.md` | MODIFY | `### 6. Commit the Spec` | `sdd-spec.md:584` | 1 |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | `## Workflow` | `SKILL.md:38` | 1 |
| `.claude/commands/sdd-task.md` | MODIFY | `### 2. Read the Spec` (advisory check step inserted after it) | `sdd-task.md:101` | 1 |
| `.agent/workflows/sdd-task.md` | MODIFY | `### 2. Read the Spec` | `sdd-task.md:97` | 1 |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | `## Workflow` | `SKILL.md:43` | 1 |
| `packages/ai-parrot/tests/experts/test_sources_inline.py` | MODIFY | (append tests; anchor = end of file) | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_entries.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/taxonomy.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/scope.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/inventory.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences_render.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/publish.py` | CREATE | — | — | — |
| `scripts/sdd/check_spec_consequences.py` | CREATE | — | — | — |
| `sdd/taxonomy/subsystems.yaml` | CREATE | — | — | — |
| `sdd/decisions/approvals.jsonl` | CREATE | — | — | — |
| `docs/decisions/*.md` (seed, ≥ 7 files) | CREATE | — | — | — |
| `docs/sdd/decision-audit.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_{spec_entries,taxonomy,approvals,scope,inventory,consequences,consequences_render,publish,feat778_compat}.py` | CREATE | — | — | — |
| `tests/sdd_scripts/test_check_spec_consequences.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Strict Pydantic models (`_Strict`, `extra="forbid"`) for every new record; stable string literals; additive enum values only.
- All decision-plane reads go through `DecisionRepository`; never `store.list_pages` from a new module except inside `InventorySnapshot`.
- Async-first; git verification in the approval adapter uses `asyncio.create_subprocess_exec`, never blocking subprocess calls in async paths.
- `DecisionError` with stable codes for every refusal; diagnostics, not exceptions, for spec-content faults (`invalid` / `incomplete` carry them).
- Error codes introduced: `ADR_UNSUPPORTED_SCHEMA`, `ADR_INVALID_ID`, `SPEC_*` (M2), `TAXONOMY_INVALID`, `APPROVAL_MANIFEST_INVALID`, `APPROVAL_UNVERIFIED`, `TARGET_UNRESOLVED`, `TARGET_FOREIGN`, `SCOPE_INCOMPLETE`, `SNAPSHOT_UNSTABLE`, `SUPERSESSION_INVALID`, `WAIVER_INVALID`, `BATCH_PARTIAL`.
- Gate script mirrors `scripts/sdd/check_task_graph.py` (argparse, `--json`, Pydantic report); exit codes per matrix.
- `wikitoolkit` CLI additions follow the existing `adr` subcommand registration at `cli.py:2663`; MCP additions follow the `_Spec` + dispatch pattern and update `_tool_surface.py` in the same task.
- Logging through `self.logger`; no `print` outside the CLI/script entry points (`# noqa: T201`).

### Known Risks / Gotchas
- **Budgeted outputs are not gate inputs** (audit F02): `DecisionService.for_symbol()/why()` and `pack_dossier()` omit records; the evaluator must consume `InventorySnapshot.eligible` only.
- **Double-acceptance trap** (F03): `parse_adr()` never sets `review_status`; the eligibility predicate must not require `review_status == accepted`.
- **One document → one record** (F04): `parse_adr()` + `documented_decision_id()` are path-identified; spec entries need `spec_entries.py`, never a frontmatter extension.
- **`lookup()` is lexical** (F05): exact-id validation is `TargetResolver`; `_resolve_symbol()` does not check existence.
- **Supersedes is a link, not a transition** (F06): `_visible()` filters by `source_status`; effectiveness comes from `InventorySnapshot.effective_head`, retirement from approved events.
- **Digest self-reference** (F07): writing `## Consequences` changes the file; `canonicalize_spec` must strip generated sections and the status line before hashing; code changes alter `verify_freshness` without changing stored pages — the manifest includes observed source hashes.
- **Compatibility is one-directional** (F10): old readers fail on schema 2 explicitly; upgrade readers (FEAT-778 runtime included) before publishing schema-2 records. Rollout order: M1 merged and deployed → seed batch published.
- **Structural read-repair** (S6): `StructuralService._ensure_fresh()` rescans changed files on ordinary reads; the gate must use `read_repair=False` or a rescan during evaluation silently changes the snapshot. Truncation is a boolean — treat it as incompleteness, never as "no more impact".
- **Exact-set MCP tests**: `_tool_surface.py` is the single inventory (FEAT-700); forgetting it fails `test_mcp_server.py`.
- **Approval offline**: when `origin/<base_branch>` is unreachable the adapter verifies against the local base ref and emits `APPROVAL_LOCAL_BASE` diagnostic; publication still requires ancestry.
- **Edge cases carried from the brainstorm**: missing/ambiguous/foreign targets, unknown taxonomy ids, duplicate entry ids, dangling refs, cycles ⇒ `invalid`; a no-decision spec still validates and computes impact; legacy ADRs without taxonomy/targets stay visible as unmapped with an explicit coverage gap; missing dossier fields say "not recorded"; unverifiable approval refuses activation; missing/stale generated content fails check mode and render is the repair; generated content never stores authoritative resolution metadata.
- **Shared tree hazard**: `_tool_surface.py`, `transport.py`, `cli.py` and the three `/sdd-spec` files are edited by other in-flight features; rebase early.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | existing; models and reports |
| `PyYAML` | existing core dependency | `## Decisions` block, taxonomy file |
| `wikitoolkit` (in-repo) | — | decision / structural planes, MCP transport |
| `git` CLI | ≥ 2.30 | approval adapter (`cat-file`, `merge-base --is-ancestor`, `show`) |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Flow type and base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Who asserts a decision — *Resolved in brainstorm*: a structured, human-approved section of the spec; no LLM inference on the critical path.
- [x] Granularity — *Resolved in brainstorm*: two layers; module-level architecture rules in v1, symbol-level task contracts in the certificate phase.
- [x] v1 core — *Resolved in brainstorm*: consequence preview in `/sdd-spec`; task certificate, drift job and backfill are later phases.
- [x] Checks in v1 — *Resolved in brainstorm*: contradictions, blast radius, undeclared supersedes, evidence gaps (all four).
- [x] Verdict semantics — *Resolved in brainstorm*: `## Consequences` written into the spec; only an unresolved contradiction is a blocking finding. Contract clarification: invalid inputs and incomplete audits cannot authorize approval either.
- [x] Target resolution — *Resolved in brainstorm*: explicit `sym:`/`file:`/`dir:` ids; unresolved target is a spec error.
- [x] Seed — *Resolved in brainstorm*: curated architecture-rules file(s), approved once, ingested as accepted.
- [x] Should the plane also feed spec authoring — *Resolved in brainstorm*: yes; decisions are curated ontological knowledge consumed by `/sdd-spec` and produced by it; retrieval needs a subsystem axis (`about`) besides symbols.
- [x] Approval trust adapter — *Resolved in brainstorm*: the git commit on `base_branch` that sets the spec `**Status**: approved` (or lands a seed batch), recorded in `sdd/decisions/approvals.jsonl` (spec path, entry ids, sha256 of the canonical Decisions block, approving commit sha, actor = commit author; signed commits recommended); ingestion trusts only a digest-matching entry; an edit without a new entry turns records `unverified`; retirement and waivers are new manifest entries.
- [x] v1 conflict boundary — *Resolved in brainstorm*: only explicit `contradicts` / `supersedes` ID links can block; target/polarity coincidences are advisory; a structured proposition language is a follow-up spec.
- [x] Seed packaging — *Resolved in brainstorm*: ADR Markdown under `docs/decisions/` with extended metadata, one file per rule, approved as a batch in the same manifest.
- [x] Taxonomy / manifest locations and curator — *Resolved in brainstorm*: `sdd/taxonomy/subsystems.yaml`, `sdd/decisions/approvals.jsonl`, curated by the repo owner via PRs to `base_branch`; subsystems projected as `concept:<id>` pages.
- [x] CI in v1 — *Resolved in brainstorm*: later delivery; v1 runs from `/sdd-spec` and ships the read-only check script.
- [x] `/sdd-task` dossier propagation — *Resolved in brainstorm*: later, with the task-certificate phase.
- [x] Governing Decisions mandatory? — *Resolved in brainstorm*: the complete evaluation is mandatory; the section is always rendered but claims no reading attestation.
- [x] `/sdd-brief` preview — *Resolved in brainstorm*: `/sdd-spec` only in v1.
- [x] External verifier spike — *Resolved in brainstorm*: deferred until task certificates exist.
- [ ] Batch-visibility marker shape (M8): a dedicated `adr:batch:<id>` page vs a `pending` lifecycle value on each record — decide at M8 task time; both keep half-written batches invisible. — *Owner: spec author (implementation)*
- [ ] Initial taxonomy granularity: start with the ~12 subsystems listed in M10 and grow by PR, or seed one subsystem per `KNOWN_PROJECTS` entry only? — *Owner: Jesús (can be decided at M10 task time)*
- [x] Q3 (escalated from design research S9): should `/sdd-task` run `check_spec_consequences` in read-only check mode and refuse decomposition of a spec whose report is missing, stale or blocking? — *Owner: Jesús (2026-10-31)*: **no refusal**. The SDD flow is used in other packages where nobody will author ADR documents or build the graph, so `/sdd-task` must never refuse a spec for lacking a report; it runs check mode and emits a **warning** only when a report exists and is contrary (`conflict`, `invalid`, `incomplete` or stale). Carried into §2 (portability principle, `skipped` status), §3 M9/M10 and AC19.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.166.0, reasoning high, 127 s) · Status: completed
> · Transcript: `sdd/state/FEAT-784/design_research/` (brief, suggestions.json, triage.md, run.json)
> Every `affected_paths` entry passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define a real consistent decision inventory snapshot (architecture) | CONFIRM | `inventory()` skips deleted pages and downgrades decode errors to diagnostics (repository.py:63-95); gate must fail closed | §3 M5 |
| S2 | Do not expose partially published approval batches (risk) | CONFIRM | only per-page CAS exists (store.py:824/1865); readers need a batch marker | §3 M8, AC12 |
| S3 | Version the envelope and relation vocabulary explicitly (api) | CONFIRM | `Literal[1]`, `parrot-adr:v1`, closed `DecisionLink.relation` (models.py:144/175, codec.py:34) | §3 M1, §7 rollout order |
| S4 | Separate effective-governing inventory from ordinary retrieval (architecture) | CONFIRM | `_visible()` shows unknown/proposed statuses (service.py:161-170); supersession not evaluated there | §3 M5, §7 |
| S5 | Add a typed target resolver instead of interpreting empty structural results (api) | CONFIRM | `outline()` empty on missing/unindexed; `lookup()` is a suggestion API | §3 M4 (`ResolvedTarget.state`) |
| S6 | Treat blast-radius truncation and read-repair as audit incompleteness (risk) | CONFIRM | `_BLAST_RADIUS_NODE_CAP = 500` (:42), `truncated` (:458), `_ensure_fresh` read-repair with `read_repair=False` mode (:138/:433) | §3 M6 (`read_repair=False`; cap ⇒ `incomplete`), §7 |
| S7 | Make the `about` taxonomy independent from free-form SDD tags (alternative) | CONFIRM | `DocTaxonomy` permits arbitrary tags, warns on unknown projects (sdd_meta.py:201/220) | §3 M3 |
| S8 | Keep the spec-entry parser separate from legacy ADR refresh; define revision transitions (architecture) | CONFIRM | `parse_adr()` is one path-identified record (parser.py:252, codec.py:104) | §3 M2, M8 |
| S9 | Make approval an executable SDD transition (architecture) | CONFIRM + ESCALATE | `/sdd-spec` refusal is M9/M10 (AC15); extending the refusal to `/sdd-task` decomposition is cheap but the owner deferred `/sdd-task` work | §3 M10, AC15; §8 Q3 |
| S10 | Freeze the approval-evidence trust adapter before implementing ingestion (risk) | CONFIRM | resolved by the owner before this spec (git-commit-bound manifest); `review()` is never a publication path | §3 M3, §7, §8 |
| S11 | Require backend and transport parity for the new evaluation API (testing) | CONFIRM | parity tests already make SQLite and memory mandatory | §4 Integration Tests |

Summary: **11** confirmed · **0** rejected · **1** escalated (S9, partial).

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-784-sdd-decision-audit` from `origin/dev`; the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in §3 skeletons):
  - M2 → M1 (imports `DecisionRef`, `DecisionRecord` schema-2 fields)
  - M3 → M2 (`canonical_block_bytes`), M3 → M1
  - M4 → (existing `StructuralService`, `BaseWikiStore`) — independent of M1–M3
  - M5 → M1, M3 (`Taxonomy`, `ApprovalManifest`, `ApprovalAdapter`)
  - M6 → M2, M3, M4, M5
  - M7 → M6 (`ConsequenceReport`, `GoverningDossier`)
  - M8 → M1, M2, M3, M5, M6
  - M9 → M6, M7, M8
  - M10 → M2 (block grammar), M3 (file formats), M9 (script name); taxonomy/seed/template files can be authored in parallel with M1–M9 but the seed approval entry is recorded after M9 lands
  - M11 → M1, M5
  - M1, M4 and the document parts of M10 have no inbound edge and run concurrently.
- **Shared files** (tasks serialized): `decisions/__init__.py` (M1 exports, M6/M8/M9 exports), `decisions/ingest.py` (M8 only), `transport.py` / `cli.py` / `_tool_surface.py` (M9 only), `okf/ontology.py` (M1 only).
- **Exclusive resources**: none (no extension rebuilds, lockfile or migration steps).
- **Cross-feature dependencies**: none to merge first; FEAT-778 is merged. Watch for concurrent edits to `transport.py`, `cli.py`, `_tool_surface.py` and the three `/sdd-spec` entry-point files.
