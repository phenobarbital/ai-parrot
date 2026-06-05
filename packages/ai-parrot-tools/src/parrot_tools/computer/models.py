"""
Data models for the Computer-Use Agent feature (FEAT-227).

All models are pure Pydantic v2 BaseModel subclasses with no external
dependencies beyond pydantic itself.
"""
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class EnvState(BaseModel):
    """State returned after each computer-use action.

    Every action executed by the AsyncComputerBackend captures a
    screenshot and the current URL, returning them as an EnvState.

    Attributes:
        screenshot: Raw PNG bytes of the current viewport.
        url: The current page URL after the action.
    """

    screenshot: bytes
    url: str


class ComputerUseConfig(BaseModel):
    """Configuration for the ComputerUse tool type in GoogleGenAIClient.

    Controls which environment the computer-use model operates in and
    which predefined functions (actions) are excluded.

    Attributes:
        environment: The environment string — always ENVIRONMENT_BROWSER
            for browser automation.
        excluded_actions: List of predefined function names to exclude
            from the model's available action set.
    """

    environment: str = "ENVIRONMENT_BROWSER"
    excluded_actions: list[str] = Field(default_factory=list)


class ComputerTask(BaseModel):
    """A reusable sequence of natural-language instructions.

    Tasks are named, described, and composed of ordered natural-language
    steps. They can be parameterised for use inside run_loop().

    Attributes:
        name: Unique task name (used as a key in the toolkit's task store).
        description: Human-readable description of the task's purpose.
        steps: Ordered list of natural-language instructions for the model.
        params_schema: Optional JSON Schema dict for validating params passed
            at runtime (e.g. when iterating over a list of records).
    """

    name: str
    description: str
    steps: list[str]
    params_schema: Optional[dict] = None


class TaskResult(BaseModel):
    """Result of a single task execution.

    Captures whether the task succeeded, any screenshots taken during
    execution, optionally extracted data, and the final URL.

    Attributes:
        task_name: Name of the task that was executed.
        success: Whether the task completed without errors.
        screenshots: List of PNG bytes captured during the task.
        extracted_data: Optional structured data extracted during the task.
        error: Error message if the task failed; None on success.
        url: The page URL at the end of the task.
    """

    task_name: str
    success: bool
    screenshots: list[bytes] = Field(default_factory=list)
    extracted_data: Optional[dict] = None
    error: Optional[str] = None
    url: str = ""


class LoopResult(BaseModel):
    """Result of a loop execution.

    Captures how many iterations completed, the reason the loop stopped,
    per-iteration results, and any errors encountered.

    Attributes:
        task_name: Name of the task that was looped.
        iterations_completed: Total number of iterations that ran.
        stop_reason: One of ``"count"``, ``"condition_met"``,
            ``"max_reached"``, ``"aborted"``, or ``"error"``.
        results: List of per-iteration TaskResult objects.
        errors: List of error messages from failed iterations.
    """

    task_name: str
    iterations_completed: int
    stop_reason: Literal["count", "condition_met", "max_reached", "aborted", "error"]
    results: list[TaskResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
