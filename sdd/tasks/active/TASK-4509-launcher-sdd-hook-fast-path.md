# TASK-4509: Launcher fast path for `parrot sdd run worktree_environment --hook` (rev 0.3 C16)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4072, TASK-4085
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3 C16 (spec §3 M1, lines 293-296 *[rev 0.5: were 288-291]*; proposal §3 C16 items 2 and 3) was approved on
2026-10-17. It makes the shipped `sdd-coder`/`sdd-worker` `PreToolUse` guard call
`parrot sdd run worktree_environment --hook` instead of a monorepo file path. The guard fires on
**every** Bash/Write/Edit of those seats. The spec therefore requires a launcher argv fast path
with the same shape as the `wikitoolkit claude-hook` one: the decision happens before Click is
imported, behind a single `is_managed()` call.

The proposal assigned this to TASK-4072. The 2026-10-19 readiness review split it into this task.
TASK-4072 can then ship the launcher without waiting on `parrot.sdd`: TASK-4085 creates
`parrot/sdd/scripts/` and moves `worktree_environment` there, and that sits behind TASK-4070.
TASK-4072's readiness section records the split.

Proposal C16 item 3 also lands here. `dispatchers/claude.py:625` builds the same hook for
programmatic `AgentDefinition`s from `Path(worktree_environment.__file__)`. After the move it must
stop deriving the command from a file path.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Created by the readiness review; no prior version.
- Resolved by spec rev 0.5 (2026-10-20):
  - C19 item 3 — programmatic hook command: `shlex.join([sys.executable, "-m",
    "parrot.sdd.scripts.worktree_environment", "--hook"]) + " || exit 2"`. There is no `PATH`
    dependence, and it stays cheap because the `parrot.sdd` package roots are import-free.
    Shipped frontmatter keeps `parrot sdd run worktree_environment --hook` (TASK-4089).
  - C19 item 4 / D17 — latency budget: S4's targets apply. Median delta ≤ 5 ms in a non-managed
    venv (versus `python -m parrot.sdd.scripts.worktree_environment --hook`), ≤ 50 ms
    managed→project.
  - Folded in from dev's rev 0.5 D4c notes (2026-10-20): `dispatchers/claude.py:625` emits the form above;
    `import parrot` costs about 9 ms. Context before this task lands: after TASK-4085,
    `worktree_environment.__file__` names the moved `parrot/sdd/scripts/worktree_environment.py`, which
    still runs by path, so the current hook keeps working until this task changes it.
  - Anchors re-verified on dev `9625844f5` (2026-10-20): spec C16 text in §3 M1 is lines 293-296 (was
    288-291); §7 "Hook latency budget (S4)" is line 1152 (was ~1015); `entry.py` pattern is `:18-29` (was
    `:18-28`); the test function is defined at `:286` (`:285` is its parametrize line). All other anchors hold.

---

## Scope

- In `packages/ai-parrot/src/parrot/launcher.py` (created by TASK-4071/4072), add
  `SDD_HOOK_ARGV = ["sdd", "run", "worktree_environment", "--hook"]`. In `main_parrot`'s `load()`:
  when `sys.argv[1:] == SDD_HOOK_ARGV`, return a callable that sets `sys.argv[1:] = ["--hook"]` and
  runs `parrot.sdd.scripts.worktree_environment.main`. Otherwise return `parrot.cli:cli` as today.
- The decision goes through the existing `_dispatch` path. The re-exec decision (one
  `is_managed()` call) therefore happens first, and the fast path also works **after** a re-exec
  into a project venv, as for `claude-hook`. Neither `parrot.cli` nor Click is ever imported on
  this path.
- `dispatchers/claude.py:625`: stop deriving the hook from `worktree_environment.__file__`. Emit
  `shlex.join([sys.executable, "-m", "parrot.sdd.scripts.worktree_environment", "--hook"]) + " || exit 2"`
  (spec rev 0.5 C19 = D4c).
- Tests: the fast path never imports `click`/`parrot.cli`; byte-equivalent behaviour (exit code,
  stdout JSON) to running the module with `--hook` on allow, deny and rewrite payloads; the
  dispatcher hook form.
- Append the `--hook` round trip to the S4 report (`sdd/state/FEAT-633/spikes/S4-launcher-overhead.md`,
  created by TASK-4072): method, numbers, verdict against the budget.

**NOT in scope**:
- Moving `worktree_environment` or its re-export shim (TASK-4085).
- Rewriting the two shipped frontmatters (TASK-4089), the widened `test_no_repo_script_refs`
  (TASK-4090) and C3's foreign-repo guard check (TASK-4091).
- The general `parrot sdd run <helper>` Click command (TASK-4091). This fast path handles exactly
  one argv.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | `SDD_HOOK_ARGV` + fast path in `main_parrot.load()` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py` | MODIFY | `:625` hook command no longer derived from `__file__` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | `test_programmatic_claude_protection_does_not_depend_on_project_settings` (`:285-295`, defined at `:286`) asserts `"worktree_environment.py" in command` (`:294`); update it to assert `-m parrot.sdd.scripts.worktree_environment --hook` (spec rev 0.5 C19 / D4c) |
| `packages/ai-parrot/tests/launcher/test_launcher_sdd_hook.py` | CREATE | Fast-path tests (no Click import, behaviour parity, post-re-exec) |
| `sdd/state/FEAT-633/spikes/S4-launcher-overhead.md` | MODIFY | `--hook` round-trip row + verdict |

---

## Codebase Contract (Anti-Hallucination)

> Verified on dev `9f51c7735`. `launcher.py`, `parrot/sdd/` and the S4 report do not exist yet;
> their shapes come from the dependency tasks' blueprints.

### Verified Imports
```python
# after TASK-4085:
from parrot.sdd.scripts.worktree_environment import main   # def main() -> None (today: flows/dev_loop/worktree_environment.py:464)
# after TASK-4071/4072 (TASK-4072 blueprint):
#   launcher: is_managed, LOOP_GUARD_ENV, _dispatch(script, load_entry), main_parrot()
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py (484 lines, stdlib-only)
#   :464 def main() -> None:   # argparse; `--hook` is required=True (:467); reads the hook payload from stdin
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py
#   :66  from parrot.flows.dev_loop import worktree_environment
#   :621-627 if profile.subagent in {"sdd-worker", "sdd-coder"}:
#                hook_command = (shlex.join([sys.executable, str(Path(worktree_environment.__file__).resolve()), "--hook"]) + " || exit 2")
# TASK-4072 blueprint (launcher.py):
#   def _dispatch(script: str, load_entry: Callable[[], Callable[[], Any]]) -> int   # re-exec decision first, then load_entry()()
#   def main_parrot() -> int:  def load(): from parrot.cli import cli; return cli;  return _dispatch("parrot", load)
# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
#   :286 test_programmatic_claude_protection_does_not_depend_on_project_settings — asserts "worktree_environment.py" in command (:294)  [rev 0.5: def is :286; :285 is @parametrize]
```

### Does NOT Exist
- ~~`parrot.launcher`~~ / ~~`parrot.sdd.scripts.worktree_environment`~~ on dev today (dependencies create them).
- ~~A `parrot sdd` Click group~~ until TASK-4091. The fast path must not depend on it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/launcher/test_launcher_sdd_hook.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S4-launcher-overhead.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#main",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_run_options"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`parrot/knowledge/wiki/entry.py:18-29` *[rev 0.5: was :18-28]* (`HOOK_ARGV = ["claude-hook"]`): an exact argv match
answered before the heavy CLI is imported.

### Key Constraints
- Exact match only: `sys.argv[1:] == SDD_HOOK_ARGV`. Any other `parrot sdd …` argv goes to Click.
- `parrot.launcher` keeps its stdlib-only import boundary (TASK-4072's
  `test_launcher_stdlib_only`). Import `parrot.sdd.scripts.worktree_environment` lazily inside
  `load()`, never at module top.
- The hook must fail closed exactly as today. A Python error propagates as a non-zero exit, and the
  ` || exit 2` suffix in the frontmatter turns that into a block.

### References in Codebase
- Spec §3 M1 lines 293-296; §7 "Hook latency budget (S4)" (line 1152). *[rev 0.5: were 285-291 / ~1015]*
- Spec §3 "Rev 0.5 decision clauses", D4 (c). *[rev 0.5]*
- Proposal `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C16 items 2-3.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-4072 and TASK-4085 are done. *[rev 0.5]* The programmatic hook form is fixed by C19 / D4c.
2. Add the fast path to `main_parrot.load()`.
3. Update `dispatchers/claude.py:625` and its test.
4. Write `test_launcher_sdd_hook.py`; measure and append the S4 row.

### `packages/ai-parrot/src/parrot/launcher.py` (MODIFY)
```python
SDD_HOOK_ARGV = ["sdd", "run", "worktree_environment", "--hook"]


def main_parrot() -> int:
    """``parrot`` console script (real entry ``parrot.cli:cli``; keeps the C16 sdd-hook fast path)."""
    def load() -> Callable[[], Any]:
        if sys.argv[1:] == SDD_HOOK_ARGV:
            from parrot.sdd.scripts.worktree_environment import main as hook_main

            def run_hook() -> int:
                sys.argv[1:] = ["--hook"]
                hook_main()
                return 0

            return run_hook
        from parrot.cli import cli
        return cli
    return _dispatch("parrot", load)
```

### FILL IN checklist
- [ ] `test_fast_path_never_imports_click`: run `python -c "…main_parrot()…"` with the hook argv and an
      allow payload on stdin, then assert `"click" not in sys.modules` and `"parrot.cli" not in sys.modules`
      (print them from an atexit hook or the subprocess).
- [ ] `test_fast_path_matches_module_behaviour`: for an allow, a deny and a rewrite payload, the exit code
      and stdout JSON equal those of `python -m parrot.sdd.scripts.worktree_environment --hook`.
- [ ] `test_fast_path_survives_reexec`: in TASK-4072's fake managed home, the chain still answers the hook
      without importing Click in either interpreter.
- [ ] Dispatcher test: the command ends with ` || exit 2`, contains `-m parrot.sdd.scripts.worktree_environment --hook`
      *[rev 0.5 D4c]*, and contains no `packages/` or `flows/dev_loop` path.

---

## Acceptance Criteria

- [ ] `parrot sdd run worktree_environment --hook` answers `PreToolUse` payloads with the same exit code
      and stdout as the module itself, and imports neither `click` nor `parrot.cli` (test-enforced).
- [ ] It works in a non-managed venv and after a managed→project re-exec.
- [ ] `dispatchers/claude.py` no longer builds the hook from `worktree_environment.__file__`; it emits
      `<sys.executable> -m parrot.sdd.scripts.worktree_environment --hook || exit 2` *[rev 0.5 D4c]*.
- [ ] The S4 report has a `--hook` row with method, median/p95 and a verdict against the budget.
- [ ] `ruff check` passes on every touched Python file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/launcher/test_launcher_sdd_hook.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

See the FILL IN checklist: no-Click import, behaviour parity on allow/deny/rewrite payloads,
post-re-exec survival, and the dispatcher hook form.

---

## Agent Instructions

1. Use the programmatic hook form fixed by spec rev 0.5 C19 / D4c (see Scope); do not use the
   PATH-dependent `parrot sdd run …` form in `dispatchers/claude.py`. The latency budget is C19 item 4 /
   D17: the S4 targets as written in the Acceptance Criteria; report the measured numbers against them
   and do not pick a new budget.
2. Do not touch shipped markdown, the shim, or `parrot sdd`'s Click group.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
