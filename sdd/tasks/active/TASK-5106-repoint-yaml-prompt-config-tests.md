# TASK-5106: Repoint test_yaml_prompt_config.py at the current prompt-config API

**Feature**: FEAT-791 — BotManager fixes — Jira web-channel OAuth2 registration + BotManager test-API drift
**Spec**: `sdd/specs/manager-manager-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:31f12d3a6967`

---

## Context

Implements spec §3 Module 3 (Lane B, part 1). 16 tests in
`packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` call
`BotManager._build_prompt_builder(...)`, a method that no longer exists
anywhere under `packages/*/src`. Every one of them fails with
`AttributeError: type object 'BotManager' has no attribute '_build_prompt_builder'`.

Because the merge/feature-tier selector treats this module as a direct importer
of `manager.py`, every feature that touches `BotManager` reports these as
"new red" (`new_red=19, baseline_red=0` — FEAT-704 PR #1821, TASK-4480). The
gate shows false failures.

The replacement API is already exercised by the sibling module
`packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py`:
`get_preset(...)` to build the base builder, then the static
`AgentRegistry._apply_prompt_config(bot, PromptConfig(...))` to apply the
remove / add / customize mutations.

---

## Scope

- Replace every `BotManager._build_prompt_builder(cfg)` call in
  `test_yaml_prompt_config.py` with the current API, via one module-local
  helper so the 16 test bodies change only at the construction line.
- Keep every test name, class name and assertion intent exactly as they are.
- Drop the now-unused `from parrot.manager.manager import BotManager` imports.

**NOT in scope**: restoring `BotManager._build_prompt_builder` (removed
deliberately — spec §1 Non-Goals); any change to
`packages/ai-parrot/src/parrot/registry/registry.py` or to the prompt
builder/preset modules; `test_tooling_integration.py` (TASK-5107);
anything in Lane A (TASK-5105).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` | MODIFY | Repoint 16 tests at `get_preset` + `AgentRegistry._apply_prompt_config` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `2ac26be889` (dev, 2026-11-03).

### Verified Imports
```python
from parrot.registry.registry import PromptConfig, AgentRegistry  # verified: used at packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py:9
from parrot.bots.prompts.presets import get_preset                # verified: used at packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py:53
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class PromptConfig(BaseModel):
    preset: str = "default"
    remove: List[str] = Field(default_factory=list)
    add: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    customize: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

class AgentRegistry:
    @staticmethod
    def _apply_prompt_config(bot: AbstractBot, prompt_config: PromptConfig) -> None:
        """Apply remove / add / customize to bot._prompt_builder.

        Reads and mutates ``bot._prompt_builder``.  When that attribute is
        None AND the config has mutations, it builds
        ``get_preset(prompt_config.preset or "default")`` itself and assigns it.
        When it is None and there are NO mutations, it returns without
        building anything — so a preset-only test must set _prompt_builder itself.
        """
```

The existing config dicts in the test file use exactly the four `PromptConfig`
field names (`preset`, `remove`, `add`, `customize`), so `PromptConfig(**cfg)`
accepts each one unchanged.

### Does NOT Exist
- ~~`BotManager._build_prompt_builder`~~ — removed; zero hits in `packages/*/src`
- ~~`AgentRegistry.build_prompt_builder`~~ — not a real method
- ~~`AgentRegistry._apply_prompt_config` as an instance method~~ — it is a `@staticmethod`;
  call it on the class, never on an instance you construct
- ~~`PromptConfig.layers`~~ / ~~`PromptConfig.presets`~~ — not real fields

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry._apply_prompt_config",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#PromptConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Test-only task.** Do not touch `manager.py`, `registry.py` or any `src/` file.
- Keep all 16 test names and their classes (`TestYAMLPresetSelection`,
  `TestYAMLRemoveOperation`, `TestYAMLAddOperation`, `TestYAMLCustomizeOperation`,
  `TestYAMLCombinedOperations`) — the spec's §4 table and AC-6 reference them.
- Do not weaken an assertion to make a test pass. If an assertion genuinely no
  longer holds under the current API, stop and record it in the Completion Note
  rather than editing the expectation.
- The helper must assign `_prompt_builder` from `get_preset` **before** calling
  `_apply_prompt_config` — the preset-only tests (`TestYAMLPresetSelection`)
  have no mutations, so `_apply_prompt_config` would otherwise return early
  leaving the builder `None`.
- Update the module docstring (line 4 mentions `BotManager._build_prompt_builder`).

### References in Codebase
- `packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py` — the sibling
  module already using the current API; green on dev
- `packages/ai-parrot/src/parrot/registry/registry.py` — `_apply_prompt_config` body

---

## Implementation Blueprint

### Steps (in order)
1. Add the module-local `_build(cfg)` helper near the top of the file, after the
   existing `REQUEST_CTX` constant — *why*: it localizes the API change to one
   place so the 16 bodies change only at their construction line, keeping the
   diff reviewable and each test's intent visibly unchanged.
2. Replace each `from parrot.manager.manager import BotManager` +
   `builder = BotManager._build_prompt_builder({...})` pair with
   `builder = _build({...})` — *why*: the import is what makes the selector treat
   this module as a direct importer of `manager.py`, which is the gate-noise
   half of the issue.
3. Update the module docstring to name the current API — *why*: it currently
   advertises a method that no longer exists.
4. Run the Validation Commands; all 16 must pass with 0 failures.

### `packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` (MODIFY — add helper)
```python
# occurrences: 1 (verified: grep -c 'class TestYAMLPresetSelection:' packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py)
# BEFORE — insert above `class TestYAMLPresetSelection:` (verified: packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py:38)
from types import SimpleNamespace

from parrot.bots.prompts.presets import get_preset
from parrot.registry.registry import AgentRegistry, PromptConfig


def _build(cfg: dict):
    """Build a PromptBuilder from a YAML prompt-config dict.

    Replaces the removed ``BotManager._build_prompt_builder``.  The preset is
    materialised here rather than left to ``_apply_prompt_config`` because that
    helper only builds one when the config carries mutations.
    """
    config = PromptConfig(**cfg)
    bot = SimpleNamespace(_prompt_builder=get_preset(config.preset))
    AgentRegistry._apply_prompt_config(bot, config)
    return bot._prompt_builder
```
**Why this shape**: `PromptConfig(**cfg)` accepts the existing dicts verbatim because
they already use its four field names, so no test's config literal has to change.
Pre-assigning `_prompt_builder` is what makes `TestYAMLPresetSelection` (no mutations)
work — `_apply_prompt_config` returns early on a `None` builder with no mutations.
`SimpleNamespace` is enough: `_apply_prompt_config` reads and writes only
`bot._prompt_builder`. Do not change the helper's name or its return value.

### `packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` (MODIFY — call sites)
```python
# occurrences: 1 (verified: grep -c 'builder = BotManager._build_prompt_builder({"preset": "default"})' packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py)
# REPLACE — each of the 16 construction sites, e.g. at test_yaml_prompt_config.py:42-43
# FILL IN: for every test, delete its `from parrot.manager.manager import BotManager`
# line and rewrite `BotManager._build_prompt_builder(<dict>)` as `_build(<dict>)`,
# leaving the dict literal and every assertion byte-identical.
# Two sites bind to a name other than `builder` (test_customize_preserves_priority
# uses `original` and `customized`) — preserve those local names.
# Bounded by: AC-1 (all 16 green) and AC-2 (no assertion weakened).
```
**Why**: this is a mechanical substitution, but it must stay mechanical — the value of
these tests is that their assertions were written against the intended semantics, so
the only thing allowed to change is how the builder is obtained.

### FILL IN checklist
- [ ] 16 construction sites rewritten to `_build(...)`, dict literals untouched; bounded by AC-1
- [ ] every `from parrot.manager.manager import BotManager` line removed; bounded by AC-3
- [ ] module docstring updated to name the current API; bounded by AC-4

---

## Acceptance Criteria

- [ ] AC-1: `pytest packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py -q` → 0 failed,
      16 previously-failing tests now pass.
- [ ] AC-2: No assertion was weakened, renamed or deleted; no test name changed.
- [ ] AC-3: No reference to `BotManager` remains in the file.
- [ ] AC-4: The module docstring names the current API.
- [ ] AC-5: `packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py` stays green.
- [ ] AC-6: No file under any `src/` tree was modified.
- [ ] No linting errors: `ruff check` on the changed file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py -q`
- `pytest packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py -q`

---

## Test Specification

No new tests. The 16 existing tests are the specification; they must pass unchanged
in name and assertion. Run with an absolute `PYTHONPATH` to the worktree's
`packages/ai-parrot/src`, since the shared venv is editable-installed against the
main checkout:

```bash
PYTHONPATH=/abs/path/to/worktree/packages/ai-parrot/src \
  pytest packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py -q
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug manager-manager-fixes --feature-id FEAT-791`)
2. **Read the spec** at `sdd/specs/manager-manager-fixes.spec.md` (§3 M3)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — confirm `_apply_prompt_config` is still a
   `@staticmethod` with the documented early-return before writing the helper
5. **Update status** in `sdd/tasks/index/manager-manager-fixes.json` → `"in-progress"`
6. **Implement** from the Implementation Blueprint
7. **Verify** — run the Validation Commands; 0 failed is the bar
8. **Commit the code** — stage only this task's one file
9. **Close** with `parrot sdd task close TASK-5106 manager-manager-fixes verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
