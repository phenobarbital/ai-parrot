"""Symbol plane models and id grammar for the wiki structural backend.

This module is the foundation contract for FEAT-498 (ast-grep structural
plane): every extraction, storage and service layer downstream shares the
:class:`SymbolRecord` / :class:`SymbolRef` / :class:`StructuralOutline`
models and the ``sym:<rel>#<qualname>[~n]`` id grammar defined here.

Nothing in this module reads the filesystem or imports anything beyond
``pydantic`` and the standard library, to avoid import cycles with
``languages/base.py`` and ``repo_scan.py`` (both of which import from
here).
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    """Kind of a symbol extracted from a source file.

    Mirrors the design's §4.4 symbol table across the five supported
    languages (Python, TypeScript/JavaScript, PHP, Rust, Perl).
    """

    MODULE = "module"
    CLASS = "class"
    INTERFACE = "interface"
    TRAIT = "trait"
    ENUM = "enum"
    STRUCT = "struct"
    IMPL = "impl"
    FUNCTION = "function"
    METHOD = "method"
    CONST = "const"
    TYPE = "type"
    PACKAGE = "package"
    ROLE = "role"
    FIELD = "field"
    ATTRIBUTE = "attribute"
    MOD = "mod"


class SymbolRecord(BaseModel):
    """A single extracted symbol (class, function, method, ...).

    Attributes:
        rel_path: POSIX path relative to the repository root.
        language: Scanner name that produced this record (``python``,
            ``javascript``, ``php``, ``rust``, ``perl``).
        kind: Symbol kind.
        name: Local identifier as written in the source.
        qualname: Fully-qualified name, e.g. ``"UserService.get_user"``
            or ``"App\\Models\\User::getFullName"``.
        parent: Container qualname, or ``None`` for top-level symbols.
        signature: Parameters (and return type) as written in the source.
        doc: First line of the symbol's documentation/docstring.
        exported: Whether the symbol is exported/public (``export``,
            ``pub``, ``public``).
        is_async: Whether the symbol is declared ``async``.
        start_line: 1-based inclusive start line.
        end_line: 1-based inclusive end line.
        start_byte: Byte offset of the symbol's first byte in the file.
        end_byte: Byte offset just past the symbol's last byte.
        node_kind: The tree-sitter/ast-grep node kind that produced this
            record, or ``""`` when derived from Python's stdlib ``ast``.
        decorators: Decorator/attribute strings attached to the symbol.
        content_hash: SHA-1 hex digest of the symbol's source text.
        depth: Nesting depth — ``1`` for top-level, ``2`` for direct
            members, etc.
    """

    rel_path: str
    language: str
    kind: SymbolKind
    name: str
    qualname: str
    parent: str | None = None
    signature: str = ""
    doc: str = ""
    exported: bool = False
    is_async: bool = False
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    node_kind: str = ""
    decorators: list[str] = Field(default_factory=list)
    content_hash: str
    depth: int = 1


class SymbolRef(BaseModel):
    """An unresolved reference from one symbol to another symbol or name.

    Attributes:
        src_qualname: Qualname of the symbol that holds the reference.
        rel: Kind of reference — ``"calls"``, ``"extends"``,
            ``"implements"`` or ``"uses"``.
        target_text: The reference target as written in the source
            (e.g. ``"BaseService"``, ``"helper"``, ``"self.repo.get"``).
        line: 1-based line number where the reference occurs.
    """

    src_qualname: str
    rel: str = Field(pattern=r"^(calls|extends|implements|uses)$")
    target_text: str
    line: int


class StructuralOutline(BaseModel):
    """Result of the ast-grep structural extraction seam for one file.

    Attributes:
        summary: Short summary line for the page.
        symbols: Extracted symbol records.
        refs: Extracted unresolved references.
        imports: Raw import specifiers — same contract as
            :attr:`parrot.knowledge.wiki.languages.base.LanguageOutline.imports`,
            resolved later by :meth:`LanguageScanner.resolve_import`.
    """

    summary: str = ""
    symbols: list[SymbolRecord] = Field(default_factory=list)
    refs: list[SymbolRef] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str:
    """Build a ``sym:`` concept id.

    Args:
        rel_path: POSIX path relative to the repository root.
        qualname: Fully-qualified symbol name.
        ordinal: 1-based source-order occurrence of ``qualname`` within
            ``rel_path``. The first occurrence (``ordinal <= 1``) keeps
            the clean id; repeats get a ``~<ordinal>`` suffix.

    Returns:
        ``"sym:<rel_path>#<qualname>"`` for the first occurrence, or
        ``"sym:<rel_path>#<qualname>~<ordinal>"`` for repeats.
    """
    base = f"sym:{rel_path}#{qualname}"
    return base if ordinal <= 1 else f"{base}~{ordinal}"


def parse_sym_id(concept_id: str) -> tuple[str, str, int]:
    """Invert :func:`sym_concept_id`.

    Args:
        concept_id: A ``sym:<rel_path>#<qualname>[~<ordinal>]`` id.

    Returns:
        ``(rel_path, qualname, ordinal)`` — ``ordinal`` is ``1`` when no
        ``~<n>`` suffix is present.

    Raises:
        ValueError: If ``concept_id`` does not start with ``"sym:"`` or
            has no ``#`` separator.
    """
    if not concept_id.startswith("sym:"):
        raise ValueError(f"Not a sym: id: {concept_id!r}")
    body = concept_id[len("sym:"):]
    rel_path, sep, rest = body.partition("#")
    if not sep:
        raise ValueError(f"Missing '#' in sym: id: {concept_id!r}")
    ordinal = 1
    qualname = rest
    tail_sep_idx = rest.rfind("~")
    if tail_sep_idx != -1:
        candidate_ordinal = rest[tail_sep_idx + 1:]
        if candidate_ordinal.isdigit():
            qualname = rest[:tail_sep_idx]
            ordinal = int(candidate_ordinal)
    return rel_path, qualname, ordinal


def sha1_of_text(text: str) -> str:
    """Compute the SHA-1 hex digest of UTF-8 encoded ``text``.

    Same digest family as
    :meth:`parrot.knowledge.wiki.sources.SourceCollectionManager._compute_hash`,
    but computed in-memory over already-decoded text instead of a file
    path.

    Args:
        text: Text to hash.

    Returns:
        Lowercase hex SHA-1 digest.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()
