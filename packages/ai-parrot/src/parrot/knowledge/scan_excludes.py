"""The single source of truth for directories no scanner ever descends into.

Both knowledge subsystems walk the same repositories and had grown their
own copy of this list: ``wiki.repo_scan.DEFAULT_EXCLUDE_DIRS`` and
``graphindex.cli._ALWAYS_SKIP``. The graphindex copy was a strict subset,
missing exactly the tool-output directories (``.claude``, ``.parrot``,
``.worktrees``, ``.graphindex``, ``.obsidian``, ``.trash``) — so anything
discovering through graphindex re-scanned every SDD worktree, i.e. a full
duplicate copy of the repository per open worktree.

This module owns the union. It deliberately imports nothing: every CLI
entry point pays for whatever a scanner's constants module drags in, so
the shared list must stay a leaf.

Names here are matched against individual path PARTS, never prefixes — a
directory called ``build`` is pruned at any depth. Path-prefix exclusions
(e.g. a nested wiki bundle) are a separate concern owned by the caller.
"""

from __future__ import annotations

#: Directory names never descended into, by any scanner in this package.
SCAN_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        # Version control metadata.
        ".git",
        ".hg",
        ".svn",
        # Interpreter / package manager output.
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".tox",
        "build",
        "dist",
        ".eggs",
        # Editor and linter caches.
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        # Tool output planes. Scanning these re-ingests the tool's own
        # artifacts, and `.claude` in particular holds SDD worktrees —
        # a complete second copy of the repository, per worktree.
        ".parrot",
        ".claude",
        ".worktrees",
        ".graphindex",
        # Obsidian vault internals — never descend into these when a repo
        # embeds a vault (the vault build mode has its own scanner).
        ".obsidian",
        ".trash",
    }
)
