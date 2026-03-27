"""Unit tests for the Checkov executor and config."""

from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.security.checkov.config import CheckovConfig
from parrot.tools.security.checkov.executor import CheckovExecutor


class TestCheckovConfig:
    """Test CheckovConfig model."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = CheckovConfig()
        assert config.docker_image == "bridgecrew/checkov:latest"
        assert config.output_format == "json"
        assert config.compact is True
        assert config.frameworks == []
        assert config.run_checks == []
        assert config.skip_checks == []

    def test_custom_frameworks(self):
        """Custom framework specification."""
        config = CheckovConfig(frameworks=["terraform", "cloudformation"])
        assert len(config.frameworks) == 2
        assert "terraform" in config.frameworks
        assert "cloudformation" in config.frameworks

    def test_check_filters(self):
        """Check inclusion/exclusion filters."""
        config = CheckovConfig(
            run_checks=["CKV_AWS_18", "CKV_AWS_21"],
            skip_checks=["CKV_AWS_1"],
        )
        assert "CKV_AWS_18" in config.run_checks
        assert "CKV_AWS_21" in config.run_checks
        assert "CKV_AWS_1" in config.skip_checks

    def test_external_checks_dir(self):
        """External checks directory configuration."""
        config = CheckovConfig(external_checks_dir="/custom/policies")
        assert config.external_checks_dir == "/custom/policies"

    def test_external_checks_git(self):
        """External checks git configuration."""
        config = CheckovConfig(
            external_checks_git="main@https://github.com/org/policies.git"
        )
        assert config.external_checks_git == "main@https://github.com/org/policies.git"

    def test_soft_fail_mode(self):
        """Soft fail mode configuration."""
        config = CheckovConfig(soft_fail=True)
        assert config.soft_fail is True

    def test_baseline_configuration(self):
        """Baseline file configuration."""
        config = CheckovConfig(baseline="/path/to/.checkov.baseline")
        assert config.baseline == "/path/to/.checkov.baseline"

    def test_skip_paths(self):
        """Skip paths configuration."""
        config = CheckovConfig(skip_paths=["node_modules", ".terraform"])
        assert "node_modules" in config.skip_paths
        assert ".terraform" in config.skip_paths


class TestCheckovExecutor:
    """Test CheckovExecutor class."""

    @pytest.fixture
    def executor(self):
        """Create executor with terraform framework."""
        config = CheckovConfig(
            frameworks=["terraform"],
            compact=True,
        )
        return CheckovExecutor(config)

    @pytest.fixture
    def default_executor(self):
        """Create executor with default config."""
        return CheckovExecutor(CheckovConfig())

    def test_default_cli_name(self, executor):
        """Default CLI name is 'checkov'."""
        assert executor._default_cli_name() == "checkov"

    def test_build_directory_scan_args(self, executor):
        """Directory scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="directory", target="/app/terraform")
        assert "-d" in args
        assert "/app/terraform" in args
        assert "-o" in args
        assert "json" in args
        assert "--compact" in args
        assert "--framework" in args
        assert "terraform" in args

    def test_build_file_scan_args(self, executor):
        """File scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="file", target="/app/main.tf")
        assert "-f" in args
        assert "/app/main.tf" in args

    def test_build_args_with_checks(self):
        """Check filters are included."""
        config = CheckovConfig(
            run_checks=["CKV_AWS_18", "CKV_AWS_21"],
            skip_checks=["CKV_AWS_1"],
        )
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--check" in args
        assert "CKV_AWS_18,CKV_AWS_21" in args
        assert "--skip-check" in args
        assert "CKV_AWS_1" in args

    def test_build_args_without_compact(self):
        """Non-compact mode omits --compact flag."""
        config = CheckovConfig(compact=False)
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--compact" not in args

    def test_build_args_with_external_checks(self):
        """External checks directory is included."""
        config = CheckovConfig(external_checks_dir="/policies")
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--external-checks-dir" in args
        assert "/policies" in args

    def test_build_args_with_external_git(self):
        """External checks git is included."""
        config = CheckovConfig(
            external_checks_git="main@https://github.com/org/policies.git"
        )
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--external-checks-git" in args
        assert "main@https://github.com/org/policies.git" in args

    def test_build_args_with_soft_fail(self):
        """Soft fail mode is included."""
        config = CheckovConfig(soft_fail=True)
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--soft-fail" in args

    def test_build_args_with_baseline(self):
        """Baseline file is included."""
        config = CheckovConfig(baseline="/path/to/.baseline")
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--baseline" in args
        assert "/path/to/.baseline" in args

    def test_build_args_with_skip_paths(self):
        """Skip paths are included."""
        config = CheckovConfig(skip_paths=["node_modules", ".terraform"])
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--skip-path" in args
        assert "node_modules" in args
        assert ".terraform" in args

    def test_build_args_download_modules_disabled(self):
        """Download modules can be disabled."""
        config = CheckovConfig(download_external_modules=False)
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--no-download-external-modules" in args

    def test_build_args_secrets_disabled(self):
        """Secrets scanning can be disabled."""
        config = CheckovConfig(enable_secret_scan=False)
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        assert "--skip-secrets-checks" in args

    def test_build_args_multiple_frameworks(self):
        """Multiple frameworks are included."""
        config = CheckovConfig(frameworks=["terraform", "cloudformation", "kubernetes"])
        executor = CheckovExecutor(config)
        args = executor._build_cli_args(scan_type="directory", target="/app")
        # Each framework gets its own --framework flag
        framework_count = args.count("--framework")
        assert framework_count == 3


class TestCheckovExecutorHelpers:
    """Test helper methods on CheckovExecutor."""

    @pytest.fixture
    def executor(self):
        """Create executor with default config."""
        return CheckovExecutor(CheckovConfig())

    def test_scan_directory_method_exists(self, executor):
        """scan_directory helper exists."""
        assert hasattr(executor, "scan_directory")

    def test_scan_file_method_exists(self, executor):
        """scan_file helper exists."""
        assert hasattr(executor, "scan_file")

    def test_scan_terraform_method_exists(self, executor):
        """scan_terraform helper exists."""
        assert hasattr(executor, "scan_terraform")

    def test_scan_cloudformation_method_exists(self, executor):
        """scan_cloudformation helper exists."""
        assert hasattr(executor, "scan_cloudformation")

    def test_scan_kubernetes_method_exists(self, executor):
        """scan_kubernetes helper exists."""
        assert hasattr(executor, "scan_kubernetes")

    def test_scan_dockerfile_method_exists(self, executor):
        """scan_dockerfile helper exists."""
        assert hasattr(executor, "scan_dockerfile")

    def test_scan_secrets_method_exists(self, executor):
        """scan_secrets helper exists."""
        assert hasattr(executor, "scan_secrets")

    def test_scan_github_actions_method_exists(self, executor):
        """scan_github_actions helper exists."""
        assert hasattr(executor, "scan_github_actions")

    def test_list_checks_method_exists(self, executor):
        """list_checks helper exists."""
        assert hasattr(executor, "list_checks")


class TestCheckovExecutorHelperExecution:
    """Test helper method execution."""

    @pytest.fixture
    def executor(self):
        """Create executor with default config."""
        return CheckovExecutor(CheckovConfig())

    @pytest.mark.asyncio
    async def test_scan_directory_calls_execute(self, executor):
        """scan_directory calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_directory("/app/terraform")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["scan_type"] == "directory"
            assert call_kwargs["target"] == "/app/terraform"

    @pytest.mark.asyncio
    async def test_scan_file_calls_execute(self, executor):
        """scan_file calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_file("/app/main.tf")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["scan_type"] == "file"
            assert call_kwargs["target"] == "/app/main.tf"

    @pytest.mark.asyncio
    async def test_scan_terraform_calls_execute(self, executor):
        """scan_terraform calls execute with terraform framework."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_terraform("/app/terraform")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["terraform"]

    @pytest.mark.asyncio
    async def test_scan_cloudformation_calls_execute(self, executor):
        """scan_cloudformation calls execute with cloudformation framework."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_cloudformation("/app/cfn")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["cloudformation"]

    @pytest.mark.asyncio
    async def test_scan_kubernetes_calls_execute(self, executor):
        """scan_kubernetes calls execute with kubernetes framework."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_kubernetes("/app/k8s")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["kubernetes"]

    @pytest.mark.asyncio
    async def test_scan_dockerfile_calls_execute(self, executor):
        """scan_dockerfile calls execute with dockerfile framework."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_dockerfile("/app/Dockerfile")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["dockerfile"]
            # Should be file scan for Dockerfile
            assert call_kwargs["scan_type"] == "file"

    @pytest.mark.asyncio
    async def test_scan_dockerfile_directory(self, executor):
        """scan_dockerfile uses directory scan for non-Dockerfile paths."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_dockerfile("/app/docker")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["scan_type"] == "directory"

    @pytest.mark.asyncio
    async def test_scan_secrets_calls_execute(self, executor):
        """scan_secrets calls execute with secrets framework."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_secrets("/app/src")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["secrets"]
            assert call_kwargs["enable_secret_scan"] is True

    @pytest.mark.asyncio
    async def test_scan_github_actions_calls_execute(self, executor):
        """scan_github_actions calls execute with github_actions framework."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_github_actions("./.github/workflows")

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["github_actions"]

    @pytest.mark.asyncio
    async def test_list_checks_calls_execute(self, executor):
        """list_checks calls execute with --list flag."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.list_checks(framework="terraform")

            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[1].get("args", [])
            assert "--list" in call_args


class TestCheckovExecutorWithOverrides:
    """Test helper methods with parameter overrides."""

    @pytest.fixture
    def executor(self):
        """Create executor with default config."""
        return CheckovExecutor(CheckovConfig())

    @pytest.mark.asyncio
    async def test_scan_directory_with_frameworks(self, executor):
        """scan_directory accepts framework override."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_directory(
                "/app", frameworks=["terraform", "cloudformation"]
            )

            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["frameworks"] == ["terraform", "cloudformation"]

    @pytest.mark.asyncio
    async def test_scan_directory_with_checks(self, executor):
        """scan_directory accepts check filters."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_directory(
                "/app",
                run_checks=["CKV_AWS_18"],
                skip_checks=["CKV_AWS_1"],
            )

            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["run_checks"] == ["CKV_AWS_18"]
            assert call_kwargs["skip_checks"] == ["CKV_AWS_1"]

    @pytest.mark.asyncio
    async def test_scan_terraform_with_download_modules(self, executor):
        """scan_terraform accepts download_modules parameter."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_terraform("/app/terraform", download_modules=False)

            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["download_external_modules"] is False

    @pytest.mark.asyncio
    async def test_scan_secrets_with_skip_paths(self, executor):
        """scan_secrets accepts skip_paths parameter."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ("{}", "", 0)

            await executor.scan_secrets(
                "/app/src", skip_paths=["node_modules", ".git"]
            )

            call_kwargs = mock_exec.call_args[1]
            assert call_kwargs["skip_paths"] == ["node_modules", ".git"]


class TestImports:
    """Test module imports."""

    def test_import_from_checkov_package(self):
        """Config and Executor can be imported from checkov package."""
        from parrot.tools.security.checkov import CheckovConfig, CheckovExecutor

        assert CheckovConfig is not None
        assert CheckovExecutor is not None

    def test_import_from_security_package(self):
        """Config and Executor can be imported from security package."""
        from parrot.tools.security import CheckovConfig, CheckovExecutor

        assert CheckovConfig is not None
        assert CheckovExecutor is not None

    def test_instantiation(self):
        """Imported classes can be instantiated."""
        from parrot.tools.security import CheckovConfig, CheckovExecutor

        config = CheckovConfig(frameworks=["terraform"])
        executor = CheckovExecutor(config)
        assert executor._default_cli_name() == "checkov"
