# TASK-4580: Resolve a parrot-capable interpreter for close_task.sh's `task.closed` emission

**Feature**: FEAT-718 — close_task.sh must emit `task.closed` with an interpreter that can import `parrot`
**Spec**: `sdd/specs/fixgroup-a322afe6fc2b.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:79901cd6b884`

---

## Context

Implements the whole of FEAT-718 (spec §3 Module 1 **and** Module 2 — they touch
one script and its own test file and must land in one commit, since the tests
only pass once the script is fixed).

`scripts/sdd/close_task.sh:124` runs the FEAT-566 Module-12 `task.closed`
emission through a bare `python3` taken from `PATH`, inside a
`try/except Exception` that only warns on stderr. When `PATH`'s `python3`
cannot `import parrot` — which is the case in every environment that closes
tasks unattended (dev-loop/`sdd-coder` seats with no shell, Bubblewrap
worktree agents, CI, a plain login shell) — the event is **silently dropped**
and the script still exits 0.

That is `issue:79901cd6b884` (major): two tests in
`tests/sdd/test_ledger_lifecycle_acceptance.py` fail with
`FileNotFoundError: .../repo/.parrot/ledger/events.jsonl`, making the
merge-tier gate red for every feature — and, worse, the shared lifecycle log
under-reports real closures in production. `issue:dc663a223799` (minor) is the
same defect seen from inside a worktree.

Reproduced on `dev` at `a74a4ac6e`:

```bash
printf '#!/bin/sh\nexit 1\n' > /tmp/stub/python3 && chmod +x /tmp/stub/python3
PATH=/tmp/stub:/usr/bin:/bin .venv/bin/python -m pytest \
  tests/sdd/test_ledger_lifecycle_acceptance.py -k close_task_emits -q
# → FileNotFoundError on .parrot/ledger/events.jsonl, close_task.sh exit 0
```

`scripts/sdd/codex_hook.sh` (FEAT-563) already solved this for the codex hook:
it resolves the **main checkout's** `.venv/bin/python` via
`git rev-parse --path-format=absolute --git-common-dir` instead of trusting
`PATH`. This task backports that pattern into `close_task.sh`.

---

## Scope

- Add a deterministic interpreter resolution step to `scripts/sdd/close_task.sh`,
  placed inside the existing Module-12 emission block (after the hard
  post-condition), that picks the first **executable** candidate of:
  `$SDD_LEDGER_PYTHON` → `<script's main checkout>/.venv/bin/python` →
  `$VIRTUAL_ENV/bin/python` → `python3`.
- Derive the second candidate from `${BASH_SOURCE[0]}`, **not** from `$PWD`:
  the script is routinely run with a cwd that is a different, throwaway
  repository, and from linked worktrees that hold no `.venv`.
- Invoke the unchanged heredoc with the resolved interpreter and pass its path
  in as a 4th positional argument so the best-effort warning can name it.
- Document the resolution order and `SDD_LEDGER_PYTHON` in the script header.
- Add `TestInterpreterResolution` to `tests/sdd/test_close_task_ledger.py` with
  the two tests of spec §3 Module 2 (sabotaged `PATH`; `SDD_LEDGER_PYTHON`
  override).

**NOT in scope**:
- *What* is emitted (kind/subject/actor/payload) — unchanged (spec N1).
- Ledger-root resolution: `find_shared_root(start_dir)` keeps deciding *where*
  the log lives, resolved before `import parrot` so navconfig's `os.chdir()`
  cannot redirect it (spec N2).
- The move / index / staging / post-condition logic of `close_task.sh`
  (lines 42–115) and its exit codes 1/2/3 (spec N3).
- Any Python file under `packages/` (spec AC8).
- Editing `tests/sdd/test_ledger_lifecycle_acceptance.py` — it is fixed
  transitively and must pass unmodified.
- Creating a shared shell helper library for `scripts/sdd/` (spec §6 "Does NOT
  Exist") and provisioning or mutating any venv (spec N4).
- Closing `issue:dc663a223799` (spec N5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/close_task.sh` | MODIFY | Resolve `PY_BIN` before the Module-12 heredoc; use it; name it in the warning; document `SDD_LEDGER_PYTHON` |
| `tests/sdd/test_close_task_ledger.py` | MODIFY | Add `TestInterpreterResolution` (sabotaged `PATH`, `SDD_LEDGER_PYTHON` override) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references, re-checked on `dev` at `a74a4ac6e`.

### Verified Imports

Used only *inside* the unchanged heredoc — do not add, remove or reorder them:

```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent   # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
from parrot.knowledge.wiki.ledger.log import LedgerLog        # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py
from parrot.knowledge.wiki.project import find_shared_root    # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1546
```

Test-side imports already present at the top of
`tests/sdd/test_close_task_ledger.py` (lines 11-15) — `json`, `subprocess`,
`pathlib.Path`, `pytest`. `os` is imported *locally* inside
`_worktree_python_env` (line 63), not at module level.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1546
def find_shared_root(start: Path | None = None) -> Path | None: ...

# tests/sdd/test_close_task_ledger.py — reuse these verbatim, do not reimplement
REPO_ROOT = Path(__file__).resolve().parents[2]          # line 17
CLOSE_TASK_SH = REPO_ROOT / "scripts" / "sdd" / "close_task.sh"   # line 18
def _init_repo(tmp_path: Path) -> Path: ...              # line 21
def _worktree_python_env() -> dict: ...                  # line 53
def _run_close_task(repo, task_id, feature_slug, verification="verified"): ...  # line 71
def _read_events(repo: Path) -> list[dict]: ...          # line 81
class TestTaskClosedEmission: ...                        # line 88
```

```bash
# scripts/sdd/close_task.sh
set -euo pipefail                                   # line 31
REPO_ROOT="$(git rev-parse --show-toplevel)"        # line 42
cd "$REPO_ROOT"                                     # line 43
# FEAT-566 Module 12: emit task.closed ...          # line 117 (comment block 117-122)
python3 - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" <<'PYEOF' || true   # line 124
task_id, feature_slug, verification = sys.argv[1:4]                      # line 129 (inside heredoc)
print(f"⚠️  task.closed ledger emission skipped: {exc}", file=sys.stderr) # line 151 (inside heredoc)
```

```bash
# scripts/sdd/codex_hook.sh:6-9 — the pattern to mirror (git 2.43.0 supports --path-format, ≥2.31)
common_dir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
main_checkout=$(dirname "$common_dir")
python_bin="$main_checkout/.venv/bin/python"
[ -x "$python_bin" ] || exit 0
```

### Does NOT Exist

- ~~`scripts/sdd/_lib.sh`~~ / ~~a sourced shell preamble~~ — there is **no**
  shared shell helper for interpreter resolution. `codex_hook.sh` inlines its
  own three lines; inline here too. Do **not** create a shared library.
- ~~`PARROT_PYTHON`~~, ~~`SDD_PYTHON`~~, ~~`PARROT_LEDGER_ROOT`~~ — no such
  environment variable exists anywhere in the repo. `SDD_LEDGER_PYTHON` is
  introduced by this task; nothing reads it yet.
- ~~`scripts/run_in_venv.sh` as the fix~~ — it exists, but it `source`s an
  activate script and `exec`s a command, which cannot wrap a heredoc-fed
  interpreter, and it resolves the venv from its own parent dir only.
- ~~`close_task.sh --dry-run`~~ / ~~`--no-ledger`~~ / ~~a logging framework~~ —
  do not exist; `echo` / `>&2` is the only output channel.
- ~~a `conftest.py` stub-interpreter fixture~~ / ~~a `monkeypatch` PATH helper
  in `tests/sdd/`~~ — do not exist; the new tests build their own stub.
- ~~`$BASH_SOURCE` without an index~~ — use `${BASH_SOURCE[0]}`; `set -u` is
  active and the bare name is not a defined scalar here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/close_task.sh",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd/test_close_task_ledger.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:tests/sdd/test_close_task_ledger.py#_init_repo",
    "sym:tests/sdd/test_close_task_ledger.py#_read_events",
    "sym:tests/sdd/test_close_task_ledger.py#_run_close_task",
    "sym:tests/sdd/test_close_task_ledger.py#TestTaskClosedEmission"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `set -euo pipefail` is active (line 31): every parameter expansion of a
  possibly-unset variable must be `:-` / `:+`-guarded, and the `git rev-parse`
  probe must be `|| true`-guarded so a script dir outside a git repo cannot
  abort an otherwise-successful closure.
- Candidates are selected by `-x` **existence only** — never probed by running
  them. A probe costs a ~1s `import parrot` startup on the happy path and
  still cannot distinguish "deps missing" from "slow import"; ordering is what
  makes the choice correct.
- Resolution must stay **inside** the emission block, after the
  `✅ ... closed` line, so a failed closure (exit 1/2/3) still never touches
  the ledger — `test_missing_task_exits_before_emitting` asserts this.
- The heredoc stays quoted (`<<'PYEOF'`): no shell interpolation inside the
  Python body. The interpreter path reaches it as `sys.argv[4]`.
- Keep the emission best-effort: `|| true` on the invocation and the
  `except Exception` handler both stay (AC6,
  `test_ledger_emission_failure_never_fails_an_otherwise_successful_closure`
  asserts the `ledger emission skipped` substring — keep that exact wording in
  the message).

### References in Codebase

- `scripts/sdd/codex_hook.sh:6-9` — main-checkout venv resolution to mirror.
- `scripts/sdd/close_task.sh:117-152` — the block being edited.
- `tests/sdd/test_close_task_ledger.py:88-152` — existing emission tests.

---

## Implementation Blueprint

### Steps (in order)

1. Extend the script's header comment with the resolution order and
   `SDD_LEDGER_PYTHON` — *why*: the next operator debugging a missing event
   must find the rule in the file that implements it, not in the spec.
2. Insert the `PY_BIN` resolution block between the Module-12 comment (line
   117-122) and the invocation (line 124) — *why*: it must run only on the
   success path, after the hard post-condition, so a failed closure never
   emits.
3. Change the invocation to `"$PY_BIN" - … "$PY_BIN" <<'PYEOF' || true` —
   *why*: the 4th argument carries the resolved path into the quoted heredoc
   without shell interpolation.
4. Read it as `sys.argv[1:5]` and name it in the warning — *why*: a swallowed
   emission currently gives no clue which interpreter failed; one line of
   stderr now answers it.
5. Append `TestInterpreterResolution` to the test file — *why*: AC1/AC4 are
   the only guard against this regressing back to "passes on my machine".
6. Run both validation commands twice — once in an activated shell, once with
   the sabotaged `PATH` of AC1 — *why*: the bug is invisible in the first
   environment, which is exactly how it survived two ledger issues.

### `scripts/sdd/close_task.sh` (MODIFY — header)

```bash
# occurrences: 1 (verified: grep -c '^#   3  post-condition failed' scripts/sdd/close_task.sh)
# AFTER — insert below `#   3  post-condition failed (active copy still present) — must never happen` (verified: scripts/sdd/close_task.sh:30)
#
# Ledger emission interpreter:
#   The task.closed emission below needs an interpreter that can import
#   `parrot`. `PATH`'s python3 is that interpreter only in a shell that ran
#   `source .venv/bin/activate` — not in dev-loop coder seats, sandboxed
#   worktree agents or CI — and a failed import is swallowed (emission is
#   best-effort), silently dropping the event. So the interpreter is resolved
#   explicitly, first executable candidate wins:
#     1. $SDD_LEDGER_PYTHON            (operator override; ignored if not -x)
#     2. <this script's main checkout>/.venv/bin/python   (cf. codex_hook.sh)
#     3. $VIRTUAL_ENV/bin/python       (an activated venv)
#     4. python3                       (last resort — today's behaviour)
#   Candidate 2 is derived from ${BASH_SOURCE[0]}, never from $PWD: this
#   script is routinely run with a cwd in a different repo (the ledger test
#   fixtures) or in a linked worktree that holds no .venv.
```

**Why this shape**: the header is the script's contract surface — usage, exit
codes, and now the interpreter rule. It names the failure mode (swallowed
import → dropped event) so the comment cannot be mistaken for decoration.

### `scripts/sdd/close_task.sh` (MODIFY — resolution + invocation)

```bash
# occurrences: 1 (verified: grep -c 'swallowed, never turning an otherwise-successful closure into a failure.' scripts/sdd/close_task.sh)
# AFTER — insert below `# swallowed, never turning an otherwise-successful closure into a failure.` (verified: scripts/sdd/close_task.sh:122)
# Resolve an interpreter that can import parrot (see header). Existence-only
# checks: never probe a candidate by running it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
SCRIPT_CHECKOUT=""
if [[ -n "$SCRIPT_COMMON_DIR" ]]; then
  SCRIPT_CHECKOUT="$(dirname "$SCRIPT_COMMON_DIR")"
fi
PY_BIN="python3"
for candidate in \
  "${SDD_LEDGER_PYTHON:-}" \
  "${SCRIPT_CHECKOUT:+$SCRIPT_CHECKOUT/.venv/bin/python}" \
  "${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PY_BIN="$candidate"
    break
  fi
done
```

```bash
# occurrences: 1 (verified: grep -c 'python3 - "\$TASK_ID"' scripts/sdd/close_task.sh)
# REPLACE — `python3 - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" <<'PYEOF' || true` (verified: scripts/sdd/close_task.sh:124)
"$PY_BIN" - "$TASK_ID" "$FEATURE_SLUG" "$VERIFICATION" "$PY_BIN" <<'PYEOF' || true
```

**Why**: `"$PY_BIN"` replaces the only untrusted lookup in the block, and the
4th argument is how the quoted heredoc learns which interpreter ran it.
`${VAR:+...}` keeps an unset variable from expanding to a bare `/.venv/bin/python`
under `set -u`.

### `scripts/sdd/close_task.sh` (MODIFY — inside the heredoc)

```python
# occurrences: 1 (verified: grep -c 'task_id, feature_slug, verification = sys.argv' scripts/sdd/close_task.sh)
# REPLACE — `task_id, feature_slug, verification = sys.argv[1:4]` (verified: scripts/sdd/close_task.sh:129)
task_id, feature_slug, verification, py_bin = sys.argv[1:5]
```

```python
# occurrences: 1 (verified: grep -c 'task.closed ledger emission skipped' scripts/sdd/close_task.sh)
# REPLACE — `    print(f"⚠️  task.closed ledger emission skipped: {exc}", file=sys.stderr)` (verified: scripts/sdd/close_task.sh:151)
    print(f"⚠️  task.closed ledger emission skipped ({py_bin}): {exc}", file=sys.stderr)
```

**Why**: the substring `ledger emission skipped` is asserted by
`test_ledger_emission_failure_never_fails_an_otherwise_successful_closure`, so
it stays verbatim; the interpreter path is appended, not substituted.

### `tests/sdd/test_close_task_ledger.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'assert _read_events(repo) == \[\]' tests/sdd/test_close_task_ledger.py gives 2; the LAST line of the file is the second)
# AFTER — append at end of file, below `class TestTaskClosedEmission`'s last test (verified: tests/sdd/test_close_task_ledger.py:152)


def _unimportable_python3(tmp_path: Path) -> Path:
    """A `python3` on PATH that cannot import parrot — the reported failure mode.

    Returns the directory to put first on PATH. The stub exits non-zero
    without reading stdin, so if close_task.sh ever falls back to PATH the
    emission is lost exactly as in issue:79901cd6b884.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python3"
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    return bin_dir


class TestInterpreterResolution:
    def test_emission_survives_a_path_without_an_importable_python3(self, tmp_path):
        """issue:79901cd6b884: the event must not depend on PATH's python3."""
        repo = _init_repo(tmp_path)
        env = _worktree_python_env()
        env.pop("VIRTUAL_ENV", None)
        env.pop("SDD_LEDGER_PYTHON", None)
        env["PATH"] = f"{_unimportable_python3(tmp_path)}:/usr/bin:/bin"

        result = subprocess.run(
            ["bash", str(CLOSE_TASK_SH), "TASK-9001", "demo-feature", "verified"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        # FILL IN: assert exactly one task.closed event with subject
        # "task:TASK-9001" and payload verification "verified" — bounded by AC1
        # (use _read_events(repo), as TestTaskClosedEmission does)

    def test_sdd_ledger_python_override_is_honoured(self, tmp_path):
        """SDD_LEDGER_PYTHON wins over every other candidate (AC4)."""
        repo = _init_repo(tmp_path)
        env = _worktree_python_env()
        env["SDD_LEDGER_PYTHON"] = str(_unimportable_python3(tmp_path) / "python3")

        result = subprocess.run(
            ["bash", str(CLOSE_TASK_SH), "TASK-9001", "demo-feature", "verified"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        # FILL IN: assert the closure still succeeded (completed/ twin exists),
        # no event was written, and the warning names the stub path — bounded by
        # AC4 + AC6
```

**Why this shape**: both tests must keep `cwd=repo` (a throwaway `git init`
fixture with no `.venv`) and pass the real script by absolute path — that is
what makes "resolve from `${BASH_SOURCE[0]}`, not `$PWD`" observable (AC5).
They call `subprocess.run` directly rather than `_run_close_task`, because the
helper hard-codes `env=_worktree_python_env()` and these tests must mutate the
env. The second test deliberately asserts the *absence* of an event: that is
how it proves the override was obeyed rather than silently ignored.

### FILL IN checklist

- [ ] `test_emission_survives_a_path_without_an_importable_python3` — the
  event assertions; bounded by AC1.
- [ ] `test_sdd_ledger_python_override_is_honoured` — the closure/no-event/
  warning assertions; bounded by AC4 + AC6.

---

## Acceptance Criteria

- [ ] With a `python3` on `PATH` that cannot import `parrot`, no `VIRTUAL_ENV`
  and no `SDD_LEDGER_PYTHON`, `close_task.sh` exits 0 and writes exactly one
  `task.closed` event (`subject == "task:TASK-9001"`,
  `payload.verification == "verified"`) to the caller's
  `.parrot/ledger/events.jsonl` (spec AC1).
- [ ] `pytest tests/sdd/test_ledger_lifecycle_acceptance.py -q` is 5/5 in an
  activated shell **and** under that sabotaged `PATH`, with the file unmodified
  (spec AC2).
- [ ] `pytest tests/sdd/test_close_task_ledger.py -q` is 7/7 in both
  environments (spec AC3).
- [ ] An executable `SDD_LEDGER_PYTHON` wins over every other candidate; a
  non-executable one is ignored and closure still succeeds (spec AC4).
- [ ] Resolution uses `${BASH_SOURCE[0]}`, not `$PWD` (spec AC5).
- [ ] A failing emission still prints `ledger emission skipped` on stderr and
  exits 0; move/index/staging behaviour and exit codes 1/2/3 are unchanged
  (spec AC6).
- [ ] `bash -n scripts/sdd/close_task.sh` is clean; no new external dependency
  (spec AC7).
- [ ] No file under `packages/` is modified (spec AC8).
- [ ] `artifacts/logs/feat-566-lifecycle.log` (rewritten by the regression-gate
  test on every run) is **not** committed.

---

## Validation Commands

- `pytest tests/sdd/test_close_task_ledger.py -q`
- `pytest tests/sdd/test_ledger_lifecycle_acceptance.py -q`

---

## Test Specification

Seven tests in `tests/sdd/test_close_task_ledger.py` (5 existing, unchanged +
2 new), plus the 5 of `tests/sdd/test_ledger_lifecycle_acceptance.py` fixed
transitively and left unedited. Both files must be run twice: in an activated
shell, and with a sabotaged `PATH`:

```bash
printf '#!/bin/sh\nexit 1\n' > "$STUB/python3" && chmod +x "$STUB/python3"
PATH="$STUB:/usr/bin:/bin" .venv/bin/python -m pytest \
  tests/sdd/test_close_task_ledger.py tests/sdd/test_ledger_lifecycle_acceptance.py -q
```

Fixtures: the existing `_init_repo(tmp_path)` git fixture plus the new
`_unimportable_python3(tmp_path)` stub. No network, no database, no real venv
is created.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-a322afe6fc2b --feature-id FEAT-718`)
2. **Read the spec** at `sdd/specs/fixgroup-a322afe6fc2b.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing code: re-`grep` every anchor
   and its occurrence count; if one moved, correct this task's blueprint first
5. **Update status** in `sdd/tasks/index/fixgroup-a322afe6fc2b.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete both `FILL IN`
   markers
7. **Verify** every acceptance criterion — run the Validation Commands in
   **both** environments, and `bash -n scripts/sdd/close_task.sh`
8. **Commit the code** — stage only `scripts/sdd/close_task.sh` and
   `tests/sdd/test_close_task_ledger.py` (never `git add .` / `-A`); restore
   `artifacts/logs/feat-566-lifecycle.log` with `git checkout --` before
   committing
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4580 fixgroup-a322afe6fc2b verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
