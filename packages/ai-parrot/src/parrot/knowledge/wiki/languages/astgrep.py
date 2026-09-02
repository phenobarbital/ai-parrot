"""Optional ast-grep structural extraction seam for the wiki scanners.

Mirrors :mod:`parrot.knowledge.wiki.languages.treesitter`: a cached,
never-raising seam that hides an optional dependency (``ast-grep-py``,
extra ``wiki-structural``). :func:`is_available` / :func:`supported_language`
/ :func:`parse` return ``None``/``False`` whenever the package, a language
grammar, or a rule file is missing — callers fall back to the existing
tree-sitter walker or heuristic tier unconditionally.

Extraction rules are pure data: one YAML file per language under
``languages/rules/<lang>.yaml``, validated into a :class:`RuleSet` at load
time. Anything a rule needs that is not expressible as ``kind``/``field``/
``inside``/``has`` data lives in the small, fixed :data:`EXTRACTORS` table
(doc-comment/parent lookups) — implemented once here, never per rule file.

This module never touches the working tree beyond the ``src`` string it is
given, and it never raises: a pyo3 ``PanicException`` (a ``BaseException``,
not an ``Exception``) is caught around the one call that can produce it
(``SgRoot(...)``), and every other failure mode degrades to ``None`` with at
most one log record per (language, rule id) key.
"""

from __future__ import annotations

import functools
import importlib.util
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field, field_validator

from parrot.knowledge.wiki.symbols import (
    StructuralOutline,
    SymbolKind,
    SymbolRecord,
    SymbolRef,
    sha1_of_text,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ast_grep_py import SgNode, SgRoot

logger = logging.getLogger(__name__)

#: Directory containing one ``<lang>.yaml`` rule file per language,
#: installed as package data (see ``pyproject.toml``). Exposed as a
#: module-level constant so tests can point ``RuleSet._load_from_dir``
#: at a temporary directory instead of the real package data.
_RULES_DIR = Path(__file__).parent / "rules"

#: Languages ast-grep-py supports out of the box for this feature.
_BUILTIN_LANGUAGES: frozenset[str] = frozenset(
    {"python", "javascript", "typescript", "tsx", "php", "rust"}
)

#: Qualname separator per language; anything absent here joins with ``.``.
_QUALNAME_JOINER: dict[str, str] = {
    "php": "::",
    "rust": "::",
    "perl": "::",
}

#: Cached result of the Perl dynamic-registration attempt (``None`` = not
#: attempted yet).
_PERL_REGISTERED: bool | None = None

#: Rule (language, rule id) keys already warned about a bad ``kind`` /
#: matcher error, so repeated files/scans don't spam the log.
_WARNED_RULE_KEYS: set[tuple[str, str]] = set()


def is_available() -> bool:
    """Return whether ``ast-grep-py`` is importable in this process.

    Returns:
        ``True`` when ``import ast_grep_py`` succeeds, ``False`` otherwise.
        Never raises.
    """
    try:
        import ast_grep_py  # noqa: F401
    except ImportError:
        return False
    return True


def _locate_perl_binding() -> str | None:
    """Find the ``tree-sitter-perl`` wheel's compiled binding.

    Returns:
        Path to the ``_binding*.so`` file, or ``None`` when the
        ``tree_sitter_perl`` package or its binding cannot be located.
    """
    try:
        spec = importlib.util.find_spec("tree_sitter_perl")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    candidates = sorted(Path(spec.origin).parent.glob("_binding*.so"))
    return str(candidates[0]) if candidates else None


def _register_perl_dynamic_language() -> bool:
    """Attempt one-time dynamic registration of Perl with ast-grep-py.

    Cached at module level (``_PERL_REGISTERED``) so registration is
    attempted at most once per process. Logs at DEBUG (not per-file) when
    the attempt fails.

    Returns:
        ``True`` when Perl is registered (or was already registered),
        ``False`` when the binding could not be located or registration
        raised.
    """
    global _PERL_REGISTERED
    if _PERL_REGISTERED is not None:
        return _PERL_REGISTERED

    binding_path = _locate_perl_binding()
    if binding_path is None:
        logger.debug("tree-sitter-perl binding not found; Perl ast-grep support disabled")
        _PERL_REGISTERED = False
        return False

    try:
        from ast_grep_py import register_dynamic_language

        register_dynamic_language(
            {
                "perl": {  # type: ignore[typeddict-unknown-key]
                    "library_path": binding_path,
                    "language_symbol": "tree_sitter_perl",
                    # "extensions" is accepted at runtime (verified against
                    # ast-grep-py 0.45.3) but missing from the installed
                    # CustomLang TypedDict stub.
                    "extensions": ["pl", "pm", "t"],
                }
            }
        )
    except Exception:
        logger.debug("ast-grep dynamic registration of Perl failed", exc_info=True)
        _PERL_REGISTERED = False
        return False

    _PERL_REGISTERED = True
    return True


def supported_language(lang: str) -> bool:
    """Return whether ``lang`` can be parsed by ast-grep-py right now.

    Args:
        lang: ast-grep language name (e.g. ``"python"``, ``"rust"``,
            ``"perl"``).

    Returns:
        ``True`` for the built-in whitelist, or for ``"perl"`` once
        dynamic registration against the installed ``tree-sitter-perl``
        wheel has succeeded. ``False`` for anything else, including when
        ``ast-grep-py`` itself is not installed. Never raises.
    """
    if not is_available():
        return False
    if lang in _BUILTIN_LANGUAGES:
        return True
    if lang == "perl":
        return _register_perl_dynamic_language()
    return False


def parse(src: str, lang: str) -> SgRoot | None:
    """Parse ``src`` as ``lang`` into an ast-grep ``SgRoot``, or ``None``.

    ``supported_language()`` is checked first in every path — the
    ``BaseException`` fence below is defence in depth, not the primary
    guard, since pyo3 can panic (``PanicException``, a ``BaseException``,
    not an ``Exception``) for a handful of inputs the whitelist should
    already exclude.

    Args:
        src: Full file source text.
        lang: ast-grep language name.

    Returns:
        A constructed ``SgRoot``, or ``None`` when ast-grep is
        unavailable, the language is unsupported, or parsing panicked.
    """
    if not supported_language(lang):
        return None
    try:
        return _sgroot_factory(src, lang)
    except BaseException:  # noqa: BLE001 - pyo3 PanicException is not an Exception
        logger.warning("ast-grep panicked while parsing language=%s; falling back", lang)
        return None


def _sgroot_factory(src: str, lang: str) -> SgRoot:
    """Construct an ``SgRoot`` — isolated so tests can spy on/replace it."""
    from ast_grep_py import SgRoot

    return SgRoot(src, lang)


def named_text(node: SgNode, var: str) -> str:
    """Join a ``$$$VAR`` metavariable capture, ignoring anonymous nodes.

    Anonymous nodes (e.g. the ``,`` separators in an argument list) are
    included in ``get_multiple_matches`` captures; only ``is_named()``
    nodes should appear in rendered output.

    Args:
        node: The matched node the capture was taken from.
        var: Metavariable name (without the ``$$$`` prefix).

    Returns:
        ``", "``-joined text of the named captured nodes, or ``""`` when
        there is no such capture.
    """
    matches = node.get_multiple_matches(var)
    if not matches:
        return ""
    return ", ".join(n.text() for n in matches if n.is_named())


# ---------------------------------------------------------------------
# Fixed extractors — the only place rule files may plug in logic.
# ---------------------------------------------------------------------


#: Node kinds to walk past (not treat as a doc-comment blocker) when
#: looking for the nearest preceding comment — Rust's ``#[derive(...)]``
#: (TASK-2744: verified live, matches ``rust.py``'s own
#: ``while prev.type == "attribute_item": prev = prev.prev_sibling``).
#: Harmless no-op for grammars without this kind.
_COMMENT_SKIP_KINDS = frozenset({"attribute_item"})


def _first_comment_before(node: SgNode) -> SgNode | None:
    """Return the nearest preceding comment-kind sibling.

    Skips over any :data:`_COMMENT_SKIP_KINDS` node in between (e.g. a
    Rust attribute macro sitting between the doc comment and the item it
    documents), matching every walker's own behavior for the same case.
    """
    prev = node.prev()
    while prev is not None and prev.kind() in _COMMENT_SKIP_KINDS:
        prev = prev.prev()
    if prev is not None and "comment" in prev.kind():
        return prev
    return None


#: Wrapper node kinds whose own leading position is where a doc comment
#: actually sits for an exported declaration (e.g. TS/JS
#: ``export class Foo {}`` — the comment precedes ``export_statement``,
#: not the ``class_declaration`` inside it).
_COMMENT_PROBE_WRAPPERS = frozenset({"export_statement"})


def _first_comment_before_export_aware(node: SgNode) -> SgNode | None:
    """Like :func:`_first_comment_before`, but probes past an export wrapper.

    TASK-2742: verified against ast-grep-py 0.45.3's typescript grammar —
    an exported declaration's own ``.prev()`` is the ``export`` keyword
    token, not the doc comment, which instead precedes the
    ``export_statement`` wrapper itself.

    Deliberately a SEPARATE extractor from :func:`leading_comment`
    (used only by ``class``/``function``/``interface``/``type`` rules,
    not ``const``): the JS/TS walker's own ``_leading_doc`` call for
    ``lexical_declaration`` (``const``) has no such parent-probing
    fallback, so an exported const's doc is a byte-parity casualty in
    the walker too — reproducing that asymmetry, not "fixing" it, is
    the parity contract (spec §7 "the walkers are the oracle").
    """
    parent = node.parent()
    probe = parent if parent is not None and parent.kind() in _COMMENT_PROBE_WRAPPERS else node
    prev = probe.prev()
    if prev is not None and "comment" in prev.kind():
        return prev
    return None


def _strip_comment_markers(text: str) -> str:
    """Strip common line/block comment markers and doc-comment sigils."""
    text = text.strip()
    for prefix in ("////", "///", "//!", "//", "/**", "/*!", "/*", "#"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.rstrip("*/").strip()
    lines = [ln.strip().lstrip("*").strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln).strip()


def first_docstring(node: SgNode) -> str:
    """First bare string-literal statement in ``node``'s body.

    Mirrors the "docstring" convention (a lone string expression as the
    first statement of a block) for languages that use it.
    """
    body = node.field("body")
    if body is None:
        return ""
    for child in body.children():
        if not child.is_named():
            continue
        if child.kind() == "expression_statement":
            expr = child.child(0)
            if expr is not None and "string" in expr.kind():
                return _strip_comment_markers(expr.text().strip("\"'"))
        break
    return ""


def leading_comment(node: SgNode) -> str:
    """Nearest plain leading comment immediately before ``node``."""
    comment = _first_comment_before(node)
    return _strip_comment_markers(comment.text()) if comment is not None else ""


def leading_doc_comment(node: SgNode) -> str:
    """Nearest leading *doc* comment (``/** */``, ``///``) before ``node``."""
    comment = _first_comment_before(node)
    if comment is None:
        return ""
    text = comment.text().strip()
    if text.startswith(("/**", "///", "/*!")):
        return _strip_comment_markers(text)
    return ""


def leading_comment_exported(node: SgNode) -> str:
    """Like :func:`leading_comment`, probing past an ``export_statement``.

    Use for TS/JS declarations the walker itself doc-probes through the
    export wrapper for (``class``/``function``/``interface``/``type``) —
    NOT for ``const`` (see :func:`_first_comment_before_export_aware`).
    """
    comment = _first_comment_before_export_aware(node)
    return _strip_comment_markers(comment.text()) if comment is not None else ""


def module_docstring(node: SgNode) -> str:
    """First bare string-literal statement at the top of the module."""
    for child in node.children():
        if not child.is_named():
            continue
        if child.kind() == "expression_statement":
            expr = child.child(0)
            if expr is not None and "string" in expr.kind():
                return _strip_comment_markers(expr.text().strip("\"'"))
        break
    return ""


def first_heading_comment(node: SgNode) -> str:
    """First comment node anywhere at the top level of the file."""
    for child in node.children():
        if "comment" in child.kind():
            return _strip_comment_markers(child.text())
        if child.is_named():
            break
    return ""


def pod_head2(node: SgNode) -> str:
    """First non-empty line of a Perl ``=head2`` POD block preceding ``node``."""
    pod = _first_comment_before(node)
    if pod is None or "pod" not in pod.kind():
        return ""
    lines = pod.text().splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("=head2"):
            for later in lines[i + 1:]:
                stripped = later.strip()
                if stripped and not stripped.startswith("="):
                    return stripped
    return ""


#: Node kinds whose block-less form scopes everything until the next
#: occurrence (or EOF) as a *preceding sibling*, not an ancestor — Perl's
#: ``package Foo;`` and PHP's ``namespace Foo\Bar;`` (TASK-2743).
_PRECEDING_CONTAINER_KINDS = frozenset({"package_statement", "namespace_definition"})


def preceding_package(node: SgNode) -> str:
    """Qualname of the last package/namespace statement preceding ``node``.

    Perl's block-less ``package Foo;`` form (and PHP's equivalent
    block-less ``namespace Foo\\Bar;``) scopes everything until the next
    such statement (or EOF) — the *last preceding* one, not an ancestor,
    is the container (matches ``perl.py``'s existing walker).
    """
    current = node.prev()
    while current is not None:
        if current.kind() in _PRECEDING_CONTAINER_KINDS:
            name_node = current.field("name") or current.child(1)
            return name_node.text() if name_node is not None else ""
        current = current.prev()
    return ""


#: Container kinds a PHP method/function can be nested in.
_PHP_CONTAINER_KINDS = frozenset(
    {"class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"}
)


def php_qualified_container(node: SgNode) -> str:
    """Namespace-qualified name of ``node``'s enclosing PHP container.

    PHP's block-less ``namespace Foo\\Bar;`` form is a preceding sibling
    of the class it scopes, not an ancestor (see :func:`preceding_package`)
    — this combines that namespace lookup with the immediate
    class/interface/trait/enum ancestor's own name, joined by ``\\``, so
    a method's ``parent`` can carry the full ``Ns\\Class`` qualname (spec
    §2 ``SymbolRecord.qualname`` example
    ``"App\\Models\\User::getFullName"``).
    """
    container = next((a for a in node.ancestors() if a.kind() in _PHP_CONTAINER_KINDS), None)
    if container is None:
        return ""
    name_field = container.field("name")
    container_name = name_field.text() if name_field is not None else ""
    namespace = preceding_package(container)
    return f"{namespace}\\{container_name}" if namespace else container_name


EXTRACTORS: dict[str, Callable[[SgNode], str]] = {
    "none": lambda _node: "",
    "first_docstring": first_docstring,
    "leading_comment": leading_comment,
    "leading_comment_exported": leading_comment_exported,
    "leading_doc_comment": leading_doc_comment,
    "pod_head2": pod_head2,
    "module_docstring": module_docstring,
    "first_heading_comment": first_heading_comment,
    "preceding_package": preceding_package,
    "php_qualified_container": php_qualified_container,
}


# ---------------------------------------------------------------------
# Rule schema
# ---------------------------------------------------------------------


class SymbolSpec(BaseModel):
    """One ``symbols[]`` entry of a language rule file.

    Attributes:
        id: A :class:`~parrot.knowledge.wiki.symbols.SymbolKind` value
            (``"class"``, ``"function"``, ...).
        rule: ast-grep rule object, evaluated as
            ``node.find_all({"rule": rule})``.
        name: How to extract the symbol's local name — ``{"field": ...}``,
            ``{"path": [...]}``, or ``{"text": true}``.
        signature: Optional, same shape as ``name``.
        doc: Name of an :data:`EXTRACTORS` entry (``"none"`` for no doc).
        parent: Either ``{"ancestor": <kind>, "name": {...}}`` (structural
            lookup) or the name of an :data:`EXTRACTORS` entry that
            returns the parent qualname directly (e.g.
            ``"preceding_package"``).
        exported: ``"always"``, ``"never"``, ``{"inside": <kind>}`` or
            ``{"has": <kind>}``.
        is_async: Same shape family as ``exported``.
        depth: Explicit nesting depth; when omitted, defaults to ``2``
            when ``parent`` is set, else ``1``.
        qualname_joiner: Separator between ``parent`` and ``name`` in the
            computed qualname; when omitted, falls back to the
            language's entry in ``_QUALNAME_JOINER`` (``.`` by default).
            TASK-2743: PHP needs two different separators in the same
            file — ``\\`` between a namespace and its class, ``::``
            between a class and its method — which a single per-language
            joiner cannot express.
    """

    id: str
    rule: dict[str, Any]
    name: dict[str, Any] | None = None
    signature: dict[str, Any] | None = None
    doc: str = "none"
    parent: dict[str, Any] | str | None = None
    exported: dict[str, Any] | str | None = None
    is_async: dict[str, Any] | str | None = Field(default=None, alias="async")
    depth: int | None = None
    qualname_joiner: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("doc")
    @classmethod
    def _doc_extractor_exists(cls, value: str) -> str:
        if value not in EXTRACTORS:
            raise ValueError(f"unknown doc extractor: {value!r}")
        return value

    @field_validator("parent")
    @classmethod
    def _parent_extractor_exists(cls, value: Any) -> Any:
        if isinstance(value, str) and value not in EXTRACTORS:
            raise ValueError(f"unknown parent extractor: {value!r}")
        return value


class RefSpec(BaseModel):
    """One ``refs[]`` entry of a language rule file.

    Attributes:
        rel: ``"calls"``, ``"extends"``, ``"implements"`` or ``"uses"``.
        rule: ast-grep rule object.
        target: How to extract the reference target text — ``{"field":
            ...}`` or ``{"each": <kind>}`` (one ref per descendant of
            that kind).
        scope: Optional ``{"ancestor": [<kind>, ...]}`` — the nearest
            enclosing symbol whose qualname becomes ``src_qualname``.
    """

    rel: str = Field(pattern=r"^(calls|extends|implements|uses)$")
    rule: dict[str, Any]
    target: dict[str, Any]
    scope: dict[str, Any] | None = None


class ImportSpec(BaseModel):
    """One ``imports[]`` entry of a language rule file."""

    rule: dict[str, Any]


class RuleSet(BaseModel):
    """Validated, cached extraction rules for one language.

    Attributes:
        language: ast-grep language name this file's rules target.
        aliases: Other ast-grep language names served by this same file
            (e.g. ``typescript.yaml`` also serves ``tsx``/``javascript``).
        summary: Name of an :data:`EXTRACTORS` entry used for the file's
            summary line.
        symbols: Symbol extraction rules.
        refs: Reference extraction rules.
        imports: Import-statement extraction rules.
    """

    language: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = "none"
    symbols: list[SymbolSpec] = Field(default_factory=list)
    refs: list[RefSpec] = Field(default_factory=list)
    imports: list[ImportSpec] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _summary_extractor_exists(cls, value: str) -> str:
        if value not in EXTRACTORS:
            raise ValueError(f"unknown summary extractor: {value!r}")
        return value

    @classmethod
    @functools.cache
    def load(cls, lang: str) -> RuleSet | None:
        """Load and validate ``languages/rules/<lang>.yaml`` for ``lang``.

        Resolves aliases: a rule file may declare ``aliases`` covering
        other ast-grep language names it also serves (e.g.
        ``typescript.yaml`` also serves ``javascript``/``tsx``) — every
        rule file under the package is scanned once for a
        ``language``/``aliases`` match.

        Cached (``functools.lru_cache``) — call ``RuleSet.load.cache_clear()``
        to force a reload (tests only; rule files are package data and do
        not change at runtime).

        Args:
            lang: ast-grep language name.

        Returns:
            The validated :class:`RuleSet`, or ``None`` when no rule file
            matches ``lang`` or the matching file fails validation (in
            which case exactly one WARNING is logged).
        """
        return cls._load_uncached(lang)

    @classmethod
    def _load_uncached(cls, lang: str) -> RuleSet | None:
        return cls._load_from_dir(_RULES_DIR, lang)

    @classmethod
    def _load_from_dir(cls, rules_dir: Path, lang: str) -> RuleSet | None:
        """Scan ``rules_dir`` for a ``*.yaml`` file matching ``lang``.

        Split out from :meth:`_load_uncached` so tests can point it at a
        temporary directory instead of the real package data.
        """
        if not rules_dir.is_dir():
            return None
        for yaml_path in sorted(rules_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                logger.warning("Malformed ast-grep rule file: %s", yaml_path)
                continue
            if not isinstance(raw, dict):
                continue
            declared = {raw.get("language"), *raw.get("aliases", [])}
            if lang not in declared:
                continue
            try:
                return cls.model_validate(raw)
            except Exception as exc:  # noqa: BLE001 - any validation failure -> None + one WARNING
                logger.warning("Invalid ast-grep rule file %s: %s", yaml_path, exc)
                return None
        return None


# ---------------------------------------------------------------------
# Value/spec resolution helpers
# ---------------------------------------------------------------------


def _strip_enclosing_parens(text: str) -> str:
    """Strip one layer of surrounding ``(...)``, matching every walker's
    own ``params_node_text.strip("()")`` convention for a parameter list
    (render.py's documented ``SymbolRecord.signature`` contract). A no-op
    for any other field (names/paths never carry surrounding parens)."""
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1]
    return text


def _resolve_value_spec(node: SgNode, spec: dict[str, Any] | None) -> str:
    """Resolve a ``name``/``signature``-shaped spec against ``node``."""
    if not spec:
        return ""
    field_name = spec.get("field")
    if field_name:
        target = node.field(field_name)
        return _strip_enclosing_parens(target.text()) if target is not None else ""
    path = spec.get("path")
    if path:
        current: SgNode | None = node
        for kind in path:
            current = current.find(kind=kind) if current is not None else None
        return _strip_enclosing_parens(current.text()) if current is not None else ""
    if spec.get("text"):
        return node.text()
    return ""


def _resolve_parent(node: SgNode, spec: dict[str, Any] | str | None) -> str | None:
    """Resolve a ``parent``-shaped spec against ``node``."""
    if spec is None:
        return None
    if isinstance(spec, str):
        extractor = EXTRACTORS.get(spec)
        result = extractor(node) if extractor else ""
        return result or None
    ancestor_kind = spec.get("ancestor")
    if ancestor_kind:
        for ancestor in node.ancestors():
            if ancestor.kind() == ancestor_kind:
                return _resolve_value_spec(ancestor, spec.get("name")) or None
    return None


def _resolve_bool_spec(node: SgNode, spec: dict[str, Any] | str | None) -> bool:
    """Resolve an ``exported``/``is_async``-shaped spec against ``node``."""
    if spec is None:
        return False
    if spec == "always":
        return True
    if spec == "never":
        return False
    if isinstance(spec, dict):
        if "inside" in spec:
            kind = spec["inside"]
            return any(ancestor.kind() == kind for ancestor in node.ancestors())
        if "has" in spec:
            kind = spec["has"]
            return node.find(kind=kind) is not None
    return False


def _build_symbol_record(
    node: SgNode,
    spec: SymbolSpec,
    *,
    language: str,
    rel_path: str,
) -> SymbolRecord | None:
    """Build one :class:`SymbolRecord` from a matched node, or ``None``."""
    try:
        kind = SymbolKind(spec.id)
    except ValueError:
        logger.warning("Unknown SymbolKind for rule id=%s in language=%s", spec.id, language)
        return None

    name = _resolve_value_spec(node, spec.name)
    if not name:
        return None
    parent = _resolve_parent(node, spec.parent)
    joiner = spec.qualname_joiner if spec.qualname_joiner is not None else _QUALNAME_JOINER.get(language, ".")
    qualname = f"{parent}{joiner}{name}" if parent else name
    depth = spec.depth if spec.depth is not None else (2 if parent else 1)
    node_range = node.range()

    return SymbolRecord(
        rel_path=rel_path,
        language=language,
        kind=kind,
        name=name,
        qualname=qualname,
        parent=parent,
        signature=_resolve_value_spec(node, spec.signature),
        doc=EXTRACTORS[spec.doc](node) if spec.doc in EXTRACTORS else "",
        exported=_resolve_bool_spec(node, spec.exported),
        is_async=_resolve_bool_spec(node, spec.is_async),
        start_line=node_range.start.line + 1,
        end_line=node_range.end.line + 1,
        start_byte=node_range.start.index,
        end_byte=node_range.end.index,
        node_kind=node.kind(),
        content_hash=sha1_of_text(node.text()),
        depth=depth,
    )


def _find_all_isolated(root: SgNode, rule: dict[str, Any], *, language: str, rule_id: str) -> list[SgNode]:
    """``root.find_all({"rule": rule})``, isolating a bad-matcher error.

    A rule referencing a ``kind`` the installed grammar wheel does not
    have raises ``RuntimeError: cannot get matcher`` — logged once per
    (language, rule id) key, then treated as "no matches" so the rest of
    the rule file keeps working.
    """
    try:
        # `rule` is an arbitrary, YAML-decoded nested dict validated only
        # at the top level by SymbolSpec/RefSpec/ImportSpec — too dynamic
        # to satisfy the SDK's structural `Config` TypedDict statically.
        return list(root.find_all({"rule": rule}))  # type: ignore[call-overload]
    except RuntimeError:
        key = (language, rule_id)
        if key not in _WARNED_RULE_KEYS:
            _WARNED_RULE_KEYS.add(key)
            logger.warning("ast-grep rule %r for language=%s could not be evaluated", rule_id, language)
        return []


def extract(src: str, lang: str, rel_path: str, *, max_depth: int = 2) -> StructuralOutline | None:
    """Run the ast-grep structural extraction seam over one file.

    Args:
        src: Full file source text.
        lang: ast-grep language name.
        rel_path: POSIX path relative to the repository root (stamped
            onto every produced :class:`SymbolRecord`).
        max_depth: Symbols whose resolved ``depth`` exceeds this value
            are dropped.

    Returns:
        A :class:`StructuralOutline`, or ``None`` when ast-grep is
        unavailable, the language is unsupported, parsing failed, or no
        rule file matches ``lang``. Never raises.
    """
    ruleset = RuleSet.load(lang)
    if ruleset is None:
        return None
    sg_root = parse(src, lang)
    if sg_root is None:
        return None
    root = sg_root.root()

    symbols: list[SymbolRecord] = []
    for spec in ruleset.symbols:
        for node in _find_all_isolated(root, spec.rule, language=lang, rule_id=spec.id):
            record = _build_symbol_record(node, spec, language=lang, rel_path=rel_path)
            if record is not None and record.depth <= max_depth:
                symbols.append(record)

    refs: list[SymbolRef] = []
    for ref_spec in ruleset.refs:
        for node in _find_all_isolated(root, ref_spec.rule, language=lang, rule_id=ref_spec.rel):
            src_qualname = ""
            if ref_spec.scope:
                ancestor_kinds = ref_spec.scope.get("ancestor") or []
                for ancestor in node.ancestors():
                    if ancestor.kind() in ancestor_kinds:
                        name_field = ancestor.field("name")
                        src_qualname = name_field.text() if name_field is not None else ""
                        break
            each_kind = ref_spec.target.get("each")
            if each_kind:
                for descendant in _find_all_isolated(node, {"kind": each_kind}, language=lang, rule_id=ref_spec.rel):
                    refs.append(
                        SymbolRef(
                            src_qualname=src_qualname,
                            rel=ref_spec.rel,
                            target_text=descendant.text(),
                            line=node.range().start.line + 1,
                        )
                    )
            else:
                target_text = _resolve_value_spec(node, ref_spec.target)
                if target_text:
                    refs.append(
                        SymbolRef(
                            src_qualname=src_qualname,
                            rel=ref_spec.rel,
                            target_text=target_text,
                            line=node.range().start.line + 1,
                        )
                    )

    imports: list[str] = []
    for import_spec in ruleset.imports:
        for node in _find_all_isolated(root, import_spec.rule, language=lang, rule_id="imports"):
            imports.append(node.text())

    summary = EXTRACTORS[ruleset.summary](root) if ruleset.summary in EXTRACTORS else ""

    return StructuralOutline(summary=summary, symbols=symbols, refs=refs, imports=imports)
