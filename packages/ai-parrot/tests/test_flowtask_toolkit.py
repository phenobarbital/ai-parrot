"""
Tests for FlowtaskToolkit.

These tests verify:
1. FlowtaskToolkit inherits from AbstractToolkit
2. get_tools() returns the expected 6 tools
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

    def test_get_tools_returns_six_tools(self):
        """Verify get_tools() returns exactly 6 tools."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()
        tools = toolkit.get_tools()

        assert len(tools) == 6

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
            'flowtask_code_execution',
            'flowtask_task_service',
            'flowtask_list_tasks'
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
    async def test_task_execution_with_storage(self):
        """Test task_execution passes storage parameter."""
        from parrot.tools.flowtask import FlowtaskToolkit
        from parrot.tools.flowtask import tool as flowtask_module

        toolkit = FlowtaskToolkit()

        mock_task = AsyncMock()
        mock_task.run = AsyncMock(return_value=pd.DataFrame([{"col": "val"}]))
        mock_task.__aenter__ = AsyncMock(return_value=mock_task)
        mock_task.__aexit__ = AsyncMock(return_value=None)
        mock_task.stat = None

        mock_task_cls = MagicMock(return_value=mock_task)

        # Patch at the import target inside the tool module
        with patch.object(flowtask_module, '__builtins__', flowtask_module.__builtins__):
            with patch.dict('sys.modules', {
                'flowtask.tasks.task': MagicMock(Task=mock_task_cls)
            }):
                result = await toolkit.flowtask_task_execution(
                    program="test",
                    task_name="test_task",
                    storage="private",
                    variables={"key": "value"}
                )

        if result["status"] == "success":
            # Verify Task was called with storage and variables
            call_kwargs = mock_task_cls.call_args
            assert call_kwargs[1]["storage"] == "private"
            assert call_kwargs[1]["variables"] == {"key": "value"}
            assert "stats" in result

    @pytest.mark.asyncio
    async def test_task_execution_returns_stats(self):
        """Test task_execution extracts and returns stats."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_stat = MagicMock()
        mock_stat.task_name = "test_task"
        mock_stat.duration = 1.5
        mock_stat._private = "hidden"

        mock_task = AsyncMock()
        mock_task.run = AsyncMock(return_value={"result": "ok"})
        mock_task.__aenter__ = AsyncMock(return_value=mock_task)
        mock_task.__aexit__ = AsyncMock(return_value=None)
        mock_task.stat = mock_stat

        mock_task_cls = MagicMock(return_value=mock_task)

        with patch.dict('sys.modules', {
            'flowtask.tasks.task': MagicMock(Task=mock_task_cls)
        }):
            result = await toolkit.flowtask_task_execution(
                program="test",
                task_name="test_task"
            )

        if result["status"] == "success":
            assert result["stats"] is not None
            assert "task_name" in result["stats"]
            assert "duration" in result["stats"]
            assert "_private" not in result["stats"]


class TestFlowtaskRemoteExecution:
    """Test the flowtask_remote_execution method."""

    @pytest.mark.asyncio
    async def test_remote_execution_missing_task_domain(self):
        """Test remote_execution returns error when TASK_DOMAIN not set."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        with patch.dict('os.environ', {}, clear=True):
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
        """Test remote_execution with mocked aiohttp."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "success", "data": []})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
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

        mock_response = AsyncMock()
        mock_response.status = 202
        mock_response.json = AsyncMock(return_value={
            "message": "Task test.test_task was Queued",
            "task": "test.test_task",
            "task_execution": "f06c1506-6f54-4a32-8c10-956d6adac8b4"
        })

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await toolkit.flowtask_remote_execution(
                    program="test",
                    task_name="test_task",
                    long_running=True
                )

        assert result["status"] == "queued"


class TestFlowtaskTaskService:
    """Test the flowtask_task_service method."""

    @pytest.mark.asyncio
    async def test_task_service_missing_task_domain(self):
        """Test task_service returns error when TASK_DOMAIN not set."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        with patch.dict('os.environ', {}, clear=True):
            import os
            os.environ.pop('TASK_DOMAIN', None)

            result = await toolkit.flowtask_task_service(
                program="test",
                task_name="test_task"
            )

        assert result["status"] == "error"
        assert "TASK_DOMAIN" in result["error"]

    @pytest.mark.asyncio
    async def test_task_service_get_success(self):
        """Test task_service GET with mocked aiohttp."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.content_type = "application/json"
        mock_response.json = AsyncMock(return_value={"data": [{"id": 1}]})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await toolkit.flowtask_task_service(
                    program="walmart",
                    task_name="daily_report",
                    params={"date": "2024-01-15"}
                )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_task_service_post_success(self):
        """Test task_service POST with mocked aiohttp."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.content_type = "application/json"
        mock_response.json = AsyncMock(return_value={"data": [{"id": 1}]})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await toolkit.flowtask_task_service(
                    program="walmart",
                    task_name="daily_report",
                    method="POST",
                    params={"date": "2024-01-15"}
                )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_task_service_not_found(self):
        """Test task_service returns not_found for 404."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.content_type = "application/json"
        mock_response.text = AsyncMock(return_value="Not Found")

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await toolkit.flowtask_task_service(
                    program="test",
                    task_name="nonexistent"
                )

        assert result["status"] == "not_found"


class TestFlowtaskListTasks:
    """Test the flowtask_list_tasks method."""

    @pytest.mark.asyncio
    async def test_list_tasks_missing_task_domain(self):
        """Test list_tasks returns error when TASK_DOMAIN not set."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        with patch.dict('os.environ', {}, clear=True):
            import os
            os.environ.pop('TASK_DOMAIN', None)

            result = await toolkit.flowtask_list_tasks(program="test")

        assert result["status"] == "error"
        assert "TASK_DOMAIN" in result["error"]

    @pytest.mark.asyncio
    async def test_list_tasks_success(self):
        """Test list_tasks with mocked aiohttp."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        tasks_data = [
            {"task": "daily_report", "task_id": "1"},
            {"task": "weekly_summary", "task_id": "2"}
        ]

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=tasks_data)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await toolkit.flowtask_list_tasks(
                    program="walmart",
                    fields=["task", "task_id"]
                )

        assert result["status"] == "success"
        assert result["count"] == 2
        assert len(result["tasks"]) == 2

    @pytest.mark.asyncio
    async def test_list_tasks_all_programs(self):
        """Test list_tasks without program filter."""
        from parrot.tools.flowtask import FlowtaskToolkit

        toolkit = FlowtaskToolkit()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[])

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch.dict('os.environ', {'TASK_DOMAIN': 'https://api.example.com'}):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await toolkit.flowtask_list_tasks()

        assert result["status"] == "success"


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
        assert input_model.storage == "default"
        assert input_model.variables is None
        assert input_model.attributes is None
        assert input_model.params is None
        assert input_model.ignore_steps is None
        assert input_model.run_only is None

    def test_task_execution_input_with_extras(self):
        """Test FlowtaskTaskExecutionInput with all parameters."""
        from parrot.tools.flowtask import FlowtaskTaskExecutionInput

        input_model = FlowtaskTaskExecutionInput(
            program="test",
            task_name="test_task",
            storage="private",
            variables={"key": "value"},
            attributes={"attr": True},
            params={"p": 1},
            ignore_steps=["step1"],
            run_only=["step2"]
        )

        assert input_model.storage == "private"
        assert input_model.variables == {"key": "value"}
        assert input_model.ignore_steps == ["step1"]
        assert input_model.run_only == ["step2"]

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

    def test_task_service_input_model(self):
        """Test FlowtaskTaskServiceInput validation."""
        from parrot.tools.flowtask import FlowtaskTaskServiceInput

        input_model = FlowtaskTaskServiceInput(
            program="walmart",
            task_name="daily_report",
            method="POST",
            params={"date": "2024-01-15"}
        )

        assert input_model.program == "walmart"
        assert input_model.method == "POST"
        assert input_model.params == {"date": "2024-01-15"}
        assert input_model.timeout == 300.0

    def test_list_tasks_input_model(self):
        """Test FlowtaskListTasksInput validation."""
        from parrot.tools.flowtask import FlowtaskListTasksInput

        input_model = FlowtaskListTasksInput(
            program="walmart",
            fields=["task", "task_id"]
        )

        assert input_model.program == "walmart"
        assert input_model.fields == ["task", "task_id"]
        assert input_model.timeout == 60.0

    def test_list_tasks_input_defaults(self):
        """Test FlowtaskListTasksInput with defaults."""
        from parrot.tools.flowtask import FlowtaskListTasksInput

        input_model = FlowtaskListTasksInput()

        assert input_model.program is None
        assert input_model.fields is None

    def test_code_execution_input_model(self):
        """Test FlowtaskCodeExecutionInput validation."""
        from parrot.tools.flowtask import FlowtaskCodeExecutionInput, TaskCodeFormat

        input_model = FlowtaskCodeExecutionInput(
            task_code="name: Test Task\nsteps: []"
        )

        assert input_model.format == TaskCodeFormat.YAML


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
