# TASK-5132: Installer wiring — plan/apply stale removal, install note, status keys

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5129, TASK-5130
**Assigned-to**: unassigned

---

## Context

Spec §2 (plan/apply, receipt rules, source-checkout guard) and §3 Module 2. TASK-5129 computes the stale file set;
this task turns it into `PlannedAction`s, removes the files, keeps the receipt honest, and surfaces both stale
files and stale MCP entries (TASK-5130) in `install` (report only) and `status`. TASK-5135 adds the CLI flags.

---

## Scope

- Add `"stale-remove"`, `"keep-stale"`, `"skip-symlink"` to `PlanAction` right after `"receipt-remove"`.
- Add `plan_stale()` and `remove_stale_sdd_files()` right above `def uninstall_sdd_integration(`.
- `install_sdd_integration`: before its final `return`, append one report-only `note:` when stale files (0 in a
  source checkout) or stale MCP entries (for the hosts being installed) exist. It deletes nothing.
- `sdd_status`: add `"stale"` (`[]` in a source checkout) and `"stale_mcp"` keys next to `"receipt_version"`.
- Import `parrot.sdd.stale` / `parrot.mcp.toolkit_stale` **inside** these functions (TASK-5129: `stale.py`
  imports `installer` at module level, so a top-level import here would be a cycle).
- Append the M2 tests to `packages/ai-parrot/tests/sdd/test_installer_stale.py`.

**NOT in scope**: CLI options and printing (TASK-5135); MCP removal (TASK-5131 — `remove_stale_sdd_files` handles
files only); changing `plan_uninstall` / `uninstall_sdd_integration` behaviour (plain uninstall must behave exactly
as after PR #1940).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | PlanAction values, plan_stale, remove_stale_sdd_files, install note, status keys |
| `packages/ai-parrot/tests/sdd/test_installer_stale.py` | MODIFY | M2 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside functions in installer.py (lazy — no module-level import):
from parrot.sdd.stale import StaleEntry, find_stale, is_source_checkout   # created by TASK-5129
from parrot.mcp.toolkit_stale import find_stale_mcp_entries              # created by TASK-5130
# already imported at installer.py top: os (line 17), fnmatch is NOT imported — add `import fnmatch` at the top.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
PlanAction = Literal[ …, "receipt-remove", ]                          # lines 79-108; anchor `    "receipt-remove",` line 108
class PlannedAction(BaseModel): action: PlanAction; target: str; note: str = ""   # line 112; str() -> "plan: <action> <target> (<note>)"
def load_receipt(root: Path) -> dict[str, Any]                         # line 209
def _save_receipt(root: Path, receipt: dict[str, Any]) -> None         # line 256 (also stamps version)
def _under(path: Path, base: Path) -> bool                             # line 270 — lexical; pass realpaths
def install_sdd_integration(root, hosts=("claude",), *, ...) -> list[str]  # line 1059; `    return [a for a in actions if a]` line 1163
def _prune_empty_parents(root: Path, path: Path) -> None               # line 1256
def uninstall_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False) -> list[str]  # line 1267
def sdd_status(root: Path) -> dict[str, Any]                           # line 1422; `        "receipt_version": receipt.get("version"),` line 1464
RECEIPT_PATH = Path("sdd/.sdd-installed.json")                         # line 44
SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "google")       # line 39
# Inside install_sdd_integration the host list variable is `hosts` (same name as the parameter).
```

### Does NOT Exist
- ~~`--force` semantics~~ — `--force` is a hidden no-op since PR #1940; wire nothing to it.
- ~~`installer.remove_stale_mcp_entries`~~ — MCP removal lives in `parrot.mcp.toolkit_stale` (TASK-5131); the CLI
  calls it, not this module.
- ~~a `"stale"` key in the manifest~~ — stale data never goes into `_assets/manifest.json`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer_stale.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#PlannedAction",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#load_receipt",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_save_receipt",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_under",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_prune_empty_parents",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#uninstall_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#sdd_status"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Mirror the existing plan/apply split (`plan_uninstall` → `uninstall_sdd_integration`): a pure `plan_stale`
  returns `PlannedAction`s; the apply loop produces action-log strings (`"warning:"`/`"note:"` prefixes drive
  `cli._echo_actions`).
- Symlink safety: before unlinking, require `_under(Path(os.path.realpath(p.parent)), Path(os.path.realpath(root)))`
  — a lexically-inside path whose parent resolves outside the repo is skipped with a warning.
- The receipt is **never** removed; it is saved only when a key was popped and the receipt file exists.
- The install note and status must never fail the command: wrap the MCP lookup in `try/except (ValueError,
  OSError, RuntimeError)` and treat a failure as 0 entries.
- `sdd_status` and `install` read the user-global Gemini file (read-only). Tests must monkeypatch
  `parrot.knowledge.wiki.google.assets.default_mcp_config_path` (the `gemini` fixture from TASK-5129).

---

## Implementation Blueprint

### Steps (in order)
1. Add `import fnmatch` to the top imports and the three `PlanAction` values — *why*: `PlannedAction` validation
   rejects unknown actions.
2. Add `plan_stale` and `remove_stale_sdd_files` above `uninstall_sdd_integration` — *why*: spec Edit Sites row.
3. Add the install note and the status keys — *why*: G5 (report, never delete).
4. Append the M2 tests — *why*: AC-1..AC-6.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY) — PlanAction
```python
# occurrences: 1 (verified: grep -c '    "receipt-remove",' installer.py)
# AFTER — insert below `    "receipt-remove",` (verified: installer.py:108)
    "stale-remove",
    "keep-stale",
    "skip-symlink",
```
Also add `stale: stale-remove | keep-stale | skip-symlink.` to the comment block above `PlanAction` (lines 76-78).

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY) — plan + apply
```python
# occurrences: 1 (verified: grep -c 'def uninstall_sdd_integration(' installer.py)
# BEFORE — insert above `def uninstall_sdd_integration(` (verified: installer.py:1267)
def plan_stale(root: Path, hosts: Sequence[str], *, keep: Sequence[str] = ()) -> list[PlannedAction]:
    """Pure: ``stale-remove`` per StaleEntry (note = "<reason>: <detail>"), ``keep-stale`` when a ``keep``
    glob (fnmatch on the posix path) matches, ``skip-symlink`` for symlink entries."""
    from parrot.sdd.stale import find_stale

    plan: list[PlannedAction] = []
    for entry in find_stale(root, hosts):
        # FILL IN: symlink -> skip-symlink (note "symlink; never followed"); any(fnmatch.fnmatch(entry.path, g)
        #   for g in keep) -> keep-stale (note "--keep"); else stale-remove (note f"{entry.reason}: {entry.detail}").
        pass
    return plan


def remove_stale_sdd_files(
    root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS, *, keep: Sequence[str] = (), dry_run: bool = False
) -> list[str]:
    """Remove stale SDD files (current assets, seeds and state untouched).

    dry_run → ``str(step)`` lines (prefixed by a ``note:`` line in a source checkout).
    Real run in a source checkout → RuntimeError("refusing: <root> is the ai-parrot source checkout …").
    Each removal → "<path> — removed (<reason>)"; keep → "<path> — kept (--keep)";
    symlink → "warning: <path> — symlink; kept". Removed receipt keys are popped and the receipt saved
    only if it changed; empty → ["no stale SDD files"]. Ends with a "note: commit the deletions" line
    when anything was removed.
    """
    from parrot.sdd.stale import is_source_checkout

    source = is_source_checkout(root)
    plan = plan_stale(root, hosts, keep=keep)
    if dry_run:
        head = [f"note: {root} is the ai-parrot source checkout — a real run refuses to delete here"] if source else []
        return head + ([str(step) for step in plan] or ["no stale SDD files"])
    if source:
        raise RuntimeError(
            f"refusing: {root} is the ai-parrot source checkout — its sdd-* files and scripts/sdd/ are the asset "
            "sources; use --dry-run to inspect"
        )
    if not plan:
        return ["no stale SDD files"]
    receipt = load_receipt(root)
    actions: list[str] = []
    removed = 0
    # FILL IN: per step — stale-remove: p = root / step.target; skip with "warning: <t> — resolves outside the
    #   repository; kept" unless _under(Path(os.path.realpath(p.parent)), Path(os.path.realpath(root)));
    #   p.unlink(missing_ok=True); _prune_empty_parents(root, p); popped = receipt["files"].pop(step.target, None);
    #   reason = step.note.split(":", 1)[0]; actions "<t> — removed (<reason>)"; removed += 1.
    #   keep-stale -> "<t> — kept (--keep)"; skip-symlink -> "warning: <t> — symlink; kept".
    # FILL IN: when a key was popped and (root / RECEIPT_PATH).exists(): _save_receipt(root, receipt).
    if removed:
        actions.append("note: commit the deletions (git add -A <paths> && git commit)")
    return actions
```
**Why**: dry-run, refusal and output strings are spec-fixed and written out; only the loop body is yours.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY) — install note
```python
# occurrences: 1 (verified: grep -c '    return [a for a in actions if a]' installer.py)
# BEFORE — insert above `    return [a for a in actions if a]` (verified: installer.py:1163)
    actions.append(_stale_note(root, hosts))
```
and add this helper right above `def plan_stale(`:
```python
def _stale_note(root: Path, hosts: Sequence[str]) -> str:
    """Report-only install note (G5): counts stale files (0 in a source checkout) and stale MCP entries."""
    from parrot.mcp.toolkit_stale import find_stale_mcp_entries
    from parrot.sdd.stale import find_stale, is_source_checkout

    files = 0 if is_source_checkout(root) else len(find_stale(root, SUPPORTED_HOSTS))
    # FILL IN: entries = len(find_stale_mcp_entries(root, hosts)) inside try/except (ValueError, OSError,
    #   RuntimeError) -> 0. Return "" when files == entries == 0, else
    #   f"note: {files} stale SDD file(s), {entries} stale MCP entr{'y' if entries == 1 else 'ies'} — review with "
    #   "`parrot sdd uninstall --stalled --dry-run`".
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY) — status keys
```python
# occurrences: 1 (verified: grep -c '        "receipt_version": receipt.get("version"),' installer.py)
# BEFORE — insert above `        "receipt_version": receipt.get("version"),` (verified: installer.py:1464)
        "stale": _stale_report(root),
        "stale_mcp": _stale_mcp_report(root),
```
with two helpers above `def sdd_status(`: `_stale_report(root)` → `[]` in a source checkout else
`[e.model_dump() for e in find_stale(root)]`; `_stale_mcp_report(root)` →
`[e.model_dump() for e in find_stale_mcp_entries(root, SUPPORTED_HOSTS)]`, `[]` on (ValueError, OSError, RuntimeError).
Update the `sdd_status` docstring key list with `"stale": [...], "stale_mcp": [...]`.

### `packages/ai-parrot/tests/sdd/test_installer_stale.py` (MODIFY)
```python
# AFTER — append at the end of the file (reuse `stale_repo` / `gemini` from TASK-5129)
# FILL IN: spec §4 M2 rows — test_remove_stale_removes_and_prunes (scripts/sdd/ folder gone, a current asset
#   byte-identical), test_remove_stale_updates_receipt, test_remove_stale_keep_glob
#   ('.claude/commands/sdd-team-*'), test_remove_stale_dry_run_writes_nothing (snapshot every file's bytes before/after),
#   test_remove_stale_refuses_source_checkout (create SOURCE_CHECKOUT_MARKER; RuntimeError; dry-run starts with
#   "note:"), test_install_reports_stale_note (re-run install_sdd_integration(root, ("claude",), sdd_coder=False) ->
#   exactly one line containing "stale SDD file(s)", orphans still on disk), test_status_reports_stale
#   ("stale" lists entries, "stale_mcp" key present), test_plain_uninstall_unchanged (orphans untouched by
#   uninstall_sdd_integration).
```

### FILL IN checklist
- [ ] `plan_stale` loop — three actions; bounded by AC-3.
- [ ] `remove_stale_sdd_files` loop + receipt save; bounded by AC-1, AC-2.
- [ ] `_stale_note` MCP count + message; bounded by AC-5.
- [ ] `_stale_report` / `_stale_mcp_report`; bounded by AC-6.
- [ ] the 8 tests listed.

---

## Acceptance Criteria

- [ ] AC-1: stale files removed, empty parents pruned (never the root), every current asset/seed/state file and the
      receipt byte-identical except the popped receipt keys.
- [ ] AC-2: a source checkout refuses a real run with `RuntimeError`; dry-run lists with a leading `note:`.
- [ ] AC-3: `--keep` globs keep matches; symlinks are kept with a warning; dry-run writes nothing.
- [ ] AC-4: plain `uninstall_sdd_integration` behaves exactly as before (no stale removal).
- [ ] AC-5: `install_sdd_integration` adds exactly one `note:` when stale files/entries exist and deletes nothing.
- [ ] AC-6: `sdd_status(root)` has `"stale"` and `"stale_mcp"`; neither can raise.
- [ ] Existing installer tests still pass; `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer_stale.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`

---

## Test Specification

See the blueprint; rows are spec §4 "Unit Tests" with Module = M2 plus `test_plain_uninstall_unchanged`.

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
9. **Close the task** with `parrot sdd task close TASK-5132 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: `stale` / `toolkit_stale` imported lazily inside installer functions (see TASK-5129).
