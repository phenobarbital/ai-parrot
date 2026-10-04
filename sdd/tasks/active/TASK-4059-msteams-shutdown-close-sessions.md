# TASK-4059: Close MSTeams wrapper sessions in IntegrationBotManager.shutdown()

**Feature**: FEAT-629 — IntegrationBotManager shutdown closes MSTeams wrapper sessions
**Spec**: `sdd/specs/integrations-manager-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Resolves ledger issue `issue:a9514c9232ad`. See spec §1.

## Scope

- `manager.py` `shutdown()`: iterate `self.msteams_bots.items()` and await
  `wrapper.close_formdesigner_client()` and `wrapper.close_voice_transcriber()`, each in its own
  `try/except Exception` logging `self.logger.error(...)` with the bot name.
- New test module per spec §4.

**NOT in scope**: changes to `msteams/wrapper.py`; a `stop()` for the MS Teams wrapper.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py` | CREATE |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.manager import IntegrationBotManager  # manager.py:91
```

### Existing Signatures to Use
```python
# manager.py:102
def __init__(self, bot_manager: 'BotManager')
# manager.py:108
self.msteams_bots: Dict[str, 'MSTeamsAgentWrapper'] = {}
# manager.py:1008
async def shutdown(self) -> None
# msteams/wrapper.py:1040
async def close_formdesigner_client(self) -> None
# msteams/wrapper.py:1046
async def close_voice_transcriber(self) -> None
```

### Does NOT Exist
- `MSTeamsAgentWrapper.stop()` / `.close()` — there is no single teardown method.

## Acceptance Criteria
Spec §5 AC1–AC3.

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py -q
ruff check packages/ai-parrot-integrations/src/parrot/integrations/manager.py packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py
```

## Completion Note
_(filled on close)_
