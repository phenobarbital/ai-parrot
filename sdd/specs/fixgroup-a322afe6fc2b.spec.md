---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [ledger, close-task, task-closed, interpreter-resolution, sandbox]
---

# Feature Specification: close_task.sh must emit `task.closed` with an interpreter that can import `parrot`

**Feature ID**: FEAT-718
**Date**: 2026-10-22
**Author**: agent:sdd-fix (from `issue:79901cd6b884`, group `fixgroup:a322afe6fc2b`)
**Status**: approved
**Target version**: current

---

## 1. Motivation & Business Requirements

### Problem Statement

`issue:79901cd6b884` (major, bug, discovered from `spec:FEAT-626`) reports that
two tests in `tests/sdd/test_ledger_lifecycle_acceptance.py` fail on a clean
checkout of `origin/dev` — `test_close_task_emits_durable_task_closed_event`
with `FileNotFoundError: .../repo/.parrot/ledger/events.jsonl`, and
`TestLifecycleRegressionGate::test_focused_acceptance_suites_pass_and_evidence_is_saved`
alongside it. The issue was filed as "likely environment/sandbox related" with
no root cause. `issue:dc663a223799` (minor, from `spec:FEAT-625`) is the same
defect observed one day earlier from inside a feature worktree.

The root cause is now identified and reproduced deterministically.

`scripts/sdd/close_task.sh:124` emits the Module-12 `task.closed` event through
a **bare `python3` taken from `PATH`**:

```bash
python3 - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" <<'PYEOF' || true
```

and the heredoc wraps the whole emission in `try/except Exception` whose
handler only prints `⚠️  task.closed ledger emission skipped: <exc>` to stderr
(by design: a ledger failure must never undo a successful closure). So when the
`python3` that `PATH` resolves cannot `import parrot.knowledge.wiki.ledger.*`,
the event is **silently dropped** and `close_task.sh` still exits 0.

`PATH`'s `python3` is the repo venv's interpreter only in an interactive shell
that ran `source .venv/bin/activate`. It is *not* in the environments that
actually close tasks unattended:

- dev-loop / `sdd-coder` seats, which have no shell and never activate a venv
  (`.claude/rules/codebase-conventions.md` § "Tool-driven coder without a shell");
- Bubblewrap-sandboxed worktree agents, where the shared environment is
  read/execute-only and not activated;
- any CI step or plain login shell that invokes the script directly.

Consequences, in order of severity:

1. **Silent ledger data loss in production.** Every task closed from a
   non-activated environment is missing its `task.closed` event in
   `.parrot/ledger/events.jsonl`, so the shared lifecycle log under-reports
   closures — exactly the durability FEAT-566 Module 12 promised.
2. **A permanently red merge-tier gate.** The two acceptance tests above fail
   for every feature whose validation runs outside an activated venv, which is
   how the issue surfaced ("It makes the merge-tier validation red for every
   feature"). The regression-gate test fails transitively, because the suite it
   shells out to — `tests/sdd/test_close_task_ledger.py` — contains two tests
   with the same dependency
   (`test_successful_closure_emits_task_closed_after_post_condition`,
   `test_verification_status_is_recorded_in_the_event_payload`).

Reproduced on `dev` at `83b6290a3` by putting a `python3` that cannot import
`parrot` first on `PATH` (`/usr/bin/python3`, which has none of the venv's
dependencies):

```
PATH=<stub>:/usr/bin:/bin .venv/bin/python -m pytest \
  tests/sdd/test_ledger_lifecycle_acceptance.py -k close_task_emits
→ FileNotFoundError: .../repo/.parrot/ledger/events.jsonl   (close_task.sh exit 0)

PATH=<stub>:/usr/bin:/bin .venv/bin/python -m pytest \
  tests/sdd/test_close_task_ledger.py tests/sdd/test_ledger_workflow_twins.py \
  tests/knowledge/wiki/test_cli_ledger.py -q
→ 2 failed, 62 passed   (the regression gate's own three targets)
```

All 5 tests pass in an activated shell, which is why the defect reads as
"environment dependent" rather than as a bug in the script.

The repository already solved this exact problem once: `scripts/sdd/codex_hook.sh`
resolves the **main checkout's** `.venv/bin/python` through
`git rev-parse --path-format=absolute --git-common-dir` instead of trusting
`PATH`. `close_task.sh` predates that pattern and never adopted it.

### Goals

- G1. `close_task.sh` emits `task.closed` whenever an interpreter able to import
  `parrot` exists for the checkout that owns the script — regardless of `PATH`,
  of whether a venv is activated, and of the caller's working directory.
- G2. Interpreter resolution is deterministic, documented in the script, and
  overridable by the operator through one environment variable.
- G3. The emission stays strictly best-effort: a resolution or emission failure
  still prints its warning to stderr and still exits 0 (FEAT-566 Module 12's
  "never block closure" contract, covered by
  `test_ledger_emission_failure_never_fails_an_otherwise_successful_closure`).
- G4. A regression test proves G1 by sabotaging `PATH` — so the defect cannot
  return as "passes on my machine".

### Non-Goals (explicitly out of scope)

- N1. No change to *what* is emitted: kind, subject, actor and payload stay
  `task.closed` / `task:<ID>` / `agent:close_task.sh` /
  `{feature, verification}`.
- N2. No change to ledger-root resolution. `find_shared_root(start_dir)` keeps
  deciding *where* the log lives (from the caller's cwd, resolved before
  `import parrot` so navconfig's `os.chdir()` cannot redirect it). This feature
  only fixes *which interpreter* runs that code.
- N3. No change to the move/index/post-condition logic of `close_task.sh`
  (lines 42–115) and no new dependency for the script.
- N4. Not a venv provisioning step: when no usable interpreter exists at all,
  the script degrades exactly as today (warning + exit 0). It never creates or
  mutates an environment.
- N5. `issue:dc663a223799` (the duplicate from `spec:FEAT-625`) is resolved by
  the same change but is NOT claimed by this feature; it is reported for the
  operator to close separately.

---

## 2. Architectural Design

### Overview

Insert one resolution step before the existing heredoc: compute `PY_BIN`, then
invoke `"$PY_BIN" - …` instead of `python3 - …`. The heredoc body is untouched.

Resolution order (first executable candidate wins):

| # | Candidate | Why |
|---|---|---|
| 1 | `$SDD_LEDGER_PYTHON` | operator escape hatch, and the hook tests inject through it |
| 2 | `<script's main checkout>/.venv/bin/python` | the venv that belongs to the checkout owning this script — the `codex_hook.sh` precedent; execute-only access is enough |
| 3 | `$VIRTUAL_ENV/bin/python` | an activated venv, when the checkout has none |
| 4 | `python3` | today's behaviour, last resort |

Candidate 2 is derived from `${BASH_SOURCE[0]}`, **not** from `$PWD`:
`close_task.sh` is routinely run with a cwd that is a *different* repository
(both ledger test suites `cd` into a throwaway `git init` fixture and pass the
real script by absolute path), and from linked worktrees whose own directory
holds no `.venv`. `git -C "$script_dir" rev-parse --path-format=absolute
--git-common-dir` yields the main checkout's `.git` from any worktree; its
parent is the main checkout.

Candidates are selected by existence (`-x`), never probed by running them: the
script must not pay a ~1s `import parrot` startup per candidate on a path that
is already the happy one, and a probe cannot tell "deps missing" from "slow
import" anyway. Ordering is what makes selection correct.

### Component Diagram

```
close_task.sh
  ├─ move active/ → completed/, update index, stage, hard post-condition   (unchanged)
  └─ emit task.closed
       ├─ resolve_ledger_python()        ← NEW (pure shell, no side effects)
       │    $SDD_LEDGER_PYTHON
       │    → git -C <script_dir> rev-parse --git-common-dir → <main>/.venv/bin/python
       │    → $VIRTUAL_ENV/bin/python
       │    → python3
       └─ "$PY_BIN" - <<PYEOF            ← body unchanged
              find_shared_root(cwd) → <root>/.parrot/ledger/events.jsonl
              LedgerLog(...).append(LedgerEvent(kind="task.closed", ...))
              except Exception → warn on stderr, exit 0
```

### Integration Points

- `scripts/sdd/close_task.sh` — the only production caller of the emission.
- `tests/sdd/test_close_task_ledger.py` — shell-level emission coverage.
- `tests/sdd/test_ledger_lifecycle_acceptance.py` — FEAT-566 acceptance gate
  (fixed transitively; not edited).
- `scripts/sdd/finalize_task.py` / `/sdd-done` consume the resulting events;
  neither is touched.

### Data Models

None. No Python module, class or model is added or changed.

### New Public Interfaces

One documented environment variable:

- `SDD_LEDGER_PYTHON` — absolute path to the interpreter used for the
  `task.closed` emission. When set and executable it wins over every other
  candidate; when set and *not* executable it is ignored (the script falls
  through) so a stale export can never break task closure.

---

## 3. Module Breakdown

### Module 1: interpreter resolution in `close_task.sh`

**File**: `scripts/sdd/close_task.sh` (modify)

1. Extend the header comment block with the resolution order and
   `SDD_LEDGER_PYTHON`.
2. Before the emission block, add the resolution (runs only on the success
   path, after the hard post-condition, so a failed closure still never
   touches the ledger):

   ```bash
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   PY_BIN="python3"
   script_common_dir="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute \
     --git-common-dir 2>/dev/null || true)"
   script_checkout=""
   [[ -n "$script_common_dir" ]] && script_checkout="$(dirname "$script_common_dir")"
   for candidate in \
     "${SDD_LEDGER_PYTHON:-}" \
     "${script_checkout:+$script_checkout/.venv/bin/python}" \
     "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"; do
     if [[ -n "$candidate" && -x "$candidate" ]]; then
       PY_BIN="$candidate"
       break
     fi
   done
   ```

   `set -euo pipefail` is active, so every expansion is `:-`/`:+`-guarded and
   the `git` call is `|| true`-guarded (a non-repo script dir must not abort
   the script).
3. Change the invocation to `"$PY_BIN" - "$TASK_ID" "$FEATURE_SLUG"
   "$VERIFICATION" <<'PYEOF' || true`.
4. Include the resolved interpreter in the failure warning so the next
   diagnosis is one line:
   `⚠️  task.closed ledger emission skipped (<py>): <exc>` — the path is passed
   into the heredoc as a 4th positional argument, keeping the quoted `<<'PYEOF'`
   (no shell interpolation inside the Python body).

### Module 2: regression coverage

**File**: `tests/sdd/test_close_task_ledger.py` (modify)

Add `TestInterpreterResolution` with two tests, reusing the existing
`_init_repo` / `_read_events` helpers:

1. `test_emission_survives_a_path_without_an_importable_python3` — write a
   stub `python3` into `tmp_path/"bin"` that exits 1 without reading stdin,
   run `close_task.sh` with `PATH="<stub dir>:/usr/bin:/bin"` (venv **not** on
   `PATH`, `VIRTUAL_ENV` and `SDD_LEDGER_PYTHON` removed from the env), and
   assert exit 0 **and** exactly one `task.closed` event. This is the failing
   case reproduced in §1 and the direct guard for G1.
2. `test_sdd_ledger_python_override_is_honoured` — point
   `SDD_LEDGER_PYTHON` at the same failing stub while leaving `PATH` intact,
   and assert the closure still exits 0, no event is written, and the warning
   names the stub. This pins the precedence of candidate 1 (and would fail if
   the variable were silently ignored).

Both tests must keep the script's cwd a throwaway `git init` fixture, exactly
as the existing tests do — that is what makes the resolution-from-`BASH_SOURCE`
requirement observable.

---

## 4. Test Specification

### Unit Tests

`tests/sdd/test_close_task_ledger.py` (existing 5 + 2 new):

| Test | Asserts |
|---|---|
| `test_successful_closure_emits_task_closed_after_post_condition` | unchanged behaviour in an activated env |
| `test_verification_status_is_recorded_in_the_event_payload` | payload unchanged |
| `test_missing_task_exits_before_emitting` | exit 2, no event (resolution must not run early) |
| `test_already_closed_is_idempotent_and_still_succeeds` | idempotent closure |
| `test_ledger_emission_failure_never_fails_an_otherwise_successful_closure` | G3: warning + exit 0 |
| `test_emission_survives_a_path_without_an_importable_python3` | **G1/G4** |
| `test_sdd_ledger_python_override_is_honoured` | G2 precedence |

### Integration Tests

`tests/sdd/test_ledger_lifecycle_acceptance.py` — not edited. Its
`test_close_task_emits_durable_task_closed_event` and
`TestLifecycleRegressionGate::test_focused_acceptance_suites_pass_and_evidence_is_saved`
must pass both with and without an activated venv on `PATH`.

### Validation Contract

tests:
- tests/sdd/test_close_task_ledger.py
- tests/sdd/test_ledger_lifecycle_acceptance.py
markers: none

### Test Data / Fixtures

The existing `_init_repo(tmp_path)` git fixture, plus a stub `python3`
(`#!/bin/sh` + `exit 1`) written into `tmp_path/"bin"` by the new tests. No
network, no database, no real venv is created.

Both contract files must **additionally** be run once with a sabotaged `PATH`
— a `python3` first on `PATH` that cannot import `parrot` — which is the
environment the reported failure needs:

```bash
printf '#!/bin/sh\nexit 1\n' > "$STUB/python3" && chmod +x "$STUB/python3"
PATH="$STUB:/usr/bin:/bin" .venv/bin/python -m pytest \
  tests/sdd/test_close_task_ledger.py tests/sdd/test_ledger_lifecycle_acceptance.py -q

bash -n scripts/sdd/close_task.sh
```

`artifacts/logs/feat-566-lifecycle.log` is rewritten by the regression-gate
test on every run; it is evidence, and any diff in it must not be committed as
part of this feature.

---

## 5. Acceptance Criteria

- **AC1**. With a `python3` on `PATH` that cannot import `parrot`, no
  `VIRTUAL_ENV`, and no `SDD_LEDGER_PYTHON`, `close_task.sh` exits 0 and
  `.parrot/ledger/events.jsonl` in the caller's repo contains exactly one
  `task.closed` event with `subject == "task:<ID>"` and the given
  `verification`.
- **AC2**. `tests/sdd/test_ledger_lifecycle_acceptance.py` passes 5/5 both in an
  activated shell and under the sabotaged `PATH` of AC1.
- **AC3**. `tests/sdd/test_close_task_ledger.py` passes with the two new tests,
  in both environments.
- **AC4**. `SDD_LEDGER_PYTHON`, when executable, is used in preference to every
  other candidate; when set to a non-executable path it is ignored and closure
  still succeeds.
- **AC5**. Interpreter resolution uses the script's own location
  (`${BASH_SOURCE[0]}`) — proven by the tests, whose cwd is an unrelated
  throwaway repo with no `.venv`.
- **AC6**. A failing emission still prints `ledger emission skipped` on stderr
  and exits 0; the move/index/staging behaviour and the exit codes 1/2/3 are
  byte-for-byte unchanged in behaviour.
- **AC7**. `bash -n scripts/sdd/close_task.sh` is clean and the script adds no
  new external dependency (`git`, `jq`, `date`, `mktemp` only, as today).
- **AC8**. No Python source file under `packages/` is modified by this feature.

---

## 6. Codebase Contract

### Verified Imports

Used *inside* the unchanged heredoc (confirmed present on `dev` at `83b6290a3`):

```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent   # events.py
from parrot.knowledge.wiki.ledger.log import LedgerLog        # log.py
from parrot.knowledge.wiki.project import find_shared_root    # project.py:1546
```

### Existing Signatures

- `find_shared_root(start: Path | None = None) -> Path | None`
  — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1546`.
- `LedgerLog(path: str)` with `.append(event)` —
  `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py`.
- `LedgerEvent(kind=..., subject=..., actor=..., payload=...)` —
  `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`.
- Test helpers already present in `tests/sdd/test_close_task_ledger.py`:
  `_init_repo(tmp_path) -> Path` (line 21), `_worktree_python_env() -> dict`
  (line 53), `_run_close_task(repo, task_id, feature_slug, verification)`
  (line 71), `_read_events(repo) -> list[dict]` (line 81),
  `class TestTaskClosedEmission` (line 88).

### Integration Points

- `scripts/sdd/close_task.sh:31` `set -euo pipefail`;
  `:42` `REPO_ROOT="$(git rev-parse --show-toplevel)"`;
  `:117-122` the Module-12 comment block;
  `:124` `python3 - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" <<'PYEOF' || true`
  (sha256 `dbb02bf709042914e8bee1b035202383ee844cfcc637c7e61b87ad7905e43e09`).
- `scripts/sdd/codex_hook.sh:6-9` — the `--path-format=absolute --git-common-dir`
  → `<main>/.venv/bin/python` precedent to mirror. `git version 2.43.0`
  supports `--path-format` (≥ 2.31).

### Does NOT Exist (Anti-Hallucination)

- There is **no** shared shell helper for interpreter resolution — no
  `scripts/sdd/_lib.sh`, no sourced preamble. `codex_hook.sh` inlines its own
  three lines; `close_task.sh` must inline its own too. Do not create a shared
  library in this feature.
- `scripts/run_in_venv.sh` exists but **must not** be used here: it `source`s an
  activate script and `exec`s, which cannot wrap a heredoc-fed interpreter, and
  it resolves the venv from its own parent directory only.
- There is no `PARROT_PYTHON`, `SDD_PYTHON` or `PARROT_LEDGER_ROOT` environment
  variable anywhere in the repo. `SDD_LEDGER_PYTHON` is introduced by this
  feature; do not assume an existing one.
- `tests/sdd/test_close_task_ledger.py` has **no** `conftest.py`-provided
  fixture for a stub interpreter and no `monkeypatch`-based PATH helper; the new
  tests build the stub themselves.
- `close_task.sh` has no `--dry-run`, no `--no-ledger` flag and no logging
  framework; `echo`/`>&2` is the only output channel.

### Edit Sites (Blueprint Anchors)

| File | Anchor | Edit |
|---|---|---|
| `scripts/sdd/close_task.sh` | header block ending `#   3  post-condition failed (active copy still present) — must never happen` (line 30) | document resolution order + `SDD_LEDGER_PYTHON` |
| `scripts/sdd/close_task.sh` | `# FEAT-566 Module 12: emit task.closed to the shared work ledger, AFTER the` (line 117) | insert the resolution block after the comment, before the invocation |
| `scripts/sdd/close_task.sh` | `python3 - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" <<'PYEOF' || true` (line 124) | `"$PY_BIN" - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" "$PY_BIN" <<'PYEOF' \|\| true` |
| `scripts/sdd/close_task.sh` | `print(f"⚠️  task.closed ledger emission skipped: {exc}", file=sys.stderr)` | name the interpreter in the warning |
| `tests/sdd/test_close_task_ledger.py` | end of file, after `class TestTaskClosedEmission` | append `class TestInterpreterResolution` with the two tests |

---

## 7. Provenance

- `issue:79901cd6b884` — major, bug, `discovered_from: spec:FEAT-626`,
  `about: tests/sdd/test_ledger_lifecycle_acceptance.py`. Claimed by
  `agent:sdd-fix` on 2026-10-22; group `fixgroup:a322afe6fc2b`
  (`max_severity: major` → SDD lane, `planner_version: 1`).
- `issue:dc663a223799` — minor duplicate from `spec:FEAT-625` (same symptom,
  observed from inside `feat-FEAT-625-wikitoolkit-lint`). Same root cause, same
  fix; left open and unclaimed per N5.
- Parent `FEAT-626` is closed (`completed_at: 2026-10-03`), so this feature
  opens its own spec rather than reusing the parent.
- Origin of the defect: FEAT-566 Module 12 added the emission with a bare
  `python3`; `scripts/sdd/codex_hook.sh` (FEAT-563) later established the
  main-checkout-venv resolution pattern that this feature backports.
