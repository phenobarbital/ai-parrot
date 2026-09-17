# TASK-3371: Claude Code toolkit-only reconciler + `toolkit_server_names`

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (Claude half), driven by design research **S1** and **S3** (both
CONFIRM, both `risk: high`).

`_install_mcp_json` (`claude_code/installer.py:462`) reconciles **both** the
`wikitoolkit` entry and the managed `parrot-<name>` entries. `parrot toolkits`
must never touch wikitoolkit — that server stays owned by `parrot claude install`.
Calling `_install_mcp_json` from the new command would silently rewrite an
artifact outside its ownership (spec Goals, AC5).

Separately, `_managed_server_names` (`:304`) seeds its result with
`["wikitoolkit"]` at `:332`. Reusing it to compute approvals for
`parrot toolkits` would authorize wikitoolkit from a command that is supposed to
be blind to it.

This task splits both concerns without duplicating logic: the toolkit half becomes
a public function, and `_install_mcp_json` calls it.

---

## Scope

- Extract the `parrot-<name>` reconciliation out of `_install_mcp_json` into a
  public `reconcile_toolkit_entries(root)`.
- Refactor `_install_mcp_json` to call it, so there is one implementation.
- Split `toolkit_server_names(root)` out of `_managed_server_names`, without the
  `"wikitoolkit"` seed; `_managed_server_names` then calls it and prepends.
- Test that a toolkit-only reconcile leaves the wikitoolkit entry byte-identical
  and still preserves foreign `parrot-<name>` keys.

**NOT in scope**: the `HostAdapter` protocol (TASK-3374), removing `--toolkits`
from the CLI (TASK-3377), Codex (TASK-3372) or Google (TASK-3373).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Extract `reconcile_toolkit_entries` + `toolkit_server_names` |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` | MODIFY | Toolkit-only reconcile preserves wikitoolkit |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
# Already imported inside the functions in this module — keep the local-import style.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _managed_server_names(root: Path) -> list[str]:          # line 304
    # line 321: `from parrot.mcp.toolkit_config import load_toolkits_config`  (local import)
    # line 332: `names = ["wikitoolkit"]`                     <- the seed to split out
    # line 333-336: `for name, section in sorted(cfg.toolkits.items()):`
    #                   key = f"parrot-{name}"                # line 334
    #                   if section.enabled and _is_managed_toolkit_entry(servers.get(key), root, name):
    #                       names.append(key)
def _install_mcp_approval(root: Path) -> str: ...            # line 340
def _uninstall_mcp_approval(root: Path, removed_toolkit_names: Sequence[str] = ()) -> str | None: ...  # line 371
    # ALREADY name-selective — reuse as-is, do not change its signature.
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:   # line 420
    # line 440: `if not isinstance(args, list) or args[:2] != ["mcp-local", name]: return False`
    # accepts the pinned shape ["mcp-local", name, "--config", <path>] and the legacy 2-arg shape
def _install_mcp_json(root: Path) -> str:                    # line 462
    # line 512: `key = f"parrot-{name}"`
    # line 517: foreign entry -> warn + skip (`if existing is not None and not _is_managed_toolkit_entry(...)`)
    # line 528: `for key in [k for k in servers if k != "wikitoolkit" and k.startswith("parrot-")]:`
    # line 529: `name = key[len("parrot-"):]`
    # line 532: `if _is_managed_toolkit_entry(servers[key], root, name):`  -> cleanup of disabled/deleted

# Config file: <root>/.mcp.json  with root key "mcpServers"
# Entry shape written for a toolkit (mirrors google/assets.py:91-99):
#   {"command": <parrot bin>, "args": ["mcp-local", <name>, "--config", <abs cfg path>],
#    "cwd": <root>, "env": {...}}
```

### Does NOT Exist
- ~~`claude_code.installer.reconcile_toolkit_entries`~~ / ~~`toolkit_server_names`~~
  — these are what THIS task creates.
- ~~`claude_code/assets.py::toolkit_mcp_entries`~~ — **does not exist in the
  claude_code package.** That helper lives in `google/assets.py:81`. The Claude
  installer builds its entries inline inside `_install_mcp_json`. Do not import a
  claude_code assets helper that isn't there.
- ~~a `wikitoolkit=False` parameter on `_install_mcp_json`~~ — the split is a new
  function, not a flag.
- ~~`_managed_toolkit_names`~~ — the existing function is `_managed_server_names`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_mcp_json",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_managed_server_names",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_is_managed_toolkit_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_mcp_approval",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_uninstall_mcp_approval",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Behavior-preserving refactor.** `_install_mcp_json`'s observable output
  (actions string, warnings, resulting `.mcp.json`) must not change. Existing
  tests in `test_installer_mcp.py` are the regression net.
- The foreign-entry warn-and-skip at `:517` and the cleanup loop at `:528-532`
  both move into the new function — they are toolkit concerns, not wiki concerns.
- Keep the local-import style for `load_toolkits_config` (the module deliberately
  avoids a top-level import of `parrot.mcp`).
- `_uninstall_mcp_approval` already takes `removed_toolkit_names` — do **not**
  change it; TASK-3375 passes the toolkit names it removed.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:162-191` — the
  same toolkit reconcile/cleanup shape, for cross-checking the extraction

---

## Implementation Blueprint

### Steps (in order)
1. Add `toolkit_server_names(root)` and rewrite `_managed_server_names` to call it
   — *why*: the `["wikitoolkit"]` seed is exactly what must not leak into
   `parrot toolkits` approvals (S3), and splitting it is a two-line change.
2. Add `reconcile_toolkit_entries(root)` holding the `parrot-<name>` upsert,
   foreign-skip and cleanup logic lifted from `_install_mcp_json` — *why*: one
   implementation, callable with or without the wiki half.
3. Rewrite `_install_mcp_json` to do its wikitoolkit work then delegate — *why*:
   guarantees the two paths can never diverge, which a copy-paste would not.
4. Add the preservation tests — *why*: AC5 is the whole point of the task and is
   not observable from the refactor alone.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _managed_server_names(root: Path) -> list[str]:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# BEFORE — insert above `def _managed_server_names(root: Path) -> list[str]:`
# (verified: claude_code/installer.py:304)
def toolkit_server_names(root: Path) -> list[str]:
    """Return the `parrot-<name>` keys in .mcp.json confirmed managed by us.

    Deliberately EXCLUDES "wikitoolkit": `parrot toolkits` must never authorize or
    de-authorize the wiki server (FEAT-570 AC5). `_managed_server_names` prepends
    it for the full-integration path.

    Must be called AFTER `.mcp.json` has been reconciled, so the entry-shape check
    reflects the final state.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    path = root / ".mcp.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    servers = servers if isinstance(servers, dict) else {}

    cfg = load_toolkits_config(root)
    names: list[str] = []
    for name, section in sorted(cfg.toolkits.items()):
        key = f"parrot-{name}"
        if section.enabled and _is_managed_toolkit_entry(servers.get(key), root, name):
            names.append(key)
    return names
```
**Why this shape**: this is `_managed_server_names`' body (`:321-337`) with the
`["wikitoolkit"]` seed removed — lifted rather than rewritten so the
managed-shape semantics and the "call me after reconciliation" ordering
requirement are preserved exactly. `_managed_server_names` then becomes
`return ["wikitoolkit", *toolkit_server_names(root)]`, keeping its docstring's
promise intact for the wiki installer.

```python
# occurrences: 1 (verified: grep -cF 'def _install_mcp_json(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# BEFORE — insert above `def _install_mcp_json(root: Path) -> str:`
# (verified: claude_code/installer.py:462)
def reconcile_toolkit_entries(root: Path) -> tuple[list[str], list[str]]:
    """Reconcile ONLY the `parrot-<name>` keys of .mcp.json from the toolkit config.

    Never reads or writes the "wikitoolkit" key, and never touches any other
    foreign key (FEAT-570 AC5). Upserts one entry per ENABLED section, skips a
    `parrot-<name>` key whose content is not our shape (reported as a warning),
    and deletes managed entries whose section is disabled or gone.

    Returns:
        (actions, warnings) — human-readable strings.
    """
    # FILL IN: lift the toolkit half of _install_mcp_json (verified:
    # claude_code/installer.py:512-532) — the `key = f"parrot-{name}"` upsert, the
    # foreign warn-and-skip at :517, and the cleanup loop at :528-532 — reading and
    # writing .mcp.json itself. Bounded by AC5: the "wikitoolkit" key must be
    # absent from every read-modify-write path here.
    raise NotImplementedError
```
**Why**: returning `(actions, warnings)` instead of a single joined string is what
lets TASK-3374's `HostAdapter` surface collisions to the CLI as real warnings
rather than prose buried in an action line. `_install_mcp_json` keeps returning
its single string by joining what this returns with its own wikitoolkit action.

```python
# occurrences: 1 (verified: grep -cF 'def _install_mcp_json(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# MODIFY `_install_mcp_json` (verified: claude_code/installer.py:462):
#   keep its wikitoolkit upsert, then DELETE lines 512-532 and call
#   `reconcile_toolkit_entries(root)` in their place, folding the returned
#   actions/warnings into its existing return string.
# FILL IN: the delegation + message assembly — the function's returned text and
# the resulting .mcp.json must be unchanged for existing callers; bounded by the
# existing test_installer_mcp.py assertions.
```
**Why**: a behavior-preserving refactor is the only safe way to avoid two
reconcilers. If the returned string must change shape, change the tests
deliberately — do not let it drift silently.

### `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` (MODIFY)
```python
# ADD (do not remove existing cases — they are the refactor's regression net):
def test_reconcile_toolkit_entries_preserves_wikitoolkit(tmp_path): ...
def test_reconcile_toolkit_entries_preserves_foreign_entry(tmp_path): ...
def test_toolkit_server_names_excludes_wikitoolkit(tmp_path): ...
# FILL IN: bodies — the wikitoolkit case must compare the entry's exact JSON value
# before and after, not merely assert the key still exists; bounded by AC5.
```
**Why**: asserting only "the key is present" would pass even if the entry were
rewritten with a different binary path or args, which is exactly the failure S1
warned about.

### FILL IN checklist
- [ ] `installer.py::reconcile_toolkit_entries` — lift the toolkit half of `_install_mcp_json`; bounded by AC5
- [ ] `installer.py::_install_mcp_json` — delegate and preserve its returned text; bounded by existing tests
- [ ] `test_installer_mcp.py` — three cases, wikitoolkit compared by value; bounded by AC5

---

## Acceptance Criteria

- [ ] `reconcile_toolkit_entries` exists and is importable from
      `parrot.knowledge.wiki.claude_code.installer`
- [ ] A toolkit-only reconcile leaves the `wikitoolkit` entry **byte-identical**
- [ ] A foreign `parrot-<name>` entry is preserved and reported as a warning
- [ ] A disabled/removed section's managed entry is deleted
- [ ] `toolkit_server_names(root)` never returns `"wikitoolkit"`
- [ ] `_managed_server_names(root)` still returns `"wikitoolkit"` first (unchanged)
- [ ] `_uninstall_mcp_approval`'s signature is unchanged
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py
import json
from parrot.knowledge.wiki.claude_code.installer import (
    reconcile_toolkit_entries, toolkit_server_names,
)


def test_reconcile_toolkit_entries_preserves_wikitoolkit(tmp_path):
    """AC5 — the wiki server is not ours to touch."""
    # FILL IN: seed .mcp.json with a wikitoolkit entry + one managed parrot-memory
    # entry, snapshot the wikitoolkit value, reconcile, assert deep equality
    ...


def test_toolkit_server_names_excludes_wikitoolkit(tmp_path):
    assert "wikitoolkit" not in toolkit_server_names(tmp_path)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 2, §7 Known Risks, design research S1 and S3).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `_install_mcp_json` is still at
   `:462`, `_managed_server_names` at `:304` and the seed at `:332`.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3371-claude-toolkit-only-reconciler.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
