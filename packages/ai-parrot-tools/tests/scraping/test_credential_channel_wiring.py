"""Tests for the credential_resolver/channel wiring through the real
dispatch path (FEAT-453 code-review remediation, AC-5).

Before this remediation, ``exec_authenticate``/``exec_await_human`` already
accepted ``credential_resolver``/``channel`` (TASK-2384/2385/2389), but
``execute_plan_steps``/``_dispatch_step`` never forwarded them — a
``credential_provider``-backed ``Authenticate`` or a mid-plan ``await_human``
was unreachable from ``BusinessAutomationToolkit.run_operation()`` no matter
how the toolkit was configured. These tests prove the wiring now reaches
every dispatch site, including the recursive loop/conditional/oauth
closures inside ``_dispatch_step``.
"""

from unittest.mock import AsyncMock

import pytest
from parrot_tools.scraping import executor as executor_module
from parrot_tools.scraping.executor import _dispatch_step, execute_plan_steps
from parrot_tools.scraping.models import ScrapingStep
from parrot_tools.scraping.plan import ScrapingPlan


@pytest.fixture
def spy_driver():
    driver = AsyncMock()
    driver.get_page_source = AsyncMock(return_value="<html></html>")
    driver.current_url = "http://x/"
    return driver


class TestExecutePlanStepsForwarding:
    async def test_forwards_credential_resolver_to_authenticate(self, spy_driver, monkeypatch):
        spy = AsyncMock(return_value=True)
        monkeypatch.setattr(executor_module, "exec_authenticate", spy)
        resolver = AsyncMock(return_value=("user", "pass"))

        plan = ScrapingPlan(url="http://x/", objective="t", steps=[{"action": "authenticate"}])
        await execute_plan_steps(spy_driver, plan=plan, credential_resolver=resolver)

        spy.assert_awaited_once()
        _, kwargs = spy.await_args
        assert kwargs["credential_resolver"] is resolver

    async def test_forwards_channel_to_await_human(self, spy_driver, monkeypatch):
        spy = AsyncMock(return_value=True)
        monkeypatch.setattr(executor_module, "exec_await_human", spy)
        channel = object()

        plan = ScrapingPlan(
            url="http://x/",
            objective="t",
            steps=[{"action": "await_human", "condition_type": "manual"}],
        )
        await execute_plan_steps(spy_driver, plan=plan, channel=channel)

        spy.assert_awaited_once()
        _, kwargs = spy.await_args
        assert kwargs["channel"] is channel

    async def test_defaults_to_none_when_not_supplied(self, spy_driver, monkeypatch):
        """Backward compatibility: callers that never pass these kwargs
        (every pre-existing caller) must still resolve to None, not raise."""
        auth_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(executor_module, "exec_authenticate", auth_spy)

        plan = ScrapingPlan(url="http://x/", objective="t", steps=[{"action": "authenticate"}])
        await execute_plan_steps(spy_driver, plan=plan)

        _, kwargs = auth_spy.await_args
        assert kwargs["credential_resolver"] is None


class TestDispatchStepForwardsThroughRecursiveClosures:
    """``_dispatch_step``'s ``loop``/``conditional``/``authenticate`` branches
    each build a recursive ``_dispatch`` closure forwarding this call's own
    ``credential_resolver``/``channel`` to the nested ``_dispatch_step`` call
    (so a nested authenticate/await_human is never silently downgraded to
    ``None`` just because it is inside one of these). Each test captures the
    ``dispatch_step_fn`` the real ``exec_loop``/``exec_conditional``/
    ``exec_authenticate`` would call, then invokes it directly with a nested
    step — decoupled from those functions' own condition/iteration/method
    semantics, which are already covered elsewhere.
    """

    async def test_loop_closure_forwards_credential_resolver(self, spy_driver, monkeypatch):
        auth_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(executor_module, "exec_authenticate", auth_spy)

        captured = {}

        async def _fake_exec_loop(driver, action, dispatch_fn, base_url, timeout):
            captured["dispatch_fn"] = dispatch_fn
            return True

        monkeypatch.setattr(executor_module, "exec_loop", _fake_exec_loop)

        resolver = AsyncMock(return_value=("user", "pass"))
        step = ScrapingStep.from_dict({"action": "loop", "actions": []})
        await _dispatch_step(spy_driver, step, "http://x/", 10, {}, credential_resolver=resolver)

        nested_step = ScrapingStep.from_dict({"action": "authenticate"})
        await captured["dispatch_fn"](spy_driver, nested_step, "http://x/", 10, {})

        auth_spy.assert_awaited_once()
        _, kwargs = auth_spy.await_args
        assert kwargs["credential_resolver"] is resolver

    async def test_conditional_closure_forwards_channel(self, spy_driver, monkeypatch):
        human_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(executor_module, "exec_await_human", human_spy)

        captured = {}

        async def _fake_exec_conditional(driver, action, dispatch_fn, base_url, timeout):
            captured["dispatch_fn"] = dispatch_fn
            return True

        monkeypatch.setattr(executor_module, "exec_conditional", _fake_exec_conditional)

        channel = object()
        step = ScrapingStep.from_dict({"action": "conditional", "expected_value": "true"})
        await _dispatch_step(spy_driver, step, "http://x/", 10, {}, channel=channel)

        nested_step = ScrapingStep.from_dict({"action": "await_human", "condition_type": "manual"})
        await captured["dispatch_fn"](spy_driver, nested_step, "http://x/", 10, {})

        human_spy.assert_awaited_once()
        _, kwargs = human_spy.await_args
        assert kwargs["channel"] is channel

    async def test_authenticate_closure_forwards_channel_to_custom_steps(self, spy_driver, monkeypatch):
        human_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(executor_module, "exec_await_human", human_spy)

        captured = {}

        async def _fake_exec_authenticate(driver, action, dispatch_fn, *, credential_resolver=None, timeout=30):
            captured["dispatch_fn"] = dispatch_fn
            return True

        monkeypatch.setattr(executor_module, "exec_authenticate", _fake_exec_authenticate)

        channel = object()
        step = ScrapingStep.from_dict({"action": "authenticate", "method": "custom"})
        await _dispatch_step(spy_driver, step, "http://x/", 10, {}, channel=channel)

        nested_step = ScrapingStep.from_dict({"action": "await_human", "condition_type": "manual"})
        await captured["dispatch_fn"](spy_driver, nested_step, "http://x/", 10, {})

        human_spy.assert_awaited_once()
        _, kwargs = human_spy.await_args
        assert kwargs["channel"] is channel
