"""Unit tests for result size policy + per-call deadline (FEAT-477, TASK-2606)."""

import asyncio
import json

import pytest
from parrot.mcp.config import AgentMCPMountConfig
from parrot.mcp.result_policy import (
    MCPToolError,
    apply_size_policy,
    resolve_cap,
    run_with_deadline,
)


class _Decl:
    def __init__(self, max_result_tokens=None):
        self.max_result_tokens = max_result_tokens


class _Cfg:
    def __init__(self, max_result_tokens=25_000):
        self.max_result_tokens = max_result_tokens


@pytest.fixture
def huge_list_result():
    return [{"id": i, "value": "x" * 40} for i in range(500)]


@pytest.fixture
def result_with_nones():
    return {"a": 1, "b": None, "items": [{"x": 1, "y": None}, {"x": 2, "y": None}]}


class TestResultPolicy:
    def test_per_tool_cap_overrides_mount_default(self):
        assert resolve_cap(_Decl(100), _Cfg(25_000)) == 100

    def test_falls_back_to_mount_default_when_no_per_tool_cap(self):
        assert resolve_cap(_Decl(None), _Cfg(25_000)) == 25_000

    def test_falls_back_to_hardcoded_default_when_neither_set(self):
        from parrot.mcp.result_policy import DEFAULT_MAX_RESULT_TOKENS

        assert resolve_cap(None, None) == DEFAULT_MAX_RESULT_TOKENS

    def test_truncation_states_itself(self, huge_list_result):
        out = apply_size_policy(huge_list_result, cap=100)
        assert out["truncated"] is True
        assert "truncated" in json.dumps(out).lower()
        assert out["returned_count"] < out["total_count"] == len(huge_list_result)

    def test_truncation_is_deterministic(self, huge_list_result):
        a = apply_size_policy(huge_list_result, cap=100)
        b = apply_size_policy(huge_list_result, cap=100)
        assert a == b

    def test_small_result_is_not_truncated(self):
        out = apply_size_policy({"ok": True}, cap=10_000)
        assert out["truncated"] is False
        assert out["result"] == {"ok": True}

    def test_exclude_none_applied(self, result_with_nones):
        out = apply_size_policy(result_with_nones, cap=10_000)
        assert "null" not in json.dumps(out["result"])
        assert "b" not in out["result"]
        assert all("y" not in item for item in out["result"]["items"])

    def test_oversized_non_list_result_truncates_as_string(self):
        big_string_result = "x" * 10_000
        out = apply_size_policy(big_string_result, cap=10)
        assert out["truncated"] is True
        assert isinstance(out["result"], str)
        assert len(out["result"]) < len(json.dumps(big_string_result))

    async def test_call_deadline_names_the_method(self):
        async def slow_method():
            await asyncio.sleep(1)

        with pytest.raises(MCPToolError, match="slow_forecast"):
            await run_with_deadline(slow_method, deadline=0.05, name="slow_forecast")

    async def test_call_completes_within_deadline(self):
        async def fast_method():
            return {"ok": True}

        result = await run_with_deadline(fast_method, deadline=5.0, name="fast")
        assert result == {"ok": True}

    def test_deadline_below_client_ceiling(self):
        cfg = AgentMCPMountConfig(agents=["a"], resource_server_url="https://h/x")
        assert cfg.call_deadline_seconds < 300
