"""Pulumi Toolkit for infrastructure deployment.

Provides tools for deploying and managing infrastructure using Pulumi,
starting with Docker/Docker Compose as the initial provider.
"""

from pathlib import Path
from typing import Any, Optional

from ..toolkit import AbstractToolkit

from .config import (
    PulumiApplyInput,
    PulumiConfig,
    PulumiDestroyInput,
    PulumiOperationResult,
    PulumiPlanInput,
    PulumiStatusInput,
)
from .executor import PulumiExecutor


class PulumiToolkit(AbstractToolkit):
    """Toolkit for infrastructure deployment using Pulumi.

    Each public async method is exposed as a separate tool with the `pulumi_` prefix.

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

        # Or call directly
        result = await toolkit.pulumi_plan("/path/to/project")
    """

    def __init__(self, config: Optional[PulumiConfig] = None, **kwargs):
        """Initialize the Pulumi toolkit.

        Args:
            config: Pulumi configuration. Uses defaults if not provided.
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.config = config or PulumiConfig()
        self.executor = PulumiExecutor(self.config)

    def _validate_project_path(self, project_path: str) -> tuple[bool, str]:
        """Validate that project_path exists and contains Pulumi.yaml.

        Args:
            project_path: Path to Pulumi project directory.

        Returns:
            Tuple of (is_valid, error_message).
        """
        path = Path(project_path)

        if not path.exists():
            return False, f"Project path not found: {project_path}"

        if not path.is_dir():
            return False, f"Project path is not a directory: {project_path}"

        pulumi_yaml = path / "Pulumi.yaml"
        if not pulumi_yaml.exists():
            # Also check for Pulumi.yml
            pulumi_yml = path / "Pulumi.yml"
            if not pulumi_yml.exists():
                return False, f"Pulumi.yaml not found in {project_path}"

        return True, ""

    async def pulumi_plan(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
        target: Optional[list[str]] = None,
        refresh: bool = True,
    ) -> PulumiOperationResult:
        """Preview infrastructure changes without applying.

        Shows what resources would be created, updated, or deleted
        if you were to run `pulumi_apply`. This is a safe operation
        that makes no changes to your infrastructure.

        Args:
            project_path: Path to Pulumi project directory containing Pulumi.yaml.
            stack_name: Stack name to preview (defaults to 'dev').
            config: Configuration values to set before preview.
            target: Specific resource URNs to target for preview.
            refresh: Refresh resource state before preview.

        Returns:
            PulumiOperationResult with preview details including:
            - resources: List of resources to be affected
            - summary: Count of creates/updates/deletes
            - success: Whether preview completed successfully
        """
        # Validate project path
        valid, error = self._validate_project_path(project_path)
        if not valid:
            return PulumiOperationResult(
                success=False,
                operation="preview",
                error=error,
            )

        self.logger.info("Running pulumi preview on %s (stack: %s)", project_path, stack_name or "default")

        try:
            result = await self.executor.preview(
                project_path=project_path,
                stack=stack_name,
                config_values=config,
                target=target,
                refresh=refresh,
            )
            return result
        except Exception as e:
            self.logger.error("Preview failed: %s", e)
            return PulumiOperationResult(
                success=False,
                operation="preview",
                error=str(e),
            )

    async def pulumi_apply(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
        auto_approve: bool = True,
        target: Optional[list[str]] = None,
        refresh: bool = True,
        replace: Optional[list[str]] = None,
    ) -> PulumiOperationResult:
        """Apply infrastructure changes.

        Creates, updates, or deletes resources to match the desired state
        defined in your Pulumi program. By default runs with auto_approve=True
        to avoid interactive prompts in agent workflows.

        Args:
            project_path: Path to Pulumi project directory containing Pulumi.yaml.
            stack_name: Stack name to apply (defaults to 'dev').
            config: Configuration values to set before apply.
            auto_approve: Skip confirmation prompt and apply immediately.
            target: Specific resource URNs to target for apply.
            refresh: Refresh resource state before apply.
            replace: Resource URNs to force-replace during apply.

        Returns:
            PulumiOperationResult with apply details including:
            - resources: List of resources that were affected
            - outputs: Stack outputs after apply
            - summary: Count of creates/updates/deletes
            - success: Whether apply completed successfully
        """
        # Validate project path
        valid, error = self._validate_project_path(project_path)
        if not valid:
            return PulumiOperationResult(
                success=False,
                operation="up",
                error=error,
            )

        self.logger.info("Running pulumi up on %s (stack: %s)", project_path, stack_name or "default")

        try:
            result = await self.executor.up(
                project_path=project_path,
                stack=stack_name,
                config_values=config,
                auto_approve=auto_approve,
                target=target,
                refresh=refresh,
                replace=replace,
            )
            return result
        except Exception as e:
            self.logger.error("Apply failed: %s", e)
            return PulumiOperationResult(
                success=False,
                operation="up",
                error=str(e),
            )

    async def pulumi_destroy(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
        auto_approve: bool = True,
        target: Optional[list[str]] = None,
    ) -> PulumiOperationResult:
        """Tear down infrastructure.

        Deletes all resources managed by the specified stack. By default
        runs with auto_approve=True to avoid interactive prompts in
        agent workflows.

        WARNING: This operation is destructive and cannot be undone.
        Use pulumi_plan first to preview what will be destroyed.

        Args:
            project_path: Path to Pulumi project directory containing Pulumi.yaml.
            stack_name: Stack name to destroy (defaults to 'dev').
            auto_approve: Skip confirmation prompt and destroy immediately.
            target: Specific resource URNs to target for destruction.

        Returns:
            PulumiOperationResult with destroy details including:
            - resources: List of resources that were deleted
            - summary: Count of deleted resources
            - success: Whether destroy completed successfully
        """
        # Validate project path
        valid, error = self._validate_project_path(project_path)
        if not valid:
            return PulumiOperationResult(
                success=False,
                operation="destroy",
                error=error,
            )

        self.logger.info("Running pulumi destroy on %s (stack: %s)", project_path, stack_name or "default")

        try:
            result = await self.executor.destroy(
                project_path=project_path,
                stack=stack_name,
                auto_approve=auto_approve,
                target=target,
            )
            return result
        except Exception as e:
            self.logger.error("Destroy failed: %s", e)
            return PulumiOperationResult(
                success=False,
                operation="destroy",
                error=str(e),
            )

    async def pulumi_status(
        self,
        project_path: str,
        stack_name: Optional[str] = None,
    ) -> PulumiOperationResult:
        """Check current stack state.

        Returns the current outputs and resource state of the specified stack.
        This is a read-only operation that makes no changes.

        Args:
            project_path: Path to Pulumi project directory containing Pulumi.yaml.
            stack_name: Stack name to check (defaults to 'dev').

        Returns:
            PulumiOperationResult with current state including:
            - outputs: Current stack outputs
            - resources: Currently deployed resources (if available)
            - success: Whether status check completed successfully
        """
        # Validate project path
        valid, error = self._validate_project_path(project_path)
        if not valid:
            return PulumiOperationResult(
                success=False,
                operation="stack",
                error=error,
            )

        self.logger.info("Getting pulumi stack status for %s (stack: %s)", project_path, stack_name or "default")

        try:
            result = await self.executor.stack_output(
                project_path=project_path,
                stack=stack_name,
            )
            return result
        except Exception as e:
            self.logger.error("Status check failed: %s", e)
            return PulumiOperationResult(
                success=False,
                operation="stack",
                error=str(e),
            )

    async def pulumi_list_stacks(
        self,
        project_path: str,
    ) -> tuple[list[str], str]:
        """List all stacks in the project.

        Args:
            project_path: Path to Pulumi project directory containing Pulumi.yaml.

        Returns:
            Tuple of (stack_names, error_message).
        """
        # Validate project path
        valid, error = self._validate_project_path(project_path)
        if not valid:
            return [], error

        try:
            return await self.executor.list_stacks(project_path)
        except Exception as e:
            self.logger.error("List stacks failed: %s", e)
            return [], str(e)
