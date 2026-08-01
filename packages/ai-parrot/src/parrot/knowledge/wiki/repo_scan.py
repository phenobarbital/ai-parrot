"""Deterministic codebase scanner for the LLM Wiki retrieval plane.

Turns a source-code repository into :class:`WikiPageRecord` rows and
typed edges for the machine-first WikiStore plane (FEAT-260) — fully
offline: no LLM, no embeddings, no *required* external parsers.

Page model produced per repository:

- one ``file:<relpath>`` page per scanned source file — title, an
  extracted summary (module docstring / first heading / first line),
  an API outline for files claimed by a registered
  :class:`~parrot.knowledge.wiki.languages.base.LanguageScanner`
  (classes, functions, docstrings — Python via :mod:`ast`; other
  languages via tree-sitter or a stdlib heuristic, FEAT-394), and the
  file content head for lexical (FTS5) search;
- one ``dir:<relpath>`` overview page per directory, whose body lists
  the children with their summaries;
- ``contains`` edges directory → child, and ``references`` edges
  between file pages derived from their import statements, resolved
  per-language via the scanner registry
  (:mod:`parrot.knowledge.wiki.languages`).

Used by the ``wikitoolkit build`` / ``parrot wiki build`` CLI
(:mod:`parrot.knowledge.wiki.cli`) and by the git ``post-commit``
auto-upsert installed by ``parrot claude install``.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.languages import (
    all_scanners,
    scanned_suffixes,
    scanner_for,
    set_scan_root,
)
from parrot.knowledge.wiki.languages.python import PythonScanner
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens

logger = logging.getLogger(__name__)

#: Singleton used by the :func:`_python_outline`/:func:`_module_index`
#: thin wrappers kept for parity with pre-FEAT-394 callers/tests.
_PYTHON_SCANNER = PythonScanner()

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

#: File suffixes treated as source code (category ``module``).
#:
#: ``.svelte`` is claimed by the JS/TS scanner (FEAT-396), which analyses
#: the component's ``<script>`` block — not its markup.
CODE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".pyx", ".pxd", ".pyi",
    ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".svelte",
    ".php",
    ".sql", ".sh", ".bash",
})

#: File suffixes treated as documentation (category ``document``).
DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt", ".html", ".htm"})

#: HTML suffixes get a ``<title>``-aware shallow summary instead of the
#: markdown/rst summary helper (FEAT-394) — never a deep outline/edges.
_HTML_SUFFIXES: frozenset[str] = frozenset({".html", ".htm"})

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

#: Build-report basename written at the root of every exported wiki
#: bundle — the marker that identifies a directory as *being* a wiki.
WIKI_BUNDLE_MARKER = "wiki_stats.json"

#: Skip files larger than this many bytes (default 512 KiB).
DEFAULT_MAX_FILE_BYTES = 512 * 1024

#: Cap stored page bodies at this many characters (~4k tokens).
DEFAULT_BODY_MAX_CHARS = 16_000

_SUMMARY_MAX_CHARS = 240

#: Opens and closes a YAML frontmatter block.
_FRONTMATTER_DELIMITER = "---"

#: Frontmatter keys consulted for a document summary, in priority order.
_FRONTMATTER_SUMMARY_KEYS = ("summary", "title")

#: A top-level YAML mapping key, used to tell a frontmatter block from a
#: document that merely opens with a horizontal rule.
_YAML_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:")

#: Scalar values that carry no summary: YAML block-scalar indicators
#: (the text lives on following lines) and the delimiter itself.
_EMPTY_YAML_SCALARS = frozenset({"|", "|-", "|+", ">", ">-", ">+", "---"})


def _frontmatter_lead(block: list[str]) -> str:
    """Best summary carried by a YAML frontmatter block, if any.

    Deliberately not a YAML parse: only top-level ``key: value`` scalars
    are read, which is all a summary needs and keeps this dependency-free
    on the hot ingest path.

    Args:
        block: Lines between the frontmatter delimiters.

    Returns:
        The first usable value among :data:`_FRONTMATTER_SUMMARY_KEYS`,
        or ``""`` when the block carries none.
    """
    for key in _FRONTMATTER_SUMMARY_KEYS:
        prefix = f"{key}:"
        for line in block:
            if not line.startswith(prefix):  # top-level keys only
                continue
            value = line[len(prefix):].strip().strip("\"'").strip()
            if value and value not in _EMPTY_YAML_SCALARS:
                return value
            break  # key present but unusable — try the next one
    return ""


# --------------------------------------------------------------------------
# Result containers
# --------------------------------------------------------------------------


class FileSlice(BaseModel):
    """Everything scanned from a single source file.

    Attributes:
        rel_path: POSIX-style path relative to the repository root.
        record: The wiki page record for the file (``source_id`` is
            filled in later by the build pipeline).
        imports: Raw, language-native import specifiers extracted by the
            file's :class:`~parrot.knowledge.wiki.languages.base.LanguageScanner`
            (dotted Python modules today; other languages' native import
            syntax once their plugin lands), used to derive cross-file
            ``references`` edges.
        language: Name of the :class:`LanguageScanner` that produced this
            slice's outline/imports (e.g. ``"python"``), or ``None`` when
            no scanner claims the file's suffix (shallow page only).
    """

    rel_path: str
    record: WikiPageRecord
    imports: list[str] = Field(default_factory=list)
    language: str | None = None


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
    suffixes: Iterable[str] | None = None,
    exclude_dirs: Iterable[str] | None = None,
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


def find_wiki_bundle_dirs(
    root: Path,
    exclude_dirs: Iterable[str] | None = None,
) -> list[str]:
    """Locate exported wiki bundles nested inside ``root``.

    A wiki must never ingest another wiki's export: those pages mirror
    the repository's own files, so indexing them fills every result set
    with near-duplicates of their own sources and buries the originals.
    Bundles are recognised by the :data:`WIKI_BUNDLE_MARKER` build
    report that ``build`` writes at the root of each export.

    The build already excludes the export directory it is *currently*
    configured to write; this finds the ones it is not — a bundle left
    behind by an earlier configuration, or one vendored in from another
    project.

    A marker at ``root`` itself is ignored: the repository being scanned
    may legitimately be a bundle, and pruning it would discover nothing.

    Args:
        root: Repository root directory.
        exclude_dirs: Directory names pruned during the walk (merged
            with :data:`DEFAULT_EXCLUDE_DIRS`); path-prefix entries
            containing ``/`` are ignored here.

    Returns:
        Sorted root-relative POSIX paths of the bundle directories.
    """
    root = root.resolve()
    pruned_names = set(DEFAULT_EXCLUDE_DIRS)
    pruned_paths: set[str] = set()
    for entry in (e.strip("/") for e in exclude_dirs or ()):
        if not entry:
            continue
        if "/" in entry:
            pruned_paths.add(entry)
        else:
            pruned_names.add(entry)

    bundles: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        if current != root and (current / WIKI_BUNDLE_MARKER).is_file():
            bundles.append(current.relative_to(root).as_posix())
            continue  # a bundle is opaque — never descend into it
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if entry.name in pruned_names:
                continue
            rel = entry.relative_to(root).as_posix()
            if any(rel == pp or rel.startswith(pp + "/") for pp in pruned_paths):
                continue
            stack.append(entry)
    return sorted(bundles)


def is_inside_wiki_bundle(root: Path, rel_path: str) -> bool:
    """Whether ``rel_path`` sits inside a nested exported wiki bundle.

    The ancestor-walk counterpart to :func:`find_wiki_bundle_dirs`, for
    the incremental path. It answers the question for one file in
    O(path depth) rather than O(repository), so the git post-commit
    hook keeps its docs-only fast path instead of scanning the whole
    tree on every commit.

    A marker at ``root`` itself is ignored, matching
    :func:`find_wiki_bundle_dirs`.

    Args:
        root: Repository root directory.
        rel_path: POSIX-style path relative to ``root``.

    Returns:
        ``True`` when any ancestor directory below ``root`` carries the
        :data:`WIKI_BUNDLE_MARKER`.
    """
    root = root.resolve()
    parts = PurePosixPath(rel_path).parts
    for depth in range(1, len(parts)):
        if (root.joinpath(*parts[:depth]) / WIKI_BUNDLE_MARKER).is_file():
            return True
    return False


def discover_repo_files(
    root: Path,
    suffixes: Iterable[str] | None = None,
    exclude_dirs: Iterable[str] | None = None,
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
    # Nested wiki bundles are pruned as path prefixes, whichever way the
    # file list was obtained — git ls-files sees them too.
    excluded = list(exclude_dirs or ())
    excluded.extend(find_wiki_bundle_dirs(root, exclude_dirs=excluded))
    pruned = DEFAULT_EXCLUDE_DIRS | frozenset(excluded)

    rel_paths: list[str] | None = None
    if use_git:
        rel_paths = _git_ls_files(root)
    if rel_paths is None:
        rel_paths = _walk_files(root, pruned)

    return sorted({
        rel
        for rel in rel_paths
        if is_wiki_relevant(rel, suffixes=suffixes, exclude_dirs=excluded)
    })


def _git_ls_files(root: Path) -> list[str] | None:
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

    .. note::
        Thin wrapper kept for parity with pre-FEAT-394 callers/tests —
        the extraction logic itself now lives in
        :class:`~parrot.knowledge.wiki.languages.python.PythonScanner`,
        consulted via the registry in :func:`build_file_slice`.

    Args:
        source: Raw Python source text.

    Returns:
        Tuple of ``(summary, outline_lines, imported_modules)``.  On a
        syntax error every element degrades to empty.
    """
    result = _PYTHON_SCANNER.outline(source, "")
    return result.summary, result.outline, result.imports


_HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _html_title_summary(content: str) -> str:
    """Summary for an HTML document: ``<title>``, else first heading.

    HTML is shallow-scan only (no outline, no import edges) — this is a
    dedicated helper rather than an extension of :func:`_markdown_summary`,
    which is frontmatter-aware and has different (YAML) semantics.

    Args:
        content: Raw HTML document text.

    Returns:
        The extracted title/heading text, truncated to
        :data:`_SUMMARY_MAX_CHARS`, or ``""`` when neither is present.
    """
    match = _HTML_TITLE_RE.search(content)
    if match:
        return match.group(1).strip()[:_SUMMARY_MAX_CHARS]
    match = _HTML_HEADING_RE.search(content)
    if match:
        text = _HTML_TAG_RE.sub("", match.group(1)).strip()
        return text[:_SUMMARY_MAX_CHARS]
    return ""


def _markdown_summary(content: str) -> str:
    """Summary for a markdown/rst document.

    Resolution order, first hit wins:

    1. the ``summary`` field of a leading YAML frontmatter block,
    2. its ``title`` field,
    3. the first heading or non-empty line of the body after the block.

    Frontmatter is metadata, not prose. Reading straight from the top
    of such a file yields its ``---`` delimiter, which is useless in a
    search result *and* gets indexed by FTS as though it were content —
    the same meaningless token repeated across every document that has
    a frontmatter block.

    Args:
        content: Raw document text.

    Returns:
        The summary line, truncated to :data:`_SUMMARY_MAX_CHARS`.
    """
    lines = content.splitlines()
    body = lines
    if lines and lines[0].strip() == _FRONTMATTER_DELIMITER:
        for idx in range(1, len(lines)):
            if lines[idx].strip() != _FRONTMATTER_DELIMITER:
                continue
            block = lines[1:idx]
            # Position is not enough: a document may simply open with a
            # horizontal rule. Without a single top-level `key:` this is
            # not metadata, and consuming it would drop the real lead.
            if not any(_YAML_KEY_RE.match(line) for line in block):
                break
            lead = _frontmatter_lead(block)
            if lead:
                return lead[:_SUMMARY_MAX_CHARS]
            body = lines[idx + 1:]
            break
        # No closing delimiter: not a frontmatter block after all. Fall
        # through and read the document, delimiter line skipped below.

    for line in body:
        stripped = line.strip().lstrip("#").strip()
        if stripped and stripped != _FRONTMATTER_DELIMITER:
            return stripped[:_SUMMARY_MAX_CHARS]
    return ""


def build_file_slice(
    root: Path,
    rel_path: str,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> FileSlice | None:
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
    language: str | None = None

    scanner = scanner_for(suffix)
    if scanner is not None:
        try:
            lang_outline = scanner.outline(content, rel_path)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.warning(
                "Scanner %s failed on %s, degrading to shallow page: %s",
                scanner.name, rel_path, exc,
            )
            summary = _first_line(content) or rel_path
        else:
            language = scanner.name
            imports = lang_outline.imports
            summary = (
                lang_outline.summary
                or f"{scanner.name.title()} module {rel_path}"
            )
            if lang_outline.outline:
                sections.append(
                    "## API outline\n" + "\n".join(lang_outline.outline)
                )
    elif suffix in _HTML_SUFFIXES:
        summary = _html_title_summary(content) or rel_path
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
    return FileSlice(
        rel_path=rel_path, record=record, imports=imports, language=language
    )


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

    .. note::
        Thin wrapper kept for parity with pre-FEAT-394 callers/tests —
        delegates to
        :meth:`~parrot.knowledge.wiki.languages.python.PythonScanner.build_reference_index`.
        Handles both flat layouts (``pkg/mod.py`` → ``pkg.mod``) and src
        layouts (``packages/x/src/pkg/mod.py`` → ``pkg.mod`` — everything
        up to and including a ``src`` component is stripped).
    """
    return _PYTHON_SCANNER.build_reference_index(rel_paths)


def build_import_edges(
    files: list[FileSlice],
    index_paths: Iterable[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Derive ``references`` edges between file pages from their imports.

    Files are grouped by :attr:`FileSlice.language`; each language's
    reference index is built once (via its scanner's
    :meth:`~parrot.knowledge.wiki.languages.base.LanguageScanner.build_reference_index`)
    over the full repository file list, then each file's raw imports are
    resolved through that same scanner's
    :meth:`~parrot.knowledge.wiki.languages.base.LanguageScanner.resolve_import`.
    Files with no language (unscanned suffixes) carry no imports and
    contribute no edges. Unresolvable specifiers are silently dropped —
    no dangling edges — and a PHP ``require`` (say) can never resolve
    into a JS/TS file's reference index since each language's index is
    built and searched independently.

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
    index_paths = list(index_paths)

    by_language: dict[str, list[FileSlice]] = {}
    for fs in files:
        if fs.language:
            by_language.setdefault(fs.language, []).append(fs)

    edges: set[tuple[str, str, str]] = set()
    scanners = all_scanners()
    for language, lang_files in by_language.items():
        scanner = scanners.get(language)
        if scanner is None:
            continue
        ref_index = scanner.build_reference_index(index_paths)
        for fs in lang_files:
            src = file_concept_id(fs.rel_path)
            for spec in fs.imports:
                target = scanner.resolve_import(spec, fs.rel_path, ref_index)
                if target and target != fs.rel_path:
                    edges.add((src, file_concept_id(target), "references"))
    return sorted(edges)


# --------------------------------------------------------------------------
# Top-level scan
# --------------------------------------------------------------------------


def scan_repository(
    root: Path,
    suffixes: Iterable[str] | None = None,
    exclude_dirs: Iterable[str] | None = None,
    body_max_chars: int = DEFAULT_BODY_MAX_CHARS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    use_git: bool = True,
    rel_paths: Iterable[str] | None = None,
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
    set_scan_root(root)
    if rel_paths is None:
        discovered = discover_repo_files(
            root, suffixes=suffixes, exclude_dirs=exclude_dirs, use_git=use_git
        )
        targets = discovered
    else:
        targets = sorted({PurePosixPath(p).as_posix() for p in rel_paths})
        # The repo-wide index is only needed to resolve imports to files
        # OUTSIDE the changed set. Skip the (whole-repo) discovery scan
        # when no changed file belongs to a registered language scanner
        # and can therefore produce import edges — e.g. a docs- or
        # config-only commit — so the git post-commit hook does not pay
        # an O(repo) cost on every such commit.
        if any(PurePosixPath(t).suffix in scanned_suffixes() for t in targets):
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
