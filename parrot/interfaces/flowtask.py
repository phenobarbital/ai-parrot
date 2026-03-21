"""Flowtask Interface - Mixin for managing Flowtask DAG tasks.

Provides async methods for interacting with the Flowtask API:
- Execute tasks locally or remotely via REST API
- Launch long-running tasks on workers
- Submit ad-hoc tasks from JSON/YAML definitions
- Query task and job status
- List available programs and tasks

Flowtask (github.com/phenobarbital/flowtask) is a plugin-based,
component-driven task execution framework that runs DAG-based workflows
defined in JSON, YAML, or TOML files.

Environment Variables:
    TASK_DOMAIN: Base URL of the Flowtask API server (required for remote ops).
    TASK_API_TOKEN: Optional Bearer token for authenticated endpoints.
"""
import os
import json
import asyncio
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

import aiohttp
from pydantic import BaseModel, Field, field_validator
from navconfig.logging import logging


logger = logging.getLogger("FlowtaskInterface")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Possible statuses of a Flowtask task/job."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskCodeFormat(str, Enum):
    """Supported formats for ad-hoc task definitions."""
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"


# ---------------------------------------------------------------------------
# Pydantic models — Request
# ---------------------------------------------------------------------------

class TaskExecutionRequest(BaseModel):
    """Request model for executing a Flowtask task."""

    program: str = Field(
        ...,
        description="Program name/slug that owns the task (e.g. 'nextstop')."
    )
    task_name: str = Field(
        ...,
        description="Name of the task to execute (e.g. 'employees_report')."
    )
    long_running: bool = Field(
        default=False,
        description=(
            "When True the task is enqueued to a worker and the API "
            "returns immediately with a job ID (HTTP 202)."
        ),
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional runtime parameters forwarded to the task.",
    )
    timeout: float = Field(
        default=300.0,
        ge=1.0,
        le=3600.0,
        description="HTTP timeout in seconds (applies when long_running=False).",
    )

    @field_validator("program", "task_name")
    @classmethod
    def _no_slashes(cls, v: str) -> str:
        if "/" in v or "\\" in v:
            raise ValueError("Must not contain path separators.")
        return v.strip()


class TaskCodeRequest(BaseModel):
    """Request model for submitting an ad-hoc task from a JSON/YAML string."""

    task_code: str = Field(
        ...,
        min_length=2,
        description="The task definition as a JSON or YAML string.",
    )
    format: TaskCodeFormat = Field(
        default=TaskCodeFormat.YAML,
        description="Format of *task_code*.",
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional runtime parameters merged into the payload.",
    )


class WorkerTaskRequest(BaseModel):
    """Request model for dispatching a task to a Flowtask worker."""

    program: str = Field(
        ...,
        description="Program name/slug.",
    )
    task_name: str = Field(
        ...,
        description="Name of the task to dispatch.",
    )
    worker: Optional[str] = Field(
        default=None,
        description="Target worker name/ID. None lets the scheduler pick.",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Job priority (1 = highest, 10 = lowest).",
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional runtime parameters.",
    )
    schedule_at: Optional[datetime] = Field(
        default=None,
        description="Schedule the job for a future time (UTC). None = immediate.",
    )

    @field_validator("program", "task_name")
    @classmethod
    def _no_slashes(cls, v: str) -> str:
        if "/" in v or "\\" in v:
            raise ValueError("Must not contain path separators.")
        return v.strip()


# ---------------------------------------------------------------------------
# Pydantic models — Response
# ---------------------------------------------------------------------------

class TaskResult(BaseModel):
    """Response model for a completed task execution."""

    status: TaskStatus = Field(
        description="Final status of the task.",
    )
    program: str = Field(
        default="",
        description="Program name.",
    )
    task_name: str = Field(
        default="",
        description="Task name.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Unique execution/job identifier.",
    )
    result: Optional[Any] = Field(
        default=None,
        description="Task output data (format varies by task).",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if the task failed.",
    )
    stacktrace: Optional[str] = Field(
        default=None,
        description="Python traceback on failure.",
    )
    stats: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Execution statistics (duration, row counts, etc.).",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata returned by the API.",
    )


class JobInfo(BaseModel):
    """Lightweight info about a queued/running job."""

    job_id: str = Field(description="Unique job identifier.")
    program: str = Field(default="", description="Program name.")
    task_name: str = Field(default="", description="Task name.")
    status: TaskStatus = Field(description="Current job status.")
    queued_at: Optional[datetime] = Field(default=None)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    worker: Optional[str] = Field(default=None, description="Assigned worker.")
    metadata: Optional[Dict[str, Any]] = Field(default=None)


# ---------------------------------------------------------------------------
# Interface (mixin)
# ---------------------------------------------------------------------------

class FlowtaskInterface:
    """Interface for managing Flowtask DAG tasks.

    Mix this into a bot or service class to gain async helpers for:

    - **run_task** / **run_task_remote** — execute a task locally or via API.
    - **dispatch_task** — enqueue a task on a Flowtask worker.
    - **submit_task_code** — send an ad-hoc JSON/YAML task definition.
    - **get_job_status** — poll a running/queued job.
    - **list_programs** / **list_tasks** — discover available programs & tasks.
    - **cancel_job** — cancel a queued or running job.

    All remote methods require the ``TASK_DOMAIN`` environment variable.
    """

    # -----------------------------------------------------------------
    # Configuration helpers
    # -----------------------------------------------------------------

    def _ft_base_url(self) -> str:
        """Return the Flowtask API base URL from environment."""
        url = os.getenv("TASK_DOMAIN", "").rstrip("/")
        if not url:
            raise EnvironmentError(
                "TASK_DOMAIN environment variable is not set. "
                "Set it to the Flowtask API base URL "
                "(e.g. https://flowtask.example.com)."
            )
        return url

    def _ft_headers(self) -> Dict[str, str]:
        """Build common HTTP headers for Flowtask API requests."""
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        token = os.getenv("TASK_API_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _ft_timeout(self, seconds: float = 300.0) -> aiohttp.ClientTimeout:
        """Create an aiohttp timeout from seconds."""
        return aiohttp.ClientTimeout(total=seconds)

    # -----------------------------------------------------------------
    # Internal HTTP helpers
    # -----------------------------------------------------------------

    async def _ft_request(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> Dict[str, Any]:
        """Execute an HTTP request against the Flowtask API with retries.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: URL path (appended to TASK_DOMAIN).
            payload: JSON body for POST/PUT/PATCH.
            timeout: Request timeout in seconds.
            max_retries: Max retry attempts on transient failures.
            backoff_factor: Exponential backoff factor.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            EnvironmentError: If TASK_DOMAIN is not set.
            aiohttp.ClientError: After exhausting retries.
        """
        base = self._ft_base_url()
        url = f"{base}{path}"
        headers = self._ft_headers()
        client_timeout = self._ft_timeout(timeout)

        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession(
                    timeout=client_timeout,
                    headers=headers,
                ) as session:
                    kwargs: Dict[str, Any] = {}
                    if payload is not None:
                        kwargs["json"] = payload

                    async with session.request(method, url, **kwargs) as resp:
                        body = await resp.json(content_type=None)

                        if resp.status in (200, 201, 202):
                            return {
                                "http_status": resp.status,
                                "data": body,
                            }

                        # Non-retryable client errors
                        if 400 <= resp.status < 500:
                            return {
                                "http_status": resp.status,
                                "data": body,
                                "error": body.get("error", resp.reason),
                            }

                        # Server errors — retryable
                        last_error = aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=str(body),
                        )

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc

            # Exponential backoff before retry
            if attempt < max_retries - 1:
                delay = backoff_factor * (2 ** attempt)
                logger.warning(
                    "Flowtask API request to %s failed (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    url, attempt + 1, max_retries, delay, last_error,
                )
                await asyncio.sleep(delay)

        raise aiohttp.ClientError(
            f"Flowtask API request failed after {max_retries} attempts: "
            f"{last_error}"
        )

    # -----------------------------------------------------------------
    # Task execution — remote (API)
    # -----------------------------------------------------------------

    async def run_task_remote(
        self,
        request: Union[TaskExecutionRequest, Dict[str, Any]],
    ) -> TaskResult:
        """Execute a Flowtask task via the remote API.

        Args:
            request: A ``TaskExecutionRequest`` or equivalent dict.

        Returns:
            ``TaskResult`` with execution outcome.
        """
        if isinstance(request, dict):
            request = TaskExecutionRequest(**request)

        payload: Dict[str, Any] = {
            "long_running": request.long_running,
        }
        if request.parameters:
            payload["params"] = request.parameters

        path = f"/api/v2/task/{request.program}/{request.task_name}"

        try:
            resp = await self._ft_request(
                "POST",
                path,
                payload=payload,
                timeout=request.timeout,
            )

            http_status = resp.get("http_status", 0)
            data = resp.get("data", {})

            if http_status == 202:
                # Task was queued (long_running=True)
                return TaskResult(
                    status=TaskStatus.QUEUED,
                    program=request.program,
                    task_name=request.task_name,
                    task_id=data.get("task_id") or data.get("job_id"),
                    metadata=data,
                )

            if http_status == 200:
                return TaskResult(
                    status=TaskStatus.SUCCESS,
                    program=request.program,
                    task_name=request.task_name,
                    task_id=data.get("task_id"),
                    result=data.get("result", data),
                    stats=data.get("stats"),
                    metadata=data,
                )

            # Error responses
            return TaskResult(
                status=TaskStatus.FAILED,
                program=request.program,
                task_name=request.task_name,
                error=resp.get("error") or data.get("error", f"HTTP {http_status}"),
                metadata=data,
            )

        except Exception as exc:
            logger.error(
                "Remote task execution failed for %s/%s: %s",
                request.program, request.task_name, exc,
            )
            return TaskResult(
                status=TaskStatus.FAILED,
                program=request.program,
                task_name=request.task_name,
                error=str(exc),
            )

    # -----------------------------------------------------------------
    # Task execution — local
    # -----------------------------------------------------------------

    async def run_task_local(
        self,
        request: Union[TaskExecutionRequest, Dict[str, Any]],
    ) -> TaskResult:
        """Execute a Flowtask task locally using the flowtask library.

        Requires the ``flowtask`` package to be installed.

        Args:
            request: A ``TaskExecutionRequest`` or equivalent dict.

        Returns:
            ``TaskResult`` with execution outcome.
        """
        if isinstance(request, dict):
            request = TaskExecutionRequest(**request)

        try:
            from flowtask.tasks.task import Task  # pylint: disable=import-outside-toplevel
        except ImportError:
            return TaskResult(
                status=TaskStatus.FAILED,
                program=request.program,
                task_name=request.task_name,
                error=(
                    "flowtask package is not installed. "
                    "Install with: uv pip install flowtask"
                ),
            )

        try:
            task = Task(
                program=request.program,
                task=request.task_name,
                debug=True,
            )

            async with task as t:
                result = await t.run()

            return TaskResult(
                status=TaskStatus.SUCCESS,
                program=request.program,
                task_name=request.task_name,
                result=self._ft_format_result(result),
                stats=t.get_stats() if hasattr(t, "get_stats") else None,
            )

        except Exception as exc:
            logger.error(
                "Local task execution failed for %s/%s: %s",
                request.program, request.task_name, exc,
            )
            return TaskResult(
                status=TaskStatus.FAILED,
                program=request.program,
                task_name=request.task_name,
                error=str(exc),
            )

    # -----------------------------------------------------------------
    # Dispatch to worker
    # -----------------------------------------------------------------

    async def dispatch_task(
        self,
        request: Union[WorkerTaskRequest, Dict[str, Any]],
    ) -> TaskResult:
        """Dispatch a task to a Flowtask worker for background execution.

        The task is always enqueued (long_running) and returns a job ID
        that can be polled with ``get_job_status``.

        Args:
            request: A ``WorkerTaskRequest`` or equivalent dict.

        Returns:
            ``TaskResult`` with status=QUEUED and the assigned job_id.
        """
        if isinstance(request, dict):
            request = WorkerTaskRequest(**request)

        payload: Dict[str, Any] = {
            "long_running": True,
            "priority": request.priority,
        }
        if request.worker:
            payload["worker"] = request.worker
        if request.parameters:
            payload["params"] = request.parameters
        if request.schedule_at:
            payload["schedule_at"] = request.schedule_at.isoformat()

        path = f"/api/v2/task/{request.program}/{request.task_name}"

        try:
            resp = await self._ft_request("POST", path, payload=payload)
            data = resp.get("data", {})

            return TaskResult(
                status=TaskStatus.QUEUED,
                program=request.program,
                task_name=request.task_name,
                task_id=data.get("task_id") or data.get("job_id"),
                metadata=data,
            )

        except Exception as exc:
            logger.error(
                "Failed to dispatch task %s/%s: %s",
                request.program, request.task_name, exc,
            )
            return TaskResult(
                status=TaskStatus.FAILED,
                program=request.program,
                task_name=request.task_name,
                error=str(exc),
            )

    # -----------------------------------------------------------------
    # Submit ad-hoc task code (JSON/YAML string)
    # -----------------------------------------------------------------

    async def submit_task_code(
        self,
        request: Union[TaskCodeRequest, Dict[str, Any]],
    ) -> TaskResult:
        """Submit an ad-hoc task definition as a JSON or YAML string.

        The task definition is sent to the Flowtask API for immediate
        execution. This is useful for dynamically generated pipelines.

        Args:
            request: A ``TaskCodeRequest`` or equivalent dict.

        Returns:
            ``TaskResult`` with execution outcome.
        """
        if isinstance(request, dict):
            request = TaskCodeRequest(**request)

        # Parse the task definition
        try:
            if request.format == TaskCodeFormat.YAML:
                import yaml  # pylint: disable=import-outside-toplevel
                body_task = yaml.safe_load(request.task_code)
            elif request.format == TaskCodeFormat.TOML:
                import tomllib  # pylint: disable=import-outside-toplevel
                body_task = tomllib.loads(request.task_code)
            else:
                body_task = json.loads(request.task_code)
        except Exception as exc:
            return TaskResult(
                status=TaskStatus.FAILED,
                error=f"Failed to parse task code as {request.format.value}: {exc}",
            )

        if request.parameters:
            body_task.setdefault("params", {}).update(request.parameters)

        task_id = str(uuid.uuid4())
        payload: Dict[str, Any] = {
            "task_id": task_id,
            "task": body_task,
        }

        try:
            resp = await self._ft_request(
                "POST",
                "/api/v2/task/execute",
                payload=payload,
            )
            data = resp.get("data", {})
            http_status = resp.get("http_status", 0)

            if http_status in (200, 201, 202):
                status = (
                    TaskStatus.QUEUED if http_status == 202 else TaskStatus.SUCCESS
                )
                return TaskResult(
                    status=status,
                    task_id=data.get("task_id", task_id),
                    result=data.get("result"),
                    stats=data.get("stats"),
                    metadata=data,
                )

            return TaskResult(
                status=TaskStatus.FAILED,
                task_id=task_id,
                error=resp.get("error") or data.get("error", f"HTTP {http_status}"),
                metadata=data,
            )

        except Exception as exc:
            logger.error("Failed to submit task code: %s", exc)
            return TaskResult(
                status=TaskStatus.FAILED,
                task_id=task_id,
                error=str(exc),
            )

    # -----------------------------------------------------------------
    # Submit ad-hoc task code — local execution
    # -----------------------------------------------------------------

    async def submit_task_code_local(
        self,
        request: Union[TaskCodeRequest, Dict[str, Any]],
    ) -> TaskResult:
        """Execute an ad-hoc task definition locally via the flowtask library.

        Args:
            request: A ``TaskCodeRequest`` or equivalent dict.

        Returns:
            ``TaskResult`` with execution outcome.
        """
        if isinstance(request, dict):
            request = TaskCodeRequest(**request)

        try:
            from flowtask.tasks.task import Task  # pylint: disable=import-outside-toplevel
            from flowtask.storages import MemoryTaskStorage  # pylint: disable=import-outside-toplevel
        except ImportError:
            return TaskResult(
                status=TaskStatus.FAILED,
                error=(
                    "flowtask package is not installed. "
                    "Install with: uv pip install flowtask"
                ),
            )

        # Parse
        try:
            if request.format == TaskCodeFormat.YAML:
                import yaml  # pylint: disable=import-outside-toplevel
                body_task = yaml.safe_load(request.task_code)
            elif request.format == TaskCodeFormat.TOML:
                import tomllib  # pylint: disable=import-outside-toplevel
                body_task = tomllib.loads(request.task_code)
            else:
                body_task = json.loads(request.task_code)
        except Exception as exc:
            return TaskResult(
                status=TaskStatus.FAILED,
                error=f"Failed to parse task code as {request.format.value}: {exc}",
            )

        if request.parameters:
            body_task.setdefault("params", {}).update(request.parameters)

        task_id = str(uuid.uuid4())

        try:
            task = Task(task=task_id)
            async with task as t:
                t.taskstore = MemoryTaskStorage()
                if await t.start(payload=body_task):
                    result = await t.run()
                    stats = t.get_stats() if hasattr(t, "get_stats") else None
                else:
                    return TaskResult(
                        status=TaskStatus.FAILED,
                        task_id=task_id,
                        error="Failed to start task with the provided payload.",
                    )

            return TaskResult(
                status=TaskStatus.SUCCESS,
                task_id=task_id,
                result=self._ft_format_result(result),
                stats=stats,
            )

        except Exception as exc:
            import traceback  # pylint: disable=import-outside-toplevel
            logger.error("Local task code execution failed: %s", exc)
            return TaskResult(
                status=TaskStatus.FAILED,
                task_id=task_id,
                error=str(exc),
                stacktrace=traceback.format_exc(),
            )

    # -----------------------------------------------------------------
    # Job status & management
    # -----------------------------------------------------------------

    async def get_job_status(self, job_id: str) -> JobInfo:
        """Query the status of a queued/running Flowtask job.

        Args:
            job_id: The job identifier returned by dispatch_task.

        Returns:
            ``JobInfo`` with current status.
        """
        try:
            resp = await self._ft_request(
                "GET",
                f"/api/v2/job/{job_id}",
            )
            data = resp.get("data", {})

            return JobInfo(
                job_id=job_id,
                program=data.get("program", ""),
                task_name=data.get("task", data.get("task_name", "")),
                status=TaskStatus(data.get("status", "pending")),
                queued_at=data.get("queued_at"),
                started_at=data.get("started_at"),
                finished_at=data.get("finished_at"),
                worker=data.get("worker"),
                metadata=data,
            )

        except Exception as exc:
            logger.error("Failed to get job status for %s: %s", job_id, exc)
            return JobInfo(
                job_id=job_id,
                status=TaskStatus.FAILED,
                metadata={"error": str(exc)},
            )

    async def cancel_job(self, job_id: str) -> TaskResult:
        """Cancel a queued or running Flowtask job.

        Args:
            job_id: The job identifier to cancel.

        Returns:
            ``TaskResult`` indicating cancellation outcome.
        """
        try:
            resp = await self._ft_request(
                "DELETE",
                f"/api/v2/job/{job_id}",
            )
            data = resp.get("data", {})
            http_status = resp.get("http_status", 0)

            if http_status in (200, 202):
                return TaskResult(
                    status=TaskStatus.CANCELLED,
                    task_id=job_id,
                    metadata=data,
                )

            return TaskResult(
                status=TaskStatus.FAILED,
                task_id=job_id,
                error=resp.get("error") or data.get("error", f"HTTP {http_status}"),
                metadata=data,
            )

        except Exception as exc:
            logger.error("Failed to cancel job %s: %s", job_id, exc)
            return TaskResult(
                status=TaskStatus.FAILED,
                task_id=job_id,
                error=str(exc),
            )

    # -----------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------

    async def list_programs(self) -> List[str]:
        """List available Flowtask programs.

        Returns:
            List of program name strings.
        """
        try:
            resp = await self._ft_request("GET", "/api/v2/programs")
            data = resp.get("data", [])
            if isinstance(data, list):
                return data
            return data.get("programs", [])
        except Exception as exc:
            logger.error("Failed to list programs: %s", exc)
            return []

    async def list_tasks(self, program: str) -> List[Dict[str, Any]]:
        """List tasks available under a given program.

        Args:
            program: Program name/slug.

        Returns:
            List of task descriptors (dicts with at least 'name' key).
        """
        try:
            resp = await self._ft_request(
                "GET",
                f"/api/v2/tasks/{program}",
            )
            data = resp.get("data", [])
            if isinstance(data, list):
                return data
            return data.get("tasks", [])
        except Exception as exc:
            logger.error("Failed to list tasks for %s: %s", program, exc)
            return []

    async def get_task_info(
        self,
        program: str,
        task_name: str,
    ) -> Dict[str, Any]:
        """Get detailed information about a specific task definition.

        Args:
            program: Program name/slug.
            task_name: Task name.

        Returns:
            Task definition details as a dict.
        """
        try:
            resp = await self._ft_request(
                "GET",
                f"/api/v2/task/{program}/{task_name}",
            )
            return resp.get("data", {})
        except Exception as exc:
            logger.error(
                "Failed to get task info for %s/%s: %s",
                program, task_name, exc,
            )
            return {"error": str(exc)}

    # -----------------------------------------------------------------
    # Result formatting
    # -----------------------------------------------------------------

    @staticmethod
    def _ft_format_result(result: Any) -> Any:
        """Normalize task result into a JSON-serializable format.

        Handles pandas DataFrames, dicts, lists, and scalar values.
        """
        try:
            import pandas as pd  # pylint: disable=import-outside-toplevel

            if isinstance(result, pd.DataFrame):
                return {
                    "type": "dataframe",
                    "data": result.to_dict(orient="records"),
                    "columns": list(result.columns),
                    "shape": list(result.shape),
                    "row_count": len(result),
                }
        except ImportError:
            pass

        if isinstance(result, dict):
            return {"type": "dict", "data": result}
        if isinstance(result, list):
            return {"type": "list", "data": result, "count": len(result)}
        if result is None:
            return None
        return {"type": type(result).__name__, "data": str(result)}


__all__ = [
    # Enums
    "TaskStatus",
    "TaskCodeFormat",
    # Request models
    "TaskExecutionRequest",
    "TaskCodeRequest",
    "WorkerTaskRequest",
    # Response models
    "TaskResult",
    "JobInfo",
    # Interface
    "FlowtaskInterface",
]
