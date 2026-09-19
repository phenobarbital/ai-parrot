"""Bounded, cwd-scoped local tools for the FEAT-580 pilot seat (TASK-3514).

Every tool here is deliberately small and index-free: it walks whatever
files the pilot runner already materialized under one attempt's isolated
working directory (never a persistent index, never a database) and never
reads or writes outside that directory. This is what stands in for the
``current`` and ``wiki_ast`` arms' tooling -- the repo's own
``wikitoolkit`` MCP tools query a pre-built knowledge-graph plane scoped
to a real, indexed repository, which a fresh, tiny, throwaway pilot
fixture directory never has (operator-confirmed design, TASK-3514
Completion Note / scope correction).

Path safety mirrors the existing sandboxed-reader convention elsewhere in
this repo (e.g. ``read_skill_asset``): every path argument is resolved
against the bound working directory and rejected if it would escape it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List

from parrot.tools import tool

__all__ = ("LocalTools", "build_local_tools")

#: Hard caps so a single tool call can never return an unbounded amount of
#: text to the model (mirrors the LSP toolkit's own bounded-output
#: discipline, docs/sdd/lsp-pilot.md's "200 rendered items").
_MAX_LIST_ENTRIES = 200
_MAX_SEARCH_MATCHES = 50
_MAX_FILE_BYTES = 1_000_000


class PathEscapeError(ValueError):
    """Raised when a tool argument would resolve outside the bound working directory."""


def _resolve(cwd: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` against ``cwd`` and reject any escape.

    Args:
        cwd: The attempt's isolated working directory (already an
            absolute, resolved path).
        rel_path: A caller-supplied, repository-relative path.

    Returns:
        The resolved absolute path, guaranteed to be ``cwd`` or a
        descendant of it.

    Raises:
        PathEscapeError: If the resolved path would fall outside ``cwd``.
    """
    candidate = (cwd / rel_path).resolve()
    try:
        candidate.relative_to(cwd)
    except ValueError as exc:
        raise PathEscapeError(f"path {rel_path!r} resolves outside the working directory") from exc
    return candidate


def _iter_python_files(cwd: Path) -> List[Path]:
    """Every ``.py`` file under ``cwd``, sorted for deterministic output."""
    return sorted(p for p in cwd.rglob("*.py") if p.is_file())


@dataclass(frozen=True)
class LocalTools:
    """The tool sets one pilot seat attempt may expose to the agent.

    Attributes:
        base_tools: Always exposed, every arm: file read/write/list plus
            investigation answer submission.
        wiki_ast_tools: Exposed to every arm except ``current``
            (operator-confirmed per-arm loadout table, TASK-3514).
    """

    base_tools: List[Callable[..., Any]]
    wiki_ast_tools: List[Callable[..., Any]] = field(default_factory=list)


def build_local_tools(cwd: Path, answer_holder: dict) -> LocalTools:
    """Build one attempt's bounded local tools, closed over ``cwd``.

    Args:
        cwd: The attempt's isolated, already-materialized working
            directory (``benchmarks.sdd_lsp.runner`` sets the seat's own
            process ``cwd`` to exactly this directory).
        answer_holder: A dict the ``submit_answer`` tool writes
            ``{"path": ..., "line": ...}`` into, for the caller to persist
            as ``answer.json`` after the agent's turn completes -- kept
            out-of-band so the tool's return value can stay a short
            confirmation string instead of forcing the caller to parse
            the agent's final free-text response.

    Returns:
        The :class:`LocalTools` this attempt's arm may draw from.
    """
    cwd = cwd.resolve()

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 text file's full content, given a repository-relative path."""
        target = _resolve(cwd, path)
        if not target.is_file():
            return f"error: no such file: {path}"
        size = target.stat().st_size
        if size > _MAX_FILE_BYTES:
            return f"error: {path} is {size} bytes, over the {_MAX_FILE_BYTES}-byte read limit"
        return target.read_text(encoding="utf-8", errors="replace")

    @tool
    def list_dir(path: str = ".") -> str:
        """List files and directories under a repository-relative path (non-recursive)."""
        target = _resolve(cwd, path)
        if not target.is_dir():
            return f"error: no such directory: {path}"
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        truncated = len(entries) > _MAX_LIST_ENTRIES
        entries = entries[:_MAX_LIST_ENTRIES]
        listing = "\n".join(entries)
        if truncated:
            listing += f"\n... truncated at {_MAX_LIST_ENTRIES} entries"
        return listing

    @tool
    def write_file(path: str, content: str) -> str:
        """Overwrite (or create) a repository-relative file with the given full content."""
        target = _resolve(cwd, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {path}"

    @tool
    def submit_answer(path: str, line: int) -> str:
        """Submit the final answer for a read-only investigation task: a file path and one-based line number."""
        answer_holder["path"] = path
        answer_holder["line"] = line
        return f"recorded answer: {path}:{line}"

    @tool
    def text_search(pattern: str) -> str:
        """Search every file under the working directory for a literal substring; returns matching path:line:text."""
        matches: List[str] = []
        for file_path in sorted(p for p in cwd.rglob("*") if p.is_file()):
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except (UnicodeDecodeError, OSError):
                continue
            rel = file_path.relative_to(cwd)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    matches.append(f"{rel}:{lineno}: {line.strip()}")
                    if len(matches) >= _MAX_SEARCH_MATCHES:
                        return "\n".join(matches) + f"\n... truncated at {_MAX_SEARCH_MATCHES} matches"
        return "\n".join(matches) if matches else "no matches"

    @tool
    def ast_find_definition(name: str) -> str:
        """Find every top-level or class-level function/class/assignment named ``name`` across all .py files."""
        hits: List[str] = []
        for file_path in _iter_python_files(cwd):
            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8", errors="replace"), filename=str(file_path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = file_path.relative_to(cwd)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                    hits.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == name:
                            hits.append(f"{rel}:{node.lineno}")
        return "\n".join(hits) if hits else f"no definition found for {name!r}"

    @tool
    def ast_find_references(name: str) -> str:
        """Find every read/call reference to ``name`` (as a bare name or attribute) across all .py files."""
        hits: List[str] = []
        for file_path in _iter_python_files(cwd):
            try:
                tree = ast.parse(file_path.read_text(encoding="utf-8", errors="replace"), filename=str(file_path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = file_path.relative_to(cwd)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
                    hits.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.Attribute) and node.attr == name:
                    hits.append(f"{rel}:{node.lineno}")
            if len(hits) >= _MAX_SEARCH_MATCHES:
                break
        hits = hits[:_MAX_SEARCH_MATCHES]
        return "\n".join(hits) if hits else f"no references found for {name!r}"

    base_tools: List[Callable[..., Any]] = [read_file, list_dir, write_file, submit_answer]
    wiki_ast_tools: List[Callable[..., Any]] = [ast_find_definition, ast_find_references, text_search]
    return LocalTools(base_tools=base_tools, wiki_ast_tools=wiki_ast_tools)
