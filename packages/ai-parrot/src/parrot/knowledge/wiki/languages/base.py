"""Pluggable per-language scanner interface for the wiki repo scanner.

:mod:`parrot.knowledge.wiki.repo_scan` gives every file whose suffix is in
``DEFAULT_SUFFIXES`` a shallow ``file:`` page, but only files claimed by a
registered :class:`LanguageScanner` get a deep API outline and
cross-file ``references`` edges. Each scanner declares the suffixes it
claims, how to render a single file's outline, and how to resolve its raw
import specifiers to other repository files — all deterministic and
offline (FEAT-394).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class LanguageOutline(BaseModel):
    """Result of deep-scanning one source file.

    Attributes:
        summary: Short summary line for the page (module docstring,
            leading doc-comment, etc.), or ``""`` when none was found.
        outline: Rendered ``## API outline`` lines (classes, functions,
            docstrings) in the same style as the existing Python outline.
        imports: Raw language-native import specifiers as they appear in
            the source (e.g. dotted Python modules, PHP ``use`` targets,
            relative JS/TS specifiers) — resolved later by
            :meth:`LanguageScanner.resolve_import`.
    """

    summary: str = ""
    outline: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


class LanguageScanner(ABC):
    """One language's deep extractor for the wiki repo scanner.

    Subclasses register themselves (explicitly, in
    ``languages/__init__.py`` — no discovery magic) against the suffixes
    they claim. ``repo_scan.build_file_slice()`` consults the registry to
    render an outline instead of falling back to the shallow content-head
    page; ``repo_scan.build_import_edges()`` groups files by scanner and
    resolves each file's raw imports through
    :meth:`build_reference_index` / :meth:`resolve_import`.
    """

    #: Scanner name used in stats/reporting (e.g. ``"python"``, ``"php"``).
    name: ClassVar[str]
    #: File suffixes this scanner claims (e.g. ``frozenset({".php"})``).
    suffixes: ClassVar[frozenset[str]]

    @abstractmethod
    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Deep-scan one file's source into a summary/outline/imports.

        Must never raise: on any parse failure, return a
        :class:`LanguageOutline` with empty fields so the caller degrades
        to the shallow page.

        Args:
            source: Raw file content (already decoded to text).
            rel_path: POSIX-style path relative to the repository root.

        Returns:
            The extracted :class:`LanguageOutline`.
        """
        ...

    @abstractmethod
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build an opaque per-language index over the full repo file list.

        Called once per scan over every scanned path (not just this
        scanner's own files) so imports can resolve to targets outside
        the subset currently being scanned.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file
                in the repository.

        Returns:
            An opaque index object passed back into :meth:`resolve_import`.
        """
        ...

    @abstractmethod
    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> str | None:
        """Resolve one raw import specifier to a repository-relative path.

        Args:
            spec: A raw import specifier as returned in
                :attr:`LanguageOutline.imports`.
            from_file: POSIX-style relative path of the importing file.
            index: The opaque index built by :meth:`build_reference_index`.

        Returns:
            The target file's POSIX-relative path, or ``None`` when the
            specifier does not resolve to a file in this repository (the
            edge is then dropped rather than left dangling).
        """
        ...

    @property
    @abstractmethod
    def mode(self) -> str:
        """Active extraction mode: ``"ast" | "tree-sitter" | "heuristic"``."""
        ...
