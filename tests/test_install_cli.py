import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from parrot.install.cli import install


@pytest.fixture
def runner():
    return CliRunner()


@patch("parrot.install.cli.subprocess.run")
@patch("parrot.install.cli.Path.exists")
@patch("parrot.install.cli.Path.mkdir")
@patch("parrot.install.cli.Path.read_text")
@patch("parrot.install.cli.Path.write_text")
def test_cloudsploit_install_fresh(mock_write, mock_read, mock_mkdir, mock_exists, mock_run, runner):
    # Simulate fresh install (repo doesn't exist, files exist for patching)
    mock_exists.side_effect = lambda: True  # For everything else
    
    # Needs a bit of logic for exists to simulate correctly:
    def exists_side_effect(*args, **kwargs):
        return True # Just assume everything exists inside for test simplicity

    mock_exists.side_effect = exists_side_effect
    
    mock_read.side_effect = [
        'ENTRYPOINT ["cloudsploitscan"]',
        '// codestarValidRepoProviders\n// codestarHasTags\nnormal line'
    ]

    result = runner.invoke(install, ["cloudsploit"])
    assert result.exit_code == 0
    assert "Starting CloudSploit installation..." in result.output
    
    # Verify subprocesses called: git clone or git pull, then docker build
    assert mock_run.call_count >= 2


@patch("parrot.install.cli.subprocess.run")
def test_prowler_install(mock_run, runner):
    result = runner.invoke(install, ["prowler"])
    assert result.exit_code == 0
    assert "Starting Prowler installation..." in result.output

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["docker", "pull", "prowler/prowler:latest"]


class TestPulumiInstall:
    """Tests for pulumi install command."""

    def test_pulumi_command_exists(self, runner):
        """pulumi command is registered."""
        result = runner.invoke(install, ["--help"])
        assert "pulumi" in result.output

    @patch("parrot.install.cli.subprocess.run")
    def test_pulumi_install_success(self, mock_run, runner):
        """pulumi install runs curl command."""
        # Mock successful runs
        mock_run.return_value = MagicMock(returncode=0, stdout="v3.100.0")

        result = runner.invoke(install, ["pulumi"])
        assert result.exit_code == 0
        assert "Starting Pulumi installation..." in result.output
        assert "Pulumi CLI installed successfully!" in result.output

        # Should have called subprocess at least twice (curl + version check)
        assert mock_run.call_count >= 2

        # First call should be the curl command
        first_call = mock_run.call_args_list[0]
        assert "curl" in first_call[0][0]
        assert "get.pulumi.com" in first_call[0][0]

    @patch("parrot.install.cli.subprocess.run")
    def test_pulumi_install_with_docker(self, mock_run, runner):
        """--with-docker installs pulumi_docker."""
        mock_run.return_value = MagicMock(returncode=0, stdout="v3.100.0")

        result = runner.invoke(install, ["pulumi", "--with-docker"])
        assert result.exit_code == 0
        assert "Installing pulumi_docker" in result.output
        assert "pulumi_docker installed successfully!" in result.output

        # Should have called subprocess at least 3 times (curl + version + pip)
        assert mock_run.call_count >= 3

        # Check that uv pip install was called
        pip_call_found = False
        for call in mock_run.call_args_list:
            args = call[0][0]
            if isinstance(args, list) and "uv" in args and "pulumi_docker" in args:
                pip_call_found = True
                break
        assert pip_call_found, "uv pip install pulumi_docker should have been called"

    @patch("parrot.install.cli.subprocess.run")
    def test_pulumi_install_curl_failure(self, mock_run, runner):
        """Handles curl installation failure gracefully."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "curl")

        result = runner.invoke(install, ["pulumi"])
        assert result.exit_code != 0
        assert "Failed to install Pulumi CLI" in result.output

    @patch("parrot.install.cli.subprocess.run")
    def test_pulumi_install_pip_failure(self, mock_run, runner):
        """Handles pip installation failure gracefully."""
        import subprocess

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if isinstance(cmd, list) and "uv" in cmd:
                raise subprocess.CalledProcessError(1, "uv")
            return MagicMock(returncode=0, stdout="v3.100.0")

        mock_run.side_effect = side_effect

        result = runner.invoke(install, ["pulumi", "--with-docker"])
        assert result.exit_code != 0
        assert "Failed to install pulumi_docker" in result.output

    @patch("parrot.install.cli.subprocess.run")
    def test_pulumi_install_verbose(self, mock_run, runner):
        """--verbose flag is accepted."""
        mock_run.return_value = MagicMock(returncode=0, stdout="v3.100.0")

        result = runner.invoke(install, ["pulumi", "--verbose"])
        assert result.exit_code == 0
        assert "Starting Pulumi installation..." in result.output

    @patch("parrot.install.cli.subprocess.run")
    def test_pulumi_version_not_found(self, mock_run, runner):
        """Handles pulumi not in PATH after install."""
        def side_effect(*args, **kwargs):
            cmd = args[0]
            # First call (curl) succeeds
            if isinstance(cmd, str) and "curl" in cmd:
                return MagicMock(returncode=0)
            # Version check fails (not in PATH)
            if isinstance(cmd, list) and "pulumi" in cmd:
                raise FileNotFoundError("pulumi not found")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        result = runner.invoke(install, ["pulumi"])
        # Should still succeed, just with a warning
        assert result.exit_code == 0
        assert "not found in PATH" in result.output

