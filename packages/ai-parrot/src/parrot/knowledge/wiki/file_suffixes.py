"""File-suffix sets shared by the repo scanner and the Claude Code hook.

Stdlib-only on purpose: the ``PreToolUse`` hook imports these on every
tool call, so this module must never import pydantic, the scanners or the
store (FEAT-595).
"""

from __future__ import annotations

#: File suffixes treated as source code (category ``module``).
#:
#: ``.svelte`` is claimed by the JS/TS scanner (FEAT-396), which analyses
#: the component's ``<script>`` block — not its markup.
CODE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".pyx",
        ".pxd",
        ".pyi",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".svelte",
        ".php",
        ".pl",
        ".pm",
        ".t",
        ".sql",
        ".sh",
        ".bash",
        ".lua",
        ".luau",
    }
)

#: File suffixes treated as documentation (category ``document``).
DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt", ".html", ".htm"})

__all__ = ["CODE_SUFFIXES", "DOC_SUFFIXES"]
