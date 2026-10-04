---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, fidelity-gate, extraction, complexity-routing, ledger-fix]
---

# Feature Specification: dev-loop sdd-coder fixes (empty-delivery gate + declared `sdd/` targets)

**Feature ID**: FEAT-597
**Date**: 2026-09-24
**Author**: Jesus Lara (with Claude, via `/sdd-fix`)
**Status**: approved
**Target version**: next patch
**Source**: ledger fix group `fixgroup:dc9fdf558f83` (`wikitoolkit ledger plan-fix`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Two confirmed engine bugs at the sdd-coder merge boundary
(`SddCoderEngine._consolidate`, `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`),
plus one routing issue that a later commit already closed but the ledger still lists.

**A. Empty delivery passes fidelity and is reported `merged` (`issue:ee4d4879fc89`).**
`_consolidate` extracts the declared files (`_commit_declared_changes`), diffs the attempt
branch against its fork point and runs `check_fidelity(expected, changed)`. When the seat
produced *nothing* — no file in the tree, no commit — `changed == []`, `[] ⊆ expected` holds
vacuously, the (no-op) merge succeeds and the task is reported `outcome="merged"`,
`fidelity_ok=true`, with `commits=0, changed_files=[]` in `coder_delivery_report`. FEAT-581's
TASK-3534 (codex `gpt-5.6-terra`) hit exactly this; the orchestrator only noticed by inspecting
the sub-worktree by hand. The same hole is the "empty-diff-passes-fidelity" gap noted next to
PR #1460 (ignored-declared-files extraction).

**B. A task's own, declared `sdd/` target is rejected as `unexpected_files` (`issue:c748e42f2777`).**
`check_fidelity` flags **every** changed path under `sdd/` (`sdd_touched`), and
`_commit_declared_changes` never stages a declared `sdd/` path
(`declared = {p for p in expected if not p.startswith("sdd/")}`), so the coder's correct edit is
left uncommitted and reported as an undeclared leftover. FEAT-576's TASK-3460 (declared
`sdd/templates/{spec,brainstorm,proposal}.md`) and TASK-3468 (declared `sdd/WORKFLOW.md`)
each burned two correct attempts this way. The issue's secondary hypothesis (tracked files
under the `.gitignore` `templates/` rule mishandled) is **not** the cause: git status/diff
report tracked files regardless of ignore rules; the blanket `sdd/` exclusion alone explains
both failures. The rule the gate is meant to enforce is "a coder never touches
orchestrator-owned SDD *state*" — `sdd/tasks/**` (task files, per-spec index, id ledger) and
`sdd/ledger/**` — not "no deliverable may live under `sdd/`".

**C. `unknown`-classified tasks had no eligible seat (`issue:f0cf45fc31dd`) — already fixed.**
Filed 2026-09-19 on FEAT-580. Commit `957c15d96` (2026-09-20, "require strong-model seats for
'unknown' tasks too", closing the duplicate `issue:e01c03baf493`) made `roster.eligible_seats`
restrict `unknown` to `ComplexityPolicy.strong_models` exactly like `complex`, so `plan()`
now assigns such tasks to a strong MCP or native seat when one is configured and emits an
honest planning-time `complex_model_unavailable` block otherwise (the issue's suggested fix
(a) + (b)). Tests `test_complexity_routing.py` / `test_roster.py` (parity test) pin it. This
spec adds **no code** for C; it is verified and closed by evidence (see §5 AC7).

Ledger issues covered:

| Issue | Severity | Summary | Module |
|---|---|---|---|
| `issue:ee4d4879fc89` | major | `merged` with 0 commits / 0 changed files | M1 |
| `issue:c748e42f2777` | major | declared `sdd/` doc/template targets rejected as `unexpected_files` | M2 |
| `issue:f0cf45fc31dd` | major | no eligible seat for `unknown` classification | verified fixed by `957c15d96` |

### Goals
- A `merged` outcome always carries at least one changed file. An attempt that changes
  nothing is never merged and never reported as a success.
- An empty MCP delivery is treated like a dispatch failure: the existing retry ladder runs
  (attempt 2 on another eligible seat, or the native retry) instead of the task silently
  "completing".
- A path under `sdd/` that the task itself declares under `## Files to Create / Modify` is a
  legitimate deliverable: it is staged by the extraction commit and passes fidelity.
- `sdd/tasks/**` and `sdd/ledger/**` stay off-limits **even when declared** — a task that
  declares them is a spec error and the branch is still a `fidelity_violation`.
- Orchestrator docs (outcome table, `sdd-worker` bullets, `sdd-coder` rule 6) describe the new
  diagnostic and the narrowed `sdd/` rule.

### Non-Goals (explicitly out of scope)
- Suspending a model after an empty delivery (`_classify_failure_reason` returns `None`
  for it — no new suspension reason).
- Changing `parse_task_files` or the task template.
- Any change to `roster.py` / complexity routing (C is already fixed).
- Retrying a `_consolidate`-level empty delivery from the `merge()` (native) path — there the
  orchestrator owns attempt 3, as for any `failed`.

---

## 2. Architectural Design

### Overview

**M1 — empty-delivery gate (two sites, one meaning).**

1. *Merge boundary backstop* (`_consolidate`, right after `changed` is computed and before
   `check_fidelity`): if `changed` is empty **and** `branch` is not already an ancestor of
   `ctx.feature_branch` (`git merge-base --is-ancestor branch feature_branch` → rc≠0), return
   ```python
   TaskResult(task_id=..., outcome="failed", branch=branch, worktree_path=path,
              diagnostics="empty_delivery: <branch> changes no file relative to <diff_base[:12]> "
                          "(declared N file(s): a, b, …); nothing was merged")
   ```
   Nothing is linted or merged. The ancestor guard preserves the documented re-merge fallback
   in `_consolidate_diff_base` (a branch already merged by hand legitimately diffs empty).
2. *Attempt-level detection* (`_run_task`, in the `if not err:` branch before calling
   `_consolidate`): compute the attempt's **delivered paths** = committed changes
   (`git diff --name-only <fork>..<branch>` with `<fork> = git merge-base feature_branch branch`,
   run in `ctx.worktree`) ∪ dirty paths in the sub-worktree (`_dirty_paths` of
   `git status --porcelain -z --untracked-files=all`) ∪ declared-but-ignored files
   (`git ls-files --others --ignored --exclude-standard -- <declared>`, same call shape as
   `_commit_declared_changes`). If that set is empty, the attempt is an **error**:
   `err = f"empty_delivery: seat {seat.label} ({seat.backend}/{model}) delivered no file change for {task_id}"`,
   `rec = rec.model_copy(update={"error": err})`, and control falls into the existing `if err:`
   retry ladder unchanged (attempt-1 outcome row emitted as `failed`, retry seat selection,
   native retry, `complex_model_unavailable` diagnostics all as today). Factor the delivered-
   paths computation into one private helper (e.g. `_delivered_paths(ctx, expected, branch, path)`)
   used by site 2; site 1 keeps using `changed` (already computed).
   `_classify_failure_reason` must return `None` when `error` starts with `empty_delivery:`
   (explicit early return, so a later generic rule never suspends for it).

**M2 — declared `sdd/` targets.**

- `fidelity.py`: add `PROTECTED_SDD_PREFIXES: tuple[str, ...] = ("sdd/tasks/", "sdd/ledger/")`
  and `is_protected_sdd_path(path: str) -> bool`. `check_fidelity` becomes:
  `unexpected = [p for p in changed if p not in exp]` (unchanged);
  `sdd_touched = [p for p in changed if p.startswith("sdd/") and (p not in exp or is_protected_sdd_path(p))]`;
  `ok = not unexpected and not sdd_touched`. Docstring: "ok ⇔ changed ⊆ expected, and no
  changed `sdd/` path is undeclared or under a protected prefix".
- `engine.py::_commit_declared_changes`: `declared = {p for p in expected if not is_protected_sdd_path(p)}`
  (import the predicate from `fidelity`). A declared protected path is therefore never staged,
  stays dirty, and surfaces as today's `undeclared_files_left_uncommitted` fidelity violation.
  Update the docstring paragraph "`sdd/` paths are never staged at all…" accordingly.
- `_consolidate`: `unexpected_files=list(dict.fromkeys(report.unexpected + report.sdd_touched))`
  (a protected declared path would otherwise appear once, an undeclared `sdd/` path twice).

**Docs (both modules).**
- `docs/dev_loop/sdd-coder-orchestrator.md` §Outcomes table: `fidelity_violation` row →
  "touched orchestrator-owned SDD state (`sdd/tasks/`, `sdd/ledger/`) or a file not on its
  task's list, **or** banned import"; add a row (or a sentence under `failed`) for
  `failed` + `diagnostics` starting `empty_delivery:` → "the seat produced no file change; the
  engine already ran the retry ladder (MCP path); from `coder_merge` (native path) attempt 3 is
  `sdd-worker`'s".
- `.claude/agents/sdd-worker.md` (git-tracked; `git add -f` not needed but harmless): same two
  edits in the outcome bullets around lines 364–372.
- `.claude/agents/sdd-coder.md` rule 6 ("YOU NEVER TOUCH `sdd/`", ~L78–80, checklist L165,
  L183, L198): narrow to "never touch `sdd/tasks/` or `sdd/ledger/`; a path under `sdd/` that
  YOUR task lists under *Files to Create / Modify* is a normal deliverable".

### Integration Points

| Existing Component | Change | Notes |
|---|---|---|
| `fidelity.check_fidelity` | modify | protected-prefix rule; new `PROTECTED_SDD_PREFIXES`, `is_protected_sdd_path` |
| `SddCoderEngine._commit_declared_changes` | modify | stage declared non-protected `sdd/` paths |
| `SddCoderEngine._consolidate` | modify | empty-delivery backstop; dedupe `unexpected_files` |
| `SddCoderEngine._run_task` | modify | attempt-level empty-delivery → retry ladder |
| `SddCoderEngine._classify_failure_reason` | modify | `empty_delivery:` → `None` |
| `_consolidate_diff_base`, `roster.py`, `models.py` | none | `TaskOutcome`/`ERROR_CODES` unchanged — `empty_delivery` is a diagnostics prefix like `branch_not_merged:` |

### Data Models
No new models. `FidelityReport` keeps its fields; `sdd_touched` semantics narrow as above.

---

## 3. Module Breakdown

### Module 1: empty-delivery gate (`engine.py`) — covers `issue:ee4d4879fc89`
Sites 1 + 2 + `_classify_failure_reason` + docs rows for the new diagnostic.

### Module 2: declared `sdd/` targets (`fidelity.py`, `engine.py`) — covers `issue:c748e42f2777`
Protected-prefix predicate, `check_fidelity`, `_commit_declared_changes`, dedupe, docs/agent
wording.

### Module 3: tests (both)
See §4. Tests live in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/`.

---

## 4. Test Specification

| Test (file) | Description |
|---|---|
| `test_fidelity_allows_declared_sdd_docs_never_protected_state` (`test_fidelity.py`) | declared `sdd/WORKFLOW.md` + `sdd/templates/spec.md` changed → ok; declared `sdd/tasks/index/x.json` → not ok, in `sdd_touched`; undeclared `sdd/x.json` → in both `unexpected` and `sdd_touched` (existing `test_fidelity_rejects_unexpected_and_sdd` keeps passing) |
| `test_engine_commits_declared_sdd_doc_targets` (`test_engine_plan_merge.py`) | sandbox `.gitignore` gains `templates/`; a tracked `sdd/templates/task.md` and `sdd/WORKFLOW.md` exist; TASK-0002's task md declares both; coder edits both uncommitted → `merge()` → `merged`, both changes on the feature branch, clean status |
| `test_engine_never_stages_protected_sdd_state_even_if_declared` (`test_engine_plan_merge.py`) | TASK-0002 declares `sdd/tasks/index/demo.json` (or a `sdd/tasks/active/*.md`); coder edits it → `fidelity_violation`, `unexpected_files == [that path]`, no `engine-committed` commit on the branch |
| `test_engine_merge_refuses_empty_delivery` (`test_engine_plan_merge.py`) | `prepare_native` then `merge()` with no work → `outcome == "failed"`, `diagnostics.startswith("empty_delivery:")`, branch NOT an ancestor of the feature branch, feature log unchanged |
| `test_engine_merge_rejects_declared_and_undeclared_sdd_mix` (optional, same file) | declared `sdd/WORKFLOW.md` + undeclared `sdd/tasks/index/demo.json` → violation lists only the protected one once |
| `test_run_task_empty_delivery_retries_on_another_seat` (`test_engine_dispatch.py`) | new `FakeDispatcher` behaviour `"empty"` (returns a `DevelopmentOutput` claiming the file but writes/commits nothing); seat `a` → `"empty"`, seat `b` → `"ok"`; `run_chunk([TASK-0001])` → `merged`, `len(attempts) == 2`, `attempts[0].error.startswith("empty_delivery:")`, `attempts[1].seat_label != attempts[0].seat_label` |
| `test_run_task_empty_delivery_twice_is_failed` (`test_engine_dispatch.py`) | every backend `"empty"` → `outcome == "failed"`, both attempt errors start with `empty_delivery:`, feature branch untouched |
| `test_classify_failure_reason_empty_delivery_not_suspendable` (`test_engine_dispatch.py` or `test_suspensions.py`) | `engine._classify_failure_reason("empty_delivery: …", "RuntimeError") is None` |
| existing suite | `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` stays green (notably `test_engine_run_chunk_merges_clean_branches`, `test_engine_commits_gitignored_declared_work`, `test_complexity_routing.py`, `test_roster.py`) |

---

## 5. Acceptance Criteria
- [ ] AC1: `_consolidate` never returns `merged` for an attempt branch whose diff against its fork point is empty unless the branch is already an ancestor of the feature branch; the failure carries `diagnostics` starting `empty_delivery:`.
- [ ] AC2: In `_run_task`, an MCP attempt that delivers no committed, dirty or declared-ignored file is recorded as a `failed` attempt with `error` starting `empty_delivery:` and the retry ladder runs exactly as for a dispatch error.
- [ ] AC3: `_classify_failure_reason` returns `None` for an `empty_delivery:` error (no suspension).
- [ ] AC4: A declared, non-protected `sdd/` path (e.g. `sdd/WORKFLOW.md`, `sdd/templates/*.md`) is staged by the extraction commit and passes `check_fidelity`; the FEAT-576 TASK-3460/3468 shapes merge.
- [ ] AC5: Any changed path under `sdd/tasks/` or `sdd/ledger/` is a `fidelity_violation` whether declared or not, and is never staged by the engine.
- [ ] AC6: Orchestrator docs and both agent files describe the `empty_delivery:` diagnostic and the narrowed `sdd/` rule.
- [ ] AC7 (issue C, no code): `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q` passes on this branch, confirming `957c15d96`'s fix is present; `issue:f0cf45fc31dd` closes with `--resolved-by commit:957c15d96`.
- [ ] AC8: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/ -q` passes; `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine, _git   # engine.py; tests import CoderFailure/SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.fidelity import FidelityReport, check_banned_imports, check_fidelity, parse_task_files
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, TaskResult, AttemptRecord
from parrot.flows.dev_loop.models import DevelopmentOutput
```

### Existing Signatures / Anchors (verified 2026-09-24 on dev `881e73e2a`)
- `fidelity.py:19-26` `class FidelityReport(BaseModel)`: `ok, expected, changed, unexpected, sdd_touched`.
- `fidelity.py:56-67` `def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport`.
- `engine.py:56` `from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files`.
- `engine.py:144` `async def _consolidate_diff_base(feature_branch, branch, *, cwd) -> str` (documents the empty-diff re-merge fallback).
- `engine.py:2140` `@staticmethod def _dirty_paths(porcelain_z: str) -> List[str]`.
- `engine.py:2173` `async def _commit_declared_changes(self, task, expected, *, branch, path, feature) -> Optional[TaskResult]`; `engine.py:2218` `declared = {p for p in expected if not p.startswith("sdd/")}`; ignored-declared lookup `engine.py:2224-2228`.
- `engine.py:~2289` `async def _consolidate(self, ctx, manager, task, *, branch, path) -> TaskResult`; `engine.py:2325-2328` `diff_base = …; _rc, diff, _err = await _git("diff", "--name-only", f"{diff_base}..{branch}", cwd=ctx.worktree); changed = […]; report = check_fidelity(expected, changed)`; `engine.py:2335` `unexpected_files=report.unexpected + report.sdd_touched`; `engine.py:2387` `merge-base --is-ancestor` post-merge check; `engine.py:2401` `return TaskResult(..., outcome="merged", ...)`.
- `engine.py:~3338` `async def _run_task(self, ctx, task, seat, *, job_id, execution_id=None, pool=None) -> TaskResult`; `engine.py:~3367` `if not err:` → `result = await self._consolidate(...)`; the `if err:` ladder follows (`_eligible_retry_labels`, `_select_retry_seat`, `_select_native_retry_seat`).
- `engine.py:3023` `def _classify_failure_reason(self, error: str, error_class: str, outcome: Optional[str] = None) -> Optional[str]`.
- `models.py:30-39` `TaskOutcome` Literal (unchanged); `models.py:297` `class AttemptRecord` with `error: str`, `seat_label`.
- Tests: `conftest.py` `git_sandbox_feature` → `(worktree, feature_branch, base_path, index_path)`, TASK-0001..0005 declare `pkg/t{n}.py`; helper `_write_and_commit(repo, filename, content, message)`; `test_engine_plan_merge.py:107` `test_engine_native_prepare_then_merge`, `:154` `test_engine_commits_uncommitted_declared_work`, `:878` `test_engine_commits_gitignored_declared_work` (pattern for rewriting a task md's declared file and committing it); `test_engine_dispatch.py:19` `class FakeDispatcher` (behaviours `ok|fail|block|extra|banned`), `:67` `fake_builder_factory(behaviour_by_backend)`, `:82` `_roster(*labels_backends)`, `:332` `test_engine_run_chunk_merges_clean_branches`.
- Docs: `docs/dev_loop/sdd-coder-orchestrator.md:212-220` outcomes table; `.claude/agents/sdd-worker.md:364-372` outcome bullets; `.claude/agents/sdd-coder.md:78-80,165,183,198` `sdd/` rule.

### Does NOT Exist (Anti-Hallucination)
- No `empty_delivery` entry in `ERROR_CODES` / `TaskOutcome` — do not add one; it is a diagnostics/error **prefix**.
- No existing helper that lists an attempt's delivered paths; `_commit_declared_changes` computes dirty + ignored-declared inline.
- `.agent/agents/sdd-worker/agent.md` is a different (dev-flow) file, not a twin of `.claude/agents/sdd-worker.md`; leave it alone.

---

## 7. Implementation Notes & Constraints
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src` (shared venv points at the main checkout).
- Keep `_consolidate`'s ordering: read task md → extract → diff → **empty gate** → fidelity → lint → banned imports → merge.
- The attempt-level gate (site 2) must run **before** `_consolidate` so the extraction commit is never created for an empty attempt and the retry ladder sees the attempt as errored.
- Hard cut (no external consumers); `FidelityReport` shape unchanged.

## 8. Open Questions
None.

## 9. Design Research Cross-Check
Status: skipped (ledger-driven fix lane; scope fully determined by the filed issues)

## Revision History
| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-09-24 | Authored by `/sdd-fix` from fixgroup:dc9fdf558f83 |
