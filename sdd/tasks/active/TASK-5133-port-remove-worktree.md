# TASK-5133: Port `scripts/remove_worktree.py` to `parrot sdd worktree list|remove`

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec G7, §2 "`/remove-worktree` ships (G7, M5)" and §3 Module 5. Shipped assets (`sdd-fix`, `sdd-status`, the
`worktree-management` rule) already send users to `/remove-worktree`, but the command calls
`scripts/remove_worktree.py`, which exists only where someone copied it by hand (missing in flowtask → broken).
This task moves the script into the package and mounts it as `parrot sdd worktree list` / `remove`; TASK-5134
rewrites and ships the command. ai-parrot keeps `scripts/remove_worktree.py` as a compatibility shim.

---

## Scope

- Create `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`: a **behavior-preserving** port of
  `scripts/remove_worktree.py` (same sub-commands, flags, gates, messages), with `main(argv=None)`.
- Replace the `Path(__file__)` root with `repo_root()` = parent of
  `git rev-parse --path-format=absolute --git-common-dir` (the **primary** checkout even when run inside a linked
  worktree, as the old `Path(__file__).parent.parent` root was).
- Turn `scripts/remove_worktree.py` into a shim, same shape as `scripts/sdd/ensure_worktree.py`.
- Mount the verbs in `cli.VERBS["worktree"]`: `"list"` and `"remove"` → module `remove_worktree`.
- Add tests to `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`.

**NOT in scope**: the command markdown, codex/google twins, `check_asset_sync.py`, `_assets/` (TASK-5134);
`uninstall`/`status` changes in `cli.py` (TASK-5135); new flags or new safety gates.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | CREATE | Packaged port with `main(argv)` and `repo_root()` |
| `scripts/remove_worktree.py` | MODIFY | Whole file → compatibility shim |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `VERBS["worktree"]` gains `list`, `remove` |
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | MODIFY | Port tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.scripts import remove_worktree as _impl   # created by this task (shim + tests)
from parrot.sdd.cli import VERBS, mounted_modules          # verified: cli.py:175, :238
```

### Existing Signatures to Use
```python
# scripts/remove_worktree.py (423 lines, ai-parrot only) — the source of the port
REPO_ROOT = Path(__file__).resolve().parent.parent          # line 46  (replace)
WORKTREE_DIR = REPO_ROOT / ".claude" / "worktrees"           # line 47  (replace)
PROTECTED_BRANCHES = {"main", "dev", "staging", "master"}    # line 48
def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess   # line 51; uses REPO_ROOT at line 54
class Worktree  # line 59 (dataclass: path, branch, registered, primary, live_processes; name/dirty_files/unpushed/pr_state)
def live_processes_in(path: Path) -> list[tuple[int, str]]   # line 140 (/proc/<pid>/cwd — Linux only)
def discover() -> list[Worktree]                             # line 168; REPO_ROOT at 187, WORKTREE_DIR at 195-196
def cmd_list(args) -> int                                    # line 209
def _match(worktrees, target) -> list[Worktree]              # line 243
def _remove_one(wt, args) -> int                             # line 272
def cmd_remove(args) -> int                                  # line 354
def main() -> int                                            # line 393; parser.parse_args() with no argv (line 420)
# REPO_ROOT / WORKTREE_DIR are used ONLY at lines 46, 47, 54, 187, 195, 196 (verified: grep -n).

# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {   # line 175
    "worktree": {                                                    # line 176
        "ensure": ("ensure_worktree", (), "Create or reuse the feature/hotfix worktree (idempotent)."),  # line 177
        "status": ("worktree_status", (), "Discover SDD worktrees and report task state and health."),  # line 178
        "guard": ("worktree_environment", (), "Serve the PreToolUse shared-environment guard (--hook)."), # line 179
def _mount(noun, verb, module, prefix, help_)   # line 242 — calls parrot.sdd.scripts.<module>.main([*prefix, *args])
# scripts/sdd/ensure_worktree.py lines 1-8 — the shim pattern (docstring, import as _impl, __main__, sys.modules alias)
```
`packages/ai-parrot/tests/sdd/test_sdd_cli.py::test_sdd_cli_mounts_every_helper` (line 98) requires every
packaged module with a `main` to be mounted and every `parrot sdd <noun> <verb> --help` to exit 0 — mounting both
verbs satisfies it (`main(["list", "--help"])` exits 0 via argparse).

### Does NOT Exist
- ~~`parrot sdd worktree list` / `remove`~~ — today `worktree` has only `ensure`, `status`, `guard` (cli.py:177-179).
- ~~`parrot.sdd.scripts.remove_worktree`~~ — created by this task.
- ~~`scripts/sdd/remove_worktree.py`~~ — the old script lives at `scripts/remove_worktree.py` (not under `scripts/sdd/`);
  do NOT add `remove_worktree` to the `MOVED` tuple of the test file (those tests expect a `scripts/sdd/` shim).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py", "action": "CREATE"},
    {"path": "scripts/remove_worktree.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/remove_worktree.py#run",
    "sym:scripts/remove_worktree.py#Worktree",
    "sym:scripts/remove_worktree.py#discover",
    "sym:scripts/remove_worktree.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#mounted_modules"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Do not use `git rev-parse --show-toplevel`**: inside a worktree it returns the worktree, which breaks orphan-dir
  discovery under `<primary>/.claude/worktrees/`. Use `--path-format=absolute --git-common-dir` and take `.parent`.
- Resolve the root **once** in `main()` and keep it in a module variable `_ROOT` read by `run()` / `discover()` —
  the port must not run git on every `run()` call, and the old code had a single process-wide root.
- Keep `print(...)` output: this is a terminal CLI helper whose stdout/stderr text is the interface (the other
  `parrot.sdd.scripts` CLIs print too). Keep the module docstring, rewriting its "Usage" block to
  `parrot sdd worktree list|remove …`.
- Outside git: `repo_root()` exits 1 with `error: not a git repository`.

---

## Implementation Blueprint

### Steps (in order)
1. `cp scripts/remove_worktree.py packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` — *why*: the port
   is behavior-preserving; start from the exact text.
2. In the new file apply the edits below (constants → `repo_root()`/`_ROOT`, `run`, `discover`, `main(argv)`) —
   *why*: those are the only lines that depend on the script's location.
3. Replace `scripts/remove_worktree.py` with the shim — *why*: ai-parrot docs/muscle memory keep working.
4. Add the two `VERBS` rows — *why*: `parrot sdd worktree list|remove` is the shipped interface (TASK-5134).
5. Add tests — *why*: AC-1..AC-4.

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (CREATE — from the copied file)
```python
# REPLACE lines 46-47 (REPO_ROOT / WORKTREE_DIR) with:
_ROOT: Path | None = None


def repo_root() -> Path:
    """Primary checkout root: parent of ``git rev-parse --path-format=absolute --git-common-dir``.

    Exits 1 with ``error: not a git repository`` outside git.
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True, capture_output=True
    )
    if proc.returncode != 0:
        sys.exit("error: not a git repository")
    return Path(proc.stdout.strip()).parent


def _root() -> Path:
    """The root resolved by ``main()`` (resolved lazily when a function is called directly, e.g. from tests)."""
    global _ROOT
    if _ROOT is None:
        _ROOT = repo_root()
    return _ROOT


# run(): line 54 `cmd, cwd=str(cwd or REPO_ROOT), ...` -> `cmd, cwd=str(cwd or _root()), ...`
# discover(): line 187 `REPO_ROOT.resolve()` -> `_root().resolve()`;
#   lines 195-196: `worktree_dir = _root() / ".claude" / "worktrees"` then use `worktree_dir` in both lines.

# REPLACE `def main() -> int:` (line 393) and `args = parser.parse_args()` (line 420):
def main(argv: Sequence[str] | None = None) -> int:
    """argparse CLI — ``list [--check-pr]`` and ``remove [target] [--stale] [--delete-branch] [--force]
    [--dry-run]``, exactly as the old ``scripts/remove_worktree.py``."""
    global _ROOT
    # FILL IN: keep the parser body verbatim (prog="parrot sdd worktree"), then
    #   args = parser.parse_args(argv); _ROOT = repo_root(); return args.func(args)
    #   (parse first so `--help` works outside git).
    raise NotImplementedError
# Add `from typing import Sequence` to the imports; keep `if __name__ == "__main__": sys.exit(main())`.
```
**Why**: every other line stays byte-identical to the script so the gates and messages are provably unchanged.

### `scripts/remove_worktree.py` (MODIFY — whole file)
```python
# occurrences: 1 (verified: grep -c 'REPO_ROOT = Path(__file__).resolve().parent.parent' scripts/remove_worktree.py)
"""Compatibility shim — moved to ``parrot.sdd.scripts.remove_worktree`` (FEAT-795); use ``parrot sdd worktree``."""
import sys

from parrot.sdd.scripts import remove_worktree as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "worktree": {' cli.py)
# AFTER — insert below the `"guard": ("worktree_environment", …)` row inside `"worktree": {` (verified: cli.py:176-179)
        "list": ("remove_worktree", ("list",), "List worktrees and orphan dirs: dirty, unpushed, PR, live processes."),
        "remove": ("remove_worktree", ("remove",), "Remove a worktree safely (refuses a live sdd-worker, dirty, unpushed)."),
```

### `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` (MODIFY)
```python
# AFTER — append at the end of the file
def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "feature-x"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"],
                   cwd=path, check=True)
    return path


# FILL IN: tests (use monkeypatch.chdir and reset `remove_worktree._ROOT = None` in each test):
#   test_remove_worktree_root_is_primary_checkout (git worktree add .claude/worktrees/wt -b wt; chdir into it;
#     repo_root() == primary path), test_remove_worktree_list_and_dry_run (main(["list"]) == 0; create the worktree,
#     main(["remove", "wt", "--dry-run"]) == 0 and the directory still exists),
#   test_remove_worktree_refuses_dirty (untracked+modified file in wt -> main(["remove", "wt"]) != 0, dir kept),
#   test_remove_worktree_shim_aliases (importing scripts/remove_worktree.py by path yields the packaged module),
#   test_worktree_verbs_mounted ("remove_worktree" in mounted_modules(); VERBS["worktree"]["list"][0] == "remove_worktree").
```

### FILL IN checklist
- [ ] port edits at lines 46-47, 54, 187, 195-196, 393/420 only.
- [ ] `main(argv)` — parse, then resolve root; bounded by AC-1, AC-2.
- [ ] the 5 tests listed.

---

## Acceptance Criteria

- [ ] AC-1: `parrot sdd worktree list` and `parrot sdd worktree remove` accept exactly the old flags and keep every
      safety gate (primary, protected branch, live process, dirty, unpushed) with the same messages.
- [ ] AC-2: run from inside a linked worktree, the root is the primary checkout.
- [ ] AC-3: `python scripts/remove_worktree.py list` still works in ai-parrot (shim).
- [ ] AC-4: `test_sdd_cli.py::test_sdd_cli_mounts_every_helper` passes (both verbs `--help` exit 0).
- [ ] `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py::test_sdd_cli_mounts_every_helper -q`

---

## Test Specification

See the blueprint; rows are spec §4 "Unit Tests (`test_scripts_ledger_worktree.py`, extend)" plus the shim and
mount checks.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug parrot-sdd-install-remove --feature-id FEAT-795`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/parrot-sdd-install-remove.json`
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5133 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
