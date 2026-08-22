---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Nightly Snapshot — a soaked, CI-green pointer into `dev`

**Feature ID**: FEAT-443
**Date**: 2026-08-22
**Author**: Jesus Lara
**Status**: draft
**Target version**: (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

The Git Parrot Flow (FEAT-145 + FEAT-187) works for AI-Parrot but degrades
badly as soon as developers who are new to the flow join. In the sibling
repository **fieldsync**, a PR into `dev` approved by mistake — carrying a
feature its author never validated end to end — breaks `dev` for everyone.

The structural gap is that **there is no stable target anywhere in the
topology**. Every branch a validator could point at is either moving
continuously (`dev`) or is a mirror of what already shipped (`main`,
and today also `staging`). A mentor who wants to exercise a feature
end to end has no choice but to check out `dev` and absorb whatever
landed in the last few hours.

Note what this spec does *not* claim to fix. A nightly pointer is
**containment, not prevention**: `dev` keeps breaking at the same rate,
and a broken feature still reaches the pointer once it ages past the soak
window. Preventing the fieldsync failure requires gates on the `PR → dev`
boundary (required status checks, protected `dev`, CODEOWNERS review,
per-PR preview environments). Those are out of scope here and are tracked
in §8. What this spec buys is a target that is **never worse than
yesterday**, plus a changelog that tells the validator what to exercise.

This spec is implemented in AI-Parrot as a proving ground before being
proposed for fieldsync. The two repositories share a stack — `python
run.py` → `navigator.Application(Main)` → `navconfig`, `navigator_auth`,
pgpool, memcache, `BackgroundQueue` — which is what makes the smoke
contract in Module 3 portable between them.

### Goals

- Introduce a long-lived `nightly` ref that always points at a commit of
  `dev` that has **soaked** (default 24h) and has **green CI**.
- Guarantee `nightly` never regresses: on any gate failure the pointer
  stays where it was, so the validator always has a working target.
- Produce, per snapshot, a **differential manifest** listing which
  features entered since the previous snapshot, with their acceptance
  criteria rendered as an actionable test checklist.
- Surface the volume of change that carries **no SDD attribution** as a
  first-class health metric, rather than hiding it.
- Provide a **smoke contract** that is the same command locally and in
  the snapshot job, so "works on my machine" and "the snapshot passed"
  mean the same thing.
- Define the output contract (manifest schema, release tag naming, event
  shape) that the sibling infra spec consumes to deploy `nightly` to the
  k8s `development` environment.

### Non-Goals (explicitly out of scope)

- **No k8s deploy, no image build.** *Resolved during design discussion
  (2026-08-22)*: the deploy lives in a sibling infra spec. This spec ends
  at a moved pointer plus a consumable manifest, release tag, and event.
- **No redefinition of `staging`.** `staging` keeps its FEAT-187
  release-candidate semantics, including being a valid `base_branch` for
  features during a freeze. `nightly` is a separate ref precisely because
  those two models are incompatible (see §2 Overview).
- **No selective feature inclusion.** `nightly` may only point at a commit
  that already exists on `dev`. Cherry-picking a subset of features is
  forbidden by design — it would force divergence, produce conflicts, and
  validate a code combination that exists nowhere else.
- **No chat notification transport.** Slack/Teams delivery was considered
  and not selected for v1; the delivery channels are the repo file, the
  GitHub pre-release, and the app-served endpoint contract. Revisit once
  FEAT-417 (commcenter-notify) lands — tracked in §8.
- **No gates on the `PR → dev` boundary.** Protected `dev`, required
  status checks, and CODEOWNERS are the actual prevention layer and are
  deliberately a separate concern (§8).
- **No changes to `CHANGELOG.md`.** The snapshot manifest is an internal
  "what to test" artifact; `CHANGELOG.md` remains the external "what
  shipped" artifact. They must not be conflated.

---

## 2. Architectural Design

### Overview

`nightly` is a **published pointer, not a working branch**. Four
invariants define it, and every design decision below follows from them:

1. **Subset of `dev`.** `nightly` may only ever point at a commit that is
   already reachable from `origin/dev`.
2. **No inbound writes.** Nobody commits to `nightly`, nobody branches
   from it, nothing is ever merged *into* it.
3. **Monotonic.** A new candidate must have the current `nightly` as an
   ancestor. The pointer never moves backwards.
4. **Freeze on red.** If any gate fails, the pointer does not move. A
   stale-but-working target beats a fresh-but-broken one.

Because of (1) and (2), advancing the pointer is always a fast-forward and
can never conflict. That is the property that makes the whole mechanism
cheap; a model that allowed cherry-picks would lose it immediately.

Selection uses **age plus evidence**, not age alone. Age is a weak proxy
— it only means "nobody complained", which carries signal only if people
actually run `dev`. A green CI run for the exact SHA is direct evidence.
The soak window's real job is narrower: to exclude work merged today,
which was the original requirement.

Topology after this spec:

```
  dev ──(snapshot: soak 24h + CI green + smoke)──► nightly ──(cut)──► staging ──PR──► main
       automatic, nightly                                   manual        release    tag
       [this spec, FEAT-443]                          [sibling spec: sdd-release]  [FEAT-187]
```

`nightly` is deliberately absent from the `sync-down.yml` matrix. It
receives merges from nobody — a hotfix that lands on `main` reaches
`nightly` on the next snapshot, after `sync-down` has brought it to `dev`.
Adding it to that matrix would break invariant (2).

### Component Diagram

```
                    .github/workflows/nightly-snapshot.yml
                    (schedule: nightly + workflow_dispatch)
                                     │
                                     ▼
                     scripts/sdd/snapshot.py  ── the whole algorithm
                                     │
        ┌────────────────┬───────────┴────────────┬──────────────────┐
        ▼                ▼                        ▼                  ▼
   candidate         gate: CI green          gate: smoke        manifest +
   selection         (gh run list)           (pytest -m smoke   changelog
   (soak + first-    per candidate SHA        in clean worktree) (from sdd/ tree,
    parent walk)                                                  NOT git log)
        │                │                        │                  │
        └────────────────┴────────────┬───────────┴──────────────────┘
                                      ▼
                        all gates green?  ──no──► freeze + escalate (Module 7)
                                      │yes
                                      ▼
                      git push origin <sha>:nightly     (fast-forward, always legal)
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
     sdd/nightly/<date>.md    GitHub pre-release       output contract
     (committed to dev)       tag nightly-<date>       (consumed by the
                              body = changelog          sibling infra spec)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts/sdd/sdd_meta.py:26` `KNOWN_BRANCHES` | Modify (additive) | Add `nightly`; simultaneously **reject** it as a `base_branch` for any flow |
| `.github/workflows/ci.yml` | Read-only | Source of the green-CI signal, queried via `gh run list --commit <sha>` |
| `.github/workflows/sync-down.yml` | **No change** | `nightly` deliberately stays out of the matrix (see Overview) |
| `.github/workflows/release.yml:3` `on: release: [created]` | Constraint | Publishes wheels to PyPI on release creation. The nightly pre-release **must not** trigger it — see §7 Known Risks |
| `sdd/tasks/index/<feature>.json` | Read-only | Feature attribution source: `feature_id`, `completed_at`, task list |
| `sdd/tasks/{active,completed}/TASK-*.md` | Read-only | `## Acceptance Criteria` sections become the validator's checklist |
| `pyproject.toml` `[tool.pytest.ini_options]` | Modify (additive) | Register the `smoke` marker (required: `--strict-markers` is on) |
| `run.py`, `app.py` | Read-only | Boot target for the smoke contract |

### Data Models

```python
# scripts/sdd/snapshot.py — Pydantic models (the output contract)

class FeatureEntry(BaseModel):
    """One SDD feature that entered this snapshot."""
    feature_id: str                  # "FEAT-439"
    feature: str                     # "onnx-injection-guardrail-backend"
    title: str                       # from the spec's H1
    spec: str                        # "sdd/specs/<slug>.spec.md"
    completed_at: datetime | None
    task_count: int
    checklist: list[str]             # AC lines harvested from the task files

class UnattributedChange(BaseModel):
    """Commits in the window that map to no FEAT-ID — the health metric."""
    commit_count: int
    subjects: list[str]              # truncated sample for the changelog

class SnapshotManifest(BaseModel):
    """The full contract emitted by one snapshot run."""
    generated_at: datetime
    previous_sha: str                # nightly before the move
    nightly_sha: str                 # nightly after the move
    dev_sha: str                     # origin/dev HEAD at run time
    soak_hours: int
    commits_in_window: int
    features: list[FeatureEntry]
    unattributed: UnattributedChange
    gates: dict[str, Literal["pass", "fail", "skip"]]
    degraded: bool = False           # true when advanced under a relaxed gate
```

### New Public Interfaces

```python
# scripts/sdd/snapshot.py
def select_candidate(soak_hours: int = 24) -> str | None: ...
def build_manifest(previous_sha: str, candidate_sha: str) -> SnapshotManifest: ...
def render_changelog(manifest: SnapshotManifest) -> str: ...
def main(argv: list[str] | None = None) -> int: ...
```

CLI surface (mirrors `reserve_ids.py`, which is the house pattern):

```
python -m scripts.sdd.snapshot [--soak-hours 24] [--dry-run] [--skip-smoke]
                               [--json <path>] [--changelog <path>]
```

`--dry-run` performs every gate and renders the manifest but never moves
the pointer, never commits, and never publishes. It is the mode a human
runs before trusting the automation.

---

## 3. Module Breakdown

**Isolation**: per-spec (one worktree, sequential tasks).

### Module 1: `nightly` ref recognition and base-branch rejection

Add `nightly` to `KNOWN_BRANCHES` in `scripts/sdd/sdd_meta.py:26` so the
SDD commands stop warning about an unknown branch, **and** add an explicit
rejection so no flow can ever use it as `base_branch` — it is a pointer,
not a base. The rejection mirrors the existing `type: feature` +
`base_branch: main` guard. Also creates the `nightly` ref itself
(initially at the current `origin/dev`).

### Module 2: Candidate selection

Walk `origin/dev` first-parent history newest-first; take the first commit
whose committer date is at least `soak_hours` old; verify CI green for
that exact SHA via `gh run list --commit <sha>`; walk further back if red
or if no run exists. Assert monotonicity (current `nightly` is an ancestor
of the candidate). Return `None` when no candidate qualifies.

### Module 3: Smoke contract

Register the `smoke` pytest marker and implement the portable boot
contract, run in a **clean detached worktree at the candidate SHA**:
boot the app object; resolve config through navconfig and assert required
keys are present and non-placeholder; compare the aiohttp route table
against a golden snapshot; bind an ephemeral port, `GET /health` → 200,
then assert clean shutdown within a bounded timeout; check pg/memcache/
redis reachability or skip with an explicit reason.

The full suite also runs at this stage — **not** only the tests belonging
to the features in the window. The risk being managed is a new feature
breaking an old one; the new feature's own tests already ran in its PR.

### Module 4: Manifest and changelog generation

Attribution comes from the SDD tree, not from `git log`:
`git diff --name-only <prev>..<cand> -- sdd/tasks/index/` yields the
features touched in the window; each index header supplies `feature_id`,
`spec`, and `completed_at`; each task file supplies its
`## Acceptance Criteria` lines. Commits in the window that map to no
FEAT-ID are counted into `UnattributedChange`.

The changelog is **differential** against the previous snapshot, renders
the checklist per feature, and always prints the unattributed count.

### Module 5: `/sdd-snapshot` command and scheduled workflow

`.claude/commands/sdd-snapshot.md` wrapping `scripts/sdd/snapshot.py`, and
`.github/workflows/nightly-snapshot.yml` running it on a schedule plus
`workflow_dispatch`.

### Module 6: Delivery

Three channels, all fed from one `SnapshotManifest`:
1. `sdd/nightly/<YYYY-MM-DD>.md` committed to `dev` (source of truth, auditable).
2. A GitHub **pre-release** tagged `nightly-<YYYY-MM-DD>` whose body is the
   changelog — a stable daily URL that needs no repo access.
3. The app-served contract: the manifest JSON is written to a documented
   path so the sibling infra spec can bake it into the image and expose it.
   **This spec defines the path and schema only; it does not serve it.**

### Module 7: Stale escalation

Track consecutive failed runs in a small state file. Day 1: `::notice::`.
Day 2: `::warning::`. Day 3+: `::error::` naming the blocking commit and
the age of the pointer. The pointer is **never** force-advanced.

---

## 4. Test Specification

### Unit Tests

`tests/sdd_scripts/test_snapshot.py` — pure-function coverage over a
synthetic git fixture repo:
- soak boundary: commit at exactly `soak_hours` is eligible; one second
  younger is not
- red CI: candidate is skipped and the walk continues to the next green one
- no eligible candidate: returns `None`, pointer untouched, exit code documented
- monotonicity: a candidate that does not have current `nightly` as an
  ancestor is rejected
- attribution: an index file touched in the window produces a
  `FeatureEntry`; a commit with no FEAT-ID lands in `unattributed`
- changelog is differential: a feature present in the previous manifest
  does not reappear
- AC harvesting tolerates both `- [ ]` and `- [x]` and never treats a
  checked box as evidence of verification

### Integration Tests

- Full `--dry-run` against the real repository: manifest validates against
  the Pydantic model, no ref is moved, nothing is committed.
- Smoke contract executes against `run.py` and reports pass/skip with
  reasons (no live pg/redis required in CI).
- `sdd_meta` rejects `base_branch: nightly` for both `feature` and
  `hotfix`, while `KNOWN_BRANCHES` contains `nightly`.

### Test Data / Fixtures

```python
# tests/sdd_scripts/conftest.py — extend the existing fixtures
# - tmp git repo with a scripted first-parent history and controlled dates
# - fake `gh` on PATH returning scripted run conclusions per SHA
# - minimal sdd/tasks/index/*.json + TASK-*.md pair for attribution tests
```

---

## 5. Acceptance Criteria

- [ ] `nightly` exists on origin and is an ancestor of `origin/dev`.
- [ ] `KNOWN_BRANCHES` contains `nightly`, **and** every SDD command
      rejects `base_branch: nightly` for both flow types.
- [ ] Advancing the pointer is always a fast-forward; the implementation
      contains no cherry-pick, no merge into `nightly`, and no force-push
      to `nightly`.
- [ ] A candidate younger than `--soak-hours` is never selected.
- [ ] A candidate whose CI run for that exact SHA is not green is never
      selected.
- [ ] A candidate that does not have the current `nightly` as an ancestor
      is rejected (monotonicity).
- [ ] On any gate failure the pointer does not move and the run reports
      the failure; `nightly` still points at the last good commit.
- [ ] The full test suite — not a feature-filtered subset — runs against
      the candidate before the pointer moves.
- [ ] `pytest -m smoke` is the same invocation locally and in the job.
- [ ] The changelog is differential: features reported in snapshot N-1 do
      not reappear in snapshot N.
- [ ] Every feature entry renders its acceptance criteria as a checklist.
- [ ] The unattributed-commit count is always present, including when zero.
- [ ] A checked `- [x]` acceptance criterion is never reported as evidence
      that the criterion was verified.
- [ ] `--dry-run` moves no ref, writes no commit, and publishes nothing.
- [ ] The nightly pre-release does **not** trigger `release.yml` / a PyPI
      publish.
- [ ] Three consecutive failures produce an escalated `::error::` naming
      the blocking commit and the pointer's age.
- [ ] `sync-down.yml`'s matrix is unchanged (still `[staging, dev]`).

---

## 6. Codebase Contract

### Verified Existing Files (to be modified)

| File | Lines | Current state |
|---|---|---|
| `scripts/sdd/sdd_meta.py` | 92 total | `KNOWN_BRANCHES` at :26 = `frozenset({"main", "staging", "dev"})`; `class FlowMeta` at :29; `def parse` at :45; `def emit` at :78 |
| `pyproject.toml` | `[tool.pytest.ini_options]` | `addopts = ['--strict-config', '--strict-markers']`; `markers = ['asyncio: …', 'real_llm: …']` — a `smoke` marker MUST be registered or `-m smoke` fails under `--strict-markers` |

### Existing Class Signatures (verified)

```python
# scripts/sdd/sdd_meta.py:26
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})

# scripts/sdd/sdd_meta.py:29
class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]
    base_branch: str
    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta": ...

# scripts/sdd/sdd_meta.py:45
def parse(doc_path: Path) -> FlowMeta: ...
# scripts/sdd/sdd_meta.py:78
def emit(meta: FlowMeta) -> str: ...
```

```python
# scripts/sdd/reserve_ids.py — the house pattern for a git-native SDD script.
# Follow its structure: module docstring, Pydantic result model, _run_git
# helper, _assert_safe_to_reserve preflight, main(argv) -> int with argparse.
class IdReservationError(RuntimeError): ...      # :39
class IdReservation(BaseModel): ...              # :46
def _run_git(...)                                # :55
def _assert_safe_to_reserve(root: Path, base_branch: str) -> None: ...   # :106
def reserve_ids(...)                             # :165
def main(argv: list[str] | None = None) -> int: ...                      # :290
```

### Verified Data Shapes

```jsonc
// sdd/tasks/index/<feature>.json — header keys (verified)
{ "feature": "...", "feature_id": "FEAT-439", "spec": "sdd/specs/....spec.md",
  "type": "feature", "base_branch": "dev",
  "created_at": "...", "completed_at": "2026-08-21T20:16:52+00:00" }

// task entry keys (verified)
["id","slug","title","feature_id","feature","spec","status","priority",
 "effort","depends_on","parallel","parallelism_notes","assigned_to",
 "started_at","completed_at","file","verification"]
```

Measured on the tree at spec time — these numbers justify the design and
should be re-measured, not assumed, during implementation:
- 60/60 of the most recent task files contain a `## Acceptance Criteria` section.
- 276/355 per-spec indexes carry a non-null `completed_at`.
- `verification` is the bare string `"verified"` in 523 task entries and
  `null` in 1911 — it is **not** a structured verification record.
- 27 of the last 40 first-parent commits on `dev` are direct commits, not
  PR merges. The unattributed bucket will be large at first; that is the
  point of measuring it.

### Integration Points (verified)

```yaml
# .github/workflows/release.yml:3  — publishes wheels to PyPI
on:
  release:
    types: [created]
```

```yaml
# .github/workflows/ci.yml:4  — the green signal this spec consumes
on:
  push:
    branches: [main, dev]
  pull_request:
    branches: [main, dev]
```

```yaml
# .github/workflows/sync-down.yml — matrix MUST remain [staging, dev]
strategy:
  matrix:
    target: [staging, dev]
```

### Does NOT Exist (Anti-Hallucination)

Verified absent at spec time — all of these are **created** by this
feature; do not `import` or reference them as if they already exist:

- `scripts/sdd/snapshot.py`, `scripts/sdd/nightly.py`, `scripts/sdd/changelog.py`
- `.github/workflows/nightly.yml`, `.github/workflows/snapshot.yml`
- `.claude/commands/sdd-snapshot.md`, `.claude/commands/sdd-release.md`
- the `sdd/nightly/` directory
- a `smoke` pytest marker (only `asyncio` and `real_llm` are registered)
- the `nightly` branch on origin
- any e2e/integration pytest tier — `pytest -m e2e` currently selects
  nothing. Do not assume an e2e suite exists to call.
- `tests/sdd_scripts/test_snapshot.py`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Model `scripts/sdd/snapshot.py` on `scripts/sdd/reserve_ids.py`:
  module docstring, Pydantic models, a `_run_git` wrapper, an explicit
  preflight assertion, `main(argv) -> int` with argparse. Same house style.
- Google-style docstrings and strict type hints throughout (CLAUDE.md).
- Never shell out to `git` with a mutating command outside the single,
  clearly-named push function — that keeps the invariants auditable in
  one place.
- All heavy work happens in a **detached worktree at the candidate SHA**,
  never in the caller's working tree.

### Known Risks / Gotchas

- **The nightly pre-release must not publish to PyPI.** `release.yml`
  fires on `release: [created]`, which includes pre-releases. Module 6
  MUST either gate `release.yml` on `if: !github.event.release.prerelease`
  or publish the nightly notes through a mechanism that does not create a
  GitHub Release object. This is the single highest-risk interaction in
  the spec — getting it wrong publishes a nightly build to PyPI.
- **Concurrent pushes to `dev` are routine in this repo.** During the
  design session `dev` moved four times in under an hour. The candidate
  SHA must be resolved once and pinned for the whole run; never
  re-resolve `origin/dev` mid-run.
- **`gh run list --commit <sha>` may return no run at all** for a commit
  that was never pushed as a branch tip. Treat "no run" as not-green and
  keep walking, rather than crashing or assuming green.
- **A green CI run is not a green *full* suite.** `ci.yml` runs a matrix
  of package test jobs; confirm which jobs must be green before treating
  the SHA as eligible, rather than accepting any successful run.
- **The unattributed bucket will be large initially** (27/40 measured).
  Do not "fix" this by hiding it or by inventing attribution heuristics —
  its size is the signal. Reducing it is a process change (protected
  `dev`), not a code change.
- **Do not read `verification: "verified"` as proof of anything.** It is a
  free-text string set by hand, absent on 1911 of 2434 task entries.
- **First run has no previous snapshot.** The differential changelog must
  degrade gracefully: bootstrap `previous_sha` to the initial `nightly`
  position and say so in the manifest.
- **Clock skew and timezones.** Committer dates in this repo appear in
  several offsets (`+02:00`, `-03:00`, `-04:00`). Compare in UTC.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `gh` CLI | already used by `sync-down.yml` | CI-run status query and pre-release creation |
| `pydantic` | already in tree | manifest models |
| `pyyaml` | already in tree | frontmatter parsing via `sdd_meta` |

No new Python dependencies.

---

## 8. Open Questions

- [x] Does the k8s `development` deploy live in this spec? — *Resolved
  during design discussion (2026-08-22)*: no. Sibling infra spec. This
  spec ends at pointer + manifest + release tag + output contract.
- [x] How does the changelog reach the validator? — *Resolved during
  design discussion (2026-08-22)*: three channels — a versioned file at
  `sdd/nightly/<date>.md`, a GitHub pre-release tagged `nightly-<date>`,
  and a documented manifest path the deployed app serves. Chat
  notification was considered and deferred.
- [x] Stale policy when the snapshot fails repeatedly? — *Resolved during
  design discussion (2026-08-22)*: escalate by consecutive-failure count
  (notice → warning → error naming the blocking commit and the pointer
  age). Never force-advance the pointer.
- [x] Default soak window? — *Resolved during design discussion
  (2026-08-22)*: 24h, configurable. A one-week window was rejected: it
  leaves every release stale by a week and forces debugging of code from
  seven days back while `dev` has moved hundreds of commits.
- [x] Reuse `staging` for this instead of a new ref? — *Resolved during
  design discussion (2026-08-22)*: no. FEAT-187 `staging` accepts commits
  of its own (features may base on it during a freeze), which is
  incompatible with the pointer model.
- [x] Should `nightly` join the `sync-down.yml` matrix? — *Resolved during
  design discussion (2026-08-22)*: no. It receives merges from nobody; a
  hotfix reaches it via `dev` on the next snapshot.
- [ ] Which subset of `ci.yml` jobs constitutes "green" for eligibility —
  all matrix legs, or a named required set? — *Owner: Jesus Lara*.
  Decide during Module 2 implementation.
- [ ] Should `dev` be protected (no direct pushes, required status checks)
  as the actual prevention layer? This is the fix for the fieldsync
  failure that the nightly pointer only contains. — *Owner: Jesus Lara*.
  Separate spec; blocks nothing here.
- [ ] Chat delivery once FEAT-417 (commcenter-notify) lands — should the
  escalation alerts route there? — *Owner: Jesus Lara*.
- [ ] Does fieldsync need the identical manifest schema, or a profile of
  it? Decide when porting; do not prematurely factor a shared package —
  duplicate the script first. — *Owner: Jesus Lara*.

---

## Worktree Strategy

- **Isolation unit**: per-spec. All tasks run sequentially in one worktree.
- **Rationale**: Modules 2, 4, and 6 all converge on
  `scripts/sdd/snapshot.py` and the `SnapshotManifest` model; running them
  in parallel worktrees would conflict on the same file constantly.
- **Cross-feature dependencies**: none blocking. FEAT-187
  (`git-parrot-flow`) is already merged and its `sync-down.yml` repair
  landed on `dev` in commit `86ac5633e`.
- **Downstream**: the sibling `sdd-release` spec consumes `nightly` and
  the manifest; it should not start until Modules 1, 4, and 6 are merged.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-08-22 | Jesus Lara | Initial spec (FEAT-443) |
