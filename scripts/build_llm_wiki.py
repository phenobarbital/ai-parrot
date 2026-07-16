#!/usr/bin/env python
"""Build an **LLM Wiki** around a codebase repository.

This is a standalone, reusable tool that compiles a source repository —
its Python code *and* its Markdown documentation — into an
:mod:`parrot.knowledge.wiki` knowledge base: the machine-first retrieval
plane introduced by FEAT-260 (PR #1018).

What it produces (all under ``--output``):

* ``wiki.db`` — the :class:`~parrot.knowledge.wiki.store.SQLiteWikiStore`
  retrieval plane (FTS5/BM25 + typed edges) an agent queries and
  contributes to.  This is the durable "machine plane".
* An **OKF v0.1 markdown bundle** (``index.md`` + ``summaries/``,
  ``entities/``, ``concepts/``, ``overviews/`` …) — the human-browsable
  projection produced by :func:`parrot.knowledge.wiki.export.export_okf_bundle`.
* ``graph.html`` + ``graph.json`` — an interactive, fully-offline
  knowledge-graph map produced by
  :func:`parrot.knowledge.graphindex.export_html.export_graph`
  (ECharts, community-coloured, centrality-sized).
* ``README.md`` + ``wiki_stats.json`` — an entry point and a build report.

Design — deterministic, offline, code-aware
--------------------------------------------
Pages are compiled **without an LLM** by statically analysing the code
(Python ``ast``) and parsing Markdown.  Every page is grounded in a real
source artefact, and the whole build is reproducible with no API key.
The output is nonetheless an *LLM* wiki in the FEAT-260 sense: it is
optimised for machine/agent retrieval (stable ``concept_id`` links, typed
edges, BM25 index, token-budgeted bodies) and an agent can query it and
file new pages back into the same store.

Page taxonomy (mapped onto :class:`WikiPageCategory` / OKF types):

======================  ==================  =====================
Source artefact         Wiki category       Graph ``NodeKind``
======================  ==================  =====================
Python package          ``overview``        ``document``
Python module           ``summary``         ``wiki_page``
Public class            ``entity``          ``symbol``
Public module function  ``concept``         ``symbol``
Markdown document       ``overview``        ``document``
======================  ==================  =====================

Typed edges the builder derives:

* package ``contains`` module / sub-package
* module ``defines`` class / function
* module ``references`` module  (from intra-repo ``import`` statements)
* class ``extends`` class       (resolved base classes)
* doc ``mentions`` module       (dotted paths cited in prose)

Usage
-----
Build the AI-Parrot wiki with the bundled defaults (whole ``parrot``
namespace + ``docs/``)::

    python scripts/build_llm_wiki.py --preset ai-parrot

Build a wiki for an arbitrary repo::

    python scripts/build_llm_wiki.py \\
        --repo /path/to/repo \\
        --src-root src \\
        --docs docs --docs README.md \\
        --output /path/to/repo/docs/wiki \\
        --wiki-name my-repo

Query the produced store afterwards (BM25)::

    python - <<'PY'
    import asyncio
    from parrot.knowledge.wiki.store import create_wiki_store
    async def main():
        store = create_wiki_store("docs/parrot", backend="sqlite")
        for hit in await store.search_fts("agent crew orchestration", limit=5):
            print(hit["title"], "->", hit["concept_id"])
    asyncio.run(main())
    PY
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from parrot.knowledge.graphindex.analytics import compute_analytics
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.communities import detect_communities
from parrot.knowledge.graphindex.export_html import export_graph
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.wiki.export import export_okf_bundle
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import (
    WikiPageRecord,
    create_wiki_store,
    estimate_tokens,
)

logger = logging.getLogger("build_llm_wiki")


# ===========================================================================
# Configuration
# ===========================================================================

#: Directory / path fragments never walked for source or docs.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
    ".egg-info",
    ".claude/worktrees",
    "site-packages",
)

#: rel-string → graph EdgeKind.  The store keeps the open string; the graph
#: needs the enum.  Any rel not listed maps to ``REFERENCES``.
REL_TO_EDGE_KIND: dict[str, EdgeKind] = {
    "contains": EdgeKind.CONTAINS,
    "defines": EdgeKind.DEFINES,
    "references": EdgeKind.REFERENCES,
    "extends": EdgeKind.EXTENDS,
    "mentions": EdgeKind.MENTIONS,
    "explains": EdgeKind.EXPLAINS,
}


@dataclass
class WikiBuildConfig:
    """Everything needed to compile one repository into a wiki.

    Attributes:
        repo: Repository root (all reported paths are relative to it).
        src_roots: Import roots to walk for ``*.py`` — the directories that
            would be on ``sys.path`` (dotted module names are computed
            relative to these).
        doc_paths: Files or directories (relative to ``repo``) scanned for
            ``*.md`` documentation.
        output: Destination directory for the wiki artefacts.
        wiki_name: Human-readable wiki identifier.
        excludes: Path fragments to skip.
        include_functions: Emit a page per public module-level function
            (docstringed only).
        graph_node_kinds: Which page kinds become nodes in ``graph.html``
            (subset of ``{"package", "module", "class", "function", "doc"}``).
        max_body_chars: Hard cap on any page body (keeps token budgets sane).
        backend: Wiki store backend (``"sqlite"`` or ``"memory"``).
        enrich_llm: Optional ``"provider:model"`` spec (e.g.
            ``"google:gemini-3-flash"``).  When set, each selected page's
            docstring-derived ``summary`` is rewritten into an LLM prose
            summary before the store/OKF/graph artefacts are produced.
        enrich_kinds: Page kinds whose summaries the LLM pass rewrites.
        enrich_concurrency: Max concurrent LLM calls during enrichment.
        enrich_limit: Optional cap on the number of pages enriched (handy
            for a cheap trial run before committing to the full corpus).
    """

    repo: Path
    src_roots: list[Path]
    doc_paths: list[Path]
    output: Path
    wiki_name: str = "codebase-wiki"
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    include_functions: bool = True
    graph_node_kinds: frozenset[str] = frozenset({"package", "module"})
    max_body_chars: int = 24_000
    backend: str = "sqlite"
    enrich_llm: Optional[str] = None
    enrich_kinds: frozenset[str] = frozenset(
        {"package", "module", "class", "doc"}
    )
    enrich_concurrency: int = 8
    enrich_limit: Optional[int] = None


# ===========================================================================
# Draft intermediate representation
# ===========================================================================


@dataclass
class PageDraft:
    """A page before it is written to either the store or the graph.

    Carries both the wiki fields (``concept_id`` … ``body``) and the graph
    projection fields (``node_kind`` … ``domain_tags``) so a single pass
    can feed the retrieval plane and the knowledge-graph map.
    """

    concept_id: str
    title: str
    category: str
    kind: str  # one of package/module/class/function/doc
    node_kind: NodeKind
    source_uri: str
    summary: str = ""
    body: str = ""
    source_id: Optional[str] = None
    domain_tags: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> WikiPageRecord:
        """Project into a :class:`WikiPageRecord` for the retrieval plane."""
        return WikiPageRecord(
            concept_id=self.concept_id,
            node_id=self.concept_id,
            title=self.title,
            category=self.category,
            summary=self.summary,
            body=self.body,
            source_id=self.source_id,
            token_count=estimate_tokens(self.body or self.summary),
        )

    def to_node(self) -> UniversalNode:
        """Project into a graph :class:`UniversalNode`."""
        return UniversalNode(
            node_id=self.concept_id,
            kind=self.node_kind,
            title=self.title,
            source_uri=self.source_uri,
            summary=self.summary or None,
            domain_tags={"category": self.category, **self.domain_tags},
        )


@dataclass
class EdgeDraft:
    """A typed relation between two page ``concept_id``s."""

    src: str
    dst: str
    rel: str

    def as_store_tuple(self) -> tuple[str, str, str]:
        """Return the ``(src, dst, rel)`` triple the store's edges take."""
        return (self.src, self.dst, self.rel)

    def to_edge(self) -> UniversalEdge:
        """Project into a graph :class:`UniversalEdge`."""
        return UniversalEdge(
            source_id=self.src,
            target_id=self.dst,
            kind=REL_TO_EDGE_KIND.get(self.rel, EdgeKind.REFERENCES),
        )


# ===========================================================================
# File discovery
# ===========================================================================


def _is_excluded(path: Path, excludes: Iterable[str]) -> bool:
    """True when any exclude fragment appears in the path string."""
    s = str(path)
    return any(frag in s for frag in excludes)


def discover_python_files(
    src_root: Path, excludes: Iterable[str]
) -> list[Path]:
    """Return every non-excluded ``*.py`` under ``src_root`` (sorted)."""
    return sorted(
        p
        for p in src_root.rglob("*.py")
        if p.is_file() and not _is_excluded(p, excludes)
    )


def discover_markdown_files(
    doc_paths: Iterable[Path], excludes: Iterable[str]
) -> list[Path]:
    """Return every non-excluded ``*.md`` reachable from ``doc_paths``."""
    found: set[Path] = set()
    for base in doc_paths:
        if not base.exists():
            logger.warning("doc path does not exist, skipping: %s", base)
            continue
        if base.is_file() and base.suffix.lower() == ".md":
            if not _is_excluded(base, excludes):
                found.add(base)
        elif base.is_dir():
            for p in base.rglob("*.md"):
                if p.is_file() and not _is_excluded(p, excludes):
                    found.add(p)
    return sorted(found)


def module_dotted_name(py_file: Path, src_root: Path) -> Optional[str]:
    """Compute the importable dotted name of a module.

    Args:
        py_file: Absolute path to the ``.py`` file.
        src_root: The import root it lives under.

    Returns:
        Dotted name (``__init__.py`` collapses to its package), or ``None``
        when the file is not under ``src_root``.
    """
    try:
        rel = py_file.resolve().relative_to(src_root.resolve())
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return None
    return ".".join(parts)


# ===========================================================================
# Python extraction (AST)
# ===========================================================================

_WS_RE = re.compile(r"\s+")


def _first_line(text: Optional[str]) -> str:
    """First non-empty line of a docstring, whitespace-normalised."""
    if not text:
        return ""
    for line in text.strip().splitlines():
        line = line.strip()
        if line:
            return _WS_RE.sub(" ", line)
    return ""


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a compact ``name(args) -> ret`` signature via ``ast.unparse``."""
    try:
        args = ast.unparse(node.args)
    except Exception:  # noqa: BLE001 — never fail a build on formatting
        args = "..."
    ret = ""
    if node.returns is not None:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:  # noqa: BLE001
            ret = ""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({args}){ret}"


def _base_names(cls: ast.ClassDef) -> list[str]:
    """Best-effort base-class display names for a ``ClassDef``."""
    names: list[str] = []
    for base in cls.bases:
        try:
            names.append(ast.unparse(base))
        except Exception:  # noqa: BLE001
            continue
    return names


def _iter_imports(tree: ast.Module, module_name: str) -> set[str]:
    """Collect dotted targets referenced by a module's import statements.

    Relative imports are resolved against ``module_name`` so intra-repo
    edges land on the right target.
    """
    targets: set[str] = set()
    pkg_parts = module_name.split(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative: drop `level` trailing components from the package.
                base = pkg_parts[: len(pkg_parts) - node.level]
                mod = (base + ([node.module] if node.module else []))
                prefix = ".".join(mod)
            else:
                prefix = node.module or ""
            if prefix:
                targets.add(prefix)
                for alias in node.names:
                    targets.add(f"{prefix}.{alias.name}")
    return targets


@dataclass
class _ModuleExtract:
    """Raw AST extraction for one module (pre-page-assembly)."""

    module_name: str
    docstring: str
    classes: list[dict[str, Any]]
    functions: list[dict[str, Any]]
    imports: set[str]


def extract_module(py_file: Path, module_name: str) -> Optional[_ModuleExtract]:
    """Parse one module and pull out its documented public surface.

    Returns ``None`` when the file cannot be parsed (syntax error / encoding),
    logging a warning — a single bad file never aborts the build.
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        logger.warning("skip unparseable module %s: %s", py_file, exc)
        return None

    classes: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            methods = [
                {
                    "signature": _signature(m),
                    "doc": _first_line(ast.get_docstring(m)),
                }
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not m.name.startswith("_")
            ]
            classes.append(
                {
                    "name": node.name,
                    "bases": _base_names(node),
                    "doc": ast.get_docstring(node) or "",
                    "methods": methods,
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            functions.append(
                {
                    "name": node.name,
                    "signature": _signature(node),
                    "doc": ast.get_docstring(node) or "",
                }
            )

    return _ModuleExtract(
        module_name=module_name,
        docstring=ast.get_docstring(tree) or "",
        classes=classes,
        functions=functions,
        imports=_iter_imports(tree, module_name),
    )


# ===========================================================================
# Page assembly
# ===========================================================================

MODULE_CID = "mod:{name}"
PKG_CID = "pkg:{name}"
CLASS_CID = "class:{module}.{name}"
FUNC_CID = "func:{module}.{name}"
DOC_CID = "doc:{slug}"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """Lowercase slug safe for a concept id."""
    return _SLUG_RE.sub("-", text.lower()).strip("-")


def _truncate(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars on a line boundary with a marker."""
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = limit
    return text[:cut].rstrip() + "\n\n…(truncated)…\n"


class WikiComposer:
    """Turns discovered files into :class:`PageDraft` / :class:`EdgeDraft`.

    A single instance accumulates the whole repository so cross-references
    (imports, base classes, doc mentions) can be resolved against the full
    set of known pages before edges are emitted.
    """

    def __init__(self, config: WikiBuildConfig) -> None:
        self.config = config
        self.pages: dict[str, PageDraft] = {}
        self.edges: list[EdgeDraft] = []
        # Resolution indexes, populated as modules are added.
        self._module_ids: dict[str, str] = {}  # dotted name → concept_id
        self._class_by_simple: dict[str, list[str]] = {}  # ClassName → cids
        self._packages: set[str] = set()
        self._source_ids: dict[str, str] = {}  # source_uri → source_id

    # -- registration helpers ------------------------------------------

    def _add_page(self, page: PageDraft) -> None:
        if page.concept_id in self.pages:
            return
        page.body = _truncate(page.body, self.config.max_body_chars)
        self.pages[page.concept_id] = page

    def _add_edge(self, src: str, dst: str, rel: str) -> None:
        if src == dst:
            return
        self.edges.append(EdgeDraft(src=src, dst=dst, rel=rel))

    def _rel_uri(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.config.repo.resolve()))
        except ValueError:
            return str(path)

    # -- module / package pages ----------------------------------------

    def add_module(self, extract: _ModuleExtract, py_file: Path) -> None:
        """Create the module page (+ class/function pages) and DEFINES edges."""
        name = extract.module_name
        cid = MODULE_CID.format(name=name)
        uri = self._rel_uri(py_file)
        source_id = self._source_ids.get(uri)
        self._module_ids[name] = cid

        # Register the package chain for CONTAINS edges later.
        self._ensure_packages(name)

        summary = _first_line(extract.docstring) or f"Module {name}"
        body = self._module_body(extract)
        self._add_page(
            PageDraft(
                concept_id=cid,
                title=name,
                category="summary",
                kind="module",
                node_kind=NodeKind.WIKI_PAGE,
                source_uri=uri,
                summary=summary,
                body=body,
                source_id=source_id,
                domain_tags={"module": name},
            )
        )

        # Class pages.
        for cls in extract.classes:
            self._add_class(name, cls, uri, source_id)

        # Function pages (optional, docstringed only).
        if self.config.include_functions:
            for fn in extract.functions:
                if not fn["doc"]:
                    continue
                self._add_function(name, fn, uri, source_id)

    def _ensure_packages(self, module_name: str) -> None:
        """Register every ancestor package of a module (idempotent)."""
        parts = module_name.split(".")
        for i in range(1, len(parts)):
            pkg = ".".join(parts[:i])
            self._packages.add(pkg)

    def _add_class(
        self, module: str, cls: dict[str, Any], uri: str, source_id: Optional[str]
    ) -> None:
        cid = CLASS_CID.format(module=module, name=cls["name"])
        self._class_by_simple.setdefault(cls["name"], []).append(cid)
        summary = _first_line(cls["doc"]) or f"Class {cls['name']} in {module}"
        self._add_page(
            PageDraft(
                concept_id=cid,
                title=cls["name"],
                category="entity",
                kind="class",
                node_kind=NodeKind.SYMBOL,
                source_uri=uri,
                summary=summary,
                body=self._class_body(module, cls),
                source_id=source_id,
                domain_tags={"module": module, "symbol_type": "class"},
            )
        )
        self._add_edge(MODULE_CID.format(name=module), cid, "defines")

    def _add_function(
        self, module: str, fn: dict[str, Any], uri: str, source_id: Optional[str]
    ) -> None:
        cid = FUNC_CID.format(module=module, name=fn["name"])
        summary = _first_line(fn["doc"]) or f"Function {fn['name']} in {module}"
        body = f"# {fn['name']}\n\n```python\n{fn['signature']}\n```\n\n{fn['doc']}\n"
        self._add_page(
            PageDraft(
                concept_id=cid,
                title=f"{fn['name']}()",
                category="concept",
                kind="function",
                node_kind=NodeKind.SYMBOL,
                source_uri=uri,
                summary=summary,
                body=body,
                source_id=source_id,
                domain_tags={"module": module, "symbol_type": "function"},
            )
        )
        self._add_edge(MODULE_CID.format(name=module), cid, "defines")

    # -- body renderers -------------------------------------------------

    def _module_body(self, extract: _ModuleExtract) -> str:
        lines = [f"# `{extract.module_name}`", ""]
        if extract.docstring:
            lines += [extract.docstring.strip(), ""]
        if extract.classes:
            lines += ["## Classes", ""]
            for cls in extract.classes:
                bases = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
                doc = f" — {_first_line(cls['doc'])}" if cls["doc"] else ""
                lines.append(f"- **`{cls['name']}{bases}`**{doc}")
            lines.append("")
        docfns = [f for f in extract.functions if f["doc"]] or extract.functions
        if docfns:
            lines += ["## Functions", ""]
            for fn in docfns:
                doc = f" — {_first_line(fn['doc'])}" if fn["doc"] else ""
                lines.append(f"- `{fn['signature']}`{doc}")
            lines.append("")
        return "\n".join(lines)

    def _class_body(self, module: str, cls: dict[str, Any]) -> str:
        bases = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
        lines = [
            f"# {cls['name']}",
            "",
            f"Defined in [`{module}`](../summaries/{_okf_filename(MODULE_CID.format(name=module))}).",
            "",
            f"```python\nclass {cls['name']}{bases}\n```",
            "",
        ]
        if cls["doc"]:
            lines += [cls["doc"].strip(), ""]
        if cls["methods"]:
            lines += ["## Methods", ""]
            for m in cls["methods"]:
                doc = f" — {m['doc']}" if m["doc"] else ""
                lines.append(f"- `{m['signature']}`{doc}")
            lines.append("")
        return "\n".join(lines)

    # -- cross-reference edges (resolved after all pages exist) --------

    def resolve_import_edges(self, extracts: dict[str, _ModuleExtract]) -> None:
        """Emit module→module ``references`` edges from import statements."""
        for name, extract in extracts.items():
            src_cid = self._module_ids.get(name)
            if not src_cid:
                continue
            seen: set[str] = set()
            for target in extract.imports:
                dst = self._resolve_module_target(target)
                if dst and dst != src_cid and dst not in seen:
                    self._add_edge(src_cid, dst, "references")
                    seen.add(dst)

    def _resolve_module_target(self, dotted: str) -> Optional[str]:
        """Map a dotted import target to a known module concept_id.

        Tries the exact name, then progressively shorter prefixes, so
        ``a.b.c.func`` resolves to module ``a.b.c`` (or ``a.b``).
        """
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            cid = self._module_ids.get(candidate)
            if cid:
                return cid
        return None

    def resolve_extends_edges(self, extracts: dict[str, _ModuleExtract]) -> None:
        """Emit class→class ``extends`` edges for unambiguously resolved bases."""
        for name, extract in extracts.items():
            for cls in extract.classes:
                src = CLASS_CID.format(module=name, name=cls["name"])
                for base in cls["bases"]:
                    simple = base.split(".")[-1].split("[")[0]
                    targets = self._class_by_simple.get(simple, [])
                    if len(targets) == 1 and targets[0] != src:
                        self._add_edge(src, targets[0], "extends")

    def build_package_pages(self) -> None:
        """Create one page per package and CONTAINS edges to its children."""
        all_modules = set(self._module_ids)
        for pkg in sorted(self._packages):
            cid = PKG_CID.format(name=pkg)
            children_mods = sorted(
                m for m in all_modules if _direct_child(pkg, m)
            )
            children_pkgs = sorted(
                p for p in self._packages if _direct_child(pkg, p)
            )
            body = self._package_body(pkg, children_pkgs, children_mods)
            self._add_page(
                PageDraft(
                    concept_id=cid,
                    title=pkg,
                    category="overview",
                    kind="package",
                    node_kind=NodeKind.DOCUMENT,
                    source_uri=pkg.replace(".", "/"),
                    summary=f"Package {pkg} ({len(children_mods)} modules, "
                    f"{len(children_pkgs)} sub-packages).",
                    body=body,
                    domain_tags={"package": pkg},
                )
            )
            for child in children_pkgs:
                self._add_edge(cid, PKG_CID.format(name=child), "contains")
            for child in children_mods:
                self._add_edge(cid, MODULE_CID.format(name=child), "contains")

    def _package_body(
        self, pkg: str, sub_pkgs: list[str], modules: list[str]
    ) -> str:
        lines = [f"# `{pkg}`", "", f"Python package **{pkg}**.", ""]
        if sub_pkgs:
            lines += ["## Sub-packages", ""]
            lines += [f"- `{p}`" for p in sub_pkgs]
            lines.append("")
        if modules:
            lines += ["## Modules", ""]
            lines += [f"- `{m}`" for m in modules]
            lines.append("")
        return "\n".join(lines)

    # -- markdown docs --------------------------------------------------

    def add_doc(self, md_file: Path) -> None:
        """Create an ``overview`` page from a Markdown document + mentions."""
        uri = self._rel_uri(md_file)
        try:
            text = md_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            logger.warning("skip unreadable doc %s: %s", md_file, exc)
            return
        cid = DOC_CID.format(slug=_slug(uri))
        title = _doc_title(text, md_file)
        summary = _doc_summary(text)
        source_id = self._source_ids.get(uri)
        self._add_page(
            PageDraft(
                concept_id=cid,
                title=title,
                category="overview",
                kind="doc",
                node_kind=NodeKind.DOCUMENT,
                source_uri=uri,
                summary=summary,
                body=_truncate(text, self.config.max_body_chars),
                source_id=source_id,
                domain_tags={"doc_path": uri},
            )
        )
        # Doc → module mentions: dotted paths cited in the prose.
        for target in self._mentioned_modules(text):
            self._add_edge(cid, target, "mentions")

    def _mentioned_modules(self, text: str) -> set[str]:
        """Return concept_ids of known modules explicitly named in ``text``."""
        found: set[str] = set()
        for dotted in set(_DOTTED_RE.findall(text)):
            cid = self._resolve_module_target(dotted)
            if cid:
                found.add(cid)
        return found


def _direct_child(parent: str, candidate: str) -> bool:
    """True when ``candidate`` is a direct dotted child of ``parent``."""
    return (
        candidate.startswith(parent + ".")
        and "." not in candidate[len(parent) + 1 :]
    )


_DOTTED_RE = re.compile(r"\b(?:parrot|parrot_tools|parrot_loaders|parrot_pipelines|sdd)(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\b")


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (``--- ... ---``).

    Frontmatter keys (``type: feature``) and YAML comments (``# ...``)
    otherwise masquerade as the doc's summary/title — common in SDD
    specs, proposals, and task files.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1 :])
    return text


def _doc_title(text: str, md_file: Path) -> str:
    """First ``# H1`` heading, else the humanised filename."""
    for line in _strip_frontmatter(text).splitlines():
        if line.startswith("# "):
            return _WS_RE.sub(" ", line[2:].strip())
    return md_file.stem.replace("_", " ").replace("-", " ").title()


def _doc_summary(text: str) -> str:
    """First non-heading, non-empty prose line of a doc (trimmed)."""
    for line in _strip_frontmatter(text).splitlines():
        s = line.strip()
        if s and not s.startswith(("#", ">", "-", "*", "|", "`")):
            return _WS_RE.sub(" ", s)[:280]
    return ""


# ===========================================================================
# OKF filename helper (mirror of export.py so bodies can cross-link)
# ===========================================================================


def _okf_filename(concept_id: str) -> str:
    """Reproduce the export bundle's per-page filename for a concept id."""
    from parrot.knowledge.okf.utils import flatten_concept_id_for_filename

    return f"{flatten_concept_id_for_filename(concept_id)}.md"


# ===========================================================================
# Optional LLM enrichment — rewrite page summaries as prose
# ===========================================================================

_ENRICH_SYSTEM_PROMPT = (
    "You write concise, factual summaries for a developer knowledge wiki. "
    "Given a page's source excerpt, describe what it is and does in ONE or "
    "TWO plain sentences. No preamble, no markdown, no bullet points, no code "
    "fences — return only the summary prose."
)

_KIND_LABEL = {
    "package": "Python package",
    "module": "Python module",
    "class": "Python class",
    "function": "Python function",
    "doc": "documentation page",
}


def _enrich_prompt(page: PageDraft) -> str:
    """Build the user prompt asking the model to summarise one page."""
    label = _KIND_LABEL.get(page.kind, "page")
    excerpt = page.body[:6000] if page.body else page.summary
    return (
        f"{label}: {page.title}\n\n"
        f"Source excerpt:\n\n{excerpt}\n\n"
        "Write the summary."
    )


async def enrich_summaries(
    config: WikiBuildConfig, pages: list[PageDraft]
) -> dict[str, Any]:
    """Rewrite selected page summaries into LLM prose (in place).

    Uses the AI-Parrot client factory — ``LLMFactory.create`` resolves a
    ``"provider:model"`` spec (e.g. ``"google:gemini-3-flash"`` →
    :class:`GoogleGenAIClient`) and the returned client handles all session /
    auth / retry boilerplate.  A single canary call runs first so a missing
    API key or bad model aborts immediately instead of failing thousands of
    times; the rest run concurrently under a semaphore, and any per-page
    failure keeps that page's deterministic docstring summary.

    Args:
        config: Build configuration (holds the ``enrich_*`` fields).
        pages: All page drafts; those whose ``kind`` is in
            ``config.enrich_kinds`` are candidates.

    Returns:
        A stats dict: model, targeted/enriched/failed counts.
    """
    # Deferred import: pulls in the client stack only when enrichment is used.
    from parrot.clients.factory import LLMFactory

    provider, model = LLMFactory.parse_llm_string(config.enrich_llm or "")
    if not model:
        raise ValueError(
            f"--enrich-llm needs an explicit model, e.g. '{provider}:gemini-3-flash'"
        )

    targets = [p for p in pages if p.kind in config.enrich_kinds]
    if config.enrich_limit is not None:
        targets = targets[: config.enrich_limit]
    if not targets:
        logger.warning("enrichment: no pages match enrich_kinds — skipping")
        return {"model": config.enrich_llm, "targeted": 0, "enriched": 0}

    logger.info(
        "enrichment: rewriting %d summaries via %s (concurrency=%d)",
        len(targets),
        config.enrich_llm,
        config.enrich_concurrency,
    )

    client = LLMFactory.create(config.enrich_llm, model_args={"temperature": 0.2})
    enriched = 0
    failed = 0

    async with client:

        async def _summarise(page: PageDraft) -> Optional[str]:
            response = await client.ask(
                prompt=_enrich_prompt(page),
                model=model,
                system_prompt=_ENRICH_SYSTEM_PROMPT,
                max_tokens=160,
                temperature=0.2,
            )
            text = (getattr(response, "output", None) or "").strip()
            return _WS_RE.sub(" ", text) if text else None

        # Canary — fail fast on auth/model errors before the fan-out.
        try:
            first = await _summarise(targets[0])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"enrichment canary call failed ({type(exc).__name__}: {exc}). "
                "Check the API key and model name."
            ) from exc
        if first:
            targets[0].summary = first
            enriched += 1

        sem = asyncio.Semaphore(config.enrich_concurrency)

        async def _worker(page: PageDraft) -> bool:
            async with sem:
                try:
                    summary = await _summarise(page)
                except Exception as exc:  # noqa: BLE001 — keep deterministic
                    logger.debug("enrich failed for %s: %s", page.concept_id, exc)
                    return False
            if summary:
                page.summary = summary
                return True
            return False

        results = await asyncio.gather(*(_worker(p) for p in targets[1:]))
        enriched += sum(results)
        failed = len(targets) - enriched

    logger.info("enrichment: %d rewritten, %d fell back", enriched, failed)
    return {
        "model": config.enrich_llm,
        "targeted": len(targets),
        "enriched": enriched,
        "failed": failed,
    }


# ===========================================================================
# Build orchestration
# ===========================================================================


async def build_wiki(config: WikiBuildConfig) -> dict[str, Any]:
    """Run the full deterministic build and return a stats dict."""
    t0 = time.monotonic()
    config.output.mkdir(parents=True, exist_ok=True)

    # 1. Discover.  The output dir is self-excluded: it may live under a
    # doc path (e.g. ``docs/parrot`` under ``docs/``) and is full of
    # generated ``*.md`` that must never be re-ingested as sources.
    excludes = config.excludes + (
        str(config.output),
        str(config.output.resolve()),
    )
    py_files: list[tuple[Path, str]] = []
    for root in config.src_roots:
        for py in discover_python_files(root, excludes):
            dotted = module_dotted_name(py, root)
            if dotted:
                py_files.append((py, dotted))
    md_files = discover_markdown_files(config.doc_paths, excludes)
    logger.info("discovered %d modules, %d docs", len(py_files), len(md_files))

    # 2. Register sources (best-effort — enables lint + provenance).
    composer = WikiComposer(config)
    _register_sources(composer, config, py_files, md_files)

    # 3. Extract + assemble module/class/function pages.
    extracts: dict[str, _ModuleExtract] = {}
    for py, dotted in py_files:
        ex = extract_module(py, dotted)
        if ex is None:
            continue
        extracts[dotted] = ex
        composer.add_module(ex, py)

    # 4. Packages + cross-reference edges (needs the full page set).
    composer.build_package_pages()
    composer.resolve_import_edges(extracts)
    composer.resolve_extends_edges(extracts)

    # 5. Docs (after modules so mentions resolve).
    for md in md_files:
        composer.add_doc(md)

    logger.info(
        "composed %d pages, %d edges", len(composer.pages), len(composer.edges)
    )

    # 5b. Optional LLM enrichment — rewrite summaries as prose in place, so
    # the store, OKF frontmatter, and graph tooltips all carry it.
    enrich_stats: Optional[dict[str, Any]] = None
    if config.enrich_llm:
        enrich_stats = await enrich_summaries(
            config, list(composer.pages.values())
        )

    # 6. Populate the retrieval plane.
    store = create_wiki_store(
        config.output, wiki_name=config.wiki_name, backend=config.backend
    )
    records = [p.to_record() for p in composer.pages.values()]
    n_pages = await store.upsert_pages(records)
    valid_ids = set(composer.pages)
    edge_tuples = [
        e.as_store_tuple()
        for e in composer.edges
        if e.src in valid_ids and e.dst in valid_ids
    ]
    n_edges = await store.add_edges(edge_tuples)
    logger.info("wiki.db: %d pages, %d edges written", n_pages, n_edges)

    # 7. OKF markdown bundle (human-browsable projection).
    okf_report = await export_okf_bundle(
        store, config.output, wiki_name=config.wiki_name
    )
    logger.info("OKF bundle: %d files", okf_report.files_written)

    # 8. Interactive knowledge-graph map.
    graph_stats = _export_graph_map(composer, config)

    # 9. README + stats.
    store_stats = await store.stats()
    stats = {
        "wiki_name": config.wiki_name,
        "generated_at": _now_iso(),
        "repo": str(config.repo),
        "modules": len(extracts),
        "docs": len(md_files),
        "pages": len(composer.pages),
        "pages_by_category": _count_by(composer.pages.values(), "category"),
        "edges": len(edge_tuples),
        "edges_by_rel": _count_edges(composer.edges, valid_ids),
        "store": store_stats,
        "okf_files": okf_report.files_written,
        "graph": graph_stats,
        "enrichment": enrich_stats,
        "duration_ms": round((time.monotonic() - t0) * 1000, 1),
    }
    _write_readme(config, stats)
    (config.output / "wiki_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("build complete in %.1f ms", stats["duration_ms"])
    return stats


def _register_sources(
    composer: WikiComposer,
    config: WikiBuildConfig,
    py_files: list[tuple[Path, str]],
    md_files: list[Path],
) -> None:
    """Register every source file in the manifest (best-effort)."""
    if config.backend != "sqlite":
        return  # json manifest path kept simple; skip for memory backend
    try:
        mgr = SourceCollectionManager(
            config.output / "sources", db_path=config.output / "wiki.db"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("source manifest unavailable: %s", exc)
        return
    for path in [p for p, _ in py_files] + list(md_files):
        try:
            entry = mgr.add_source(path.resolve())
            composer._source_ids[composer._rel_uri(path)] = entry.source_id
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not register source %s: %s", path, exc)


def _export_graph_map(
    composer: WikiComposer, config: WikiBuildConfig
) -> dict[str, Any]:
    """Assemble the selected page subset into a graph and export HTML/JSON."""
    kinds = config.graph_node_kinds
    node_ids = {
        p.concept_id for p in composer.pages.values() if p.kind in kinds
    }
    nodes = [
        p.to_node() for p in composer.pages.values() if p.concept_id in node_ids
    ]
    edges = [
        e.to_edge()
        for e in composer.edges
        if e.src in node_ids and e.dst in node_ids
    ]
    if not nodes:
        logger.warning("no graph nodes selected — skipping graph export")
        return {"nodes": 0, "edges": 0, "exported": False}

    assembler = GraphAssembler(tenant_id=config.wiki_name)
    for n in nodes:
        assembler.add_node(n)
    for e in edges:
        assembler.add_edge(e)

    communities = None
    analytics = None
    try:
        communities = detect_communities(
            graph=assembler.graph, nodes=nodes, write_back_to_nodes=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("community detection skipped: %s", exc)
    try:
        analytics = compute_analytics(assembler.graph, nodes, edges)
    except Exception as exc:  # noqa: BLE001
        logger.warning("analytics skipped: %s", exc)

    try:
        html_path, json_path = export_graph(
            assembler.graph,
            config.output,
            communities=communities,
            analytics=analytics,
            title=f"{config.wiki_name} — Knowledge Map",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("graph export failed: %s", exc)
        return {"nodes": len(nodes), "edges": len(edges), "exported": False}

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "exported": True,
        "html": str(html_path.relative_to(config.output)),
        "json": str(json_path.relative_to(config.output)),
        "communities": (
            len(communities.communities) if communities else 0
        ),
        "modularity": (
            round(communities.modularity, 4) if communities else None
        ),
    }


# ===========================================================================
# Reporting helpers
# ===========================================================================


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _count_by(pages: Iterable[PageDraft], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in pages:
        key = getattr(p, attr)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _count_edges(edges: list[EdgeDraft], valid: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in edges:
        if e.src in valid and e.dst in valid:
            counts[e.rel] = counts.get(e.rel, 0) + 1
    return dict(sorted(counts.items()))


def _write_readme(config: WikiBuildConfig, stats: dict[str, Any]) -> None:
    """Write a human entry-point README for the generated wiki."""
    cats = stats["pages_by_category"]
    rels = stats["edges_by_rel"]
    graph = stats["graph"]
    lines = [
        f"# {config.wiki_name} — LLM Wiki",
        "",
        "> Machine-first knowledge base compiled from this repository's code "
        "and documentation by "
        "[`scripts/build_llm_wiki.py`](../../scripts/build_llm_wiki.py), using "
        "the AI-Parrot `parrot.knowledge.wiki` retrieval plane (FEAT-260).",
        "",
        "## What's here",
        "",
        "| Artefact | Purpose |",
        "| --- | --- |",
        "| `wiki.db` | SQLite retrieval plane (FTS5/BM25 + typed edges) — the "
        "machine plane an agent queries and contributes to. |",
        "| `index.md` + category folders | OKF v0.1 markdown bundle — the "
        "human-browsable projection of every page. |",
        "| `graph.html` | Interactive, offline knowledge-graph map (open in a "
        "browser). |",
        "| `graph.json` | Serialized graph (nodes, edges, communities). |",
        "| `wiki_stats.json` | Full build report. |",
        "",
        "## Contents",
        "",
        f"- **{stats['pages']}** pages from **{stats['modules']}** Python "
        f"modules and **{stats['docs']}** documents",
        f"- **{stats['edges']}** typed cross-reference edges",
        "",
        "### Pages by category",
        "",
    ]
    lines += [f"- `{k}`: {v}" for k, v in cats.items()]
    lines += ["", "### Edges by relation", ""]
    lines += [f"- `{k}`: {v}" for k, v in rels.items()]
    if graph.get("exported"):
        lines += [
            "",
            "### Knowledge map",
            "",
            f"- [`graph.html`](./graph.html) — {graph['nodes']} nodes, "
            f"{graph['edges']} edges, {graph.get('communities', 0)} communities "
            f"(modularity {graph.get('modularity')})",
        ]
    lines += [
        "",
        "## Querying the wiki",
        "",
        "```python",
        "import asyncio",
        "from parrot.knowledge.wiki.store import create_wiki_store",
        "",
        "async def main():",
        f"    store = create_wiki_store({str(config.output.name)!r}, backend='sqlite')",
        "    for hit in await store.search_fts('agent crew orchestration', limit=5):",
        "        print(hit['title'], '->', hit['concept_id'])",
        "",
        "asyncio.run(main())",
        "```",
        "",
        "## Regenerating",
        "",
        "```bash",
        "source .venv/bin/activate",
        "python scripts/build_llm_wiki.py --preset ai-parrot",
        "```",
        "",
        f"_Generated {stats['generated_at']} in {stats['duration_ms']} ms._",
        "",
    ]
    (config.output / "README.md").write_text("\n".join(lines), encoding="utf-8")


# ===========================================================================
# CLI
# ===========================================================================


def _ai_parrot_preset(repo: Path) -> WikiBuildConfig:
    """Default configuration that indexes the whole AI-Parrot monorepo."""
    src_roots: list[Path] = []
    packages = repo / "packages"
    if packages.is_dir():
        for pkg in sorted(packages.glob("*/src")):
            src_roots.append(pkg)
    else:  # fallback: a flat repo
        src_roots.append(repo)
    doc_paths = [
        repo / "docs",
        repo / "README.md",
        repo / "CLAUDE.md",
        repo / ".agent",
    ]
    # SDD artifacts — proposals, specs, and task files document what was
    # proposed, designed, and developed (FEAT history).  Dotted module
    # paths cited in their prose become ``mentions`` edges, linking each
    # spec to the code it describes.
    sdd_roots = [repo, *sorted(packages.glob("*"))] if packages.is_dir() else [repo]
    for sdd_root in sdd_roots:
        for sub in ("proposals", "specs", "tasks"):
            doc_paths.append(sdd_root / "sdd" / sub)
    return WikiBuildConfig(
        repo=repo,
        src_roots=src_roots,
        doc_paths=[p for p in doc_paths if p.exists()],
        output=repo / "docs" / "parrot",
        wiki_name="ai-parrot",
    )


def parse_args(argv: Optional[list[str]] = None) -> WikiBuildConfig:
    """Build a :class:`WikiBuildConfig` from command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Compile a codebase repository into an LLM Wiki.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--preset",
        choices=["ai-parrot"],
        help="Use a built-in configuration for a known repository.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Repository root (paths are reported relative to it).",
    )
    parser.add_argument(
        "--src-root",
        action="append",
        default=[],
        type=Path,
        help="Import root to walk for *.py (repeatable). Relative to --repo.",
    )
    parser.add_argument(
        "--docs",
        action="append",
        default=[],
        type=Path,
        help="Markdown file or directory to index (repeatable). Relative to --repo.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination directory for the wiki (default: <repo>/docs/wiki).",
    )
    parser.add_argument("--wiki-name", default="codebase-wiki")
    parser.add_argument(
        "--no-functions",
        action="store_true",
        help="Do not emit a page per public module-level function.",
    )
    parser.add_argument(
        "--graph-kinds",
        default="package,module",
        help="Comma list of page kinds included in graph.html "
        "(package,module,class,function,doc). Default is the architecture "
        "map (package+module); add 'class' for a denser graph.",
    )
    parser.add_argument(
        "--backend",
        choices=["sqlite", "memory"],
        default="sqlite",
        help="Wiki store backend.",
    )
    parser.add_argument(
        "--enrich-llm",
        metavar="PROVIDER:MODEL",
        help="Rewrite page summaries into LLM prose via the parrot client "
        "factory, e.g. 'google:gemini-3-flash'. Needs the provider's API key.",
    )
    parser.add_argument(
        "--enrich-kinds",
        default="package,module,class,doc",
        help="Comma list of page kinds whose summaries the LLM pass rewrites.",
    )
    parser.add_argument(
        "--enrich-concurrency",
        type=int,
        default=8,
        help="Max concurrent LLM calls during enrichment.",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=None,
        help="Cap pages enriched (cheap trial run before the full corpus).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug logging."
    )
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    # Importing `parrot` configures the root logger at DEBUG, which makes the
    # basicConfig above a no-op — force the level so a non-verbose build stays
    # quiet, and silence aiosqlite's per-statement DEBUG chatter outright.
    logging.getLogger().setLevel(level)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    repo = args.repo.resolve()

    if args.preset == "ai-parrot":
        config = _ai_parrot_preset(repo)
    else:
        if not args.src_root:
            parser.error("--src-root is required unless --preset is given")
        config = WikiBuildConfig(
            repo=repo,
            src_roots=[(repo / r).resolve() for r in args.src_root],
            doc_paths=[(repo / d).resolve() for d in args.docs],
            output=(args.output or repo / "docs" / "wiki").resolve(),
            wiki_name=args.wiki_name,
        )

    # Apply overrides that make sense on top of a preset too.
    if args.output:
        config.output = args.output.resolve()
    if args.wiki_name != "codebase-wiki":
        config.wiki_name = args.wiki_name
    if args.no_functions:
        config.include_functions = False
    config.graph_node_kinds = frozenset(
        k.strip() for k in args.graph_kinds.split(",") if k.strip()
    )
    config.backend = args.backend
    if args.enrich_llm:
        config.enrich_llm = args.enrich_llm
        config.enrich_kinds = frozenset(
            k.strip() for k in args.enrich_kinds.split(",") if k.strip()
        )
        config.enrich_concurrency = args.enrich_concurrency
        config.enrich_limit = args.enrich_limit
    return config


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    config = parse_args(argv)
    logger.info(
        "building wiki %r from %d src root(s) -> %s",
        config.wiki_name,
        len(config.src_roots),
        config.output,
    )
    stats = asyncio.run(build_wiki(config))
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
