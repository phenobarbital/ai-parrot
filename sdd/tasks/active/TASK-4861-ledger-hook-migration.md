# TASK-4861: Managed ledger hooks — no pre-commit export; migrate installed blocks in place

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and G1/G7. Today the managed `parrot-ledger` pre-commit block runs
`wikitoolkit ledger export-log --stage --quiet`, which stages `sdd/ledger/events.jsonl` into every commit in
every checkout — the root cause of ledger data riding along in feature PRs. The generator must stop exporting,
and because `_install_managed_git_hook` currently returns "already installed" whenever the begin marker is
present (`installer.py:933-936`), already-installed hooks would never be upgraded. This task makes the
pre-commit block an explanatory no-op and makes `_install_ledger_hooks` replace an outdated ledger block in
place. The import-only post hooks are unchanged in behavior.

---

## Scope

- `assets.ledger_hook_block(root, "pre-commit")` returns a marker block containing only comments (no command):
  it explains that FEAT-758 moved delivery to `/sdd-done` (`wikitoolkit ledger outbox`). The post-merge /
  post-checkout / post-rewrite blocks still run `ledger import-log --quiet` exactly as now.
- `_install_ledger_hooks(root)`: for each event, if the hook file exists and contains `LEDGER_HOOK_BEGIN`,
  compare the existing marker block with the freshly generated block:
  - identical → `"git <event> ledger hook — already installed"` (unchanged);
  - different → replace ONLY the bytes between and including the markers (keep everything else byte-for-byte,
    keep the file mode), action `"git <event> ledger hook — upgraded"`.
  Otherwise delegate to the existing `_install_managed_git_hook` (create / chain / refuse non-shell) unchanged.
- The `manual_hint` for pre-commit no longer mentions `export-log --stage`.
- Do not change `_install_managed_git_hook`'s semantics for the wiki `post-commit`/`post-merge` hooks.
- Update `tests/knowledge/wiki/test_installer_ledger_hooks.py`.

**NOT in scope**: CLI rejection of `--stage` (TASK-4860); removing the pre-commit block entirely (kept as a
documented no-op so uninstall and reinstall stay symmetric); installing hooks on the user's real checkout
(spec Worktree Strategy: exclusive manual post-implementation operation).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | No-export pre-commit block |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | In-place ledger block upgrade |
| `tests/knowledge/wiki/test_installer_ledger_hooks.py` | MODIFY | Upgrade/idempotence/custom-bytes tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# installer.py already has: from parrot.knowledge.wiki.claude_code import assets ; import stat
# tests already import: assets, installer, _git_hook_path, _install_git_hook, _install_ledger_hooks,
#                       _uninstall_ledger_hooks   (test_installer_ledger_hooks.py:11-18)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
LEDGER_HOOK_BEGIN = "# >>> parrot-ledger >>>"   # :51
LEDGER_HOOK_END = "# <<< parrot-ledger <<<"     # :52
LEDGER_HOOK_EVENTS: tuple[str, ...] = ("pre-commit", "post-merge", "post-checkout", "post-rewrite")  # :53
def resolve_wikitoolkit_bin(root: Path) -> str   # used at assets.py:230
def ledger_hook_block(root: Path, hook_name: str) -> str:  # :218 — raises ValueError for unknown events
def ledger_hook_new_file(root: Path, hook_name: str) -> str:  # :241 — "#!/bin/sh\n" + block

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _remove_marker_block(text: str, begin: str, end: str) -> str:  # :72
def _git_hook_path(root: Path, hook_name: str = "post-commit") -> Optional[Path]:  # :832
def _install_managed_git_hook(root, hook_name, label, *, block=None, new_file=None, begin_marker=None,
                              manual_hint=None) -> str:  # :902 — returns "already installed" if marker present (:935)
def _install_ledger_hooks(root: Path) -> list[str]:  # :973
def _uninstall_ledger_hooks(root: Path) -> list[str]:  # :993 — unchanged
```

### Does NOT Exist
- ~~`installer._replace_marker_block`~~ — no replace helper exists; add a private one in `installer.py`.
- ~~`assets.LEDGER_HOOK_VERSION`~~ — not needed; compare full block text instead.
- ~~`wikitoolkit ledger outbox` in a hook~~ — hooks must never push or deliver (spec §7: no implicit network
  pushes on ordinary commits).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_installer_ledger_hooks.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#ledger_hook_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_ledger_hooks",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_managed_git_hook",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_remove_marker_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_git_hook_path"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Change `ledger_hook_block` — *why*: the generator is the source of every new/upgraded hook.
2. Add `_replace_marker_block` and the upgrade branch in `_install_ledger_hooks` — *why*: existing installs.
3. Update tests — *why*: spec §4 "Installed hook upgrade" row.

### `assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def ledger_hook_block(root: Path, hook_name: str) -> str:' assets.py)
# REPLACE the body from `wt_bin = resolve_wikitoolkit_bin(root)` (assets.py:230) through the return (:238):
    if hook_name == "pre-commit":
        return (
            f"{LEDGER_HOOK_BEGIN}\n"
            f"# FEAT-758: ledger events no longer travel in commits. /sdd-done delivers them to\n"
            f"# origin/dev with `wikitoolkit ledger outbox prepare|integrate`. Intentionally a no-op.\n"
            f"# Installed by `parrot claude install`; remove with `parrot claude uninstall`.\n"
            f"{LEDGER_HOOK_END}\n"
        )
    wt_bin = resolve_wikitoolkit_bin(root)
    return (
        f"{LEDGER_HOOK_BEGIN}\n"
        f"# Sync the shared SDD ledger event log (FEAT-694).\n"
        f"# Installed by `parrot claude install`; remove with `parrot claude uninstall`.\n"
        f"{wt_bin} ledger import-log --quiet >/dev/null 2>&1 || true\n"
        f"{LEDGER_HOOK_END}\n"
    )
```
Also update the docstring's first line to "Build the managed ledger block (import-only post hooks; no-op
pre-commit)". Keep the `ValueError` guard above unchanged.

### `installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _install_ledger_hooks(root: Path) -> list[str]:' installer.py)
# REPLACE the whole function (installer.py:973-990) with:
def _replace_marker_block(text: str, begin: str, end: str, block: str) -> str | None:
    """Return ``text`` with its first ``begin``..``end`` block replaced, or ``None`` if markers are unbalanced."""
    # FILL IN: locate begin; locate end AFTER it; slice up to and including the end-marker line's "\n"
    #   (or EOF); return prefix + block + suffix. Missing end -> None — bounded by "preserve unrelated hook bytes".
    raise NotImplementedError


def _install_ledger_hooks(root: Path) -> list[str]:
    """Install or upgrade the ``parrot-ledger`` block on every event of :data:`assets.LEDGER_HOOK_EVENTS`."""
    actions: list[str] = []
    for event in assets.LEDGER_HOOK_EVENTS:
        block = assets.ledger_hook_block(root, event)
        hook_path = _git_hook_path(root, event)
        if hook_path is not None and hook_path.exists():
            text = hook_path.read_text(encoding="utf-8")
            if assets.LEDGER_HOOK_BEGIN in text:
                # FILL IN: new = _replace_marker_block(...); None -> append action
                #   "git {event} ledger hook — skipped (unbalanced parrot-ledger markers; fix manually)";
                #   new == text -> "... — already installed"; else write new, re-apply the original
                #   st_mode, action "git {event} ledger hook — upgraded". `continue` in all three cases.
                pass
        actions.append(
            _install_managed_git_hook(
                root,
                event,
                f"{event} ledger",
                block=block,
                new_file=assets.ledger_hook_new_file(root, event),
                begin_marker=assets.LEDGER_HOOK_BEGIN,
                manual_hint=(
                    "nothing (FEAT-758: pre-commit no longer exports ledger events)"
                    if event == "pre-commit"
                    else "wikitoolkit ledger import-log --quiet"
                ),
            )
        )
    return actions
```
**Why**: migration must happen *before* `_install_managed_git_hook`'s marker-present shortcut, scoped to the
ledger markers only (spec §3 M4), so the wiki post-commit/post-merge blocks keep their exact semantics.

### `tests/knowledge/wiki/test_installer_ledger_hooks.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_ledger_hooks_installed_on_four_events(tmp_path: Path) -> None:')
# EDIT test_ledger_hooks_installed_on_four_events (:48): expected text per event becomes
#   pre-commit -> "FEAT-758" present and "export-log" ABSENT; others -> "import-log".
# EDIT test_ledger_hook_runs_without_worktree_guard (:64): run the post-merge hook instead of pre-commit and
#   assert "ledger import-log --quiet" in args.log; additionally run pre-commit and assert args.log has no
#   "export-log".
# APPEND:
def test_outdated_pre_commit_block_is_upgraded_preserving_custom_bytes(tmp_path: Path) -> None:
    # FILL IN: write a pre-commit hook = "#!/bin/sh\necho custom-before\n" + OLD block (with
    #   "ledger export-log --stage --quiet") + "echo custom-after\n", mode 0o755; install; assert action
    #   "upgraded", both custom lines byte-identical, no "export-log", mode preserved; second install ->
    #   "already installed" and file unchanged.


def test_unbalanced_markers_are_left_untouched(tmp_path: Path) -> None:
    # FILL IN: begin marker without end -> action contains "skipped"; file bytes unchanged.


def test_non_shell_hook_still_refused(tmp_path: Path) -> None:
    # FILL IN: "#!/usr/bin/env python3\n" pre-commit without markers -> "not a shell script", unchanged.
```

### FILL IN checklist
- [ ] `_replace_marker_block` — bounded by "preserve unrelated hook bytes"
- [ ] upgrade branch in `_install_ledger_hooks` — bounded by spec §3 M4 ("reports unchanged only when contents match")
- [ ] 2 test edits + 3 new tests

---

## Acceptance Criteria

- [ ] Old export block replaced; custom bytes and executable mode preserved; second install unchanged
- [ ] New installs never contain `export-log`
- [ ] Post hooks still import; `_uninstall_ledger_hooks` behavior unchanged (existing test passes)
- [ ] `ruff check` clean on both source files

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_installer_ledger_hooks.py -q`

---

## Test Specification

See the test blueprint above.

---

## Agent Instructions

1. Work in the feature worktree. No dependency — may run concurrently with TASK-4857.
2. Read spec §3 Module 4.
3. Verify the Codebase Contract, implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the three listed files; close with `scripts/sdd/close_task.sh TASK-4861 ledger-outbox-integration verified`.
5. Do NOT run `parrot claude install` against the real repository.

---

## Completion Note

*(Agent fills this in when done)*
