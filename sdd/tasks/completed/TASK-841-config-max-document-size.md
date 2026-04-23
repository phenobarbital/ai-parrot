# TASK-841: Add max_document_size_mb config to TelegramAgentConfig

**Feature**: FEAT-120 — Telegram Wrapper Rich Message Integration
**Spec**: `sdd/specs/telegram-wrapper-audio-files-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 5. The document handler (TASK-845) needs a configurable file-size limit so
operators can control the maximum document size their bot will accept. This config field
must exist before the document handler can reference it.

---

## Scope

- Add `max_document_size_mb: int = 20` field to `TelegramAgentConfig` dataclass
- Add `enable_reply_context: bool = True` field to `TelegramAgentConfig` dataclass
  (referenced in spec Open Question #4 — needed by TASK-844)
- Write unit tests verifying default values and custom overrides

**NOT in scope**: Document handler logic (TASK-845), wrapper method changes

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/models.py` | MODIFY | Add two config fields |
| `tests/unit/test_telegram_config_feat120.py` | CREATE | Unit tests for new fields |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py
from dataclasses import dataclass, field  # used by TelegramAgentConfig
from typing import Optional, List, Dict   # used throughout
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/models.py:39
@dataclass
class TelegramAgentConfig:
    name: str                                          # line 60
    chatbot_id: str                                    # line 61
    bot_token: Optional[str] = None                    # line 62
    # ... (many fields) ...
    singleton_agent: bool = True                       # line 110 — LAST field before __post_init__

    def __post_init__(self):                           # line 112
        ...
```

### Does NOT Exist
- ~~`TelegramAgentConfig.max_document_size_mb`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentConfig.enable_reply_context`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentConfig.max_file_size`~~ — no such field; the correct name is `max_document_size_mb`

---

## Implementation Notes

### Pattern to Follow
Add new fields in the same style as existing Optional/bool fields in the dataclass,
placed after `singleton_agent` and before `__post_init__`:

```python
# After singleton_agent: bool = True (line 110)
# Document handling settings
max_document_size_mb: int = 20
# Reply context enrichment
enable_reply_context: bool = True
```

### Key Constraints
- Do NOT modify `__post_init__` unless the new fields need environment-variable fallbacks
- `max_document_size_mb` is an `int`, not `Optional[int]` — always has a default
- `enable_reply_context` is a `bool` — simple toggle, no env-var resolution needed

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/models.py:39-110` — existing config fields pattern

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig().max_document_size_mb` defaults to `20`
- [ ] `TelegramAgentConfig().enable_reply_context` defaults to `True`
- [ ] Both fields accept custom values at construction
- [ ] Existing tests still pass (no breaking changes to config)
- [ ] Unit tests pass: `pytest tests/unit/test_telegram_config_feat120.py -v`

---

## Test Specification

```python
# tests/unit/test_telegram_config_feat120.py
import pytest
from parrot.integrations.telegram.models import TelegramAgentConfig


class TestTelegramConfigFeat120:
    def test_max_document_size_mb_default(self):
        """Default max_document_size_mb is 20."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1")
        assert config.max_document_size_mb == 20

    def test_max_document_size_mb_custom(self):
        """Custom max_document_size_mb is accepted."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1", max_document_size_mb=50)
        assert config.max_document_size_mb == 50

    def test_enable_reply_context_default(self):
        """Default enable_reply_context is True."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1")
        assert config.enable_reply_context is True

    def test_enable_reply_context_disabled(self):
        """enable_reply_context can be disabled."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1", enable_reply_context=False)
        assert config.enable_reply_context is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `TelegramAgentConfig` is still at `models.py:39` and `singleton_agent` is still the last field before `__post_init__`
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-841-config-max-document-size.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-23
**Notes**: Added `max_document_size_mb: int = 20` and `enable_reply_context: bool = True` to `TelegramAgentConfig` dataclass after `singleton_agent` field. All 7 unit tests pass.

**Deviations from spec**: none
