---
type: feature
base_branch: dev
---

# Feature Specification: Deterministic complexity routing for SDD tasks

**Feature ID**: FEAT-561
**Date**: 2026-09-16
**Author**: Codex, from requirements by Jesus Lara
**Status**: draft
**Target version**: Next SDD tooling release

Source: direct feature request by Jesus Lara. Initial thresholds are proposed
policy for approval; they are not empirically calibrated model rankings.

## 1. Motivation & Business Requirements

### Problem Statement

The sdd-worker → sdd-coder cycle currently distributes tasks by rotating
roster position. It does not measure the complexity of existing code,
dependency reach, scope, acceptance criteria or downstream task count.
An LLM deciding that a task is easy can therefore select a weaker coder
without reproducible evidence. A later retry can also choose an unsuitable
model even if the initial selection was appropriate.

### Goals

- Measure all five requested signal families before dispatch.
- Make classification a pure, deterministic, versioned policy with evidence.
- Route complex tasks exclusively to configured `gpt-5.6-terra` or `sonnet-5`
  candidates, including retries and native preparation.
- Preserve normal scheduling constraints, scope fidelity and human review.
- Expose missing evidence and explain every classification and routing decision.

### Non-Goals

- Predicting implementation complexity of code that does not exist yet.
- Claiming these metrics eliminate all selection bias or prove either model's superiority.
- Asking an LLM to score difficulty, rewrite thresholds, or select evidence.
- Training a classifier, modifying provider clients, or installing Radon.
- Changing dependency ordering, implementing FEAT-559 suspensions, or changing
  the separate writer_generate/writer_apply delegation protocol.

## 2. Architectural Design

### Overview

`coder_plan` collects evidence from the task artifact, per-spec index,
existing target files and structural wiki. A pure evaluator classifies each
task. The assigner intersects the required model set with available seats.
Before each actual dispatch the engine validates the evidence fingerprint
and the selected model. The worker reports the decision; it cannot override it.

```text
Task + index + existing files + wiki blast
                   ↓
          measured evidence snapshot
                   ↓
       versioned deterministic evaluator
                   ↓
     model eligibility ∩ available roster
                   ↓
        chunk → preflight → attempt
                   ↓
           audit + review outcomes
```

### Measurement contract

No inputs come from title adjectives, estimated effort, an LLM's confidence,
coder feedback, selected model or eventual task outcome.

1. **Cyclomatic complexity:** inspect every existing Python file declared
   MODIFY. Run the installed Ruff asynchronously with isolated configuration,
   C901 only, max-complexity 0, no cache, no fixes and `--ignore-noqa`, JSON
   output and explicit file arguments. This extracts existing function
   complexities independently of repository suppressions and exclusions.
   Record per-function values and per-file maximum; score the maximum over
   MODIFY files. C901 diagnostics are successful measurements, not tool
   failures. Ruff exit 2, malformed output or syntax errors make the affected
   measurement unknown. A separate syntax-only Ruff pass distinguishes an
   empty valid module from unparseable Python. No functions gives known zero;
   CREATE gives not_applicable, never a measured zero. Unsupported source
   languages give unknown. Documentation/configuration gives not_applicable.
   Record the Ruff version and invocation; parser fixtures pin its output contract.
2. **Blast radius:** use exact `sym:<repo-relative-path>#<qualname>` identifiers
   listed in a machine-readable Complexity Contract that accompanies and
   agrees with the task's verified Codebase Contract. Resolve every declared
   existing symbol, including references outside MODIFY files. Collect
   `wikitoolkit symbols blast <id> --depth 2 --no-inferred --tests --json`
   against the feature checkout. Count the union of impacted symbol IDs and
   paths, excluding roots, and retain each root's raw result. Explicitly
   report this as a depth-two static graph estimate, not all runtime users.
   Missing roots, failed queries, stale results or truncation are unknown,
   with the observed count retained as a lower bound. An explicitly empty
   symbol list for a task with no existing symbol references is not_applicable;
   an absent list is unknown. Querying only selected low-impact roots is invalid.
3. **Scope:** count unique normalized task paths, CREATE and MODIFY separately.
   Module identity is the repo-relative parent directory, an objective proxy
   for breadth; root-level files belong to `.`. Count all declared files,
   including tests and documentation. CREATE weight is 1; MODIFY weight is 2.
   Reject duplicate conflicting actions, globs, escaping paths and symlinks
   outside the checkout. Missing MODIFY targets or existing CREATE targets
   invalidate the contract and block dispatch; do not silently change action.
4. **Acceptance criteria:** count top-level checkbox criteria in the task's
   Acceptance Criteria section, checked or unchecked, excluding fenced code
   and nested explanatory bullets. Missing/malformed sections are unknown.
   Count the task's criteria, not the entire feature spec's criteria.
5. **Downstream tasks:** from the complete per-spec index count distinct direct
   dependents and distinct transitive descendants, regardless of status.
   Deduplicate diamond paths; exclude the task itself. Missing nodes or
   cycles invalidate the dependency contract. The score uses transitive count;
   direct count remains visible. This deliberately does not count prerequisites.

The Complexity Contract contains `schema_version: 1`, normalized
`targets: [{path, action}]`, and `contract_symbols: [symbol_id]`.
It stores declarations, not a hand-authored score. The parser must compare
its targets with Files to Create / Modify, and preserve provenance to the
Codebase Contract for every symbol. SDD task authors/reviewers own completeness;
the evaluator cannot certify that a human omitted no relevant dependency.
Legacy tasks without this section remain parseable but yield unknown symbol
coverage and therefore require the complex-task route until upgraded.

### Initial policy v1

These are explicit initial policy choices for review, not calibrated findings.
Comparison is inclusive. Each row contributes at most two points.

| Signal | 0 points | 1 point | 2 points |
|---|---|---|---|
| Maximum existing cyclomatic complexity | 0–10 | 11–20 | ≥21 |
| Distinct impacted symbols, depth 2 | 0–9 | 10–29 | ≥30 |
| Weighted file scope, CREATE + 2×MODIFY | 0–3 | 4–7 | ≥8 |
| Distinct parent directories | 0–1 | 2 | ≥3 |
| Task acceptance criteria | 0–4 | 5–7 | ≥8 |
| Transitive downstream tasks | 0–1 | 2–4 | ≥5 |

Classify **complex** if total ≥5, maximum complexity ≥21, blast count ≥30,
or downstream task count ≥5. Otherwise classify **standard** when all
applicable measurements are available. Any unknown applicable signal yields
**unknown**, unless observed evidence already proves complex. Both complex
and unknown require the strong-model allowlist. Not_applicable contributes
zero points with its reason preserved. Never turn an unavailable tool into
a fabricated zero. Invalid task structure blocks rather than classifies.

Thresholds and allowlist live in validated configuration, versioned and
hashed with the evidence. No automatic tuning or per-task LLM overrides.
Changing policy requires a new policy version and invalidates cached plans.

### Models and dispatch rules

The requested two-model candidate list is:

| Candidate model | Intended seat |
|---|---|
| `gpt-5.6-terra` | MCP seat backed by the existing Codex dispatcher |
| `sonnet-5` | Explicitly configured Claude seat, or native seat where the host supports that exact model |

This is an operator policy allowlist, not a provider availability assertion.
Do not silently equate `sonnet`, `haiku` or another alias with `sonnet-5`.
An explicit operator-maintained identity mapping may connect a canonical
candidate to a provider's exact deployed model ID; retain both identities.
Unrecognized identity or unsupported model blocks that candidate.

- Standard tasks retain the configured roster rotation behavior.
- Complex/unknown tasks may use only a matching, available model. Apply
  any execution-pool suspension exclusions before selecting a seat.
- Preserve sorted task ordering, exclusive tasks and one seat per chunk.
  When an eligible seat is already used, close that chunk and continue in
  another chunk; never fill the gap with an ineligible coder.
- No matching available seat produces a per-task `complex_model_unavailable`
  routing block. Other ready tasks can continue. Distinguish this from a
  dependency block and from a transient seat already occupied in a chunk.
- Probe fallbacks, retry_seat and native preparation apply the same model
  restriction. A failed strong coder cannot retry through a weak seat.
- Validate the effective dispatch profile model before invocation; preserve
  configured and reported resolved model identity in attempt telemetry.
  Never leave a model empty and rely on a provider default for this route.
- The worker's current self-implementation/fallback instructions must not
  bypass a complex/unknown block. It reports the block and waits for an
  eligible model/configuration instead of implementing on an unspecified model.

### Snapshot and audit

`ComplexityAssessment` contains task ID, schema/policy versions, classification,
total and component points, reason codes, raw metric states/values, collector
versions, task/index/policy hashes, repository HEAD, target content hashes,
wiki evidence hashes, and an assessment ID (SHA-256 of canonical JSON).
Timestamp metadata is outside the deterministic assessment hash.

Persist assessments under
`artifacts/sdd-coder/complexity/<feature-id>/<task-id>/<assessment-id>.json`
in the feature checkout before dispatch; an audit write failure blocks that
task. Attempt records refer to the assessment ID and record selected model.
Do not commit runtime artifacts automatically or let the coder alter them.

Recompute measurements at planning; never cache a wiki result across plans.
Before dispatch, revalidate task/index/policy/target hashes and HEAD. A
change returns `complexity_plan_stale` and requires replanning rather than
silently changing an already displayed assignment. Validate native tasks
before allocating their worktree. Bind evidence to the feature checkout,
not a different worktree's files. Wiki results lack a complete graph revision
token today: record this limitation; do not claim atomic graph snapshots or
that refreshing a root proves all callers are up to date.

### Data models and new interfaces

New Pydantic models in `sdd_coder/complexity_models.py`:

- `ComplexityPolicy`: version, thresholds, ordered model identities and bounds.
- `ComplexityContract`: schema version, targets and existing contract symbol IDs.
- `ComplexityEvidence`: states `ok|unknown|not_applicable`, values, sources and hashes.
- `ComplexityAssessment`: immutable evidence, points, classification and reasons.
- `ComplexityBlock`: task ID, assessment ID, error code and diagnostic details.

Proposed interfaces (new, not existing API):

```python
def parse_complexity_contract(task_text: str) -> ComplexityContract:
    """Validate declarations against task sections; raise on contradictions."""

async def collect_complexity(worktree: Path, task_file: Path, index_path: Path,
                             policy: ComplexityPolicy) -> ComplexityEvidence:
    """Collect bounded pre-dispatch measurements without provider calls."""

def evaluate_complexity(evidence: ComplexityEvidence,
                        policy: ComplexityPolicy) -> ComplexityAssessment:
    """Return a deterministic, model-independent classification."""

def eligible_seats(assessment: ComplexityAssessment, seats: list[RosterSeat],
                   policy: ComplexityPolicy) -> list[RosterSeat]:
    """Filter available seats without overriding availability or suspension."""
```

`RosterConfig` gains a policy field; `SddCoderToolkit.__init__` accepts matching
configuration for its list-roster path. `PlannedTask` and `AttemptRecord` gain
assessment references, `CoderPlan` gains assessments and routing blocks.
New fields permit reading older serialized reports; new dispatches must
always have a current assessment. New error codes:
`complexity_contract_invalid`, `complexity_plan_stale`,
`complex_model_unavailable`, `complexity_audit_failed`.

## 3. Module Breakdown

Paths below use `CORE = packages/ai-parrot/src/parrot/flows/dev_loop` and
`TESTS = packages/ai-parrot/tests/flows/dev_loop` only as documentation shorthand.

| Module | Files and responsibility | Depends on |
|---|---|---|
| M1 | CREATE `CORE/sdd_coder/complexity_models.py`, `complexity.py`; models, contract parser, pure evaluator | Existing Pydantic |
| M2 | CREATE `CORE/sdd_coder/complexity_collectors.py`; asynchronous Ruff/wiki collection, counts and fingerprints | M1 |
| M3 | MODIFY `CORE/sdd_coder/models.py`, `roster.py`, `engine.py`, `toolkit.py`; route, revalidate, persist, guard retries/native paths | M1–M2 |
| M4 | MODIFY `sdd/templates/task.md`, `.claude/commands/sdd-task.md`, `.agents/skills/sdd-task/SKILL.md`, both worker prompt copies, `examples/sdd-coder-mcp.yaml`, `docs/dev_loop/sdd-coder-orchestrator.md`; emit contracts and explain blocking/model policy | M1–M3 |
| M5 | CREATE `TESTS/sdd_coder/test_complexity.py`, `test_complexity_collectors.py`, `test_complexity_routing.py`; update affected existing roster/engine/model/toolkit tests | M1–M4 |

Worker prompt copies are `.claude/agents/sdd-worker.md` and
`CORE/_subagent_data/sdd-worker.md`; they must remain byte-identical.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 | yes, after spec approval | Pydantic models; versioned additive scoring; explicit unknown/invalid semantics | — |
| M2 | yes, after spec approval | Exact scoped inputs; Ruff C901; depth-two deduplicated graph; async bounded subprocesses | — |
| M3 | no at this draft stage | All dispatch paths must share eligibility; named additive response fields/errors | Must reconcile FEAT-559 implementation state and finalize changed method signatures in task contracts |
| M4 | yes, after spec approval | Declarative task contract; two configured candidates; no worker override; prompt parity | — |
| M5 | yes, after spec approval | Boundary and adversarial matrix below, fixture-driven without live model calls | — |

### Worktree Strategy

Isolation: **per-spec**, from `dev`. Implement in one feature worktree after
approval/decomposition. M3 owns shared dispatch integration; do not run
multiple tasks editing engine/roster/models concurrently. Coordinate with
FEAT-559 (`sdd-coder-execution-pool-suspensions`), whose approved design
overlaps the same files. Task decomposition must reverify the then-current
contracts and preserve its execution-scoped eligibility exclusions.

## 4. Test Specification

| Area | Required cases |
|---|---|
| Scoring | Every threshold at n−1/n/n+1; total 4/5; each hard trigger; same evidence/policy gives identical result; input permutations do not change counts/hash |
| Independence | Changing title/effort/model preference or injecting “this is easy” does not change assessment |
| Scope | CREATE-only, MODIFY-only, mixed, tests/docs; duplicate paths; directory normalization; escaping paths; action/existence mismatch |
| Ruff | Existing complex function, trivial function, empty valid module, syntax error, noqa suppression, tool timeout/missing binary, malformed JSON, unsupported language |
| Blast | Multiple roots sharing callers; direct/transitive overlap; missing root; stale/truncated output; inferred edges excluded; tests included; failed CLI; no applicable symbols versus missing contract |
| Criteria and DAG | Nested/fenced checkboxes excluded; checked criteria counted; missing section; diamond graph; direct versus descendants; completed descendants; cycle and dangling task IDs |
| Routing | Standard rotation unchanged; complex/unknown only strong candidates; one eligible seat/multiple tasks; exclusive tasks; no strong candidate without starvation of standard tasks |
| Bypass prevention | Probe fallback to weak model, MCP retry, native preparation, worker fallback, aliases and omitted model; no forbidden dispatch invocation occurs |
| Freshness/audit | Modified task/index/policy/target/HEAD invalidates plan; no worktree allocated on stale native request; persistence failure; deterministic assessment IDs; attempt references survive retry |
| Compatibility | Old reports deserialize; new dispatch cannot skip assessment; existing toolkit envelope and scheduler tests pass; worker prompt parity |

Use tiny synthetic Python files, fixture wiki JSON and a temporary local Git
repository. Stub dispatchers to inspect requested model identity; no live
provider calls or remote wiki required for deterministic tests. Run targeted
SDD coder tests, prompt parity, affected SDD contract tests, black and ruff.
Store test logs under `artifacts/logs/`.

## 5. Acceptance Criteria

- [ ] AC1: Before any coder starts, all five signal families are recorded with provenance and state.
- [ ] AC2: The versioned v1 policy and every threshold boundary pass deterministic tests.
- [ ] AC3: No LLM judgment, task title or model outcome enters the evaluator.
- [ ] AC4: CREATE/MODIFY, breadth, criteria and downstream counts follow the exact definitions above.
- [ ] AC5: Blast results deduplicate callers and distinguish missing/stale/truncated data from zero impact.
- [ ] AC6: Unknown evidence routes conservatively; invalid structure blocks with a specific diagnostic.
- [ ] AC7: Complex/unknown tasks dispatch only to available configured identities for `gpt-5.6-terra` or `sonnet-5`.
- [ ] AC8: Probe fallback, retries, native preparation and worker self-implementation cannot bypass AC7.
- [ ] AC9: Unavailable strong candidates block affected tasks explicitly while independent eligible work continues.
- [ ] AC10: Every attempt references persisted evidence; stale evidence requires replanning before dispatch.
- [ ] AC11: Standard rotation, dependency ordering, exclusive semantics, fidelity and review remain valid.
- [ ] AC12: Task generation emits the measurement contract; legacy tasks remain readable with conservative routing.
- [ ] AC13: Worker prompt copies remain identical; docs describe thresholds, availability and graph limitations.
- [ ] AC14: Targeted tests and existing affected regression suites pass; no new dependency or direct provider SDK call is introduced.

## 6. Codebase Contract

Verified against HEAD `833c92168e352aef1abf8913b65dbcf6c0b5d0f3`.
Source contracts are unchanged from the initial research commit
`9c167eeaa7b17b6e84886c32eacf081c154e0f9d` (only `.gitignore` changed).
Reverify references before task decomposition.

### Verified definitions and imports

These definitions were verified by reading source; no runtime import smoke
test of the full engine was run during specification research.

```python
from parrot.flows.dev_loop.task_scheduler import TaskRef, TaskScheduler
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, PlannedTask, CoderPlan
from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner, available_seats
```

| Existing contract | Verified source |
|---|---|
| `TaskRef.depends_on: List[str]`, `file: str`, `parallel: bool` | `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:32` |
| `TaskScheduler.from_index_file(cls, path: Path) -> Optional[TaskScheduler]` | Same file, line 104 |
| `RosterSeat`: label, kind, optional backend, model, fallback_model | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:45` |
| `RosterConfig`: seats, wait/smoke bounds, lint, feedback | Same file, line 116 |
| `PlannedTask`: task_id/task_file/title/seat_label/native/backend/model | Same file, line 138 |
| `CoderPlan`: feature metadata, pending/blocked, chunks, roster, orphan_branches | Same file, line 167 |
| `available_seats(roster, results)` substitutes probed model_used | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py:115` |
| `ChunkAssigner.assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]` | Same file, line 134 |
| `ChunkAssigner.retry_seat(self, failed_label: str, exclude: Set[str]) -> Optional[RosterSeat]` excludes native seats | Same file, line 169 |
| `SddCoderEngine.plan(self, feature: str, worktree: str) -> CoderPlan` | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:457` |
| `_cached_plan` currently caches by feature ID without complexity evidence | Same file, line 490 |
| `prepare_native(self, feature: str, worktree: str, task_id: str) -> NativePrep` currently defaults empty model to haiku | Same file, line 512 |
| `_run_task` invokes retry_seat after failed attempt | Same file, line 1057; retry call line 1091 |
| `run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderJob` | Same file, line 1138 |
| `SddCoderToolkit.__init__` converts list roster to RosterConfig | `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:56` |
| `symbols_blast` has depth/inferred/tests/JSON options | `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2243` |
| `BlastRadiusOutput`: root, impacted, files, truncated | `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py:91` |
| `StructuralService.blast_radius(self, symbol: str, *, relations: list[str] \| None = None, depth: int = 2, include_inferred: bool = True, include_tests: bool = True) -> BlastRadiusOutput` | Same file, line 287 |
| Root refresh only; reverse traversal; node cap; missing root returns empty data with root=None | Same file, lines 314–359 |
| Worker uses server plan and prepared native model | `.claude/agents/sdd-worker.md:222` |

### Integration Points

Collector/evaluator run before `ChunkAssigner.assign`; retry selection gains
the same eligibility predicate. Cache validation runs before run_chunk and
prepare_native side effects. Toolkit passes policy through both supported
roster configuration forms. Worker displays server assessments and respects
routing blocks. No changes to `clients/base.py` are required.

### Does NOT Exist (Anti-Hallucination)

- `sdd_coder/orchestrator.py`: the implementation is `engine.py`.
- Existing `ComplexityAssessment`, complexity evaluator or model-eligibility
  fields in the inspected roster/plan models: these are proposed additions.
- A graph revision token in `BlastRadiusOutput`, or a guarantee that root
  refresh updates every caller: neither is provided by the current service.
- A strong-model pair in the shipped example roster: its current candidates
  are qwen, gemini, codex-spark and haiku.
- A numeric cyclomatic-complexity metric derived from CREATE file contents:
  those contents do not exist before dispatch.

## 7. Implementation Notes & Constraints

Use existing Pydantic v2, pathlib, hashlib, JSON and async subprocess support.
Ruff is already declared in the core development dependencies
(`packages/ai-parrot/pyproject.toml:792`); Radon is not required.
Do not use synchronous subprocesses in async collectors. Pass arguments as
arrays without a shell and pin the working directory. Bound each collector
to 30 seconds and 8 MiB captured output; exceeding either produces unknown
evidence with diagnostics, not a fallback zero. Bound simultaneous collectors
to four; cancellation must terminate and reap their processes.

The task artifact is the declarative source. Reject conflicting duplicated
scope declarations. Existing effort estimates remain informational only.
Classifying based on the maximum across MODIFY files intentionally catches
hot spots even when the proposed edit is small; expect some over-routing.
Directory breadth and checklist count are proxies and can be affected by
task authoring style. Calibration must use later held-out tasks and recorded
outcomes; never retroactively relabel a dispatch to make its model look better.

External dependencies: none added. Existing wiki CLI/service and Ruff are
runtime measurement prerequisites; their absence has defined unknown semantics.

## 8. Open Questions

- [x] Signals and timing: the five user-requested families, before dispatch.
- [x] Candidate list: `gpt-5.6-terra` and `sonnet-5`, as requested.
- [x] Unknown evidence: conservative model routing with explicit diagnostics.
- [x] Initial threshold policy: explicit v1 proposal in §2, reviewable with this draft.
- [x] Operational Git prerequisite: clean checkout verified; `dev` synchronized
  with `git pull --ff-only origin dev`; FEAT-561 reserved by the repository allocator.
- [ ] Before task decomposition: reconcile actual FEAT-559 integration state
  and freeze M3's changed signatures — spec/task author.
- [ ] Before deployment: configure exact supported model identities for the
  chosen host; missing candidates remain visibly blocked — operator.

## 9. Design Research Cross-Check

Status: skipped. Input is a direct feature request with no prior accepted
brainstorm/proposal; no independent reviewer was invoked. Findings above
come from repository/wiki research and must not be presented as independent review.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-16 | Codex | Initial specification with verified contracts and reserved FEAT-561 identity |
