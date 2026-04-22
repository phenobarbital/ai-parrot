# TASK-821: Wire `ReminderToolkit` into `JiraSpecialist.post_configure`

**Feature**: FEAT-115 — Reminder Toolkit for Agents
**Spec**: `sdd/specs/FEAT-115-reminder-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-818, TASK-819
**Assigned-to**: unassigned

---

## Context

Implements Module 2 of the spec. Makes the `JiraSpecialist` agent the first
consumer of `ReminderToolkit`, unblocking the user-facing MVP:

> Manager on Telegram → JiraSpecialist → "recuérdame en 5h contactar a X"

Small integration: instantiate the toolkit with the runtime
`AgentSchedulerManager`, call `get_tools()`, extend `self.tools`, and register
with `self.tool_manager` — mirroring the `JiraToolkit` wiring already present at
`jira_specialist.py:580-614`.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/bots/jira_specialist.py` inside
  `post_configure()` (after `JiraToolkit` is registered, before method returns).
- Read `scheduler_manager = self.app.get("scheduler_manager")`. If `None`, log a
  warning and skip wiring (do NOT crash; a JiraSpecialist without scheduler should
  still boot).
- Instantiate `ReminderToolkit(scheduler_manager=scheduler_manager)`.
- `self.tools.extend(reminder_toolkit.get_tools())`.
- `self.tool_manager.register_tools(reminder_toolkit.get_tools())` — mirror
  the try/except around `register_tools` that already wraps `JiraToolkit` at
  lines 613-619.
- Add a short manual smoke check (documented in Acceptance Criteria) confirming
  the three new tool names appear in the registered tool list.

**NOT in scope**:
- Changes to any file outside `jira_specialist.py`.
- Unit tests (if needed, add a small test under `packages/ai-parrot/tests/bots/`
  only if it fits in the effort budget; otherwise a smoke run is enough given
  the thin nature of the change).
- Changes to other bots/agents. FEAT-115 picks JiraSpecialist as the first
  consumer intentionally; other bots can adopt the toolkit in follow-up work.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_specialist.py` | MODIFY | Add `ReminderToolkit` registration in `post_configure` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Add near the existing JiraToolkit import in jira_specialist.py (top of file).
from parrot.tools.reminder import ReminderToolkit
# created by TASK-818: packages/ai-parrot/src/parrot/tools/reminder.py
```

### Existing Code to Mirror (JiraToolkit wiring)

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py

    async def post_configure(self) -> None:                 # line 546
        await super().post_configure()                      # line 562
        # ... (auth selection lines 564-600, JiraToolkit construction) ...

        if self.tool_manager is not None:                   # line 602
            self.jira_toolkit.set_tool_manager(self.tool_manager)

        tools = self.jira_toolkit.get_tools()               # line 605
        if not tools:                                       # line 606
            return

        if not hasattr(self, "tools") or self.tools is None:  # line 609
            self.tools = []
        self.tools.extend(tools)                            # line 611

        try:                                                # line 613
            self.tool_manager.register_tools(tools)
        except Exception as exc:                            # line 615 (BLE001 suppressed)
            self.logger.error(
                "Failed to register Jira tools: %s", exc, exc_info=True
            )
            return
```

### Scheduler manager location

```python
# packages/ai-parrot/src/parrot/scheduler/__init__.py:1449
self.app['scheduler_manager'] = self
# So from JiraSpecialist: scheduler_manager = self.app.get("scheduler_manager")
```

### Does NOT Exist

- ~~`Agent.add_toolkit(toolkit)`~~ — not a method on the base Agent. Tools are registered via `tool_manager.register_tools(list_of_tools)`.
- ~~`self.app["reminder_manager"]`~~ — no such key. Reminders reuse `app["scheduler_manager"]`.
- ~~`self.register_toolkit(...)`~~ on `JiraSpecialist` — no such method. Follow the `JiraToolkit` pattern literally.

---

## Implementation Notes

### Target code shape

Add this block **after** the existing JiraToolkit `try/except` in `post_configure()`:

```python
        # --- Reminder toolkit (FEAT-115) ---------------------------------
        scheduler_manager = self.app.get("scheduler_manager") if self.app else None
        if scheduler_manager is None:
            self.logger.warning(
                "JiraSpecialist: app['scheduler_manager'] is not set; "
                "the reminder toolkit will NOT be registered. Set up "
                "AgentSchedulerManager in app.py to enable reminders."
            )
            return

        reminder_toolkit = ReminderToolkit(scheduler_manager=scheduler_manager)
        if self.tool_manager is not None:
            reminder_toolkit.set_tool_manager(self.tool_manager)

        reminder_tools = reminder_toolkit.get_tools()
        if not reminder_tools:
            return

        self.tools.extend(reminder_tools)
        try:
            self.tool_manager.register_tools(reminder_tools)
        except Exception as exc:  # noqa: BLE001 - mirror JiraToolkit tolerance
            self.logger.error(
                "Failed to register Reminder tools: %s", exc, exc_info=True
            )
```

### Key Constraints

- Warning-only path when `scheduler_manager is None` — do NOT raise. The bot
  must still boot if the scheduler is disabled.
- Use the same `BLE001` suppression comment used around JiraToolkit registration.
- Preserve the existing early `return` after JiraToolkit; the new block must be
  structured so it does not short-circuit JiraToolkit registration.
- Do not rename existing variables (`tools`, `toolkit_kwargs`, etc.). Use
  `reminder_tools` / `reminder_toolkit` to avoid collisions.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/jira_specialist.py:546-619` — mirrored pattern.
- `packages/ai-parrot/src/parrot/scheduler/__init__.py:1449` — where `scheduler_manager` is exposed on the app.

---

## Acceptance Criteria

- [ ] `jira_specialist.py` imports `ReminderToolkit` and registers it in `post_configure`.
- [ ] When `app['scheduler_manager']` is missing, the bot logs a warning and proceeds without raising.
- [ ] Smoke check (manual, run once by the implementing agent):
      ```bash
      source .venv/bin/activate
      python -c "
      from parrot.bots.jira_specialist import JiraSpecialist
      from parrot.tools.reminder import ReminderToolkit
      print('imports ok')
      "
      ```
- [ ] Smoke check (running bot — optional but preferred): after bot boot, the
      list of registered tools from `JiraSpecialist.tool_manager.get_tools()`
      contains `reminder_schedule_reminder`, `reminder_list_my_reminders`,
      `reminder_cancel_reminder` (or the equivalent names given the toolkit's
      `tool_prefix` chosen in TASK-818).
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/jira_specialist.py` → no errors.
- [ ] No unrelated changes in the diff.

---

## Agent Instructions

1. Verify TASK-818 is complete. Verify TASK-819 passes green.
2. Apply the diff to `jira_specialist.py` per the sketch. Keep the change tight — resist the urge to refactor other parts of `post_configure`.
3. Run ruff. Run the import smoke check.
4. If a full bot boot is easy in the dev env, run it and list `tool_manager.get_tools()` to confirm the three reminder tools appear.
5. Move the task file to `sdd/tasks/completed/`, flip `.index.json`, commit as `sdd: complete TASK-821 — wire ReminderToolkit into JiraSpecialist`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations, issues encountered.

**Deviations from spec**: none | describe if any

---
**Completed by**: sdd-worker agent
**Date**: 2026-04-22
**Notes**: Added `from parrot.tools.reminder import ReminderToolkit` import and wiring block in `post_configure()` after JiraToolkit registration. Gracefully skips with warning when `scheduler_manager` is None. Ruff clean (pre-existing F401 issues for `math` and `pandas` are not our change). All 19 FEAT-115 tests pass.

**Deviations from spec**: none
