# TASK-817: Document the bot cleanup lifecycle

**Feature**: FEAT-114 — Bot Cleanup Lifecycle
**Spec**: `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-813, TASK-814
**Assigned-to**: unassigned

---

## Context

The spec (§5 Acceptance Criteria) requires documentation updates where
the hook / agent lifecycle is described, including the MRO contract
for `HookableAgent`. This task delivers those updates.

The goal is to leave a single, discoverable page that explains:

- `AbstractBot.cleanup()` is the canonical per-bot teardown hook.
- `BotManager._cleanup_all_bots` is wired on aiohttp `on_cleanup` and
  iterates every registered bot concurrently, bounded by
  `BOT_CLEANUP_TIMEOUT` (env-tunable, default 20 s).
- `HookableAgent.cleanup()` cooperates via MRO — subclasses MUST
  declare the mixin before the bot base
  (`class MyAgent(HookableAgent, JiraSpecialist):`).
- `AbstractBot.shutdown()` is **separate** (A2A / MCP semantics).

---

## Scope

- Locate the existing hook/integration docs under
  `packages/ai-parrot/docs/`. Recent features add Markdown pages;
  pick the existing page that best describes the bot lifecycle or
  the hook system (e.g. a file already describing HookableAgent
  or the BotManager), and extend it with a dedicated
  "Cleanup lifecycle" section. If no suitable page exists, create
  `packages/ai-parrot/docs/bot-cleanup-lifecycle.md`.
- The section MUST contain:
  1. A one-paragraph overview of the shutdown sequence (`on_shutdown`
     → `on_cleanup`).
  2. A subsection "Writing cleanup-aware agents" that shows the
     correct MRO pattern for `HookableAgent` subclasses, with a
     positive and a negative example (the negative example labelled
     with why it breaks).
  3. A subsection "Configuration" listing `BOT_CLEANUP_TIMEOUT`
     (default 20 s), how to override via env, and the on-timeout
     behaviour (log warning, continue with other bots).
  4. A note that `AbstractBot.shutdown()` is intentionally separate
     from `cleanup()` and is NOT the resource-release hook.
- Update the `parrot/core/hooks/mixins.py` class docstring only if
  TASK-813 did not already cover it — if the docstring already has
  the MRO contract paragraph, skip the docstring edit and cover it
  in the external doc only.

**NOT in scope**:
- New code in `src/` — this task is documentation only.
- API reference changes (Sphinx / autodoc) unless the project
  happens to use autodoc for this module (verify with a quick
  `grep` for `automodule::` referencing `core.hooks.mixins`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/docs/bot-cleanup-lifecycle.md` *(or the existing equivalent page)* | CREATE or MODIFY | Add the "Cleanup lifecycle" section per the structure above. |

*(Exact target file TBD by the implementing agent after a 1-minute
scan of `packages/ai-parrot/docs/`.)*

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No code imports in this task — it is documentation. Cross-references
to code use Markdown links with file paths relative to the repo root.

### Existing Signatures to Use (for cross-reference only)

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:3134
class AbstractBot(ABC):
    async def cleanup(self) -> None: ...

# packages/ai-parrot/src/parrot/core/hooks/mixins.py
class HookableAgent:
    async def cleanup(self) -> None: ...   # added by TASK-813

# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:
    async def _cleanup_all_bots(self, app: web.Application) -> None: ...  # added by TASK-814
    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool: ...  # added by TASK-814

# packages/ai-parrot/src/parrot/conf.py
BOT_CLEANUP_TIMEOUT: int  # added by TASK-812, default 20
```

### Does NOT Exist

- ~~`AbstractBot.dispose()` / `AbstractBot.close()`~~ — the canonical
  method is `cleanup()`.
- ~~`parrot.core.hooks.HookableAgent.close()`~~ — not a method on
  the mixin. Only `cleanup()` and `stop_hooks()` exist.
- ~~`BotManager.shutdown_bots()`~~ — not a public method. The
  internal helper is `_cleanup_all_bots`; docs should describe the
  behaviour, not advertise the private name as public API.

---

## Implementation Notes

### Pattern to Follow

Structure the new section like existing docs pages (which use
H2/H3 headings and code fences with language hints). A minimal
skeleton to copy:

```markdown
## Cleanup lifecycle

Every bot registered in `BotManager._bots` receives a call to
`AbstractBot.cleanup()` when the aiohttp application fires
`on_cleanup`. Cleanups run concurrently with `asyncio.gather` and are
bounded per-bot by `BOT_CLEANUP_TIMEOUT` (default 20 s).

### Shutdown sequence

1. `on_shutdown` — `BotManager.on_shutdown`: cancels background
   tasks, shuts down integration bots (Telegram / Slack / Matrix /
   HITL), closes `chat_storage`.
2. `on_cleanup` — `BotManager._cleanup_all_bots`: iterates every bot
   concurrently, each call bounded by `BOT_CLEANUP_TIMEOUT`.
3. `on_cleanup` — `BotManager._cleanup_shared_redis`: closes the
   shared Redis client (runs **after** bot cleanups so bots can still
   use Redis during their own teardown).

### Writing cleanup-aware agents

Agents that use `HookableAgent` get hook teardown for free — but only
when the mixin is declared **before** the bot base in the class bases:

```python
# ✅ Correct — HookableAgent first
class JiraTroc(HookableAgent, JiraSpecialist):
    ...

# ❌ Incorrect — super().cleanup() resolves to object in the mixin,
# hooks never stop via BotManager's cleanup.
class JiraTroc(JiraSpecialist, HookableAgent):
    ...
```

### Configuration

| Variable | Type | Default | Effect |
|---|---|---|---|
| `BOT_CLEANUP_TIMEOUT` | int (seconds) | `20` | Per-bot cleanup timeout. On timeout the bot is logged and skipped; other bots still complete. |

### `shutdown()` vs `cleanup()`

`AbstractBot.shutdown()` is an A2A / MCP integration hook with its own
semantics (worker teardown, MCP server stop). **It is not** the
resource-release hook. Put LLM / store / KB / MCP teardown in
`cleanup()`.
```

### Key Constraints

- Keep prose in English — the rest of `docs/` is English.
- Use Markdown tables for the configuration section so it matches
  the existing docs style.
- Do not duplicate the full flow diagram from the spec; link to the
  spec file from the docs page so the diagram stays in one place.

### References in Codebase

- `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md` — spec with full
  diagram and rationale.
- `packages/ai-parrot/docs/` — existing docs style.

---

## Acceptance Criteria

- [ ] Documentation page created or extended under `packages/ai-parrot/docs/`.
- [ ] Page contains the four subsections listed in Scope.
- [ ] Positive and negative MRO examples are present.
- [ ] `BOT_CLEANUP_TIMEOUT` default (`20`) and env-override mechanism are documented.
- [ ] Separation of `shutdown()` vs `cleanup()` is explicitly called out.
- [ ] Page links to the FEAT-114 spec.
- [ ] No stale references to methods that do not exist (cross-check against the task's "Does NOT Exist" section).

---

## Test Specification

No automated tests. Manual verification: `grep -rn "BOT_CLEANUP_TIMEOUT"
packages/ai-parrot/docs/` returns the new documentation; the page
renders in any Markdown viewer.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md` for full context.
2. **Check dependencies** — TASK-813 and TASK-814 must be in `sdd/tasks/completed/`.
3. **Scan** `packages/ai-parrot/docs/` for an existing page that
   discusses `HookableAgent`, hooks, or the bot lifecycle. Pick
   extension over creation when a good home exists.
4. **Verify** the class docstring on `HookableAgent` (TASK-813 output)
   to avoid duplicating or contradicting it.
5. **Update status** in `sdd/tasks/.index.json` → `in-progress`.
6. **Write** the documentation following the pattern above.
7. **Move this file** to `sdd/tasks/completed/TASK-817-cleanup-lifecycle-docs.md`.
8. **Update index** → `done`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-22
**Notes**: Created `docs/bot-cleanup-lifecycle.md` (new file, no existing equivalent found). Contains: overview, shutdown sequence table, cleanup-aware agent section with correct/incorrect MRO examples, configuration table, shutdown() vs cleanup() distinction, double-cleanup safety note, and links to spec. Docstring in `mixins.py` already updated by TASK-813 — not duplicated here.

**Deviations from spec**: none
