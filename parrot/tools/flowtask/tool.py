"""
FlowtaskToolkit for AI-Parrot - Execute Flowtask components and tasks dynamically.

This toolkit provides tools for:
- Running individual Flowtask components with custom input data
- Executing local Flowtask tasks
- Calling remote Flowtask API endpoints
- Running tasks from JSON/YAML code definitions
"""
import os
import re
import io
import uuid
import json
import asyncio
import traceback
import importlib
from typing import Any, Dict, List, Optional, Union, Type
from enum import Enum
from contextlib import redirect_stdout
from pydantic import BaseModel, Field
import pandas as pd
from ..toolkit import AbstractToolkit
from ..decorators import tool_schema


# -----------------------------
# Input models (schemas)
# -----------------------------

class FlowtaskComponentInput(BaseModel):
    """Input schema for component_call tool."""

    component_name: str = Field(
        description="Name of the Flowtask component to execute (e.g., 'GooglePlaces', 'GoogleGeoCoding')"
    )

    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dictionary of attributes to pass to the component (e.g., {'use_proxies': True, 'type': 'traffic'})"
    )

    input_data: Union[Dict[str, Any], List[Dict[str, Any]], str] = Field(
        description="Input data for the component - can be a dictionary, list of dictionaries, or JSON string"
    )

    structured_output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional structured output schema to format the results"
    )

    return_as_dataframe: bool = Field(
        default=False,
        description="Whether to return the result as a pandas DataFrame (if possible)"
    )


class FlowtaskTaskExecutionInput(BaseModel):
    """Input schema for task_execution tool."""

    program: str = Field(
        description="Program name/slug for the task (e.g., 'nextstop', 'test')"
    )

    task_name: str = Field(
        description="Name of the task to execute (e.g., 'employees_report')"
    )

    debug: bool = Field(
        default=True,
        description="Whether to run in debug mode"
    )


class FlowtaskRemoteExecutionInput(BaseModel):
    """Input schema for remote_execution tool."""

    program: str = Field(
        description="Program name/slug for the task"
    )

    task_name: str = Field(
        description="Name of the task to execute"
    )

    long_running: bool = Field(
        default=False,
        description="If True, task is enqueued and returns immediately with status. "
                    "If False, waits for task completion."
    )

    timeout: float = Field(
        default=300.0,
        description="Timeout in seconds for the API call (only applies when long_running=False)"
    )

    max_retries: int = Field(
        default=3,
        description="Maximum number of retry attempts on failure"
    )

    backoff_factor: float = Field(
        default=1.0,
        description="Backoff factor for exponential retry delay (delay = backoff_factor * 2^attempt)"
    )


class TaskCodeFormat(str, Enum):
    """Format of the task code."""
    JSON = "json"
    YAML = "yaml"


class FlowtaskCodeExecutionInput(BaseModel):
    """Input schema for code_execution tool."""

    task_code: str = Field(
        description="The task definition as JSON or YAML string"
    )

    format: TaskCodeFormat = Field(
        default=TaskCodeFormat.YAML,
        description="Format of the task code: 'json' or 'yaml'"
    )


# -----------------------------
# Toolkit implementation
# -----------------------------

class FlowtaskToolkit(AbstractToolkit):
    """
    Toolkit for executing Flowtask components and tasks dynamically.

    This toolkit provides multiple tools for:
    - Running individual Flowtask components with custom input data
    - Executing local Flowtask tasks by program/task name
    - Calling remote Flowtask API endpoints
    - Running tasks from JSON/YAML code definitions

    Example usage:
        toolkit = FlowtaskToolkit()
        tools = toolkit.get_tools()

        # Execute a component
        result = await toolkit.flowtask_component_call(
            component_name="GooglePlaces",
            input_data=[{"address": "123 Main St"}]
        )

        # Run a local task
        result = await toolkit.flowtask_task_execution(
            program="nextstop",
            task_name="employees_report"
        )
    """

    def __init__(self, **kwargs):
        """Initialize the FlowtaskToolkit."""
        super().__init__(**kwargs)

        # Component cache to avoid repeated imports
        self._component_cache: Dict[str, Type] = {}

        # Known components (can be extended)
        self.known_components = {
            'GooglePlaces',
        }

        # ANSI escape pattern for cleaning stdout
        self._ansi_escape = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

    # -----------------------------
    # Helper methods
    # -----------------------------

    def _import_component(self, component_name: str) -> Type:
        """
        Dynamically import a Flowtask component.

        Args:
            component_name: Name of the component to import

        Returns:
            Component class

        Raises:
            ImportError: If component cannot be imported
        """
        # Check cache first
        if component_name in self._component_cache:
            return self._component_cache[component_name]

        try:
            # Import from flowtask.components
            module_path = f"flowtask.components.{component_name}"
            module = importlib.import_module(module_path)
            component_class = getattr(module, component_name)

            # Cache the component
            self._component_cache[component_name] = component_class
            return component_class

        except ImportError as e:
            raise ImportError(
                f"Could not import component '{component_name}': {str(e)}"
            )
        except AttributeError as e:
            raise ImportError(
                f"Component '{component_name}' not found in module: {str(e)}"
            )

    def _prepare_input_data(
        self,
        input_data: Union[Dict, List, str]
    ) -> Union[pd.DataFrame, Dict, List]:
        """
        Prepare input data for the component.

        Args:
            input_data: Raw input data

        Returns:
            Processed input data (DataFrame, dict, or list)
        """
        try:
            # Handle string input (assume JSON)
            if isinstance(input_data, str):
                input_data = json.loads(input_data)

            # Convert list of dictionaries to DataFrame
            if isinstance(input_data, list) and len(input_data) > 0:
                if isinstance(input_data[0], dict):
                    return pd.DataFrame(input_data)
                else:
                    return input_data

            # Convert dictionary to DataFrame if it has list values
            if isinstance(input_data, dict):
                if all(isinstance(v, list) for v in input_data.values()):
                    try:
                        return pd.DataFrame(input_data)
                    except ValueError:
                        return input_data
                else:
                    # Single row dictionary
                    return pd.DataFrame([input_data])

            return input_data

        except Exception:
            return input_data

    def _format_output(
        self,
        result: Any,
        structured_output: Optional[Dict[str, Any]] = None,
        return_as_dataframe: bool = False
    ) -> Any:
        """
        Format the component output according to specifications.

        Args:
            result: Raw component result
            structured_output: Optional output structure
            return_as_dataframe: Whether to return as DataFrame

        Returns:
            Formatted result
        """
        try:
            # If result is already a DataFrame
            if isinstance(result, pd.DataFrame):
                if return_as_dataframe:
                    return {
                        "data": result.to_dict(orient='records'),
                        "columns": list(result.columns),
                        "shape": result.shape,
                        "type": "dataframe"
                    }
                else:
                    return result.to_dict(orient='records')

            # If result is a list and we want DataFrame format
            if isinstance(result, list) and return_as_dataframe:
                if result and isinstance(result[0], dict):
                    df = pd.DataFrame(result)
                    return {
                        "data": result,
                        "columns": list(df.columns),
                        "shape": df.shape,
                        "type": "dataframe"
                    }

            # Apply structured output if specified
            if structured_output:
                return self._apply_structured_output(result, structured_output)

            return result

        except Exception:
            return result

    def _apply_structured_output(
        self,
        result: Any,
        structure: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply structured output formatting to the result.

        Args:
            result: Raw result data
            structure: Desired output structure

        Returns:
            Structured result
        """
        try:
            if isinstance(result, pd.DataFrame):
                data = result.to_dict(orient='records')
            elif isinstance(result, list):
                data = result
            else:
                data = [result] if not isinstance(result, list) else result

            structured_result = {}
            for key, mapping in structure.items():
                if isinstance(mapping, str):
                    if isinstance(data, list) and data:
                        structured_result[key] = [
                            item.get(mapping) for item in data if isinstance(item, dict)
                        ]
                    else:
                        structured_result[key] = data.get(mapping) if isinstance(data, dict) else None
                elif isinstance(mapping, dict):
                    structured_result[key] = self._apply_structured_output(data, mapping)
                else:
                    structured_result[key] = mapping

            return structured_result

        except Exception:
            return result

    def _format_task_result(self, result: Any) -> Dict[str, Any]:
        """
        Format task execution result for consistent output.

        Args:
            result: Task execution result (typically DataFrame)

        Returns:
            Formatted result dictionary
        """
        if isinstance(result, pd.DataFrame):
            return {
                "type": "dataframe",
                "data": result.to_dict(orient='records'),
                "columns": list(result.columns),
                "shape": list(result.shape),
                "row_count": len(result)
            }
        elif isinstance(result, dict):
            return {"type": "dict", "data": result}
        elif isinstance(result, list):
            return {"type": "list", "data": result, "count": len(result)}
        else:
            return {"type": type(result).__name__, "data": str(result)}

    # -----------------------------
    # Tools (public async methods)
    # -----------------------------

    @tool_schema(FlowtaskComponentInput)
    async def flowtask_component_call(
        self,
        component_name: str,
        input_data: Union[Dict[str, Any], List[Dict[str, Any]], str],
        attributes: Optional[Dict[str, Any]] = None,
        structured_output: Optional[Dict[str, Any]] = None,
        return_as_dataframe: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a single Flowtask component with custom input data and attributes.

        This tool imports and runs any Flowtask component dynamically, allowing
        flexible data processing with custom configurations.

        Example:
            result = await flowtask_component_call(
                component_name="GooglePlaces",
                input_data=[{"address": "123 Main St"}],
                attributes={"use_proxies": True}
            )
        """
        attributes = attributes or {}

        try:
            # Import the component
            component_cls = self._import_component(component_name)

            # Prepare input data
            processed_input = self._prepare_input_data(input_data)

            # Create component instance with attributes
            component_kwargs = attributes.copy()
            component_kwargs['input'] = processed_input

            try:
                component = component_cls(**component_kwargs)
            except TypeError as e:
                return {
                    "status": "error",
                    "error": f"Failed to initialize component '{component_name}': {str(e)}",
                    "component_name": component_name
                }

            # Execute the component using async context manager
            async with component as comp:
                result = await comp.run()

                # Format the output
                formatted_result = self._format_output(
                    result,
                    structured_output,
                    return_as_dataframe
                )

                return {
                    "status": "success",
                    "result": formatted_result,
                    "metadata": {
                        "component_name": component_name,
                        "attributes": attributes,
                        "input_type": type(processed_input).__name__,
                        "output_type": type(result).__name__
                    }
                }

        except ImportError as e:
            return {
                "status": "error",
                "error": str(e),
                "component_name": component_name
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to execute component '{component_name}': {str(e)}",
                "error_type": type(e).__name__,
                "component_name": component_name
            }

    @tool_schema(FlowtaskTaskExecutionInput)
    async def flowtask_task_execution(
        self,
        program: str,
        task_name: str,
        debug: bool = True
    ) -> Dict[str, Any]:
        """
        Execute a Flowtask Task locally by program and task name.

        This runs the task using the local Flowtask Task instance,
        which processes the DAG-based workflow defined in the task configuration.

        Example:
            result = await flowtask_task_execution(
                program="nextstop",
                task_name="employees_report",
                debug=True
            )
        """
        try:
            from flowtask.tasks.task import Task

            task = Task(program=program, task=task_name, debug=debug)

            async with task as t:
                result = await t.run()

            return {
                "status": "success",
                "program": program,
                "task": task_name,
                "result": self._format_task_result(result)
            }

        except ImportError as e:
            return {
                "status": "error",
                "error": f"Flowtask not installed or import error: {str(e)}",
                "program": program,
                "task": task_name
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
                "program": program,
                "task": task_name
            }

    @tool_schema(FlowtaskRemoteExecutionInput)
    async def flowtask_remote_execution(
        self,
        program: str,
        task_name: str,
        long_running: bool = False,
        timeout: float = 300.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0
    ) -> Dict[str, Any]:
        """
        Execute a Flowtask Task remotely via the Flowtask API.

        Calls the Flowtask API endpoint to run a task. If long_running is True,
        the task is enqueued and returns immediately with status. Otherwise,
        waits for task completion.

        Uses exponential backoff retry on transient failures.

        Example:
            result = await flowtask_remote_execution(
                program="nextstop",
                task_name="employees_report",
                long_running=False,
                timeout=600.0
            )
        """
        try:
            import httpx
        except ImportError:
            return {
                "status": "error",
                "error": "httpx package not installed. Install with: pip install httpx"
            }

        # Get TASK_DOMAIN from environment - required
        task_domain = os.getenv("TASK_DOMAIN")
        if not task_domain:
            return {
                "status": "error",
                "error": "TASK_DOMAIN environment variable is not set. "
                         "Please set it to the Flowtask API base URL."
            }

        url = f"{task_domain.rstrip('/')}/api/v2/task/{program}/{task_name}"
        payload = {"long_running": long_running}

        last_error = None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload)

                    # Handle different response codes
                    if response.status_code == 200:
                        return {
                            "status": "success",
                            "program": program,
                            "task": task_name,
                            "response": response.json()
                        }
                    elif response.status_code == 202:
                        # Task queued (long_running=True)
                        return {
                            "status": "queued",
                            "program": program,
                            "task": task_name,
                            "response": response.json()
                        }
                    elif response.status_code == 400:
                        # Task execution error
                        return {
                            "status": "task_error",
                            "program": program,
                            "task": task_name,
                            "response": response.json()
                        }
                    elif response.status_code == 406:
                        # Result not acceptable (known Flowtask bug)
                        return {
                            "status": "result_error",
                            "program": program,
                            "task": task_name,
                            "response": response.json(),
                            "note": "406 error - result data format issue (known Flowtask behavior)"
                        }
                    else:
                        # Other errors - may be transient, retry
                        last_error = f"HTTP {response.status_code}: {response.text}"
                        if attempt < max_retries - 1:
                            delay = backoff_factor * (2 ** attempt)
                            await asyncio.sleep(delay)
                            continue
                        return {
                            "status": "error",
                            "error": last_error,
                            "program": program,
                            "task": task_name
                        }

            except httpx.TimeoutException:
                last_error = f"Request timed out after {timeout} seconds"
                if attempt < max_retries - 1:
                    delay = backoff_factor * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
                if attempt < max_retries - 1:
                    delay = backoff_factor * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

        return {
            "status": "error",
            "error": last_error or "Max retries exceeded",
            "program": program,
            "task": task_name,
            "retries": max_retries
        }

    @tool_schema(FlowtaskCodeExecutionInput)
    async def flowtask_code_execution(
        self,
        task_code: str,
        format: TaskCodeFormat = TaskCodeFormat.YAML
    ) -> Dict[str, Any]:
        """
        Execute a Flowtask Task from a JSON or YAML code definition.

        This allows running ad-hoc task definitions without requiring them to be
        saved as files. The task code should follow the standard Flowtask task
        definition format with name, description, and steps.

        Example:
            result = await flowtask_code_execution(
                task_code='''
                name: My Task
                steps:
                  - GooglePlaces:
                      input: [{"address": "123 Main St"}]
                ''',
                format="yaml"
            )
        """
        try:
            from flowtask.storages import MemoryTaskStorage
            from flowtask.tasks.task import Task
        except ImportError as e:
            return {
                "status": "error",
                "error": f"Flowtask not installed or import error: {str(e)}"
            }

        # Parse task code
        try:
            if format == TaskCodeFormat.YAML or format == "yaml":
                import yaml
                body_task = yaml.safe_load(task_code)
            else:
                body_task = json.loads(task_code)
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to parse task code as {format}: {str(e)}"
            }

        task_id = str(uuid.uuid4())
        error = None
        stacktrace = None
        captured_stdout = None
        stats = None
        result = None

        try:
            task = Task(task=task_id)

            async with task as t:
                t.taskstore = MemoryTaskStorage()
                stdout = io.StringIO()

                if await t.start(payload=body_task):
                    try:
                        with redirect_stdout(stdout):
                            result = await t.run()
                    except Exception as e:
                        result = None
                        stacktrace = traceback.format_exc()
                        error = str(e)

                    captured_stdout = stdout.getvalue()
                    stats = t.get_stats()
                else:
                    error = "Failed to start task with provided payload"

        except Exception as e:
            error = str(e)
            stacktrace = traceback.format_exc()

        # Clean ANSI escape codes from stdout
        clean_stdout = None
        if captured_stdout:
            clean_stdout = self._ansi_escape.sub('', captured_stdout)

        return {
            "status": "success" if error is None else "error",
            "task_id": task_id,
            "result": self._format_task_result(result) if result is not None else None,
            "error": error,
            "stacktrace": stacktrace,
            "stdout": clean_stdout,
            "stats": stats
        }

    # -----------------------------
    # Utility methods
    # -----------------------------

    def list_known_components(self) -> List[str]:
        """
        Get a list of known Flowtask components.

        Returns:
            List of component names
        """
        return sorted(list(self.known_components))

    def add_known_component(self, component_name: str) -> None:
        """
        Add a component to the known components list.

        Args:
            component_name: Name of the component to add
        """
        self.known_components.add(component_name)

    def clear_component_cache(self) -> None:
        """Clear the component import cache."""
        self._component_cache.clear()


# Backward compatibility alias
FlowtaskTool = FlowtaskToolkit


__all__ = [
    "FlowtaskToolkit",
    "FlowtaskTool",  # Backward compatibility
    "FlowtaskComponentInput",
    "FlowtaskTaskExecutionInput",
    "FlowtaskRemoteExecutionInput",
    "FlowtaskCodeExecutionInput",
    "TaskCodeFormat",
]
