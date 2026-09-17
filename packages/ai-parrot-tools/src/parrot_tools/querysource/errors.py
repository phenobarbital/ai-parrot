"""Error hierarchy for QuerysourceToolkit (spec §3 M1). Messages are written for the LLM."""

from __future__ import annotations

from parrot.exceptions import ToolError  # verified: packages/ai-parrot/src/parrot/exceptions.py:57


class QuerysourceToolkitError(ToolError):
    """Base for all toolkit errors."""


class SlugNotFoundError(QuerysourceToolkitError):
    """The query-slug does not exist in public.queries (wraps querysource.exceptions.SlugNotFound)."""


class TenantDeniedError(QuerysourceToolkitError):
    """The slug's program_slug is outside this toolkit's allowlist.

    Message format: ``slug '<slug>' is not available for programs <programs>``.
    """


class RawSqlForbiddenError(QuerysourceToolkitError):
    """Inline query / raw_query pipeline nodes are not allowed for this instance."""


class WriteDisabledError(QuerysourceToolkitError):
    """save_multiquery or a destination step was requested while allow_write=False."""


class InvalidConditionsError(QuerysourceToolkitError):
    """Placeholder / filter validation failed; the message lists offending keys and the allowed set."""
