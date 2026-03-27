"""Tests for SystemHealthTool."""

import asyncio
import pytest

from parrot.tools.system_health.tool import (
    HealthCategory,
    SystemHealthArgs,
    SystemHealthTool,
)
from parrot.tools.abstract import ToolResult


# ── Schema tests ────────────────────────────────────────────────

def test_args_default_category():
    args = SystemHealthArgs()
    assert args.category == HealthCategory.ALL


def test_args_specific_category():
    args = SystemHealthArgs(category="cpu")
    assert args.category == HealthCategory.CPU


def test_args_invalid_category():
    with pytest.raises(ValueError):
        SystemHealthArgs(category="invalid_garbage")


# ── Tool metadata ──────────────────────────────────────────────

def test_tool_schema():
    tool = SystemHealthTool()
    schema = tool.get_schema()
    assert schema["name"] == "system_health"
    assert "category" in schema["parameters"]["properties"]


# ── Collector unit tests (real psutil, no mocking) ─────────────

@pytest.mark.asyncio
async def test_collect_cpu():
    tool = SystemHealthTool()
    result = tool._collect_cpu()
    assert "physical_cores" in result
    assert "logical_cores" in result
    assert "usage_per_core_pct" in result
    assert isinstance(result["usage_per_core_pct"], list)
    assert "load_avg_1m_5m_15m" in result


@pytest.mark.asyncio
async def test_collect_memory():
    tool = SystemHealthTool()
    result = tool._collect_memory()
    assert "ram" in result
    assert "swap" in result
    ram = result["ram"]
    assert ram["total_gb"] > 0
    assert 0 <= ram["percent"] <= 100


@pytest.mark.asyncio
async def test_collect_disk():
    tool = SystemHealthTool()
    result = tool._collect_disk()
    assert isinstance(result, list)
    assert len(result) > 0
    part = result[0]
    assert "mountpoint" in part
    assert "total_gb" in part
    assert "percent" in part


@pytest.mark.asyncio
async def test_collect_network():
    tool = SystemHealthTool()
    result = tool._collect_network()
    assert isinstance(result, dict)
    # At least loopback should exist
    assert len(result) > 0
    iface = next(iter(result.values()))
    assert "bytes_sent_mb" in iface
    assert "bytes_recv_mb" in iface


@pytest.mark.asyncio
async def test_collect_processes():
    tool = SystemHealthTool()
    result = tool._collect_processes()
    assert "total_count" in result
    assert result["total_count"] > 0
    assert "top_by_cpu" in result
    assert "top_by_memory" in result
    # No PIDs exposed
    for proc in result["top_by_cpu"]:
        assert "pid" not in proc
        assert "name" in proc


@pytest.mark.asyncio
async def test_collect_system():
    tool = SystemHealthTool()
    result = tool._collect_system()
    assert "hostname" in result
    assert "platform" in result
    assert "uptime" in result
    assert "uptime_seconds" in result
    assert result["uptime_seconds"] > 0


@pytest.mark.asyncio
async def test_collect_docker():
    tool = SystemHealthTool()
    result = await tool._collect_docker()
    assert "available" in result
    if result["available"]:
        assert "running_count" in result
        assert "containers" in result


# ── Integration: execute via the public API ────────────────────

@pytest.mark.asyncio
async def test_execute_all():
    tool = SystemHealthTool()
    result = await tool.execute(category="all")
    assert isinstance(result, ToolResult)
    assert result.success is True
    data = result.result
    for key in ("cpu", "memory", "disk", "network", "processes", "system", "docker"):
        assert key in data, f"Missing section: {key}"


@pytest.mark.asyncio
async def test_execute_single_category():
    tool = SystemHealthTool()
    result = await tool.execute(category="cpu")
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "physical_cores" in result.result


@pytest.mark.asyncio
async def test_execute_memory():
    tool = SystemHealthTool()
    result = await tool.execute(category="memory")
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "ram" in result.result
