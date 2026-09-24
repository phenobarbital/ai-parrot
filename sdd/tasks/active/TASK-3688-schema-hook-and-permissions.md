# TASK-3688: Post-merge DDL ingest inside the git-hook guard + `wiki_schema_*` MCP permissions

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (hook half). The managed hook block is shared by `post-commit` and `post-merge` and guarded by `if [ ! -f .git ]` (assets.py:166-190). Adding `schema ingest-ddl --changed --quiet` INSIDE the same guard keeps the FEAT-566 worktree invariant. The Claude Code permission allowlist (assets.py:55-62) gains the four `mcp__wikitoolkit__wiki_schema_*` names.

---

## Scope

- Modify `git_hook_block` to emit the ingest line right after the `upsert --changed --quiet` line, inside the guard.
- Append four permission strings after `"mcp__wikitoolkit__wiki_blast_radius",`.
- Write `test_schema_hook_assets.py` (hook text + permissions); existing `tests/knowledge/wiki/test_installer_worktree_guard.py` must stay green.

**NOT in scope**: The CLI verb itself (TASK-3687) — the hook line is `|| true`, so it is harmless before TASK-3687 lands.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | hook line + 4 permissions |
| `packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code.assets import git_hook_block   # verified: packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:166
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
def git_hook_block(root: Path) -> str:                                  # :166-190
    wt_bin = resolve_wikitoolkit_bin(root)
    return (f"{GIT_HOOK_BEGIN}\n" ... f"if [ ! -f .git ]; then\n"            # :186  ← anchor
            f"    {wt_bin} upsert --changed --quiet >/dev/null 2>&1 || true\n"   # :187  ← insert the schema line right after this one
            f"fi\n" f"{GIT_HOOK_END}\n")
# permission allowlist entries :60-62: "mcp__wikitoolkit__wiki_symbol_lookup", "mcp__wikitoolkit__wiki_code_outline", "mcp__wikitoolkit__wiki_blast_radius",  ← append after :62
# tests/knowledge/wiki/test_installer_worktree_guard.py — TestLinkedWorktreeHookSkipsUpsert (must stay green)
```

### Does NOT Exist
- ~~a separate schema hook file~~ — one managed block serves both hooks; add a line, not a hook
- ~~`wikitoolkit schema` at install time~~ — the hook line is `|| true` and quiet; it is inert until TASK-3687 ships

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#git_hook_block"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
assets.py:186-188 — the guarded upsert line.

### Key Constraints
- The new line MUST be inside the `if [ ! -f .git ]` guard (AC10).
- Redirect output and `|| true` exactly like the upsert line.
- Permission strings match the tool names fixed by spec M5: lookup, search, neighbors, sources.

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:55-62, :166-190
- tests/knowledge/wiki/test_installer_worktree_guard.py

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Insert the ingest line after :187 — why: same guard, same failure tolerance.
2. Append the four permissions after :62 — why: Claude Code must be allowed to call the new tools without prompts.
3. Write the test; run the existing worktree-guard tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        f"if [ ! -f .git ]; then\n"' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py) → assets.py:186
# AFTER — insert below the NEXT line (:187, the `upsert --changed --quiet` f-string), still inside the `if`:
        f"    {wt_bin} schema ingest-ddl --changed --quiet >/dev/null 2>&1 || true\n"

# occurrences: 1 (verified: grep -c '    "mcp__wikitoolkit__wiki_blast_radius",' …/assets.py) → assets.py:62
# AFTER — insert below:
    # FEAT-600: schema-plane MCP tools (read-only).
    "mcp__wikitoolkit__wiki_schema_lookup",
    "mcp__wikitoolkit__wiki_schema_search",
    "mcp__wikitoolkit__wiki_schema_neighbors",
    "mcp__wikitoolkit__wiki_schema_sources",
```
**Why**: One line inside the existing guard is the whole hook change the spec allows (M4); the permission names are the tool names fixed in spec M5.

### FILL IN checklist
- [ ] test asserting the ingest line appears AFTER `if [ ! -f .git ]; then` and BEFORE `fi`
- [ ] test asserting the four permission names are present

---

## Acceptance Criteria

- [ ] `git_hook_block(root)` contains `schema ingest-ddl --changed --quiet` between the `if` and `fi` lines (AC10)
- [ ] the four permission names are in the allowlist
- [ ] `pytest tests/knowledge/wiki/test_installer_worktree_guard.py -q` green
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py -q`
- `pytest tests/knowledge/wiki/test_installer_worktree_guard.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py
from pathlib import Path
from parrot.knowledge.wiki.claude_code import assets

def test_ingest_line_inside_guard(tmp_path: Path):
    block = assets.git_hook_block(tmp_path)
    i, j, k = block.index("if [ ! -f .git ]; then"), block.index("schema ingest-ddl --changed --quiet"), block.index("\nfi\n")
    assert i < j < k

def test_permissions_present():
    text = Path(assets.__file__).read_text()
    for name in ("lookup", "search", "neighbors", "sources"):
        assert f"mcp__wikitoolkit__wiki_schema_{name}" in text
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `none` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
