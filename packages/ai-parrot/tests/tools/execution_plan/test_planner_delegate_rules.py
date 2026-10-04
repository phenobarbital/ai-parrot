"""FEAT-590 AC13: delegate rules only when delegates are configured."""

from __future__ import annotations

from typing import Any

from parrot.clients.base import AbstractClient
from parrot.tools.execution_plan.planner import PlanPlanner


class _FakeClient(AbstractClient):
    """Minimal client accepted by ``PlanPlanner`` without network access."""

    async def get_client(self) -> Any:
        return self

    async def ask(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def test_planner_rules_only_with_delegates() -> None:
    """Default planner prompts do not teach the delegate node type."""
    planner = PlanPlanner(_FakeClient(), [])

    assert '"type": "delegate"' not in planner._rules()


def test_delegate_rules_list_safe_tools() -> None:
    """Enabled delegate rules include sorted safe names and the configured limit."""
    planner = PlanPlanner(
        _FakeClient(),
        [],
        delegate_safe_tools=["write_report", "lookup_report"],
        delegate_max_tools=3,
    )

    rules = planner._rules()

    assert '"type": "delegate"' in rules
    assert "Delegate-safe tools: lookup_report, write_report." in rules
    assert "1..3 names" in rules
    assert "above 3" in rules


def test_repair_prompt_also_carries_rules() -> None:
    """Repair prompts include delegate guidance whenever it is enabled."""
    planner = PlanPlanner(_FakeClient(), [], delegate_safe_tools=["lookup_report"])

    prompt = planner._repair_prompt({}, object())

    assert '"type": "delegate"' in prompt
    assert "Delegate-safe tools: lookup_report." in prompt
