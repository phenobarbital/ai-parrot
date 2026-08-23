# TASK-2385: session_actions wait actions + HumanChannel injection

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2384
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** (Goal G1), second slice: the three waiting actions
`await_human`, `await_keypress`, `await_browser_event`.

`await_human` is the load-bearing one for this feature. Under the spec's
autonomy policy (§8, resolved U5) *every* write with legal effect pauses for a
human. But per **Decision D2** the approver is in Telegram and is not watching
Chrome, so a DOM-only wait is not sufficient: this task injects a
`HumanChannel` so the pause actually reaches a person.

Implements spec **Module 1 (part 2 of 3)**.

---

## Scope

- Implement `exec_await_human(driver, action, *, channel=None) -> bool` by
  lifting `WebScrapingTool._await_human` (tool.py:2086-2172), preserving the
  four `condition_type` values (`selector`, `url_contains`, `title_contains`,
  `manual`) and the `timeout` (default 300s).
- Add `HumanChannel` integration per **Decision D2**:
  - `condition_type="manual"` has no DOM condition to poll and therefore
    **requires** a channel — with `channel=None` it must **fail closed**
    (return `False` immediately), not block for the full timeout.
  - The DOM-based condition types keep polling, but must also call
    `channel.send_notification(...)` so the operator learns the browser is
    waiting.
- Implement `exec_await_keypress` (tool.py:2175) and `exec_await_browser_event`
  (tool.py:1913).
- Write unit tests, including the fail-closed path.

**NOT in scope**: the `ConfirmationGuard` tool-call gate (TASK-2390); wiring
into the dispatcher (TASK-2387); resolving *which* channel instance to use —
accept it as an injected parameter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py` | MODIFY | Add the three wait actions |
| `packages/ai-parrot-tools/tests/scraping/test_session_actions_waits.py` | CREATE | Unit tests incl. fail-closed |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver   # verified: drivers/abstract.py:37
from parrot_tools.scraping.models import (                        # verified: scraping/models.py
    AwaitHuman,          # line 514
    AwaitKeyPress,       # line 534
    AwaitBrowserEvent,   # line 549
)
# HITL — Decision D2. Import lazily / under TYPE_CHECKING to keep parrot_tools
# free of a hard runtime dependency on the channel implementations.
from parrot.human.channels.base import HumanChannel                # verified: human/channels/base.py:47
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
class AwaitHuman(BrowserAction):                    # line 514
    target: Optional[str] = None
    condition_type: Literal["selector","url_contains","title_contains","manual"] = "selector"
    message: str = "Waiting for human intervention..."
    timeout: int = 300

# packages/ai-parrot/src/parrot/human/channels/base.py
class HumanChannel(ABC):                            # line 47
    async def start(self) -> None: ...              # line 83
    async def stop(self) -> None: ...               # line 90
    async def send_interaction(...) -> ...          # line 100
    async def send_notification(...) -> ...         # line 119
    async def cancel_interaction(...) -> ...        # line 132
    async def register_response_handler(...) -> ... # line 151

# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py — SOURCE to lift from
async def _await_browser_event(self, action: AwaitBrowserEvent) -> bool:  # line 1913
async def _await_human(self, action: AwaitHuman):                         # line 2086
    #   line 2114: "await_human requires at least one condition
    #               (selector, url_contains, title_contains)"
    #   line 2172: "await_human timed out waiting for the specified condition."
async def _await_keypress(self, action: AwaitKeyPress):                   # line 2175

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):                          # line 37
    async def navigate(self, url: str, timeout: int = 30) -> None: ...   # line 47
    async def click(self, selector: str, timeout: int = 10) -> None: ... # line 70
    async def fill(...) -> None: ...                                     # line 79
    async def select_option(...) -> None: ...                            # line 91
    async def hover(self, selector: str, timeout: int = 10) -> None: ... # line 111
    async def press_key(self, key: str) -> None: ...                     # line 120
    async def get_page_source(self) -> str: ...                          # line 130
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...# line 134
    async def wait_for_selector(...) -> None: ...                        # line 185
    async def wait_for_navigation(self, timeout: int = 30) -> None: ...  # line 198
    async def execute_script(self, script: str, *args) -> Any: ...       # line 220
    async def evaluate(self, expression: str) -> Any: ...                # line 232
    def current_url(self) -> str: ...                                    # line 246
    async def save_pdf(self, path: str) -> bytes: ...                    # line 284
```

### Does NOT Exist

- ~~`NotifierFn`~~ — invented in this spec's v0.1 draft and **deleted at v0.2**. Use `HumanChannel` (Decision D2). Do not resurrect it.
- ~~`HumanChannel.ask()`~~ / ~~`HumanChannel.prompt()`~~ — not real methods. The surface is `send_interaction` / `send_notification` / `cancel_interaction` / `register_response_handler` / `register_cancel_handler` (base.py:100-162).
- ~~`parrot.human.TelegramHumanChannel` as a normal import~~ — it is a **lazy PEP 562 export** resolved through `parrot/human/__init__.py:40` and contributed by the ai-parrot-integrations satellite. Never import it at module top level in `parrot_tools`.

---

## Implementation Notes

### Pattern to Follow
Same module-level `exec_*` shape as TASK-2384.

### Key Constraints
- **Fail closed, do not hang.** `condition_type="manual"` with `channel=None`
  returns `False` immediately. A 300s block that then times out looks like a
  slow site; an immediate `False` is diagnosable.
- Keep the `parrot_tools` → `parrot.human` dependency soft: guard the import so
  a core-only install still imports this module.
- Preserve the existing "requires at least one condition" validation
  (tool.py:2114) — it is a real guard, not boilerplate.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All four `condition_type` values behave as in the legacy implementation
- [ ] `condition_type="manual"` with `channel=None` returns `False` immediately (does not wait for `timeout`)
- [ ] A DOM-condition pause also emits `channel.send_notification(...)` when a channel is supplied
- [ ] `exec_await_human` with no condition at all still raises/returns the legacy validation error
- [ ] Importing `session_actions` succeeds on a core-only install (no integrations satellite)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_session_actions_waits.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.scraping.session_actions import exec_await_human
from parrot_tools.scraping.models import AwaitHuman


class TestAwaitHuman:
    async def test_manual_without_channel_fails_closed(self, mock_driver):
        action = AwaitHuman(condition_type="manual", timeout=300)
        # must NOT block for 300s
        assert await exec_await_human(mock_driver, action, channel=None) is False

    async def test_selector_condition_notifies_channel(self, mock_driver, fake_channel):
        action = AwaitHuman(condition_type="selector", target="#done")
        await exec_await_human(mock_driver, action, channel=fake_channel)
        assert fake_channel.notifications, "operator was never told the browser is waiting"

    async def test_timeout_returns_false(self, never_ready_driver):
        action = AwaitHuman(condition_type="selector", target="#never", timeout=1)
        assert await exec_await_human(never_ready_driver, action) is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2385-session-actions-waits-humanchannel.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
