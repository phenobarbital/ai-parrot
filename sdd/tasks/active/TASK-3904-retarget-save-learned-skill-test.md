# TASK-3904: Retarget `test_save_learned_skill_tool.py` to `SkillFileToolkit.save_learned_skill`

**Feature**: FEAT-617 — Unpoison `packages/ai-parrot/tests` collection (merge-gate unblock)
**Spec**: `sdd/specs/manager-test-bot-cleanup-lifecycle-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

One of the 4 **genuinely stale** collection errors behind `issue:c3c59277ef77`
(the other 14 are conftest stub artifacts owned by TASK-3903).

`packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py:4` imports
`SaveLearnedSkillTool` from `parrot.memory.skills.tools`. That class is **genuinely
gone** — verified absent from both the deprecated shim (`parrot.memory.skills.tools`)
and the current module (`parrot.skills.tools`). FEAT-207 folded it into the
`SkillFileToolkit` as the `save_learned_skill` method
(`packages/ai-parrot/src/parrot/skills/tools.py:543`).

The test file still carries **6 real, valuable assertions** (file write, hot-add to
registry, name collision, trigger collision, frontmatter content, result metadata).
The API maps almost 1:1, so this is a retarget, not a rewrite of intent.

`discovered_from: issue:c3c59277ef77`

## Scope

Rewrite the test module against `SkillFileToolkit.save_learned_skill`, preserving
every existing assertion. Also migrate the two sibling imports off the deprecated
`parrot.memory.skills.*` shim onto `parrot.skills.*`, since the module is being
touched anyway and the shim emits a `DeprecationWarning` on import.

**NOT in scope**:
- Adding new coverage beyond the 6 existing test methods (spec §1 Non-Goals).
- Any change to `packages/ai-parrot/src/parrot/skills/tools.py` — the product code is
  correct; the test is what drifted (spec AC9).
- Removing the `parrot.memory.skills.*` deprecation shim itself.
- The other 3 stale files (TASK-3905) or the conftest fix (TASK-3903).

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` | MODIFY | retarget to the toolkit API |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.tools import SkillFileToolkit          # verified: packages/ai-parrot/src/parrot/skills/tools.py:376
from parrot.skills.file_registry import SkillFileRegistry # verified: packages/ai-parrot/src/parrot/skills/file_registry.py
from parrot.skills.models import SkillDefinition          # verified: packages/ai-parrot/src/parrot/skills/models.py
from parrot.tools.abstract import ToolResult              # verified: packages/ai-parrot/src/parrot/skills/tools.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/tools.py
class SkillFileToolkit(AbstractToolkit):                       # line 376
    def __init__(                                              # line 398
        self,
        file_registry: "SkillFileRegistry",
        learned_dir: Optional[Path] = None,
        max_asset_bytes: int = 64 * 1024,
        **kwargs,
    ) -> None:
        ...
        if learned_dir is None:                                # line 410
            self.exclude_tools = ("save_learned_skill",)       # line 411

    async def save_learned_skill(                              # line 543
        self,
        name: str,
        description: str,
        content: str,
        triggers: Optional[List[str]] = None,
        category: str = "general",
    ) -> ToolResult:
        ...
        # returns ToolResult(success=False, status="error", result=None,
        #   error=f"Skill name '{name}' already exists — collision rejected")   # line ~570
```
The call signature is **identical** to the old `SaveLearnedSkillTool._execute()`
(`name`, `description`, `content`, `triggers`, `category`), so every existing call
site changes only its receiver.

### Does NOT Exist
- ~~`parrot.memory.skills.tools.SaveLearnedSkillTool`~~ — module exists, class does not
- ~~`parrot.skills.tools.SaveLearnedSkillTool`~~ — folded into `SkillFileToolkit` by FEAT-207
- ~~`SkillFileToolkit._execute(...)`~~ — `save_learned_skill` is called directly, it is not an `AbstractTool`
- ~~`SkillFileToolkit(file_registry=..., learned_dir=...)` returning a tool~~ — it returns a **toolkit**; the method is called on it

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/tools.py#SkillFileToolkit.save_learned_skill",
    "sym:packages/ai-parrot/src/parrot/skills/tools.py#SkillFileToolkit.__init__"
  ]
}
```

## Implementation Notes

### Pattern to Follow
Keep the existing fixture/class layout (`skills_dir`, `registry`, a
`TestSaveLearnedSkillTool`-style class). Rename the `tool` fixture to `toolkit` and
return a `SkillFileToolkit`; every `await tool._execute(...)` becomes
`await toolkit.save_learned_skill(...)` with the same keyword arguments.

### Key Constraints
- **All 6 existing assertions must survive**: `test_writes_md_file`,
  `test_hot_adds_to_registry`, `test_name_collision`, `test_trigger_collision`,
  `test_file_content_valid`, `test_result_metadata`.
- `learned_dir` must stay non-`None` — passing `None` sets
  `exclude_tools = ("save_learned_skill",)` (`tools.py:411`) and the method would not
  be exposed.
- No `src/` changes (spec AC9).

### References in Codebase
- `packages/ai-parrot/src/parrot/skills/tools.py:543-600` — the method under test
- `.agent/CONTEXT.md` § Skills — FEAT-207's two-toolkit design

## Implementation Blueprint

### Steps (in order)
1. Replace the 3 `parrot.memory.skills.*` imports with their `parrot.skills.*`
   equivalents — because the shim emits a `DeprecationWarning` and the class the test
   wants only exists on the new path.
2. Rename the `tool` fixture to `toolkit`, constructing a `SkillFileToolkit` with the
   same `file_registry` / `learned_dir` keywords.
3. Replace all 6 `await tool._execute(` call sites with
   `await toolkit.save_learned_skill(` — keywords are unchanged.
4. Update the module docstring and the test class name to say `SkillFileToolkit`.
5. Run the file; confirm 6 passed.

### `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` (MODIFY — header)
```python
# occurrences: 1 (verified: grep -c 'from parrot.memory.skills.tools import SaveLearnedSkillTool' packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py)
# REPLACE lines 1-6 (verified: packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py:1-6)
"""Unit tests for SkillFileToolkit.save_learned_skill (FEAT-207 successor to the
removed SaveLearnedSkillTool — retargeted by FEAT-617 / issue:c3c59277ef77)."""
import pytest
from pathlib import Path
from parrot.skills.tools import SkillFileToolkit
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition
```
**Why**: `SaveLearnedSkillTool` no longer exists on any path, so the import is the
collection error itself. The sibling imports move off the deprecated
`parrot.memory.skills.*` shim at the same time to keep the module warning-free.

### `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` (MODIFY — fixture)
```python
# occurrences: 1 (verified: grep -c 'def tool(registry, skills_dir):' packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py)
# REPLACE the `tool` fixture (verified: packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py:24-29)
@pytest.fixture
def toolkit(registry, skills_dir):
    """SkillFileToolkit with a writable learned_dir.

    learned_dir MUST be non-None: SkillFileToolkit.__init__ sets
    exclude_tools = ("save_learned_skill",) when it is None (tools.py:410-411).
    """
    return SkillFileToolkit(
        file_registry=registry,
        learned_dir=skills_dir / "learned",
    )
```
**Why**: the toolkit replaces the removed single-purpose tool class; the constructor
keywords are unchanged, so only the receiver type differs.

### `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` (MODIFY — 6 call sites)
```python
# occurrences: 6 (verified: grep -c 'await tool._execute(' packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py)
# Mechanical substitution across the test class:
#   BEFORE: result = await tool._execute(name="extraer_datos", ...)
#   AFTER:  result = await toolkit.save_learned_skill(name="extraer_datos", ...)
# Keyword arguments are IDENTICAL — do not change them.
# FILL IN: update each test method's `tool` parameter to `toolkit` to match the
# renamed fixture — bounded by AC-1 (all 6 tests must pass).
```
**Why**: 6 occurrences, so no single anchor is unique — apply as a whole-file literal
substitution of `await tool._execute(` → `await toolkit.save_learned_skill(`, then fix
the fixture parameter name in each signature. The assertions themselves are untouched
because `save_learned_skill` returns the same `ToolResult` shape.

### FILL IN checklist
- [ ] Each test method's `tool` parameter renamed to `toolkit`
- [ ] Test class renamed to reference `SkillFileToolkit`
- [ ] Confirm `grep -c 'tool._execute' <file>` → 0

## Acceptance Criteria

- [ ] **AC-1** All **6** test methods pass (none deleted, none weakened)
- [ ] **AC-2** `packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` collects with **0 errors** in isolation
- [ ] **AC-3** No import from `parrot.memory.skills.*` remains in the file. Verify with
  `grep -c 'parrot.memory.skills' packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py` → `0`,
  and confirm the module emits no `DeprecationWarning` (run once with `-W error::DeprecationWarning` by hand)
- [ ] **AC-4** `ruff check` clean on the file
- [ ] **AC-5** No file under `src/` is modified (spec AC9)

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py -q`
- `pytest packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py -v`

## Test Specification

The 6 preserved methods, with their original intent:

| Test | Asserts |
|---|---|
| `test_writes_md_file` | `result.success is True` and `learned/extraer_datos.md` exists |
| `test_hot_adds_to_registry` | `registry.get("/nuevo")` is not `None` after the call |
| `test_name_collision` | duplicate `name` → `success is False`, error mentions exists/collision |
| `test_trigger_collision` | duplicate trigger → `success is False`, error mentions collision/exists |
| `test_file_content_valid` | frontmatter carries `name:`, `description:`, the trigger, `source: learned`, and the body |
| `test_result_metadata` | `result.metadata["name"]` and `result.metadata["triggers"]` populated |

## Agent Instructions

1. Test-only change. Do not touch `src/` — the product API is correct.
2. Do **not** weaken an assertion to make it pass. If `save_learned_skill` genuinely
   behaves differently from the removed tool, record the difference in the Completion
   Note and flag it rather than editing the assertion.
3. Run with `PYTHONPATH=packages/ai-parrot/src`.
4. This task is independent of TASK-3903 — its error is a real missing symbol, not
   stub poisoning, so it can be verified before or after the conftest fix lands.

## Completion Note

<!-- filled in on completion -->
**Completed by**:
**Date**:
