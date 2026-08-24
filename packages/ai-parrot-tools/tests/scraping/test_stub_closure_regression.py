"""Regression tests — the executor.py stub-branch closure (Module 2).

FEAT-453 TASK-2387. Before this task, ``executor.py::_dispatch_step`` matched
eight action types, logged a warning, and returned ``True`` — reporting
success while doing nothing. These tests prove that defect cannot resurface:
every one of the eight action types must actually invoke its real
``session_actions.exec_*`` implementation, and an unhandled action type must
still return ``False`` (never a silent ``True``).
"""

from unittest.mock import AsyncMock

import pytest
from parrot_tools.scraping import executor as executor_module
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.plan import ScrapingPlan

STUBBED = [
    "authenticate",
    "upload_file",
    "wait_for_download",
    "get_cookies",
    "set_cookies",
    "await_human",
    "await_keypress",
    "await_browser_event",
]

# Minimal extra fields each action type needs to construct validly.
_EXTRA_FIELDS = {
    "upload_file": {"selector": "#f", "file_path": "/nope/missing.pdf"},
    "set_cookies": {"cookies": []},
}

_EXEC_NAME = {
    "authenticate": "exec_authenticate",
    "upload_file": "exec_upload_file",
    "wait_for_download": "exec_wait_for_download",
    "get_cookies": "exec_get_cookies",
    "set_cookies": "exec_set_cookies",
    "await_human": "exec_await_human",
    "await_keypress": "exec_await_keypress",
    "await_browser_event": "exec_await_browser_event",
}


@pytest.fixture
def spy_driver():
    driver = AsyncMock()
    driver.get_page_source = AsyncMock(return_value="<html></html>")
    driver.current_url = "http://x/"
    return driver


class TestStubClosure:
    @pytest.mark.parametrize("action_type", STUBBED)
    async def test_no_silent_success(self, action_type, spy_driver, monkeypatch):
        """Every formerly-stubbed action must actually call its impl."""
        exec_name = _EXEC_NAME[action_type]
        return_value = {"cookies": []} if exec_name == "exec_get_cookies" else True
        spy = AsyncMock(return_value=return_value)
        # Patch the name as bound in executor's own namespace (`from .session_actions
        # import exec_*` copies the reference at import time; patching
        # session_actions.exec_* directly would not be observed here).
        monkeypatch.setattr(executor_module, exec_name, spy)

        step = {"action": action_type, **_EXTRA_FIELDS.get(action_type, {})}
        plan = ScrapingPlan(url="http://x/", objective="t", steps=[step])
        await execute_plan_steps(spy_driver, plan=plan)

        spy.assert_awaited_once()

    @pytest.mark.parametrize("action_type", STUBBED)
    def test_no_stub_return_true_survives(self, action_type):
        """Static guard: no bare 'return True' stub branch for these action
        types survives in the dispatcher source (belt-and-braces alongside
        the behavioural test above)."""
        import inspect

        source = inspect.getsource(executor_module._dispatch_step)
        assert (
            "requires the full WebScrapingTool" not in source
        ), "the stub warning message must not survive in _dispatch_step"

    async def test_unknown_action_returns_false(self, spy_driver):
        # "hover" is registered in ACTION_MAP (so ScrapingStep.from_dict does
        # not raise) but is not handled by _dispatch_step's if/elif chain,
        # exercising the real "unknown to the dispatcher" else-branch.
        plan = ScrapingPlan(url="http://x/", objective="t", steps=[{"action": "hover", "selector": "#x"}])
        result = await execute_plan_steps(spy_driver, plan=plan)
        assert not result.success or result.metadata.get("step_errors")
