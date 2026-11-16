# HOTFIX-sandbox-extra-write-paths-1: Operator-declared extra writable paths for the SDD sandbox

**Feature**: sandbox-extra-write-paths (BRIEF-sandbox-extra-write-paths)
**Spec**: sdd/briefs/sandbox-extra-write-paths.brief.md
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
The native sandbox denies writes to `/tmp/navigator/log`, the navconfig log directory, so the `parrot` CLI
cannot run inside a sandboxed sdd-worker / sdd-coder. See the brief.

## Scope
- `worktree_environment.py` (standard library only, must never raise from the hook path):
  - `EXTRA_WRITE_PATHS_KEY = "sandbox_extra_write_paths"`.
  - `load_extra_write_paths(primary: Path) -> tuple[Path, ...]` — strict reader of
    `[tool.parrot.sdd].sandbox_extra_write_paths` in `<primary>/pyproject.toml`. Missing file/table/key →
    `()`. Raises `ValueError` when the TOML is unreadable, the value is not a list of strings, or an entry:
    is not absolute; is not already normalized (`..`, `.`, trailing or doubled slashes); resolves to a path
    with fewer than two components (`/`, `/tmp`, `/home`, `/var`); is equal to, inside, or an ancestor of the
    primary checkout, the user's home directory, or a shared environment of the primary checkout. Entries
    are symlink-resolved and de-duplicated; the resolved path is what is granted.
  - `sandbox_extra_write_dirs(root, git_dir) -> tuple[Path, ...]` — the hook-path helper. `()` when
    `git_dir is None` or `root` is the primary checkout (its `pyproject.toml` is session-writable, hence
    untrusted). Any `ValueError` → `()` (fail closed). Creates each directory (`mkdir -p`), skipping one that
    cannot be created.
  - `protected_argv`: `--bind <dir> <dir>` for each, right after the scratch-root bind (after the tmpfs).
- `native_claude_sandbox.py`:
  - `native_sandbox_settings`: extend `allow_paths` with `_we.sandbox_extra_write_dirs(root, git_dir)`.
  - `_prefix_writable_roots`: include the same directories.
  - `load_launch_config`: call `_we.load_extra_write_paths(primary)` and re-raise its `ValueError` with the
    existing `Invalid sandbox launch config in <path>` prefix, so a bad value refuses to launch (exit 2).
    The return type stays `tuple[list[str], bool]`.
- Root `pyproject.toml`: `sandbox_extra_write_paths = ["/tmp/navigator"]` under `[tool.parrot.sdd]`.
- `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md`: document the key and its rules.
- Tests in the two existing test files (see Acceptance Criteria).

**NOT in scope**: changing navconfig or `etc/navigator.ini`; a CLI flag or dispatch-profile field for extra
paths; making all of `/tmp` writable in the native backend.

## Files to Create / Modify
- MODIFY `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`
- MODIFY `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`
- MODIFY `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py`
- MODIFY `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py`
- MODIFY `pyproject.toml`
- MODIFY `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md`

## Codebase Contract
- Verified: `worktree_environment.py:243` `def coder_evidence_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]`
  (pattern: `()` for `git_dir is None` / `primary == root`, never raises);
  `:282` `def claude_scratch_root() -> Path`; `:299` `def protected_argv(cwd, argv, *, derive_pythonpath=False)`;
  `:342` `"/tmp",` (the tmpfs mount); `:346` `scratch_root = claude_scratch_root()`;
  `shared_environments(cwd)` returns the shared environment directories.
- Verified: `native_claude_sandbox.py:429` `allow_paths = [root, git_dir, _we.claude_scratch_root(), *_we.worktree_admin_dirs(root, git_dir)]`;
  `:728` `def load_launch_config(primary: Path) -> tuple[list[str], bool]`, `:769` `return domains, gh_token`,
  error prefix `f"Invalid sandbox launch config in {config_path}"`; `:927` `def _prefix_writable_roots(cwd: Path)`;
  `_native_roots(cwd)` returns `(root, git_dir, primary)`; `launch_worker` returns 2 on a config `ValueError`.
- Verified: tests — `test_worktree_environment.py` helpers `_registered_feature_worktree(tmp_path)` → `(main, worktree)`
  and `_writable_binds(argv)`; `test_native_claude_sandbox.py` fixture `linked` → `(feature, main)`,
  `_launch_harness(linked, monkeypatch, primary_toml=...)`, `test_malformed_launch_config_exits_2`.
- Does NOT exist: `sandbox_extra_write_paths`, `load_extra_write_paths`, `sandbox_extra_write_dirs`.

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "pyproject.toml", "action": "MODIFY"},
    {"path": "wiki/sdd-tooling/dev_loop/claude-native-sandbox.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#protected_argv",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#coder_evidence_dirs",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#load_launch_config",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_prefix_writable_roots"
  ]
}
```

## Acceptance Criteria
- A linked worktree whose primary declares a valid extra path gets it in native `allowWrite` and as a legacy
  `--bind` placed after the `--tmpfs /tmp` mount; the directory is created when absent.
- `/tmp`, `/`, a relative path, a non-normalized path, the primary checkout, a path inside it, its shared
  environment, the home directory and a path inside it are each rejected by `load_extra_write_paths`; with
  such a config `/tmp` is never in `allowWrite` nor bound, and `launch_worker` exits 2.
- A worktree `pyproject.toml` declaring the key is ignored; the primary checkout gets no extra bind.
- An invalid config never makes `protected_argv` raise.
- The two test files pass; `ruff check` passes on the changed files.

## Validation Commands
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

## Completion Note
