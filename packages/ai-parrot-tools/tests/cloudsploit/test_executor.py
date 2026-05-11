"""Unit tests for CloudSploit Docker/CLI executor."""
import asyncio
import os

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from parrot.tools.cloudsploit.executor import CloudSploitExecutor
from parrot.tools.cloudsploit.models import CloudProvider, CloudSploitConfig, ComplianceFramework


@pytest.fixture
def config():
    return CloudSploitConfig(
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secret123",
        aws_region="us-east-1",
    )


@pytest.fixture
def executor(config):
    return CloudSploitExecutor(config)


class TestBuildEnvVars:
    def test_explicit_credentials(self, executor):
        env = executor._build_env_vars()
        assert env["AWS_ACCESS_KEY_ID"] == "AKIATEST"
        assert env["AWS_SECRET_ACCESS_KEY"] == "secret123"
        assert env["AWS_REGION"] == "us-east-1"
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"  # Defaults to same as aws_region
        assert env["AWS_SDK_LOAD_CONFIG"] == "1"
        assert "AWS_SESSION_TOKEN" not in env

    def test_with_session_token(self):
        config = CloudSploitConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
            aws_session_token="token-abc",
        )
        executor = CloudSploitExecutor(config)
        env = executor._build_env_vars()
        assert env["AWS_SESSION_TOKEN"] == "token-abc"

    def test_profile_credentials(self):
        config = CloudSploitConfig(aws_profile="production")
        executor = CloudSploitExecutor(config)
        env = executor._build_env_vars()
        assert env["AWS_PROFILE"] == "production"
        assert "AWS_ACCESS_KEY_ID" not in env

    def test_empty_credentials(self):
        config = CloudSploitConfig()
        executor = CloudSploitExecutor(config)
        env = executor._build_env_vars()
        assert env["AWS_REGION"] == "us-east-1"
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"  # Defaults from parrot.conf

    def test_gcp_provider_env_vars(self):
        config = CloudSploitConfig(
            cloud_provider=CloudProvider.GCP,
            gcp_project_id="demo-project",
            gcp_credentials_path="/tmp/gcp.json",
        )
        executor = CloudSploitExecutor(config)
        env = executor._build_env_vars()
        assert env["PROJECT"] == "demo-project"
        assert env["GOOGLE_APPLICATION_CREDENTIALS"] == "/tmp/gcp.json"
        assert "AWS_ACCESS_KEY_ID" not in env


    def test_both_explicit_and_profile(self):
        config = CloudSploitConfig(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
            aws_profile="myprofile",
        )
        executor = CloudSploitExecutor(config)
        env = executor._build_env_vars()
        assert "AWS_ACCESS_KEY_ID" in env
        assert "AWS_PROFILE" in env


class TestBuildDockerCommand:
    def test_docker_command_includes_env_vars(self, executor):
        cmd = executor._build_docker_command(["--json", "/dev/stdout"])
        assert cmd[0] == "docker"
        assert cmd[1] == "run"
        assert "--rm" in cmd
        assert "-e" in cmd
        assert "AWS_ACCESS_KEY_ID=AKIATEST" in cmd
        assert "AWS_SECRET_ACCESS_KEY=secret123" in cmd
        assert "AWS_REGION=us-east-1" in cmd
        assert "AWS_DEFAULT_REGION=us-east-1" in cmd  # Defaults from parrot.conf
        assert "AWS_SDK_LOAD_CONFIG=1" in cmd

    def test_docker_command_includes_image(self, executor):
        cmd = executor._build_docker_command(["--json", "/dev/stdout"])
        assert "cloudsploit:0.0.1" in cmd

    def test_docker_command_includes_args(self, executor):
        cmd = executor._build_docker_command(["--json", "/dev/stdout", "--ignore-ok"])
        assert cmd[-1] == "--ignore-ok"
        assert "--json" in cmd
        assert "/dev/stdout" in cmd

    def test_custom_docker_image(self):
        config = CloudSploitConfig(
            docker_image="my-registry/cloudsploit:v2",
            aws_access_key_id="KEY",
            aws_secret_access_key="SECRET",
        )
        executor = CloudSploitExecutor(config)
        cmd = executor._build_docker_command([])
        assert "my-registry/cloudsploit:v2" in cmd


class TestBuildDockerCommandMultiMount:
    def test_docker_command_no_mount(self):
        cfg = CloudSploitConfig()
        e = CloudSploitExecutor(cfg)
        cmd = e._build_docker_command(["--cloud=aws"], volume_mounts=None)
        assert "-v" not in cmd

    def test_docker_command_single_mount(self):
        e = CloudSploitExecutor(CloudSploitConfig())
        cmd = e._build_docker_command(["--cloud=aws"],
                                      volume_mounts=[("/h", "/c", None)])
        assert cmd.count("-v") == 1
        assert "/h:/c" in cmd

    def test_docker_command_read_only_mount(self):
        e = CloudSploitExecutor(CloudSploitConfig())
        cmd = e._build_docker_command(["--cloud=aws"],
                                      volume_mounts=[("/h", "/c", "ro")])
        assert "/h:/c:ro" in cmd

    def test_docker_command_multi_mount_order(self):
        e = CloudSploitExecutor(CloudSploitConfig())
        cmd = e._build_docker_command(
            ["--cloud=aws"],
            volume_mounts=[("/o", "/cloudsploit/output", None),
                           ("/cfgdir", "/cloudsploit/config", "ro")],
        )
        o_idx = cmd.index("/o:/cloudsploit/output")
        c_idx = cmd.index("/cfgdir:/cloudsploit/config:ro")
        assert o_idx < c_idx


class TestBuildCliArgs:
    JSON_PATH = "/tmp/results.json"
    COLLECTION_PATH = "/tmp/collection.json"

    def test_full_scan_defaults(self, executor):
        args = executor._build_cli_args(json_path=self.JSON_PATH)
        assert f"--json={self.JSON_PATH}" in args
        assert "--console=none" in args
        assert "--cloud=aws" in args

    def test_collection_flag(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, collection_path=self.COLLECTION_PATH,
        )
        assert f"--collection={self.COLLECTION_PATH}" in args

    def test_collection_omitted_when_none(self, executor):
        args = executor._build_cli_args(json_path=self.JSON_PATH)
        assert not any(a.startswith("--collection") for a in args)

    def test_compliance_flag(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, compliance=ComplianceFramework.PCI,
        )
        assert "--compliance=pci" in args

    def test_compliance_hipaa(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, compliance=ComplianceFramework.HIPAA,
        )
        assert "--compliance=hipaa" in args

    def test_compliance_cis1(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, compliance=ComplianceFramework.CIS1,
        )
        assert "--compliance=cis1" in args

    def test_compliance_cis2(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, compliance=ComplianceFramework.CIS2,
        )
        assert "--compliance=cis2" in args

    def test_single_plugin(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, plugins=["ec2-open-ssh"],
        )
        assert "--plugin" in args
        assert "ec2-open-ssh" in args

    def test_multiple_plugins(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH,
            plugins=["ec2-open-ssh", "s3-bucket-policy"],
        )
        assert args.count("--plugin") == 2
        assert "ec2-open-ssh" in args
        assert "s3-bucket-policy" in args

    def test_ignore_ok(self, executor):
        args = executor._build_cli_args(json_path=self.JSON_PATH, ignore_ok=True)
        assert "--ignore-ok" in args

    def test_ignore_ok_false(self, executor):
        args = executor._build_cli_args(json_path=self.JSON_PATH, ignore_ok=False)
        assert "--ignore-ok" not in args

    def test_suppress(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH, suppress=["pluginId:us-east-1:*"],
        )
        assert "--suppress" in args
        assert "pluginId:us-east-1:*" in args

    def test_multiple_suppress(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH,
            suppress=["pluginA:us-east-1:*", "pluginB:us-west-2:*"],
        )
        assert args.count("--suppress") == 2

    def test_govcloud_flag(self):
        config = CloudSploitConfig(govcloud=True)
        executor = CloudSploitExecutor(config)
        args = executor._build_cli_args(json_path=self.JSON_PATH)
        assert "--govcloud" in args

    def test_govcloud_off_by_default(self, executor):
        args = executor._build_cli_args(json_path=self.JSON_PATH)
        assert "--govcloud" not in args

    def test_gcp_cloud_arg(self):
        config = CloudSploitConfig(cloud_provider=CloudProvider.GCP, govcloud=True)
        executor = CloudSploitExecutor(config)
        args = executor._build_cli_args(json_path=self.JSON_PATH)
        assert "--cloud=google" in args
        assert "--govcloud" not in args

    def test_combined_args(self, executor):
        args = executor._build_cli_args(
            json_path=self.JSON_PATH,
            collection_path=self.COLLECTION_PATH,
            plugins=["ec2-open-ssh"],
            compliance=ComplianceFramework.PCI,
            ignore_ok=True,
            suppress=["rule:region:*"],
        )
        assert f"--json={self.JSON_PATH}" in args
        assert f"--collection={self.COLLECTION_PATH}" in args
        assert "--compliance=pci" in args
        assert "--plugin" in args
        assert "--ignore-ok" in args
        assert "--suppress" in args


class TestBuildDirectCommand:
    def test_default_cli_path(self):
        config = CloudSploitConfig(use_docker=False)
        executor = CloudSploitExecutor(config)
        cmd = executor._build_direct_command(["--json", "/dev/stdout"])
        assert cmd[0] == "cloudsploit"
        assert "--json" in cmd

    def test_custom_cli_path(self):
        config = CloudSploitConfig(
            use_docker=False,
            cli_path="/opt/cloudsploit/index.js",
        )
        executor = CloudSploitExecutor(config)
        cmd = executor._build_direct_command(["--json", "/dev/stdout"])
        assert cmd[0] == "/opt/cloudsploit/index.js"

    def test_env_vars_included(self):
        config = CloudSploitConfig(
            use_docker=False,
            aws_access_key_id="AKIA",
            aws_secret_access_key="SECRET",
        )
        executor = CloudSploitExecutor(config)
        env = executor._build_process_env()
        assert env["AWS_ACCESS_KEY_ID"] == "AKIA"
        assert env["AWS_SECRET_ACCESS_KEY"] == "SECRET"
        # Should also include inherited system env
        assert "PATH" in env


class TestMaskCredentials:
    def test_mask_access_key(self, executor):
        cmd = ["docker", "run", "-e", "AWS_ACCESS_KEY_ID=AKIATEST", "-e",
               "AWS_SECRET_ACCESS_KEY=secret123", "image", "--json", "/dev/stdout"]
        masked = executor._mask_command(cmd)
        assert "AKIATEST" not in masked
        assert "secret123" not in masked
        assert "AWS_ACCESS_KEY_ID=AKI***" in masked
        assert "AWS_SECRET_ACCESS_KEY=***" in masked

    def test_mask_session_token(self):
        config = CloudSploitConfig(
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            aws_session_token="long-session-token-here",
        )
        executor = CloudSploitExecutor(config)
        cmd = executor._build_docker_command(["--json", "/dev/stdout"])
        masked = executor._mask_command(cmd)
        assert "long-session-token-here" not in masked

    def test_no_credentials_to_mask(self):
        config = CloudSploitConfig()
        executor = CloudSploitExecutor(config)
        cmd = ["docker", "run", "--rm", "image", "--json", "/dev/stdout"]
        masked = executor._mask_command(cmd)
        assert "docker" in masked


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_docker_returns_stdout_stderr_exitcode(self, executor):
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"results": []}', b'scan complete')
        )
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            stdout, stderr, code = await executor.execute(["--json", "/dev/stdout"])
            assert code == 0
            assert '"results"' in stdout
            assert "scan complete" in stderr
            # Verify docker was called
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "docker"

    @pytest.mark.asyncio
    async def test_execute_direct_cli(self):
        config = CloudSploitConfig(
            use_docker=False,
            cli_path="/usr/local/bin/cloudsploit",
            aws_access_key_id="KEY",
            aws_secret_access_key="SECRET",
        )
        executor = CloudSploitExecutor(config)
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b'{"data": "ok"}', b'')
        )
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            stdout, stderr, code = await executor.execute(["--json", "/dev/stdout"])
            assert code == 0
            assert '"data"' in stdout
            # Verify direct CLI was called, not Docker
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "/usr/local/bin/cloudsploit"

    @pytest.mark.asyncio
    async def test_execute_nonzero_exit(self, executor):
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b'', b'Error: Docker not found')
        )
        mock_proc.returncode = 127
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            stdout, stderr, code = await executor.execute(["--json", "/dev/stdout"])
            assert code == 127
            assert "Error" in stderr

    @pytest.mark.asyncio
    async def test_timeout_raises(self, executor):
        executor.config.timeout_seconds = 1
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(
            side_effect=asyncio.TimeoutError("Scan timed out")
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await executor.execute(["--json", "/dev/stdout"])


class TestRunScan:
    """Tests for the temp-file-based scan runner.

    The executor materialises a temp dir and points CloudSploit at real
    files via ``--json`` and ``--collection``. Subprocess execution is
    mocked, so we write the expected output files ourselves from a side
    effect to simulate CloudSploit writing them.
    """

    @staticmethod
    def _make_proc(results_payload: bytes = b'{"pluginA": {"results": []}}',
                   collection_payload: bytes = b'{"aws": {}}',
                   stderr: bytes = b'') -> tuple[MagicMock, list[list[str]]]:
        """Build a mock subprocess that writes the expected output files."""
        captured_calls: list[list[str]] = []
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        async def _communicate():
            return (b'', stderr)

        mock_proc.communicate = _communicate

        def _materialise(*args, **kwargs):
            captured_calls.append(list(args))
            # When running through Docker the json/collection paths are
            # CONTAINER paths; translate them to the HOST tempdir using
            # the -v mount so the test can satisfy the file reads.
            host_dir = None
            container_dir = None
            for i, token in enumerate(args):
                if token == "-v" and i + 1 < len(args) and ":" in args[i + 1]:
                    host_dir, container_dir = args[i + 1].split(":", 1)
                    break

            def _to_host(path: str) -> str:
                if host_dir and container_dir and path.startswith(container_dir):
                    return host_dir + path[len(container_dir):]
                return path

            for token in args:
                if token.startswith("--json="):
                    with open(_to_host(token.split("=", 1)[1]), "wb") as fh:
                        fh.write(results_payload)
                elif token.startswith("--collection="):
                    with open(_to_host(token.split("=", 1)[1]), "wb") as fh:
                        fh.write(collection_payload)
            return mock_proc

        return mock_proc, captured_calls, _materialise

    @pytest.mark.asyncio
    async def test_run_scan_default(self, executor):
        executor.config.use_docker = False  # write directly to temp dir
        executor.config.cli_path = "/usr/local/bin/cloudsploit"
        mock_proc, captured, side_effect = self._make_proc()
        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            results, collection, _, stderr, code = await executor.run_scan()
        assert code == 0
        assert '"pluginA"' in results
        assert '"aws"' in collection
        call_str = " ".join(captured[0])
        assert "--json=" in call_str
        assert "--collection=" in call_str
        assert "--console=none" in call_str

    @pytest.mark.asyncio
    async def test_run_scan_with_plugins(self, executor):
        executor.config.use_docker = False
        executor.config.cli_path = "/usr/local/bin/cloudsploit"
        _, captured, side_effect = self._make_proc()
        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            await executor.run_scan(plugins=["ec2-open-ssh"])
        call_str = " ".join(captured[0])
        assert "--plugin" in call_str
        assert "ec2-open-ssh" in call_str

    @pytest.mark.asyncio
    async def test_run_scan_without_collection(self, executor):
        executor.config.use_docker = False
        executor.config.cli_path = "/usr/local/bin/cloudsploit"
        _, captured, side_effect = self._make_proc()
        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            _, collection, _, _, _ = await executor.run_scan(
                capture_collection=False,
            )
        assert collection == ""
        assert not any("--collection" in a for a in captured[0])

    @pytest.mark.asyncio
    async def test_run_compliance_scan(self, executor):
        executor.config.use_docker = False
        executor.config.cli_path = "/usr/local/bin/cloudsploit"
        _, captured, side_effect = self._make_proc()
        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            await executor.run_compliance_scan(ComplianceFramework.HIPAA)
        call_str = " ".join(captured[0])
        assert "--compliance=hipaa" in call_str
        assert "--ignore-ok" in call_str

    @pytest.mark.asyncio
    async def test_run_scan_docker_mounts_output_volume(self, executor):
        executor.config.use_docker = True
        _, captured, side_effect = self._make_proc()
        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            await executor.run_scan()
        cmd = captured[0]
        # docker run ... -v <host>:/cloudsploit/output
        assert cmd[0] == "docker"
        assert "-v" in cmd
        v_idx = cmd.index("-v")
        host_dir, container_dir = cmd[v_idx + 1].split(":")
        assert container_dir == "/cloudsploit/output"
        # Host dir is a real tempdir created and removed by the executor
        # (no longer exists after the context manager exits).
        joined = " ".join(cmd)
        assert "--json=/cloudsploit/output/results.json" in joined
        assert "--collection=/cloudsploit/output/collection.json" in joined
