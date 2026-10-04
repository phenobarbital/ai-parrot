---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [integrations, msteams, ledger-fix]
---

# Feature Specification: IntegrationBotManager shutdown closes MSTeams wrapper sessions (FEAT-551 follow-up)

**Feature ID**: FEAT-629
**Date**: 2026-10-05
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: next
**Origin**: `/sdd-fix` ledger group `fixgroup:d70a7078c613` — `issue:a9514c9232ad`
(`discovered_from: spec:FEAT-551`, closed parent).

---

## 1. Motivation & Business Requirements

### Problem Statement

`IntegrationBotManager.shutdown()`
(`packages/ai-parrot-integrations/src/parrot/integrations/manager.py`) stops Telegram, MS Agent SDK,
MSAgent, Slack, dev-loop, A2A, Matrix and HITL resources, but for MS Teams it only calls
`self.msteams_bots.clear()`. It never awaits the two resource-release methods that
`MSTeamsAgentWrapper` exposes:

- `close_formdesigner_client()` — closes the lazily created FormDesigner `aiohttp.ClientSession`
  (added by FEAT-551);
- `close_voice_transcriber()` — closes the voice transcriber (pre-existing).

Result: on application shutdown the sessions leak, producing `Unclosed client session` warnings and
leaked connectors.

### Goals
- G1: `shutdown()` awaits `close_formdesigner_client()` and `close_voice_transcriber()` on every
  registered MS Teams wrapper before the registries are cleared.
- G2: A failure closing one wrapper (or one of its resources) is logged and does not prevent the
  remaining wrappers / remaining shutdown steps from running — same per-wrapper `try/except`
  pattern as the msagent loop.

### Non-Goals
- Any change to `MSTeamsAgentWrapper` itself (its close methods are already idempotent).
- Adding a generic `stop()` to the MS Teams wrapper.

---

## 2. Architectural Design

In `shutdown()`, after the MSAgent loop, add a loop over `self.msteams_bots.items()` that awaits
`wrapper.close_formdesigner_client()` then `wrapper.close_voice_transcriber()`, each in its own
`try/except Exception` that logs via `self.logger.error(...)` with the bot name. Each close is
isolated so a failing FormDesigner close still lets the transcriber close.

---

## 3. Module Breakdown

| Module | File | Change |
|---|---|---|
| M1 | `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY `shutdown()` |
| M1 | `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py` | CREATE |

---

## 4. Test Specification

- `test_shutdown_closes_msteams_wrapper_resources` — two fake wrappers registered; after
  `shutdown()` both close methods were awaited once on each; `msteams_bots` is empty.
- `test_shutdown_msteams_close_failure_is_isolated` — wrapper A's `close_formdesigner_client`
  raises; A's `close_voice_transcriber` and wrapper B's closes are still awaited; `shutdown()`
  does not raise.

---

## 5. Acceptance Criteria

- AC1: `shutdown()` awaits both close methods on every MS Teams wrapper.
- AC2: An exception in any MS Teams close is logged and does not abort shutdown or skip other closes.
- AC3: Tests in §4 pass; `ruff check` on the touched files is clean.

---

## 6. Worktree Strategy

Single task, single worktree `feat-FEAT-629-integrations-manager-fixes` off `origin/dev`.
