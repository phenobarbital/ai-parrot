"""Pulumi configuration and data models.

Defines configuration options for running Pulumi operations including
stack management, state backend, and input/output models for all
Pulumi operations (plan, apply, destroy, status).
"""

from typing import Any, Optional

from pydantic import BaseModel, Field

# Import directly from module to avoid security package __init__.py chain
from parrot.tools.security.base_executor import BaseExecutorConfig


class PulumiConfig(BaseExecutorConfig):
    """Configuration for Pulumi executor.

    Extends BaseExecutorConfig with Pulumi-specific settings for
    stack management, state backend, and Docker execution.

    Example:
        config = PulumiConfig(
            default_stack="staging",
            auto_create_stack=True,
            state_backend="local",
        )
    """

    # Docker image for Pulumi
    docker_image: str = Field(
        default="pulumi/pulumi:latest",
        description="Docker image for Pulumi execution",
    )

    # Stack management
    default_stack: str = Field(
        default="dev",
        description="Default stack name if not specified in operation",
    )
    auto_create_stack: bool = Field(
        default=True,
        description="Automatically create stack if it doesn't exist",
    )

    # State backend
    state_backend: str = Field(
        default="local",
        description="State backend: 'local' or 'file://<path>'",
    )

    # Pulumi-specific options
    pulumi_home: Optional[str] = Field(
        default=None,
        description="Path to Pulumi home directory (for credentials and state)",
    )
    config_passphrase: Optional[str] = Field(
        default=None,
        description="Passphrase for encrypting stack configuration secrets",
    )
    non_interactive: bool = Field(
        default=True,
        description="Run in non-interactive mode (no prompts)",
    )
    skip_preview: bool = Field(
        default=False,
        description="Skip the preview step before applying changes",
    )

    model_config = {"extra": "ignore"}


# --- Input Models ---


class PulumiPlanInput(BaseModel):
    """Input for pulumi_plan operation.

    Used to preview infrastructure changes without applying them.
    Returns a detailed diff of resources to be created, updated, or deleted.
    """

    project_path: str = Field(
        ...,
        description="Path to Pulumi project directory containing Pulumi.yaml",
    )
    stack_name: Optional[str] = Field(
        default=None,
        description="Stack name to preview (defaults to config.default_stack)",
    )
    config: Optional[dict[str, Any]] = Field(
        default=None,
        description="Configuration values to set before preview (key-value pairs)",
    )
    target: Optional[list[str]] = Field(
        default=None,
        description="Specific resource URNs to target for preview",
    )
    refresh: bool = Field(
        default=True,
        description="Refresh resource state before preview",
    )


class PulumiApplyInput(BaseModel):
    """Input for pulumi_apply operation.

    Used to apply infrastructure changes. By default runs with auto_approve=True
    to avoid interactive prompts in agent workflows.
    """

    project_path: str = Field(
        ...,
        description="Path to Pulumi project directory containing Pulumi.yaml",
    )
    stack_name: Optional[str] = Field(
        default=None,
        description="Stack name to apply (defaults to config.default_stack)",
    )
    config: Optional[dict[str, Any]] = Field(
        default=None,
        description="Configuration values to set before apply (key-value pairs)",
    )
    auto_approve: bool = Field(
        default=True,
        description="Skip confirmation prompt and apply immediately",
    )
    target: Optional[list[str]] = Field(
        default=None,
        description="Specific resource URNs to target for apply",
    )
    refresh: bool = Field(
        default=True,
        description="Refresh resource state before apply",
    )
    replace: Optional[list[str]] = Field(
        default=None,
        description="Resource URNs to force-replace during apply",
    )


class PulumiDestroyInput(BaseModel):
    """Input for pulumi_destroy operation.

    Used to tear down infrastructure. By default runs with auto_approve=True
    to avoid interactive prompts in agent workflows.
    """

    project_path: str = Field(
        ...,
        description="Path to Pulumi project directory containing Pulumi.yaml",
    )
    stack_name: Optional[str] = Field(
        default=None,
        description="Stack name to destroy (defaults to config.default_stack)",
    )
    auto_approve: bool = Field(
        default=True,
        description="Skip confirmation prompt and destroy immediately",
    )
    target: Optional[list[str]] = Field(
        default=None,
        description="Specific resource URNs to target for destruction",
    )


class PulumiStatusInput(BaseModel):
    """Input for pulumi_status operation.

    Used to check the current state of a stack including deployed resources
    and their outputs.
    """

    project_path: str = Field(
        ...,
        description="Path to Pulumi project directory containing Pulumi.yaml",
    )
    stack_name: Optional[str] = Field(
        default=None,
        description="Stack name to check (defaults to config.default_stack)",
    )
    show_urns: bool = Field(
        default=False,
        description="Include full URNs in resource listing",
    )


# --- Output Models ---


class PulumiResource(BaseModel):
    """A resource in Pulumi state.

    Represents a single resource managed by Pulumi, including its
    type, name, current status, and outputs.
    """

    urn: str = Field(
        ...,
        description="Unique resource name (URN) in format urn:pulumi:stack::project::type::name",
    )
    type: str = Field(
        ...,
        description="Resource type (e.g., docker:index/container:Container)",
    )
    name: str = Field(
        ...,
        description="Logical resource name in the Pulumi program",
    )
    status: str = Field(
        ...,
        description="Resource status: 'create', 'update', 'delete', 'same', 'replace'",
    )
    outputs: Optional[dict[str, Any]] = Field(
        default=None,
        description="Resource outputs (properties computed after creation)",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider managing this resource",
    )


class PulumiOperationResult(BaseModel):
    """Result of a Pulumi operation.

    Contains the operation outcome including success status, affected resources,
    stack outputs, and a summary of changes.
    """

    success: bool = Field(
        ...,
        description="Whether the operation completed successfully",
    )
    operation: str = Field(
        ...,
        description="Operation type: 'preview', 'up', 'destroy', 'stack'",
    )
    resources: list[PulumiResource] = Field(
        default_factory=list,
        description="List of resources affected by the operation",
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Stack outputs after the operation",
    )
    summary: dict[str, int] = Field(
        default_factory=dict,
        description="Summary of changes: {create: N, update: N, delete: N, same: N}",
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        description="Duration of the operation in seconds",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if operation failed",
    )
    stack_name: Optional[str] = Field(
        default=None,
        description="Name of the stack operated on",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Name of the Pulumi project",
    )
