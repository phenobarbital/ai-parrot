---
id: F002
query_id: Q004
type: read
intent: Read the DSL step/action dispatch to see which actions the modern toolkit path actually supports
executed_at: 2026-08-23T09:23:00Z
depth: 1
parent_id: F001
---

# F002 — The modern toolkit path STUBS the 8 actions this feature needs most

## Summary

`executor.py::_dispatch_step` — the dispatcher used by the modern
`WebScrapingToolkit` — implements only 11 action types
(navigate/wait/click/fill/scroll/extract/screenshot/select/loop/conditional).
For eight further action types it logs a warning and **returns `True`**, i.e.
silently reports success without doing anything. That stub list is exactly
`authenticate`, `upload_file`, `wait_for_download`, `get_cookies`,
`set_cookies`, `await_human`, `await_keypress`, `await_browser_event` — the
login, file-exchange, session-persistence and human-approval primitives that a
Hooba invoice/expense workflow is built out of. They are implemented **only**
in the legacy `WebScrapingTool` (`tool.py`).

This is the same defect class FEAT-222 identified and fixed for
`Loop`/`Conditional` (spec §1 gap 4) — the fix covered those two and left the
other eight stubbed.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
  lines: 251-291
  symbol: `_dispatch_step`
  excerpt: |
    if action_type == "navigate": ...
    elif action_type == "wait": ...     elif action_type == "click": ...
    elif action_type == "fill": ...     elif action_type == "scroll": ...
    elif action_type == "extract": ...  elif action_type == "screenshot": ...
    elif action_type == "select": ...   elif action_type == "loop": ...
    elif action_type == "conditional": ...

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
  lines: 298-311
  symbol: `_dispatch_step` (stub branch)
  excerpt: |
    elif action_type in (
        "get_cookies", "set_cookies", "authenticate",
        "await_human", "await_keypress", "await_browser_event",
        "upload_file", "wait_for_download",
    ):
        # These advanced actions require the full WebScrapingTool context.
        # Log a warning and return True to not block the pipeline.
        logger.warning(
            "Action '%s' requires the full WebScrapingTool; "
            "skipping in standalone executor.", action_type,
        )
        return True

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
  lines: 747, 708, 2086-2172
  symbol: `_execute_step` / `_await_human`
  excerpt: |
    elif action_type == 'authenticate':      # line 747 — real implementation
    elif action_type == 'await_human':       # line 708
        result = await self._await_human(action)
    async def _await_human(self, action: AwaitHuman):   # line 2086

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
  lines: 2902-2926
  symbol: "authenticate JSON schema"
  excerpt: |
    "description": "Authentication method (for 'authenticate' action)"
    "description": "Username or email (for 'authenticate' action)"
    "description": "Press Enter after filling username (for multi-step logins)"
    "description": "Password (for 'authenticate' action)"
    "description": "CSS selector for username field / password field / submit button"

## Notes

`return True` on an unimplemented action is the dangerous part: a Hooba plan
whose step 1 is `authenticate` would proceed to step 2 believing it is logged
in. Against an accounting system that means subsequent steps operate on a login
page, not a dashboard. Any spec here must treat "close the stub gap" as a
prerequisite task, not a nice-to-have.
