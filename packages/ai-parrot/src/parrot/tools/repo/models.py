"""Shared Pydantic contracts for the read-only repo toolkit (FEAT-484).

These models are the data contracts every tool in ``parrot.tools.repo``
returns or raises. They are deliberately free of any dependency beyond
``pydantic`` so this module can be imported without pulling in the
``AbstractToolkit`` machinery.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RepoToolError(BaseModel):
    """Structured, model-readable rejection. NEVER raised as an exception.

    Attributes:
        error: A short machine-readable error code, e.g.
            ``"path_outside_root"``, ``"secret_file"``, ``"not_found"``,
            ``"timeout"``.
        detail: A human-readable explanation of the error.
        path: The repo-relative path that triggered the error, if any.
    """

    error: str
    detail: str
    path: str = ""


class RepoReadResult(BaseModel):
    """The result of a ``read_file`` call.

    Attributes:
        path: The repo-relative path that was read.
        content: The file content (possibly truncated).
        truncated: True when the content was truncated at the byte bound.
        total_bytes: The total size of the file, in bytes, before truncation.
    """

    path: str
    content: str
    truncated: bool = False
    total_bytes: int = 0


class RepoSearchHit(BaseModel):
    """One ranked result from ``search_code`` / ``related_code``.

    Attributes:
        page_id: The wiki plane page id for this hit.
        path: The repo-relative path of the source file.
        summary: A short summary of the page's content.
        outline: API outline lines, when the page has one.
        score: The ranking score assigned to this hit.
        approx_tokens: An approximate token count for this hit's payload.
    """

    page_id: str
    path: str
    summary: str = ""
    outline: list[str] = Field(default_factory=list)
    score: float = 0.0
    approx_tokens: int = 0


class RepoSearchResult(BaseModel):
    """The envelope returned by ``search_code`` / ``related_code``.

    Attributes:
        query: The original query string.
        hits: The ranked list of search hits.
        degraded: True when this result was served by the ``grep_files``
            fallback rather than the graph-backed search.
        degraded_reason: A human-readable explanation of why the result was
            degraded, when ``degraded`` is True.
        total_tokens: The approximate total token count of the payload,
            bounded by the caller's token budget.
    """

    query: str
    hits: list[RepoSearchHit] = Field(default_factory=list)
    degraded: bool = False
    degraded_reason: str = ""
    total_tokens: int = 0
