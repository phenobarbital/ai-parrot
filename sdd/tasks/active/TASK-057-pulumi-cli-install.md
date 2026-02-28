# TASK-057: Pulumi CLI Install Command

**Feature**: Pulumi Toolkit for Container Deployment
**Spec**: `sdd/specs/pulumi-toolkit-deployment.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec: CLI Install Command.

Add `parrot install pulumi` command to the existing CLI installation group. This allows users to easily install Pulumi CLI and optionally the `pulumi_docker` Python package.

---

## Scope

- Add `@install.command() pulumi` to `parrot/install/cli.py`
- Install Pulumi CLI via official installer: `curl -fsSL https://get.pulumi.com | sh`
- Add `--with-docker` flag to also install `pulumi_docker` Python package
- Add `--verbose` flag for detailed output
- Handle installation errors gracefully
- Write unit tests (mocked subprocess)

**NOT in scope**:
- Installing other Pulumi providers (AWS, GCP, etc.)
- Pulumi Cloud authentication setup
- Windows installation (Linux/macOS only)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/install/cli.py` | MODIFY | Add `pulumi` command |
| `tests/test_install_cli.py` | MODIFY | Add tests for pulumi install |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: existing commands in parrot/install/cli.py

@install.command()
@click.option("--verbose", is_flag=True, help="Enable verbose output")
@click.option("--with-docker", is_flag=True, help="Also install pulumi_docker package")
def pulumi(verbose, with_docker):
    """Install Pulumi CLI and optionally the Docker provider."""
    click.secho("Installing Pulumi CLI...", fg="green")

    # Install via official installer
    try:
        subprocess.run(
            "curl -fsSL https://get.pulumi.com | sh",
            shell=True,
            check=True,
            stdout=sys.stdout if verbose else subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        click.secho("Pulumi CLI installed successfully!", fg="green")
    except subprocess.CalledProcessError as e:
        click.secho("Failed to install Pulumi CLI.", fg="red")
        raise click.Abort()

    # Optionally install Docker provider
    if with_docker:
        click.echo("Installing pulumi_docker Python package...")
        try:
            subprocess.run(
                ["uv", "pip", "install", "pulumi_docker"],
                check=True,
                stdout=sys.stdout if verbose else subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
            click.secho("pulumi_docker installed successfully!", fg="green")
        except subprocess.CalledProcessError:
            click.secho("Failed to install pulumi_docker.", fg="red")
            raise click.Abort()

    click.secho("Installation complete!", fg="green")
```

### Key Constraints
- Use `uv pip install` (not `pip install`) per project guidelines
- Use `curl` for CLI installation (standard Pulumi approach)
- Provide clear error messages on failure
- Support `--verbose` for debugging

### References in Codebase
- `parrot/install/cli.py` — existing install commands (cloudsploit, prowler, scoutsuite)

---

## Acceptance Criteria

- [ ] `parrot install pulumi` command exists
- [ ] Installs Pulumi CLI via official curl script
- [ ] `--with-docker` flag installs `pulumi_docker` package
- [ ] `--verbose` shows detailed output
- [ ] Clear error messages on failure
- [ ] Unit tests pass: `pytest tests/test_install_cli.py -v -k pulumi`
- [ ] No linting errors: `ruff check parrot/install/cli.py`

---

## Test Specification

```python
# tests/test_install_cli.py (add to existing file)
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from parrot.install.cli import install


class TestPulumiInstall:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_pulumi_command_exists(self, runner):
        """pulumi command is registered."""
        result = runner.invoke(install, ["--help"])
        assert "pulumi" in result.output

    @patch("subprocess.run")
    def test_pulumi_install_success(self, mock_run, runner):
        """pulumi install runs curl command."""
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(install, ["pulumi"])
        assert result.exit_code == 0
        assert "Installing Pulumi CLI" in result.output

    @patch("subprocess.run")
    def test_pulumi_install_with_docker(self, mock_run, runner):
        """--with-docker installs pulumi_docker."""
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(install, ["pulumi", "--with-docker"])
        assert result.exit_code == 0
        # Should have called subprocess twice (CLI + pip)
        assert mock_run.call_count >= 2

    @patch("subprocess.run")
    def test_pulumi_install_failure(self, mock_run, runner):
        """Handles installation failure gracefully."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "curl")
        result = runner.invoke(install, ["pulumi"])
        assert result.exit_code != 0
        assert "Failed" in result.output
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-057-pulumi-cli-install.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
