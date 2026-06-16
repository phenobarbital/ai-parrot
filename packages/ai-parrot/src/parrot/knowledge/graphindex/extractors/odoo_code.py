"""Odoo-aware code extractor for GraphIndex (FEAT-240).

Subclasses CodeExtractor to capture Odoo model semantics — ``_name`` /
``_inherit`` / ``_inherits``, ``fields.*`` declarations and ``@api.*``
decorators — emitting ``EXTENDS`` edges to canonical model nodes.

All Odoo specifics live in ``domain_tags``; the only schema-level addition
is ``EdgeKind.EXTENDS`` (added by TASK-1571).  Non-Odoo classes fall back
transparently to the base ``CodeExtractor``.
"""

from __future__ import annotations

import logging
from typing import Union

from parrot.knowledge.graphindex.extractors.code import (
    CodeExtractor,
    _get_node_text,
    _make_node_id,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ODOO_BASES: set[str] = {"Model", "TransientModel", "AbstractModel"}

_FIELD_KWARGS: set[str] = {
    "comodel_name",
    "compute",
    "related",
    "store",
    "required",
    "readonly",
    "string",
    "default",
    "selection",
    "inverse",
    "search",
    "tracking",
    "ondelete",
    "domain",
    "groups",
    "company_dependent",
}

_API_DECORATORS: set[str] = {
    "depends",
    "onchange",
    "constrains",
    "model",
    "model_create_multi",
    "returns",
    "depends_context",
    "ondelete",
    "autovacuum",
}

_ModelRef = Union[str, list[str], dict[str, str], None]

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _model_node_id(model_name: str) -> str:
    """Return a stable, file-independent node id for a canonical Odoo model.

    Args:
        model_name: The Odoo model technical name (e.g. ``"res.partner"``).

    Returns:
        A 16-char hex node id derived from ``__odoo_model__::<model_name>``.
    """
    return _make_node_id("__odoo_model__", model_name)


def _strip_quotes(raw: str) -> str:
    """Remove surrounding string delimiters from a text node value.

    Args:
        raw: Raw text that may be wrapped in ``"``, ``'``, ``\"\"\"``, or
            ``'''``.

    Returns:
        Inner string content, or the original ``raw`` if no delimiters found.
    """
    for q in ('"""', "'''", '"', "'"):
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
            return raw[len(q) : -len(q)]
    return raw


def _literal_value(node, source_bytes: bytes) -> _ModelRef:
    """Best-effort evaluation of a string / list / dict literal AST node.

    Used to extract ``_name``, ``_inherit``, and ``_inherits`` assignments.
    Returns ``None`` for non-literal expressions (e.g. f-strings, variables)
    so that callers can skip canonical linking rather than crash.

    Args:
        node: A tree-sitter AST node representing the right-hand side of an
            assignment.
        source_bytes: Raw UTF-8 bytes of the source file.

    Returns:
        A ``str`` for simple string literals, a ``list[str]`` for list
        literals, a ``dict[str, str]`` for dictionary literals, or ``None``
        when the node type is not a supported literal.
    """
    if node is None:
        return None
    if node.type in ("string", "concatenated_string"):
        # Reject f-strings: tree-sitter represents interpolations as child nodes
        # with type "interpolation" inside a "string" node.
        if any(c.type == "interpolation" for c in node.children):
            return None
        return _strip_quotes(_get_node_text(node, source_bytes))
    if node.type == "list":
        out: list[str] = []
        for child in node.children:
            if child.type in ("string", "concatenated_string"):
                # Also skip f-string elements inside lists
                if any(c.type == "interpolation" for c in child.children):
                    continue
                out.append(_strip_quotes(_get_node_text(child, source_bytes)))
        return out or None
    if node.type == "dictionary":
        out_d: dict[str, str] = {}
        for pair in node.children:
            if pair.type != "pair":
                continue
            key = pair.child_by_field_name("key")
            val = pair.child_by_field_name("value")
            if key is not None and key.type == "string":
                if any(c.type == "interpolation" for c in key.children):
                    continue
                k = _strip_quotes(_get_node_text(key, source_bytes))
                v = (
                    _strip_quotes(_get_node_text(val, source_bytes))
                    if val is not None
                    and val.type == "string"
                    and not any(c.type == "interpolation" for c in val.children)
                    else ""
                )
                out_d[k] = v
        return out_d or None
    return None


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class OdooCodeExtractor(CodeExtractor):
    """Extract Odoo model structure on top of the generic code extractor.

    Only ``_extract_class`` is overridden.  Non-Odoo classes delegate to the
    base implementation, so mixing Odoo and plain Python in one repository is
    transparent.

    Emitted node types (in ``domain_tags["symbol_type"]``):
    - ``odoo_model_class`` — the concrete Python class in the file
    - ``odoo_model`` — canonical model node with synthetic ``source_uri``
    - ``odoo_field`` — ``fields.X(...)`` declarations inside the class
    - ``function`` — regular methods (unchanged from base); decorated ones
      carry ``domain_tags["decorators"]`` with ``@api.*`` metadata

    Emitted edge kinds beyond the base extractor:
    - ``EdgeKind.DEFINES`` — class → canonical model (when ``_name`` present)
    - ``EdgeKind.EXTENDS`` — class → canonical model (for each ``_inherit`` /
      ``_inherits`` name that differs from ``_name``)
    """

    # ------------------------------------------------------------------
    # Override: _extract_class
    # ------------------------------------------------------------------

    def _extract_class(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        parent_id: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> str:
        """Extract a class node, enriching Odoo model classes with domain metadata.

        Detects Odoo model classes via ``_name``/``_inherit``/``_inherits``
        assignments or via recognised base class names.  For non-Odoo classes
        delegates entirely to ``super()._extract_class()``.

        Args:
            node: tree-sitter ``class_definition`` AST node.
            file_path: Source file path as stored in ``source_uri``.
            source_bytes: Raw UTF-8 bytes of the source file.
            parent_id: ``node_id`` of the containing module or class.
            nodes: Accumulator list for emitted ``UniversalNode`` objects.
            edges: Accumulator list for emitted ``UniversalEdge`` objects.

        Returns:
            The ``node_id`` of the emitted class node.
        """
        name_node = node.child_by_field_name("name")
        class_name = (
            _get_node_text(name_node, source_bytes)
            if name_node
            else "__unknown_class__"
        )
        bases = self._extract_bases(node, source_bytes)
        meta = self._extract_model_meta(node, source_bytes)
        is_odoo = bool(
            meta["name"]
            or meta["inherit"]
            or meta["inherits"]
            or (_ODOO_BASES & set(bases))
        )
        if not is_odoo:
            return super()._extract_class(
                node, file_path, source_bytes, parent_id, nodes, edges
            )

        class_id = _make_node_id(file_path, class_name)
        docstring = self._get_docstring(node, source_bytes)
        class_node = UniversalNode(
            node_id=class_id,
            kind=NodeKind.SYMBOL,
            title=class_name,
            source_uri=file_path,
            summary=docstring,
            parent_id=parent_id,
            domain_tags={
                "symbol_type": "odoo_model_class",
                "model_name": meta["name"],
                "inherit": meta["inherit"],
                "inherits": meta["inherits"],
                "bases": bases,
                **self._span(node),
            },
        )
        nodes.append(class_node)
        edges.append(
            UniversalEdge(
                source_id=parent_id, target_id=class_id, kind=EdgeKind.CONTAINS
            )
        )
        edges.append(
            UniversalEdge(
                source_id=parent_id, target_id=class_id, kind=EdgeKind.DEFINES
            )
        )

        self._link_model(class_id, meta, nodes, edges)
        self._walk_model_body(
            node, file_path, source_bytes, class_id, class_name, nodes, edges
        )
        return class_id

    # ------------------------------------------------------------------
    # Model linking
    # ------------------------------------------------------------------

    def _link_model(
        self,
        class_id: str,
        meta: dict,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> None:
        """Emit canonical model nodes and DEFINES/EXTENDS edges.

        A canonical ``odoo_model`` node is emitted once per model name.  The
        edge type depends on context:

        - ``_name`` present → ``DEFINES`` from ``class_id`` to canonical.
        - ``_inherit``/``_inherits`` name (≠ ``_name``) → ``EXTENDS`` edge.

        Args:
            class_id: ``node_id`` of the Odoo model class.
            meta: Dictionary with keys ``"name"``, ``"inherit"``, ``"inherits"``
                populated by ``_extract_model_meta``.
            nodes: Accumulator for new canonical nodes.
            edges: Accumulator for new edges.
        """
        seen: set[str] = set()

        def ensure(model_name: str) -> str:
            mid = _model_node_id(model_name)
            if model_name not in seen:
                seen.add(model_name)
                nodes.append(
                    UniversalNode(
                        node_id=mid,
                        kind=NodeKind.SYMBOL,
                        title=model_name,
                        source_uri=f"odoo-model://{model_name}",
                        domain_tags={
                            "symbol_type": "odoo_model",
                            "model_name": model_name,
                        },
                    )
                )
            return mid

        if meta["name"]:
            edges.append(
                UniversalEdge(
                    source_id=class_id,
                    target_id=ensure(meta["name"]),
                    kind=EdgeKind.DEFINES,
                )
            )

        inherited: list[str] = []
        if isinstance(meta["inherit"], str):
            inherited.append(meta["inherit"])
        elif isinstance(meta["inherit"], list):
            inherited.extend(meta["inherit"])
        if isinstance(meta["inherits"], dict):
            inherited.extend(meta["inherits"].keys())

        for model_name in inherited:
            if model_name and model_name != meta["name"]:
                edges.append(
                    UniversalEdge(
                        source_id=class_id,
                        target_id=ensure(model_name),
                        kind=EdgeKind.EXTENDS,
                    )
                )

    # ------------------------------------------------------------------
    # Model body walking
    # ------------------------------------------------------------------

    def _walk_model_body(
        self,
        node,
        file_path: str,
        source_bytes: bytes,
        class_id: str,
        class_name: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> None:
        """Walk a class body emitting field nodes and annotating methods.

        Handles three statement shapes:

        - ``expression_statement → assignment`` — tried as a field declaration.
        - ``function_definition`` — extracted as a regular method.
        - ``decorated_definition`` — extracted as a method; ``@api.*``
          decorators stored in ``domain_tags["decorators"]``.

        Args:
            node: tree-sitter ``class_definition`` AST node.
            file_path: Source file path.
            source_bytes: Raw UTF-8 bytes of the source file.
            class_id: ``node_id`` of the parent class.
            class_name: Python class name (used for field IDs).
            nodes: Accumulator for new nodes.
            edges: Accumulator for new edges.
        """
        body = node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "assignment":
                        self._maybe_extract_field(
                            sub, file_path, source_bytes, class_id, class_name, nodes, edges
                        )
            elif child.type == "function_definition":
                self._extract_function(
                    child, file_path, source_bytes, class_id, nodes, edges
                )
            elif child.type == "decorated_definition":
                decorators = self._extract_decorators(child, source_bytes)
                for sub in child.children:
                    if sub.type == "function_definition":
                        func_id = self._extract_function(
                            sub, file_path, source_bytes, class_id, nodes, edges
                        )
                        if decorators:
                            self._annotate_decorators(func_id, decorators, nodes)

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _maybe_extract_field(
        self,
        assign,
        file_path: str,
        source_bytes: bytes,
        class_id: str,
        class_name: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> None:
        """Try to extract an Odoo field from an assignment node.

        Matches the pattern ``<name> = fields.<Type>(...)``.  Silently
        returns if the pattern does not match.

        Args:
            assign: tree-sitter ``assignment`` AST node.
            file_path: Source file path.
            source_bytes: Raw UTF-8 bytes of the source file.
            class_id: ``node_id`` of the parent class.
            class_name: Python class name (for stable field node ids).
            nodes: Accumulator for new field nodes.
            edges: Accumulator for new CONTAINS edges.
        """
        left = assign.child_by_field_name("left")
        right = assign.child_by_field_name("right")
        if (
            left is None
            or right is None
            or left.type != "identifier"
            or right.type != "call"
        ):
            return
        func = right.child_by_field_name("function")
        if func is None or func.type != "attribute":
            return
        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if (
            obj is None
            or attr is None
            or _get_node_text(obj, source_bytes) != "fields"
        ):
            return
        field_name = _get_node_text(left, source_bytes)
        field_type = _get_node_text(attr, source_bytes)
        kwargs = self._extract_field_kwargs(right, source_bytes)
        field_id = _make_node_id(file_path, f"{class_name}.{field_name}")
        nodes.append(
            UniversalNode(
                node_id=field_id,
                kind=NodeKind.SYMBOL,
                title=field_name,
                source_uri=file_path,
                summary=kwargs.get("string"),
                parent_id=class_id,
                domain_tags={
                    "symbol_type": "odoo_field",
                    "field_type": field_type,
                    **kwargs,
                    **self._span(assign),
                },
            )
        )
        edges.append(
            UniversalEdge(
                source_id=class_id, target_id=field_id, kind=EdgeKind.CONTAINS
            )
        )

    def _extract_field_kwargs(self, call_node, source_bytes: bytes) -> dict[str, str]:
        """Parse keyword arguments from a ``fields.Type(...)`` call node.

        Also captures the first positional string argument as ``comodel_name``
        (e.g. ``fields.Many2one('res.partner', ...)``) if no explicit
        ``comodel_name`` keyword is found.

        Args:
            call_node: tree-sitter ``call`` AST node.
            source_bytes: Raw UTF-8 bytes of the source file.

        Returns:
            Dictionary of recognised field kwargs (keys from ``_FIELD_KWARGS``).
        """
        out: dict[str, str] = {}
        args = call_node.child_by_field_name("arguments")
        if args is None:
            return out
        first_positional_used = False
        for arg in args.children:
            if arg.type == "keyword_argument":
                key_node = arg.child_by_field_name("name")
                val_node = arg.child_by_field_name("value")
                if key_node is None:
                    continue
                key = _get_node_text(key_node, source_bytes)
                if key in _FIELD_KWARGS and val_node is not None:
                    out[key] = _strip_quotes(_get_node_text(val_node, source_bytes))
            elif arg.type == "string" and not first_positional_used:
                first_positional_used = True
                out.setdefault(
                    "comodel_name",
                    _strip_quotes(_get_node_text(arg, source_bytes)),
                )
        return out

    # ------------------------------------------------------------------
    # Decorator extraction
    # ------------------------------------------------------------------

    def _extract_decorators(self, decorated_node, source_bytes: bytes) -> list[dict]:
        """Extract ``@api.*`` decorators from a ``decorated_definition`` node.

        Args:
            decorated_node: tree-sitter ``decorated_definition`` AST node.
            source_bytes: Raw UTF-8 bytes of the source file.

        Returns:
            List of ``{"name": str, "args": list[str]}`` dicts for each
            recognised ``@api.*`` decorator found.
        """
        found: list[dict] = []
        for child in decorated_node.children:
            if child.type != "decorator":
                continue
            expr = next(
                (
                    c
                    for c in child.children
                    if c.type in ("call", "attribute", "identifier")
                ),
                None,
            )
            if expr is None:
                continue
            call_node = expr if expr.type == "call" else None
            attr_node = call_node.child_by_field_name("function") if call_node else expr
            if attr_node is None or attr_node.type != "attribute":
                continue
            obj = attr_node.child_by_field_name("object")
            name = attr_node.child_by_field_name("attribute")
            if (
                obj is None
                or name is None
                or _get_node_text(obj, source_bytes) != "api"
            ):
                continue
            deco_name = _get_node_text(name, source_bytes)
            if deco_name not in _API_DECORATORS:
                continue
            args: list[str] = []
            if call_node is not None:
                arglist = call_node.child_by_field_name("arguments")
                if arglist is not None:
                    args = [
                        _strip_quotes(_get_node_text(a, source_bytes))
                        for a in arglist.children
                        if a.type == "string"
                    ]
            found.append({"name": deco_name, "args": args})
        return found

    @staticmethod
    def _annotate_decorators(
        func_id: str, decorators: list[dict], nodes: list[UniversalNode]
    ) -> None:
        """Attach decorator metadata to the matching function node in-place.

        Args:
            func_id: ``node_id`` of the function node to annotate.
            decorators: List of decorator dicts from ``_extract_decorators``.
            nodes: Current node list to search through.
        """
        for n in nodes:
            if n.node_id == func_id:
                n.domain_tags["decorators"] = decorators
                return

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _span(node) -> dict:
        """Return 1-based ``lineno``/``end_lineno`` from a tree-sitter node.

        Args:
            node: Any tree-sitter AST node with ``start_point``/``end_point``.

        Returns:
            ``{"lineno": int, "end_lineno": int}``
        """
        return {
            "lineno": node.start_point[0] + 1,
            "end_lineno": node.end_point[0] + 1,
        }

    @staticmethod
    def _extract_bases(class_node, source_bytes: bytes) -> list[str]:
        """Extract base class short names from a ``class_definition`` node.

        For ``class Foo(models.Model, Mixin)`` returns
        ``["Model", "Mixin"]`` (attribute right-hand side and plain
        identifiers).

        Args:
            class_node: tree-sitter ``class_definition`` AST node.
            source_bytes: Raw UTF-8 bytes of the source file.

        Returns:
            List of base class simple names.
        """
        supers = class_node.child_by_field_name("superclasses")
        if supers is None:
            return []
        names: list[str] = []
        for child in supers.children:
            if child.type == "attribute":
                attr = child.child_by_field_name("attribute")
                if attr is not None:
                    names.append(_get_node_text(attr, source_bytes))
            elif child.type == "identifier":
                names.append(_get_node_text(child, source_bytes))
        return names

    def _extract_model_meta(
        self, class_node, source_bytes: bytes
    ) -> dict:
        """Walk the class body for ``_name``, ``_inherit``, and ``_inherits``.

        Uses ``_literal_value`` for safe evaluation — dynamic expressions
        (f-strings, variables) result in ``None`` values rather than crashes.

        Args:
            class_node: tree-sitter ``class_definition`` AST node.
            source_bytes: Raw UTF-8 bytes of the source file.

        Returns:
            ``{"name": str|None, "inherit": str|list|None, "inherits": dict|None}``
        """
        meta: dict = {"name": None, "inherit": None, "inherits": None}
        body = class_node.child_by_field_name("body")
        if body is None:
            return meta
        for child in body.children:
            if child.type != "expression_statement":
                continue
            for sub in child.children:
                if sub.type != "assignment":
                    continue
                left = sub.child_by_field_name("left")
                right = sub.child_by_field_name("right")
                if left is None or left.type != "identifier":
                    continue
                key = _get_node_text(left, source_bytes)
                if key == "_name":
                    val = _literal_value(right, source_bytes)
                    meta["name"] = val if isinstance(val, str) else None
                elif key == "_inherit":
                    meta["inherit"] = _literal_value(right, source_bytes)
                elif key == "_inherits":
                    val = _literal_value(right, source_bytes)
                    meta["inherits"] = val if isinstance(val, dict) else None
        return meta


# Re-export Optional for type hints used in base class references at runtime.
__all__ = ["OdooCodeExtractor"]
