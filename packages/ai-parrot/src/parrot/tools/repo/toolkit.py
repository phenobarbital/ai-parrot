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
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from parrot.knowledge.wiki import search as wiki_search_module
from parrot.knowledge.wiki.context import pack_results
from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit

from .confinement import (
    PathOutsideRootError,
    SecretFileError,
    is_secret_path,
    resolve_readable_path,
    resolve_within_root,
)
from .git_tools import (
    LOG_FORMAT,
    SHOW_FORMAT,
    InvalidRefError,
    parse_blame,
    parse_log,
    split_show_output,
    validate_ref,
)
from .graph_search import map_neighbor_hit, map_search_hit, open_plane
from .models import RepoReadResult, RepoSearchHit, RepoSearchResult, RepoToolError
from .schemas import (
    GitBlameInput,
    GitLogInput,
    GitShowInput,
    GrepFilesInput,
    ListFilesInput,
    ReadFileInput,
    RelatedCodeInput,
    SearchCodeInput,
    WebSearchInput,
)

#: Directories never descended into by `list_files`, regardless of depth.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)


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
        self._plane_cached: tuple[Any, str] | None = None
        self.logger = logging.getLogger(__name__)

        # Capture the serializable constructor kwargs (mirroring the
        # `VectorStoreSearchTool` convention) so `build_envelope_from_tool`
        # can reconstruct this toolkit for remote/off-process execution.
        # `wiki_store` is deliberately excluded: a live store object cannot
        # cross a process boundary; the remote side re-resolves its own
        # plane lazily via `open_plane()` instead.
        self._init_kwargs.update(
            {
                "repo_root": str(self._repo_root),
                "wiki_name": wiki_name,
                "enable_web_search": enable_web_search,
                "default_search_mode": default_search_mode,
                "deny_secret_files": deny_secret_files,
                "max_result_bytes": max_result_bytes,
                "max_search_hits": max_search_hits,
                "search_budget_tokens": search_budget_tokens,
                "command_timeout": command_timeout,
            }
        )

        if not enable_web_search:
            # Shadow the class attribute with an instance one, before any
            # tool generation. `_generate_tools()` (`toolkit.py:548`) reads
            # `self.exclude_tools`, so `web_search` is never turned into a
            # tool at all — spec §3 Module 5: absent, not disabled.
            self.exclude_tools = (*self.exclude_tools, "web_search")

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
        self,
        path: str,
        start: int = 1,
        end: int = 0,
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
            raw = "".join(lines[max(start - 1, 0) : end_index])

        content = raw
        truncated = False
        encoded = content.encode("utf-8", errors="replace")
        if len(encoded) > self._max_result_bytes:
            truncated = True
            content = encoded[: self._max_result_bytes].decode("utf-8", errors="ignore")
            content += f"\n... [truncated: {total_bytes} bytes total, " f"{self._max_result_bytes} returned] ...\n"

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
                    try:
                        resolved = entry.resolve()
                    except OSError:
                        continue
                    if resolved != self._repo_root and not resolved.is_relative_to(self._repo_root):
                        # Symlink escape (spec §7): a symlinked entry whose
                        # real target is outside repo_root must never be
                        # listed or descended into — same containment rule
                        # resolve_within_root enforces for path arguments.
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

    async def _run_argv(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run an argv list in the repo root, bounded and cancellation-safe.

        Never uses a shell. The child is killed on timeout AND on
        cancellation, so a cancelled dispatch leaves no orphan process
        (spec §7).

        Args:
            argv: Program and arguments as a list — never a single string.
            timeout: Seconds; defaults to ``self._command_timeout``.

        Returns:
            Mapping with ``exit_code``, ``stdout``, ``stderr``, ``timed_out``,
            and ``stdout_truncated`` — whether raw stdout exceeded
            ``max_result_bytes`` before this method clipped it. Callers that
            do their own additional truncation accounting downstream of an
            already-clipped ``stdout`` (e.g. `git_show`'s diffstat) must
            check ``stdout_truncated`` rather than re-measuring the clipped
            string, which can never itself appear over-length.
        """
        limit = timeout if timeout is not None else self._command_timeout
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._repo_root),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
        except TimeoutError:
            self._kill(proc)
            await proc.wait()
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "timeout",
                "timed_out": True,
                "stdout_truncated": False,
            }
        except asyncio.CancelledError:
            self._kill(proc)
            # Do not await proc.wait() here on a cancel path; reap and re-raise.
            raise
        return {
            "exit_code": proc.returncode,
            "stdout": out[: self._max_result_bytes].decode("utf-8", "replace"),
            "stderr": err[:4096].decode("utf-8", "replace"),
            "timed_out": False,
            "stdout_truncated": len(out) > self._max_result_bytes,
        }

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        """Best-effort terminate; an already-exited child is not an error."""
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    def _is_git_work_tree(self) -> bool:
        """True when `git` is available and `repo_root` looks like a work tree."""
        return shutil.which("git") is not None and (self._repo_root / ".git").exists()

    def _hits_from_grep_lines(self, stdout: str) -> list[RepoSearchHit]:
        """Parse ``path:lineno:content`` lines into bounded, filtered hits."""
        hits: list[RepoSearchHit] = []
        for line in stdout.splitlines():
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            rel_path, _lineno, content = parts
            if self._deny_secret_files and is_secret_path(rel_path):
                continue
            try:
                resolve_within_root(self._repo_root, rel_path)
            except PathOutsideRootError:
                continue
            hits.append(
                RepoSearchHit(
                    page_id="",
                    path=rel_path,
                    summary=content.strip()[:300],
                    score=0.0,
                )
            )
            if len(hits) >= self._max_search_hits:
                break
        return hits

    def _walk_grep(self, pattern: str, glob: str) -> list[RepoSearchHit]:
        """Bounded, in-process fallback search for a non-git repo root."""
        hits: list[RepoSearchHit] = []
        for dirpath, dirnames, filenames in os.walk(self._repo_root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for filename in sorted(filenames):
                if len(hits) >= self._max_search_hits:
                    return hits
                full = Path(dirpath) / filename
                rel = self._rel(full)
                if glob and not full.match(glob):
                    continue
                if self._deny_secret_files and is_secret_path(rel):
                    continue
                try:
                    resolved = full.resolve()
                except OSError:
                    continue
                if resolved != self._repo_root and not resolved.is_relative_to(self._repo_root):
                    # A symlinked file whose real target escapes repo_root
                    # (os.walk's default followlinks=False already keeps
                    # symlinked *directories* out of this traversal, but a
                    # symlinked *file* still shows up in `filenames` here).
                    continue
                try:
                    text = full.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line in text.splitlines():
                    if pattern in line:
                        hits.append(
                            RepoSearchHit(
                                page_id="",
                                path=rel,
                                summary=line.strip()[:300],
                                score=0.0,
                            )
                        )
                        break
        return hits

    @tool_schema(GrepFilesInput)
    async def grep_files(
        self,
        pattern: str,
        glob: str = "",
    ) -> RepoSearchResult | RepoToolError:
        """Search the repository for a literal string.

        Prefer `search_code` for conceptual or symbol lookups — it is
        ranked and ignores build artifacts. Use `grep_files` for exact
        strings, config values, or anything not indexed by the code graph.
        The pattern is matched literally (not as a regex). Secret files
        (e.g. `.env`, private keys) are never included in results.

        Args:
            pattern: The literal string to search for.
            glob: Optional glob restricting which files are searched.

        Returns:
            A RepoSearchResult with matching hits (never an error result
            for zero matches — that is a normal, empty result).
        """
        if self._is_git_work_tree():
            argv = [
                "git",
                "grep",
                "--line-number",
                "--no-color",
                "-I",
                "--untracked",
                "-F",
                "-e",
                pattern,
                "--",
            ]
            if glob:
                argv.append(f":(glob){glob}")
            result = await self._run_argv(argv)
            if result["timed_out"]:
                self.logger.warning("grep_files: git grep timed out")
                hits: list[RepoSearchHit] = []
            elif result["exit_code"] not in (0, 1):
                self.logger.warning(
                    "grep_files: git grep failed (%s): %s",
                    result["exit_code"],
                    result["stderr"],
                )
                hits = []
            else:
                hits = self._hits_from_grep_lines(result["stdout"])
        else:
            hits = await asyncio.to_thread(self._walk_grep, pattern, glob)

        return RepoSearchResult(query=pattern, hits=hits, degraded=False)

    @tool_schema(GitLogInput)
    async def git_log(
        self,
        path: str = "",
        limit: int = 20,
    ) -> dict[str, Any] | RepoToolError:
        """List recent commits, optionally only those touching one path.

        Use this to understand why code looks the way it does, or to find
        when a behaviour changed. Paths are relative to the repository
        root.

        Args:
            path: Repository-relative path to filter by. Empty = whole repo.
            limit: Maximum commits to return (clamped to 200).

        Returns:
            Mapping with a `commits` list of {sha, author, date, subject},
            or RepoToolError when the path is refused or git is unavailable.
        """
        argv = [
            "git",
            "log",
            f"--max-count={min(max(limit, 1), 200)}",
            f"--format={LOG_FORMAT}",
        ]
        if path:
            try:
                target = resolve_within_root(self._repo_root, path)
            except PathOutsideRootError as exc:
                return self._error(exc, path)
            argv += ["--", str(target.relative_to(self._repo_root))]
        else:
            argv.append("--")

        try:
            res = await self._run_argv(argv)
        except FileNotFoundError as exc:  # `git` not on PATH
            return RepoToolError(error="git_unavailable", detail=str(exc))
        if res["timed_out"]:
            return RepoToolError(error="timeout", detail="git log timed out")
        if res["exit_code"] != 0:
            return RepoToolError(
                error="git_error",
                detail=res["stderr"][:500],
                path=path,
            )
        return {"commits": parse_log(res["stdout"])}

    @tool_schema(GitShowInput)
    async def git_show(self, ref: str) -> dict[str, Any] | RepoToolError:
        """Show a commit's message and change summary.

        Use this to see what a specific commit changed and why. `ref` may
        be a sha, branch, tag, or a relative ref such as `HEAD~3`.

        Args:
            ref: A commit sha, branch, tag, or ref such as "HEAD~3".

        Returns:
            Mapping with `commit_info` (sha/author/date/subject) and `stat` (the
            diffstat text, bounded and possibly truncated), or a
            RepoToolError when the ref is unsafe or git fails.
        """
        try:
            safe_ref = validate_ref(ref)
        except InvalidRefError as exc:
            return self._error(exc, ref)

        argv = ["git", "show", "--stat", f"--format={SHOW_FORMAT}", safe_ref, "--"]
        try:
            res = await self._run_argv(argv)
        except FileNotFoundError as exc:
            return RepoToolError(error="git_unavailable", detail=str(exc))
        if res["timed_out"]:
            return RepoToolError(error="timeout", detail="git show timed out")
        if res["exit_code"] != 0:
            return RepoToolError(
                error="git_error",
                detail=res["stderr"][:500],
                path=ref,
            )

        commit_info, stat_text = split_show_output(res["stdout"])
        # `res["stdout"]` was already clipped to `max_result_bytes` by
        # `_run_argv`, so re-measuring `stat_text` here can never itself
        # exceed the bound — `stdout_truncated` is the only reliable signal
        # that the raw git output was cut off before we ever saw it.
        truncated = res["stdout_truncated"]
        if truncated:
            stat_text += "\n... [truncated] ...\n"
        return {"commit_info": commit_info, "stat": stat_text, "truncated": truncated}

    @tool_schema(GitBlameInput)
    async def git_blame(
        self,
        path: str,
        start: int = 1,
        end: int = 0,
    ) -> dict[str, Any] | RepoToolError:
        """Show per-line commit attribution for a file.

        Use this to find who last changed a specific line and in which
        commit. Secret files are refused, since blame output includes the
        file's content.

        Args:
            path: Repository-relative path to blame.
            start: 1-based first line to blame.
            end: 1-based last line, inclusive. 0 (the default) means EOF.

        Returns:
            Mapping with a `lines` list of {line, sha, author, summary,
            content}, or a RepoToolError when the path is refused or git
            fails.
        """
        try:
            target = self._resolve_for_read(path)
        except (PathOutsideRootError, SecretFileError) as exc:
            return self._error(exc, path)

        argv = ["git", "blame", "--porcelain"]
        if start > 1 or end:
            argv += ["-L", f"{start},{end}" if end else f"{start},"]
        argv += ["--", str(target.relative_to(self._repo_root))]

        try:
            res = await self._run_argv(argv)
        except FileNotFoundError as exc:
            return RepoToolError(error="git_unavailable", detail=str(exc))
        if res["timed_out"]:
            return RepoToolError(error="timeout", detail="git blame timed out")
        if res["exit_code"] != 0:
            return RepoToolError(
                error="git_error",
                detail=res["stderr"][:500],
                path=path,
            )
        return {"lines": parse_blame(res["stdout"])}

    async def _plane(self) -> tuple[Any | None, str]:
        """Return the cached (store, reason) pair, opening it on first use.

        An injected `wiki_store` short-circuits resolution entirely, which
        is what keeps the unit tests hermetic.
        """
        if self._wiki_store is not None:
            return self._wiki_store, ""
        if self._plane_cached is None:
            self._plane_cached = await open_plane(self._repo_root)
        return self._plane_cached

    async def _degrade(self, query: str, reason: str) -> RepoSearchResult:
        """Serve a grep result in place of a graph result, and SAY SO.

        Spec §7 forbids silent degradation: the marker and the reason
        travel in the payload the model reads, and a warning is logged for
        the operator.
        """
        self.logger.warning(
            "search_code degrading to grep_files: %s (query=%r)",
            reason,
            query,
        )
        fallback = await self.grep_files(query)
        if isinstance(fallback, RepoSearchResult):
            fallback.degraded = True
            fallback.degraded_reason = reason
            return fallback
        return RepoSearchResult(
            query=query,
            hits=[],
            degraded=True,
            degraded_reason=f"{reason}; grep fallback also failed",
        )

    @tool_schema(SearchCodeInput)
    async def search_code(
        self,
        query: str,
        top_k: int = 12,
        mode: Literal["lexical", "vector", "combined"] | None = None,
    ) -> RepoSearchResult:
        """Search the codebase's structural index for relevant files and modules.

        PREFER THIS over `grep_files` for any question about where
        something lives or how modules relate: it returns ranked,
        deduplicated results with summaries and skips build artifacts,
        where grep returns raw unranked line matches. Use `grep_files`
        only for exact strings, regexes, or config values this index does
        not cover.

        Args:
            query: What you are looking for — name the symbol, module or
                subsystem, not your theory about where it might be.
            top_k: Maximum results to return.
            mode: "lexical" (default) matches names and text — best for
                symbols and modules. "combined" also considers semantic
                similarity where available. "vector" is semantic only.
                When semantic search is not configured, these fall back to
                lexical and the result is marked degraded.

        Returns:
            RepoSearchResult. Check `degraded`: when True, the structural
            index was unavailable (or returned nothing usable) and these
            are weaker grep-based results, or the mode itself degraded.
        """
        store, reason = await self._plane()
        if store is None:
            return await self._degrade(query, reason or "no wiki plane")

        effective = mode or self._default_search_mode
        note = ""
        if effective == "vector":
            # No embedder ships (spec §8 Q4), so the vector leg is skipped
            # by the plane and a pure-vector query would return nothing.
            effective, note = "lexical", "semantic search not configured"

        try:
            search = wiki_search_module.WikiCombinedSearch(
                pageindex_toolkit=None,
                graphindex_toolkit=None,
                store=store,
            )
            results = await search.search(
                query,
                mode=effective,
                top_k=min(top_k, self._max_search_hits),
                tree_name=self._wiki_name,
            )
        except Exception as exc:  # noqa: BLE001
            return await self._degrade(query, f"plane query failed: {exc}")

        if not results:
            # The plane logs and swallows its own per-leg query errors
            # rather than raising, so an empty result here is the only
            # observable signal of either "no matches" or "the plane
            # failed underneath us" — treat both as degraded rather than
            # returning a silently-empty structural result.
            return await self._degrade(
                query,
                note or "plane query returned no results",
            )

        packed = pack_results(results, budget_tokens=self._search_budget_tokens)
        hits = [map_search_hit(r) for r in results[: packed.results_packed or len(results)]]
        return RepoSearchResult(
            query=query,
            hits=hits,
            degraded=bool(note),
            degraded_reason=note,
            total_tokens=packed.tokens_used,
        )

    @tool_schema(RelatedCodeInput)
    async def related_code(self, page_id: str) -> RepoSearchResult:
        """Find pages related to a page returned by `search_code`.

        Use this to explore what a file/module contains or connects to
        (e.g. a directory's files, an import relationship) via the code
        graph's typed edges.

        Args:
            page_id: A page id previously returned by `search_code`.

        Returns:
            RepoSearchResult with neighbouring pages as hits, or a
            degraded result when the structural index is unavailable.
        """
        store, reason = await self._plane()
        if store is None:
            return await self._degrade(page_id, reason or "no wiki plane")

        try:
            edges = await store.neighbors(page_id)
        except Exception as exc:  # noqa: BLE001
            return await self._degrade(page_id, f"plane query failed: {exc}")

        hits = [map_neighbor_hit(edge) for edge in edges]
        return RepoSearchResult(query=page_id, hits=hits, degraded=False)

    @tool_schema(WebSearchInput)
    async def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """Search the public web.

        Use only for information outside this repository — library
        documentation, error messages, upstream changes. For anything
        about this codebase, use `search_code` instead.

        Args:
            query: What to search the web for.
            max_results: Maximum results to return.

        Returns:
            Mapping with a `results` list, or an `error` key when web
            search is unavailable.
        """
        try:
            from parrot_tools.ddgsearch import DdgSearchTool
        except ImportError as exc:
            self.logger.warning("web_search unavailable: %s", exc)
            return {
                "error": "web_search_unavailable",
                "detail": str(exc),
                "results": [],
            }
        try:
            tool = DdgSearchTool()
            result = await tool.execute(query=query, max_results=max_results)
            return {"results": getattr(result, "result", result)}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("web_search failed: %s", exc)
            return {
                "error": "web_search_failed",
                "detail": str(exc),
                "results": [],
            }
