---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Capability Spec Registry & Delta Markers

**Date**: 2026-08-24
**Author**: Arturo Martinez
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Our SDD workflow (`sdd/WORKFLOW.md`) treats every feature spec
(`sdd/specs/<feature>.spec.md`) as a standalone, FEAT-numbered document.
There is no persistent notion of a "capability" (e.g. `form-validation`,
`formdesigner-unknown-fields-capture`) whose behavior is described once and
then evolves over time. When FEAT-459 needs to change behavior that
FEAT-012's spec originally defined, the only mechanism today is prose: a
human (or agent) reads the old spec, hand-edits it, and adds a row to its
`## Revision History` table. There is no structured, machine-checkable
record of *what specifically changed* (added vs. modified vs. removed vs.
renamed behavior), and no tooling that verifies the edit didn't silently
drop or contradict something the original spec guaranteed.

Research into OpenSpec (`Fission-AI/OpenSpec`, v1.10.0 — cloned and read at
the source level, not just its docs) showed a materially more rigorous
mechanism for exactly this problem: a persistent per-capability spec plus a
structured `ADDED`/`MODIFIED`/`REMOVED`/`RENAMED` delta format that is
mechanically merged into that persistent spec, with real edge-case handling
(conflict detection, near-miss/typo detection, idempotent re-application,
capability retirement). We want to bring the *idea* into our workflow —
adapted to our own document shapes, our own tooling conventions (Python +
Pydantic, not TypeScript), and our own merge point (`/sdd-done`, not an
`archive` command) — as an **addition** to the existing SDD pipeline, not a
replacement for FEAT specs, tasks, or worktrees.

Who is affected: SDD spec authors (human and the `sdd-ideation`/`sdd-spec`
agents) who need to evolve previously-shipped behavior, and `sdd-worker` /
`/sdd-done`, which need a trustworthy, structured signal about exactly what
a feature changed in an already-approved capability.

## Constraints & Requirements

- Must be **additive**: existing FEAT specs without any delta block must
  continue to work exactly as they do today (backward compatible template).
- Must fit the existing SDD conventions: Markdown + YAML frontmatter for
  documents, Python + Pydantic for tooling (matching `scripts/sdd/id_ledger.py`,
  `scripts/sdd/reserve_ids.py`, `scripts/sdd/check_id_collisions.py`), git as
  the only source of truth (no new database or service).
- The merge must happen at a well-defined point in the existing pipeline —
  per discovery, that point is `/sdd-done` (mirrors OpenSpec's archive-time
  merge; the capability spec only reflects *shipped* behavior).
- v1 must replicate OpenSpec's full edge-case rigor (per discovery answer):
  conflict detection, near-miss/typo detection, idempotent re-application of
  an already-applied delta, and capability retirement when a capability's
  last requirement is removed.
- Must not require any new external service or language runtime (no Node/npm
  — this is a Python-only monorepo tool).

---

## Options Explored

### Option A: Capability Spec Registry + Delta-Merge Engine (Python, merged at `/sdd-done`)

Introduce a new, persistent document type — the **capability spec**
(`sdd/specs/capabilities/<capability-slug>.md`) — as the "living truth" for
a named capability, structurally separate from FEAT specs. A FEAT spec
declares which capabilities it adds or modifies in a new, optional
`## Capability Deltas` section using the same grammar OpenSpec uses:
`### Requirement: <name>` blocks (SHALL language) with `#### Scenario: <name>`
sub-blocks, grouped under `## ADDED Requirements` / `## MODIFIED Requirements`
/ `## REMOVED Requirements` / `## RENAMED Requirements` headers. A new Python
module (`scripts/sdd/capability_deltas.py`) parses this block into a
`DeltaPlan` (Pydantic model, mirroring `IdReservation`/`CollisionReport`'s
result-model pattern) and a merge function applies it to the target
capability spec in `RENAMED → REMOVED → MODIFIED → ADDED` order — the exact
ordering OpenSpec uses to avoid ambiguity when a rename and a removal touch
related names in the same delta. `/sdd-done` gets a new step between task
verification (current Step 7) and branch integration (current Step 9) that
runs the merge and commits the updated capability spec(s) as part of the
same feature-branch-to-base-branch integration, so a capability spec never
reflects unshipped behavior. A companion read-only validator
(`scripts/sdd/validate_capability_deltas.py`) can run during `/sdd-spec`
review, before implementation even starts, to catch malformed delta blocks
early — mirroring `check_id_collisions.py`'s role as an independent,
non-blocking-until-CI backstop.

✅ **Pros:**
- Fits existing conventions exactly: Markdown docs, Python + Pydantic
  tooling, git-native, no new infrastructure.
- Backward compatible — a FEAT spec with no `## Capability Deltas` section
  behaves exactly as today.
- Gives us the actual rigor requested (conflict detection, near-miss
  detection, idempotent re-apply, retirement) rather than a documentation-only
  convention that can silently drift from reality.
- Merge point (`/sdd-done` Step 9) is already the place where "this feature
  is verified and about to become part of base_branch" is established —
  natural fit, no new state machine needed.
- Capability specs become genuinely reusable ground truth other
  tools (wiki ingestion, `/sdd-explain`, future dashboards) can read as plain
  Markdown without needing to reconstruct history from N FEAT specs.

❌ **Cons:**
- Highest effort of the three options — a real parser + merge engine with
  edge-case handling is nontrivial to get right (OpenSpec's own `specs-apply.ts`
  needed 7+ rounds of bug fixes per its own code comments).
- Introduces a second spec taxonomy (FEAT specs vs. capability specs) that
  authors must learn to distinguish.
- Capability retirement (deleting a spec file when its last requirement is
  removed) is a genuinely risky operation to automate correctly — must be
  explicitly gated, not inferred.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (already a dependency) | `DeltaPlan`, `RequirementBlock`, `CapabilitySpec` models | Same pattern as `id_ledger.py`'s `IdLedger`, `reserve_ids.py`'s `IdReservation` |
| `PyYAML` (already a dependency, used by `sdd_meta.py`) | Frontmatter parsing for capability specs | No new dependency |
| stdlib `re` | Requirement/Scenario block boundary detection | Same style as `check_id_collisions.py`'s `_TASK_FILENAME_RE` / `_FEATURE_ID_HEADER_RE` |

🔗 **Existing Code to Reuse:**
- `scripts/sdd/sdd_meta.py:45-93` (`FlowMeta.parse`/`emit`) — exact pattern to
  follow for parsing/emitting a new frontmatter field (e.g. `capabilities:`
  declared on a FEAT spec).
- `scripts/sdd/id_ledger.py:34-83` (`IdLedger`, `load_ledger`, `save_ledger`) —
  Pydantic-model-plus-git-tracked-JSON pattern; not reused directly (capability
  ids are kebab-slugs, not a numeric ledger) but the load/validate/save shape
  is the template for a `CapabilitySpecStore`-equivalent if one is needed.
- `scripts/sdd/check_id_collisions.py` (whole file) — the "independent,
  read-only, defense-in-depth" script shape to mirror for
  `validate_capability_deltas.py`.
- `.claude/commands/sdd-done.md:206-309` (Step 9, "Integrate Feature Branch")
  — the exact hook point; runs on `base_branch`, never inside a worktree,
  which matches where a capability-spec commit must land.

---

### Option B: Delta Annotations in Revision History Only (documentation convention, no merge automation)

Keep everything as-is structurally — no new capability-spec directory, no
merge engine. Instead, extend the existing `## Revision History` table
convention: when a FEAT changes behavior an earlier spec defined, its entry
in *that earlier spec's* Revision History gets a structured annotation using
the same `ADDED`/`MODIFIED`/`REMOVED`/`RENAMED` vocabulary, written by hand
(or by an agent) directly into the old spec's existing Markdown, with no
parser, no validation, and no automated merge step anywhere.

✅ **Pros:**
- Trivial to ship — a template convention change and a note in
  `sdd/WORKFLOW.md`, no new Python code at all.
- Zero risk of a buggy merge engine corrupting an approved spec.

❌ **Cons:**
- Does not satisfy what was actually asked for (full merge automation with
  OpenSpec-level rigor) — this is the option explicitly *not* chosen during
  discovery, included here for completeness and honest tradeoff comparison.
- No machine-checkable guarantee the annotation is accurate — an agent could
  claim `REMOVED` a requirement that's still present three sections up, and
  nothing would catch it.
- Still requires a human/agent to locate and hand-edit the *old* spec file
  for every change — no separation between "the shipped truth" and "the
  history of how we got here," so old specs keep being rewritten by
  unrelated later features.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | pure documentation-convention change |

🔗 **Existing Code to Reuse:**
- `sdd/templates/spec.md:191-196` (`## Revision History` table) — the
  section that would carry the annotation.

---

### Option C: Wiki-Graph-Native Capability Deltas (unconventional)

Instead of a new flat-file capability-spec directory, treat each capability
as a **node in the existing LLM-wiki knowledge graph** (`wikitoolkit`, already
mandated by `CLAUDE.md` for all codebase knowledge and already running a
git-post-commit-hook-refreshed graph in this repo). A FEAT spec's delta block
is filed via `wikitoolkit note <capability-page-id> "<delta text>"` at
`/sdd-done` time, and each `ADDED`/`MODIFIED`/`REMOVED`/`RENAMED` operation
becomes a typed, asserted edge (`wikitoolkit link <feat-spec-page>
<capability-page> --rel modifies|adds|removes|renames`) between the FEAT
spec's page and the capability's page. "What has changed about
`form-validation`?" becomes `wikitoolkit related capability:form-validation`
instead of opening a file.

✅ **Pros:**
- Reuses infrastructure that already exists and is already a mandated
  first-stop for codebase knowledge in this repo — no new storage mechanism.
- Naturally queryable and cross-linkable (typed edges, `wikitoolkit query`)
  without writing any new parser.
- Wiki pages already support attributed, dated notes and an audit log
  (`wikitoolkit audit`) — "who claimed what changed and when" comes for free.

❌ **Cons:**
- The wiki is documented as *durable memory layered on top of the repo*, not
  the repo's source of truth — putting behavior-defining delta content only
  in the wiki DB would make it the one piece of SDD state that isn't a
  plain, git-diffable Markdown file reviewable in a PR, breaking the
  project's "everything is a file" SDD convention.
- No real merge/conflict semantics — `wikitoolkit note`/`link` are
  append/assert operations; there's no equivalent of "reject this delta
  because it collides with an existing requirement," which is exactly the
  rigor that was asked for.
- Couples the delta-tracking feature to `wikitoolkit`'s availability and
  schema; a capability's history would not be readable at all without it.

📊 **Effort:** Medium–High (mostly integration work, but must design a merge
semantics layer on top of `note`/`link` that doesn't exist today)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `wikitoolkit` (already installed, `.venv/bin/wikitoolkit`) | `note`, `link`, `remember`, `related`, `query` commands | Verified via `wikitoolkit --help` — commands exist today |

🔗 **Existing Code to Reuse:**
- `wikitoolkit note <page_id> "<text>"` and `wikitoolkit link <src> <dst>
  --rel <relation>` — verified subcommands (`wikitoolkit --help` output).
- `wikitoolkit query` / `wikitoolkit related` — verified subcommands for
  reading the resulting graph back.

---

## Recommendation

**Option A** is recommended because it is the only option that actually
delivers what discovery converged on: a persistent capability-level source
of truth, a structured delta grammar, and full merge rigor (conflict
detection, near-miss detection, idempotent re-apply, gated retirement) —
while staying inside this repo's existing conventions (Markdown + YAML
frontmatter for documents, Python + Pydantic for tooling, git as the only
store, `/sdd-done` as the integration point).

Option B is rejected as the primary approach because it was explicitly the
lighter alternative discovery moved past — it gives no machine-checkable
guarantee, which defeats the point of borrowing OpenSpec's rigor in the
first place. Option C is rejected as the *primary* mechanism because it
would make behavior-defining content live outside the plain-Markdown,
git-diffable SSOT model every other SDD artifact follows, and because
`note`/`link` have no merge/conflict semantics of their own — building those
on top of the wiki would mean building Option A's merge engine anyway, just
with an extra dependency underneath it.

What we're trading off by choosing A: more upfront implementation effort
(a real parser and merge engine) and a second document taxonomy (FEAT specs
vs. capability specs) that authors need to learn. Both are acceptable given
the explicit ask was for full OpenSpec-level rigor, not the cheapest option.

Option C is not wasted, however — nothing prevents `wikitoolkit build`/`ingest`
from later indexing `sdd/specs/capabilities/*.md` alongside everything else
it already ingests, giving the wiki's query/related tools visibility into
capability specs for free, without making the wiki the merge authority.

---

## Feature Description

### User-Facing Behavior

- When drafting a FEAT spec via `/sdd-spec`, an author who knows their
  feature changes previously-shipped behavior adds a `## Capability Deltas`
  section (new, optional — omitted specs behave exactly as today) declaring
  which capability(ies) it adds or modifies, using `## ADDED Requirements` /
  `## MODIFIED Requirements` / `## REMOVED Requirements` / `## RENAMED
  Requirements` headers with `### Requirement: <name>` + `#### Scenario:
  <name>` blocks — the same grammar as the existing spec's other structured
  sections, so it reads like more spec, not a foreign format.
- Nothing changes about `/sdd-task`, `/sdd-start`, or `sdd-worker` — they
  keep working from the FEAT spec and its tasks exactly as today.
- At `/sdd-done` time, once all tasks are verified (existing Step 5–7), a new
  step reads the spec's `## Capability Deltas` block (if present), locates
  the target capability spec(s) under `sdd/specs/capabilities/`, and merges
  the delta in. If the target capability spec doesn't exist yet (this is the
  first FEAT to touch it), a new one is created from the `ADDED` block. The
  merged capability spec is committed on `base_branch` as part of the same
  integration that lands the feature branch — visible in the same PR/merge,
  never a separate silent step.
- If a delta is malformed — a name collision between `ADDED` and `REMOVED`,
  a `MODIFIED` block naming a requirement that doesn't exist, a near-miss
  typo against an existing requirement name — `/sdd-done` aborts with a
  specific, actionable error (mirroring the report style of the existing
  Verification Report in Step 5) *before* touching `base_branch`.

### Internal Behavior

- `scripts/sdd/capability_deltas.py` (new): parses a spec's `## Capability
  Deltas` section into a `DeltaPlan` Pydantic model (`added`, `modified`,
  `removed`, `renamed` lists of `RequirementBlock`s), following the same
  result-model shape as `IdReservation` (`reserve_ids.py`) and
  `CollisionReport` (`check_id_collisions.py`).
- A merge function applies the plan against the target capability spec's
  existing `### Requirement:` blocks in `RENAMED → REMOVED → MODIFIED →
  ADDED` order (this fixed order avoids ambiguity: e.g., a rename must land
  before a modification that references the new name).
- Pre-merge validation (usable standalone via
  `scripts/sdd/validate_capability_deltas.py`, and reused inside the merge
  path) checks: no name appears in more than one operation section; every
  `MODIFIED`/`RENAMED`-from name exists in the target (or is already
  absent — treated as an idempotent no-op, not an error, so a re-run of
  `/sdd-done` after a partial failure doesn't break); every requirement has
  at least one scenario.
- Capability retirement (deleting a capability spec whose last requirement
  was just removed) only happens when the FEAT spec's delta block carries an
  explicit `retire_capability: true` marker — never inferred purely from the
  requirement count reaching zero.
- The merge commit is created on `base_branch` inside the existing
  `/sdd-done` flow (Step 9's integration point), never inside the worktree
  and never on a separate uncoordinated branch.

### Edge Cases & Error Handling

- **Near-miss requirement name** (case/whitespace variant of an existing
  name): hard error naming the close match, refusing to silently create a
  duplicate.
- **Re-running `/sdd-done` after a prior partial failure**: an already-applied
  `ADDED`/`MODIFIED`/`REMOVED`/`RENAMED` operation whose target state already
  matches is a no-op, not an error — required for `/sdd-done`'s existing
  `--force`/retry semantics to keep working.
- **`REMOVED` naming a requirement that's already gone**: warning, not a
  hard error (already-synced case).
- **Two features touching the same capability spec concurrently** (feature
  A's worktree and feature B's worktree both declare deltas against
  `form-validation` and both reach `/sdd-done` before the other merges):
  the second `/sdd-done` run re-reads the just-updated capability spec from
  `base_branch` before merging (same "read current state, don't assume
  worktree-time state" principle `reserve_ids.py` already uses for the ID
  ledger) — if the delta no longer applies cleanly, abort with a clear
  conflict message rather than silently overwriting.
- **No `## Capability Deltas` section present**: `/sdd-done` skips the new
  step entirely — fully backward compatible with every existing spec.

---

## Capabilities

### New Capabilities
- `sdd-capability-spec-registry`: the new `sdd/specs/capabilities/` directory
  and capability-spec document shape (persistent, Requirement/Scenario
  format, one file per capability).
- `sdd-capability-delta-merge`: the parser, merge engine, validator script,
  and their integration into `/sdd-done`.

### Modified Capabilities
- None yet — this is new functionality layered on top of the existing SDD
  pipeline; no existing capability spec exists to modify because this
  brainstorm is what introduces the capability-spec concept itself.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `sdd/templates/spec.md` | extends | new optional `## Capability Deltas` section; existing specs unaffected |
| `.claude/commands/sdd-done.md` | extends | new step between current Step 7 (Stamp Verification) and Step 9 (Integrate Feature Branch) that runs the delta merge on `base_branch` |
| `.claude/commands/sdd-spec.md` | extends (optional, open question) | could prompt authors to declare capabilities affected, mirroring OpenSpec's proposal-time capability declaration |
| `scripts/sdd/sdd_meta.py` | pattern reference | same frontmatter-parsing approach for any new `capabilities:` field |
| `scripts/sdd/id_ledger.py`, `scripts/sdd/reserve_ids.py` | pattern reference | Pydantic-model + git-tracked-file conventions to follow |
| `scripts/sdd/check_id_collisions.py` | pattern reference | shape for the new standalone `validate_capability_deltas.py` |
| `sdd/WORKFLOW.md` | extends | new section documenting the capability-spec layer, mirroring the existing "Task Index Schema" documentation style |
| `wikitoolkit` (optional, future) | complementary | capability specs are plain Markdown under `sdd/`, so they're automatically eligible for existing wiki ingestion once added — no forced coupling |

---

## Code Context

### User-Provided Code
None — no code snippets were provided during discovery; this brainstorm is
scoped to documents and tooling conventions, not implementation.

### Verified Codebase References

#### Classes & Signatures
```python
# From scripts/sdd/sdd_meta.py:29-92
class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]
    base_branch: str
    # model_validator(mode="after") _hotfix_implies_main  # line 35

def parse(doc_path: Path) -> FlowMeta:  # line 45
    ...

def emit(meta: FlowMeta) -> str:  # line 78
    ...

# From scripts/sdd/id_ledger.py:34-83
class IdLedger(BaseModel):
    next_task_id: int
    next_feature_id: int
    updated_at: str
    updated_by: str

def load_ledger(path: Path) -> IdLedger:  # line 57
    ...

def save_ledger(path: Path, ledger: IdLedger) -> None:  # line 69
    ...

# From scripts/sdd/reserve_ids.py:44-50
class IdReservation(BaseModel):
    kind: str
    first_id: int
    count: int
    ids: list[str]

# From scripts/sdd/check_id_collisions.py:37+
class CollisionReport(BaseModel):
    ...  # one colliding numeric ID + every distinct slug/source using it
```

#### Verified Imports
```python
# Confirmed to work (scripts/sdd/__init__.py exists, package is importable):
from scripts.sdd.sdd_meta import parse, emit, FlowMeta, KNOWN_BRANCHES
from scripts.sdd.id_ledger import IdLedger, load_ledger, save_ledger, LEDGER_PATH, bootstrap_ledger
from scripts.sdd.reserve_ids import IdReservation, IdReservationError
```

#### Key Attributes & Constants
- `scripts.sdd.sdd_meta.KNOWN_BRANCHES` → `frozenset[str]` = `{"main", "staging", "dev"}` (scripts/sdd/sdd_meta.py:26)
- `scripts.sdd.id_ledger.LEDGER_PATH` → `Path("sdd/tasks/.id_ledger.json")` (scripts/sdd/id_ledger.py:28)
- `.claude/commands/sdd-done.md` Step 9 header: `### 9. Integrate Feature Branch (FEAT-145, flow-aware)` (line 206) — the exact insertion point for a new pre-integration merge step.

### Does NOT Exist (Anti-Hallucination)
- ~~`sdd/specs/capabilities/`~~ — does not exist yet; confirmed via `ls sdd/specs/` (all entries are `<feature-slug>.spec.md`, none are capability-named or namespaced under a `capabilities/` subdirectory).
- ~~`scripts/sdd/capability_deltas.py`~~ — does not exist; proposed new module.
- ~~`scripts/sdd/validate_capability_deltas.py`~~ — does not exist; proposed new module.
- ~~Any `## Capability Deltas` section in `sdd/templates/spec.md`~~ — does not exist in the current template (verified by reading the full template; it has Motivation, Architectural Design, Module Breakdown, Test Specification, Acceptance Criteria, Codebase Contract, Implementation Notes, Open Questions, Revision History — no Requirements/Scenario delta format anywhere).
- ~~A `capabilities:` field in the spec frontmatter parsed by `sdd_meta.py`~~ — `FlowMeta` only has `type` and `base_branch`; no capability-related field exists today.

---

## Parallelism Assessment

- **Internal parallelism**: The parser/merge-engine module
  (`scripts/sdd/capability_deltas.py` + its validator) has no dependency on
  the spec-template change and could, in principle, be built and unit-tested
  independently. But the total scope here is small enough (parser + merge
  engine + validator + template section + one new `/sdd-done` step +
  `sdd/WORKFLOW.md` docs) that splitting it across worktrees would add
  coordination overhead without real benefit.
- **Cross-feature independence**: This touches shared, high-traffic files
  (`.claude/commands/sdd-done.md`, `sdd/templates/spec.md`) that other
  in-flight features could also be editing — check `sdd/tasks/index/*.json`
  for any other feature currently modifying either file before starting
  implementation, to avoid a merge-order collision on `/sdd-done`'s own
  command definition.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: the parser, merge engine, and the exact `/sdd-done`
  insertion point are tightly coupled (the merge engine's output shape is
  dictated by what `/sdd-done`'s new step needs to call and report), so
  sequential single-worktree execution avoids a merge-order hazard between
  tasks that would otherwise need to agree on an interface before either is
  done. This mirrors how the ID-ledger work (FEAT-387) reads as one cohesive
  unit rather than parallel slices.

---

## Open Questions

- [ ] Should capability ids be free-form kebab-slugs chosen by the spec
  author, or should a lightweight registry (e.g.
  `sdd/specs/capabilities/_index.json`) exist to prevent typos/duplicates
  the way `check_id_collisions.py` does for TASK/FEAT numbers? — *Owner: TBD*
- [ ] Should `/sdd-spec` be updated to prompt for "Capabilities: new /
  modified" during scaffolding (mirroring OpenSpec's proposal-time
  Capabilities section), or is that deferred to a later increment once the
  merge engine itself is proven? — *Owner: TBD*
- [ ] What should happen when the target capability spec was changed by
  *another* feature that merged into `base_branch` after this feature's
  worktree was created but before this feature's `/sdd-done` runs — retry
  against the fresh state automatically, or hard-fail requiring manual
  reconciliation? — *Owner: TBD*
- [ ] Do we need a `skip_capability_deltas: true` opt-out (mirroring
  OpenSpec's `skip_specs: true`) for pure refactor/tooling FEATs that touch
  no user-visible behavior? — *Owner: TBD*
- [ ] Capability retirement is explicitly gated behind a `retire_capability:
  true` marker per this brainstorm's recommendation — should retirement be
  in the v1 task breakdown at all, or deferred to a fast-follow given it's
  the single riskiest operation in the whole feature? — *Owner: TBD*
- [ ] Should capability specs be namespaced/pathed like OpenSpec's
  `<area>/<capability>` (e.g. `sdd/specs/capabilities/formbuilder/validation.md`)
  for large domains, or flat (`sdd/specs/capabilities/formbuilder-validation.md`)
  matching our existing flat `sdd/specs/*.spec.md` convention? — *Owner: TBD*
