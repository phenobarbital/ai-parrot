"""Pydantic argument schemas for ``ReadOnlyRepoToolkit`` tools (FEAT-484).

Each schema is attached to its tool method with the ``@tool_schema``
decorator (`parrot/tools/decorators.py:39`) and describes the arguments an
LLM may pass when calling that tool.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReadFileInput(BaseModel):
    """Arguments for ``read_file``."""

    path: str = Field(
        ..., description="Repository-relative path, e.g. 'pkg/sub/mod.py'."
    )
    start: int = Field(
        default=1, ge=1, description="1-based first line to return."
    )
    end: int = Field(
        default=0,
        ge=0,
        description="1-based last line, inclusive. 0 means end of file.",
    )


class ListFilesInput(BaseModel):
    """Arguments for ``list_files``."""

    path: str = Field(
        default=".", description="Repository-relative directory to list."
    )
    depth: int = Field(
        default=1, ge=1, description="How many directory levels to recurse."
    )
