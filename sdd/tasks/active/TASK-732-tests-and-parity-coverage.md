# TASK-732: Update tests + add Selenium↔Playwright parity coverage

**Feature**: fix-webscrapingtoolkit-executor
**Spec**: `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-727, TASK-728, TASK-729, TASK-730, TASK-731
**Assigned-to**: unassigned

---

## Context

Existing executor / toolkit tests use `MagicMock` configured to look like a
Selenium WebDriver (sync `driver.get`, `PropertyMock` for `page_source`,
`driver.switch_to.active_element`, etc.). Once TASK-729 lands these fixtures
are wrong: the executor now calls awaited `AbstractDriver` methods.

This task updates the affected test suites and adds the cross-driver parity
test required by spec acceptance criteria.

Implements **Module 6** of the spec.

---

## Scope

- Update `packages/ai-parrot-tools/tests/scraping/test_executor.py`:
  - Replace the `mock_driver` Selenium-style fixture (lines 25-38) with an
    `AsyncMock`-based `AbstractDriver` fake exposing `navigate`,
    `get_page_source`, `current_url` (PropertyMock), `execute_script`,
    `reload`, `go_back`, `screenshot`, `press_key`, `click`, `fill`,
    `select_option`, `wait_for_selector`, `evaluate`.
  - Update each existing test assertion (`mock_driver.get.assert_called_once_with(...)`
    → `mock_driver.navigate.assert_awaited_once_with(...)`, and similarly
    for `refresh` → `reload`, `back` → `go_back`, `save_screenshot` → `screenshot`,
    `switch_to.active_element.send_keys` → `press_key`).

- Update `packages/ai-parrot-tools/tests/scraping/test_toolkit.py`:
  - Update the `mock_driver` fixture (lines 67-74) the same way.
  - Tests that patch `parrot_tools.scraping.toolkit.driver_context` to yield
    the mock driver continue to work because `driver_context` already yields
    "the driver"; only the mock's surface changes.

- Update `tests/tools/scraping/test_driver_context.py`:
  - Add `TestSeleniumAdapter` class covering:
    - `test_selenium_factory_returns_abstract_driver`
    - `test_selenium_adapter_passes_config_fields` (assert `disable_images`,
      `custom_user_agent`, `mobile_device`, `headless`, `auto_install` flow
      through to the SeleniumDriver constructor).
  - Verify the Playwright factory test still passes (regression).

- Add `packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py`:
  - Implement a `RecordingDriver(AbstractDriver)` that records every method
    call as `(method_name, args, kwargs)`.
  - Run the same fixed `ScrapingPlan` (navigate → wait → click → fill →
    extract) through `execute_plan_steps` against two independent
    `RecordingDriver` instances and assert the recorded call sequences are
    identical.
  - This is the canonical proof of G1 ("no call-site changes between Selenium
    and Playwright").

- Add `packages/ai-parrot-tools/tests/scraping/test_page_snapshot_driver.py`
  (or extend an existing snapshot test file if present) with the cases listed
  in TASK-730's Test Specification.

**NOT in scope**:
- Touching production code (TASK-727 through TASK-731 own their respective files).
- Live-browser smoke tests (out of scope; this is unit-level coverage).
- Touching `tests/` for unrelated modules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/scraping/test_executor.py` | MODIFY | Replace Selenium-style mock with AbstractDriver fake; update assertions |
| `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` | MODIFY | Same fixture update |
| `tests/tools/scraping/test_driver_context.py` | MODIFY | Add Selenium adapter type + config-passthrough tests |
| `packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py` | CREATE | New parity test |
| `packages/ai-parrot-tools/tests/scraping/test_page_snapshot_driver.py` | CREATE | New snapshot tests (or merge into existing snapshot test file if there is one — check first) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11

from parrot_tools.scraping.executor import execute_plan_steps
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:33

from parrot_tools.scraping.page_snapshot import snapshot_from_driver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py:483

from parrot_tools.scraping.toolkit import WebScrapingToolkit
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:74

from parrot_tools.scraping.driver_context import DriverRegistry
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:19

from parrot_tools.scraping.toolkit_models import DriverConfig
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:15
```

### Existing Signatures to Use
```python
# Note: imports inside test_toolkit.py use parrot.tools.scraping.* alias,
# while test_executor.py uses parrot.tools.scraping.executor — keep the
# module path each test currently uses to avoid breaking the import path.

# Current fixture to REPLACE — packages/ai-parrot-tools/tests/scraping/test_executor.py:25
@pytest.fixture
def mock_driver():
    """A mock Selenium-like driver."""
    driver = MagicMock()
    type(driver).current_url = PropertyMock(return_value="https://example.com")
    type(driver).page_source = PropertyMock(return_value=HTML_BODY)
    driver.get = MagicMock(return_value=None)
    driver.refresh = MagicMock(return_value=None)
    driver.back = MagicMock(return_value=None)
    driver.execute_script = MagicMock(return_value=None)
    driver.save_screenshot = MagicMock(return_value=None)
    active_el = MagicMock()
    driver.switch_to.active_element = active_el
    return driver

# Current fixture to REPLACE — packages/ai-parrot-tools/tests/scraping/test_toolkit.py:67
@pytest.fixture
def mock_driver():
    driver = MagicMock()
    type(driver).current_url = PropertyMock(return_value="https://example.com/products")
    type(driver).page_source = PropertyMock(return_value=HTML_BODY)
    driver.get = MagicMock(return_value=None)
    driver.execute_script = MagicMock(return_value=None)
    driver.quit = MagicMock(return_value=None)
    return driver
```

### Does NOT Exist
- ~~`AbstractDriver.assert_called_once_with(...)`~~ — assertions go on the AsyncMock attributes, not on the abstract class
- ~~`pytest-async-mock`~~ — use `unittest.mock.AsyncMock` from stdlib (existing tests already do)
- ~~A pre-existing `test_page_snapshot.py`~~ — verify with `ls` before creating; merge into it if present

---

## Implementation Notes

### Pattern to Follow

```python
# Replacement mock_driver fixture (shared across executor & toolkit tests)
HTML_BODY = "<html><body><h1>Title</h1><p class='desc'>Hello world</p></body></html>"

@pytest.fixture
def mock_driver():
    """An AsyncMock-backed AbstractDriver fake."""
    driver = AsyncMock()
    type(driver).current_url = PropertyMock(return_value="https://example.com")
    driver.get_page_source = AsyncMock(return_value=HTML_BODY)
    driver.navigate = AsyncMock(return_value=None)
    driver.reload = AsyncMock(return_value=None)
    driver.go_back = AsyncMock(return_value=None)
    driver.execute_script = AsyncMock(return_value=None)
    driver.evaluate = AsyncMock(return_value="")
    driver.screenshot = AsyncMock(return_value=b"")
    driver.press_key = AsyncMock(return_value=None)
    driver.click = AsyncMock(return_value=None)
    driver.fill = AsyncMock(return_value=None)
    driver.select_option = AsyncMock(return_value=None)
    driver.wait_for_selector = AsyncMock(return_value=None)
    driver.quit = AsyncMock(return_value=None)
    return driver


# RecordingDriver for the parity test
class RecordingDriver(AbstractDriver):
    def __init__(self):
        self.calls = []
        self._url = ""
        self._html = "<html><body><h1>ok</h1></body></html>"

    async def start(self): self.calls.append(("start",))
    async def quit(self): self.calls.append(("quit",))
    async def navigate(self, url, timeout=30):
        self.calls.append(("navigate", url, timeout)); self._url = url
    async def go_back(self): self.calls.append(("go_back",))
    async def go_forward(self): self.calls.append(("go_forward",))
    async def reload(self): self.calls.append(("reload",))
    async def click(self, selector, timeout=10):
        self.calls.append(("click", selector, timeout))
    async def fill(self, selector, value, timeout=10):
        self.calls.append(("fill", selector, value, timeout))
    async def select_option(self, selector, value, *, by="value", timeout=10):
        self.calls.append(("select_option", selector, value, by, timeout))
    async def hover(self, selector, timeout=10):
        self.calls.append(("hover", selector, timeout))
    async def press_key(self, key):
        self.calls.append(("press_key", key))
    async def get_page_source(self):
        self.calls.append(("get_page_source",)); return self._html
    async def get_text(self, selector, timeout=10):
        self.calls.append(("get_text", selector)); return ""
    async def get_attribute(self, selector, attribute, timeout=10):
        self.calls.append(("get_attribute", selector, attribute)); return None
    async def get_all_texts(self, selector, timeout=10):
        self.calls.append(("get_all_texts", selector)); return []
    async def screenshot(self, path, full_page=False):
        self.calls.append(("screenshot", path)); return b""
    async def wait_for_selector(self, selector, timeout=10, state="visible"):
        self.calls.append(("wait_for_selector", selector, timeout, state))
    async def wait_for_navigation(self, timeout=30):
        self.calls.append(("wait_for_navigation", timeout))
    async def wait_for_load_state(self, state="load", timeout=30):
        self.calls.append(("wait_for_load_state", state, timeout))
    async def execute_script(self, script, *args):
        self.calls.append(("execute_script", script, args))
    async def evaluate(self, expression):
        self.calls.append(("evaluate", expression)); return ""
    @property
    def current_url(self): return self._url


@pytest.mark.asyncio
async def test_executor_parity_selenium_vs_playwright_mock():
    plan = ScrapingPlan(
        url="https://example.com",
        objective="parity",
        steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "wait", "condition": ".ready", "condition_type": "selector"},
            {"action": "click", "selector": "#go"},
            {"action": "fill", "selector": "#q", "value": "hi"},
            {"action": "extract", "selector": "h1", "extract_name": "title"},
        ],
    )
    a = RecordingDriver(); b = RecordingDriver()
    await execute_plan_steps(a, plan=plan)
    await execute_plan_steps(b, plan=plan)
    assert a.calls == b.calls
```

### Key Constraints

- Use `AsyncMock` for awaited methods, plain `PropertyMock` for `current_url`.
- The parity test must NOT mock at the abstract layer — it instantiates a
  real (in-memory) `AbstractDriver` subclass to prove the executor never
  reaches into Selenium-only attributes.
- Keep `parrot.tools.scraping` import alias if existing tests use it (some
  tests import via the `parrot.tools.scraping` namespace; verify before
  changing — both paths resolve to the same module).

### References in Codebase

- `packages/ai-parrot-tools/tests/scraping/test_executor.py` — current 30 tests; expect ~half to need assertion updates
- `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` — current ~30 tests; only `mock_driver` fixture changes affect them
- `tests/tools/scraping/test_driver_context.py` — current `TestDriverRegistry` + `TestDriverContext`

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-tools/tests/scraping/ -v` passes (all updated tests).
- [ ] `pytest tests/tools/scraping/ -v` passes (driver_context + new selenium adapter tests).
- [ ] New `test_executor_parity_selenium_vs_playwright_mock` test exists and asserts identical call sequences across two `RecordingDriver` instances.
- [ ] New `test_selenium_factory_returns_abstract_driver` exists and asserts `isinstance(driver, AbstractDriver)`.
- [ ] No test imports `from selenium...` for the purpose of mocking — all driver mocking goes through `AbstractDriver`.

---

## Test Specification

(Tests ARE the deliverable in this task — see Implementation Notes above for the canonical patterns.)

---

## Agent Instructions

1. Read spec Module 6 + Acceptance Criteria.
2. Confirm TASK-727/728/729/730/731 are complete.
3. Update fixtures, run suites incrementally (`-x` to fail fast), iterate on assertions until green.
4. Add the parity test last so failure points clearly to either executor or driver code.
5. Move file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*
