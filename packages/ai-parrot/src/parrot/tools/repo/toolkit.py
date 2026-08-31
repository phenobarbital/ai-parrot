"""``ReadOnlyRepoToolkit`` — cwd-confined, write-free repository access.

See ``sdd/specs/readonly-repo-toolkit.spec.md`` (FEAT-484) §2/§3 Module 1.
This module currently implements the static grounding axis (``read_file``,
``list_files``); later tasks add ``grep_files``, the local git history
tools, graph-backed search, and the opt-in ``web_search`` to this same
class.

Read-only by construction: this class defines no mutating method, so
``AbstractToolkit._generate_tools()`` (`tools/toolkit.py:537`) — which
turns every public ``async def`` into an LLM-callable tool — has nothing
to expose. There is no flag that adds write capability.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit

from .confinement import (
    PathOutsideRootError,
    SecretFileError,
    is_secret_path,
    resolve_readable_path,
    resolve_within_root,
)
from .models import RepoReadResult, RepoToolError
from .schemas import ListFilesInput, ReadFileInput

#: Directories never descended into by `list_files`, regardless of depth.
_SKIP_DIRS = frozenset({
    ".git", ".venv", "__pycache__", "node_modules", "build", "dist",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
})


class ReadOnlyRepoToolkit(AbstractToolkit):
    """Cwd-confined, write-free repository access for any AbstractClient."""

    def __init__(
        self,
        *,
        repo_root: Path,
        wiki_store: object | None = None,
        wiki_name: str = "parrot",
        enable_web_search: bool = False,
        default_search_mode: Literal["lexical", "vector", "combined"] = "lexical",
        deny_secret_files: bool = True,
        max_result_bytes: int = 64_000,
        max_search_hits: int = 12,
        search_budget_tokens: int = 4_000,
        command_timeout: float = 20.0,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit.

        Args:
            repo_root: The repository checkout this toolkit is confined to.
            wiki_store: An already-open wiki store, or None to resolve one
                lazily (consumed by the graph-backed search tools).
            wiki_name: The wiki plane name to query.
            enable_web_search: When True, exposes the ``web_search`` tool.
                When False, the method is not exposed as a tool at all.
            default_search_mode: The default ``search_code`` mode.
            deny_secret_files: When True (default), the secret deny-list
                (spec §8 Q1) applies to `read_file` / `grep_files` /
                `list_files`. Never affects path containment.
            max_result_bytes: Byte bound applied to any single tool result.
            max_search_hits: Maximum number of hits returned by search tools.
            search_budget_tokens: Token budget for `search_code` results.
            command_timeout: Timeout, in seconds, for any subprocess.
            **kwargs: Forwarded to `AbstractToolkit.__init__`.
        """
        super().__init__(**kwargs)
        self._repo_root = Path(repo_root).resolve()
        self._wiki_store = wiki_store
        self._wiki_name = wiki_name
        self._enable_web_search = enable_web_search
        self._default_search_mode = default_search_mode
        self._deny_secret_files = deny_secret_files
        self._max_result_bytes = max_result_bytes
        self._max_search_hits = max_search_hits
        self._search_budget_tokens = search_budget_tokens
        self._command_timeout = command_timeout
        self.logger = logging.getLogger(__name__)

    def _error(self, exc: Exception, path: str = "") -> RepoToolError:
        """Convert a confinement exception into a model-readable error.

        NEVER re-raises: spec §2 requires a structured tool error the model
        can recover from, not an exception that aborts the dispatch loop.

        Args:
            exc: The exception raised while resolving or reading a path.
            path: The caller-supplied path that triggered the failure.

        Returns:
            A `RepoToolError` describing the failure.
        """
        if isinstance(exc, SecretFileError):
            code = "secret_file"
        elif isinstance(exc, PathOutsideRootError):
            code = "path_outside_root"
        elif isinstance(exc, FileNotFoundError):
            code = "not_found"
        elif isinstance(exc, IsADirectoryError):
            code = "not_a_file"
        else:
            code = "error"
        self.logger.warning("repo tool rejected %r: %s", path, exc)
        return RepoToolError(error=code, detail=str(exc), path=path)

    def _rel(self, target: Path) -> str:
        """Render an absolute, confined path as repo-relative POSIX text."""
        try:
            return target.relative_to(self._repo_root).as_posix()
        except ValueError:
            return target.as_posix()

    def _resolve_for_read(self, path: str) -> Path:
        """Resolve `path`, applying the deny-list only when enabled.

        Raises:
            PathOutsideRootError: `path` escapes the repository root.
            SecretFileError: `path` matches the secret deny-list and
                `deny_secret_files` is True.
        """
        if self._deny_secret_files:
            return resolve_readable_path(self._repo_root, path)
        return resolve_within_root(self._repo_root, path)

    @tool_schema(ReadFileInput)
    async def read_file(
        self, path: str, start: int = 1, end: int = 0,
    ) -> RepoReadResult | RepoToolError:
        """Read a text file from the repository, optionally a line range.

        Use this after `search_code` has told you which file to open. Paths
        are relative to the repository root; paths outside it are refused,
        as are secret files such as `.env` or private keys. Large files are
        truncated — pass `start`/`end` to page through one instead.

        Args:
            path: Repository-relative path, e.g. "pkg/sub/mod.py".
            start: 1-based first line to return. Defaults to the file start.
            end: 1-based last line, inclusive. 0 (the default) means end of
                file.

        Returns:
            RepoReadResult with the content, or RepoToolError if refused.
        """
        try:
            target = self._resolve_for_read(path)
        except (PathOutsideRootError, SecretFileError) as exc:
            return self._error(exc, path)

        def _read() -> tuple[str, int]:
            total = target.stat().st_size
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read(), total

        try:
            raw, total_bytes = await asyncio.to_thread(_read)
        except (FileNotFoundError, IsADirectoryError, OSError) as exc:
            return self._error(exc, path)

        if start > 1 or end:
            lines = raw.splitlines(keepends=True)
            end_index = end if end else len(lines)
            raw = "".join(lines[max(start - 1, 0):end_index])

        content = raw
        truncated = False
        encoded = content.encode("utf-8", errors="replace")
        if len(encoded) > self._max_result_bytes:
            truncated = True
            content = encoded[: self._max_result_bytes].decode(
                "utf-8", errors="ignore"
            )
            content += (
                f"\n... [truncated: {total_bytes} bytes total, "
                f"{self._max_result_bytes} returned] ...\n"
            )

        return RepoReadResult(
            path=self._rel(target),
            content=content,
            truncated=truncated,
            total_bytes=total_bytes,
        )

    @tool_schema(ListFilesInput)
    async def list_files(self, path: str = ".", depth: int = 1) -> dict[str, Any]:
        """List files and directories under a repository path.

        Use this to explore repository structure before reading a file.
        Skips VCS/build/cache directories and any secret files. Results are
        bounded — increase `depth` sparingly on large trees.

        Args:
            path: Repository-relative directory to list. Defaults to root.
            depth: How many directory levels to recurse. 1 means immediate
                children only.

        Returns:
            A dict with `path`, `files` (repo-relative paths) and
            `truncated`, or a `RepoToolError`-shaped dict if `path` is
            refused.
        """
        try:
            base = resolve_within_root(self._repo_root, path)
        except PathOutsideRootError as exc:
            return self._error(exc, path).model_dump()

        max_hits = min(self._max_search_hits * 10, 500)

        def _walk() -> tuple[list[str], bool]:
            found: list[str] = []
            hit_bound = False

            def _recurse(directory: Path, remaining_depth: int) -> None:
                nonlocal hit_bound
                if hit_bound or remaining_depth <= 0:
                    return
                try:
                    entries = sorted(directory.iterdir())
                except OSError:
                    return
                for entry in entries:
                    if hit_bound:
                        return
                    if entry.name in _SKIP_DIRS:
                        continue
                    rel = self._rel(entry)
                    if is_secret_path(rel):
                        continue
                    if entry.is_dir():
                        found.append(rel + "/")
                        if len(found) >= max_hits:
                            hit_bound = True
                            return
                        _recurse(entry, remaining_depth - 1)
                    else:
                        found.append(rel)
                        if len(found) >= max_hits:
                            hit_bound = True
                            return

            _recurse(base, depth)
            return found, hit_bound

        files, truncated = await asyncio.to_thread(_walk)
        return {
            "path": self._rel(base) or ".",
            "files": files,
            "truncated": truncated,
        }
