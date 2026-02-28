# Feature Specification: Pulumi Toolkit for Container Deployment

**Feature ID**: FEAT-013
**Date**: 2026-02-28
**Author**: claude-session
**Status**: approved
**Target version**: 1.x.x
**Brainstorm**: `sdd/proposals/pulumi-toolkit-deployment.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI agents need the ability to deploy and manage containerized applications as part of their workflows. Currently, there's no infrastructure-as-code (IaC) toolkit in AI-Parrot that allows agents to:

1. **Plan deployments** before executing them (preview changes)
2. **Apply infrastructure changes** declaratively
3. **Destroy resources** when no longer needed
4. **Check status** of deployed infrastructure

The primary use case is **rapid prototyping of image deployments** — allowing agents to spin up containers (e.g., databases, services, test environments) on-demand using Docker/Docker Compose as the initial provider.

### Goals
- Implement `PulumiToolkit` inheriting from `AbstractToolkit`
- Expose `pulumi_plan`, `pulumi_apply`, `pulumi_destroy`, `pulumi_status` as agent tools
- Start with Docker/Docker Compose provider for simplicity
- Add CLI installation via `parrot install pulumi`
- Enable agents to deploy containers through conversational interaction

### Non-Goals (explicitly out of scope)
- Cloud provider support (AWS, GCP, Azure) — future enhancement
- Kubernetes provider support — future enhancement
- Custom Pulumi program generation by AI — future enhancement
- Pulumi Cloud state backend integration — use local state initially
- Multi-stack orchestration — single stack per operation

---

## 2. Architectural Design

### Overview

Follow the **CLI-Based Executor Pattern** established by security toolkits (Checkov, Prowler, Trivy). The toolkit wraps the Pulumi CLI as an executor with structured input/output parsing.

This approach:
- Works with any Pulumi language (YAML, Python, TypeScript, Go)
- Reuses battle-tested `BaseExecutor` infrastructure
- Provides consistent debugging experience via CLI output
- Supports Docker execution mode as fallback

### Component Diagram
```
┌─────────────────────────────────────────────────────────────┐
│                      PulumiToolkit                          │
│  (AbstractToolkit subclass)                                 │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ pulumi_plan │  │pulumi_apply │  │pulumi_destroy│         │
│  │ pulumi_status│              │                 │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          ▼                                  │
│              ┌───────────────────────┐                      │
│              │    PulumiExecutor     │                      │
│              │   (BaseExecutor)      │                      │
│              ├───────────────────────┤                      │
│              │ _build_cli_args()     │                      │
│              │ _parse_json_output()  │                      │
│              │ preview() / up()      │                      │
│              │ destroy() / stack()   │                      │
│              └───────────┬───────────┘                      │
│                          │                                  │
│                          ▼                                  │
│              ┌───────────────────────┐                      │
│              │   asyncio.subprocess  │                      │
│              │   pulumi preview/up   │                      │
│              └───────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Base class for toolkit with auto tool generation |
| `BaseExecutor` | extends | CLI execution pattern from security toolkits |
| `BaseExecutorConfig` | extends | Configuration with Docker/CLI modes |
| `parrot/install/cli.py` | modifies | Add `@install.command() pulumi` |
| `ToolRegistry` | uses | Register toolkit for agent discovery |

### Data Models
```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from parrot.tools.security.base_executor import BaseExecutorConfig


class PulumiConfig(BaseExecutorConfig):
    """Configuration for Pulumi executor."""

    docker_image: str = Field(
        default="pulumi/pulumi:latest",
        description="Docker image for Pulumi execution"
    )
    default_stack: str = Field(
        default="dev",
        description="Default stack name if not specified"
    )
    auto_create_stack: bool = Field(
        default=True,
        description="Auto-create stack if it doesn't exist"
    )
    state_backend: str = Field(
        default="local",
        description="State backend: 'local' or 'file://<path>'"
    )


class PulumiPlanInput(BaseModel):
    """Input for pulumi_plan operation."""

    project_path: str = Field(
        ..., description="Path to Pulumi project directory"
    )
    stack_name: Optional[str] = Field(
        None, description="Stack name (defaults to 'dev')"
    )
    config: Optional[Dict[str, Any]] = Field(
        None, description="Configuration values to set"
    )


class PulumiApplyInput(BaseModel):
    """Input for pulumi_apply operation."""

    project_path: str = Field(
        ..., description="Path to Pulumi project directory"
    )
    stack_name: Optional[str] = Field(
        None, description="Stack name (defaults to 'dev')"
    )
    config: Optional[Dict[str, Any]] = Field(
        None, description="Configuration values to set"
    )
    auto_approve: bool = Field(
        default=True, description="Skip confirmation prompt"
    )


class PulumiDestroyInput(BaseModel):
    """Input for pulumi_destroy operation."""

    project_path: str = Field(
        ..., description="Path to Pulumi project directory"
    )
    stack_name: Optional[str] = Field(
        None, description="Stack name (defaults to 'dev')"
    )
    auto_approve: bool = Field(
        default=True, description="Skip confirmation prompt"
    )


class PulumiStatusInput(BaseModel):
    """Input for pulumi_status operation."""

    project_path: str = Field(
        ..., description="Path to Pulumi project directory"
    )
    stack_name: Optional[str] = Field(
        None, description="Stack name (defaults to 'dev')"
    )


class PulumiResource(BaseModel):
    """A resource in Pulumi state."""

    urn: str
    type: str
    name: str
    status: str  # create, update, delete, same
    outputs: Optional[Dict[str, Any]] = None


class PulumiOperationResult(BaseModel):
    """Result of a Pulumi operation."""

    success: bool
    operation: str  # preview, up, destroy, stack
    resources: List[PulumiResource] = []
    outputs: Dict[str, Any] = {}
    summary: Dict[str, int] = {}  # {create: N, update: N, delete: N, same: N}
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
```

### New Public Interfaces
```python
class PulumiToolkit(AbstractToolkit):
    """Toolkit for infrastructure deployment using Pulumi.

    Each public method is exposed as a separate tool with the `pulumi_` prefix.

    Available Operations:
    - pulumi_plan: Preview infrastructure changes without applying
    - pulumi_apply: Apply infrastructure changes
    - pulumi_destroy: Tear down infrastructure
    - pulumi_status: Check current stack state

    Example:
        toolkit = PulumiToolkit()
        tools = toolkit.get_tools()

        # Use with agent
        agent = Agent(tools=tools)
    """

    async def pulumi_plan(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> PulumiOperationResult:
        """Preview infrastructure changes without applying.

        Args:
            project_path: Path to Pulumi project directory
            stack_name: Stack name (defaults to 'dev')
            config: Configuration values to set

        Returns:
            Preview result with resources to be created/updated/deleted
        """
        ...

    async def pulumi_apply(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_approve: bool = True
    ) -> PulumiOperationResult:
        """Apply infrastructure changes.

        Args:
            project_path: Path to Pulumi project directory
            stack_name: Stack name (defaults to 'dev')
            config: Configuration values to set
            auto_approve: Skip confirmation prompt

        Returns:
            Apply result with created/updated resources and outputs
        """
        ...

    async def pulumi_destroy(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        auto_approve: bool = True
    ) -> PulumiOperationResult:
        """Tear down infrastructure.

        Args:
            project_path: Path to Pulumi project directory
            stack_name: Stack name (defaults to 'dev')
            auto_approve: Skip confirmation prompt

        Returns:
            Destroy result with deleted resources
        """
        ...

    async def pulumi_status(
        self,
        project_path: str,
        stack_name: Optional[str] = None
    ) -> PulumiOperationResult:
        """Check current stack state.

        Args:
            project_path: Path to Pulumi project directory
            stack_name: Stack name (defaults to 'dev')

        Returns:
            Current resources and their states
        """
        ...
```

---

## 3. Module Breakdown

### Module 1: Pulumi Configuration
- **Path**: `parrot/tools/pulumi/config.py`
- **Responsibility**: Define `PulumiConfig` extending `BaseExecutorConfig` with Pulumi-specific settings
- **Depends on**: `parrot/tools/security/base_executor.py`

### Module 2: Pulumi Executor
- **Path**: `parrot/tools/pulumi/executor.py`
- **Responsibility**: CLI argument building, subprocess execution, JSON output parsing
- **Depends on**: Module 1, `BaseExecutor`

### Module 3: Pulumi Toolkit
- **Path**: `parrot/tools/pulumi/toolkit.py`
- **Responsibility**: `AbstractToolkit` subclass exposing plan/apply/destroy/status as tools
- **Depends on**: Module 2

### Module 4: CLI Install Command
- **Path**: `parrot/install/cli.py` (modify)
- **Responsibility**: Add `parrot install pulumi` command
- **Depends on**: None (extends existing CLI)

### Module 5: Package Init
- **Path**: `parrot/tools/pulumi/__init__.py`
- **Responsibility**: Export `PulumiToolkit`, `PulumiConfig`, register with toolkit registry
- **Depends on**: Modules 1-3

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_config_defaults` | Module 1 | Validates default configuration values |
| `test_config_docker_image` | Module 1 | Custom Docker image configuration |
| `test_executor_build_preview_args` | Module 2 | CLI args for `pulumi preview` |
| `test_executor_build_up_args` | Module 2 | CLI args for `pulumi up --yes --json` |
| `test_executor_build_destroy_args` | Module 2 | CLI args for `pulumi destroy` |
| `test_executor_parse_json_output` | Module 2 | Parse Pulumi JSON output to models |
| `test_toolkit_get_tools` | Module 3 | All 4 tools exposed correctly |
| `test_toolkit_plan_validates_path` | Module 3 | Returns error for missing project |
| `test_toolkit_plan_creates_stack` | Module 3 | Auto-creates stack when missing |

### Integration Tests
| Test | Description |
|---|---|
| `test_pulumi_plan_docker_project` | Plan a Docker container deployment |
| `test_pulumi_apply_and_destroy` | Full lifecycle: apply then destroy |
| `test_pulumi_status_after_apply` | Status shows deployed resources |
| `test_install_pulumi_cli` | CLI installation command works |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_docker_project(tmp_path):
    """Create a minimal Pulumi Docker project."""
    project_dir = tmp_path / "pulumi-docker-test"
    project_dir.mkdir()

    # Pulumi.yaml
    (project_dir / "Pulumi.yaml").write_text("""
name: test-docker-project
runtime: yaml
""")

    # Pulumi.dev.yaml (stack config)
    (project_dir / "Pulumi.dev.yaml").write_text("""
config: {}
""")

    # Main.yaml (resources)
    (project_dir / "Main.yaml").write_text("""
resources:
  redis:
    type: docker:Container
    properties:
      name: test-redis
      image: redis:alpine
      ports:
        - internal: 6379
          external: 6379
outputs:
  containerId: ${redis.id}
""")

    return project_dir


@pytest.fixture
def mock_pulumi_output():
    """Mock Pulumi JSON output for testing parsers."""
    return {
        "version": 3,
        "deployment": {
            "resources": [
                {
                    "urn": "urn:pulumi:dev::test::docker:index/container:Container::redis",
                    "type": "docker:index/container:Container",
                    "custom": True,
                    "outputs": {"id": "abc123", "name": "test-redis"}
                }
            ]
        }
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `PulumiToolkit` class exists and inherits from `AbstractToolkit`
- [ ] `pulumi_plan` tool previews changes and returns structured diff
- [ ] `pulumi_apply` tool applies changes with `--yes --json` flags
- [ ] `pulumi_destroy` tool tears down resources safely
- [ ] `pulumi_status` tool returns current stack state
- [ ] `parrot install pulumi` installs Pulumi CLI via official installer
- [ ] `parrot install pulumi` optionally installs `pulumi_docker` pip package
- [ ] All unit tests pass: `pytest tests/tools/pulumi/ -v`
- [ ] Integration test deploys and destroys a Docker container
- [ ] Docker execution mode works when CLI not installed locally
- [ ] JSON output parsing handles all Pulumi output formats
- [ ] Error handling returns actionable messages (not stack traces)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `BaseExecutor` pattern from `parrot/tools/security/base_executor.py`
- Follow `ECSToolkit` style for async infrastructure methods
- Use `@tool_schema` decorator for input validation
- Pydantic models for all inputs/outputs
- Comprehensive logging with `self.logger`

### Known Risks / Gotchas
- **State management**: Local state files can be lost; document backup recommendations
- **Docker daemon**: Must be running for Docker provider; detect and give clear error
- **Concurrent operations**: Pulumi uses lock files; surface lock errors clearly
- **Long-running operations**: Large deployments may timeout; make timeout configurable

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pulumi` (CLI) | `>=3.0` | Core Pulumi CLI for operations |
| `pulumi_docker` | `>=4.0` | Docker provider (optional, for Python programs) |

### CLI Installation Command
```python
@install.command()
@click.option("--verbose", is_flag=True, help="Enable verbose output")
@click.option("--with-docker", is_flag=True, help="Also install pulumi_docker package")
def pulumi(verbose, with_docker):
    """Install Pulumi CLI and optionally the Docker provider."""
    click.secho("Installing Pulumi CLI...", fg="green")

    # Install Pulumi CLI via official installer
    subprocess.run(
        "curl -fsSL https://get.pulumi.com | sh",
        shell=True,
        check=True,
        ...
    )

    if with_docker:
        click.echo("Installing pulumi_docker Python package...")
        subprocess.run(
            ["uv", "pip", "install", "pulumi_docker"],
            check=True,
            ...
        )
```

---

## 7. Open Questions

- [ ] **State backend**: Should we default to local file state or offer Pulumi Cloud integration? — *Owner: architect*: local file.
- [ ] **Multi-stack**: How to handle projects with multiple stacks (dev/staging/prod) in one operation? — *Owner: architect*: not handle multi-stack in one operation.
- [ ] **Secrets**: How to pass secrets to Pulumi programs securely (env vars vs config)? — *Owner: security*: env vars.
- [ ] **Resource quotas**: Should we limit what resources agents can create to prevent runaway costs? — *Owner: platform*: No

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-28 | claude-session | Initial draft from brainstorm |
