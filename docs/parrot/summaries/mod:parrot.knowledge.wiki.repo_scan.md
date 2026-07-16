---
type: Wiki Summary
title: parrot.knowledge.wiki.repo_scan
id: mod:parrot.knowledge.wiki.repo_scan
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic codebase scanner for the LLM Wiki retrieval plane.
relates_to:
- concept: class:parrot.knowledge.wiki.repo_scan.FileSlice
  rel: defines
- concept: class:parrot.knowledge.wiki.repo_scan.RepoScan
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.build_dir_pages
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.build_file_slice
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.build_import_edges
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.dir_concept_id
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.discover_repo_files
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.file_concept_id
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.is_wiki_relevant
  rel: defines
- concept: func:parrot.knowledge.wiki.repo_scan.scan_repository
  rel: defines
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.repo_scan`

Deterministic codebase scanner for the LLM Wiki retrieval plane.

Turns a source-code repository into :class:`WikiPageRecord` rows and
typed edges for the machine-first WikiStore plane (FEAT-260) — fully
offline: no LLM, no embeddings, no external parsers.

Page model produced per repository:

- one ``file:<relpath>`` page per scanned source file — title, an
  extracted summary (module docstring / first heading / first line),
  an API outline for Python files (classes, functions, docstrings via
  :mod:`ast`), and the file content head for lexical (FTS5) search;
- one ``dir:<relpath>`` overview page per directory, whose body lists
  the children with their summaries;
- ``contains`` edges directory → child, and ``references`` edges
  between Python file pages derived from their import statements.

Used by the ``wikitoolkit build`` / ``parrot wiki build`` CLI
(:mod:`parrot.knowledge.wiki.cli`) and by the git ``post-commit``
auto-upsert installed by ``parrot claude install``.

## Classes

- **`FileSlice(BaseModel)`** — Everything scanned from a single source file.
- **`RepoScan(BaseModel)`** — Full result of scanning a repository.

## Functions

- `def is_wiki_relevant(rel_path: str, suffixes: Optional[Iterable[str]]=None, exclude_dirs: Optional[Iterable[str]]=None) -> bool` — Whether a repository-relative path is in wiki scope.
- `def file_concept_id(rel_path: str) -> str` — Return the stable concept id for a file page.
- `def dir_concept_id(rel_path: str) -> str` — Return the stable concept id for a directory overview page.
- `def discover_repo_files(root: Path, suffixes: Optional[Iterable[str]]=None, exclude_dirs: Optional[Iterable[str]]=None, use_git: bool=True) -> list[str]` — Enumerate candidate source files under ``root``.
- `def build_file_slice(root: Path, rel_path: str, body_max_chars: int=DEFAULT_BODY_MAX_CHARS, max_file_bytes: int=DEFAULT_MAX_FILE_BYTES) -> Optional[FileSlice]` — Build the wiki page record for a single repository file.
- `def build_dir_pages(files: list[FileSlice]) -> tuple[list[WikiPageRecord], list[tuple[str, str, str]]]` — Derive directory overview pages and ``contains`` edges.
- `def build_import_edges(files: list[FileSlice], index_paths: Optional[Iterable[str]]=None) -> list[tuple[str, str, str]]` — Derive ``references`` edges between file pages from Python imports.
- `def scan_repository(root: Path, suffixes: Optional[Iterable[str]]=None, exclude_dirs: Optional[Iterable[str]]=None, body_max_chars: int=DEFAULT_BODY_MAX_CHARS, max_file_bytes: int=DEFAULT_MAX_FILE_BYTES, use_git: bool=True, rel_paths: Optional[Iterable[str]]=None) -> RepoScan` — Scan a repository into wiki page records and edges.
