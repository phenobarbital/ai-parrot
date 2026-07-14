"""Code extractor — tree-sitter Python parsing for GraphIndex.

Parses Python source files and emits ``UniversalNode`` / ``UniversalEdge``
instances representing the structural and semantic content of a codebase.
Rationale nodes are extracted from docstrings and tagged comments.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

import pathspec

from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)

# Tags that mark rationale comments
_DEFAULT_TAGS: set[str] = {"NOTE", "WHY", "HACK", "TODO", "FIXME", "XXX"}
# Regex for tagged comments: # TAG: text  or  # TAG text
_TAG_RE = re.compile(r"#\s*({tags}):?\s*(.*)", re.IGNORECASE)
# Design-reference citations in comments/docstrings, e.g. "ADR-12",
# "RFC 4180", "ADR/007". Captured as first-class Rationale nodes and linked
# to the code that cites them.
_CITATION_RE = re.compile(r"\b(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)


def _make_node_id(source_uri: str, symbol: str) -> str:
    """Create a stable node ID from a source URI and symbol name.

    Args:
        source_uri: File path of the source.
        symbol: Symbol identifier (module name, class name, etc.).

    Returns:
        A hex-encoded SHA-1 prefix unique within the tenant.
    """
    raw = f"{source_uri}::{symbol}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _get_node_text(node, source_bytes: bytes) -> str:
    """Extract the text slice covered by a tree-sitter node.

    Args:
        node: A ``tree_sitter.Node`` instance.
        source_bytes: The full source bytes.

    Returns:
        The decoded text for this node.
    """
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


class CodeExtractor:
    """Extract code structure from Python source files using tree-sitter.

    Emits ``UniversalNode`` instances for modules, classes, and functions
    (``kind=NodeKind.SYMBOL``) and ``Rationale`` nodes from docstrings and
    tagged comments (``kind=NodeKind.RATIONALE``).

    Edges emitted: ``contains``, ``defines``, ``explains``.
    Import edges (``references``) are emitted for ``import`` statements.

    Args:
        tag_set: Set of comment tags to extract as Rationale nodes.
            Defaults to ``{"NOTE", "WHY", "HACK", "TODO", "FIXME", "XXX"}``.
        ignore_file: Path to a ``.graphindexignore`` file.  If provided, files
            matching the patterns will be filtered out by ``is_ignored()``.
    """

    DEFAULT_TAGS: set[str] = _DEFAULT_TAGS

    def __init__(
        self,
        tag_set: Optional[set[str]] = None,
        ignore_file: Optional[str] = None,
    ) -> None:
        self.tag_set: set[str] = tag_set if tag_set is not None else set(self.DEFAULT_TAGS)
        self._parser = self._build_parser()
        self._ignore_spec: Optional[pathspec.PathSpec] = None
        if ignore_file:
            self._load_ignore(ignore_file)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def extract(
        self, file_path: str, source: str, *, mtime: Optional[float] = None
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Parse a Python source file and return nodes and edges.

        The module node's ``domain_tags`` always includes a ``sha1`` of the
        source content.  When ``mtime`` is supplied, it is also stored so that
        persistence backends can perform incremental staleness checks without
        re-reading the file.

        Args:
            file_path: Source-relative file path, used as ``source_uri``.
            source: Raw source code text.
            mtime: Optional filesystem modification time (``os.stat().st_mtime``).
                When provided, stamped into the module node's ``domain_tags``
                under the key ``"mtime"``.  Keyword-only to preserve backward
                compatibility.

        Returns:
            Tuple of ``(nodes, edges)`` extracted from the file.
        """
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []

        source_bytes = source.encode("utf-8", errors="replace")
        sha1 = hashlib.sha1(source_bytes).hexdigest()

        try:
            tree = self._parser.parse(source_bytes)
        except Exception as exc:
            logger.warning("tree-sitter parse error for %s: %s", file_path, exc)
            error_node = UniversalNode(
                node_id=_make_node_id(file_path, "__parse_error__"),
                kind=NodeKind.SYMBOL,
                title=file_path,
                source_uri=file_path,
                domain_tags={"parse_error": True, "symbol_type": "module"},
                provenance=Provenance.AMBIGUOUS,
            )
            nodes.append(error_node)
            return nodes, edges

        root = tree.root_node

        # Check for parse errors in the tree
        has_error = root.has_error
        if has_error:
            logger.debug("Syntax errors detected in %s — continuing with degraded extraction", file_path)

        # Module node — always includes sha1; mtime only when provided
        module_id = _make_node_id(file_path, "__module__")
        module_node = UniversalNode(
            node_id=module_id,
            kind=NodeKind.SYMBOL,
            title=Path(file_path).stem,
            source_uri=file_path,
            domain_tags={
                "symbol_type": "module",
                "sha1": sha1,
                **({"mtime": mtime} if mtime is not None else {}),
                **({"parse_error": True} if has_error else {}),
            },
            provenance=Provenance.AMBIGUOUS if has_error else Provenance.EXTRACTED,
        )
        nodes.append(module_node)

        # Walk the AST
        self._walk_module(root, file_path, source_bytes, module_id, nodes, edges)

        # Extract rationale from all comment nodes in the tree
        rationale_nodes, rationale_edges = self._extract_all_rationale(
            root, file_path, source_bytes, nodes
        )
        nodes.extend(rationale_nodes)
        edges.extend(rationale_edges)

        # Extract ADR/RFC design-reference citations as first-class nodes.
        citation_nodes, citation_edges = self._extract_citations(
            root, file_path, source_bytes, nodes
        )
        nodes.extend(citation_nodes)
        edges.extend(citation_edges)

        return nodes, edges

    def is_ignored(self, file_path: str) -> bool:
        """Check if a file path matches ``.graphindexignore`` patterns.

        Args:
            file_path: Path to test.

        Returns:
            ``True`` if the file should be excluded from indexing.
        """
        if self._ignore_spec is None:
            return False
        return self._ignore_spec.match_file(file_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_parser():
        """Construct a tree-sitter Parser for Python.

        Returns:
            A configured ``tree_sitter.Parser`` instance.
        """
        from tree_sitter import Language, Parser
        import tree_sitter_python

        lang = Language(tree_sitter_python.language())
        return Parser(lang)

    def _load_ignore(self, ignore_file: str) -> None:
        """Load gitignore-style patterns from *ignore_file*.

        Args:
            ignore_file: Path to the ``.graphindexignore`` file.
        """
        try:
            text = Path(ignore_file).read_text(encoding="utf-8")
            self._ignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", text.splitlines())
        except OSError as exc:
            logger.warning("Cannot read ignore file %s: %s", ignore_file, exc)

    def _walk_module(
        self,
        root,
        file_path: str,
        source_bytes: bytes,
        module_id: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> None:
        """Walk top-level statements to extract classes, functions, imports.

        Args:
            root: The AST root node.
            file_path: Source URI for all nodes.
            source_bytes: Raw source bytes.
            module_id: The parent module's node ID.
            nodes: Accumulated node list (mutated in place).
            edges: Accumulated edge list (mutated in place).
        """
        for child in root.children:
            if child.type == "class_definition":
                self._extract_class(child, file_path, source_bytes, module_id, nodes, edges)
            elif child.type == "function_definition":
                self._extract_function(child, file_path, source_bytes, module_id, nodes, edges)
            elif child.type in ("import_statement", "import_from_statement"):
                self._extract_import(child, file_path, source_bytes, module_id, edges)
            elif child.type == "decorated_definition":
                # Unwrap decorator → look at the actual definition
                for sub in child.children:
                    if sub.type == "class_definition":
                        self._extract_class(sub, file_path, source_bytes, module_id, nodes, edges)
                    elif sub.type == "function_definition":
                        self._extract_function(sub, file_path, source_bytes, module_id, nodes, edges)

    def _extract_class(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        parent_id: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:
        """Extract a class definition and its methods.

        Args:
            node: The ``class_definition`` AST node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            parent_id: Parent node's ID (module or outer class).
            nodes: Accumulated node list.
            edges: Accumulated edge list.

        Returns:
            The ``node_id`` of the extracted class node.
        """
        name_node = node.child_by_field_name("name")
        class_name = _get_node_text(name_node, source_bytes) if name_node else "__unknown_class__"
        class_id = _make_node_id(file_path, class_name)

        # Extract class docstring for summary
        docstring = self._get_docstring(node, source_bytes)

        class_node = UniversalNode(
            node_id=class_id,
            kind=NodeKind.SYMBOL,
            title=class_name,
            source_uri=file_path,
            summary=docstring,
            parent_id=parent_id,
            domain_tags={
                "symbol_type": "class",
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
            },
        )
        nodes.append(class_node)

        # contains edge: module → class
        edges.append(UniversalEdge(source_id=parent_id, target_id=class_id, kind=EdgeKind.CONTAINS))
        # defines edge: module → class
        edges.append(UniversalEdge(source_id=parent_id, target_id=class_id, kind=EdgeKind.DEFINES))

        # Walk class body for methods
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "function_definition":
                    self._extract_function(child, file_path, source_bytes, class_id, nodes, edges)
                elif child.type == "decorated_definition":
                    for sub in child.children:
                        if sub.type == "function_definition":
                            self._extract_function(sub, file_path, source_bytes, class_id, nodes, edges)

        return class_id

    def _extract_function(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        parent_id: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:
        """Extract a function/method definition.

        Args:
            node: The ``function_definition`` AST node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            parent_id: Parent node's ID (module or class).
            nodes: Accumulated node list.
            edges: Accumulated edge list.

        Returns:
            The ``node_id`` of the extracted function node.
        """
        name_node = node.child_by_field_name("name")
        func_name = _get_node_text(name_node, source_bytes) if name_node else "__unknown_func__"

        # Disambiguate same-named functions in different classes/modules
        parent_payload = next(
            (n for n in nodes if n.node_id == parent_id), None
        )
        qualified_name = (
            f"{parent_payload.title}.{func_name}" if parent_payload else func_name
        )
        func_id = _make_node_id(file_path, qualified_name)

        docstring = self._get_docstring(node, source_bytes)

        func_node = UniversalNode(
            node_id=func_id,
            kind=NodeKind.SYMBOL,
            title=func_name,
            source_uri=file_path,
            summary=docstring,
            parent_id=parent_id,
            domain_tags={
                "symbol_type": "function",
                "qualified_name": qualified_name,
                "lineno": node.start_point[0] + 1,
                "end_lineno": node.end_point[0] + 1,
            },
        )
        nodes.append(func_node)

        edges.append(UniversalEdge(source_id=parent_id, target_id=func_id, kind=EdgeKind.CONTAINS))

        return func_id

    def _extract_import(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        module_id: str,
        edges: list[UniversalEdge],
    ) -> None:
        """Emit ``references`` edges for import statements.

        Args:
            node: An ``import_statement`` or ``import_from_statement`` node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            module_id: The importing module's node ID.
            edges: Accumulated edge list.
        """
        import_text = _get_node_text(node, source_bytes).strip()
        # Use a synthetic target ID for the imported module
        target_id = _make_node_id(file_path, f"__import__{import_text}")
        edges.append(
            UniversalEdge(
                source_id=module_id,
                target_id=target_id,
                kind=EdgeKind.REFERENCES,
            )
        )

    def _get_docstring(self, func_or_class_node, source_bytes: bytes) -> Optional[str]:
        """Extract the first docstring from a function or class body.

        Args:
            func_or_class_node: A ``function_definition`` or ``class_definition`` node.
            source_bytes: Raw source bytes.

        Returns:
            The docstring text stripped of quotes, or ``None`` if absent.
        """
        body = func_or_class_node.child_by_field_name("body")
        if not body:
            return None
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type in ("string", "concatenated_string"):
                        raw = _get_node_text(sub, source_bytes)
                        # Strip quotes from triple-quoted strings
                        for q in ('"""', "'''", '"', "'"):
                            if raw.startswith(q) and raw.endswith(q):
                                inner = raw[len(q):-len(q)]
                                return inner.strip()
        return None

    def _extract_all_rationale(
        self,
        root,
        file_path: str,
        source_bytes: bytes,
        existing_nodes: list[UniversalNode],
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract Rationale nodes from tagged comments throughout the file.

        Walks the AST to find comment nodes whose text matches the configured
        tag set.  Also emits ``Rationale`` nodes for module/class/function
        docstrings that are not already captured.

        Args:
            root: AST root node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            existing_nodes: Already-created nodes (used to find nearest parent).

        Returns:
            Tuple of ``(rationale_nodes, explains_edges)``.
        """
        rationale_nodes: list[UniversalNode] = []
        explains_edges: list[UniversalEdge] = []
        tag_pattern = re.compile(
            r"#\s*({tags}):?\s+(.+)".format(tags="|".join(self.tag_set)),
            re.IGNORECASE,
        )

        self._walk_for_comments(
            root, file_path, source_bytes, existing_nodes,
            tag_pattern, rationale_nodes, explains_edges,
        )
        return rationale_nodes, explains_edges

    def _walk_for_comments(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        existing_nodes: list[UniversalNode],
        tag_pattern: re.Pattern,
        rationale_nodes: list[UniversalNode],
        explains_edges: list[UniversalEdge],
    ) -> None:
        """Recursively walk AST to collect tagged comments.

        Args:
            node: Current AST node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            existing_nodes: Already-created nodes for parent lookup.
            tag_pattern: Compiled regex for tag matching.
            rationale_nodes: Accumulated rationale nodes (mutated).
            explains_edges: Accumulated edges (mutated).
        """
        if node.type == "comment":
            text = _get_node_text(node, source_bytes)
            match = tag_pattern.match(text)
            if match:
                tag = match.group(1).upper()
                content = match.group(2).strip()
                rat_id = _make_node_id(file_path, f"__rationale__{text[:40]}")
                rat_node = UniversalNode(
                    node_id=rat_id,
                    kind=NodeKind.RATIONALE,
                    title=f"{tag}: {content[:60]}",
                    source_uri=file_path,
                    summary=content,
                    domain_tags={"tag": tag},
                )
                rationale_nodes.append(rat_node)
                # Try to link to the nearest enclosing symbol node
                nearest = self._find_nearest_symbol(
                    node, file_path, source_bytes, existing_nodes
                )
                if nearest:
                    explains_edges.append(
                        UniversalEdge(
                            source_id=rat_id,
                            target_id=nearest,
                            kind=EdgeKind.EXPLAINS,
                        )
                    )

        for child in node.children:
            self._walk_for_comments(
                child, file_path, source_bytes, existing_nodes,
                tag_pattern, rationale_nodes, explains_edges,
            )

    def _find_nearest_symbol(
        self,
        comment_node,
        file_path: str,
        source_bytes: bytes,
        existing_nodes: list[UniversalNode],
    ) -> Optional[str]:
        """Walk up the AST to find the enclosing function or class.

        Args:
            comment_node: The comment AST node.
            file_path: Source URI.
            source_bytes: Raw source bytes (unused here, kept for interface).
            existing_nodes: Already-created symbol nodes.

        Returns:
            The ``node_id`` of the nearest enclosing symbol, or ``None``.
        """
        parent = comment_node.parent
        while parent is not None:
            if parent.type == "function_definition":
                name_node = parent.child_by_field_name("name")
                if name_node:
                    func_name = _get_node_text(name_node, source_bytes)
                    # Search existing nodes by title
                    for n in existing_nodes:
                        if n.kind == NodeKind.SYMBOL and n.title == func_name:
                            return n.node_id
            elif parent.type == "class_definition":
                name_node = parent.child_by_field_name("name")
                if name_node:
                    cls_name = _get_node_text(name_node, source_bytes)
                    for n in existing_nodes:
                        if n.kind == NodeKind.SYMBOL and n.title == cls_name:
                            return n.node_id
            parent = parent.parent
        # Fall back to the module node
        for n in existing_nodes:
            if n.kind == NodeKind.SYMBOL and n.domain_tags.get("symbol_type") == "module":
                return n.node_id
        return None

    def _extract_citations(
        self,
        root,
        file_path: str,
        source_bytes: bytes,
        existing_nodes: list[UniversalNode],
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract ADR/RFC design-reference citations as first-class nodes.

        Scans both comments (linked to the nearest enclosing symbol) and
        symbol docstrings (linked to their owning symbol) for references such
        as ``ADR-12`` or ``RFC 4180``. Identical citations within a file
        collapse into a single ``Rationale`` node (``domain_tags['tag'] ==
        "CITATION"``); each citing symbol gets a ``REFERENCES`` edge to it.

        Args:
            root: AST root node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            existing_nodes: Already-created nodes (symbols + rationale) used
                for symbol lookup and docstring scanning.

        Returns:
            Tuple of ``(citation_nodes, reference_edges)``.
        """
        citation_nodes: list[UniversalNode] = []
        citation_edges: list[UniversalEdge] = []
        seen_nodes: dict[str, str] = {}          # normalized ref -> node_id
        seen_edges: set[tuple[str, str]] = set()  # (symbol_id, normalized ref)

        def _register(raw_kind: str, number: str, link_target: Optional[str]) -> None:
            norm = f"{raw_kind.upper()}-{int(number)}"
            cid = seen_nodes.get(norm)
            if cid is None:
                cid = _make_node_id(file_path, f"__citation__{norm}")
                citation_nodes.append(
                    UniversalNode(
                        node_id=cid,
                        kind=NodeKind.RATIONALE,
                        title=norm,
                        source_uri=file_path,
                        summary=f"Design reference {norm} cited in {Path(file_path).name}",
                        domain_tags={
                            "tag": "CITATION",
                            "citation_kind": raw_kind.upper(),
                            "citation_ref": norm,
                        },
                    )
                )
                seen_nodes[norm] = cid
            if link_target and (link_target, norm) not in seen_edges:
                citation_edges.append(
                    UniversalEdge(
                        source_id=link_target,
                        target_id=cid,
                        kind=EdgeKind.REFERENCES,
                    )
                )
                seen_edges.add((link_target, norm))

        # 1) Citations inside comments — link to the nearest enclosing symbol.
        self._walk_for_citations(
            root, file_path, source_bytes, existing_nodes, _register
        )
        # 2) Citations inside docstrings captured as symbol summaries.
        for node in existing_nodes:
            if node.kind == NodeKind.SYMBOL and node.summary:
                for match in _CITATION_RE.finditer(node.summary):
                    _register(match.group(1), match.group(2), node.node_id)

        return citation_nodes, citation_edges

    def _walk_for_citations(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        existing_nodes: list[UniversalNode],
        register,
    ) -> None:
        """Recursively walk the AST, registering ADR/RFC refs in comments.

        Args:
            node: Current AST node.
            file_path: Source URI.
            source_bytes: Raw source bytes.
            existing_nodes: Already-created nodes for nearest-symbol lookup.
            register: Callback ``(kind, number, link_target)`` from
                :meth:`_extract_citations`.
        """
        if node.type == "comment":
            text = _get_node_text(node, source_bytes)
            matches = list(_CITATION_RE.finditer(text))
            if matches:
                target = self._find_nearest_symbol(
                    node, file_path, source_bytes, existing_nodes
                )
                for match in matches:
                    register(match.group(1), match.group(2), target)

        for child in node.children:
            self._walk_for_citations(
                child, file_path, source_bytes, existing_nodes, register
            )
