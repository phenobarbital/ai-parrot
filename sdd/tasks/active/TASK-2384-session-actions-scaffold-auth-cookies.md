# TASK-2384: session_actions module scaffold + authenticate & cookie actions

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (Goal G1), first of three slices.

`executor.py::_dispatch_step` currently matches eight action types, logs a
warning and **returns `True`** — reporting success without doing anything
(spec §1, lines 298-311). The real implementations live only as methods on the
legacy `WebScrapingTool`. This task creates the shared module and lifts the
three *session-identity* actions into it: `authenticate`, `get_cookies`,
`set_cookies`.

The module shape is not a free choice: FEAT-222 already established it for
`Loop`/`Conditional` in `advanced_actions.py`. Mirror that file exactly.

Implements spec **Module 1 (part 1 of 3)**.

---

## Scope

- Create `session_actions.py` with the shared module-level types
  (`DispatchStepFn` type alias, module logger) mirroring `advanced_actions.py`.
- Implement `exec_authenticate(driver, action, dispatch_step_fn, *, credential_resolver=None, timeout=30) -> bool`
  by lifting the body of `WebScrapingTool._handle_authentication` (tool.py:1841).
  Support all four `method` values (`form`, `basic`, `oauth`, `custom`),
  including `enter_on_username` multi-step logins and `custom_steps` recursion
  through `dispatch_step_fn`.
- Implement `exec_get_cookies(driver, action) -> dict[str, Any]` from tool.py:1807.
- Implement `exec_set_cookies(driver, action) -> bool` from tool.py:1826.
- Write unit tests against a mocked `AbstractDriver`.

**NOT in scope**: wiring these into `executor.py` or `tool.py` (TASK-2387);
the wait actions (TASK-2385); the file actions (TASK-2386); the
`credential_provider` field on `Authenticate` (TASK-2389) — accept the
`credential_resolver` parameter now but leave it optional and unused by default.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py` | CREATE | Shared implementations; mirrors advanced_actions.py |
| `packages/ai-parrot-tools/tests/scraping/test_session_actions_auth.py` | CREATE | Unit tests for auth + cookies |

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
    Authenticate,   # line 478
    GetCookies,     # line 388
    SetCookies,     # line 397
    BrowserAction,  # line 14
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py
# THE PATTERN TO COPY (FEAT-222). Standalone async fns taking AbstractDriver
# plus a dispatch callback — NOT methods on a tool class.
def substitute_template_vars(...)                    # line 102
async def _evaluate_js_condition(driver: AbstractDriver, condition: str) -> bool:  # line 209
async def exec_loop(                                 # line 229
    driver, action, dispatch_step_fn, base_url, timeout) -> bool: ...
async def exec_conditional(                          # line 313
    driver, action, dispatch_step_fn, base_url, timeout) -> bool: ...

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
class Authenticate(BrowserAction):                  # line 478
    method: Literal["form","basic","oauth","custom"] = "form"
    username: Optional[str] = None
    password: Optional[str] = None
    username_selector: str = "#username"
    enter_on_username: bool = False                 # multi-step logins
    password_selector: str = "#password"
    submit_selector: str = 'input[type="submit"], button[type="submit"]'
    custom_steps: Optional[List[BrowserAction]] = None
    token: Optional[str] = None
    header_name: str = "Authorization"
    header_value_format: str = "Bearer {}"

# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py — SOURCE to lift from
async def _get_cookies(self, action: GetCookies) -> Dict[str, Any]:  # line 1807
async def _set_cookies(self, action: SetCookies) -> bool:            # line 1826
async def _handle_authentication(self, action: Authenticate):        # line 1841

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

- ~~`parrot_tools.scraping.session_actions`~~ — does not exist yet; **this task creates it**.
- ~~`AbstractDriver.set_cookie()`~~ / ~~`AbstractDriver.get_cookies()`~~ — NOT on the driver ABC. Cookie work goes through `execute_script`/`evaluate` or the driver-specific context, exactly as `tool.py:1807-1840` does it.
- ~~`Authenticate.credential_provider`~~ — not a field yet (TASK-2389 adds it). Do not reference it.
- ~~`CredentialBroker`~~ — do not import it in this task; only accept the optional `credential_resolver` callable.

---

## Implementation Notes

### Pattern to Follow
Copy the structural shape of `advanced_actions.py` verbatim: module-level
`async def exec_<action>(driver, action, ...)`, no class, `dispatch_step_fn`
passed in for any recursion (`custom_steps`).

### Key Constraints
- Async throughout; never block the loop.
- **Never log a credential.** `action.password` must not reach any log record,
  exception message, or repr. Redact before logging.
- Return `False` on failure — never `True`. The whole point of this feature is
  that a falsely-successful action corrupts an accounting workflow.
- `self.logger` does not exist here (module-level functions) — use the module
  logger, as `advanced_actions.py` does.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] `exec_authenticate` handles `form` logins including `enter_on_username` multi-step flows
- [ ] `custom_steps` recurse through `dispatch_step_fn`, not through a re-implemented dispatcher
- [ ] `exec_get_cookies` / `exec_set_cookies` round-trip a session on a mocked driver
- [ ] No credential value appears in any log record (assert with `caplog`)
- [ ] Every function returns `False` (never `True`) on a failure path
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_session_actions_auth.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.scraping.session_actions import (
    exec_authenticate, exec_get_cookies, exec_set_cookies,
)
from parrot_tools.scraping.models import Authenticate, GetCookies, SetCookies


class TestExecAuthenticate:
    async def test_form_login_fills_and_submits(self, mock_driver):
        action = Authenticate(username="u", password="p")
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=None) is True
        mock_driver.fill.assert_any_await("#username", "u")
        mock_driver.click.assert_awaited_with(action.submit_selector, timeout=10)

    async def test_enter_on_username_multistep(self, mock_driver):
        action = Authenticate(username="u", password="p", enter_on_username=True)
        await exec_authenticate(mock_driver, action, dispatch_step_fn=None)
        mock_driver.press_key.assert_awaited_with("Enter")

    async def test_never_logs_password(self, mock_driver, caplog):
        await exec_authenticate(mock_driver, Authenticate(username="u", password="hunter2"),
                                dispatch_step_fn=None)
        assert "hunter2" not in caplog.text

    async def test_returns_false_on_failure(self, failing_driver):
        assert await exec_authenticate(failing_driver, Authenticate(), dispatch_step_fn=None) is False


class TestCookies:
    async def test_roundtrip(self, mock_driver):
        cookies = await exec_get_cookies(mock_driver, GetCookies())
        assert await exec_set_cookies(mock_driver, SetCookies(cookies=cookies)) is True
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
7. **Move this file** to `sdd/tasks/completed/TASK-2384-session-actions-scaffold-auth-cookies.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
