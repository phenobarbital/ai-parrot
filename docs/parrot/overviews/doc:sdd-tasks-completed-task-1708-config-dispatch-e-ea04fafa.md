---
type: Wiki Overview
title: 'TASK-1708: Config Dispatch Extension'
id: doc:sdd-tasks-completed-task-1708-config-dispatch-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task wires the two new config dataclasses into the YAML parsing dispatch
  chain so that `kind: a2a` and `kind: msagent` entries in `integrations_bots.yaml`
  are recognized and parsed into the correct config objects.'
relates_to:
- concept: mod:parrot.integrations.models
  rel: mentions
---

# TASK-1708: Config Dispatch Extension

**Feature**: FEAT-271 — MSAgent & A2A YAML Integrations
**Spec**: `sdd/specs/msagent-a2a-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1706, TASK-1707
**Assigned-to**: unassigned

---

## Context

This task wires the two new config dataclasses into the YAML parsing dispatch chain so that `kind: a2a` and `kind: msagent` entries in `integrations_bots.yaml` are recognized and parsed into the correct config objects.

Implements spec §3 Module 3.

---

## Scope

- Add `A2AAgentConfig` import (with `try/except ImportError` guard) to `models.py`.
- Add `MSAgentIntegrationConfig` import (with `try/except ImportError` guard) to `models.py`.
- Add `elif kind == 'a2a'` branch in `IntegrationBotConfig.from_dict()`.
- Add `elif kind == 'msagent'` branch in `IntegrationBotConfig.from_dict()`.
- Update the `agents` dict type annotation in `IntegrationBotConfig` to include the new config types.
- Add the new config imports to `manager.py`'s import block.

**NOT in scope**: Startup methods (TASK-1710, TASK-1711), discovery registry, tests (TASK-1712).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/models.py` | MODIFY | Add imports + `elif` branches + type union |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Add config imports to the import block |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-integrations/src/parrot/integrations/models.py:1-13
from dataclasses import dataclass, field
from typing import Dict, List, Any, Union
from .telegram.models import TelegramAgentConfig       # line 6
from .msteams.models import MSTeamsAgentConfig          # line 7
from .whatsapp.models import WhatsAppAgentConfig        # line 8
from .slack.models import SlackAgentConfig              # line 9
try:                                                    # line 10
    from .msagentsdk.models import MSAgentSDKConfig     # line 11
except ImportError:                                     # line 12
    MSAgentSDKConfig = None                             # line 13
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/models.py:17
@dataclass
class IntegrationBotConfig:
    agents: Dict[str, Union[TelegramAgentConfig, MSTeamsAgentConfig, WhatsAppAgentConfig, SlackAgentConfig, MSAgentSDKConfig]] = field(default_factory=dict)  # line 36

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig':  # line 39
        # Dispatch chain at lines 50-59:
        # kind = agent_data.get('kind', 'telegram')
        # if kind == 'telegram': ...
        # elif kind == 'msteams': ...
        # elif kind == 'whatsapp': ...
        # elif kind == 'slack': ...
        # elif kind == 'msagentsdk': ...
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:26-31
from .models import (
    IntegrationBotConfig,
    TelegramAgentConfig,
    MSTeamsAgentConfig,
    WhatsAppAgentConfig,
    SlackAgentConfig,
    MSAgentSDKConfig,
)
```

### Does NOT Exist
- ~~`kind == 'a2a'` branch~~ — does not exist yet; this task adds it
- ~~`kind == 'msagent'` branch~~ — does not exist yet; this task adds it
- ~~`A2AAgentConfig` in models.py imports~~ — not imported yet; this task adds it

---

## Implementation Notes

### Pattern to Follow
```python
# In models.py — add after the MSAgentSDKConfig import guard:
try:
    from .a2a.models import A2AAgentConfig
except ImportError:
    A2AAgentConfig = None  # type: ignore[assignment,misc]

try:
    from .msagentsdk.models import MSAgentIntegrationConfig
except ImportError:
    MSAgentIntegrationConfig = None  # type: ignore[assignment,misc]

# In from_dict(), after the existing elif chain:
            elif kind == 'a2a' and A2AAgentConfig is not None:
                agents[name] = A2AAgentConfig.from_dict(name, agent_data)
            elif kind == 'msagent' and MSAgentIntegrationConfig is not None:
                agents[name] = MSAgentIntegrationConfig.from_dict(name, agent_data)
```

### Key Constraints
- Guard both imports with `try/except ImportError` — `A2AAgentConfig` requires `ai-parrot-server` (indirectly), `MSAgentIntegrationConfig` requires the msagentsdk extra.
- Add `and XConfig is not None` check in the `elif` to handle missing deps gracefully.
- Update the `Union` type hint on `agents` dict to include the new types.
- The `MSAgentIntegrationConfig` import comes from `msagentsdk.models` (same file as `MSAgentSDKConfig`) — only one import guard needed for both.

---

## Acceptance Criteria

- [ ] `kind: a2a` in YAML produces an `A2AAgentConfig` instance
- [ ] `kind: msagent` in YAML produces an `MSAgentIntegrationConfig` instance
- [ ] Missing `ai-parrot-server` does not crash import (ImportError guard)
- [ ] Existing kinds (`telegram`, `msteams`, `whatsapp`, `slack`, `msagentsdk`) still work
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/models.py`

---

## Test Specification

```python
# tests/integrations/test_config_dispatch.py
import pytest
from parrot.integrations.models import IntegrationBotConfig


class TestConfigDispatch:
    def test_a2a_kind_parsed(self):
        data = {"agents": {"TestA2A": {"kind": "a2a", "chatbot_id": "test"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "TestA2A" in config.agents
        assert config.agents["TestA2A"].kind == "a2a"

    def test_msagent_kind_parsed(self):
        data = {"agents": {"TestMS": {"kind": "msagent", "chatbot_id": "test"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "TestMS" in config.agents
        assert config.agents["TestMS"].kind == "msagent"

    def test_existing_kinds_unaffected(self):
        data = {"agents": {"Bot": {"kind": "telegram", "chatbot_id": "x", "bot_token": "t"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "Bot" in config.agents

    def test_unknown_kind_skipped(self):
        data = {"agents": {"X": {"kind": "unknown", "chatbot_id": "x"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "X" not in config.agents
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1706 and TASK-1707 are completed
3. **Verify the Codebase Contract** — confirm `models.py` dispatch chain is still at the listed lines
4. **Implement** the import guards and `elif` branches
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1708-config-dispatch-extension.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude)
**Date**: 2026-07-09
**Notes**: Added `try/except ImportError` guarded imports for `MSAgentIntegrationConfig` and `A2AAgentConfig` to `models.py`, added `elif kind == 'a2a'` and `elif kind == 'msagent'` branches (each guarded with `and XConfig is not None`) to `IntegrationBotConfig.from_dict()`, and updated the `agents` dict's `Union` type annotation to include both new types. Added the same two imports to `manager.py`'s import block (with `# noqa: F401` — they're forward-compatible imports consumed by `_start_a2a_bot()`/`_start_msagent_bot()` added in TASK-1709/TASK-1710, unused in this task's scope). Verified against the task's 4-case test scaffold (a2a parsed, msagent parsed, existing kinds unaffected, unknown kind skipped) — all pass. `ruff check` passes clean on both files.

**Deviations from spec**: none
