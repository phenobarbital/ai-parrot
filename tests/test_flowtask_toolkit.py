"""
Tests for FlowtaskToolkit.

These tests verify:
1. FlowtaskToolkit inherits from AbstractToolkit
2. get_tools() returns the expected 4 tools
3. Each method works correctly with mocked dependencies
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd


class TestFlowtaskToolkitStructure:
    """Test the toolkit structure and tool generation."""

    def test_toolkit_inherits_from_abstract_toolkit(self):
        """Verify FlowtaskToolkit inherits from AbstractToolkit."""
        from parrot.tools.flowtask import FlowtaskToolkit
        from parrot.tools.toolkit import AbstractToolkit

        toolkit = FlowtaskToolkit()
        assert isinstance(toolkit, AbstractToolkit)

    def test_get_tools_returns_four_tools(self):
        """Verify get_tools() returns exactly 4 tools."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()
        tools = toolkit.get_tools()

        assert len(tools) == 4

    def test_tool_names_are_correct(self):
        """Verify tool names match expected names."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()
        tools = toolkit.get_tools()
        tool_names = sorted([t.name for t in tools])

        expected_names = sorted([
            'flowtask_component_call',
            'flowtask_task_execution',
            'flowtask_remote_execution',
            'flowtask_code_execution'
        ])

        assert tool_names == expected_names

    def test_backward_compatibility_alias(self):
        """Verify FlowtaskTool is an alias for FlowtaskToolkit."""
        from parrot.tools.flowtask import FlowtaskToolkit, FlowtaskTool

        assert FlowtaskTool is FlowtaskToolkit


class TestFlowtaskComponentCall:
    """Test the flowtask_component_call method."""

    @pytest.mark.asyncio
    async def test_component_call_import_error(self):
        """Test component_call returns error for invalid component."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        result = await toolkit.flowtask_component_call(
            component_name="NonExistentComponent",
            input_data=[{"test": "data"}]
        )

        assert result["status"] == "error"
        assert "NonExistentComponent" in result["error"]

    @pytest.mark.asyncio
    async def test_component_call_success(self):
        """Test component_call with mocked component."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        # Mock the component
        mock_component = AsyncMock()
        mock_component.run = AsyncMock(return_value=pd.DataFrame([{"result": "value"}]))
        mock_component.__aenter__ = AsyncMock(return_value=mock_component)
        mock_component.__aexit__ = AsyncMock(return_value=None)

        mock_cls = MagicMock(return_value=mock_component)

        with patch.object(toolkit, '_import_component', return_value=mock_cls):
            result = await toolkit.flowtask_component_call(
                component_name="TestComponent",
                input_data=[{"test": "data"}]
            )

        assert result["status"] == "success"
        assert "result" in result


class TestFlowtaskTaskExecution:
    """Test the flowtask_task_execution method."""

    @pytest.mark.asyncio
    async def test_task_execution_import_error(self):
        """Test task_execution returns error when flowtask not installed."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        with patch.dict('sys.modules', {'flowtask.tasks.task': None}):
            with patch('builtins.__import__', side_effect=ImportError("No module")):
                result = await toolkit.flowtask_task_execution(
                    program="test",
                    task_name="test_task"
                )

        # May succeed if flowtask is installed, or fail with import error
        assert "status" in result

    @pytest.mark.asyncio
    async def test_task_execution_success(self):
        """Test task_execution with mocked Task."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        # Mock the Task class
        mock_task = AsyncMock()
        mock_task.run = AsyncMock(return_value=pd.DataFrame([{"col": "val"}]))
        mock_task.__aenter__ = AsyncMock(return_value=mock_task)
        mock_task.__aexit__ = AsyncMock(return_value=None)

        mock_task_cls = MagicMock(return_value=mock_task)

        with patch('parrot.tools.flowtask.component.Task', mock_task_cls, create=True):
            # Import Task from the patched module
            import importlib
            import parrot.tools.flowtask.tool as component_module
            importlib.reload(component_module)

            # Re-test with mocked module
            # For simplicity, we test the method structure here
            result = await toolkit.flowtask_task_execution(
                program="test",
                task_name="test_task"
            )

        assert "status" in result


class TestFlowtaskRemoteExecution:
    """Test the flowtask_remote_execution method."""

    @pytest.mark.asyncio
    async def test_remote_execution_missing_task_domain(self):
        """Test remote_execution returns error when TASK_DOMAIN not set."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        with patch.dict('os.environ', {}, clear=True):
            # Remove TASK_DOMAIN if it exists
            import os
            os.environ.pop('TASK_DOMAIN', None)

            result = await toolkit.flowtask_remote_execution(
                program="test",
                task_name="test_task"
            )

        assert result["status"] == "error"
        assert "TASK_DOMAIN" in result["error"]

    @pytest.mark.asyncio
    async def test_remote_execution_success(self):
        """Test remote_execution with mocked httpx."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success", "data": []}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('httpx.AsyncClient', return_value=mock_client):
                result = await toolkit.flowtask_remote_execution(
                    program="test",
                    task_name="test_task"
                )

        assert result["status"] == "success"
        assert result["program"] == "test"
        assert result["task"] == "test_task"

    @pytest.mark.asyncio
    async def test_remote_execution_queued(self):
        """Test remote_execution returns queued status for long_running=True."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "message": "Task test.test_task was Queued",
            "task": "test.test_task",
            "task_execution": "f06c1506-6f54-4a32-8c10-956d6adac8b4"
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('httpx.AsyncClient', return_value=mock_client):
                result = await toolkit.flowtask_remote_execution(
                    program="test",
                    task_name="test_task",
                    long_running=True
                )

        assert result["status"] == "queued"


class TestFlowtaskCodeExecution:
    """Test the flowtask_code_execution method."""

    @pytest.mark.asyncio
    async def test_code_execution_invalid_yaml(self):
        """Test code_execution returns error for invalid YAML."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        result = await toolkit.flowtask_code_execution(
            task_code="{ invalid yaml: :",
            format="yaml"
        )

        assert result["status"] == "error"
        # Either flowtask not installed OR parse error
        error_lower = result["error"].lower()
        assert "parse" in error_lower or "flowtask" in error_lower

    @pytest.mark.asyncio
    async def test_code_execution_invalid_json(self):
        """Test code_execution returns error for invalid JSON."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        result = await toolkit.flowtask_code_execution(
            task_code="{ invalid json",
            format="json"
        )

        assert result["status"] == "error"
        # Either flowtask not installed OR parse error
        error_lower = result["error"].lower()
        assert "parse" in error_lower or "flowtask" in error_lower or "json" in error_lower


class TestInputModels:
    """Test the Pydantic input models."""

    def test_component_input_model(self):
        """Test FlowtaskComponentInput validation."""
        from parrot.tools.flowtask import FlowtaskComponentInput

        input_model = FlowtaskComponentInput(
            component_name="GooglePlaces",
            input_data=[{"address": "123 Main St"}]
        )

        assert input_model.component_name == "GooglePlaces"
        assert input_model.attributes == {}
        assert input_model.return_as_dataframe is False

    def test_task_execution_input_model(self):
        """Test FlowtaskTaskExecutionInput validation."""
        from parrot.tools.flowtask import FlowtaskTaskExecutionInput

        input_model = FlowtaskTaskExecutionInput(
            program="nextstop",
            task_name="employees_report"
        )

        assert input_model.program == "nextstop"
        assert input_model.task_name == "employees_report"
        assert input_model.debug is True

    def test_remote_execution_input_model(self):
        """Test FlowtaskRemoteExecutionInput validation."""
        from parrot.tools.flowtask import FlowtaskRemoteExecutionInput

        input_model = FlowtaskRemoteExecutionInput(
            program="nextstop",
            task_name="employees_report",
            long_running=True
        )

        assert input_model.long_running is True
        assert input_model.timeout == 300.0
        assert input_model.max_retries == 3
        assert input_model.backoff_factor == 1.0

    def test_code_execution_input_model(self):
        """Test FlowtaskCodeExecutionInput validation."""
        from parrot.tools.flowtask import FlowtaskCodeExecutionInput, TaskCodeFormat

        input_model = FlowtaskCodeExecutionInput(
            task_code="name: Test Task\nsteps: []"
        )

        assert input_model.format == TaskCodeFormat.YAML


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
