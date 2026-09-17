# TASK-3372: Codex toolkit-only reconciler (`reconcile_toolkit_tables`)

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (Codex half), driven by design research **S1** and **S2** (both
CONFIRM, both `risk: high`).

`codex/installer.py::_install_mcp` (`:110`) regenerates one managed marker block
containing **both** the wikitoolkit table and one
`[mcp_servers.parrot-<name>]` table per enabled section. `parrot toolkits` must
leave wikitoolkit alone (AC5), so the toolkit half needs its own entry point.

Codex is the **asymmetric** host that S2 warned about: it has **no
`_is_managed_toolkit_entry`**. Ownership is decided structurally instead — a table
inside the managed marker block is ours; a table with the same name outside it is
foreign and is warned about and skipped (`_install_mcp`'s docstring, `:117-121`).
Reconciliation is "regenerate the whole managed block from config", so removal of
a disabled section needs no per-table tracking.

---

## Scope

- Extract the `parrot-<name>` table generation out of `_install_mcp` into a public
  `reconcile_toolkit_tables(root)` that preserves the wikitoolkit table verbatim.
- Refactor `_install_mcp` to call it.
- Test that a toolkit-only reconcile leaves the wikitoolkit table unchanged and
  still skips a foreign `[mcp_servers.parrot-<name>]` table outside the block.

**NOT in scope**: the `HostAdapter` protocol (TASK-3374), removing `--toolkits`
from `codex/cli.py` (TASK-3378), Claude (TASK-3371) or Google (TASK-3373).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | Extract `reconcile_toolkit_tables` |
| `tests/knowledge/wiki/test_codex_toolkit_reconcile.py` | CREATE | Wikitoolkit + foreign-table preservation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
from parrot.knowledge.wiki.codex import assets              # verified: codex/assets.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str: ...  # line 17
def _remove_marker_block(text: str, begin: str, end: str) -> str: ...              # line 31
def _validate_toml(path: Path, text: str) -> None: ...                             # line 44
def _remove_toml_table(text: str, table: str) -> str: ...                          # line 54
def _existing_table_names(text: str) -> set[str]: ...                              # line 100
def _install_mcp(root: Path) -> str:                                               # line 110
    # line 122: `from parrot.mcp.toolkit_config import load_toolkits_config`  (local import)
    # line 125: `path = root / ".codex" / "config.toml"`
    # line 126-128: read `before`, `_validate_toml`, `_remove_marker_block(before, assets.MCP_BEGIN, assets.MCP_END)`
    # line 129: `_remove_toml_table(without_managed, assets.MCP_TABLE)`
    # line 130: `cfg = load_toolkits_config(root)`
    # line 131: `existing_tables = _existing_table_names(without_existing)`
    # line 134-147: build `sections` dict, skipping disabled sections and
    #               name-colliding tables found OUTSIDE the managed block
    # line 148: `toolkit_block = assets.toolkit_mcp_block(root, sections)`
    # line 153: `assets.mcp_block(root, toolkit_block)`  <- wikitoolkit + toolkits together
    # line 159/165/168: the three returned action strings
def install_codex_integration(..., toolkits: Sequence[str] = (), ...) -> list[str]: ...  # line 202

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str: ...  # line 60
# assets.MCP_BEGIN / assets.MCP_END / assets.MCP_TABLE — marker + table constants
# assets.mcp_block(root, toolkit_block) — composes the wikitoolkit table WITH the
#   toolkit block into the full managed block

# Config file: <root>/.codex/config.toml
# Toolkit table name: [mcp_servers.parrot-<name>]
```

### Does NOT Exist
- ~~`codex.installer._is_managed_toolkit_entry`~~ — **does not exist.** This is the
  asymmetry S2 flagged. Ownership here is the managed marker block plus
  `_existing_table_names`; do not import or invent a per-entry shape check.
- ~~`codex/assets.py::toolkit_mcp_entries`~~ — the Codex helper is
  `toolkit_mcp_block` (returns TOML text, `:60`), not a dict of entries. The
  `toolkit_mcp_entries` name belongs to `google/assets.py:81`.
- ~~`codex.installer.reconcile_toolkit_tables`~~ — what THIS task creates.
- ~~a per-table removal step for disabled sections~~ — the managed block is
  regenerated wholesale, so a disabled section simply is not emitted.
- ~~`_install_mcp_json`~~ — that is the Claude function name, not Codex's.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_codex_toolkit_reconcile.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_install_mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_existing_table_names",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_upsert_marker_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_validate_toml",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#toolkit_mcp_block",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The wikitoolkit table lives inside the same managed marker block.** A
  toolkit-only reconcile therefore cannot simply regenerate the block — it must
  preserve the existing wikitoolkit table text and regenerate only the
  `parrot-<name>` tables around it. This is the crux of the task.
- `_validate_toml` must run on the result before writing; never write TOML that
  does not parse.
- Preserve the warn-and-skip for a `parrot-<name>` table already present OUTSIDE
  the managed block (`_install_mcp` docstring `:117-121`).
- Behavior-preserving: `_install_mcp`'s returned action strings and the resulting
  file must not change for the full-integration path.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py:110-168` — the
  function being split
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:462` — the
  sibling Claude extraction (TASK-3371), for shape consistency

---

## Implementation Blueprint

### Steps (in order)
1. Decide how to preserve the wikitoolkit table: read the current managed block,
   extract the wikitoolkit table text, and re-compose it with a freshly generated
   toolkit block — *why*: Codex's whole-block regeneration is what would otherwise
   rewrite wikitoolkit, and AC5 forbids that.
2. Add `reconcile_toolkit_tables(root)` returning `(actions, warnings)` — *why*:
   same contract as the Claude and Google siblings so TASK-3374's adapters are
   uniform.
3. Refactor `_install_mcp` to call it — *why*: one generator for the toolkit
   tables, no copy-paste drift.
4. Add the preservation tests — *why*: AC5 is not observable from the refactor.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _install_mcp(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# BEFORE — insert above `def _install_mcp(root: Path) -> str:`
# (verified: codex/installer.py:110)
def reconcile_toolkit_tables(root: Path) -> tuple[list[str], list[str]]:
    """Regenerate ONLY the `[mcp_servers.parrot-<name>]` tables in .codex/config.toml.

    The managed marker block also carries the wikitoolkit table; this function
    preserves that table's existing text verbatim and rewrites the toolkit tables
    around it (FEAT-570 AC5). A `parrot-<name>` table present OUTSIDE the managed
    block is foreign: it is reported as a warning and omitted, never overwritten.

    Codex has no per-entry managed-shape check (unlike Claude and Google) —
    ownership is structural: inside the marker block means ours.

    Returns:
        (actions, warnings) — human-readable strings.
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    path = root / ".codex" / "config.toml"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    _validate_toml(path, before)
    # FILL IN: extract the existing wikitoolkit table text out of the managed block
    # (marker constants assets.MCP_BEGIN / assets.MCP_END, verified: codex/installer.py:128),
    # build `sections` from ENABLED config sections while skipping names found by
    # `_existing_table_names` outside the block (pattern verified:
    # codex/installer.py:131-147), render them with `assets.toolkit_mcp_block(root, sections)`,
    # re-compose preserved-wikitoolkit + new-toolkit-block via `_upsert_marker_block`,
    # `_validate_toml` the result, and write only if changed.
    # Bounded by AC5 (wikitoolkit table byte-identical) and AC12 (valid TOML).
    raise NotImplementedError
```
**Why this shape**: the `(actions, warnings)` return matches TASK-3371 and
TASK-3373 so `HostAdapter.reconcile` (TASK-3374) has one signature across three
very different hosts. The docstring states the structural-ownership rule
explicitly because an implementer arriving from the Claude task will otherwise
look for `_is_managed_toolkit_entry` and not find it. Preserving the wikitoolkit
table as **text** (rather than regenerating it from assets) is deliberate: it
guarantees byte-identity even if the wiki entry's generator changes.

```python
# occurrences: 1 (verified: grep -cF 'def _install_mcp(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# MODIFY `_install_mcp` (verified: codex/installer.py:110): keep its wikitoolkit
# composition via `assets.mcp_block(...)` (verified: :153), and source the toolkit
# block from the same `sections`-building helper the new function uses, so the two
# paths cannot diverge.
# FILL IN: factor the shared `sections`-building + collision-warning logic
# (verified: codex/installer.py:134-147) into a module-private helper both
# functions call; the returned action strings at :159/:165/:168 must not change.
```
**Why**: `_install_mcp` legitimately regenerates the whole block including
wikitoolkit — that is its job. Only the *toolkit sections* computation is shared,
so that is what gets factored out, not the block composition.

### `tests/knowledge/wiki/test_codex_toolkit_reconcile.py` (CREATE)
```python
"""Codex toolkit-only reconciliation (FEAT-570, TASK-3372)."""
from __future__ import annotations

import pytest

from parrot.knowledge.wiki.codex.installer import reconcile_toolkit_tables  # verified: this task


def _write_config(root, body: str) -> None:
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "config.toml").write_text(body, encoding="utf-8")


def test_reconcile_preserves_wikitoolkit_table(tmp_path):
    """AC5 — the wiki table inside the managed block is not ours to rewrite."""
    # FILL IN: seed a config whose managed block holds a wikitoolkit table plus one
    # parrot-memory table, declare `memory` in .parrot/mcp-toolkits.yaml, reconcile,
    # and assert the wikitoolkit table's text is unchanged; bounded by AC5.


def test_reconcile_skips_foreign_table_outside_block(tmp_path):
    """A hand-written [mcp_servers.parrot-memory] outside the markers is untouched."""
    # FILL IN: assert the foreign table survives verbatim AND a warning is returned;
    # bounded by AC5.


def test_reconcile_output_is_valid_toml(tmp_path):
    # FILL IN: tomllib.loads the result; bounded by AC12.
```
**Why**: Codex is the host where a naive regeneration silently destroys the most
(a whole block, not one key), so all three cases assert on raw text rather than a
parsed round-trip.

### FILL IN checklist
- [ ] `installer.py::reconcile_toolkit_tables` — preserve wikitoolkit text, regenerate toolkit tables; bounded by AC5
- [ ] `installer.py` — factor the shared sections/collision helper out of `_install_mcp`; bounded by existing behavior
- [ ] `test_codex_toolkit_reconcile.py` — three cases asserting on raw TOML text; bounded by AC5, AC12

---

## Acceptance Criteria

- [ ] `reconcile_toolkit_tables` is importable from
      `parrot.knowledge.wiki.codex.installer` and returns `(actions, warnings)`
- [ ] A toolkit-only reconcile leaves the wikitoolkit table **byte-identical**
- [ ] A `parrot-<name>` table outside the managed block is preserved verbatim and
      reported as a warning
- [ ] A disabled section's table disappears from the regenerated block
- [ ] The written file always parses as TOML (`_validate_toml` runs before write)
- [ ] `_install_mcp`'s returned action strings are unchanged
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py`

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_codex_toolkit_reconcile.py -q`
- `pytest tests/knowledge/wiki/test_codex_bookstore.py -q`

---

## Test Specification

See the CREATE block above. Add a fourth case asserting that reconciling twice in
a row is idempotent (the second run reports no change), which is how the CLI will
behave when an operator re-runs `parrot toolkits install`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 2, design research S1 and S2).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `_install_mcp` is still at `:110`
   and that `_is_managed_toolkit_entry` genuinely does **not** exist in this module.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3372-codex-toolkit-only-reconciler.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
