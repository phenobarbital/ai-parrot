"""Unit tests for parrot_tools.computer.models (TASK-1475)."""
import pytest
from pydantic import ValidationError

from parrot_tools.computer.models import (
    ComputerTask,
    ComputerUseConfig,
    EnvState,
    LoopResult,
    TaskResult,
)


class TestEnvState:
    """Tests for EnvState."""

    def test_valid(self):
        state = EnvState(screenshot=b"\x89PNG...", url="https://example.com")
        assert state.screenshot == b"\x89PNG..."
        assert state.url == "https://example.com"

    def test_screenshot_bytes(self):
        state = EnvState(screenshot=b"", url="https://example.com")
        assert isinstance(state.screenshot, bytes)

    def test_missing_url_raises(self):
        with pytest.raises(ValidationError):
            EnvState(screenshot=b"\x89PNG...")  # type: ignore[call-arg]

    def test_missing_screenshot_raises(self):
        with pytest.raises(ValidationError):
            EnvState(url="https://example.com")  # type: ignore[call-arg]


class TestComputerUseConfig:
    """Tests for ComputerUseConfig."""

    def test_defaults(self):
        cfg = ComputerUseConfig()
        assert cfg.environment == "ENVIRONMENT_BROWSER"
        assert cfg.excluded_actions == []

    def test_custom_excluded(self):
        cfg = ComputerUseConfig(excluded_actions=["drag_and_drop", "record_har"])
        assert len(cfg.excluded_actions) == 2


class TestComputerTask:
    """Tests for ComputerTask."""

    def test_valid(self):
        task = ComputerTask(
            name="fill_form",
            description="Fill registration form",
            steps=["Click name field", "Type name", "Click submit"],
        )
        assert len(task.steps) == 3
        assert task.params_schema is None

    def test_with_params_schema(self):
        task = ComputerTask(
            name="search",
            description="Search for something",
            steps=["Type in search box"],
            params_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        assert task.params_schema is not None

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            ComputerTask(  # type: ignore[call-arg]
                description="No name",
                steps=["Step 1"],
            )


class TestTaskResult:
    """Tests for TaskResult."""

    def test_success(self):
        result = TaskResult(task_name="test_task", success=True)
        assert result.success is True
        assert result.screenshots == []
        assert result.error is None
        assert result.url == ""

    def test_failure(self):
        result = TaskResult(
            task_name="failing_task",
            success=False,
            error="Element not found",
        )
        assert result.success is False
        assert result.error == "Element not found"

    def test_with_screenshots(self):
        result = TaskResult(
            task_name="screenshotted",
            success=True,
            screenshots=[b"\x89PNG...", b"\x89PNG2..."],
            url="https://result.com",
        )
        assert len(result.screenshots) == 2
        assert result.url == "https://result.com"


class TestLoopResult:
    """Tests for LoopResult."""

    def test_stop_reason_count(self):
        result = LoopResult(
            task_name="test",
            iterations_completed=3,
            stop_reason="count",
            results=[],
            errors=[],
        )
        assert result.stop_reason == "count"

    def test_stop_reason_condition_met(self):
        result = LoopResult(
            task_name="test",
            iterations_completed=2,
            stop_reason="condition_met",
        )
        assert result.stop_reason == "condition_met"

    def test_stop_reason_max_reached(self):
        result = LoopResult(
            task_name="test",
            iterations_completed=100,
            stop_reason="max_reached",
        )
        assert result.stop_reason == "max_reached"

    def test_stop_reason_aborted(self):
        result = LoopResult(
            task_name="test",
            iterations_completed=0,
            stop_reason="aborted",
        )
        assert result.stop_reason == "aborted"

    def test_stop_reason_error(self):
        result = LoopResult(
            task_name="test",
            iterations_completed=1,
            stop_reason="error",
            errors=["Connection refused"],
        )
        assert result.stop_reason == "error"
        assert result.errors == ["Connection refused"]

    def test_invalid_stop_reason(self):
        with pytest.raises(ValidationError):
            LoopResult(
                task_name="test",
                iterations_completed=0,
                stop_reason="invalid_reason",  # type: ignore[arg-type]
            )
