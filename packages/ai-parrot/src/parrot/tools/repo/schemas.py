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


class GrepFilesInput(BaseModel):
    """Arguments for ``grep_files``."""

    pattern: str = Field(
        ..., description="Fixed-string pattern to search for, literally."
    )
    glob: str = Field(
        default="", description="Optional glob to restrict which files are searched."
    )


class GitLogInput(BaseModel):
    """Arguments for ``git_log``."""

    path: str = Field(
        default="",
        description="Repository-relative path to filter by. Empty = whole repo.",
    )
    limit: int = Field(
        default=20, ge=1, description="Maximum commits to return (clamped to 200)."
    )


class GitShowInput(BaseModel):
    """Arguments for ``git_show``."""

    ref: str = Field(
        ..., description="A commit sha, branch, tag, or ref such as 'HEAD~3'."
    )


class GitBlameInput(BaseModel):
    """Arguments for ``git_blame``."""

    path: str = Field(..., description="Repository-relative path to blame.")
    start: int = Field(
        default=1, ge=1, description="1-based first line to blame."
    )
    end: int = Field(
        default=0, ge=0, description="1-based last line, inclusive. 0 means EOF."
    )
