"""Unit tests for the Trivy executor."""

from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.security.trivy.config import TrivyConfig
from parrot.tools.security.trivy.executor import TrivyExecutor


class TestTrivyConfig:
    """Test TrivyConfig model."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = TrivyConfig()
        assert config.docker_image == "aquasec/trivy:latest"
        assert "CRITICAL" in config.severity_filter
        assert "HIGH" in config.severity_filter
        assert "vuln" in config.scanners
        assert "secret" in config.scanners
        assert config.output_format == "json"
        assert config.ignore_unfixed is False

    def test_custom_severity(self):
        """Custom severity filter."""
        config = TrivyConfig(severity_filter=["CRITICAL", "HIGH", "MEDIUM"])
        assert len(config.severity_filter) == 3
        assert "MEDIUM" in config.severity_filter

    def test_custom_scanners(self):
        """Custom scanner types."""
        config = TrivyConfig(scanners=["vuln", "misconfig", "secret", "license"])
        assert len(config.scanners) == 4
        assert "license" in config.scanners

    def test_custom_docker_image(self):
        """Custom Docker image."""
        config = TrivyConfig(docker_image="aquasec/trivy:0.48.0")
        assert config.docker_image == "aquasec/trivy:0.48.0"

    def test_cache_options(self):
        """Cache configuration options."""
        config = TrivyConfig(
            cache_dir="/tmp/trivy-cache",
            db_skip_update=True,
        )
        assert config.cache_dir == "/tmp/trivy-cache"
        assert config.db_skip_update is True

    def test_kubernetes_options(self):
        """Kubernetes configuration options."""
        config = TrivyConfig(
            k8s_context="my-cluster",
            k8s_namespace="production",
            k8s_components=["workload", "infra", "rbac"],
        )
        assert config.k8s_context == "my-cluster"
        assert config.k8s_namespace == "production"
        assert "rbac" in config.k8s_components

    def test_compliance_option(self):
        """Compliance specification option."""
        config = TrivyConfig(compliance="docker-cis-1.6.0")
        assert config.compliance == "docker-cis-1.6.0"

    def test_skip_options(self):
        """Skip directories and files options."""
        config = TrivyConfig(
            skip_dirs=["/app/vendor", "/app/node_modules"],
            skip_files=["*.test.js"],
        )
        assert len(config.skip_dirs) == 2
        assert len(config.skip_files) == 1


class TestTrivyExecutorCliArgs:
    """Test TrivyExecutor CLI argument building."""

    @pytest.fixture
    def executor(self):
        config = TrivyConfig(
            severity_filter=["CRITICAL", "HIGH"],
            scanners=["vuln", "secret"],
        )
        return TrivyExecutor(config)

    def test_build_image_scan_args(self, executor):
        """Image scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="image", target="nginx:latest")

        assert args[0] == "image"
        assert "--format" in args
        assert "json" in args
        assert "--severity" in args
        # Find the severity value
        sev_idx = args.index("--severity")
        assert "CRITICAL,HIGH" in args[sev_idx + 1]
        assert "--scanners" in args
        assert "nginx:latest" in args

    def test_build_fs_scan_args(self, executor):
        """Filesystem scan CLI args are built correctly."""
        args = executor._build_cli_args(scan_type="fs", target="/app")

        assert args[0] == "fs"
        assert "/app" in args
        assert "--format" in args
        assert "--severity" in args

    def test_build_repo_scan_args(self, executor):
        """Repository scan CLI args are built correctly."""
        args = executor._build_cli_args(
            scan_type="repo",
            target="https://github.com/org/repo.git",
        )

        assert args[0] == "repo"
        assert "https://github.com/org/repo.git" in args

    def test_build_config_scan_args(self, executor):
        """Config scan CLI args are built correctly."""
        args = executor._build_cli_args(
            scan_type="config",
            target="./terraform",
        )

        assert args[0] == "config"
        assert "./terraform" in args

    def test_build_k8s_scan_args(self, executor):
        """Kubernetes scan CLI args are built correctly."""
        args = executor._build_cli_args(
            scan_type="k8s",
            target="cluster",
            k8s_context="my-context",
            k8s_namespace="default",
        )

        assert args[0] == "k8s"
        assert "--context" in args
        ctx_idx = args.index("--context")
        assert args[ctx_idx + 1] == "my-context"
        assert "--namespace" in args
        ns_idx = args.index("--namespace")
        assert args[ns_idx + 1] == "default"
        assert "cluster" in args

    def test_build_sbom_args(self, executor):
        """SBOM generation CLI args are built correctly."""
        args = executor._build_cli_args(
            scan_type="image",
            target="myapp:v1",
            sbom_format="cyclonedx",
        )

        assert "--format" in args
        fmt_idx = args.index("--format")
        assert args[fmt_idx + 1] == "cyclonedx"

    def test_ignore_unfixed_flag(self):
        """ignore_unfixed flag is included."""
        config = TrivyConfig(ignore_unfixed=True)
        executor = TrivyExecutor(config)
        args = executor._build_cli_args(scan_type="image", target="test:latest")

        assert "--ignore-unfixed" in args

    def test_compliance_flag(self, executor):
        """Compliance flag is included when specified."""
        args = executor._build_cli_args(
            scan_type="k8s",
            target="cluster",
            compliance="k8s-cis-1.23",
        )

        assert "--compliance" in args
        comp_idx = args.index("--compliance")
        assert args[comp_idx + 1] == "k8s-cis-1.23"

    def test_skip_db_update_flag(self):
        """Skip DB update flag is included."""
        config = TrivyConfig(db_skip_update=True)
        executor = TrivyExecutor(config)
        args = executor._build_cli_args(scan_type="image", target="test:latest")

        assert "--skip-db-update" in args

    def test_cache_dir_option(self):
        """Cache directory option is included."""
        config = TrivyConfig(cache_dir="/tmp/trivy-cache")
        executor = TrivyExecutor(config)
        args = executor._build_cli_args(scan_type="image", target="test:latest")

        assert "--cache-dir" in args
        cache_idx = args.index("--cache-dir")
        assert args[cache_idx + 1] == "/tmp/trivy-cache"

    def test_skip_dirs_option(self):
        """Skip directories option is included."""
        config = TrivyConfig(skip_dirs=["/app/vendor", "/app/node_modules"])
        executor = TrivyExecutor(config)
        args = executor._build_cli_args(scan_type="fs", target="/app")

        skip_count = args.count("--skip-dirs")
        assert skip_count == 2

    def test_default_cli_name(self, executor):
        """Default CLI name is 'trivy'."""
        assert executor._default_cli_name() == "trivy"

    def test_output_file_option(self):
        """Output file option is included."""
        config = TrivyConfig(output_file="/tmp/results.json")
        executor = TrivyExecutor(config)
        args = executor._build_cli_args(scan_type="image", target="test:latest")

        assert "--output" in args
        out_idx = args.index("--output")
        assert args[out_idx + 1] == "/tmp/results.json"


class TestTrivyExecutorHelpers:
    """Test TrivyExecutor helper methods."""

    @pytest.fixture
    def executor(self):
        return TrivyExecutor(TrivyConfig())

    def test_scan_image_exists(self, executor):
        """scan_image helper exists."""
        assert hasattr(executor, "scan_image")
        assert callable(executor.scan_image)

    def test_scan_filesystem_exists(self, executor):
        """scan_filesystem helper exists."""
        assert hasattr(executor, "scan_filesystem")
        assert callable(executor.scan_filesystem)

    def test_scan_repository_exists(self, executor):
        """scan_repository helper exists."""
        assert hasattr(executor, "scan_repository")
        assert callable(executor.scan_repository)

    def test_scan_config_exists(self, executor):
        """scan_config helper exists."""
        assert hasattr(executor, "scan_config")
        assert callable(executor.scan_config)

    def test_scan_k8s_exists(self, executor):
        """scan_k8s helper exists."""
        assert hasattr(executor, "scan_k8s")
        assert callable(executor.scan_k8s)

    def test_generate_sbom_exists(self, executor):
        """generate_sbom helper exists."""
        assert hasattr(executor, "generate_sbom")
        assert callable(executor.generate_sbom)

    @pytest.mark.asyncio
    async def test_scan_image_calls_execute(self, executor):
        """scan_image calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"Results": []}', "", 0)

            await executor.scan_image("nginx:latest")

            mock.assert_called_once()
            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["scan_type"] == "image"
            assert call_kwargs["target"] == "nginx:latest"

    @pytest.mark.asyncio
    async def test_scan_image_with_options(self, executor):
        """scan_image passes through options."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"Results": []}', "", 0)

            await executor.scan_image(
                "nginx:latest",
                severity=["CRITICAL"],
                ignore_unfixed=True,
                scanners=["vuln"],
            )

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["severity_filter"] == ["CRITICAL"]
            assert call_kwargs["ignore_unfixed"] is True
            assert call_kwargs["scanners"] == ["vuln"]

    @pytest.mark.asyncio
    async def test_scan_filesystem_calls_execute(self, executor):
        """scan_filesystem calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"Results": []}', "", 0)

            await executor.scan_filesystem("/app")

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["scan_type"] == "fs"
            assert call_kwargs["target"] == "/app"

    @pytest.mark.asyncio
    async def test_scan_k8s_calls_execute(self, executor):
        """scan_k8s calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"Results": []}', "", 0)

            await executor.scan_k8s(
                context="prod-cluster",
                namespace="default",
                compliance="k8s-cis-1.23",
            )

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["scan_type"] == "k8s"
            assert call_kwargs["target"] == "cluster"
            assert call_kwargs["k8s_context"] == "prod-cluster"
            assert call_kwargs["k8s_namespace"] == "default"
            assert call_kwargs["compliance"] == "k8s-cis-1.23"

    @pytest.mark.asyncio
    async def test_generate_sbom_calls_execute(self, executor):
        """generate_sbom calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"bomFormat": "CycloneDX"}', "", 0)

            await executor.generate_sbom(
                "myapp:v1",
                sbom_format="cyclonedx",
                output_file="/tmp/sbom.json",
            )

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["scan_type"] == "image"
            assert call_kwargs["target"] == "myapp:v1"
            assert call_kwargs["sbom_format"] == "cyclonedx"
            assert call_kwargs["output_file"] == "/tmp/sbom.json"

    @pytest.mark.asyncio
    async def test_scan_config_calls_execute(self, executor):
        """scan_config calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"Results": []}', "", 0)

            await executor.scan_config(
                "./terraform",
                compliance="aws-cis-1.4.0",
            )

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["scan_type"] == "config"
            assert call_kwargs["target"] == "./terraform"
            assert call_kwargs["compliance"] == "aws-cis-1.4.0"

    @pytest.mark.asyncio
    async def test_scan_repository_calls_execute(self, executor):
        """scan_repository calls execute with correct args."""
        with patch.object(executor, "execute", new_callable=AsyncMock) as mock:
            mock.return_value = ('{"Results": []}', "", 0)

            await executor.scan_repository(
                "https://github.com/org/repo.git",
                branch="main",
            )

            call_kwargs = mock.call_args.kwargs
            assert call_kwargs["scan_type"] == "repo"
            # Branch should be appended to URL
            assert "main" in call_kwargs["target"]


class TestTrivyExecutorDockerMode:
    """Test TrivyExecutor in Docker mode."""

    def test_docker_mode_default(self):
        """Docker mode is enabled by default."""
        config = TrivyConfig()
        assert config.use_docker is True

    def test_direct_mode(self):
        """Direct CLI mode can be configured."""
        config = TrivyConfig(use_docker=False, cli_path="/usr/local/bin/trivy")
        executor = TrivyExecutor(config)
        assert executor.config.use_docker is False
        assert executor.config.cli_path == "/usr/local/bin/trivy"


class TestImports:
    """Test module imports."""

    def test_import_from_trivy_package(self):
        """Components can be imported from trivy package."""
        from parrot.tools.security.trivy import TrivyConfig, TrivyExecutor

        assert TrivyConfig is not None
        assert TrivyExecutor is not None

    def test_import_from_security_package(self):
        """Components can be imported from security package."""
        from parrot.tools.security import TrivyConfig, TrivyExecutor

        executor = TrivyExecutor(TrivyConfig())
        assert executor is not None
