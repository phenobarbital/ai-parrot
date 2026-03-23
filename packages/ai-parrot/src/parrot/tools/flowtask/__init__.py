"""Flowtask Toolkit — optional extra.

This package is only functional when ``flowtask`` is installed.
Install with: pip install ai-parrot[flowtask]

The module-level classes are always importable, but instantiating
FlowtaskToolkit without flowtask installed will raise a clear ImportError.
"""
from __future__ import annotations

# Always-importable exports — flowtask itself is loaded lazily inside the class
from .tool import (
    FlowtaskToolkit,
    FlowtaskTool,  # Backward compatibility alias
    FlowtaskComponentInput,
    FlowtaskTaskExecutionInput,
    FlowtaskRemoteExecutionInput,
    FlowtaskCodeExecutionInput,
    FlowtaskTaskServiceInput,
    FlowtaskListTasksInput,
    TaskCodeFormat,
)

__all__ = [
    "FlowtaskToolkit",
    "FlowtaskTool",
    "FlowtaskComponentInput",
    "FlowtaskTaskExecutionInput",
    "FlowtaskRemoteExecutionInput",
    "FlowtaskCodeExecutionInput",
    "FlowtaskTaskServiceInput",
    "FlowtaskListTasksInput",
    "TaskCodeFormat",
]
