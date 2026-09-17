# TASK-3379: Remove `--toolkits` / `--all-toolkits` from `parrot google install`

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3373, TASK-3376
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (Google Antigravity half). The owner's decision is a **full replacement**:
`parrot toolkits` becomes the only toolkit-selection surface, so the seeding flags
come off the wiki installer entirely (hard cut — no deprecation shim, per project
policy).

`parrot google install` keeps reconciling whatever `.parrot/mcp-toolkits.yaml`
declares; it simply stops *seeding*. To keep the removal discoverable rather than
silent, it gains a hint naming `parrot toolkits install` when the toolkit config
is absent or declares nothing (spec §8, resolved).

`google/cli.py` imports `available_templates` inside the callback (line 85). The `gemini` alias shares this module — `cli/__init__.py` maps **both** `google` and `gemini` to `parrot.knowledge.wiki.google.cli` — so the flag disappears from both spellings at once, and the flag-rejection test should cover both.

---

## Scope

- Delete the `--toolkits` and `--all-toolkits` options from
  `parrot/knowledge/wiki/google/cli.py` and the parameters they feed.
- Delete the `toolkits: Sequence[str] = ()` parameter and its seeding block from
  `install_google_integration`.
- Add the empty-config hint.
- Update the tests that exercise the removed flags.

**NOT in scope**: the other two hosts, the `parrot toolkits` group itself
(TASK-3376), `parrot mcp-local`'s error text (TASK-3380).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` | MODIFY | Delete both options and their parameters |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | Delete the `toolkits` parameter + seeding; add the hint |
| `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` | MODIFY | Drop flag coverage; assert the flags are rejected |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
# `from parrot.mcp.toolkit_seed import seed_toolkit_sections` is DELETED by this task.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py
#   line 64: the `"--toolkits", "toolkits_"` click.option        <- DELETE
#   line 70: the `"--all-toolkits"` click.option                 <- DELETE
#   line 87: the `names = ...` set-building expression         <- DELETE
#   the `toolkits_: str` and `all_toolkits: bool` callback parameters   <- DELETE

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def install_google_integration(...):                       # line 239
    #   line 245: `toolkits: Sequence[str] = (),`                  <- DELETE
    #   line 269: `if toolkits:`                                    <- DELETE block
    #   line 272: `seeded = seed_toolkit_sections(root, toolkits)` <- DELETE
def reconcile_toolkit_entries(...) -> tuple[list[str], list[str]]: ...   # created by TASK-3373

# Host config: mcp_config.json (user-global) + .agents/plugins/parrot/mcp_config.json
```

### Does NOT Exist
- ~~a deprecation shim for `--toolkits`~~ — this is a hard cut; the flag must be
  **rejected**, not accepted-with-warning.
- ~~`BUILTIN_TOOLKITS`~~ — deleted by TASK-3368, so an empty toolkit config is a
  normal state, not an error.
- ~~`install_google_integration(toolkits=...)`~~ — after this task the keyword does
  not exist; any caller passing it is a bug to fix, not to support.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_google_installer_toolkit_entries.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#install_google_integration",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Reconciliation must keep working.** Only seeding is removed; `parrot google
  install` still writes entries for every enabled section it finds.
- The hint fires when `load_toolkits_config(root).toolkits` is empty — that is the
  post-hard-cut state of every repo that has not yet run `parrot toolkits install`.
- Do not touch `reconcile_toolkit_entries` — it is TASK-3373's deliverable.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` — the command
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

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '"--toolkits",' packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py)
# DELETE the `"--toolkits", "toolkits_"` click.option decorator (verified: google/cli.py:64)
# DELETE the `"--all-toolkits"` click.option decorator (verified: google/cli.py:70)
# DELETE the `toolkits_: str` and `all_toolkits: bool` callback parameters
# DELETE the `names = ...` set-building expression (verified: google/cli.py:87)
# and stop passing `toolkits=` to install_google_integration.
# FILL IN: remove the now-unused `available_templates` import and any hint text
# that referenced the flags; bounded by AC9.
```
**Why**: removing the decorators is what makes Click reject `--toolkits` with a
"no such option" error — that rejection is the acceptance criterion, so do not
replace them with hidden or deprecated options.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def install_google_integration(' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# In install_google_integration (verified: google/installer.py:239):
#   DELETE the `toolkits: Sequence[str] = (),` parameter (verified: :245)
#   DELETE the `if toolkits:` block including the local
#     `from parrot.mcp.toolkit_seed import seed_toolkit_sections` import
#     and the `seed_toolkit_sections(root, toolkits)` call (verified: :269-272)
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

### `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` (MODIFY)
```python
# DELETE/REWRITE the cases that pass `--toolkits` / `--all-toolkits` or the
# `toolkits=` keyword.
# ADD:
def test_toolkits_flag_is_rejected():
    # AC9 — hard cut: the flag must not be silently accepted.
    # FILL IN: CliRunner invoke `google install --toolkits=memory`, assert a
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
- [ ] `google/cli.py` — drop the unused `available_templates` import and flag-referencing hint text; bounded by AC9
- [ ] `google/installer.py` — place the empty-config hint where `actions` is in scope; bounded by AC9
- [ ] `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` — flag-rejection and hint cases; bounded by AC9

---

## Acceptance Criteria

- [ ] `parrot google install --toolkits=memory` exits non-zero with "no such option"
- [ ] `parrot google install --all-toolkits` likewise
- [ ] `install_google_integration` no longer accepts a `toolkits` keyword
- [ ] `parrot google install` still reconciles entries for every enabled section
- [ ] An empty/absent toolkit config produces an action naming `parrot toolkits install`
- [ ] No `seed_toolkit_sections` import remains in `google/`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/google/`

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_google_installer_toolkit_entries.py -q`

---

## Test Specification

See the MODIFY block above. Add a case asserting that a repo WITH enabled sections
still gets its entries written by `parrot google install` — the removal must not
break reconciliation.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 8, §8 resolved decisions).
2. **Check dependencies** — TASK-3373 and TASK-3376 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — line numbers shift once TASK-3373 lands; re-grep
   `"--toolkits",` and `def install_google_integration(` before editing.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3379-google-flag-cut.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
