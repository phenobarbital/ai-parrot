"""Deterministic codebase scanner for the LLM Wiki retrieval plane.

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
"""

from __future__ import annotations

import ast
import logging
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

#: File suffixes treated as source code (category ``module``).
CODE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".pyx", ".pxd", ".pyi",
    ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
    ".js", ".jsx", ".ts", ".tsx", ".mjs",
    ".sql", ".sh", ".bash",
})

#: File suffixes treated as documentation (category ``document``).
DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt"})

#: File suffixes treated as configuration (category ``config``).
CONFIG_SUFFIXES: frozenset[str] = frozenset({
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".json",
})

DEFAULT_SUFFIXES: frozenset[str] = CODE_SUFFIXES | DOC_SUFFIXES | CONFIG_SUFFIXES

#: Directory names never descended into.
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", "__pycache__",
    ".venv", "venv", "node_modules", ".tox", "build", "dist", ".eggs",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".parrot", ".claude", ".worktrees", ".graphindex",
})

#: File basenames always skipped (lockfiles and similar noise).
DEFAULT_EXCLUDE_NAMES: frozenset[str] = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "uv.lock", "poetry.lock", "Cargo.lock",
})

#: Skip files larger than this many bytes (default 512 KiB).
DEFAULT_MAX_FILE_BYTES = 512 * 1024

#: Cap stored page bodies at this many characters (~4k tokens).
DEFAULT_BODY_MAX_CHARS = 16_000

_SUMMARY_MAX_CHARS = 240


# --------------------------------------------------------------------------
# Result containers
# --------------------------------------------------------------------------


class FileSlice(BaseModel):
    """Everything scanned from a single source file.

    Attributes:
        rel_path: POSIX-style path relative to the repository root.
        record: The wiki page record for the file (``source_id`` is
            filled in later by the build pipeline).
        imports: Dotted module names imported by the file (Python only),
            used to derive cross-file ``references`` edges.
    """

    rel_path: str
    record: WikiPageRecord
    imports: list[str] = Field(default_factory=list)


class RepoScan(BaseModel):
    """Full result of scanning a repository.

    Attributes:
        root: Absolute repository root that was scanned.
        files: One :class:`FileSlice` per scanned file, sorted by path.
        dir_records: Directory overview pages (``dir:`` concept ids).
        dir_edges: ``contains`` edges (dir → child dir/file pages).
        import_edges: ``references`` edges between ``file:`` pages.
        skipped: Relative paths skipped (too large / binary / unreadable).
    """

    root: Path
    files: list[FileSlice] = Field(default_factory=list)
    dir_records: list[WikiPageRecord] = Field(default_factory=list)
    dir_edges: list[tuple[str, str, str]] = Field(default_factory=list)
    import_edges: list[tuple[str, str, str]] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def is_wiki_relevant(
    rel_path: str,
    suffixes: Optional[Iterable[str]] = None,
    exclude_dirs: Optional[Iterable[str]] = None,
) -> bool:
    """Whether a repository-relative path is in wiki scope.

    Single source of truth for the selection filter, shared by full
    discovery (:func:`discover_repo_files`) and incremental upserts so
    the two paths can never disagree about what belongs in the wiki.

    Args:
        rel_path: POSIX-style path relative to the repository root.
        suffixes: File suffixes to keep (defaults to
            :data:`DEFAULT_SUFFIXES`).
        exclude_dirs: Extra exclusions (merged with
            :data:`DEFAULT_EXCLUDE_DIRS`): a bare name (``"vendor"``)
            prunes any directory of that name; an entry containing
            ``/`` (``"docs/wiki"``) prunes that root-relative path
            prefix only.

    Returns:
        ``True`` when the file should be scanned into the wiki.
    """
    keep = frozenset(suffixes) if suffixes else DEFAULT_SUFFIXES
    pruned_names = set(DEFAULT_EXCLUDE_DIRS)
    pruned_paths: set[str] = set()
    for entry in exclude_dirs or ():
        entry = entry.strip("/")
        if "/" in entry:
            pruned_paths.add(entry)
        elif entry:
            pruned_names.add(entry)

    p = PurePosixPath(rel_path)
    if not p.parts:
        return False
    if any(part in pruned_names for part in p.parts):
        return False
    rel = p.as_posix()
    if any(rel == pp or rel.startswith(pp + "/") for pp in pruned_paths):
        return False
    if p.parts[-1] in DEFAULT_EXCLUDE_NAMES:
        return False
    return p.suffix.lower() in keep


def file_concept_id(rel_path: str) -> str:
    """Return the stable concept id for a file page."""
    return f"file:{PurePosixPath(rel_path)}"


def dir_concept_id(rel_path: str) -> str:
    """Return the stable concept id for a directory overview page."""
    return f"dir:{PurePosixPath(rel_path) if rel_path else '.'}"


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def discover_repo_files(
    root: Path,
    suffixes: Optional[Iterable[str]] = None,
    exclude_dirs: Optional[Iterable[str]] = None,
    use_git: bool = True,
) -> list[str]:
    """Enumerate candidate source files under ``root``.

    Prefers ``git ls-files`` (tracked + untracked-but-not-ignored, so
    ``.gitignore`` is respected) and falls back to a filesystem walk
    with :data:`DEFAULT_EXCLUDE_DIRS` pruning when ``root`` is not a
    git repository.

    Args:
        root: Repository root directory.
        suffixes: File suffixes to keep (defaults to
            :data:`DEFAULT_SUFFIXES`).
        exclude_dirs: Directory names to prune (merged with defaults).
        use_git: Set ``False`` to force the filesystem walk.

    Returns:
        Sorted list of POSIX-style relative paths.
    """
    root = root.resolve()
    pruned = DEFAULT_EXCLUDE_DIRS | frozenset(exclude_dirs or ())

    rel_paths: Optional[list[str]] = None
    if use_git:
        rel_paths = _git_ls_files(root)
    if rel_paths is None:
        rel_paths = _walk_files(root, pruned)

    return sorted({
        rel
        for rel in rel_paths
        if is_wiki_relevant(rel, suffixes=suffixes, exclude_dirs=exclude_dirs)
    })


def _git_ls_files(root: Path) -> Optional[list[str]]:
    """List files via git (respecting .gitignore), or None if unavailable."""
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(root), "ls-files", "-z",
                "--cached", "--others", "--exclude-standard",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.decode("utf-8", errors="replace")
    return [p for p in out.split("\0") if p]


def _walk_files(root: Path, pruned: frozenset[str]) -> list[str]:
    """Filesystem fallback for :func:`discover_repo_files`."""
    found: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in pruned and not entry.is_symlink():
                    stack.append(entry)
            elif entry.is_file():
                found.append(entry.relative_to(root).as_posix())
    return found


# --------------------------------------------------------------------------
# Per-file extraction
# --------------------------------------------------------------------------


def _first_line(text: str, limit: int = _SUMMARY_MAX_CHARS) -> str:
    """Return the first non-empty line of ``text``, truncated."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return ""


def _category_for(rel_path: str) -> str:
    """Map a file suffix to an open-string wiki category."""
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix in DOC_SUFFIXES:
        return "document"
    if suffix in CONFIG_SUFFIXES:
        return "config"
    return "module"


def _python_outline(source: str) -> tuple[str, list[str], list[str]]:
    """Extract summary, API outline, and imports from Python source.

    Args:
        source: Raw Python source text.

    Returns:
        Tuple of ``(summary, outline_lines, imported_modules)``.  On a
        syntax error every element degrades to empty.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return "", [], []

    summary = _first_line(ast.get_docstring(tree) or "")
    outline: list[str] = []
    imports: list[str] = []

    def _sig(node: ast.AST) -> str:
        args = getattr(node, "args", None)
        names = [a.arg for a in args.args] if args else []
        return f"({', '.join(names)})"

    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.append(node.module)
        elif isinstance(node, ast.ClassDef):
            doc = _first_line(ast.get_docstring(node) or "")
            outline.append(f"class {node.name}: {doc}".rstrip(": "))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    idoc = _first_line(ast.get_docstring(item) or "")
                    outline.append(
                        f"    def {item.name}{_sig(item)}: {idoc}".rstrip(": ")
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = _first_line(ast.get_docstring(node) or "")
            outline.append(f"def {node.name}{_sig(node)}: {doc}".rstrip(": "))
    return summary, outline, imports


def _markdown_summary(content: str) -> str:
    """Summary for a markdown/rst document: first heading or first line."""
    for line in content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:_SUMMARY_MAX_CHARS]
    return ""


def build_file_slice(
    root: Path,
    rel_path: str,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> Optional[FileSlice]:
    """Build the wiki page record for a single repository file.

    Args:
        root: Repository root.
        rel_path: POSIX relative path of the file.
        body_max_chars: Cap on the stored page body length.
        max_file_bytes: Files larger than this are skipped.

    Returns:
        A :class:`FileSlice`, or ``None`` when the file is missing,
        binary, or oversized.
    """
    path = root / rel_path
    try:
        if path.stat().st_size > max_file_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:1024]:
        return None
    content = data.decode("utf-8", errors="replace")

    category = _category_for(rel_path)
    suffix = PurePosixPath(rel_path).suffix.lower()
    imports: list[str] = []
    sections: list[str] = []

    if suffix in {".py", ".pyi"}:
        summary, outline, imports = _python_outline(content)
        summary = summary or f"Python module {rel_path}"
        if outline:
            sections.append("## API outline\n" + "\n".join(outline))
    elif suffix in DOC_SUFFIXES:
        summary = _markdown_summary(content) or rel_path
    else:
        summary = _first_line(content) or rel_path

    body_head = content[:body_max_chars]
    truncated = len(content) > body_max_chars
    sections.append(
        "## Content" + (" (truncated)" if truncated else "") + "\n" + body_head
    )
    body = f"# {rel_path}\n\n" + "\n\n".join(sections)

    record = WikiPageRecord(
        concept_id=file_concept_id(rel_path),
        node_id=rel_path,
        title=rel_path,
        category=category,
        summary=summary,
        body=body,
        token_count=estimate_tokens(body),
    )
    return FileSlice(rel_path=rel_path, record=record, imports=imports)


# --------------------------------------------------------------------------
# Directory pages + import edges
# --------------------------------------------------------------------------


def build_dir_pages(
    files: list[FileSlice],
) -> tuple[list[WikiPageRecord], list[tuple[str, str, str]]]:
    """Derive directory overview pages and ``contains`` edges.

    Args:
        files: Scanned file slices.

    Returns:
        Tuple ``(dir_records, edges)``; edges connect each directory
        page to its child directory/file pages.
    """
    children: dict[str, set[tuple[str, str]]] = {}  # dir -> {(kind, rel)}
    summaries: dict[str, str] = {
        fs.rel_path: fs.record.summary for fs in files
    }

    for fs in files:
        p = PurePosixPath(fs.rel_path)
        parent = p.parent.as_posix()
        parent = "" if parent == "." else parent
        children.setdefault(parent, set()).add(("file", fs.rel_path))
        # Register ancestor chain dir -> subdir
        current = parent
        while current:
            up = PurePosixPath(current).parent.as_posix()
            up = "" if up == "." else up
            children.setdefault(up, set()).add(("dir", current))
            current = up

    records: list[WikiPageRecord] = []
    edges: list[tuple[str, str, str]] = []
    for dir_rel, kids in sorted(children.items()):
        cid = dir_concept_id(dir_rel)
        lines: list[str] = []
        for kind, rel in sorted(kids):
            child_cid = (
                file_concept_id(rel) if kind == "file" else dir_concept_id(rel)
            )
            edges.append((cid, child_cid, "contains"))
            label = summaries.get(rel, "") if kind == "file" else "directory"
            lines.append(f"- [{child_cid}] {PurePosixPath(rel).name} — {label}")
        title = dir_rel or "."
        body = f"# Directory {title}\n\n" + "\n".join(lines)
        records.append(
            WikiPageRecord(
                concept_id=cid,
                node_id=f"dir/{title}",
                title=f"{title}/",
                category="overview",
                summary=f"Directory overview of {title} "
                        f"({len(kids)} entries)",
                body=body,
                token_count=estimate_tokens(body),
            )
        )
    return records, edges


def _module_index(rel_paths: Iterable[str]) -> dict[str, str]:
    """Map importable dotted module names to relative file paths.

    Handles both flat layouts (``pkg/mod.py`` → ``pkg.mod``) and src
    layouts (``packages/x/src/pkg/mod.py`` → ``pkg.mod`` — everything
    up to and including a ``src`` component is stripped).
    """
    index: dict[str, str] = {}
    for rel in rel_paths:
        p = PurePosixPath(rel)
        if p.suffix not in {".py", ".pyi"}:
            continue
        parts = list(p.parts)
        if "src" in parts:
            parts = parts[parts.index("src") + 1:]
        if not parts:
            continue
        parts[-1] = PurePosixPath(parts[-1]).stem
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            index.setdefault(".".join(parts), rel)
    return index


def build_import_edges(
    files: list[FileSlice],
    index_paths: Optional[Iterable[str]] = None,
) -> list[tuple[str, str, str]]:
    """Derive ``references`` edges between file pages from Python imports.

    An import edge is emitted when an imported dotted module (or any
    dotted prefix of it) resolves to another repository file.

    Args:
        files: Scanned file slices (edge sources).
        index_paths: Relative paths used to build the import-target
            index; defaults to the scanned files themselves.  Pass the
            full repository file list on partial scans so imports still
            resolve to files outside the scanned subset.

    Returns:
        Deduplicated ``(src_concept, dst_concept, "references")`` edges.
    """
    if index_paths is None:
        index_paths = [fs.rel_path for fs in files]
    index = _module_index(index_paths)
    edges: set[tuple[str, str, str]] = set()
    for fs in files:
        src = file_concept_id(fs.rel_path)
        for module in fs.imports:
            parts = module.split(".")
            target: Optional[str] = None
            for depth in range(len(parts), 0, -1):
                target = index.get(".".join(parts[:depth]))
                if target:
                    break
            if target and target != fs.rel_path:
                edges.add((src, file_concept_id(target), "references"))
    return sorted(edges)


# --------------------------------------------------------------------------
# Top-level scan
# --------------------------------------------------------------------------


def scan_repository(
    root: Path,
    suffixes: Optional[Iterable[str]] = None,
    exclude_dirs: Optional[Iterable[str]] = None,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    use_git: bool = True,
    rel_paths: Optional[Iterable[str]] = None,
) -> RepoScan:
    """Scan a repository into wiki page records and edges.

    Args:
        root: Repository root directory.
        suffixes: File suffixes to include (defaults to
            :data:`DEFAULT_SUFFIXES`).
        exclude_dirs: Extra directory names to prune.
        body_max_chars: Cap on stored page body length.
        max_file_bytes: Skip files larger than this.
        use_git: Prefer ``git ls-files`` for discovery.
        rel_paths: Explicit relative paths to scan instead of running
            discovery (used for incremental upserts).

    Returns:
        A fully populated :class:`RepoScan`.
    """
    root = root.resolve()
    if rel_paths is None:
        discovered = discover_repo_files(
            root, suffixes=suffixes, exclude_dirs=exclude_dirs, use_git=use_git
        )
        targets = discovered
    else:
        targets = sorted({PurePosixPath(p).as_posix() for p in rel_paths})
        # The repo-wide index is only needed to resolve Python imports to
        # files OUTSIDE the changed set. Skip the (whole-repo) discovery
        # scan when no changed file can produce import edges — e.g. a
        # docs- or config-only commit — so the git post-commit hook does
        # not pay an O(repo) cost on every such commit.
        if any(PurePosixPath(t).suffix in {".py", ".pyi"} for t in targets):
            discovered = discover_repo_files(
                root, suffixes=suffixes, exclude_dirs=exclude_dirs,
                use_git=use_git,
            )
        else:
            discovered = list(targets)

    scan = RepoScan(root=root)
    for rel in targets:
        fs = build_file_slice(
            root,
            rel,
            body_max_chars=body_max_chars,
            max_file_bytes=max_file_bytes,
        )
        if fs is None:
            scan.skipped.append(rel)
        else:
            scan.files.append(fs)

    scan.dir_records, scan.dir_edges = build_dir_pages(scan.files)
    scan.import_edges = build_import_edges(scan.files, index_paths=discovered)
    logger.info(
        "Scanned %s: %d pages, %d dirs, %d import edges, %d skipped",
        root,
        len(scan.files),
        len(scan.dir_records),
        len(scan.import_edges),
        len(scan.skipped),
    )
    return scan
