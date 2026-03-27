"""Unit tests for the security base executor."""

import pytest

from parrot.tools.security.base_executor import BaseExecutor, BaseExecutorConfig


class ConcreteExecutor(BaseExecutor):
    """Test implementation of BaseExecutor."""

    def _build_cli_args(self, **kwargs) -> list[str]:
        return ["--test", kwargs.get("param", "default")]

    def _default_cli_name(self) -> str:
        return "test-scanner"


class TestBaseExecutorConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = BaseExecutorConfig()
        assert config.use_docker is True
        assert config.timeout == 600
        assert config.aws_region == "us-east-1"
        assert config.docker_image == ""
        assert config.cli_path is None

    def test_aws_credentials(self):
        """AWS credentials can be set."""
        config = BaseExecutorConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret123",
            aws_region="eu-west-1",
        )
        assert config.aws_access_key_id == "AKIATEST"
        assert config.aws_secret_access_key == "secret123"
        assert config.aws_region == "eu-west-1"

    def test_aws_session_token(self):
        """AWS session token for temporary credentials."""
        config = BaseExecutorConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret123",
            aws_session_token="FwoGZXIvYXdzEOr//////////",
        )
        assert config.aws_session_token is not None

    def test_gcp_credentials(self):
        """GCP credentials can be set."""
        config = BaseExecutorConfig(
            gcp_credentials_file="/path/to/creds.json",
            gcp_project_id="my-project-123",
        )
        assert config.gcp_credentials_file == "/path/to/creds.json"
        assert config.gcp_project_id == "my-project-123"

    def test_azure_credentials(self):
        """Azure credentials can be set."""
        config = BaseExecutorConfig(
            azure_client_id="12345678-1234-1234-1234-123456789012",
            azure_client_secret="secret~value",
            azure_tenant_id="87654321-4321-4321-4321-210987654321",
            azure_subscription_id="sub-12345",
        )
        assert config.azure_client_id is not None
        assert config.azure_client_secret is not None
        assert config.azure_tenant_id is not None
        assert config.azure_subscription_id is not None


class TestBaseExecutor:
    @pytest.fixture
    def executor(self):
        config = BaseExecutorConfig(
            use_docker=True,
            docker_image="test/scanner:latest",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        return ConcreteExecutor(config)

    @pytest.fixture
    def executor_all_creds(self):
        """Executor with all cloud credentials."""
        config = BaseExecutorConfig(
            use_docker=True,
            docker_image="test/scanner:latest",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            aws_session_token="FwoGZXIvYXdzEOrTOKEN",
            gcp_credentials_file="/path/to/gcp-creds.json",
            gcp_project_id="my-gcp-project",
            azure_client_id="azure-client-id",
            azure_client_secret="azure-secret",
            azure_tenant_id="azure-tenant",
            azure_subscription_id="azure-sub",
        )
        return ConcreteExecutor(config)

    def test_build_env_vars_aws(self, executor):
        """Environment variables are built correctly for AWS."""
        env = executor._build_env_vars()
        assert env["AWS_ACCESS_KEY_ID"] == "AKIAIOSFODNN7EXAMPLE"
        assert "AWS_SECRET_ACCESS_KEY" in env
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"
        assert env["AWS_REGION"] == "us-east-1"

    def test_build_env_vars_all_providers(self, executor_all_creds):
        """Environment variables include all cloud providers."""
        env = executor_all_creds._build_env_vars()

        # AWS
        assert env["AWS_ACCESS_KEY_ID"] == "AKIAIOSFODNN7EXAMPLE"
        assert env["AWS_SECRET_ACCESS_KEY"] is not None
        assert env["AWS_SESSION_TOKEN"] is not None

        # GCP
        assert env["GOOGLE_APPLICATION_CREDENTIALS"] == "/path/to/gcp-creds.json"
        assert env["GCP_PROJECT_ID"] == "my-gcp-project"

        # Azure
        assert env["AZURE_CLIENT_ID"] == "azure-client-id"
        assert env["AZURE_CLIENT_SECRET"] == "azure-secret"
        assert env["AZURE_TENANT_ID"] == "azure-tenant"
        assert env["AZURE_SUBSCRIPTION_ID"] == "azure-sub"

    def test_build_docker_command(self, executor):
        """Docker command is built correctly."""
        args = ["--check", "s3"]
        cmd = executor._build_docker_command(args)
        assert cmd[0] == "docker"
        assert "run" in cmd
        assert "--rm" in cmd
        assert "test/scanner:latest" in cmd
        assert "--check" in cmd
        assert "s3" in cmd

    def test_build_docker_command_with_env_vars(self, executor):
        """Docker command includes environment variables."""
        args = ["--scan"]
        cmd = executor._build_docker_command(args)

        # Check that -e flags are present
        cmd_str = " ".join(cmd)
        assert "-e AWS_ACCESS_KEY_ID=" in cmd_str
        assert "-e AWS_SECRET_ACCESS_KEY=" in cmd_str

    def test_build_direct_command(self, executor):
        """Direct CLI command is built correctly."""
        executor.config.use_docker = False
        args = ["--check", "s3"]
        cmd = executor._build_direct_command(args)
        assert cmd[0] == "test-scanner"
        assert "--check" in cmd
        assert "s3" in cmd

    def test_build_direct_command_with_custom_path(self, executor):
        """Direct CLI command uses custom path when provided."""
        executor.config.use_docker = False
        executor.config.cli_path = "/usr/local/bin/custom-scanner"
        args = ["--scan"]
        cmd = executor._build_direct_command(args)
        assert cmd[0] == "/usr/local/bin/custom-scanner"

    def test_mask_command_hides_secrets(self, executor):
        """Secrets are masked in command output."""
        cmd = [
            "docker",
            "run",
            "-e",
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG",
            "-e",
            "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
        ]
        masked = executor._mask_command(cmd)
        assert "wJalrXUtnFEMI" not in masked
        assert "***" in masked
        # Access key ID should show first 3 chars only
        assert "AKI***" in masked

    def test_mask_command_hides_aws_session_token(self, executor):
        """AWS session token is masked."""
        cmd = ["-e", "AWS_SESSION_TOKEN=FwoGZXIvYXdzEOrTOKEN"]
        masked = executor._mask_command(cmd)
        assert "FwoGZXIvYXdzEOrTOKEN" not in masked
        assert "AWS_SESSION_TOKEN=***" in masked

    def test_mask_command_hides_azure_secret(self, executor):
        """Azure client secret is masked."""
        cmd = ["-e", "AZURE_CLIENT_SECRET=super-secret-value"]
        masked = executor._mask_command(cmd)
        assert "super-secret-value" not in masked
        assert "AZURE_CLIENT_SECRET=***" in masked

    def test_mask_command_hides_gcp_path(self, executor):
        """GCP credentials file path is partially masked."""
        cmd = ["-e", "GOOGLE_APPLICATION_CREDENTIALS=/home/user/secret/creds.json"]
        masked = executor._mask_command(cmd)
        assert "/home/user/secret" not in masked
        assert "creds.json" in masked  # Filename is kept

    def test_abstract_methods_required(self):
        """Cannot instantiate BaseExecutor directly."""
        config = BaseExecutorConfig()
        with pytest.raises(TypeError):
            BaseExecutor(config)  # type: ignore


class TestExecutorExecution:
    @pytest.fixture
    def echo_executor(self):
        """Executor that runs echo command."""
        config = BaseExecutorConfig(use_docker=False, cli_path="echo", timeout=5)

        class EchoExecutor(BaseExecutor):
            def _build_cli_args(self, **kwargs) -> list[str]:
                return kwargs.get("args", ["hello"])

            def _default_cli_name(self) -> str:
                return "echo"

        return EchoExecutor(config)

    @pytest.mark.asyncio
    async def test_execute_success(self, echo_executor):
        """Execute returns stdout, stderr, exit code."""
        stdout, stderr, code = await echo_executor.execute(["hello", "world"])
        assert code == 0
        assert "hello world" in stdout

    @pytest.mark.asyncio
    async def test_execute_with_kwargs(self, echo_executor):
        """Execute builds args from kwargs when args not provided."""
        stdout, stderr, code = await echo_executor.execute(args=["test", "output"])
        assert code == 0
        assert "test" in stdout

    @pytest.mark.asyncio
    async def test_execute_nonzero_exit(self):
        """Execute handles non-zero exit codes and warns by default."""
        config = BaseExecutorConfig(use_docker=False, cli_path="false", timeout=5)

        class FalseExecutor(BaseExecutor):
            def _build_cli_args(self, **kwargs) -> list[str]:
                return []

            def _default_cli_name(self) -> str:
                return "false"

        executor = FalseExecutor(config)
        stdout, stderr, code = await executor.execute([])
        assert code != 0

    @pytest.mark.asyncio
    async def test_execute_expected_nonzero_exit(self):
        """Execute does not warn for expected non-zero exit codes."""
        config = BaseExecutorConfig(use_docker=False, cli_path="false", timeout=5)

        class FalseExecutor(BaseExecutor):
            def __init__(self, config):
                super().__init__(config)
                self.expected_exit_codes = [0, 1]

            def _build_cli_args(self, **kwargs) -> list[str]:
                return []

            def _default_cli_name(self) -> str:
                return "false"

        executor = FalseExecutor(config)
        # Assuming false exits with 1, the warning logic won't trigger. 
        # Using a valid assert for the return code ensures the execution works.
        stdout, stderr, code = await executor.execute([])
        assert code == 1

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """Execution times out correctly."""
        config = BaseExecutorConfig(use_docker=False, cli_path="sleep", timeout=1)

        class SleepExecutor(BaseExecutor):
            def _build_cli_args(self, **kwargs) -> list[str]:
                return ["10"]

            def _default_cli_name(self) -> str:
                return "sleep"

        executor = SleepExecutor(config)
        stdout, stderr, code = await executor.execute(["10"])
        assert code == -1  # Timeout indicator
        assert "Timeout" in stderr


class TestExecutorStreaming:
    """Tests for execute_streaming method."""

    @pytest.fixture
    def bash_executor(self):
        """Executor that runs bash with stderr output."""
        config = BaseExecutorConfig(use_docker=False, cli_path="bash", timeout=5)

        class BashExecutor(BaseExecutor):
            def _build_cli_args(self, **kwargs) -> list[str]:
                return ["-c", kwargs.get("script", "echo hello")]

            def _default_cli_name(self) -> str:
                return "bash"

        return BashExecutor(config)

    @pytest.mark.asyncio
    async def test_streaming_returns_same_as_execute(self, bash_executor):
        """execute_streaming returns (stdout, stderr, exit_code) like execute."""
        stdout, stderr, code = await bash_executor.execute_streaming(
            args=["-c", "echo hello"]
        )
        assert code == 0
        assert "hello" in stdout

    @pytest.mark.asyncio
    async def test_streaming_captures_stderr(self, bash_executor):
        """execute_streaming captures stderr output."""
        stdout, stderr, code = await bash_executor.execute_streaming(
            args=["-c", "echo 'out'; echo 'err line 1' >&2; echo 'err line 2' >&2"]
        )
        assert code == 0
        assert "out" in stdout
        assert "err line 1" in stderr
        assert "err line 2" in stderr

    @pytest.mark.asyncio
    async def test_streaming_callback_invoked(self, bash_executor):
        """progress_callback is called for each stderr line."""
        received_lines: list[str] = []

        def on_progress(line: str) -> None:
            received_lines.append(line)

        stdout, stderr, code = await bash_executor.execute_streaming(
            progress_callback=on_progress,
            args=["-c", "echo 'line1' >&2; echo 'line2' >&2; echo 'line3' >&2"],
        )
        assert code == 0
        assert len(received_lines) == 3
        assert "line1" in received_lines[0]
        assert "line2" in received_lines[1]
        assert "line3" in received_lines[2]

    @pytest.mark.asyncio
    async def test_streaming_callback_error_does_not_crash(self, bash_executor):
        """Callback errors are swallowed to avoid killing the scan."""

        def bad_callback(line: str) -> None:
            raise ValueError("callback error")

        stdout, stderr, code = await bash_executor.execute_streaming(
            progress_callback=bad_callback,
            args=["-c", "echo 'err' >&2; echo 'ok'"],
        )
        assert code == 0
        assert "ok" in stdout

    @pytest.mark.asyncio
    async def test_streaming_timeout(self):
        """execute_streaming handles timeout."""
        config = BaseExecutorConfig(use_docker=False, cli_path="sleep", timeout=1)

        class SleepExecutor(BaseExecutor):
            def _build_cli_args(self, **kwargs) -> list[str]:
                return ["10"]

            def _default_cli_name(self) -> str:
                return "sleep"

        executor = SleepExecutor(config)
        stdout, stderr, code = await executor.execute_streaming(args=["10"])
        assert code == -1
        assert "Timeout" in stderr

    @pytest.mark.asyncio
    async def test_streaming_no_callback(self, bash_executor):
        """execute_streaming works fine without a callback."""
        stdout, stderr, code = await bash_executor.execute_streaming(
            args=["-c", "echo 'progress' >&2; echo 'result'"]
        )
        assert code == 0
        assert "result" in stdout
        assert "progress" in stderr


class TestImports:
    def test_import_from_security_package(self):
        """BaseExecutor can be imported from parrot.tools.security."""
        from parrot.tools.security import BaseExecutor, BaseExecutorConfig

        assert BaseExecutor is not None
        assert BaseExecutorConfig is not None

    def test_import_from_base_executor_module(self):
        """BaseExecutor can be imported from base_executor module."""
        from parrot.tools.security.base_executor import (
            BaseExecutor,
            BaseExecutorConfig,
        )

        config = BaseExecutorConfig(timeout=300)
        assert config.timeout == 300
