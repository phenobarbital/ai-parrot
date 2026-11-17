# TASK-5131: Stale MCP toolkit entry removal (`remove_stale_mcp_entries`)

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5130
**Assigned-to**: unassigned

---

## Context

Spec G8, §2 "Stale MCP toolkit entries" and §3 Module 6 (`remove_stale_mcp_entries` skeleton). TASK-5130
finds the stale `parrot-<name>` entries; this task removes them, touching nothing else in each config file, and
drops the matching Claude approvals. TASK-5135 calls it from `parrot sdd uninstall --stalled`.

---

## Scope

- Add `remove_stale_mcp_entries(root, hosts, *, keep=(), dry_run=False, gemini_config=None) -> list[str]` to
  `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py`.
- `keep` globs (fnmatch) match the string `<file>#<key>` with `file` as displayed by `StaleMcpEntry.file`
  (`.mcp.json#parrot-memory`, `~/.gemini/config/mcp_config.json#parrot-lsp`).
- Per file: delete every non-kept stale key, write the file **once**. JSON: pop from `mcpServers` and save with
  `_save_mcp_config`. TOML: `_remove_toml_table(text, f"mcp_servers.{key}")` per key; when the managed marker
  block is left with no table header, remove the block with `_remove_marker_block`; `_validate_toml` the result
  and **never write** a file that fails (warning instead).
- After writing `.mcp.json`, call `uninstall_toolkit_approvals(root, <removed keys>)` and append its message.
- Output lines exactly as in the spec skeleton (see blueprint docstring).
- Add the removal tests to `packages/ai-parrot/tests/mcp/test_toolkit_stale.py`.

**NOT in scope**: re-registering toolkits (removal only, spec Non-Goals); editing `.parrot/mcp-toolkits.yaml`;
installer/CLI wiring (TASK-5132/5135); changing `find_stale_mcp_entries`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` | MODIFY | Add `remove_stale_mcp_entries` |
| `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` | MODIFY | Removal tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.codex import assets as codex_assets  # verified: codex/assets.py:19-20 (MCP_BEGIN, MCP_END)
from parrot.knowledge.wiki.codex.installer import _remove_marker_block, _remove_toml_table, _validate_toml  # verified: codex/installer.py:37, :60, :50
from parrot.knowledge.wiki.google.installer import _save_mcp_config  # verified: google/installer.py:64
from parrot.knowledge.wiki.claude_code.installer import uninstall_toolkit_approvals  # verified: claude_code/installer.py:577
# from TASK-5130 (same module): StaleMcpEntry, find_stale_mcp_entries, _mcp_files, _McpFile, _read_servers
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _remove_marker_block(text: str, begin: str, end: str) -> str   # line 37 — removes the whole block (incl. truncated)
def _validate_toml(path: Path, text: str) -> None                  # line 50 — raises RuntimeError when text is not TOML
def _remove_toml_table(text: str, table: str) -> str               # line 60 — removes `[table]` and `[table.*]`, keeps others
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"                       # line 19
MCP_END = "# <<< parrot-wiki Codex MCP <<<"                         # line 20
# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _save_mcp_config(path: Path, data: dict[str, Any]) -> None     # line 64 — json indent=2 + "\n"
def _load_mcp_config(path: Path) -> dict[str, Any]                 # line 46 — RuntimeError when unparsable
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def uninstall_toolkit_approvals(root: Path, removed_toolkit_names: Sequence[str]) -> Optional[str]  # line 577
#   removed_toolkit_names are the exact `parrot-<name>` keys; never touches "wikitoolkit"; returns a message or None
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig  # line 90
```

### Does NOT Exist
- ~~`_uninstall_mcp_approval` for this purpose~~ — it also strips `"wikitoolkit"`; use `uninstall_toolkit_approvals`.
- ~~a TOML writer (`tomli_w`, `toml.dumps`)~~ — not a dependency; edit TOML text with `_remove_toml_table`.
- ~~`reconcile_toolkit_entries` / `reconcile_toolkit_tables` as a cleanup path~~ — they keep foreign-repo and
  retired entries by design; do not call them here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_stale.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkit_stale.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_remove_marker_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_validate_toml",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_remove_toml_table",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_save_mcp_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#uninstall_toolkit_approvals",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Byte-identity: every key/table that is not removed — `wikitoolkit`, `bookstore`, foreign entries, kept entries —
  must survive unchanged. JSON files are re-serialized by `_save_mcp_config` (same format the installers write).
- Re-read each file at apply time (do not trust the detection snapshot's text) and only delete keys that are still
  present and still pass `is_parrot_toolkit_entry`.
- A file write that fails (OSError) or TOML that fails `_validate_toml` → one `warning:` line, file untouched,
  continue with the next file.
- Imports of `codex`/`claude_code` installers go at module top only if they add no cycle; if `ruff`/import errors
  show a cycle, move them inside the function (both are already imported lazily by `parrot.mcp.hosts`).

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and `remove_stale_mcp_entries` below — *why*: signature and output lines are spec-fixed.
2. Implement `_remove_from_file()` for JSON and TOML — *why*: one write per file, never a partial or invalid file.
3. Add the removal tests — *why*: AC-1..AC-6.

### `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` (MODIFY)
```python
# AFTER — append at the end of the module (after `find_stale_mcp_entries`, created by TASK-5130)
def _remove_from_file(item: _McpFile, keys: Sequence[str]) -> tuple[list[str], str | None]:
    """Delete ``keys`` from one config file and write it once. Returns (removed keys, warning or None)."""
    # FILL IN: json -> data = _load_mcp_config(item.path); pop each key still present and still
    #   is_parrot_toolkit_entry; _save_mcp_config only if something was popped.
    #   toml -> text = item.path.read_text(); for key: text = _remove_toml_table(text, f"mcp_servers.{key}");
    #   if codex_assets.MCP_BEGIN in text and the block between MCP_BEGIN/MCP_END holds no line starting with "[":
    #   text = _remove_marker_block(text, MCP_BEGIN, MCP_END); _validate_toml(item.path, text) before writing.
    #   Catch RuntimeError/OSError -> ([], f"warning: {item.display} — not changed ({exc})").
    raise NotImplementedError


def remove_stale_mcp_entries(
    root: Path,
    hosts: Sequence[str],
    *,
    keep: Sequence[str] = (),
    dry_run: bool = False,
    gemini_config: Path | None = None,
) -> list[str]:
    """dry_run → "plan: stale-mcp-remove <file>#<key> (<reason>)" lines. Real run: per file, drop the
    non-kept keys (JSON: ``mcpServers`` key; TOML: ``_remove_toml_table`` + ``_validate_toml``, and an emptied
    managed marker block is removed), write the file once, then ``uninstall_toolkit_approvals(root, removed)``
    for Claude. Lines: "<file>#<key> — removed (<reason>)", "<file>#<key> — kept (--keep)", and one
    "note: re-register with `parrot toolkits install <names>`" when a removed entry's toolkit is enabled here.
    Empty → ["no stale MCP entries"]."""
    entries = find_stale_mcp_entries(root, hosts, gemini_config=gemini_config)
    if not entries:
        return ["no stale MCP entries"]
    files = {item.display: item for item in _mcp_files(root, hosts, gemini_config)}
    lines: list[str] = []
    # FILL IN: split entries into kept (any fnmatch(f"{e.file}#{e.key}", glob) for glob in keep) and to_remove.
    #   dry_run -> "plan: stale-mcp-remove <file>#<key> (<reason>)" per to_remove and
    #   "plan: keep-stale <file>#<key> (--keep)" per kept; return.
    #   Real run: group to_remove by e.file; _remove_from_file(files[e.file], keys); one
    #   "<file>#<key> — removed (<reason>)" per removed key; warnings as returned; "<file>#<key> — kept (--keep)".
    #   If any key was removed from ".mcp.json": msg = uninstall_toolkit_approvals(root, removed_claude_keys);
    #   append msg when not None. Re-register note: names of removed keys that are enabled sections of
    #   load_toolkits_config(root) (ValueError -> skip the note), sorted, de-duplicated.
    return lines
```
**Why**: the function body is mostly bookkeeping fixed by the spec's output contract; the file edit is isolated so
a broken file can never take the others down.

### `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` (MODIFY)
```python
# AFTER — append at the end of the file (TASK-5130 created it; reuse its `repo`, `gemini`, `_entry` helpers)
# and add `remove_stale_mcp_entries` to the existing `from parrot.mcp.toolkit_stale import …` line.
# FILL IN: tests (always gemini_config=gemini):
#   test_remove_mcp_json_keeps_others (wikitoolkit/bookstore/foreign `parrot-x` byte-equal after removal),
#   test_codex_tables_removed_inside_and_outside_block (wikitoolkit table text unchanged; tomllib.loads(result) ok),
#   test_codex_emptied_block_removed (block with only the stale table -> block gone),
#   test_claude_approvals_dropped (.claude/settings.local.json enabledMcpjsonServers loses only the removed key),
#   test_keep_matches_file_key (keep=[".mcp.json#parrot-scraping"] -> kept line, file unchanged),
#   test_unparsable_file_untouched (invalid TOML -> warning line, bytes unchanged),
#   test_reregister_note (foreign-repo `parrot-browsing`, browsing enabled -> one note naming browsing),
#   test_dry_run_mcp_writes_nothing (all files byte-identical; lines start with "plan:"),
#   test_nothing_stale (["no stale MCP entries"]).
```

### FILL IN checklist
- [ ] `_remove_from_file` — JSON + TOML paths, emptied block, validate-before-write; bounded by AC-2, AC-5.
- [ ] `remove_stale_mcp_entries` — keep split, dry-run, grouping, approvals, re-register note; bounded by AC-1..AC-4.
- [ ] the 9 tests listed.

---

## Acceptance Criteria

- [ ] AC-1: every stale entry of the selected hosts is removed; `wikitoolkit`, `bookstore`, non-`parrot-` keys and
      foreign-shaped `parrot-*` entries stay byte-identical.
- [ ] AC-2: `.codex/config.toml` stays valid TOML; an emptied managed marker block is removed; an invalid file is never written.
- [ ] AC-3: removed Claude keys leave `enabledMcpjsonServers`; others (and `wikitoolkit`) stay.
- [ ] AC-4: `--keep '<file>#<key>'` keeps the entry; dry-run writes nothing.
- [ ] AC-5: removing an entry of an enabled toolkit ends with one `parrot toolkits install` note.
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_stale.py packages/ai-parrot/tests/mcp/test_toolkit_stale.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_toolkit_stale.py -q`

---

## Test Specification

See the blueprint; rows from spec §4 `test_toolkit_stale.py` that remove or write.

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
9. **Close the task** with `parrot sdd task close TASK-5131 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
