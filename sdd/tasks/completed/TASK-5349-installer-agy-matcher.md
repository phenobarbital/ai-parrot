# TASK-5349: Widen the managed AGY hook matcher to `run_command|write_file|edit_file`

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5348
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. PR #2040 registers one named hook, `parrot-sdd-permissions`, with matcher `run_command`,
both in the installer (`_agy_hook_entry`) and in ai-parrot's tracked `.agents/hooks.json`. TASK-5348 makes
the hook judge `write_file`/`edit_file`, but AGY only sends those events if the matcher names them. This
task widens the matcher, migrates receipt-owned `run_command`-only entries on reinstall, reports a stale
matcher in `parrot sdd status`, and updates the tracked file. Foreign named hooks and user-edited matchers are
reported, never overwritten. PR #2040's command forms, allow-rules and `--no-agy-permissions` stay as they are.

---

## Scope

- `installer.py`: `_AGY_MATCHER` constant; `_agy_hook_entry` uses it; `_agy_active_hook` recognises both the
  widened and the legacy `run_command` matcher; `_install_agy_hook` migrates a receipt-owned legacy entry in
  place (command and timeout kept) and reports user-edited/foreign ones; `_agy_permissions_report` adds
  `matcher` and `stale`.
- `.agents/hooks.json`: matcher → `run_command|write_file|edit_file` (command `sh ../scripts/sdd/agy_hook.sh`
  and timeout `20` unchanged).
- Tests: update PR #2040's matcher assertions; add migration/stale/roundtrip tests; one end-to-end check that
  the tracked launcher answers a `write_file` payload (the merged policy from TASK-5348).

**NOT in scope**: the hook policy itself (TASK-5347/5348); the launcher's prerequisite check (TASK-5353,
which consumes `stale`); new named hooks or vendored scripts (spec: none).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `_AGY_MATCHER`, entry/active-hook/migration/status changes |
| `.agents/hooks.json` | MODIFY | widened matcher |
| `packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py` | MODIFY | matcher, migration, stale status, google roundtrip |
| `packages/ai-parrot/tests/sdd/test_agy_permissions.py` | MODIFY | tracked-matcher assertion + launcher `write_file` check |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09), after the PR #2040 merge. The spec's PR #2040 line numbers
> (585, 693, …) still match.

### Verified Imports
```python
# tests (test_installer_agy_permissions.py:19-29)
from parrot.sdd.installer import (...)            # AGY_HOOK_NAME and friends — read the import block before editing
from parrot.sdd.scripts.agy_permissions import SDD_ALLOW_RULES
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
AGY_HOOK_LINE = "parrot sdd hooks agy-permissions --hook"        # line 498
_AGY_SUFFIX = " sdd hooks agy-permissions --hook"                # line 499
AGY_HOOKS_PATH = Path(".agents/hooks.json")                     # line 500
AGY_HOOK_NAME = "parrot-sdd-permissions"                        # line 501
_AGY_LAUNCHER = "scripts/sdd/agy_hook.sh"                       # line 503
def _agy_hook_entry(command: str) -> dict[str, Any]:             # line 585 — matcher "run_command", timeout 10
def _install_agy_hook(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> tuple[bool, list[str]]:  # line 625
    #   appends "agy-permissions" to receipt["settings_hooks"] (lines 639-642) BEFORE comparing; returns early when
    #   previous == entry, or when the active hook is the repository launcher ("repository launcher kept")
def _install_agy_permissions(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:  # line 693
def _agy_active_hook(data: dict[str, Any]) -> str | None:        # line 773 — requires group["matcher"] == "run_command"
def _agy_permissions_report(root: Path) -> dict[str, Any]:       # line 791 — {"form","command","settings","missing_rules"}
def _read_json_object(path: Path) -> dict[str, Any] | None:      # PR #2040 helper used above
def _write_json_object(path: Path, data: dict[str, Any]) -> None:
# .agents/hooks.json — line 5: `        "matcher": "run_command",`
# packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py
#   line 79:  assert entry["matcher"] == "run_command"           (test_install_registers_hook_rules_and_ownership)
#   line 277: test_repository_launcher_form_is_kept               (legacy launcher entry with matcher run_command)
#   line 295: test_status_ignores_an_inactive_hook                (matcher "wrong_tool" stays inactive)
#   fixtures: home (line 39), repo (line 52); helpers _install (57), _read (63), _write (71)
# packages/ai-parrot/tests/sdd/test_agy_permissions.py
#   line 485: test_tracked_hooks_json_runs_the_repository_launcher — `assert entry["matcher"] == "run_command"`
#   line 494: test_launcher_serves_this_checkout — pattern for running `sh ../scripts/sdd/agy_hook.sh` from REPO_ROOT/.agents
```

### Does NOT Exist
- ~~`_AGY_MATCHER`~~ — created here.
- ~~A `matcher`/`stale` key in `_agy_permissions_report`~~ — added here.
- ~~A second named SDD hook or `.agents/hooks/*.py`~~ — spec: FEAT-847 adds neither.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": ".agents/hooks.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_agy_permissions.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_agy_hook_entry",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_agy_hook",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_agy_active_hook",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_agy_permissions_report"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- "Receipt-owned" means `"agy-permissions"` was already in `receipt["settings_hooks"]` **before** this install
  call — read it before `_install_agy_hook` appends it (line 639).
- Migrate only a legacy group whose matcher is exactly `"run_command"`; keep its `command`, `timeout` and any
  other keys. A matcher that is neither `"run_command"` nor `_AGY_MATCHER` is user-edited: leave it and emit a
  `warning:` line. A legacy entry that is not receipt-owned: leave it and emit a `note:` about the stale matcher.
- `_agy_active_hook` must keep treating unknown matchers (e.g. `"wrong_tool"`) as inactive — existing test.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_AGY_MATCHER` and use it in `_agy_hook_entry` — *why*: one source for the managed matcher.
2. Let `_agy_active_hook` accept `{"run_command", _AGY_MATCHER}` and add `_agy_hook_matcher(data)` — *why*: status must see a stale entry as active-but-stale, not as missing.
3. Add the migration to `_install_agy_hook` — *why*: spec "re-running install migrates a receipt-owned run_command-only entry in place".
4. Add `matcher`/`stale` to `_agy_permissions_report` — *why*: `parrot sdd status` and the launcher (TASK-5353) read it.
5. Edit `.agents/hooks.json` and the tests.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'AGY_HOOK_NAME = "parrot-sdd-permissions"' installer.py) — line 501
# AFTER — insert below it:
#: FEAT-847 M2 — the managed hook also judges file writes; "run_command" alone is the legacy (stale) matcher
_AGY_MATCHER = "run_command|write_file|edit_file"
_AGY_LEGACY_MATCHER = "run_command"

# occurrences: 1 (verified: grep -c 'def _agy_hook_entry(command: str) -> dict\[str, Any\]:') — line 585
# REPLACE the body's "matcher": "run_command" with "matcher": _AGY_MATCHER, and add a docstring:
#     """Managed PreToolUse entry for the agy permission hook (matcher _AGY_MATCHER)."""

# occurrences: 1 (verified: grep -c 'def _agy_active_hook(data: dict\[str, Any\]) -> str | None:') — line 773
# In its loop REPLACE `group.get("matcher") != "run_command"` with
#     `group.get("matcher") not in (_AGY_LEGACY_MATCHER, _AGY_MATCHER)`
# and INSERT below the function:
def _agy_hook_matcher(data: dict[str, Any]) -> str | None:
    """The matcher of our active named hook group (legacy or widened), else None."""
    # FILL IN: same traversal as _agy_active_hook; return the group's matcher for the group holding the active
    #   command — bounded by: unknown matchers stay inactive (test_status_ignores_an_inactive_hook).
    return None

# In _install_agy_hook (line 625): FILL IN — capture `owned = "agy-permissions" in receipt.get("settings_hooks", [])`
#   BEFORE the append at lines 639-642. Before the `previous == entry` / launcher early returns: if the active group's
#   matcher is _AGY_LEGACY_MATCHER and `owned`, set that group's "matcher" to _AGY_MATCHER in place, write the file
#   and return (True, [f"{AGY_HOOKS_PATH} — agy permission hook matcher widened to {_AGY_MATCHER}"]); if it is
#   legacy and not owned, keep it and add a f"note: {AGY_HOOKS_PATH} — stale matcher 'run_command' (not owned by
#   this install); widen it by hand" line; any other non-managed matcher -> keep it, add a "warning:" line —
#   bounded by spec §3 M2 (foreign/user-edited entries are reported, not overwritten).

# In _agy_permissions_report (line 791): add to the returned dict
#     "matcher": matcher, "stale": matcher is not None and matcher != _AGY_MATCHER,
#   where matcher = _agy_hook_matcher(<the same hooks.json data>)
```
**Why this shape**: the managed entry and the status read the same constant, so the launcher prerequisite
(TASK-5353) can trust `report["stale"]` instead of re-parsing the file.

### `.agents/hooks.json` (MODIFY)
```json
// occurrences: 1 (verified: grep -c '"matcher": "run_command",' .agents/hooks.json) — line 5
// REPLACE that line with:
        "matcher": "run_command|write_file|edit_file",
```

### Tests (MODIFY)
```python
# test_installer_agy_permissions.py — line 79: expect _AGY_MATCHER ("run_command|write_file|edit_file").
# FILL IN tests (one function each) in test_installer_agy_permissions.py:
#  - test_installer_agy_matcher_widened: install --host google -> matcher == "run_command|write_file|edit_file"
#  - receipt-owned legacy entry (install, then rewrite the matcher to "run_command" by hand, reinstall) -> widened,
#    command/timeout kept; same for the repository-launcher form (rework test_repository_launcher_form_is_kept so
#    the launcher command is kept AND, when owned, its matcher widened)
#  - not-owned legacy entry and a user-edited matcher ("run_command|write_file") -> untouched, note/warning line
#  - foreign named hooks survive (extend test_foreign_hooks_and_user_rules_survive)
#  - _agy_permissions_report: widened -> stale False; legacy -> stale True; inactive matcher -> command None
#  - test_sdd_install_google_roundtrip: install_sdd_integration(root, hosts=("google",)) then
#    uninstall_sdd_integration -> .agents/hooks.json has the widened matcher while installed; .agents/agents/ and
#    .agents/skills/ exist while installed and are gone (or reduced to non-managed files) after uninstall
# test_agy_permissions.py — line 485 test: expect matcher "run_command|write_file|edit_file"; ADD
#  - test_launcher_judges_write_file: like test_launcher_serves_this_checkout (skip when the launcher reports
#    "unavailable"), send a write_file payload whose Path is outside `ws` -> decision "deny"
```

### FILL IN checklist
- [ ] `_agy_hook_matcher`; bounded by `test_status_ignores_an_inactive_hook`
- [ ] `_install_agy_hook` migration/report rules; bounded by spec §3 M2
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] `parrot sdd install --host google` writes matcher `run_command|write_file|edit_file`; reinstall migrates a receipt-owned `run_command`-only entry in place.
- [ ] Foreign named hooks and user-edited matchers are left untouched and reported; `parrot sdd status` reports `stale` for a legacy matcher.
- [ ] The tracked `.agents/hooks.json` carries the widened matcher with its original command and timeout.
- [ ] All tests in both test files pass; `ruff check` is clean on `installer.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_agy_permissions.py -q`

---

## Test Specification

See the Tests block in the Implementation Blueprint; reuse the `home`/`repo` fixtures and `_install`/`_read`/
`_write` helpers of `test_installer_agy_permissions.py`, and `REPO_ROOT`/`ws`/`_payload` in `test_agy_permissions.py`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5349 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: Claude Opus 4.6 (host session)
**Date**: 2026-11-09
**Notes**: Widened managed AGY hook matcher from `run_command` to `run_command|write_file|edit_file`. Added `_AGY_MATCHER` and `_AGY_LEGACY_MATCHER` constants. `_agy_hook_entry` uses the widened matcher. `_agy_active_hook` accepts both legacy and widened matchers. Added `_agy_hook_matcher` (broader: returns any matcher for our command). `_install_agy_hook` migrates receipt-owned legacy entries in place, reports not-owned and user-edited matchers. `_agy_permissions_report` adds `matcher` and `stale` keys. Updated `.agents/hooks.json`. Added 5 new tests (migration, stale status, user-edited matcher, roundtrip, launcher write_file). All 27 + 212 + 115 tests pass.

**Deviations from spec**: `_agy_hook_matcher` returns any matcher for our command (not just legacy/managed), so user-edited matchers are detected correctly. `_agy_permissions_report` only calls `_agy_hook_matcher` when the hook is active (`command is not None`), keeping `matcher=None` and `stale=False` for fully inactive hooks.
