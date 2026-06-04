"""Tests for advanced_actions — Loop / Conditional / template substitution.

FEAT-222 TASK-1445.
"""
from unittest.mock import AsyncMock

from parrot_tools.scraping.advanced_actions import (
    exec_conditional,
    exec_loop,
    substitute_template_vars,
)
from parrot_tools.scraping.models import Conditional, Loop


# ── substitute_template_vars ──────────────────────────────────────────

class TestSubstituteTemplateVars:
    def test_simple_index(self):
        assert substitute_template_vars("item-{i}", 3) == "item-3"

    def test_index_alias(self):
        assert substitute_template_vars("p-{index}", 2) == "p-2"

    def test_iteration_alias(self):
        assert substitute_template_vars("it-{iteration}", 4) == "it-4"

    def test_start_index_offset(self):
        assert substitute_template_vars("item-{i}", 0, start_index=5) == "item-5"

    def test_arithmetic_plus(self):
        assert substitute_template_vars("page-{i+1}", 0) == "page-1"

    def test_arithmetic_minus(self):
        assert substitute_template_vars("page-{i-1}", 3) == "page-2"

    def test_arithmetic_mult(self):
        assert substitute_template_vars("n-{i*2}", 3) == "n-6"

    def test_arithmetic_index_token(self):
        assert substitute_template_vars("page-{index+1}", 0) == "page-1"

    def test_value_substitution(self):
        result = substitute_template_vars(
            "{value}", 0, values=["a", "b"], value_name="value"
        )
        assert result == "a"

    def test_custom_value_name(self):
        result = substitute_template_vars(
            "city-{town}", 1, values=["NYC", "LA"], value_name="town"
        )
        assert result == "city-LA"

    def test_nested_dict(self):
        result = substitute_template_vars({"url": "page-{i}", "count": 5}, 2)
        assert result == {"url": "page-2", "count": 5}

    def test_nested_list(self):
        result = substitute_template_vars(["item-{i}", "other"], 1)
        assert result == ["item-1", "other"]

    def test_scalar_passthrough(self):
        assert substitute_template_vars(42, 1) == 42
        assert substitute_template_vars(None, 1) is None
        assert substitute_template_vars(True, 1) is True

    def test_invalid_expr_kept(self):
        # Non-evaluable expression containing 'i' is left untouched.
        assert substitute_template_vars("{i+}", 1) == "{i+}"


# ── exec_loop ─────────────────────────────────────────────────────────

class TestExecLoop:
    async def test_fixed_iterations(self):
        driver = AsyncMock()
        dispatch = AsyncMock(return_value=True)
        action = Loop(
            actions=[{"action": "click", "selector": ".btn"}], iterations=3
        )
        result = await exec_loop(driver, action, dispatch)
        assert result is True
        assert dispatch.call_count == 3

    async def test_values_list_iteration(self):
        driver = AsyncMock()
        seen_selectors = []

        async def dispatch(d, step, url, timeout, extracted):
            seen_selectors.append(step.action.selector)
            return True

        action = Loop(
            actions=[{"action": "click", "selector": "{value}"}],
            values=["a", "b", "c"],
        )
        result = await exec_loop(driver, action, dispatch)
        assert result is True
        assert seen_selectors == ["a", "b", "c"]

    async def test_template_substitution_in_action(self):
        driver = AsyncMock()
        seen = []

        async def dispatch(d, step, url, timeout, extracted):
            seen.append(step.action.url)
            return True

        action = Loop(
            actions=[{"action": "navigate", "url": "https://x.com/page-{i+1}"}],
            iterations=2,
        )
        await exec_loop(driver, action, dispatch)
        assert seen == ["https://x.com/page-1", "https://x.com/page-2"]

    async def test_break_on_error(self):
        driver = AsyncMock()
        dispatch = AsyncMock(side_effect=[True, False])
        action = Loop(
            actions=[{"action": "click", "selector": ".btn"}],
            iterations=5,
            break_on_error=True,
        )
        result = await exec_loop(driver, action, dispatch)
        assert result is False
        assert dispatch.call_count == 2

    async def test_no_break_on_error_continues(self):
        driver = AsyncMock()
        dispatch = AsyncMock(return_value=False)
        action = Loop(
            actions=[{"action": "click", "selector": ".btn"}],
            iterations=3,
            break_on_error=False,
        )
        result = await exec_loop(driver, action, dispatch)
        assert result is True
        assert dispatch.call_count == 3

    async def test_condition_stops_loop(self):
        driver = AsyncMock()
        # Condition evaluates False → loop body never runs.
        driver.evaluate = AsyncMock(return_value=False)
        dispatch = AsyncMock(return_value=True)
        action = Loop(
            actions=[{"action": "click", "selector": ".btn"}],
            iterations=5,
            condition="document.querySelector('.next')",
        )
        result = await exec_loop(driver, action, dispatch)
        assert result is True
        assert dispatch.call_count == 0

    async def test_condition_true_runs(self):
        driver = AsyncMock()
        driver.evaluate = AsyncMock(return_value=True)
        dispatch = AsyncMock(return_value=True)
        action = Loop(
            actions=[{"action": "click", "selector": ".btn"}],
            iterations=2,
            condition="true",
        )
        result = await exec_loop(driver, action, dispatch)
        assert result is True
        assert dispatch.call_count == 2


# ── exec_conditional ──────────────────────────────────────────────────

class TestExecConditional:
    async def test_exists_true_branch(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock()  # resolves → element exists
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".element",
            condition_type="exists",
            expected_value="true",
            actions_if_true=[{"action": "click", "selector": ".btn"}],
        )
        result = await exec_conditional(driver, action, dispatch)
        assert result is True
        assert dispatch.call_count == 1

    async def test_not_exists_false_branch(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock(side_effect=Exception("not found"))
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".element",
            condition_type="exists",
            expected_value="true",
            actions_if_true=[{"action": "click", "selector": ".yes"}],
            actions_if_false=[{"action": "click", "selector": ".no"}],
        )
        await exec_conditional(driver, action, dispatch)
        # Element missing → false branch dispatched.
        assert dispatch.call_count == 1
        assert dispatch.call_args[0][1].action.selector == ".no"

    async def test_not_exists_condition(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock(side_effect=Exception("not found"))
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".gone",
            condition_type="not_exists",
            expected_value="true",
            actions_if_true=[{"action": "click", "selector": ".ok"}],
        )
        await exec_conditional(driver, action, dispatch)
        assert dispatch.call_count == 1

    async def test_text_contains(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock()
        driver.get_text = AsyncMock(return_value="Hello World")
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".msg",
            condition_type="text_contains",
            expected_value="World",
            actions_if_true=[{"action": "click", "selector": ".ok"}],
        )
        await exec_conditional(driver, action, dispatch)
        assert dispatch.call_count == 1

    async def test_text_equals_false(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock()
        driver.get_text = AsyncMock(return_value="Hello")
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".msg",
            condition_type="text_equals",
            expected_value="Goodbye",
            actions_if_true=[{"action": "click", "selector": ".ok"}],
        )
        await exec_conditional(driver, action, dispatch)
        # Text mismatch, no false branch → nothing dispatched.
        assert dispatch.call_count == 0

    async def test_attribute_equals(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock()
        driver.get_attribute = AsyncMock(return_value="active")
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".tab",
            condition_type="attribute_equals",
            expected_value="class=active",
            actions_if_true=[{"action": "click", "selector": ".ok"}],
        )
        await exec_conditional(driver, action, dispatch)
        assert dispatch.call_count == 1

    async def test_unknown_condition_returns_false(self):
        driver = AsyncMock()
        driver.wait_for_selector = AsyncMock()
        dispatch = AsyncMock(return_value=True)
        action = Conditional(
            target=".x",
            condition_type="exists",
            expected_value="true",
        )
        # Force an unknown condition_type past validation.
        object.__setattr__(action, "condition_type", "bogus")
        result = await exec_conditional(driver, action, dispatch)
        assert result is False
        assert dispatch.call_count == 0
