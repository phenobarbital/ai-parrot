# HOTFIX-c61e28722cca-1: Bind the sdd-coder durable store writable from a linked worktree

**Feature**: brief `sandbox-coder-store-readonly` (ledger `issue:c61e28722cca`)
**Spec**: `sdd/briefs/sandbox-coder-store-readonly.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`resolve_durable_root` puts the sdd-coder evidence store at
`<main checkout>/artifacts/logs/sdd-coder-usage`, deliberately outside any
worktree so it survives `git worktree remove`. The SDD sandbox mounts the whole
primary checkout read-only except four narrow exceptions, and `artifacts/` is
not one of them. From inside a linked worktree the store is therefore readable
but not writable, so `parrot sdd task review prepare` and
`parrot sdd task finalize` both fail.

This task adds the fifth exception, scoped to that one directory. See the
brief's "Root cause" and "Research findings" for the full analysis.

---

## Scope

- Add the module constant `CODER_EVIDENCE_DIR` to `worktree_environment.py`.
- Add `coder_evidence_dirs(root, git_dir)`, a narrow twin of
  `shared_ledger_dirs`, which creates the directory on the host and returns it
  only for a linked worktree.
- Bind it writable in `protected_argv` (Bubblewrap backend).
- Add it to `allow_paths` in `native_sandbox_settings` (native backend).
- Write tests covering both backends, the primary-checkout no-op, the negative
  case (the rest of `artifacts/` stays read-only) and drift against
  `resolve_durable_root`.

**NOT in scope**:

- Changing `resolve_durable_root` or where the store lives.
- Making the sandbox honour a custom `SDD_CODER_TELEMETRY_DIR`. An
  env-controlled writable bind is a sandbox-escape surface
  (`SDD_CODER_TELEMETRY_DIR=/` would bind `/`). The default root only.
- Binding any other part of `artifacts/`. `artifacts/laya/` and the generator
  scripts must stay read-only.
- `validate_native_write_path` — it re-reads
  `native_sandbox_settings(root)["sandbox"]["filesystem"]["allowWrite"]`, so it
  picks the new path up with no edit of its own.
- `issue:cb467a1f6ade` (navconfig crash in the same two CLIs) — unrelated defect.
- The `unsupported_host` mislabel — that is HOTFIX-c61e28722cca-2.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `CODER_EVIDENCE_DIR`, `coder_evidence_dirs()`, bind in `protected_argv` |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | Extend `allow_paths` in `native_sandbox_settings` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | Bind tests, real-subprocess write test, drift guard |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` | MODIFY | Document the fifth writable exception |
| `.claude/rules/worktree-management.md` | MODIFY | Twin of the asset above (`git add -f`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# worktree_environment.py is stdlib-only BY CONTRACT. Its module docstring
# (worktree_environment.py:1-5) states: "This file deliberately uses only the
# standard library and can run directly as a Claude hook, even when importing
# the rest of Parrot is unavailable."
# DO NOT import parrot.flows.dev_loop.sdd_coder.telemetry from it.
from pathlib import Path  # already imported: worktree_environment.py:13

# native_claude_sandbox.py already imports the policy module as `_we`:
# verified by `_we.shared_ledger_dirs(...)` at native_claude_sandbox.py:403
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:142
SHARED_LEDGER_DIR = Path(".parrot") / "ledger"

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:205-231
def shared_ledger_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
    if git_dir is None:
        return ()
    primary = git_dir.parent
    if primary == root:
        return ()
    ledger_dir = (primary / SHARED_LEDGER_DIR).resolve()
    if not ledger_dir.is_dir() or ledger_dir.is_relative_to(root):
        return ()
    return (ledger_dir,)

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:234-248
def claude_scratch_root() -> Path:
    root = CLAUDE_SCRATCH_ROOT
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root.resolve()

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py:251
def protected_argv(cwd: Path, argv: Sequence[str], *, derive_pythonpath: bool = False) -> list[str]:
    ...  # bind loop for the ledger is at line 308

# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:388
def native_sandbox_settings(
    cwd: Path, *, allowed_domains: Sequence[str] = (), include_sandbox: bool = True
) -> dict[str, Any]:
    ...  # allow_paths is built at lines 402-403

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py:150
#   resolved = (main_checkout / "artifacts" / "logs" / "sdd-coder-usage").resolve()
def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path: ...
```

### Does NOT Exist

- ~~`worktree_environment.CODER_EVIDENCE_DIR`~~ — this task creates it.
- ~~`worktree_environment.coder_evidence_dirs`~~ — this task creates it.
- ~~a shared constant exporting `artifacts/logs/sdd-coder-usage`~~ — the path is
  built inline at `telemetry.py:150` and nowhere else. There is nothing to
  import; duplicate it and guard the duplication with a test.
- ~~`native_claude_sandbox.CODER_EVIDENCE_DIR`~~ — the native backend reads the
  constant through `_we`, it does not define its own.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#shared_ledger_dirs",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#claude_scratch_root",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#protected_argv",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#native_sandbox_settings",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root"
  ]
}
```

---

## Implementation Notes

### Key constraints

- **Stdlib only** in `worktree_environment.py`. No `parrot.*` import, ever.
- **`mkdir` only on the linked-worktree branch**, after the `primary == root`
  early return. `test_primary_checkout_has_no_extra_ledger_bind`
  (`test_worktree_environment.py:489`) asserts the primary's writable binds are
  exactly `[scratch_root.resolve(), main.resolve()]`, so the primary path must
  stay a pure no-op with no filesystem side effect.
- **The directory must be created, not skipped when absent.** This is the one
  place the new helper differs from `shared_ledger_dirs`, which returns `()`
  for a missing dir. The store does not exist before the first execution, and
  bwrap cannot bind a missing path — so an absent directory here is the normal
  first-run case, not a reason to skip. `claude_scratch_root()`
  (`worktree_environment.py:234-248`) documents the identical reasoning.
- Keep the `is_relative_to(root)` guard: binding a path already inside the
  worktree would make it a mount point and break `git worktree remove` (the
  same hazard `protected_argv:301-305` already comments on).
- A `mkdir` failure (read-only parent, permissions) must degrade to `()`, never
  raise: `protected_argv` wraps **every** Bash call, so one raise denies the
  whole session — the hazard `existing_directory` (`worktree_environment.py:27`)
  was written to avoid.

### References in codebase

- `worktree_environment.py:205-231` — the shape to copy.
- `worktree_environment.py:234-248` — the host-side `mkdir` precedent.
- `test_worktree_environment.py:478-535` — the three ledger tests to mirror.

---

## Implementation Blueprint

### Steps (in order)

1. Add `CODER_EVIDENCE_DIR` beside `SHARED_LEDGER_DIR` — *why*: one named
   constant the drift test can compare against `resolve_durable_root`.
2. Add `coder_evidence_dirs()` after `shared_ledger_dirs()` — *why*: keeps the
   two narrow-exception helpers adjacent and readable.
3. Bind it in `protected_argv` right after the ledger loop — *why*: mount order
   is irrelevant here (none of these nest), adjacency keeps the diff obvious.
4. Extend `allow_paths` in `native_sandbox_settings` — *why*: the native
   backend must allow exactly what bwrap allows; `validate_native_write_path`
   then inherits it for free.
5. Write the tests — *why*: a silent regression here is invisible until a
   worker fails at its review boundary.
6. Update both twins of `worktree-management.md` — *why*: the rule enumerates
   the writable set, and it is now wrong.

### `worktree_environment.py` (MODIFY) — constant

```python
# occurrences: 1 (verified: grep -c 'SHARED_LEDGER_DIR = ' packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py)
# AFTER — insert below `SHARED_LEDGER_DIR = Path(".parrot") / "ledger"` (verified: worktree_environment.py:142)
# The sdd-coder durable evidence store. ``resolve_durable_root``
# (parrot/flows/dev_loop/sdd_coder/telemetry.py) places it under the PRIMARY
# checkout so the dataset outlives ``git worktree remove``, and
# ``parrot sdd task review prepare`` / ``finalize`` write into it from inside a
# worktree. Only this directory is bound — ``artifacts/`` also holds Python the
# host executes (``artifacts/laya/``), which must stay read-only. This module is
# stdlib-only by contract, so the path is duplicated here rather than imported;
# ``test_coder_evidence_dir_matches_resolve_durable_root`` guards the drift.
CODER_EVIDENCE_DIR = Path("artifacts") / "logs" / "sdd-coder-usage"
```

### `worktree_environment.py` (MODIFY) — helper

```python
# AFTER — insert below the closing `return (ledger_dir,)` of `shared_ledger_dirs`
# (verified: worktree_environment.py:231)


def coder_evidence_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]:
    """Return the primary checkout's sdd-coder evidence store for a linked worktree.

    ``parrot sdd task review prepare`` and ``parrot sdd task finalize`` resolve
    the store to ``<primary>/artifacts/logs/sdd-coder-usage`` and write the
    review checkpoint and the task journal there. Only that directory is
    returned: the rest of ``artifacts/`` holds Python the unsandboxed host
    executes and stays read-only.

    Unlike :func:`shared_ledger_dirs`, a missing directory is created rather
    than skipped — the store does not exist before the first execution, and
    Bubblewrap cannot bind a path that is not there.

    Args:
        root: The checkout root resolved for the command's working directory.
        git_dir: The common Git directory, or ``None`` outside a repository.

    Returns:
        The evidence directory to bind writable, or an empty tuple for the
        primary checkout (already writable) and when it cannot be created.
    """
    if git_dir is None:
        return ()
    primary = git_dir.parent
    if primary == root:
        return ()
    evidence_dir = (primary / CODER_EVIDENCE_DIR).resolve()
    if evidence_dir.is_relative_to(root):
        return ()
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Never raise: protected_argv wraps every Bash call, so one raise
        # denies the whole session. Degrade to "no bind" and let the CLI
        # report its own write failure.
        return ()
    return (evidence_dir,)
```

### `worktree_environment.py` (MODIFY) — bind

```python
# occurrences: 1 (verified: grep -c 'for ledger_dir in shared_ledger_dirs' packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py)
# AFTER — insert below the two lines at worktree_environment.py:308-309:
#     for ledger_dir in shared_ledger_dirs(root, git_dir):
#         command.extend(["--bind", str(ledger_dir), str(ledger_dir)])
    for evidence_dir in coder_evidence_dirs(root, git_dir):
        command.extend(["--bind", str(evidence_dir), str(evidence_dir)])
```

Also extend `protected_argv`'s docstring sentence that enumerates the writable
set (`worktree_environment.py:256-258`, "the primary checkout's shared SDD
ledger (``.parrot/ledger``, …), private temporary storage,") to name the
evidence store.

### `native_claude_sandbox.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'allow_paths.extend(_we.shared_ledger_dirs' packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py)
# AFTER — insert below `allow_paths.extend(_we.shared_ledger_dirs(root, git_dir))`
# (verified: native_claude_sandbox.py:403)
    allow_paths.extend(_we.coder_evidence_dirs(root, git_dir))
```

**Why**: `validate_native_write_path` (`native_claude_sandbox.py:501-520`)
re-reads `native_sandbox_settings(root)["sandbox"]["filesystem"]["allowWrite"]`,
so this single line also unblocks the Write/Edit file-tool guard.

### FILL IN checklist

- [ ] Both `worktree-management.md` twins: add the evidence store to the
      sentence listing the writable set (the one beginning "The checkout, Git
      metadata, the primary checkout's worktree root … and the primary
      checkout's `.parrot/ledger/`"), and keep the two files byte-identical.

---

## Acceptance Criteria

- [ ] From a linked worktree, a sandboxed process can create and write a file
      under `<primary>/artifacts/logs/sdd-coder-usage/`.
- [ ] From a linked worktree, a sandboxed process still **cannot** write to
      `<primary>/artifacts/laya/`, `<primary>/artifacts/` itself, or any other
      path under the primary checkout.
- [ ] `coder_evidence_dirs` returns `()` for the primary checkout and performs
      no `mkdir` there; `test_primary_checkout_has_no_extra_ledger_bind` still
      passes unchanged.
- [ ] The directory is created when absent, and a `mkdir` failure returns `()`
      instead of raising.
- [ ] The native settings' `filesystem.allowWrite` contains the evidence
      directory for a linked worktree.
- [ ] A test fails if `CODER_EVIDENCE_DIR` and `resolve_durable_root`'s default
      ever disagree.
- [ ] `ruff check` clean on both modified source files.
- [ ] Both `worktree-management.md` twins are updated and identical.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`

Run with `PYTHONPATH=<worktree>/packages/ai-parrot/src` (absolute — a relative
entry gives false greens inside a worktree).

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
# Mirror the three ledger tests at lines 478-535.


def test_feature_worktree_binds_primary_coder_evidence_dir_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The evidence store is writable; the rest of artifacts/ is not."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main, worktree = _registered_feature_worktree(tmp_path)
    (main / "artifacts" / "laya").mkdir(parents=True)
    binds = _writable_binds(policy.protected_argv(worktree, ["true"]))
    assert (main / "artifacts" / "logs" / "sdd-coder-usage").resolve() in binds
    assert (main / "artifacts").resolve() not in binds
    assert (main / "artifacts" / "laya").resolve() not in binds
    assert main.resolve() not in binds


def test_coder_evidence_dir_is_created_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First run: bwrap cannot bind a missing path, so the helper creates it."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main, worktree = _registered_feature_worktree(tmp_path)
    assert not (main / "artifacts" / "logs" / "sdd-coder-usage").exists()
    policy.protected_argv(worktree, ["true"])
    assert (main / "artifacts" / "logs" / "sdd-coder-usage").is_dir()


def test_primary_checkout_gets_no_evidence_bind_and_no_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch_root: Path
) -> None:
    """The primary is already writable: no bind, and no filesystem side effect."""
    monkeypatch.setattr(policy.shutil, "which", lambda name: "/usr/bin/bwrap")
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    assert _writable_binds(policy.protected_argv(main, ["true"])) == [
        scratch_root.resolve(),
        main.resolve(),
    ]
    assert not (main / "artifacts").exists()


def test_coder_evidence_dirs_degrades_when_mkdir_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mkdir failure must not raise — protected_argv wraps every Bash call."""
    main, worktree = _registered_feature_worktree(tmp_path)
    git_dir = (main / ".git").resolve()

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(policy.Path, "mkdir", _boom)
    assert policy.coder_evidence_dirs(worktree, git_dir) == ()


def test_real_feature_worktree_can_write_evidence_store_but_not_laya(tmp_path: Path) -> None:
    """Real bwrap: the store is writable, the executable corner of artifacts/ is not."""
    _require_bubblewrap()
    # Build the repo + worktree exactly as
    # test_real_feature_worktree_can_write_shared_ledger_but_not_wiki_plane does
    # (test_worktree_environment.py:499-535), then:
    #   - `touch <main>/artifacts/logs/sdd-coder-usage/probe` succeeds
    #   - `touch <main>/artifacts/laya/probe` leaves no file behind


def test_coder_evidence_dir_matches_resolve_durable_root(tmp_path: Path) -> None:
    """Drift guard: the stdlib-only policy module duplicates telemetry's default."""
    from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root

    # FILL IN: build a throwaway git repo at tmp_path, call
    # resolve_durable_root(None, worktree_base_path=str(tmp_path / "wt")), and
    # assert the result equals (repo / policy.CODER_EVIDENCE_DIR).resolve().
```

```python
# packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py
def test_native_allow_write_includes_coder_evidence_dir(tmp_path: Path) -> None:
    """The native backend allows exactly what bwrap binds."""
    # FILL IN: build a linked worktree, call native_sandbox_settings(worktree),
    # assert the evidence dir is in settings["sandbox"]["filesystem"]["allowWrite"]
    # and that <primary>/artifacts is not.
```

---

## Agent Instructions

1. **Work in the brief worktree** —
   `.parrot/worktrees/fix-c61e28722cca-sandbox-coder-store-readonly`, branch
   `fix-c61e28722cca-sandbox-coder-store-readonly`. Never on `dev`.
2. **Read the brief** at `sdd/briefs/sandbox-coder-store-readonly.brief.md`.
3. **Verify the Codebase Contract** before writing code — re-check every line
   number above; `dev` moves.
4. **Implement** exactly the five files listed. No other file.
5. **Validate** — `ruff check --fix` on the two source files, then the
   Validation Commands with an absolute `PYTHONPATH`.
6. **Commit** — stage only this task's files:
   `fix(sandbox): HOTFIX-c61e28722cca-1 — bind the sdd-coder evidence store`.
   `.claude/rules/worktree-management.md` needs `git add -f`.
7. **Fill in the Completion Note** below and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from brief**: none | describe if any
