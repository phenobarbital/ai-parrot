"""Pulumi executor for running infrastructure deployment commands.

Extends BaseExecutor to provide Pulumi-specific CLI argument building
and helper methods for preview, apply, destroy, and status operations.
"""

import json
import os
from typing import Any, Optional

from navconfig.logging import logging

from parrot.tools.security.base_executor import BaseExecutor

from .config import (
    PulumiConfig,
    PulumiOperationResult,
    PulumiResource,
)


class PulumiExecutor(BaseExecutor):
    """Executes Pulumi CLI commands via Docker or direct CLI.

    Supports Docker execution mode or direct CLI invocation.
    Parses JSON output from Pulumi commands into structured models.

    Pulumi CLI patterns:
        pulumi preview --json --stack <stack>
        pulumi up --yes --json --stack <stack>
        pulumi destroy --yes --json --stack <stack>
        pulumi stack output --json --stack <stack>

    Example:
        config = PulumiConfig(default_stack="dev")
        executor = PulumiExecutor(config)
        result = await executor.preview("/path/to/project")
    """

    def __init__(self, config: Optional[PulumiConfig] = None):
        """Initialize the Pulumi executor.

        Args:
            config: Pulumi configuration. Uses defaults if not provided.
        """
        super().__init__(config or PulumiConfig())
        self.config: PulumiConfig = self.config  # type narrowing
        self.logger = logging.getLogger(self.__class__.__name__)
        # Pulumi may exit with non-zero on preview with changes
        self.expected_exit_codes = [0, 1]

    def _default_cli_name(self) -> str:
        """Return the default Pulumi CLI binary name."""
        return "pulumi"

    def _build_cli_args(self, **kwargs) -> list[str]:
        """Build Pulumi CLI arguments for an operation.

        Args:
            **kwargs: Operation parameters including:
                - command: Operation type (preview, up, destroy, stack, stack_init, stack_select)
                - stack: Stack name to operate on
                - config_values: Dict of config values to set
                - target: List of specific resource URNs to target
                - refresh: Whether to refresh state before operation
                - replace: List of resource URNs to force-replace

        Returns:
            List of CLI argument strings.
        """
        args: list[str] = []
        command = kwargs.get("command", "preview")
        stack = kwargs.get("stack", self.config.default_stack)

        if command == "preview":
            args.extend(["preview", "--json"])
            if stack:
                args.extend(["--stack", stack])

            # Refresh state before preview
            if kwargs.get("refresh", True):
                args.append("--refresh")

            # Target specific resources
            target = kwargs.get("target")
            if target:
                for urn in target:
                    args.extend(["--target", urn])

        elif command == "up":
            args.extend(["up", "--json"])
            if stack:
                args.extend(["--stack", stack])

            # Non-interactive mode
            if kwargs.get("auto_approve", True):
                args.append("--yes")

            # Skip preview
            if kwargs.get("skip_preview", self.config.skip_preview):
                args.append("--skip-preview")

            # Refresh state before apply
            if kwargs.get("refresh", True):
                args.append("--refresh")

            # Target specific resources
            target = kwargs.get("target")
            if target:
                for urn in target:
                    args.extend(["--target", urn])

            # Force-replace specific resources
            replace = kwargs.get("replace")
            if replace:
                for urn in replace:
                    args.extend(["--replace", urn])

        elif command == "destroy":
            args.extend(["destroy", "--json"])
            if stack:
                args.extend(["--stack", stack])

            # Non-interactive mode
            if kwargs.get("auto_approve", True):
                args.append("--yes")

            # Target specific resources
            target = kwargs.get("target")
            if target:
                for urn in target:
                    args.extend(["--target", urn])

        elif command == "stack":
            # Get stack information/outputs
            args.extend(["stack", "output", "--json"])
            if stack:
                args.extend(["--stack", stack])

        elif command == "stack_select":
            # Select an existing stack
            args.extend(["stack", "select", stack])

        elif command == "stack_init":
            # Initialize a new stack
            args.extend(["stack", "init", stack])

        elif command == "stack_list":
            # List all stacks
            args.extend(["stack", "ls", "--json"])

        # Non-interactive mode for all commands
        if self.config.non_interactive and command not in ("stack_select", "stack_init"):
            args.append("--non-interactive")

        return args

    def _build_docker_command(self, args: list[str], project_path: str = ".") -> list[str]:
        """Build docker run command with project path mounted.

        Overrides base implementation to add project path mounting.

        Args:
            args: Pulumi CLI arguments.
            project_path: Path to Pulumi project directory.

        Returns:
            Full docker run command as list of strings.
        """
        cmd = ["docker", "run", "--rm"]

        # Add environment variables
        for key, val in self._build_env_vars().items():
            cmd.extend(["-e", f"{key}={val}"])

        # Add Pulumi-specific env vars
        if self.config.config_passphrase:
            cmd.extend(["-e", f"PULUMI_CONFIG_PASSPHRASE={self.config.config_passphrase}"])

        # Mount project directory
        abs_project_path = os.path.abspath(project_path)
        cmd.extend(["-v", f"{abs_project_path}:/pulumi/projects"])
        cmd.extend(["-w", "/pulumi/projects"])

        # Mount Pulumi home if specified
        if self.config.pulumi_home:
            cmd.extend(["-v", f"{self.config.pulumi_home}:/root/.pulumi"])

        # Add the docker image
        cmd.append(self.config.docker_image)

        # Add pulumi CLI arguments
        cmd.extend(args)

        return cmd

    def _build_process_env(self) -> dict[str, str]:
        """Build process environment for direct CLI execution.

        Extends base implementation to add Pulumi-specific env vars.

        Returns:
            Full environment dictionary for subprocess.
        """
        env = super()._build_process_env()

        # Add Pulumi-specific environment variables
        if self.config.config_passphrase:
            env["PULUMI_CONFIG_PASSPHRASE"] = self.config.config_passphrase

        # Set home directory for state storage
        if self.config.pulumi_home:
            env["PULUMI_HOME"] = self.config.pulumi_home

        return env

    def _parse_pulumi_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        operation: str,
    ) -> PulumiOperationResult:
        """Parse Pulumi JSON output into structured result.

        Args:
            stdout: Raw stdout from Pulumi CLI.
            stderr: Raw stderr from Pulumi CLI.
            exit_code: Process exit code.
            operation: Operation type (preview, up, destroy, stack).

        Returns:
            Parsed PulumiOperationResult.
        """
        success = exit_code == 0
        resources: list[PulumiResource] = []
        outputs: dict[str, Any] = {}
        summary: dict[str, int] = {}
        error: Optional[str] = None

        if not success and stderr:
            error = stderr.strip()

        if not stdout.strip():
            return PulumiOperationResult(
                success=success,
                operation=operation,
                resources=resources,
                outputs=outputs,
                summary=summary,
                error=error,
            )

        try:
            # Pulumi outputs newline-delimited JSON for streaming
            # We need to parse the last complete JSON object or combine them
            lines = stdout.strip().split("\n")
            combined_data: dict[str, Any] = {}

            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    # Merge data from each line
                    if isinstance(data, dict):
                        combined_data.update(data)
                except json.JSONDecodeError:
                    continue

            # Parse resources from steps or resources key
            steps = combined_data.get("steps", []) or combined_data.get("resources", [])
            for step in steps:
                if isinstance(step, dict):
                    resource = PulumiResource(
                        urn=step.get("urn", ""),
                        type=step.get("type", step.get("resourceType", "")),
                        name=step.get("name", step.get("resourceName", "")),
                        status=step.get("op", step.get("status", "same")),
                        outputs=step.get("outputs"),
                        provider=step.get("provider"),
                    )
                    if resource.urn:  # Only add if URN exists
                        resources.append(resource)

            # Parse outputs
            outputs = combined_data.get("outputs", {})
            if not isinstance(outputs, dict):
                outputs = {}

            # For stack output command, the entire response is the outputs
            if operation == "stack" and not outputs and combined_data:
                # Stack output returns outputs directly
                outputs = {k: v for k, v in combined_data.items()
                          if k not in ("version", "deployment", "checkpoint")}

            # Parse summary
            summary_data = combined_data.get("summary", {}) or combined_data.get("changeSummary", {})
            if isinstance(summary_data, dict):
                for key in ["create", "update", "delete", "same", "replace"]:
                    if key in summary_data:
                        summary[key] = summary_data[key]

            # Extract duration if available
            duration = combined_data.get("durationSeconds") or combined_data.get("duration")

            return PulumiOperationResult(
                success=success,
                operation=operation,
                resources=resources,
                outputs=outputs,
                summary=summary,
                duration_seconds=float(duration) if duration else None,
                error=error,
            )

        except Exception as e:
            self.logger.warning("Failed to parse Pulumi output: %s", e)
            return PulumiOperationResult(
                success=success,
                operation=operation,
                resources=resources,
                outputs=outputs,
                summary=summary,
                error=error or str(e),
            )

    async def _ensure_stack(self, project_path: str, stack: str) -> tuple[bool, str]:
        """Ensure the specified stack exists, creating it if needed.

        Args:
            project_path: Path to Pulumi project.
            stack: Stack name to ensure exists.

        Returns:
            Tuple of (success, error_message).
        """
        if not self.config.auto_create_stack:
            return True, ""

        # Try to select the stack first
        args = self._build_cli_args(command="stack_select", stack=stack)

        if self.config.use_docker:
            cmd = self._build_docker_command(args, project_path)
            env = None
        else:
            cmd = self._build_direct_command(args)
            env = self._build_process_env()

        import asyncio
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=None if self.config.use_docker else project_path,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            return True, ""

        # Stack doesn't exist, try to create it
        self.logger.info("Stack '%s' not found, creating...", stack)
        args = self._build_cli_args(command="stack_init", stack=stack)

        if self.config.use_docker:
            cmd = self._build_docker_command(args, project_path)
        else:
            cmd = self._build_direct_command(args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=None if self.config.use_docker else project_path,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            self.logger.info("Stack '%s' created successfully", stack)
            return True, ""

        error = stderr.decode().strip()
        self.logger.error("Failed to create stack '%s': %s", stack, error)
        return False, error

    async def _execute_in_project(
        self,
        project_path: str,
        **kwargs,
    ) -> tuple[str, str, int]:
        """Execute a Pulumi command in a project directory.

        Args:
            project_path: Path to Pulumi project directory.
            **kwargs: Arguments passed to _build_cli_args().

        Returns:
            Tuple of (stdout, stderr, exit_code).
        """
        import asyncio

        args = self._build_cli_args(**kwargs)

        if self.config.use_docker:
            cmd = self._build_docker_command(args, project_path)
            env = None
            cwd = None
        else:
            cmd = self._build_direct_command(args)
            env = self._build_process_env()
            cwd = project_path

        self.logger.debug("Executing: %s", self._mask_command(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout
            )
            exit_code = proc.returncode or 0

            if exit_code not in self.expected_exit_codes:
                self.logger.warning(
                    "Pulumi exited with code %d: %s",
                    exit_code,
                    stderr.decode()[:500],
                )

            return stdout.decode(), stderr.decode(), exit_code

        except asyncio.TimeoutError:
            self.logger.error(
                "Execution timed out after %d seconds", self.config.timeout
            )
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

            return "", f"Timeout: execution exceeded {self.config.timeout} seconds", -1

    # --- High-level operations ---

    async def preview(
        self,
        project_path: str,
        stack: Optional[str] = None,
        config_values: Optional[dict[str, Any]] = None,
        target: Optional[list[str]] = None,
        refresh: bool = True,
    ) -> PulumiOperationResult:
        """Preview infrastructure changes without applying.

        Args:
            project_path: Path to Pulumi project directory.
            stack: Stack name (defaults to config.default_stack).
            config_values: Configuration values to set (not yet implemented).
            target: Specific resource URNs to target.
            refresh: Refresh state before preview.

        Returns:
            PulumiOperationResult with preview details.
        """
        stack = stack or self.config.default_stack

        # Ensure stack exists
        success, error = await self._ensure_stack(project_path, stack)
        if not success:
            return PulumiOperationResult(
                success=False,
                operation="preview",
                error=f"Failed to ensure stack: {error}",
            )

        stdout, stderr, exit_code = await self._execute_in_project(
            project_path,
            command="preview",
            stack=stack,
            target=target,
            refresh=refresh,
        )

        return self._parse_pulumi_output(stdout, stderr, exit_code, "preview")

    async def up(
        self,
        project_path: str,
        stack: Optional[str] = None,
        config_values: Optional[dict[str, Any]] = None,
        auto_approve: bool = True,
        target: Optional[list[str]] = None,
        refresh: bool = True,
        replace: Optional[list[str]] = None,
    ) -> PulumiOperationResult:
        """Apply infrastructure changes.

        Args:
            project_path: Path to Pulumi project directory.
            stack: Stack name (defaults to config.default_stack).
            config_values: Configuration values to set (not yet implemented).
            auto_approve: Skip confirmation prompt.
            target: Specific resource URNs to target.
            refresh: Refresh state before apply.
            replace: Resource URNs to force-replace.

        Returns:
            PulumiOperationResult with apply details.
        """
        stack = stack or self.config.default_stack

        # Ensure stack exists
        success, error = await self._ensure_stack(project_path, stack)
        if not success:
            return PulumiOperationResult(
                success=False,
                operation="up",
                error=f"Failed to ensure stack: {error}",
            )

        stdout, stderr, exit_code = await self._execute_in_project(
            project_path,
            command="up",
            stack=stack,
            auto_approve=auto_approve,
            target=target,
            refresh=refresh,
            replace=replace,
        )

        return self._parse_pulumi_output(stdout, stderr, exit_code, "up")

    async def destroy(
        self,
        project_path: str,
        stack: Optional[str] = None,
        auto_approve: bool = True,
        target: Optional[list[str]] = None,
    ) -> PulumiOperationResult:
        """Tear down infrastructure.

        Args:
            project_path: Path to Pulumi project directory.
            stack: Stack name (defaults to config.default_stack).
            auto_approve: Skip confirmation prompt.
            target: Specific resource URNs to target.

        Returns:
            PulumiOperationResult with destroy details.
        """
        stack = stack or self.config.default_stack

        stdout, stderr, exit_code = await self._execute_in_project(
            project_path,
            command="destroy",
            stack=stack,
            auto_approve=auto_approve,
            target=target,
        )

        return self._parse_pulumi_output(stdout, stderr, exit_code, "destroy")

    async def stack_output(
        self,
        project_path: str,
        stack: Optional[str] = None,
    ) -> PulumiOperationResult:
        """Get current stack outputs.

        Args:
            project_path: Path to Pulumi project directory.
            stack: Stack name (defaults to config.default_stack).

        Returns:
            PulumiOperationResult with stack outputs.
        """
        stack = stack or self.config.default_stack

        stdout, stderr, exit_code = await self._execute_in_project(
            project_path,
            command="stack",
            stack=stack,
        )

        return self._parse_pulumi_output(stdout, stderr, exit_code, "stack")

    async def list_stacks(
        self,
        project_path: str,
    ) -> tuple[list[str], str]:
        """List all stacks in the project.

        Args:
            project_path: Path to Pulumi project directory.

        Returns:
            Tuple of (stack_names, error_message).
        """
        stdout, stderr, exit_code = await self._execute_in_project(
            project_path,
            command="stack_list",
        )

        if exit_code != 0:
            return [], stderr.strip()

        try:
            data = json.loads(stdout)
            if isinstance(data, list):
                stacks = [s.get("name", "") for s in data if isinstance(s, dict)]
                return stacks, ""
        except json.JSONDecodeError:
            pass

        return [], "Failed to parse stack list"
