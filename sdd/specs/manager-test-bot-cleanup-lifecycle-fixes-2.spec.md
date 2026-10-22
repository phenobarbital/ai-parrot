---
feature_id: FEAT-641
type: feature
base_branch: dev
status: approved
created: 2026-10-08
source: ledger (issue:c3c59277ef77, issue:3ea61bd4f2dc) via /sdd-fix
---

# FEAT-641 — BotManager test collection + hang fixes

## 1. Problem
Merge-tier validation of every feature hits three pre-existing collection errors and a
post-summary hang in `packages/ai-parrot/tests`:

- `tests/manager/test_bot_cleanup_lifecycle.py` installs ~130 lines of module-scope
  `sys.modules` stubs (auto-MagicMock `parrot.tools`, `parrot.mcp`, `datamodel`, handlers…).
  `AbstractBot`'s bases become `MagicMock` → `TypeError: metaclass conflict`, and the stubs
  leak into sibling modules collected in the same session
  (`tests/scheduler/test_scheduler_callbacks.py`, `tests/test_botmanager_flags.py`).
- `tests/test_botmanager_flags.py` patches `parrot.manager.manager.IntegrationBotManager`, which
  is now a lazy local import inside `BotManager.on_startup` → `AttributeError` (2 failures).
- The same two `on_startup` tests run the real ArtifactStore SQLite backend
  (`build_conversation_backend()` → `aiosqlite.connect`, writes under `~/.parrot`) and never
  close it; aiosqlite's non-daemon worker thread keeps pytest alive after the summary (hang).

## 2. Scope (Module 1 — single task)
1. Delete the stub block from `test_bot_cleanup_lifecycle.py`; the real `BotManager` import works.
2. In `test_botmanager_flags.py`, patch `parrot.integrations.IntegrationBotManager` and stub
   `build_conversation_backend`, `build_overflow_store`, `setup_web_hitl` in the `on_startup` tests.

Not in scope: production code; other order-dependent collection errors
(`tests/outputs/a2ui/graph/test_models.py`, `tests/unit/scripts/test_recompute_contextual_embeddings.py`)
— filed as a separate ledger issue.

## 3. Acceptance Criteria
- AC1: the three files collect and pass together (27 tests) and the pytest process exits.
- AC2: none of the three files appears among collection errors of `pytest --collect-only packages/ai-parrot/tests`.
- AC3: `ruff check` clean on the touched files.
