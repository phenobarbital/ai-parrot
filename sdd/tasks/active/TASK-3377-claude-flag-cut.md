# TASK-3377: Remove `--toolkits` / `--all-toolkits` from `parrot claude install`

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3371, TASK-3376
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (Claude Code half). The owner's decision is a **full replacement**:
`parrot toolkits` becomes the only toolkit-selection surface, so the seeding flags
come off the wiki installer entirely (hard cut — no deprecation shim, per project
policy).

`parrot claude install` keeps reconciling whatever `.parrot/mcp-toolkits.yaml`
declares; it simply stops *seeding*. To keep the removal discoverable rather than
silent, it gains a hint naming `parrot toolkits install` when the toolkit config
is absent or declares nothing (spec §8, resolved).

`claude_code/cli.py` also imports `available_templates` at **module level** (line 26) and prints a fallback hint naming the flags at line 147 — both go with the options.

---

## Scope

- Delete the `--toolkits` and `--all-toolkits` options from
  `parrot/knowledge/wiki/claude_code/cli.py` and the parameters they feed.
- Delete the `toolkits: Sequence[str] = ()` parameter and its seeding block from
  `install_claude_integration`.
- Add the empty-config hint.
- Update the tests that exercise the removed flags.

**NOT in scope**: the other two hosts, the `parrot toolkits` group itself
(TASK-3376), `parrot mcp-local`'s error text (TASK-3380).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | Delete both options and their parameters |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Delete the `toolkits` parameter + seeding; add the hint |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` | MODIFY | Drop flag coverage; assert the flags are rejected |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
# `from parrot.mcp.toolkit_seed import seed_toolkit_sections` is DELETED by this task.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
#   line 90: the `"--toolkits", "toolkits_"` click.option        <- DELETE
#   line 96: the `"--all-toolkits"` click.option                 <- DELETE
#   line 127: the `names = ...` set-building expression         <- DELETE
#   the `toolkits_: str` and `all_toolkits: bool` callback parameters   <- DELETE

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def install_claude_integration(...):                       # line 770
    #   line 776: `toolkits: Sequence[str] = (),`                  <- DELETE
    #   line 818: `if toolkits:`                                    <- DELETE block
    #   line 821: `seeded = seed_toolkit_sections(root, toolkits)` <- DELETE
def reconcile_toolkit_entries(...) -> tuple[list[str], list[str]]: ...   # created by TASK-3371

# Host config: .mcp.json
```

### Does NOT Exist
- ~~a deprecation shim for `--toolkits`~~ — this is a hard cut; the flag must be
  **rejected**, not accepted-with-warning.
- ~~`BUILTIN_TOOLKITS`~~ — deleted by TASK-3368, so an empty toolkit config is a
  normal state, not an error.
- ~~`install_claude_integration(toolkits=...)`~~ — after this task the keyword does
  not exist; any caller passing it is a bug to fix, not to support.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Reconciliation must keep working.** Only seeding is removed; `parrot claude
  install` still writes entries for every enabled section it finds.
- The hint fires when `load_toolkits_config(root).toolkits` is empty — that is the
  post-hard-cut state of every repo that has not yet run `parrot toolkits install`.
- Do not touch `reconcile_toolkit_entries` — it is TASK-3371's deliverable.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` — the command
- `packages/ai-parrot/src/parrot/cli/toolkits.py` — the replacement (TASK-3376)

---

## Implementation Blueprint

### Steps (in order)
1. Delete the two options and their callback parameters in `cli.py` — *why*: Click
   will reject the flags automatically once the options are gone, which is the
   hard cut AC9 asks for.
2. Delete the `toolkits` parameter and its seeding block in `installer.py` —
   *why*: leaving the parameter would let a caller keep seeding through a back
   door the CLI no longer exposes.
3. Add the empty-config hint — *why*: without it the flag's disappearance is
   silent and operators will think toolkit support was dropped.
4. Update the tests — *why*: they currently pass the removed flags.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '"--toolkits",' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# DELETE the `"--toolkits", "toolkits_"` click.option decorator (verified: claude_code/cli.py:90)
# DELETE the `"--all-toolkits"` click.option decorator (verified: claude_code/cli.py:96)
# DELETE the `toolkits_: str` and `all_toolkits: bool` callback parameters
# DELETE the `names = ...` set-building expression (verified: claude_code/cli.py:127)
# and stop passing `toolkits=` to install_claude_integration.
# FILL IN: remove the now-unused `available_templates` import and any hint text
# that referenced the flags; bounded by AC9.
```
**Why**: removing the decorators is what makes Click reject `--toolkits` with a
"no such option" error — that rejection is the acceptance criterion, so do not
replace them with hidden or deprecated options.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def install_claude_integration(' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# In install_claude_integration (verified: claude_code/installer.py:770):
#   DELETE the `toolkits: Sequence[str] = (),` parameter (verified: :776)
#   DELETE the `if toolkits:` block including the local
#     `from parrot.mcp.toolkit_seed import seed_toolkit_sections` import
#     and the `seed_toolkit_sections(root, toolkits)` call (verified: :818-821)
#   UPDATE the docstring: seeding moved to `parrot toolkits` (FEAT-570)
#
# ADD the discoverability hint after MCP reconciliation:
    from parrot.mcp.toolkit_config import load_toolkits_config

    if not load_toolkits_config(root).toolkits:
        actions.append(
            "no local MCP toolkits configured — add them with: parrot toolkits install"
        )
# FILL IN: place the hint where `actions` is already in scope and before the
# function returns; bounded by AC9.
```
**Why**: the hint is appended to the same `actions` list the command already
prints, so it needs no new output plumbing. Checking
`load_toolkits_config(root).toolkits` rather than the file's existence means a
file that exists but declares nothing also gets the hint.

### `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` (MODIFY)
```python
# DELETE/REWRITE the cases that pass `--toolkits` / `--all-toolkits` or the
# `toolkits=` keyword.
# ADD:
def test_toolkits_flag_is_rejected():
    # AC9 — hard cut: the flag must not be silently accepted.
    # FILL IN: CliRunner invoke `claude install --toolkits=memory`, assert a
    # non-zero exit and "no such option" in the output; bounded by AC9.
    ...


def test_empty_toolkit_config_hints_at_new_command(tmp_path):
    # FILL IN: assert the returned actions mention `parrot toolkits install`;
    # bounded by AC9.
    ...
```
**Why**: asserting the flag is *rejected* (not merely absent from `--help`) is
what proves no compatibility shim was left behind.

### FILL IN checklist
- [ ] `claude_code/cli.py` — drop the unused `available_templates` import and flag-referencing hint text; bounded by AC9
- [ ] `claude_code/installer.py` — place the empty-config hint where `actions` is in scope; bounded by AC9
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` — flag-rejection and hint cases; bounded by AC9

---

## Acceptance Criteria

- [ ] `parrot claude install --toolkits=memory` exits non-zero with "no such option"
- [ ] `parrot claude install --all-toolkits` likewise
- [ ] `install_claude_integration` no longer accepts a `toolkits` keyword
- [ ] `parrot claude install` still reconciles entries for every enabled section
- [ ] An empty/absent toolkit config produces an action naming `parrot toolkits install`
- [ ] No `seed_toolkit_sections` import remains in `claude_code/`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`

---

## Test Specification

See the MODIFY block above. Add a case asserting that a repo WITH enabled sections
still gets its entries written by `parrot claude install` — the removal must not
break reconciliation.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 8, §8 resolved decisions).
2. **Check dependencies** — TASK-3371 and TASK-3376 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — line numbers shift once TASK-3371 lands; re-grep
   `"--toolkits",` and `def install_claude_integration(` before editing.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3377-claude-flag-cut.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
