# TASK-2649: Codex installer parity — managed `.codex/config.toml` toolkit tables

**Feature**: FEAT-485 — Expose Toolkits as Local MCP
**Spec**: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2645, TASK-2647
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Codex parity is in scope: `parrot codex install` /
`uninstall` manage per-toolkit `mcp_servers.parrot-<name>` TOML tables in
`.codex/config.toml`, inside the existing managed marker block, using the
installer's existing marker/TOML helpers.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py`:
  extend the MCP block builder (or add `toolkit_mcp_block(...)`) to emit,
  inside the SAME managed marker block as the wikitoolkit table, one
  `[mcp_servers.parrot-<name>]` table per enabled toolkit section:
  `command = <abs parrot bin>`, `args = ["mcp-local", "<name>"]`, and an
  `env` inline table when the section has env vars. Reuse
  `resolve_binary(root, name)` (assets.py:45) for the parrot binary.
- MODIFY `.../codex/installer.py`:
  - `_install_mcp(root)` (line 101): build the full managed block
    (wikitoolkit + enabled toolkits) from `load_toolkits_config(root)` and
    upsert it via `_upsert_marker_block`; validate with `_validate_toml`.
    Re-running reconciles (disabled/deleted sections disappear because the
    whole managed block is regenerated).
  - `uninstall_codex_integration` (line 178): the existing marker-block
    removal already removes everything inside the block — verify toolkit
    tables are gone after uninstall (also check the `_remove_toml_table`
    path at line 53/196-203 for any per-table cleanup done outside the
    marker block).
  - `integration_status` (line 221): keep truthful (block presence check at
    line 234 still works; optionally report toolkit count).
- Unit tests.

**NOT in scope**: Claude Code installer (TASK-2648); any change to the
wikitoolkit table content; Codex agents/rules/skills sections of the
installer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | toolkit tables in the managed MCP block |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | config-driven block build + reconciliation |
| `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py` | CREATE | unit tests (corrected path — see Codebase Contract note) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # created by TASK-2645
from parrot.knowledge.wiki.codex import assets              # existing module
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:  # line 16
def _remove_marker_block(text: str, begin: str, end: str) -> str:  # line 30
def _validate_toml(path: Path, text: str) -> None:  # line 43
def _remove_toml_table(text: str, table: str) -> str:  # line 53
def _install_mcp(root: Path) -> str:  # line 101 — writes .codex/config.toml (line 102);
#   currently upserts assets.mcp_block(root) (line 109) and returns a
#   ".codex/config.toml — ..." status string (lines 115-118)
def install_codex_integration(...):  # line 152 — calls _install_mcp (line 170)
def uninstall_codex_integration(root: Path) -> list[str]:  # line 178
#   removes wikitoolkit MCP (status at line 203); reads config at line 196
def integration_status(root: Path) -> dict[str, Any]:  # line 221
#   checks assets.MCP_BEGIN in the config text (line 234)

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
def resolve_binary(root: Path, name: str) -> str:  # line 45 — reuse for "parrot"
def mcp_block(root: Path) -> str:  # line 53 — current wikitoolkit-only block
MCP_BEGIN  # marker constant — READ assets.py for its exact value and the
           # matching END marker before editing
```

### Stale Contract Entry (corrected)
- ~~`tests/wiki/codex/test_installer_toolkit_entries.py`~~ — no
  `tests/wiki/` directory exists in this repo (same stale-path issue found
  in TASK-2648). The actual test tree mirrors
  `packages/ai-parrot/src/parrot/knowledge/wiki/` at `tests/knowledge/wiki/`
  (see `tests/knowledge/wiki/test_codex_integration.py`, which already
  covers the rest of this installer). Corrected path:
  `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py`.

### Does NOT Exist
- ~~`assets.toolkit_mcp_block`~~ — created by this task (or fold into an
  extended `mcp_block(root, config)` — implementer's choice, document it).
- ~~a TOML library dependency for WRITING~~ — the block is built as a
  string template (see current `mcp_block`) and validated by
  `_validate_toml`; do not add a TOML-writer dependency.
- ~~per-toolkit marker blocks~~ — ONE managed block contains all tables;
  reconciliation = regenerate the whole block.
- ~~`parrot codex install --toolkits` flag~~ — config-driven, no new flags.

---

## Implementation Notes

### Key Constraints
- The whole managed block is regenerated from config on each install —
  that IS the reconciliation (simpler than the JSON case; no foreign-entry
  problem inside our own marker block).
- Foreign `mcp_servers.*` tables OUTSIDE the marker block are never
  touched. A foreign table named `parrot-<name>` outside the block →
  leave it; TOML duplicate-table collision will be caught by
  `_validate_toml` — in that case warn + omit our table (mirror
  TASK-2648's warn-and-skip semantics).
- Status strings follow the existing `".codex/config.toml — ..."` convention.
- TOML string escaping: paths and env values must be quoted safely (use
  the same quoting style as the existing `mcp_block`).

---

## Acceptance Criteria

- [ ] Enabled sections → `[mcp_servers.parrot-<name>]` tables inside the managed block; `_validate_toml` passes
- [ ] Re-run reconciles: disabled/deleted sections' tables gone
- [ ] Wikitoolkit table content unchanged
- [ ] Uninstall removes all toolkit tables (marker block gone)
- [ ] Foreign tables outside the block untouched; duplicate-name collision → warn + omit
- [ ] Tests pass: `pytest tests/wiki/codex/test_installer_toolkit_entries.py -v`; ruff clean

---

## Test Specification

```python
# tests/wiki/codex/test_installer_toolkit_entries.py
def test_install_writes_toolkit_tables(tmp_root_with_config): ...
def test_install_is_idempotent(tmp_root_with_config): ...
def test_disabled_section_table_removed_on_rerun(tmp_root_with_config): ...
def test_wikitoolkit_table_unchanged(tmp_root_with_config): ...
def test_uninstall_removes_tables(tmp_root_with_config): ...
def test_toml_always_valid(tmp_root_with_config): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2645, TASK-2647 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `assets.mcp_block` and the
   marker constants FIRST
4. **Update status** in `sdd/tasks/index/expose-toolkits-as-local-mcp.json` → `"in-progress"`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index** → `"done"`, **fill in the Completion Note**

---

## Completion Note

**Completed by**: sdd-start (Claude)
**Date**: 2026-09-01
**Notes**:
- `assets.py`: added `toolkit_mcp_block(root, sections)` — renders one
  `[mcp_servers.parrot-<name>]` TOML table per (name, section) pair it is
  given (an inline `env = { ... }` table when `section.env` is non-empty),
  reusing `resolve_binary(root, "parrot")`. Extended `mcp_block(root,
  toolkit_block="")` with an optional pre-built `toolkit_block` parameter
  embedded inside the SAME `MCP_BEGIN`/`MCP_END` marker pair as the
  wikitoolkit table; the default (`""`) reproduces the original
  wikitoolkit-only block byte-for-byte (verified — `mcp_block(root)` with
  no args is unchanged). `ToolkitSection` is imported only under
  `TYPE_CHECKING` (module already has `from __future__ import
  annotations`), matching the pattern used in TASK-2648's `claude_code/assets.py`.
- `installer.py`: added `_existing_table_names(text)` (scans
  `_TABLE_HEADER` matches) and rewired `_install_mcp` to, after its
  unchanged wikitoolkit-table removal/validation steps,
  `load_toolkits_config(root)`, filter to enabled sections, and for each
  one check whether `mcp_servers.parrot-<name>` already exists as a
  foreign table OUTSIDE the marker block (`without_existing`) — if so,
  print a stderr warning and omit that toolkit from the block instead of
  producing a duplicate-table TOML that `_validate_toml` would reject.
  The surviving sections are rendered via `toolkit_mcp_block` and passed
  into `mcp_block`; the whole managed block is regenerated on every
  install, which **is** the reconciliation (disabled/deleted sections
  simply vanish from the regenerated block — no per-table tracking).
  `uninstall_codex_integration` needed NO changes: it already removes the
  entire `MCP_BEGIN`/`MCP_END` block, which now happens to contain every
  toolkit table too. Extended `integration_status` with an additional
  `toolkit_count` key (counts `[mcp_servers.parrot-` table headers inside
  the current block) — additive only; `codex/cli.py`'s `status` display
  iterates a fixed `labels` dict so the new key is safely ignored there.
- Added `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py` (8
  tests): enabled sections get tables and disabled ones don't; a second
  run with no config change is byte-identical; disabling a
  previously-enabled section drops its table on re-run; the wikitoolkit
  table's `args`/`default_tools_approval_mode`/`command` are unaffected;
  uninstall removes the whole block (wikitoolkit + all toolkit tables);
  the written config always parses as valid TOML; a foreign table with an
  unrelated name is preserved; a foreign `parrot-<name>` table is left
  untouched with a stderr warning (`capsys`) instead of causing a
  duplicate-table TOML error. All 8 pass; `ruff check` clean on all three
  touched files (verified zero *new* findings on `installer.py` — same 4
  pre-existing `Optional`/style findings before and after, via `git
  stash`).
- Ran the existing `tests/knowledge/wiki/test_codex_integration.py` suite
  (6/6 still pass unmodified) and the full `tests/knowledge/wiki/` suite
  (1211 passed, only the TASK-2648-noted pre-existing
  `test_fresh_install_writes_all_artifacts` failure, unrelated to Codex).
  Also confirmed `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py`
  (a separate, stale duplicate test tree under the package's own
  `tests/`) already fails to even *collect* on the pre-task commit
  (`ModuleNotFoundError: parrot.utils.types`, unrelated import-chain
  issue) — confirmed via `git stash` — so it is not part of the
  effectively-running suite and out of scope.
- Corrected the same stale Codebase Contract test-path pattern found in
  TASK-2648: the task named
  `tests/wiki/codex/test_installer_toolkit_entries.py`, but no
  `tests/wiki/` directory exists — corrected to
  `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py`, mirroring
  `test_codex_integration.py`.

**Deviations from spec**: none, beyond the stale test-path correction
noted above (test location only, not scope/behavior) and the additive
`toolkit_count` field on `integration_status` (explicitly optional per
the task's Scope note).
