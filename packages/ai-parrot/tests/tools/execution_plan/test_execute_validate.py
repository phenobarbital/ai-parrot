"""Unit tests for ``plan_execute``/``plan_validate`` — acquisition front and
pipeline wiring (TASK-2184).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from parrot.clients.base import AbstractClient
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit
from parrot.tools.working_memory.tool import WorkingMemoryToolkit


class _FakeToolManager:
    def __init__(self, tools: Dict[str, Any]) -> None:
        self._tools = tools
        self.calls: List[tuple] = []

    def get_tool(self, name: str) -> Optional[Any]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools)

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional[Any] = None,
    ) -> Any:
        self.calls.append((tool_name, dict(parameters)))
        payload = self._tools[tool_name]
        return payload(parameters) if callable(payload) else payload


class _ScriptedPlannerClient(AbstractClient):
    """AbstractClient double returning scripted `ask()` responses."""

    def __init__(self, responses: List[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._responses = list(responses)
        self.calls: List[str] = []

    async def get_client(self) -> Any:
        return self

    async def __aenter__(self) -> "_ScriptedPlannerClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        return SimpleNamespace(output=self._responses.pop(0))

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.fixture
def wm_toolkit() -> WorkingMemoryToolkit:
    return WorkingMemoryToolkit()


@pytest.fixture
def manager() -> _FakeToolManager:
    return _FakeToolManager({"fast": {"ok": True}})


@pytest.fixture
def plans_dir(tmp_path: Path) -> Path:
    valid_plan = {
        "name": "valid_sweep",
        "objective": "a valid file plan",
        "nodes": [{"id": "n1", "tool": "fast", "store_as": "k1"}],
    }
    (tmp_path / "valid_sweep.json").write_text(json.dumps(valid_plan))

    invalid_plan = {
        "name": "invalid_sweep",
        "objective": "references an unregistered tool",
        "nodes": [{"id": "n1", "tool": "nope_not_registered", "store_as": "k1"}],
    }
    (tmp_path / "invalid_sweep.json").write_text(json.dumps(invalid_plan))
    return tmp_path


_VALID_PLAN_JSON = {
    "name": "authored_plan",
    "objective": "authored",
    "nodes": [{"id": "n1", "tool": "fast", "store_as": "k1"}],
}
_INVALID_PLAN_JSON = {
    "name": "authored_plan",
    "objective": "authored",
    "nodes": [{"id": "n1", "tool": "nope_not_registered", "store_as": "k1"}],
}


def _toolkit(manager: _FakeToolManager, wm_toolkit: WorkingMemoryToolkit, **kwargs: Any) -> ExecutionPlanToolkit:
    return ExecutionPlanToolkit(
        tool_manager=manager, working_memory=wm_toolkit, soft_timeout=5.0, **kwargs
    )


class TestArbitration:
    async def test_both_sources_error(self, manager, wm_toolkit, plans_dir) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir, planner_llm="google:x")
        result = await toolkit.plan_execute(objective="do x", plan_name="y")
        assert result.status == "error"
        assert "exactly one" in result.error

    async def test_neither_source_error(self, manager, wm_toolkit) -> None:
        toolkit = _toolkit(manager, wm_toolkit)
        result = await toolkit.plan_execute()
        assert result.status == "error"
        assert "exactly one" in result.error

    async def test_objective_without_planner_error(self, manager, wm_toolkit) -> None:
        toolkit = _toolkit(manager, wm_toolkit)  # no planner_llm configured
        result = await toolkit.plan_execute(objective="do x")
        assert result.status == "error"
        assert "planner_llm" in result.error

    async def test_plan_name_without_plans_dir_error(self, manager, wm_toolkit) -> None:
        toolkit = _toolkit(manager, wm_toolkit)  # no plans_dir configured
        result = await toolkit.plan_execute(plan_name="sweep")
        assert result.status == "error"
        assert "plans_dir" in result.error

    async def test_params_with_objective_error(self, manager, wm_toolkit) -> None:
        toolkit = _toolkit(manager, wm_toolkit, planner_llm="google:x")
        result = await toolkit.plan_execute(objective="do x", params={"date": "2026"})
        assert result.status == "error"
        assert "params" in result.error

    async def test_arbitration_checked_before_any_llm_call(
        self, manager, wm_toolkit, plans_dir
    ) -> None:
        client = _ScriptedPlannerClient([json.dumps(_VALID_PLAN_JSON)])
        toolkit = _toolkit(manager, wm_toolkit, planner_llm=client, plans_dir=plans_dir)
        await toolkit.plan_execute(objective="do x", plan_name="y")
        assert client.calls == []


class TestPlanExecute:
    async def test_plan_name_happy_path_manifest(self, manager, wm_toolkit, plans_dir) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir)
        result = await toolkit.plan_execute(plan_name="valid_sweep")
        assert result.status == "success"
        assert result.result["nodes_ok"] == 1

    async def test_plan_name_invalid_no_repair_tool_error(self, manager, wm_toolkit, plans_dir) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir)
        result = await toolkit.plan_execute(plan_name="invalid_sweep")
        assert result.status == "error"
        assert "invalid" in result.error.lower()
        assert manager.calls == []  # nothing executed

    async def test_plan_name_load_error_verbatim(self, manager, wm_toolkit, plans_dir) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir)
        result = await toolkit.plan_execute(plan_name="does_not_exist")
        assert result.status == "error"
        assert "Unknown plan" in result.error

    async def test_objective_repair_round_then_execute(self, manager, wm_toolkit) -> None:
        client = _ScriptedPlannerClient(
            [json.dumps(_INVALID_PLAN_JSON), json.dumps(_VALID_PLAN_JSON)]
        )
        toolkit = _toolkit(manager, wm_toolkit, planner_llm=client)

        result = await toolkit.plan_execute(objective="sweep reports")

        assert result.status == "success"
        assert result.result["nodes_ok"] == 1
        assert len(client.calls) == 2  # author + exactly one repair

    async def test_objective_repair_exhausted_tool_error(self, manager, wm_toolkit) -> None:
        client = _ScriptedPlannerClient(
            [json.dumps(_INVALID_PLAN_JSON), json.dumps(_INVALID_PLAN_JSON)]
        )
        toolkit = _toolkit(manager, wm_toolkit, planner_llm=client)

        result = await toolkit.plan_execute(objective="sweep reports")

        assert result.status == "error"
        assert len(client.calls) == 2  # author + exactly one repair, then give up
        assert manager.calls == []  # nothing executed

    async def test_partial_manifest_is_success(self, manager, wm_toolkit, tmp_path) -> None:
        def get(params: Dict[str, Any]) -> Dict[str, Any]:
            if params["key"] == "b":
                raise RuntimeError("boom")
            return {"ok": True}

        manager_with_fanout = _FakeToolManager(
            {"listing": {"keys": ["a", "b"]}, "get": get}
        )
        toolkit = _toolkit(manager_with_fanout, wm_toolkit, plans_dir=tmp_path)
        plan_json = {
            "name": "partial-plan",
            "objective": "induce a partial failure",
            "nodes": [
                {"id": "listing", "tool": "listing", "store_as": "listing"},
                {
                    "id": "fetch", "tool": "get", "args": {"key": "{item}"},
                    "store_as": "report_{index}", "depends_on": ["listing"],
                    "for_each": {"source": "{artifacts.listing}", "select": "keys[]"},
                },
            ],
        }
        (tmp_path / "partial-plan.json").write_text(json.dumps(plan_json))

        result = await toolkit.plan_execute(plan_name="partial-plan")

        assert result.status == "success"
        assert result.result["nodes_failed"] >= 1

    async def test_soft_timeout_from_plan_execute_returns_running_summary(
        self, manager, wm_toolkit, tmp_path
    ) -> None:
        def slow(_params: Dict[str, Any]) -> Dict[str, Any]:
            raise AssertionError("sync callable should not be reached")

        class _SlowManager(_FakeToolManager):
            async def execute_tool(self, tool_name, parameters, permission_context=None):
                self.calls.append((tool_name, dict(parameters)))
                import asyncio
                await asyncio.sleep(0.3)
                return {"ok": True}

        slow_manager = _SlowManager({"slow": {"ok": True}})
        toolkit = ExecutionPlanToolkit(
            tool_manager=slow_manager, working_memory=wm_toolkit,
            soft_timeout=0.01, plans_dir=tmp_path,
        )
        plan_json = {
            "name": "slow-plan", "objective": "slow",
            "nodes": [{"id": "n1", "tool": "slow", "store_as": "k1"}],
        }
        (tmp_path / "slow-plan.json").write_text(json.dumps(plan_json))

        result = await toolkit.plan_execute(plan_name="slow-plan")

        assert result.status == "success"
        assert result.result["status"] == "running"
        assert "run_id" in result.result
        import asyncio
        await asyncio.sleep(0.6)  # let the background run finish


class TestPlanValidate:
    async def test_dry_run_returns_plan_verbatim_and_report(
        self, manager, wm_toolkit, plans_dir
    ) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir)

        result = await toolkit.plan_validate(plan_name="valid_sweep")

        assert result.status == "success"
        assert result.result["ok"] is True
        assert result.result["plan"]["name"] == "valid_sweep"
        assert result.result["issues"] == []

    async def test_dry_run_reports_invalid_plan_without_erroring(
        self, manager, wm_toolkit, plans_dir
    ) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir)

        result = await toolkit.plan_validate(plan_name="invalid_sweep")

        assert result.status == "success"
        assert result.result["ok"] is False
        assert any(issue["code"] == "unknown_tool" for issue in result.result["issues"])

    async def test_dry_run_never_executes(self, manager, wm_toolkit, plans_dir) -> None:
        toolkit = _toolkit(manager, wm_toolkit, plans_dir=plans_dir)

        await toolkit.plan_validate(plan_name="valid_sweep")

        assert manager.calls == []
        assert toolkit._runs == {}

    async def test_dry_run_objective_mode_includes_repair_and_verbatim_plan(
        self, manager, wm_toolkit
    ) -> None:
        client = _ScriptedPlannerClient(
            [json.dumps(_INVALID_PLAN_JSON), json.dumps(_VALID_PLAN_JSON)]
        )
        toolkit = _toolkit(manager, wm_toolkit, planner_llm=client)

        result = await toolkit.plan_validate(objective="sweep reports")

        assert result.status == "success"
        assert result.result["ok"] is True
        assert result.result["plan"]["name"] == "authored_plan"
        assert len(client.calls) == 2
        assert manager.calls == []
