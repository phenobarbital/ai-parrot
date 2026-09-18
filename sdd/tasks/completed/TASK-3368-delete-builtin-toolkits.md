# TASK-3368: Delete `BUILTIN_TOOLKITS` — toolkit resolution becomes file-only

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `scraping`, `browsing` and `memory` are hardcoded in
`BUILTIN_TOOLKITS` (`toolkit_config.py:89`) and resolve implicitly whether or not
the operator asked for them. The owner's decision is that **nothing except
wikitoolkit is implicit** — every local MCP server becomes opt-in.

This is the foundation task: every later task in FEAT-570 assumes
`load_toolkits_config` returns only what the file declares. It also removes the
workaround block in `toolkit_seed.py` that exists *solely* to filter builtins
back out of that result, so the deletion makes two modules simpler, not more
complex.

Deleting the constant breaks `toolkit_seed.py`'s module-level import and three
test modules that assert implicit resolution. All of that is in scope here so the
tree is green at this commit.

---

## Scope

- Delete the `BUILTIN_TOOLKITS` constant from `parrot/mcp/toolkit_config.py`.
- Change `load_toolkits_config` to start from an empty mapping instead of seeding
  from the builtins, and rewrite its docstring accordingly.
- Remove `toolkit_seed.py`'s now-dangling `BUILTIN_TOOLKITS` import and the
  builtin-filtering block inside `seed_toolkit_sections`.
- Update the three test modules that assert implicit builtin resolution.

**NOT in scope**: the replacement templates (TASK-3370), the new seed helpers
(TASK-3369), the `parrot mcp-local` unknown-name error text (TASK-3380), docs and
examples (TASK-3380).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` | MODIFY | Delete `BUILTIN_TOOLKITS`; `load_toolkits_config` starts empty |
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | Drop the import and the builtin-filtering block |
| `tests/mcp/test_toolkit_config.py` | MODIFY | Replace builtin-resolution assertions |
| `tests/mcp/test_local_cli.py` | MODIFY | `--list` no longer shows builtins |
| `tests/mcp/test_mcp_local_e2e.py` | MODIFY | Declare sections explicitly before spawning |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import MCPToolkitsConfig, ToolkitSection, load_toolkits_config  # verified: toolkit_config.py:19,79,105
from parrot.mcp.toolkit_seed import seed_toolkit_sections, SeedResult  # verified: toolkit_seed.py:154,35
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
class ToolkitSection(BaseModel):                     # line 19
    class_path: str = Field(..., alias="class")      # line 49
    enabled: bool = True                             # line 50
class MCPToolkitsConfig(BaseModel):                  # line 79
    toolkits: dict[str, ToolkitSection]              # line 87
BUILTIN_TOOLKITS: dict[str, ToolkitSection] = {...}  # line 89  <- DELETE
#   "scraping" -> parrot_tools.scraping.toolkit.WebScrapingToolkit        # line 91
#   "browsing" -> parrot_tools.browsing.toolkit.WebBrowsingToolkit        # line 95
#   "memory"   -> parrot.tools.working_memory.tool.WorkingMemoryToolkit   # line 99
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig:  # line 105
    # line 143: merged = {name: section.model_copy() for name, section in BUILTIN_TOOLKITS.items()}  <- the deletion point
    # line ~150: `if not config_path.exists(): if explicit: raise ValueError(...); return MCPToolkitsConfig(toolkits=merged)`

# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
from parrot.mcp.toolkit_config import BUILTIN_TOOLKITS   # line 13  <- DELETE
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult:  # line 154
    # lines ~193-205: the `for builtin_name in BUILTIN_TOOLKITS:` block that re-reads
    # the raw file to discard builtin names from `existing_sections`  <- DELETE WHOLESALE
```

### Does NOT Exist
- ~~`toolkit_config.DEFAULT_TOOLKITS`~~ / ~~`FALLBACK_TOOLKITS`~~ — the constant is
  named `BUILTIN_TOOLKITS` and nothing replaces it.
- ~~a `builtins=` parameter on `load_toolkits_config`~~ — the signature is
  `(root, config_path=None)` and does not change.
- ~~`parrot/mcp/_toolkit_templates/scraping.yaml`~~ — does NOT exist yet; it is
  created by TASK-3370. Do not reference it from this task.
- ~~`MCPToolkitsConfig.builtin_names`~~ — not an attribute.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_seed.py", "action": "MODIFY"},
    {"path": "tests/mcp/test_toolkit_config.py", "action": "MODIFY"},
    {"path": "tests/mcp/test_local_cli.py", "action": "MODIFY"},
    {"path": "tests/mcp/test_mcp_local_e2e.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#BUILTIN_TOOLKITS",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#MCPToolkitsConfig",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#ToolkitSection",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The `config_path` semantics are **unchanged**: an explicitly named missing file
  still raises `ValueError`; only the *default* path's absence changes meaning
  (was "three builtins", now "empty config").
- Do not delete `ToolkitSection` or `MCPToolkitsConfig` — only the constant.
- Keep `_DRIFT_IGNORED_KEYS` (`toolkit_seed.py:23`) — unrelated to builtins.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` — the module being cut
- `packages/ai-parrot/src/parrot/mcp/local_cli.py:35` — `_print_toolkit_list`,
  which now prints nothing for a bare repo (its docstring/error text is
  TASK-3380's job, not this task's)

---

## Implementation Blueprint

### Steps (in order)
1. Delete the `BUILTIN_TOOLKITS` block in `toolkit_config.py` — *why*: it is the
   single source of implicit resolution the feature removes.
2. Change the `merged` seed to an empty dict and rewrite the docstring — *why*:
   `load_toolkits_config` must now describe file-only behavior or the next reader
   will re-introduce the builtins.
3. Remove `toolkit_seed.py`'s import and the builtin-filtering block — *why*: the
   block exists only to undo the builtins, so it is dead code once they are gone;
   leaving it would keep re-reading the raw file for no reason.
4. Update the three test modules — *why*: they assert the old contract and would
   fail this commit.

### `packages/ai-parrot/src/parrot/mcp/toolkit_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'BUILTIN_TOOLKITS: dict[str, ToolkitSection] = {' packages/ai-parrot/src/parrot/mcp/toolkit_config.py)
# DELETE the whole statement beginning at `BUILTIN_TOOLKITS: dict[str, ToolkitSection] = {`
# (verified: toolkit_config.py:89) through its closing `}` (verified: toolkit_config.py:102).

# occurrences: 1 (verified: grep -cF 'merged: dict[str, ToolkitSection] = {name: section.model_copy() for name, section in BUILTIN_TOOLKITS.items()}' packages/ai-parrot/src/parrot/mcp/toolkit_config.py)
# REPLACE that line (verified: toolkit_config.py:143) with:
    merged: dict[str, ToolkitSection] = {}
```
**Why this shape**: the merge loop below line 143 already writes every file
section into `merged`, so seeding it empty is the whole behavioral change — no
control flow moves. The `if not config_path.exists()` branch keeps returning
`MCPToolkitsConfig(toolkits=merged)`, which is now correctly an empty config, and
its `explicit` → `ValueError` arm is untouched (spec §3 M3). Do not rename
`merged` or change the function signature; TASK-3374/3375 call it verbatim.

**Docstring**: rewrite `load_toolkits_config`'s docstring so the Returns/Raises
text says sections come only from the file. Keep the `Raises: ValueError` clause
for the explicit-path case.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from parrot.mcp.toolkit_config import BUILTIN_TOOLKITS' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# DELETE the import line (verified: toolkit_seed.py:13).

# occurrences: 1 (verified: grep -cF 'for builtin_name in BUILTIN_TOOLKITS:' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# DELETE the `for builtin_name in BUILTIN_TOOLKITS:` loop and its body
# (verified: toolkit_seed.py:~198), leaving:
        try:
            config = load_toolkits_config(root_path)
            existing_sections = set(config.toolkits.keys())
        except ValueError:
            pass
```
**Why**: `load_toolkits_config` no longer injects names that are absent from the
file, so `existing_sections` is already exactly the file's sections — the loop
that re-read the raw text to subtract builtins is now a no-op with I/O cost.
Leave the surrounding `try/except ValueError: pass` alone; making that swallow
into a hard failure is TASK-3369's job (spec §7, design research S4), and doing
it here would collide with that task's edit.

### `tests/mcp/test_toolkit_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_no_file_returns_builtins(tmp_path):' tests/mcp/test_toolkit_config.py)
# REPLACE `test_no_file_returns_builtins` (verified: tests/mcp/test_toolkit_config.py:17) with:
def test_no_file_returns_empty(tmp_path):
    """load_toolkits_config with no file resolves nothing (FEAT-570)."""
    cfg = load_toolkits_config(tmp_path)
    assert cfg.toolkits == {}


def test_explicit_missing_config_still_raises(tmp_path):
    """An explicitly named missing file is operator error, unchanged by FEAT-570."""
    with pytest.raises(ValueError, match="not found"):
        load_toolkits_config(tmp_path, config_path=tmp_path / "nope.yaml")
```
**Why**: these two pin both halves of the changed contract — the default path now
yields an empty config, while the explicit path's `ValueError` is deliberately
preserved. `test_file_overrides_builtin` (line 24) and the "appended alongside
builtins" test (line 42) must be rewritten to declare their sections in the YAML
fixture rather than relying on a builtin being present.
# FILL IN: rewrite the remaining builtin-dependent tests in this module — every
# section a test needs must now appear in its own fixture YAML; bounded by AC4.

### `tests/mcp/test_local_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_list_shows_builtins(monkeypatch, tmp_path):' tests/mcp/test_local_cli.py)
# REPLACE `test_list_shows_builtins` (verified: tests/mcp/test_local_cli.py:15) so that
# `--list` on a bare repo lists nothing, and a repo WITH a declared section lists it.
# FILL IN: the two replacement cases — assert the bare-repo listing contains none of
# "scraping"/"browsing"/"memory"; bounded by AC1 and AC4.
```
**Why**: `--list` is the user-visible proof that implicit resolution is gone. The
other cases in this module that spawn `mcp-local memory` (lines 106, 119, 164)
must first write a `memory:` section into the fixture config.

### `tests/mcp/test_mcp_local_e2e.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_mcp_local_list_shows_builtin(tmp_path, name):' tests/mcp/test_mcp_local_e2e.py)
# The e2e spawns (lines 119, 167, 185, 281) and the config assertions (lines 255-257)
# assume implicit resolution.
# FILL IN: add a fixture that writes an explicit `memory:` section (class
# parrot.tools.working_memory.tool.WorkingMemoryToolkit) into
# `<tmp_path>/.parrot/mcp-toolkits.yaml` before each spawn; bounded by AC4.
```
**Why**: the e2e must keep proving a real JSON-RPC handshake; only the way the
toolkit becomes resolvable changes.

### FILL IN checklist
- [ ] `test_toolkit_config.py` — rewrite the remaining builtin-dependent cases to declare sections in fixtures; bounded by AC4
- [ ] `test_local_cli.py::test_list_shows_builtins` → bare repo lists nothing; bounded by AC1, AC4
- [ ] `test_local_cli.py` — add an explicit `memory:` section to fixtures for the spawn cases; bounded by AC4
- [ ] `test_mcp_local_e2e.py` — explicit-section fixture for every spawn; bounded by AC4

---

## Acceptance Criteria

- [ ] `grep -rn BUILTIN_TOOLKITS packages/ src/ tests/` returns nothing
- [ ] `load_toolkits_config(tmp_path)` with no file returns `toolkits == {}`
- [ ] `load_toolkits_config(tmp_path, config_path=<missing>)` still raises `ValueError`
- [ ] `seed_toolkit_sections` behavior is otherwise unchanged (its own tests pass)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/`
- [ ] Imports work: `from parrot.mcp.toolkit_config import load_toolkits_config`

---

## Validation Commands

- `pytest tests/mcp/test_toolkit_config.py -q`
- `pytest tests/mcp/test_local_cli.py -q`
- `pytest tests/mcp/test_toolkit_seed.py -q`
- `pytest tests/mcp/test_mcp_local_e2e.py -q`

---

## Test Specification

```python
# tests/mcp/test_toolkit_config.py
import pytest
from parrot.mcp.toolkit_config import load_toolkits_config


def test_no_file_returns_empty(tmp_path):
    assert load_toolkits_config(tmp_path).toolkits == {}


def test_explicit_missing_config_still_raises(tmp_path):
    with pytest.raises(ValueError):
        load_toolkits_config(tmp_path, config_path=tmp_path / "nope.yaml")


def test_declared_section_resolves(tmp_path):
    """A section present in the file is the ONLY way a toolkit resolves now."""
    # FILL IN: write a minimal mcp-toolkits.yaml and assert the section round-trips
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 3, §7 Known Risks).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `BUILTIN_TOOLKITS` is still at
   `toolkit_config.py:89` and the seed line at `:143` before editing.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3368-delete-builtin-toolkits.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (native, sonnet)
**Date**: 2026-09-18
**Notes**: Deleted `BUILTIN_TOOLKITS` from `toolkit_config.py`; `load_toolkits_config`
now starts from an empty `merged` dict. Removed the dangling `BUILTIN_TOOLKITS`
import and builtin-filtering block in `toolkit_seed.seed_toolkit_sections`.
Updated three test modules (`test_toolkit_config.py`, `test_local_cli.py`,
`test_mcp_local_e2e.py`) that asserted implicit builtin resolution, replacing
builtin-reliant assertions with explicit-fixture equivalents per the task
blueprint. `grep -rn BUILTIN_TOOLKITS packages/ tests/` returns nothing (AC4).
Validation: `pytest tests/mcp/ -q` → 215 passed; `ruff check` clean on both
touched source files. Merge-tier check run against the full sibling task list
shows only "file not found" for test files owned by not-yet-implemented
sibling tasks (TASK-3372, TASK-3376) — no real regressions.
Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
