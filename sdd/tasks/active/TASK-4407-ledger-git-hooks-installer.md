# TASK-4407: Managed `parrot-ledger` git hooks — assets + installer (four events)

**Feature**: FEAT-694 — Shared Ledger Event Log (cross-machine sync via git hooks)
**Spec**: `sdd/specs/ledger-shared-event-log.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, G2 "zero explicit commands". `parrot claude install` gains a second managed
block, `parrot-ledger`, on `pre-commit` (export + stage) and `post-merge` / `post-checkout` /
`post-rewrite` (import). The block only embeds the command names frozen in spec §2
(`ledger export-log --stage --quiet`, `ledger import-log --quiet`), so this task needs no code
from TASK-4405/4406 and runs in parallel with them.

---

## Scope

- `assets.py`: `LEDGER_HOOK_BEGIN`, `LEDGER_HOOK_END`, `LEDGER_HOOK_EVENTS`,
  `ledger_hook_block(root, hook_name)`, `ledger_hook_new_file(root, hook_name)`.
- `installer.py`: generalise `_install_managed_git_hook` with keyword-only `block`, `new_file`,
  `begin_marker` (defaults = current wiki behaviour); add `_install_ledger_hooks`,
  `_uninstall_ledger_hooks`; wire both into `install_claude_integration` (one extra action
  entry under `git_hook`) and `uninstall_claude_integration`.
- Tests: `tests/knowledge/wiki/test_installer_ledger_hooks.py`.

**NOT in scope**: `scripts/sdd/install_hooks.py` (FEAT-577 — coexist only); repairing the old
`post-commit` block; any `wikitoolkit` command implementation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | ledger hook constants + block builders |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | generalised installer, ledger install/uninstall, wiring |
| `tests/knowledge/wiki/test_installer_ledger_hooks.py` | CREATE | M3 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets                                   # verified: claude_code/installer.py:33
from parrot.knowledge.wiki.claude_code.installer import _git_hook_path, _install_git_hook, _install_post_merge_hook  # verified: tests/knowledge/wiki/test_installer_worktree_guard.py:18-22
```

### Existing Signatures to Use
```python
# claude_code/assets.py
GIT_HOOK_BEGIN = "# >>> parrot-wiki post-commit >>>"; GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"  # line 47-48
def resolve_wikitoolkit_bin(root: Path) -> str                                         # line 88
def git_hook_block(root: Path) -> str                                                  # line 180 (has the `if [ ! -f .git ]` guard — do NOT copy it)
def git_hook_new_file(root: Path) -> str                                               # line 208

# claude_code/installer.py
def _remove_marker_block(text: str, begin: str, end: str) -> str                       # line 72
def _git_hook_path(root: Path, hook_name: str = "post-commit") -> Optional[Path]        # line 832 (common hooks dir for linked worktrees)
def _shebang_is_sh_compatible(first_line: str) -> bool                                 # line 882
def _install_managed_git_hook(root: Path, hook_name: str, label: str) -> str           # line 902-944
def _install_post_merge_hook(root: Path) -> str                                        # line 952
def install_claude_integration(root, config=None, git_hook=True, ...) -> list[str]     # line 983; hook branch 1055-1061
def uninstall_claude_integration(root: Path) -> list[str]                              # line 1075; post-commit removal 1188-1200; fallback 1202-1203
```

### Does NOT Exist
- ~~`assets.LEDGER_HOOK_BEGIN`~~, ~~`assets.ledger_hook_block`~~, ~~`installer._install_ledger_hooks`~~ — you add them.
- ~~`.git/hooks/pre-commit|post-checkout|post-rewrite` installed by parrot~~ — none today.
- ~~a linked-worktree guard in the ledger block~~ — must NOT exist (AC8).
- ~~existing tests asserting `len(install_claude_integration(...))`~~ — `grep -rn "len(actions)" tests/knowledge/wiki/test_installer*.py` found none; if you find one, update it by +1 in this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_installer_ledger_hooks.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#resolve_wikitoolkit_bin",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#git_hook_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_managed_git_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_remove_marker_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#uninstall_claude_integration"
  ]
}
```

---

## Implementation Notes

- Hooks must never fail a git op (AC12): every command line ends `>/dev/null 2>&1 || true`.
- `_install_managed_git_hook` stays backward-compatible: existing callers and
  `test_installer_worktree_guard.py` must pass unchanged. Its "not a shell script" skip
  message mentions `wikitoolkit upsert --changed --quiet`; for the ledger block mention the
  ledger command instead (add a `manual_hint: str | None = None` kwarg if needed — keyword-only).
- Chaining: a hook file already holding `parrot-wiki` or `sdd-intake-prune` blocks gets the
  ledger block appended; neither is touched (AC7). Idempotence is by `LEDGER_HOOK_BEGIN` presence.
- Uninstall: delete the file when what remains `.strip()` is `""` or `"#!/bin/sh"` (same rule as
  `installer.py:1193`).

---

## Implementation Blueprint

### Steps (in order)
1. Add the ledger constants + builders to `assets.py` — *why*: installer imports them.
2. Add keyword-only kwargs to `_install_managed_git_hook`; default to the wiki block — *why*: no duplicate function (spec §7).
3. Add `_install_ledger_hooks` / `_uninstall_ledger_hooks` after `_install_post_merge_hook`.
4. Wire into install (one extra action) and uninstall (before the fallback).
5. Tests; Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"' assets.py)
# AFTER — insert below `GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"` (verified: assets.py:48)
# FEAT-694: shared ledger event log sync (export on pre-commit, import after pull/checkout/rewrite).
LEDGER_HOOK_BEGIN = "# >>> parrot-ledger >>>"
LEDGER_HOOK_END = "# <<< parrot-ledger <<<"
LEDGER_HOOK_EVENTS: tuple[str, ...] = ("pre-commit", "post-merge", "post-checkout", "post-rewrite")

# occurrences: 1 (verified: grep -cF 'def git_hook_new_file(root: Path) -> str:' assets.py)
# AFTER — insert after the whole `git_hook_new_file` function (anchor verified: assets.py:208)
def ledger_hook_block(root: Path, hook_name: str) -> str:
    """Build the managed ledger-sync block for one hook event (no linked-worktree guard).

    Raises:
        ValueError: ``hook_name`` is not in :data:`LEDGER_HOOK_EVENTS`.
    """
    if hook_name not in LEDGER_HOOK_EVENTS:
        raise ValueError(f"unknown ledger hook event: {hook_name!r}")
    wt_bin = resolve_wikitoolkit_bin(root)
    sub = "ledger export-log --stage --quiet" if hook_name == "pre-commit" else "ledger import-log --quiet"
    return (
        f"{LEDGER_HOOK_BEGIN}\n"
        f"# Sync the shared SDD ledger event log (FEAT-694).\n"
        f"# Installed by `parrot claude install`; remove with `parrot claude uninstall`.\n"
        f"{wt_bin} {sub} >/dev/null 2>&1 || true\n"
        f"{LEDGER_HOOK_END}\n"
    )


def ledger_hook_new_file(root: Path, hook_name: str) -> str:
    """Build a fresh hook file holding only the ledger block."""
    return f"#!/bin/sh\n{ledger_hook_block(root, hook_name)}"
```
**Why**: text fixed by spec §3 M3; no `[ ! -f .git ]` guard because the pre-commit must stage
the worktree's own `sdd/ledger/events.jsonl` (spec §7).

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _install_managed_git_hook(root: Path, hook_name: str, label: str) -> str:' installer.py)
# REPLACE the signature line (installer.py:902) with:
def _install_managed_git_hook(
    root: Path,
    hook_name: str,
    label: str,
    *,
    block: str | None = None,
    new_file: str | None = None,
    begin_marker: str | None = None,
) -> str:
# and in the body replace the two assignments + marker test (installer.py:920-924):
    block = block if block is not None else assets.git_hook_block(root)
    new_file = new_file if new_file is not None else assets.git_hook_new_file(root)
    begin_marker = begin_marker if begin_marker is not None else assets.GIT_HOOK_BEGIN
    # ... `if begin_marker in text:` instead of `if assets.GIT_HOOK_BEGIN in text:`
# FILL IN: document the three kwargs in the Args section; keep every other line identical

# occurrences: 1 (verified: grep -cF 'def _install_post_merge_hook(root: Path) -> str:' installer.py)
# AFTER — insert after the whole `_install_post_merge_hook` function (anchor verified: installer.py:952)
def _install_ledger_hooks(root: Path) -> list[str]:
    """Install the ``parrot-ledger`` block on every event of :data:`assets.LEDGER_HOOK_EVENTS`."""
    return [
        _install_managed_git_hook(
            root,
            event,
            f"{event} ledger",
            block=assets.ledger_hook_block(root, event),
            new_file=assets.ledger_hook_new_file(root, event),
            begin_marker=assets.LEDGER_HOOK_BEGIN,
        )
        for event in assets.LEDGER_HOOK_EVENTS
    ]


def _uninstall_ledger_hooks(root: Path) -> list[str]:
    """Strip the ``parrot-ledger`` block from each ledger hook; never touch other blocks."""
    # FILL IN: per event: _git_hook_path(root, event); skip missing / block absent;
    # _remove_marker_block(text, LEDGER_HOOK_BEGIN, LEDGER_HOOK_END); unlink when only shebang
    # remains → "git <event> ledger hook — removed", else "… — ledger block removed"

# occurrences: 1 (verified: grep -cF '        merge_action = _install_post_merge_hook(root)' installer.py)
# AFTER — insert below `        actions.append(f"{commit_action}; {merge_action}")` (installer.py:1061, right after the anchor at 1060)
        actions.append("; ".join(_install_ledger_hooks(root)))

# occurrences: 1 (verified: grep -cF '        actions.append("nothing to remove — integration not installed")' installer.py)
# BEFORE — insert above `    if not actions:` (installer.py:1202, line before the anchor at 1203)
    actions.extend(_uninstall_ledger_hooks(root))
```
**Why**: the action string format `"git <event> ledger hook — created|…"` comes out of the
existing `label` mechanism; one joined entry keeps the action count +1 (spec §3 M3).

### `tests/knowledge/wiki/test_installer_ledger_hooks.py` (CREATE)
```python
"""FEAT-694 M3 — managed parrot-ledger git hooks."""
# FILL IN: reuse the stub-binary pattern of test_installer_worktree_guard.py:31 (stub records "$@"
# into a file); tests test_ledger_hooks_installed_on_four_events, test_ledger_hook_runs_without_worktree_guard
# (.git dir AND .git file), test_uninstall_strips_only_ledger_block, test_install_claude_integration_action_count
# (patch the non-hook installers if needed), plus AC12: hook with a non-existent wt_bin exits 0.
```

### FILL IN checklist
- [ ] installer kwargs docs; body otherwise identical
- [ ] `_uninstall_ledger_hooks`
- [ ] five tests (four spec rows + AC12)

---

## Acceptance Criteria

- [ ] AC7, AC8, AC12.
- [ ] `test_installer_worktree_guard.py` passes unchanged.
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `pytest tests/knowledge/wiki/test_installer_ledger_hooks.py -q`
- `pytest tests/knowledge/wiki/test_installer_worktree_guard.py -q`

---

## Test Specification

Spec §4 rows tagged M3.

---

## Agent Instructions

Standard SDD flow (`sdd/templates/task.md` § Agent Instructions); feature worktree
`feat-FEAT-694-ledger-shared-event-log`; `PYTHONPATH=packages/ai-parrot/src`; close with
`scripts/sdd/close_task.sh TASK-4407 ledger-shared-event-log verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
