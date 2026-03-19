# TASK-024: Package Init & Integration

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-023
**Assigned-to**: claude-session

---

## Context

This task implements Module 9 from the spec. It sets up clean public exports for the `crew` subpackage and integrates the `TelegramCrewTransport` into the existing Telegram integration module.

Implements spec Section 3, Module 9.

---

## Scope

- Populate `parrot/integrations/telegram/crew/__init__.py` with public exports
- Update `parrot/integrations/telegram/__init__.py` to expose the crew subpackage
- Ensure `from parrot.integrations.telegram.crew import TelegramCrewTransport` works
- Ensure all public types are exported: `TelegramCrewTransport`, `TelegramCrewConfig`, `CrewAgentEntry`, `AgentCard`, `AgentSkill`, `CrewRegistry`, `CoordinatorBot`

**NOT in scope**: Application startup hooks (deferred to follow-up), configuration file examples.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/__init__.py` | MODIFY | Add public exports |
| `parrot/integrations/telegram/__init__.py` | MODIFY | Add crew subpackage reference |
| `tests/test_telegram_crew/test_imports.py` | CREATE | Verify all imports work |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/integrations/telegram/crew/__init__.py
from .config import TelegramCrewConfig, CrewAgentEntry
from .agent_card import AgentCard, AgentSkill
from .registry import CrewRegistry
from .coordinator import CoordinatorBot
from .crew_wrapper import CrewAgentWrapper
from .transport import TelegramCrewTransport
from .payload import DataPayload
from .mention import mention_from_username, mention_from_card, format_reply

__all__ = [
    "TelegramCrewTransport",
    "TelegramCrewConfig",
    "CrewAgentEntry",
    "AgentCard",
    "AgentSkill",
    "CrewRegistry",
    "CoordinatorBot",
    "CrewAgentWrapper",
    "DataPayload",
    "mention_from_username",
    "mention_from_card",
    "format_reply",
]
```

### Key Constraints
- Do NOT modify existing exports in `parrot/integrations/telegram/__init__.py` — only add
- No breaking changes to existing `TelegramBotManager` or `TelegramAgentWrapper` imports

### References in Codebase
- `parrot/integrations/telegram/__init__.py` — existing exports to preserve

---

## Acceptance Criteria

- [ ] `from parrot.integrations.telegram.crew import TelegramCrewTransport` works
- [ ] `from parrot.integrations.telegram.crew import AgentCard, AgentSkill` works
- [ ] `from parrot.integrations.telegram.crew import CrewRegistry` works
- [ ] Existing `parrot.integrations.telegram` imports still work (no breakage)
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_imports.py -v`

---

## Test Specification

```python
# tests/test_telegram_crew/test_imports.py
import pytest


class TestCrewImports:
    def test_import_transport(self):
        from parrot.integrations.telegram.crew import TelegramCrewTransport
        assert TelegramCrewTransport is not None

    def test_import_config(self):
        from parrot.integrations.telegram.crew import TelegramCrewConfig, CrewAgentEntry
        assert TelegramCrewConfig is not None
        assert CrewAgentEntry is not None

    def test_import_agent_card(self):
        from parrot.integrations.telegram.crew import AgentCard, AgentSkill
        assert AgentCard is not None

    def test_import_registry(self):
        from parrot.integrations.telegram.crew import CrewRegistry
        assert CrewRegistry is not None

    def test_import_coordinator(self):
        from parrot.integrations.telegram.crew import CoordinatorBot
        assert CoordinatorBot is not None

    def test_existing_telegram_imports_unbroken(self):
        # Verify existing imports still work
        from parrot.integrations.telegram import TelegramBotManager
        assert TelegramBotManager is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-023 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-024-package-init.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Populated `crew/__init__.py` with all public exports (12 symbols in `__all__`). Created `tests/test_telegram_crew/test_imports.py` with 13 tests verifying all crew imports and existing telegram imports are unbroken. Did NOT modify `parrot/integrations/telegram/__init__.py` since the crew subpackage is accessible via `parrot.integrations.telegram.crew` without needing re-exports at the parent level. Full crew test suite: 146 tests pass.

**Deviations from spec**: Did not add crew re-exports to `parrot/integrations/telegram/__init__.py` — the crew subpackage is a separate namespace (`from parrot.integrations.telegram.crew import ...`) and adding imports at the parent level would risk circular imports and pollute the existing namespace.
