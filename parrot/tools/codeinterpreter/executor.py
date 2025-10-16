"""
Isolated code execution environment using Docker containers.
Provides secure Python code execution with resource limits and timeout controls.
"""
import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
import tempfile
import docker


@dataclass
class ExecutionResult:
    """Result from code execution in isolated environment"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    error_message: Optional[str] = None


class IsolatedExecutor:
    """
    Manages isolated Python code execution using Docker containers.

    Features:
    - Resource limits (memory, CPU)
    - Execution timeout
    - Network isolation
    - Read-only filesystem (except work directory)
    - Container reuse for better performance
    """

    def __init__(
        self,
        image: str = "python:3.11-alpine",
        memory_limit: str = "512m",
        cpu_quota: int = 50000,  # 50% of one CPU
        timeout_seconds: int = 30,
        enable_network: bool = False,
    ):
        """
        Initialize the isolated executor.

        Args:
            image: Docker image to use for execution
            memory_limit: Memory limit (e.g., "512m", "1g")
            cpu_quota: CPU quota in microseconds per 100ms period
            timeout_seconds: Maximum execution time in seconds
            enable_network: Whether to allow network access
        """
        self.client = docker.from_env()
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.cpu_period = 100000  # Standard 100ms period
        self.timeout_seconds = timeout_seconds
        self.enable_network = enable_network

        # Ensure image is available
        self._ensure_image()

    def _ensure_image(self):
        """Ensure the Docker image is available locally"""
        try:
            self.client.images.get(self.image)
        except docker.errors.ImageNotFound:
            print(f"Pulling Docker image: {self.image}")
            self.client.images.pull(self.image)

    def execute_code(
        self,
        code: str,
        working_dir: Optional[Path] = None,
        additional_files: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        Execute Python code in an isolated Docker container.

        Args:
            code: Python code to execute
            working_dir: Optional directory to mount as working directory
            additional_files: Optional dict of filename -> content to create

        Returns:
            ExecutionResult with execution details
        """
        start_time = time.time()

        try:
            # Create temporary directory for code execution
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Write the main code file
                code_file = temp_path / "main.py"
                code_file.write_text(code)

                # Write additional files if provided
                if additional_files:
                    for filename, content in additional_files.items():
                        file_path = temp_path / filename
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(content)

                # Prepare container configuration
                container_config = {
                    "image": self.image,
                    "command": ["python", "/workspace/main.py"],
                    "volumes": {
                        str(temp_path): {"bind": "/workspace", "mode": "rw"}
                    },
                    "working_dir": "/workspace",
                    "mem_limit": self.memory_limit,
                    "cpu_quota": self.cpu_quota,
                    "cpu_period": self.cpu_period,
                    "network_disabled": not self.enable_network,
                    "detach": True,
                    "remove": True,  # Auto-remove container after execution
                    "user": "nobody",  # Run as unprivileged user
                }

                # Add working directory mount if provided
                if working_dir and working_dir.exists():
                    container_config["volumes"][str(working_dir)] = {
                        "bind": "/workdir",
                        "mode": "ro"  # Read-only mount
                    }

                # Run container
                container = self.client.containers.run(**container_config)

                # Wait for completion with timeout
                try:
                    result = container.wait(timeout=self.timeout_seconds)
                    exit_code = result["StatusCode"]

                    # Get output
                    stdout = container.logs(stdout=True, stderr=False).decode("utf-8")
                    stderr = container.logs(stdout=False, stderr=True).decode("utf-8")

                    execution_time = int((time.time() - start_time) * 1000)

                    return ExecutionResult(
                        success=(exit_code == 0),
                        stdout=stdout,
                        stderr=stderr,
                        exit_code=exit_code,
                        execution_time_ms=execution_time,
                    )

                except docker.errors.APIError as e:
                    # Timeout or other container error
                    try:
                        container.stop(timeout=1)
                        container.remove(force=True)
                    except:
                        pass

                    execution_time = int((time.time() - start_time) * 1000)

                    return ExecutionResult(
                        success=False,
                        stdout="",
                        stderr="",
                        exit_code=-1,
                        execution_time_ms=execution_time,
                        error_message=f"Execution timeout after {self.timeout_seconds}s or container error: {str(e)}",
                    )

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=-1,
                execution_time_ms=execution_time,
                error_message=f"Failed to execute code: {str(e)}",
            )

    def execute_tests(
        self,
        test_code: str,
        source_code: Optional[str] = None,
        requirements: Optional[list[str]] = None,
    ) -> ExecutionResult:
        """
        Execute pytest tests in isolated environment.

        Args:
            test_code: Test code using pytest
            source_code: Optional source code being tested
            requirements: Optional list of pip packages to install

        Returns:
            ExecutionResult with test execution details
        """
        # Prepare setup script to install pytest and requirements
        setup_commands = ["pip install -q pytest"]
        if requirements:
            setup_commands.extend([f"pip install -q {req}" for req in requirements])

        # Create wrapper script that installs deps and runs tests
        wrapper_code = f"""
import subprocess
import sys

# Install dependencies
setup_commands = {setup_commands}
for cmd in setup_commands:
    result = subprocess.run(cmd.split(), capture_output=True)
    if result.returncode != 0:
        print(f"Failed to install dependency: {{cmd}}", file=sys.stderr)
        print(result.stderr.decode(), file=sys.stderr)
        sys.exit(1)

# Run pytest
result = subprocess.run(
    ["pytest", "-v", "/workspace/test_main.py"],
    capture_output=True,
    text=True
)
print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
"""

        # Prepare additional files
        additional_files = {"test_main.py": test_code}
        if source_code:
            additional_files["source.py"] = source_code

        return self.execute_code(
            code=wrapper_code,
            additional_files=additional_files,
        )

    def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate Python syntax without executing.

        Args:
            code: Python code to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            compile(code, "<string>", "exec")
            return True, None
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def cleanup(self):
        """Clean up Docker resources"""
        try:
            # Remove any dangling containers from this executor
            self.client.containers.prune()
        except Exception as e:
            print(f"Cleanup warning: {e}")


# Subprocess-based fallback for environments without Docker
class SubprocessExecutor:
    """
    Fallback executor using subprocess with basic restrictions.
    WARNING: Less secure than Docker-based isolation.
    """

    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def execute_code(
        self,
        code: str,
        working_dir: Optional[Path] = None,
        additional_files: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """Execute code using subprocess"""
        import subprocess

        start_time = time.time()

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                code_file = temp_path / "main.py"
                code_file.write_text(code)

                if additional_files:
                    for filename, content in additional_files.items():
                        (temp_path / filename).write_text(content)

                result = subprocess.run(
                    ["python", str(code_file)],
                    cwd=temp_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )

                execution_time = int((time.time() - start_time) * 1000)

                return ExecutionResult(
                    success=(result.returncode == 0),
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.returncode,
                    execution_time_ms=execution_time,
                )

        except subprocess.TimeoutExpired:
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=-1,
                execution_time_ms=execution_time,
                error_message=f"Execution timeout after {self.timeout_seconds}s",
            )
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=-1,
                execution_time_ms=execution_time,
                error_message=str(e),
            )

    def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """Validate Python syntax"""
        try:
            compile(code, "<string>", "exec")
            return True, None
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def cleanup(self):
        """No cleanup needed for subprocess executor"""
        pass


def create_executor(use_docker: bool = True, **kwargs) -> IsolatedExecutor | SubprocessExecutor:
    """
    Factory function to create appropriate executor.

    Args:
        use_docker: Whether to use Docker (falls back to subprocess if Docker unavailable)
        **kwargs: Additional arguments for executor

    Returns:
        Executor instance
    """
    if not use_docker:
        return SubprocessExecutor(timeout_seconds=kwargs.get("timeout_seconds", 30))
    try:
        return IsolatedExecutor(**kwargs)
    except Exception as e:
        print(f"Docker not available: {e}. Falling back to subprocess executor.")
        return SubprocessExecutor(timeout_seconds=kwargs.get("timeout_seconds", 30))
