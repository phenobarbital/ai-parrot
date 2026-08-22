---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: `/sdd-release` — promote a soaked snapshot into a release candidate and on to `main`

**Feature ID**: FEAT-444
**Date**: 2026-08-22
**Author**: Jesus Lara
**Status**: draft
**Target version**: (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-187 introduced `staging` as the release-candidate branch and then
deliberately left its operation manual. Its §8 records the gap as an open
question owned by Jesus Lara:

> *Should we add `/sdd-release-cut` as a follow-up command to automate
> `git checkout staging && git merge --ff-only dev && git push` with safety
> checks (working-tree-clean, no in-flight PRs targeting `staging`, etc.)?*

Two years of flow evidence say the answer is yes, and that the sketch in
that question is subtly wrong in one place: **the cut should come from
`nightly`, not from `dev` HEAD.** Cutting from `dev` reproduces exactly the
problem FEAT-187 set out to solve — the release candidate becomes
"whatever happened to be on `dev` at the moment somebody typed the
command", including work merged minutes earlier. Cutting from `nightly`
(FEAT-443) means the RC starts from a commit that has already soaked,
already passed CI, already passed smoke, and has already been deployed and
exercised in the `development` environment.

The manual procedure has also never actually run. Measured at spec time,
`staging` has **0 commits of its own** relative to both `main` and `dev` —
it has only ever been fast-forwarded from `main` by `sync-down.yml`. It
has never been cut from `dev`, never stabilized an RC, never received a
freeze fix. So this spec is not automating a well-worn path; it is
defining the path for the first time, and must be conservative about it.

### Goals

- Automate the **cut**: promote the current `nightly` commit into
  `staging`, gated by safety checks that refuse rather than force.
- Automate the **promotion**: open the `staging → main` PR that carries
  the release.
- Assemble the release notes for free by concatenating the FEAT-443
  nightly manifests that fall between the last release tag and the RC,
  producing a `--notes-file` for the existing release machinery.
- Report **what is in the RC** — features, and the unattributed-change
  count — so the freeze decision is informed.
- Close the FEAT-187 §8 open question explicitly.

### Non-Goals (explicitly out of scope)

- **No version bumping, tagging, or PyPI publishing.** `/release` and
  `scripts/release.py` already own all of that across the 11 workspace
  distributions, including the `ai-parrot>=` pin lockstep and the
  `navrules` three-file version. `/sdd-release` promotes branches and
  hands `/release` a notes file. Duplicating that machinery is forbidden.
- **No automated stabilization.** The freeze period — QA, fixes, the
  go/no-go call — is human. This spec provides `status` visibility, not
  judgment.
- **No force-push to `staging` or `main`, ever.** The cut is a merge, not
  a re-point. See §7 for why the "re-create staging at the nightly SHA"
  alternative was rejected.
- **No change to `nightly` semantics.** `/sdd-release` reads `nightly`;
  it never writes to it.
- **No new SDD flow type.** FEAT-187 already resolved that releases are
  operational, not feature-bearing. Unchanged here.

---

## 2. Architectural Design

### Overview

`/sdd-release` is a three-verb command over the promotion path. It owns
branch topology only; everything downstream of the tag is delegated.

```
 nightly ──(1) cut──► staging ──[human freeze: QA + fixes]──► (3) promote ──PR──► main
   ▲                    │                                                          │
   │ FEAT-443           │ (2) status: what's in the RC                             │ /release
   │                    │                                                          ▼
  dev ◄─────────────────┘ freeze fixes MUST be back-merged           bump + tag + GitHub Release
        (mandatory, see §7)                                                  └──► release.yml ──► PyPI
```

**Verb 1 — `cut`.** Advance `staging` to the current `nightly` commit.
Fast-forward when `staging` is an ancestor of `nightly`; a real merge
otherwise (which is the normal steady state — see §7). Refuses on any
failed gate.

**Verb 2 — `status`.** Read-only. Reports the RC contents: which features
entered since the last release tag, the unattributed-commit count, how
stale `nightly` is, and whether any freeze fix on `staging` is missing
from `dev`.

**Verb 3 — `promote`.** Open the `staging → main` PR with the assembled
notes as its body, and write the notes file that `/release` will pass to
`scripts/release.py gh-release --notes-file`.

The command deliberately stops at the PR. Merging it is a human act
subject to branch protection, and the tag that follows is `/release`'s job.

### Component Diagram

```
              .claude/commands/sdd-release.md
                          │
                          ▼
            scripts/sdd/release_flow.py
                          │
        ┌─────────────────┼──────────────────┬────────────────────┐
        ▼                 ▼                  ▼                    ▼
   cut gates         status report      notes assembly       promote
   - tree clean      - features in RC   - read manifests     - gh pr create
   - on a known      - unattributed       from sdd/nightly/    staging -> main
     branch            count              between last tag   - body = notes
   - nightly not     - nightly age        and RC             - writes
     stale           - unbackmerged     - dedupe features      .release-notes.md
   - no in-flight      freeze fixes       across snapshots
     PRs -> staging
   - staging has no
     commits missing
     from dev
                          │
                          ▼
        delegates to: /release  ->  scripts/release.py
                      (bump, tag, gh-release --notes-file)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `nightly` ref (FEAT-443) | Read-only | Source of the cut. Never written. |
| `sdd/nightly/<date>.md` manifests (FEAT-443) | Read-only | Raw material for the release notes |
| `scripts/release.py:323` `cmd_gh_release` | Delegate | Accepts `--notes-file`; this is the seam between the two commands |
| `.claude/commands/release.md` | Delegate | Already gates on HEAD being `dev`/`staging`/`main`, so running it on `staging` is supported today |
| `.github/workflows/sync-down.yml` | Constraint | After the release merges into `main`, it propagates back to `staging` and `dev`. Its matrix stays `[staging, dev]` |
| `scripts/sdd/sdd_meta.py:26` `KNOWN_BRANCHES` | Read-only | `staging` already present; `nightly` added by FEAT-443 |

### Data Models

```python
# scripts/sdd/release_flow.py

class CutGate(BaseModel):
    """One safety gate evaluated before the cut."""
    name: str
    passed: bool
    detail: str

class ReleaseCandidate(BaseModel):
    """What `status` reports and `promote` publishes."""
    staging_sha: str
    nightly_sha: str
    last_release_tag: str | None
    nightly_age_hours: float
    features: list[FeatureEntry]        # reused from FEAT-443
    unattributed_commits: int
    unbackmerged_staging_commits: list[str]   # freeze fixes missing from dev
    gates: list[CutGate]
```

`FeatureEntry` is imported from the FEAT-443 module rather than
redefined — this is a hard dependency, not a copy.

### New Public Interfaces

```python
# scripts/sdd/release_flow.py
def evaluate_cut_gates() -> list[CutGate]: ...
def cut(dry_run: bool = False) -> int: ...
def build_candidate() -> ReleaseCandidate: ...
def assemble_notes(candidate: ReleaseCandidate) -> str: ...
def promote(dry_run: bool = False) -> int: ...
def main(argv: list[str] | None = None) -> int: ...
```

```
python -m scripts.sdd.release_flow cut     [--dry-run] [--force-stale]
python -m scripts.sdd.release_flow status  [--json]
python -m scripts.sdd.release_flow promote [--dry-run] [--notes-out <path>]
```

`--force-stale` is the single documented override, and it only relaxes the
"nightly is too old" gate. No flag relaxes tree-cleanliness, the
back-merge gate, or the in-flight-PR gate.

---

## 3. Module Breakdown

**Isolation**: per-spec (one worktree, sequential tasks).

### Module 1: Cut gates

Implement `evaluate_cut_gates()`. Every gate returns a `CutGate` with a
human-readable `detail`; the cut proceeds only when all pass:
- working tree clean, and HEAD is not inside a worktree
- `origin/nightly` exists and its age is within the freshness threshold
- no open PR targets `staging` (an in-flight PR would be silently rebased
  under its author)
- `staging` has no commits that are missing from `dev` — i.e. every freeze
  fix from the previous cycle was back-merged. **This is the gate that
  prevents the divergence spiral**; see §7.

### Module 2: The cut

Advance `staging` to `origin/nightly`: fast-forward when possible,
otherwise a real merge with a conventional message. Push. Never force.
On a merge conflict, abort cleanly and report which files conflicted —
a conflict here always means Module 1's back-merge gate was bypassed or
a freeze fix was made outside the flow.

### Module 3: Status report

Build and render a `ReleaseCandidate`: features between the last release
tag and `staging`, the unattributed count, `nightly` age, and any
unbackmerged `staging` commits. `--json` for machine use.

### Module 4: Notes assembly

Read the FEAT-443 manifests in `sdd/nightly/` whose `nightly_sha` falls
between the last release tag and the RC. Concatenate, **deduplicate
features across snapshots** (a feature reported in one nightly must not
repeat), and render a release-notes body. Write it to a file suitable for
`scripts/release.py gh-release --notes-file`.

This is the external "what shipped" artifact and is written in that
register — not the internal "what to test" checklist the nightly manifest
carries.

### Module 5: Promote

Open the `staging → main` PR with the assembled notes as its body, guarded
against opening a duplicate. Print the exact `/release` invocation the
maintainer should run after the PR merges. Never merges the PR itself.

### Module 6: Command surface and docs

`.claude/commands/sdd-release.md`; update `CLAUDE.md` and `sdd/WORKFLOW.md`
with the four-branch topology and the release-cut procedure; mark the
FEAT-187 §8 open question resolved, citing this spec.

---

## 4. Test Specification

### Unit Tests

`tests/sdd_scripts/test_release_flow.py`, over synthetic git fixtures:
- each gate fails independently and produces an actionable `detail`
- a `staging` carrying a commit absent from `dev` fails the back-merge gate
- an open PR targeting `staging` fails the in-flight gate
- FF cut when `staging` is an ancestor of `nightly`
- real-merge cut when it is not, with no force-push in any code path
- notes assembly deduplicates a feature appearing in two nightly manifests
- notes assembly with zero manifests in range degrades to an explicit
  "no nightly manifests in range" body rather than an empty one
- `promote` refuses to open a second PR when one is already open

### Integration Tests

- `status --json` against the real repo validates against `ReleaseCandidate`.
- `cut --dry-run` and `promote --dry-run` mutate nothing: no ref moved, no
  commit, no PR, no file written outside a temp path.
- Grep-level assertion that the module contains no `--force`,
  `--force-with-lease`, or `reset --hard` against `staging`/`main`.

### Test Data / Fixtures

```python
# tests/sdd_scripts/conftest.py — extend FEAT-443's fixtures
# - repo with main/dev/nightly/staging and a scripted release history
# - a staging carrying an un-backmerged freeze fix
# - two sdd/nightly/<date>.md manifests sharing one feature (dedupe case)
# - fake `gh` returning scripted PR lists
```

---

## 5. Acceptance Criteria

- [ ] `cut` promotes `staging` to the current `nightly` commit, never to
      `dev` HEAD.
- [ ] `cut` refuses when the working tree is dirty.
- [ ] `cut` refuses when an open PR targets `staging`.
- [ ] `cut` refuses when `staging` holds any commit missing from `dev`.
- [ ] `cut` refuses when `nightly` is staler than the threshold, and
      `--force-stale` is the only override.
- [ ] No code path force-pushes, resets, or rewrites `staging` or `main`.
- [ ] A conflicting cut aborts cleanly and names the conflicting files.
- [ ] `status` reports features, unattributed count, `nightly` age, and
      unbackmerged `staging` commits.
- [ ] Release notes are assembled from FEAT-443 manifests and deduplicate
      features across snapshots.
- [ ] The notes file is consumable by
      `scripts/release.py gh-release --notes-file` unmodified.
- [ ] `promote` opens exactly one `staging → main` PR and never merges it.
- [ ] `/sdd-release` performs no version bump, no tag, and no PyPI publish.
- [ ] `--dry-run` on every verb mutates nothing.
- [ ] FEAT-187 §8's `/sdd-release-cut` question is marked resolved with a
      pointer to this spec.
- [ ] `CLAUDE.md` and `sdd/WORKFLOW.md` document the four-branch topology.

---

## 6. Codebase Contract

### Verified Existing Files

| File | Evidence |
|---|---|
| `scripts/release.py` | `class Package` :55, `PACKAGES` :109, `cmd_status` :226, `cmd_bump` :244, `cmd_gh_release` :323, `main` :369 |
| `scripts/sdd/sdd_meta.py` | `KNOWN_BRANCHES` :26, `FlowMeta` :29, `parse` :45, `emit` :78 (92 lines total) |
| `scripts/sdd/reserve_ids.py` | house pattern for git-native SDD scripts: `_run_git` :55, `_assert_safe_to_reserve` :106, `main(argv) -> int` :290 |
| `.claude/commands/release.md` | gates on HEAD being `dev`/`staging`/`main` (line ~51); aborts on a feature branch or worktree (line ~146) |
| `sdd/specs/git-parrot-flow.spec.md` | FEAT-187; §8 carries the `/sdd-release-cut` open question this spec closes |

### Verified Interface — the delegation seam

```python
# scripts/release.py:323
def cmd_gh_release(args: argparse.Namespace) -> int:
    """Create the GitHub Release that triggers .github/workflows/release.yml."""
    # requires: tag exists locally AND on origin; no existing GH Release
    # accepts:  --notes-file <path> | --notes <text> | (default) --generate-notes
    # builds:   gh release create <tag> --title <tag> --verify-tag [--notes-file …]
```

`--notes-file` is the contract point. `/sdd-release promote` writes that
file; `/release` passes it. Neither reimplements the other.

### Verified Repository State (re-measure before implementing)

- `staging` has 0 commits not in `main` and 0 not in `dev` — it has never
  been cut from `dev`. The steady state this spec creates has never existed.
- `main` is an ancestor of `staging` and of `dev` as of commit `86ac5633e`
  (the `sync-down.yml` repair).
- `release.yml` triggers on `release: types: [created]`.

### Does NOT Exist (Anti-Hallucination)

Verified absent at spec time — created by this feature or by FEAT-443:

- `scripts/sdd/release_flow.py`
- `.claude/commands/sdd-release.md`, `.claude/commands/sdd-snapshot.md`
- `tests/sdd_scripts/test_release_flow.py`
- the `nightly` branch and `sdd/nightly/` directory (**created by FEAT-443**
  — this spec must not create them)
- `scripts/sdd/snapshot.py` and its `FeatureEntry` / `SnapshotManifest`
  models (**created by FEAT-443**; import, do not redefine)
- any `type: release` SDD flow type — rejected by FEAT-187 and still rejected
- a `/sdd-release-cut` command — the FEAT-187 sketch was never implemented;
  this spec supersedes that name with `/sdd-release cut`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `scripts/sdd/reserve_ids.py`: module docstring, Pydantic models,
  a `_run_git` wrapper, explicit preflight assertions, `main(argv) -> int`.
- Import `FeatureEntry` and the manifest reader from FEAT-443's
  `scripts/sdd/snapshot.py`. Do not re-parse the SDD tree independently —
  two attribution implementations will drift.
- Google-style docstrings, strict type hints (CLAUDE.md).

### Known Risks / Gotchas

- **The ancestry trap after a release, and why the cut is a merge.**
  Once the `staging → main` PR merges as a merge commit, `main` holds a
  commit that `dev` does not. `sync-down.yml` then propagates it into both
  `staging` and `dev` — by separate merges, with separate commits. From
  that point `staging` is no longer an ancestor of `nightly`, so the next
  cut *cannot* be a fast-forward. This is the normal steady state, not an
  error. It is also exactly why the tempting alternative — re-creating
  `staging` at the nightly SHA with a force-push — was **rejected**: it
  would silently discard any freeze fix that had not yet been back-merged,
  and it collides with the repo's own dangerous-action guard. The cut
  merges. Always.
- **Freeze fixes MUST be back-merged into `dev`.** A fix committed on
  `staging` during a freeze and never merged down will conflict at the
  next cut, and worse, will silently regress when the next RC is cut from
  a `nightly` that never had it. Module 1's back-merge gate is the
  enforcement point and must not be made optional.
- **`/release` must not be invoked by this command.** The publish decision
  is a human confirmation in `/release`. `/sdd-release promote` prints the
  invocation; it does not run it.
- **FEAT-443 cross-constraint.** The nightly pre-release must not trigger
  `release.yml`. If FEAT-443 solves this by gating `release.yml` on
  `!github.event.release.prerelease`, verify the real release path still
  fires. Both specs touch that trigger; whichever lands second must re-test it.
- **Concurrent pushes to `dev` are routine here** (four moves in under an
  hour during the design session). Resolve `nightly` once and pin it for
  the whole run.
- **First cut is special.** `staging == main` today, so the first cut is a
  clean fast-forward and there is no previous release tag. Notes assembly
  must handle a `None` last tag rather than crashing.
- **`--generate-notes` is the current fallback in `cmd_gh_release`** and
  produces a bare list of PR titles. The whole value of Module 4 is
  replacing that with feature-level notes; don't let the fallback become
  the default path by writing an empty notes file.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `gh` CLI | already used by `sync-down.yml` and `release.py` | PR queries and creation |
| `pydantic` | already in tree | gate and candidate models |

No new Python dependencies. Hard internal dependency on FEAT-443.

---

## 8. Open Questions

- [x] Cut from `dev` HEAD or from `nightly`? — *Resolved during design
  discussion (2026-08-22)*: from `nightly`. Cutting from `dev` HEAD
  reproduces the "whatever happened to be on dev" problem FEAT-187 named.
- [x] Should `/sdd-release` bump versions and publish? — *Resolved during
  design discussion (2026-08-22)*: no. `/release` and `scripts/release.py`
  own that; the seam is `gh-release --notes-file`.
- [x] Re-point `staging` by force at each cut, or merge? — *Resolved
  during design discussion (2026-08-22)*: merge. Force-re-pointing
  discards un-backmerged freeze fixes.
- [x] Does this close FEAT-187 §8's `/sdd-release-cut` question? —
  *Resolved during design discussion (2026-08-22)*: yes, under the name
  `/sdd-release cut`, with the source changed from `dev` to `nightly`.
- [ ] Freshness threshold for `nightly` at cut time — how many hours old
  is too stale to promote? — *Owner: Jesus Lara*. Decide during Module 1.
- [ ] Should `promote` require that the RC has been deployed and exercised
  in the k8s `development` environment (a signal from the sibling infra
  spec), rather than trusting the nightly gates alone? — *Owner: Jesus
  Lara*. Depends on what signal that spec exposes.
- [ ] Should `main` be fast-forwarded from `staging` (`git push origin
  staging:main`) instead of merged via PR, to keep `main` a strict
  ancestor of `dev` and avoid the sync-down round trip entirely? This is
  cleaner topologically but conflicts with PR-based branch protection on
  `main`. — *Owner: Jesus Lara*.
- [ ] Does fieldsync need the same three-verb surface, or only `cut`? —
  *Owner: Jesus Lara*. Decide when porting.

---

## Worktree Strategy

- **Isolation unit**: per-spec. All tasks run sequentially in one worktree.
- **Rationale**: Modules 1–5 all converge on
  `scripts/sdd/release_flow.py`; parallel worktrees would conflict.
- **Cross-feature dependencies**: **blocking** — FEAT-443
  (`nightly-snapshot`) Modules 1, 4, and 6 must be merged first. This spec
  imports `FeatureEntry` and the manifest reader from FEAT-443 and reads
  the `nightly` ref and `sdd/nightly/` manifests that FEAT-443 creates.
  Do not start this feature until FEAT-443 has landed on `dev`.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-08-22 | Jesus Lara | Initial spec (FEAT-444). Closes the `/sdd-release-cut` open question from FEAT-187 §8. |
