# TASK-4609: Sync native artifacts from the ensure_worktree CLI

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4608
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `python -m scripts.sdd.ensure_worktree` is how every SDD lane
provisions a worktree — `/sdd-start`, `sdd-worker`, `sdd-planner`,
`sdd-research`, `sdd-autopilot` and `/sdd-brief`. This task makes that command
hand back a worktree whose native artifacts are already in place.

The sync call goes in **`main()`, not `ensure()`** (spec §3 M4 "Decision").
`ensure()` returns `tuple[Path, bool]` and is called directly by 14 assertions
in `tests/sdd_scripts/test_ensure_worktree.py`; `main()` runs after both the
create branch and the reuse branch, so one call site there covers everything
the CLI returns while leaving that contract — and those tests — untouched.

The hard constraint is **stdout**: `sdd-worker.md:251` does
`WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree …)`. One stray `print`
of a warning corrupts the path for every agent in the repo.

---

## Scope

- Add `--no-native-sync` and `--no-autobuild` to the argparse parser.
- After `path, created = ensure(...)` in `main()`, call
  `sync_native_artifacts(main_root=repo_root, target=path, autobuild=not args.no_autobuild)`
  unless `--dry-run` or `--no-native-sync`.
- Write every `report.warnings` entry to **stderr**, prefixed `warning: `.
- Add a `"native"` object to the `--json` payload.
- Keep the bare-stdout and exit-code contracts exactly as they are.
- Extend `tests/sdd_scripts/test_ensure_worktree.py`.

**NOT in scope**: changing `ensure()`'s signature, parameters or return value;
touching its 14 existing call sites; `worktree_manager.py` (TASK-4610);
`baseline.py` (TASK-4611).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/ensure_worktree.py` | MODIFY | CLI flags + the sync call + JSON key |
| `tests/sdd_scripts/test_ensure_worktree.py` | MODIFY | CLI wiring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.native_artifacts import NativeSyncReport, sync_native_artifacts
# available after TASK-4608; this script already imports from `parrot` transitively
# via scripts.sdd.sdd_meta -> parrot.knowledge.wiki.ledger.sdd_meta (verified:
# scripts/sdd/sdd_meta.py:10), so importing parrot here adds no new dependency.
```

### Existing Signatures to Use
```python
# scripts/sdd/ensure_worktree.py
def ensure(plan: WorktreePlan, *, repo_root: Path, sync: bool = True,
           require_paths: Sequence[str] = (), dry_run: bool = False,
           ) -> tuple[Path, bool]:                  # line 49 — DO NOT CHANGE
def main(argv: Sequence[str] | None = None) -> int:  # line 265
    parser.add_argument("--no-sync", ...)            # line 291 — about git fetch, NOT this feature
    parser.add_argument("--dry-run", ...)            # line 292
    parser.add_argument("--json", ...)               # line 293 (occurrences: 1)
    repo_root = Path.cwd()                           # line 343
    path, created = ensure(                          # line 344 (occurrences: 1)
    if args.json:                                    # line 352
    "created": created,                              # line 364 (occurrences: 1)
    print(str(path))                                 # line 369 — the bare-stdout contract
    return 0                                         # line 371
except Exception as e:                               # line 373
    sys.stderr.write(f"Error: {e}\n")                # line 374 — the stderr idiom to follow
```

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py (TASK-4606..4608)
def sync_native_artifacts(*, main_root: Path, target: Path,
                          manifest: NativeManifest | None = None,
                          autobuild: bool = True) -> NativeSyncReport
class NativeSyncReport:  # enabled, copied, skipped, built, missing, warnings
```

```python
# tests/sdd_scripts/test_ensure_worktree.py
from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main   # line 11
SLUG = "demo-feature"; FEATURE_ID = "FEAT-999"                              # lines 14-15
@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:                                   # line 19 (occurrences: 1)
    """bare `origin.git` <- `work` clone, `dev` branch carrying the SDD artifacts."""
```

### Does NOT Exist
- ~~`args.no_native_sync` / `args.no_autobuild`~~ — THIS task adds both flags.
  Note argparse maps `--no-native-sync` to `args.no_native_sync`.
- ~~a third element in `ensure()`'s return~~ — it returns exactly
  `(path, created)`. Never unpack three values.
- ~~`--no-sync` as a native-sync switch~~ — it already exists and means
  "skip `git fetch origin <base>`" (`ensure_worktree.py:291`). Do not overload it.
- ~~`logger` usage in `main()`~~ — this CLI writes operator messages with
  `sys.stderr.write` (line 374); follow that, and never `print` a warning.
- ~~a non-zero exit for a native-sync problem~~ — the command still returns 0.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/ensure_worktree.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_ensure_worktree.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/ensure_worktree.py#main",
    "sym:scripts/sdd/ensure_worktree.py#ensure",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py#sync_native_artifacts"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `repo_root = Path.cwd()` (line 343) IS the main checkout — `/sdd-task` and
  every documented invocation run from the repo root, and `ensure()` already
  relies on this. Pass it as `main_root`.
- Order: sync **after** `ensure()` returns, so a refused or discarded worktree
  is never populated.
- `--dry-run` must perform no copy and no build.
- The import of `parrot.flows.dev_loop.native_artifacts` is top-level, matching
  the file's existing import block; `scripts.sdd.sdd_meta` already pulls
  `parrot` in, so this is not a new dependency edge.

### References in Codebase
- `.claude/agents/sdd-worker.md:251` — the `$(…)` capture that makes stdout sacred.
- `scripts/sdd/ensure_worktree.py:373-375` — the error/stderr idiom.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two flags next to `--json` — *why*: operators and the dev-loop need
   an escape hatch that does not require an env var.
2. Call the sync after `ensure()` — *why*: one call site covers create and reuse.
3. Emit warnings on stderr — *why*: stdout is a captured value, not a log.
4. Add the `"native"` JSON object — *why*: `sdd-planner`/`sdd-research` parse
   this payload and should be able to see what was copied or missed.
5. Extend the tests — *why*: the stdout contract is exactly the kind of thing
   that breaks silently.

### `scripts/sdd/ensure_worktree.py` (MODIFY — 1 of 3)
```python
# occurrences: 1 (verified: grep -c '    parser.add_argument("--json", action="store_true", help="Output JSON instead of bare path.")' scripts/sdd/ensure_worktree.py)
# AFTER — insert below `parser.add_argument("--json", ...)` (verified: scripts/sdd/ensure_worktree.py:293)
    parser.add_argument(
        "--no-native-sync",
        action="store_true",
        help="Do not copy declared native build artifacts into the worktree (FEAT-722).",
    )
    parser.add_argument(
        "--no-autobuild",
        action="store_true",
        help="Copy native artifacts that exist, but never build a missing one (FEAT-722).",
    )
```
**Why**: `--no-native-sync` is the full opt-out (equivalent to
`PARROT_WORKTREE_SYNC_NATIVE=0`), `--no-autobuild` keeps the copy but forbids
compiling. Both default to False, so existing invocations gain the sync.

### `scripts/sdd/ensure_worktree.py` (MODIFY — 2 of 3)
```python
# occurrences: 1 (verified: grep -c '        path, created = ensure(' scripts/sdd/ensure_worktree.py)
# AFTER — insert below the closing `)` of the `path, created = ensure(...)` call
#   (verified: scripts/sdd/ensure_worktree.py:344-350), i.e. before `if args.json:`
        native = NativeSyncReport(enabled=False)
        if not args.dry_run and not args.no_native_sync:
            native = sync_native_artifacts(
                main_root=repo_root,
                target=path,
                autobuild=not args.no_autobuild,
            )
        for warning in native.warnings:
            # stderr ONLY: stdout is captured as the worktree path by callers
            # (.claude/agents/sdd-worker.md:251).
            sys.stderr.write(f"warning: {warning}\n")
```
**Why**: `ensure()` has already returned a verified worktree at this point, and
this is the single place both the create and the reuse branch pass through. The
default `NativeSyncReport(enabled=False)` keeps the JSON payload well-formed
when the sync was skipped.

### `scripts/sdd/ensure_worktree.py` (MODIFY — 3 of 3)
```python
# occurrences: 1 (verified: grep -c '                        "created": created,' scripts/sdd/ensure_worktree.py)
# AFTER — insert below `"created": created,` inside the json.dumps dict (verified: ensure_worktree.py:364)
                        "native": {
                            "enabled": native.enabled,
                            "copied": native.copied,
                            "skipped": native.skipped,
                            "built": native.built,
                            "missing": [entry.model_dump() for entry in native.missing],
                            "warnings": native.warnings,
                        },
```
**Why**: `MissingArtifact` is a Pydantic model, so `model_dump()` is required —
`json.dumps` cannot serialise it directly. Keys mirror `NativeSyncReport`
one-for-one so the payload needs no separate documentation.

### FILL IN checklist
- [ ] none for the three blocks above — they are complete. The only judgement
      left is in the tests below.

---

## Acceptance Criteria

- [ ] `python -m scripts.sdd.ensure_worktree --slug … --feature-id …` prints
      **only** the worktree path on stdout, even when warnings are emitted
- [ ] The command still exits 0 when the native sync reported missing artifacts
      or a failed build
- [ ] A created worktree contains the declared artifacts afterwards; a *reused*
      one is re-synced when the main checkout's artifact changed
- [ ] `--json` output contains a `native` object with the six documented keys
- [ ] `--no-native-sync` copies nothing; `--no-autobuild` copies but never
      builds; `--dry-run` does neither
- [ ] `ensure()` is unchanged: `git diff` shows no edit between
      `ensure_worktree.py:49` and `:126`, and the 14 pre-existing
      `ensure(...)` call sites in the test file are untouched
- [ ] `pytest tests/sdd_scripts/test_ensure_worktree.py -q` passes, including
      every pre-existing test
- [ ] `ruff check scripts/sdd/ensure_worktree.py tests/sdd_scripts/test_ensure_worktree.py` clean

---

## Validation Commands

- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`
- `pytest tests/sdd_scripts/test_brief_scaffold_integration.py -q`

---

## Test Specification

Extend `tests/sdd_scripts/test_ensure_worktree.py`, reusing its `tmp_git_repo`
fixture (line 19) and its `monkeypatch.chdir` style for `main()`:

```python
def _declare_stub_group(repo: Path, artifact_rel: str) -> None:
    """Append a [tool.parrot.worktree] table to the sandbox repo declaring one group.

    Keeps every test off the real cython-core / navrules-pyo3 groups, which would
    compile the actual extensions.
    """


def test_main_syncs_on_create_and_reuse(tmp_git_repo, monkeypatch, capsys):
    """The artifact lands in the new worktree, and a reuse re-syncs a changed one."""


def test_main_stdout_is_only_the_path(tmp_git_repo, monkeypatch, capsys):
    """Warnings go to stderr; stdout holds exactly one line — the path."""


def test_main_json_carries_native_report(tmp_git_repo, monkeypatch, capsys):
    """--json payload has a `native` object with enabled/copied/skipped/built/missing/warnings."""


def test_main_no_native_sync_flag(tmp_git_repo, monkeypatch, capsys):
    """--no-native-sync returns the worktree, exit 0, nothing copied."""


def test_main_dry_run_skips_sync(tmp_git_repo, monkeypatch, capsys):
    """--dry-run performs no copy and no build."""


def test_ensure_signature_unchanged(tmp_git_repo):
    """ensure() still returns a 2-tuple — the 14 existing call sites rely on it."""
    import inspect
    from scripts.sdd.ensure_worktree import ensure
    assert "autobuild" not in inspect.signature(ensure).parameters
    assert "sync_native" not in inspect.signature(ensure).parameters
```

Write real bodies for the first five; the docstrings state exactly what each
must assert. Declare a **stub group** in the sandbox repo's `pyproject.toml` for
every test — never let a test trigger the real builds.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4608 must be `"done"` (this task needs
   `sync_native_artifacts`'s `autobuild` parameter)
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint
   blocks; the three anchors were verified at `a99dd4fe9`
5. **Update status** in the per-spec index → `"in-progress"`, commit only it
6. **Implement** — write the three blocks as given, then the tests
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4609 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) — seat: gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-10-22
**Notes**: scripts/sdd/ensure_worktree.py calls the sync. test_ensure_worktree.py 25 passed; test_brief_scaffold_integration.py 1 passed.

**Deviations from spec**: none
