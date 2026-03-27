"""Tests for Docker executor (TASK-239)."""

import pytest
from unittest.mock import AsyncMock, patch

from parrot.tools.docker.config import DockerConfig
from parrot.tools.docker.executor import DockerExecutor
from parrot.tools.docker.models import (
    ContainerRunInput,
    DockerBuildInput,
    DockerExecInput,
    DockerOperationResult,
    PortMapping,
    VolumeMapping,
)


class TestDockerExecutorInit:
    """Tests for executor initialization."""

    def test_default_config(self):
        executor = DockerExecutor()
        assert executor.config.docker_cli == "docker"

    def test_custom_config(self):
        config = DockerConfig(docker_cli="/opt/docker", timeout=30)
        executor = DockerExecutor(config)
        assert executor.config.docker_cli == "/opt/docker"
        assert executor.config.timeout == 30


class TestBuildRunArgs:
    """Tests for build_run_args."""

    def test_basic(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="redis:alpine", name="test-redis", detach=True
        )
        args = executor.build_run_args(inp)
        assert args[0] == "run"
        assert "-d" in args
        assert "--name" in args
        assert "test-redis" in args
        assert "redis:alpine" in args

    def test_no_detach(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(image="alpine", detach=False)
        args = executor.build_run_args(inp)
        assert "-d" not in args

    def test_with_ports(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="nginx",
            ports=[
                PortMapping(host_port=8080, container_port=80),
                PortMapping(host_port=443, container_port=443, protocol="tcp"),
            ],
        )
        args = executor.build_run_args(inp)
        assert "-p" in args
        assert "8080:80/tcp" in args
        assert "443:443/tcp" in args

    def test_with_volumes(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="postgres",
            volumes=[
                VolumeMapping(host_path="/data", container_path="/var/lib/data"),
                VolumeMapping(
                    host_path="conf", container_path="/etc/conf", read_only=True
                ),
            ],
        )
        args = executor.build_run_args(inp)
        assert "-v" in args
        assert "/data:/var/lib/data" in args
        assert "conf:/etc/conf:ro" in args

    def test_with_env_vars(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="postgres",
            env_vars={"POSTGRES_DB": "test", "POSTGRES_USER": "admin"},
        )
        args = executor.build_run_args(inp)
        assert "-e" in args
        assert "POSTGRES_DB=test" in args
        assert "POSTGRES_USER=admin" in args

    def test_with_restart_policy(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="redis", restart_policy="unless-stopped"
        )
        args = executor.build_run_args(inp)
        assert "--restart" in args
        assert "unless-stopped" in args

    def test_with_resource_limits(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="python:3.12", cpu_limit="2", memory_limit="4g"
        )
        args = executor.build_run_args(inp)
        assert "--cpus" in args
        assert "2" in args
        assert "--memory" in args
        assert "4g" in args

    def test_config_resource_limits_fallback(self):
        config = DockerConfig(cpu_limit="1", memory_limit="2g")
        executor = DockerExecutor(config)
        inp = ContainerRunInput(image="alpine")
        args = executor.build_run_args(inp)
        assert "--cpus" in args
        assert "1" in args
        assert "--memory" in args
        assert "2g" in args

    def test_input_limits_override_config(self):
        config = DockerConfig(cpu_limit="1", memory_limit="2g")
        executor = DockerExecutor(config)
        inp = ContainerRunInput(
            image="alpine", cpu_limit="4", memory_limit="8g"
        )
        args = executor.build_run_args(inp)
        cpu_idx = args.index("--cpus")
        mem_idx = args.index("--memory")
        assert args[cpu_idx + 1] == "4"
        assert args[mem_idx + 1] == "8g"

    def test_with_network(self):
        config = DockerConfig(default_network="my-net")
        executor = DockerExecutor(config)
        inp = ContainerRunInput(image="redis")
        args = executor.build_run_args(inp)
        assert "--network" in args
        assert "my-net" in args

    def test_with_command(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(image="ubuntu", command="bash -c 'echo hello'")
        args = executor.build_run_args(inp)
        # Image should come before command
        img_idx = args.index("ubuntu")
        assert img_idx < len(args) - 1

    def test_image_is_last_before_command(self):
        executor = DockerExecutor()
        inp = ContainerRunInput(
            image="redis:alpine",
            name="test",
            detach=True,
        )
        args = executor.build_run_args(inp)
        assert args[-1] == "redis:alpine"


class TestBuildExecArgs:
    """Tests for build_exec_args."""

    def test_basic(self):
        executor = DockerExecutor()
        inp = DockerExecInput(container="redis", command="redis-cli ping")
        args = executor.build_exec_args(inp)
        assert args[0] == "exec"
        assert "redis" in args
        assert "redis-cli" in args
        assert "ping" in args

    def test_with_workdir(self):
        executor = DockerExecutor()
        inp = DockerExecInput(
            container="app", command="ls", workdir="/app/src"
        )
        args = executor.build_exec_args(inp)
        assert "-w" in args
        assert "/app/src" in args

    def test_with_user(self):
        executor = DockerExecutor()
        inp = DockerExecInput(
            container="app", command="whoami", user="root"
        )
        args = executor.build_exec_args(inp)
        assert "-u" in args
        assert "root" in args

    def test_with_env_vars(self):
        executor = DockerExecutor()
        inp = DockerExecInput(
            container="app",
            command="env",
            env_vars={"MY_VAR": "hello"},
        )
        args = executor.build_exec_args(inp)
        assert "-e" in args
        assert "MY_VAR=hello" in args


class TestBuildBuildArgs:
    """Tests for build_build_args."""

    def test_basic(self):
        executor = DockerExecutor()
        inp = DockerBuildInput(tag="myapp:v1")
        args = executor.build_build_args(inp)
        assert args[0] == "build"
        assert "-t" in args
        assert "myapp:v1" in args
        assert "." in args  # default dockerfile_path

    def test_no_cache(self):
        executor = DockerExecutor()
        inp = DockerBuildInput(tag="myapp:v1", no_cache=True)
        args = executor.build_build_args(inp)
        assert "--no-cache" in args

    def test_with_build_args(self):
        executor = DockerExecutor()
        inp = DockerBuildInput(
            tag="myapp:v1",
            build_args={"VERSION": "1.0", "ENV": "prod"},
        )
        args = executor.build_build_args(inp)
        assert "--build-arg" in args
        assert "VERSION=1.0" in args
        assert "ENV=prod" in args

    def test_custom_dockerfile_path(self):
        executor = DockerExecutor()
        inp = DockerBuildInput(tag="myapp:v1", dockerfile_path="./docker")
        args = executor.build_build_args(inp)
        assert args[-1] == "./docker"


class TestBuildCliArgs:
    """Tests for _build_cli_args."""

    def test_ps_default(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(command="ps")
        assert "ps" in args
        assert "--format" in args
        assert "{{json .}}" in args

    def test_ps_all(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(command="ps", all=True)
        assert "-a" in args

    def test_ps_with_filters(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(
            command="ps", filters={"status": "running"}
        )
        assert "--filter" in args
        assert "status=running" in args

    def test_images(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(command="images")
        assert "images" in args
        assert "--format" in args

    def test_stop(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(
            command="stop", container="redis", timeout=5
        )
        assert "stop" in args
        assert "-t" in args
        assert "5" in args
        assert "redis" in args

    def test_rm_force(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(
            command="rm", container="redis", force=True, volumes=True
        )
        assert "rm" in args
        assert "-f" in args
        assert "-v" in args

    def test_logs(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(
            command="logs", container="redis", tail=50, since="2h"
        )
        assert "logs" in args
        assert "--tail" in args
        assert "50" in args
        assert "--since" in args
        assert "2h" in args

    def test_inspect(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(
            command="inspect", container="redis"
        )
        assert "inspect" in args
        assert "--format" in args
        assert "redis" in args

    def test_prune_containers(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(command="prune_containers")
        assert "container" in args
        assert "prune" in args
        assert "-f" in args

    def test_prune_images(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(command="prune_images")
        assert "image" in args
        assert "prune" in args

    def test_prune_volumes(self):
        executor = DockerExecutor()
        args = executor._build_cli_args(command="prune_volumes")
        assert "volume" in args
        assert "prune" in args


class TestParsePsOutput:
    """Tests for parse_ps_output."""

    def test_single_line(self, mock_docker_ps_output):
        executor = DockerExecutor()
        result = executor.parse_ps_output(mock_docker_ps_output)
        assert len(result) == 1
        assert result[0].container_id == "abc123"
        assert result[0].name == "redis"
        assert result[0].image == "redis:alpine"

    def test_multi_line(self, mock_docker_ps_multi_output):
        executor = DockerExecutor()
        result = executor.parse_ps_output(mock_docker_ps_multi_output)
        assert len(result) == 2
        assert result[0].name == "redis"
        assert result[1].name == "postgres"

    def test_empty_output(self):
        executor = DockerExecutor()
        result = executor.parse_ps_output("")
        assert result == []

    def test_whitespace_output(self):
        executor = DockerExecutor()
        result = executor.parse_ps_output("  \n  \n  ")
        assert result == []

    def test_invalid_json(self):
        executor = DockerExecutor()
        result = executor.parse_ps_output("not json at all")
        assert result == []


class TestParseImagesOutput:
    """Tests for parse_images_output."""

    def test_single_line(self, mock_docker_images_output):
        executor = DockerExecutor()
        result = executor.parse_images_output(mock_docker_images_output)
        assert len(result) == 1
        assert result[0].repository == "redis"
        assert result[0].tag == "alpine"

    def test_empty_output(self):
        executor = DockerExecutor()
        result = executor.parse_images_output("")
        assert result == []


class TestCheckDaemon:
    """Tests for check_daemon."""

    @pytest.mark.asyncio
    async def test_daemon_not_running(self):
        executor = DockerExecutor(
            DockerConfig(docker_cli="/nonexistent/docker")
        )
        result = await executor.check_daemon()
        assert result is False

    @pytest.mark.asyncio
    async def test_daemon_running_mocked(self):
        executor = DockerExecutor()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.check_daemon()
            assert result is True

    @pytest.mark.asyncio
    async def test_daemon_returns_error(self):
        executor = DockerExecutor()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.check_daemon()
            assert result is False


class TestCheckCompose:
    """Tests for check_compose."""

    @pytest.mark.asyncio
    async def test_compose_not_available(self):
        executor = DockerExecutor(
            DockerConfig(compose_cli="/nonexistent/compose")
        )
        result = await executor.check_compose()
        assert result is False

    @pytest.mark.asyncio
    async def test_compose_available_mocked(self):
        executor = DockerExecutor()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"v2.24.0", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await executor.check_compose()
            assert result is True


class TestRunCommand:
    """Tests for run_command."""

    @pytest.mark.asyncio
    async def test_success(self):
        executor = DockerExecutor()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"container123", b"")
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            stdout, stderr, code = await executor.run_command(["ps"])
            assert code == 0
            assert stdout == "container123"
            assert stderr == ""

    @pytest.mark.asyncio
    async def test_failure(self):
        executor = DockerExecutor()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"Error: no such container")
        )
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            stdout, stderr, code = await executor.run_command(["stop", "x"])
            assert code == 1
            assert "no such container" in stderr

    @pytest.mark.asyncio
    async def test_os_error(self):
        executor = DockerExecutor(
            DockerConfig(docker_cli="/nonexistent/docker")
        )
        stdout, stderr, code = await executor.run_command(["ps"])
        assert code == -1
        assert "Failed to execute" in stderr


class TestResultHelpers:
    """Tests for make_error_result and make_success_result."""

    def test_make_error_result(self):
        executor = DockerExecutor()
        result = executor.make_error_result("docker_ps", "daemon not running")
        assert isinstance(result, DockerOperationResult)
        assert result.success is False
        assert result.operation == "docker_ps"
        assert result.error == "daemon not running"

    def test_make_success_result(self):
        executor = DockerExecutor()
        result = executor.make_success_result(
            "docker_ps", output="OK"
        )
        assert isinstance(result, DockerOperationResult)
        assert result.success is True
        assert result.operation == "docker_ps"
        assert result.output == "OK"
        assert result.containers == []
        assert result.images == []

    def test_make_success_result_with_containers(self):
        from parrot.tools.docker.models import ContainerInfo

        executor = DockerExecutor()
        containers = [
            ContainerInfo(
                container_id="abc",
                name="redis",
                image="redis:alpine",
                status="Up",
            )
        ]
        result = executor.make_success_result(
            "docker_ps", containers=containers
        )
        assert len(result.containers) == 1
        assert result.containers[0].name == "redis"
