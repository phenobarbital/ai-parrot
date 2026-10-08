# TASK-4142: BotManager test collection + hang fix

**Feature**: FEAT-641 manager-test-bot-cleanup-lifecycle-fixes-2
**Spec**: sdd/specs/manager-test-bot-cleanup-lifecycle-fixes-2.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: agent:sdd-fix

## Context
See spec §1. Resolves ledger issue:c3c59277ef77 and issue:3ea61bd4f2dc.

## Scope
- Remove module-scope `sys.modules` stubs from `packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py`.
- Fix patch targets / stub startup I/O in `packages/ai-parrot/tests/test_botmanager_flags.py`.

NOT in scope: production code, other test modules.

## Files to Modify
- packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py
- packages/ai-parrot/tests/test_botmanager_flags.py

## Codebase Contract
- Verified: `parrot.manager.manager` imports `build_conversation_backend`, `build_overflow_store`, `setup_web_hitl` at module scope; `IntegrationBotManager` is imported lazily from `parrot.integrations` inside `on_startup`.
- Does NOT exist: `parrot.manager.manager.IntegrationBotManager` module attribute.

## Acceptance Criteria
Spec §3 AC1–AC3.

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src timeout -s KILL 120 pytest -q \
  packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py \
  packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py \
  packages/ai-parrot/tests/test_botmanager_flags.py
```

## Completion Note
_pending_
