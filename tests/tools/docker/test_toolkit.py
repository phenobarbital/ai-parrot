"""Tests for Docker Toolkit (TASK-237)."""

import pytest
from unittest.mock import AsyncMock, patch

from parrot.tools.docker.toolkit import DockerToolkit
from parrot.tools.docker.config import DockerConfig


class TestDockerToolkit:
    """Unit tests for DockerToolkit."""

    def test_inherits_abstract_toolkit(self):
        from parrot.tools.toolkit import AbstractToolkit
        toolkit = DockerToolkit()
        assert isinstance(toolkit, AbstractToolkit)

    def test_get_tools_count(self):
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()
        assert len(tools) == 16

    def test_tool_names(self):
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()
        names = [t.name for t in tools]
        expected = [
            "docker_ps",
            "docker_images",
            "docker_inspect",
            "docker_logs",
            "docker_run",
            "docker_stop",
            "docker_start",
            "docker_restart",
            "docker_rm",
            "docker_build",
            "docker_exec",
            "docker_compose_generate",
            "docker_compose_up",
            "docker_compose_down",
            "docker_prune",
            "docker_test",
        ]
        for name in expected:
            assert name in names, f"Missing tool: {name}"

    def test_tools_have_descriptions(self):
        toolkit = DockerToolkit()
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"

    def test_default_config(self):
        toolkit = DockerToolkit()
        assert toolkit.config.docker_cli == "docker"
        assert toolkit.config.compose_cli == "docker compose"

    def test_custom_config(self):
        config = DockerConfig(docker_cli="/usr/local/bin/docker")
        toolkit = DockerToolkit(config=config)
        assert toolkit.config.docker_cli == "/usr/local/bin/docker"

    @pytest.mark.asyncio
    async def test_ps_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_ps()
            assert result.success is False
            assert "daemon" in result.error.lower()

    @pytest.mark.asyncio
    async def test_images_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_images()
            assert result.success is False
            assert "daemon" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_run(image="redis:alpine")
            assert result.success is False
            assert "daemon" in result.error.lower()

    @pytest.mark.asyncio
    async def test_stop_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_stop(container="test")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_start_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_start(container="test")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_restart_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_restart(container="test")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_build_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_build(tag="myapp:v1")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_exec_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_exec(container="test", command="ls")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_ps_success(self):
        toolkit = DockerToolkit()
        ps_json = '{"ID":"abc123","Names":"redis","Image":"redis:alpine","Status":"Up","Ports":"6379","CreatedAt":"now"}'
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=(ps_json, "", 0),
            ):
                result = await toolkit.docker_ps()
                assert result.success is True
                assert result.operation == "docker_ps"
                assert len(result.containers) == 1
                assert result.containers[0].name == "redis"

    @pytest.mark.asyncio
    async def test_images_success(self):
        toolkit = DockerToolkit()
        img_json = '{"ID":"sha256:abc","Repository":"python","Tag":"3.12","Size":"100MB","CreatedAt":"now"}'
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=(img_json, "", 0),
            ):
                result = await toolkit.docker_images()
                assert result.success is True
                assert len(result.images) == 1
                assert result.images[0].repository == "python"

    @pytest.mark.asyncio
    async def test_run_success(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=("abc123def", "", 0),
            ):
                result = await toolkit.docker_run(
                    image="redis:alpine", name="test-redis"
                )
                assert result.success is True
                assert "abc123def" in result.output

    @pytest.mark.asyncio
    async def test_run_with_ports_and_limits(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=("container_id", "", 0),
            ) as mock_run:
                result = await toolkit.docker_run(
                    image="python:3.12",
                    ports=[{"host_port": 8080, "container_port": 80}],
                    cpu_limit="2",
                    memory_limit="4g",
                )
                assert result.success is True
                # Verify build_run_args was called via run_command
                call_args = mock_run.call_args[0][0]
                assert "--cpus" in call_args
                assert "--memory" in call_args
                assert "-p" in call_args

    @pytest.mark.asyncio
    async def test_run_port_conflict_error(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("", "port is already allocated", 1),
            ):
                result = await toolkit.docker_run(image="nginx")
                assert result.success is False
                assert "different host port" in result.error.lower()

    @pytest.mark.asyncio
    async def test_start_success(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("my-container", "", 0),
            ):
                result = await toolkit.docker_start(container="my-container")
                assert result.success is True
                assert result.operation == "docker_start"

    @pytest.mark.asyncio
    async def test_start_failure(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("", "No such container: missing", 1),
            ):
                result = await toolkit.docker_start(container="missing")
                assert result.success is False
                assert "missing" in result.error.lower()

    @pytest.mark.asyncio
    async def test_restart_success(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("my-container", "", 0),
            ):
                result = await toolkit.docker_restart(container="my-container")
                assert result.success is True
                assert result.operation == "docker_restart"

    @pytest.mark.asyncio
    async def test_restart_failure(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("", "No such container: missing", 1),
            ):
                result = await toolkit.docker_restart(container="missing")
                assert result.success is False

    @pytest.mark.asyncio
    async def test_restart_passes_timeout(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("ok", "", 0),
            ) as mock_run:
                await toolkit.docker_restart(container="c", timeout=30)
                call_args = mock_run.call_args[0][0]
                assert "-t" in call_args
                assert "30" in call_args

    @pytest.mark.asyncio
    async def test_build_success(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock,
                return_value=("Successfully built abc123", "", 0),
            ):
                result = await toolkit.docker_build(
                    tag="myapp:v1", no_cache=True
                )
                assert result.success is True

    @pytest.mark.asyncio
    async def test_exec_success(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=("PONG", "", 0),
            ):
                result = await toolkit.docker_exec(
                    container="redis", command="redis-cli ping"
                )
                assert result.success is True
                assert "PONG" in result.output

    @pytest.mark.asyncio
    async def test_compose_generate_success(self, tmp_path):
        toolkit = DockerToolkit()
        output = str(tmp_path / "docker-compose.yml")
        result = await toolkit.docker_compose_generate(
            project_name="test",
            services={"redis": {"image": "redis:alpine"}},
            output_path=output,
        )
        assert result.success is True
        assert "Generated" in result.output

    @pytest.mark.asyncio
    async def test_compose_up_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_compose_up()
            assert result.success is False

    @pytest.mark.asyncio
    async def test_compose_down_checks_daemon(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_compose_down()
            assert result.success is False

    @pytest.mark.asyncio
    async def test_prune_returns_prune_result(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=("", "", 0),
            ):
                result = await toolkit.docker_prune()
                from parrot.tools.docker.models import PruneResult
                assert isinstance(result, PruneResult)
                assert result.success is True

    @pytest.mark.asyncio
    async def test_prune_daemon_down(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_prune()
            from parrot.tools.docker.models import PruneResult
            assert isinstance(result, PruneResult)
            assert result.success is False
            assert "daemon" in result.error.lower()

    @pytest.mark.asyncio
    async def test_prune_warns_on_volumes(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=("", "", 0),
            ):
                with patch.object(toolkit.logger, "warning") as mock_warn:
                    await toolkit.docker_prune(volumes=True)
                    mock_warn.assert_called_once()
                    assert "data loss" in mock_warn.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_test_daemon_down(self):
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            result = await toolkit.docker_test(container="test")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_test_container_running(self):
        toolkit = DockerToolkit()
        inspect_output = '{"State": {"Running": true}}'
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=(inspect_output, "", 0),
            ):
                result = await toolkit.docker_test(container="redis")
                assert result.success is True
                assert "running" in result.output.lower()

    @pytest.mark.asyncio
    async def test_test_container_not_running(self):
        toolkit = DockerToolkit()
        inspect_output = '{"State": {"Running": false}}'
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=True,
        ):
            with patch.object(
                toolkit.executor, "run_command",
                new_callable=AsyncMock, return_value=(inspect_output, "", 0),
            ):
                result = await toolkit.docker_test(container="redis")
                assert result.success is False
                assert "not running" in result.error.lower()

    @pytest.mark.asyncio
    async def test_all_methods_return_result_types(self):
        """Verify all tool methods return DockerOperationResult or PruneResult."""
        from parrot.tools.docker.models import DockerOperationResult, PruneResult
        toolkit = DockerToolkit()
        with patch.object(
            toolkit.executor, "check_daemon",
            new_callable=AsyncMock, return_value=False,
        ):
            # All should return error results when daemon is down
            assert isinstance(await toolkit.docker_ps(), DockerOperationResult)
            assert isinstance(await toolkit.docker_images(), DockerOperationResult)
            assert isinstance(await toolkit.docker_run(image="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_stop(container="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_rm(container="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_logs(container="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_inspect(container="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_build(tag="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_exec(container="x", command="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_compose_up(), DockerOperationResult)
            assert isinstance(await toolkit.docker_compose_down(), DockerOperationResult)
            assert isinstance(await toolkit.docker_test(container="x"), DockerOperationResult)
            assert isinstance(await toolkit.docker_prune(), PruneResult)
