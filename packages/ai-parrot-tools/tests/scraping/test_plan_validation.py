"""Tests for ScrapingPlan.validate_steps() (Module 3, Goal G2).

FEAT-453 TASK-2388.
"""
import pytest
from parrot_tools.scraping.models import BrowserAction
from parrot_tools.scraping.plan import ScrapingPlan


class TestValidateSteps:
    def test_valid_plan_returns_typed_actions(self):
        plan = ScrapingPlan(
            url="http://x/", objective="t",
            steps=[{"action": "navigate", "url": "http://x/"}],
        )
        actions = plan.validate_steps()
        assert actions[0].get_action_type() == "navigate"
        assert isinstance(actions[0], BrowserAction)

    def test_valid_plan_multiple_steps(self):
        plan = ScrapingPlan(
            url="http://x/", objective="t",
            steps=[
                {"action": "navigate", "url": "http://x/"},
                {"action": "click", "selector": "#go"},
                {"action": "get_cookies"},
            ],
        )
        actions = plan.validate_steps()
        assert [a.get_action_type() for a in actions] == ["navigate", "click", "get_cookies"]

    def test_unknown_action_raises_with_index(self):
        plan = ScrapingPlan(
            url="http://x/", objective="t",
            steps=[{"action": "navigate", "url": "http://x/"}, {"action": "teleport"}],
        )
        with pytest.raises(ValueError, match=r"step 1"):
            plan.validate_steps()

    def test_missing_required_field_raises(self):
        plan = ScrapingPlan(
            url="http://x/", objective="t",
            steps=[{"action": "upload_file", "selector": "#f"}],
        )
        with pytest.raises(ValueError, match="file_path"):
            plan.validate_steps()

    def test_construction_does_not_validate(self):
        # Must not raise — validation is opt-in only.
        ScrapingPlan(url="http://x/", objective="t", steps=[{"action": "bogus"}])

    def test_strict_false_collects_all_errors(self):
        plan = ScrapingPlan(
            url="http://x/", objective="t",
            steps=[
                {"action": "teleport"},
                {"action": "upload_file", "selector": "#f"},
                {"action": "navigate", "url": "http://x/"},
            ],
        )
        with pytest.raises(ValueError) as excinfo:
            plan.validate_steps(strict=False)
        message = str(excinfo.value)
        assert "step 0" in message
        assert "step 1" in message
        assert "step 2" not in message  # the valid step must not be reported

    def test_strict_true_raises_on_first_error_only(self):
        plan = ScrapingPlan(
            url="http://x/", objective="t",
            steps=[{"action": "teleport"}, {"action": "upload_file", "selector": "#f"}],
        )
        with pytest.raises(ValueError) as excinfo:
            plan.validate_steps(strict=True)
        assert "step 0" in str(excinfo.value)
        assert "step 1" not in str(excinfo.value)

    def test_empty_steps_returns_empty_list(self):
        plan = ScrapingPlan(url="http://x/", objective="t", steps=[])
        assert plan.validate_steps() == []
