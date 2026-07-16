---
type: Wiki Overview
title: 'TASK-1062: Refactor callers to use AgentCrew.from_definition()'
id: doc:sdd-tasks-completed-task-1062-refactor-callers-to-from-definition-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With `AgentCrew.from_definition()` available (TASK-1061), the duplicated
relates_to:
- concept: mod:parrot.bots
  rel: mentions
---

# TASK-1062: Refactor callers to use AgentCrew.from_definition()

**Feature**: FEAT-156 — AgentCrew.from_definition classmethod
**Spec**: `sdd/proposals/agentcrew-from-definition.proposal.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1061
**Assigned-to**: unassigned

---

## Context

With `AgentCrew.from_definition()` available (TASK-1061), the duplicated
`_create_crew_from_definition` methods in `CrewHandler` and `BotManager` should
delegate to it. This eliminates ~95% code duplication and ensures a single
source of truth for crew-from-definition logic.

---

## Scope

- Refactor `CrewHandler._create_crew_from_definition()` to delegate to
  `AgentCrew.from_definition()`, passing `self.bot_manager.get_bot_class` as
  `class_resolver` and `self.bot_manager.get_tool` as `tool_resolver`.
- Refactor `BotManager._create_crew_from_definition()` to delegate to
  `AgentCrew.from_definition()`, passing `self.get_bot_class` as `class_resolver`.
- Remove `_get_agents_by_ids` from both `CrewHandler` and `BotManager` (the logic
  now lives in `AgentCrew._resolve_agents_by_ids`).
- Preserve the WebSearchAgent debug logging in `CrewHandler` (move it to a
  pre-call log statement before `from_definition`).

**NOT in scope**:
- Changing the HTTP API interface or response format.
- Modifying `autonomous/orchestrator.py` callers (they use `BotManager` which
  is being updated).
- Adding new functionality beyond delegation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/crew/handler.py` | MODIFY | Replace `_create_crew_from_definition` and remove `_get_agents_by_ids` |
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Replace `_create_crew_from_definition` and remove `_get_agents_by_ids` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# After TASK-1061:
from parrot.bots.orchestration.crew import AgentCrew  # handler.py:18

# handler.py already imports AgentCrew (line 18)
# manager.py already imports AgentCrew (implicit via self._crews storage)
```

### Existing Signatures to Use
```python
# After TASK-1061 — packages/ai-parrot/src/parrot/bots/orchestration/crew.py
# AgentCrew.from_definition(
#     cls,
#     crew_def: "CrewDefinition",
#     *,
#     class_resolver: Callable[[str], Optional[type]],
#     tool_resolver: Optional[Callable[[str], Optional["AbstractTool"]]] = None,
#     **kwargs,
# ) -> "AgentCrew"

# packages/ai-parrot/src/parrot/handlers/crew/handler.py:76
async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:
    # Lines 76-158: full creation logic to be replaced

# packages/ai-parrot/src/parrot/handlers/crew/handler.py:160
def _get_agents_by_ids(self, crew: AgentCrew, agent_ids: list) -> list:
    # Lines 160-177: helper to be removed

# packages/ai-parrot/src/parrot/manager/manager.py:2050
async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:
    # Lines 2050-2144: full creation logic to be replaced

# packages/ai-parrot/src/parrot/manager/manager.py:2146
def _get_agents_by_ids(self, crew: AgentCrew, agent_ids: List[str]) -> List[Any]:
    # Lines 2146-2167: helper to be removed

# packages/ai-parrot/src/parrot/handlers/crew/handler.py:39
@property
def bot_manager(self):  # returns the bot manager with get_bot_class and get_tool

# packages/ai-parrot/src/parrot/manager/manager.py:172
def get_bot_class(self, bot_name: str) -> Optional[Type]:
```

### Does NOT Exist
- ~~`self.bot_manager.resolve_class`~~ — use `get_bot_class` instead
- ~~`self.bot_manager.resolve_tool`~~ — use `get_tool` instead
- ~~`AgentCrew.from_definition` (before TASK-1061)~~ — depends on prior task

---

## Implementation Notes

### Refactored CrewHandler pattern
```python
async def _create_crew_from_definition(
    self,
    crew_def: CrewDefinition
) -> AgentCrew:
    # Preserve WebSearchAgent debug logging
    for agent_def in crew_def.agents:
        if agent_def.agent_class == "WebSearchAgent":
            self.logger.debug(
                f"Creating WebSearchAgent '{agent_def.name or agent_def.agent_id}' "
                f"with config: contrastive_search={agent_def.config.get('contrastive_search', False)}, "
                f"synthesize={agent_def.config.get('synthesize', False)}, "
                f"temperature={agent_def.config.get('temperature', 'default')}"
            )

    return AgentCrew.from_definition(
        crew_def,
        class_resolver=self.bot_manager.get_bot_class,
        tool_resolver=self.bot_manager.get_tool,
    )
```

### Refactored BotManager pattern
```python
async def _create_crew_from_definition(
    self,
    crew_def: CrewDefinition
) -> AgentCrew:
    return AgentCrew.from_definition(
        crew_def,
        class_resolver=self.get_bot_class,
    )
```

### Key Constraints
- `CrewHandler._create_crew_from_definition` is `async` — keep the signature async
  even though `from_definition` is sync. Callers already await it.
- The `BotManager` version had a stub for shared tool resolution. Since
  `from_definition` accepts `tool_resolver=None` by default, simply omit it.
- Both methods can keep their docstrings (update to say "Delegates to AgentCrew.from_definition").
- Remove `_get_agents_by_ids` from both classes entirely — it is now
  `AgentCrew._resolve_agents_by_ids`.

### References in Codebase
- `handlers/crew/handler.py:76-177` — code being replaced
- `manager/manager.py:2050-2167` — code being replaced

---

## Acceptance Criteria

- [ ] `CrewHandler._create_crew_from_definition` delegates to `AgentCrew.from_definition`
- [ ] `BotManager._create_crew_from_definition` delegates to `AgentCrew.from_definition`
- [ ] `_get_agents_by_ids` removed from both `CrewHandler` and `BotManager`
- [ ] WebSearchAgent debug logging preserved in `CrewHandler`
- [ ] All existing tests pass: `pytest tests/ -x -q`
- [ ] No linting errors on modified files
- [ ] HTTP API behavior unchanged (manual verification: PUT /api/v1/crew still creates crews)

---

## Test Specification

```python
# No new test file needed — existing tests cover the HTTP and manager paths.
# Verify by running:
#   pytest tests/ -x -q
#
# If integration tests exist for crew creation, ensure they still pass.
# The refactored methods produce identical AgentCrew instances.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1061 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AgentCrew.from_definition` exists after TASK-1061
4. **Update status** in `sdd/tasks/index/FEAT-156.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1062-refactor-callers-to-from-definition.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-11
**Notes**: Replaced `CrewHandler._create_crew_from_definition` (lines 76-177 in handler.py)
with a delegating implementation calling `AgentCrew.from_definition()`, passing
`bot_manager.get_bot_class` as `class_resolver` and `bot_manager.get_tool` as
`tool_resolver`. Preserved the WebSearchAgent debug logging as a pre-call loop.
Replaced `BotManager._create_crew_from_definition` (lines 2050-2167 in manager.py)
with a delegating implementation calling `AgentCrew.from_definition()`, passing
`self.get_bot_class` as `class_resolver`. Removed `_get_agents_by_ids` from both
`CrewHandler` and `BotManager` — the logic now lives in
`AgentCrew._resolve_agents_by_ids`. All 20 unit tests pass.

**Deviations from spec**: none
