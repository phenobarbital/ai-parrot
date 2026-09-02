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
from typing import Any

from pydantic import BaseModel, Field

#: Max length of the source excerpt embedded in a ``sym:`` page body
#: (spec §7 "sym: page body").
_SOURCE_EXCERPT_MAX_CHARS = 2000

#: Section header separating the doc from the source excerpt in a
#: ``sym:`` page body (see :func:`symbol_to_page_fields`).
_SOURCE_HEADING = "## Source (excerpt)"


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


def symbol_to_page_fields(record: SymbolRecord, *, source_excerpt: str = "") -> dict[str, str]:
    """Build the ``sym:`` page's ``title``/``summary``/``body`` fields.

    Used by the ingest pipeline (``repo_scan.build_symbol_pages``,
    TASK-2748) to construct the :class:`~parrot.knowledge.wiki.store.WikiPageRecord`
    for one symbol, and by the page-based default store methods
    (:func:`symbol_from_page`) to decode it back.

    The body's structure (spec §7 "sym: page body") is a fixed sequence
    of ``"\\n\\n"``-separated sections in this exact order — kept stable
    on purpose so :func:`symbol_from_page` can invert it positionally
    rather than by fragile regex matching of the rendered markdown:

    0. ``# <qualname>``
    1. ``**kind** <kind> · **language** <language> · **file**
       <rel>:L<start>-<end> · **exported** <bool>``
    2. ``<signature>`` (may be empty)
    3. ``<doc>`` (may be empty)
    4. ``## Source (excerpt)``
    5. ``<source excerpt, capped at 2000 chars>``

    Args:
        record: Symbol to render.
        source_excerpt: Raw source text of the symbol's node; capped and
            appended as the trailing "Source (excerpt)" section. Empty
            when the caller does not have (or want to store) source text.

    Returns:
        ``{"title": qualname, "summary": doc, "body": <rendered body>}``.
    """
    excerpt = source_excerpt[:_SOURCE_EXCERPT_MAX_CHARS]
    body = "\n\n".join(
        [
            f"# {record.qualname}",
            (
                f"**kind** {record.kind.value} · **language** {record.language} · "
                f"**file** {record.rel_path}:L{record.start_line}-{record.end_line} · "
                f"**exported** {record.exported}"
            ),
            record.signature,
            record.doc,
            _SOURCE_HEADING,
            excerpt,
        ]
    )
    return {"title": record.qualname, "summary": record.doc, "body": body}


def symbol_from_page(page: dict[str, Any]) -> SymbolRecord | None:
    """Decode a ``sym:`` page dict back into a :class:`SymbolRecord`.

    Best-effort inverse of :func:`symbol_to_page_fields`, used by the
    page-based default implementations of ``symbols_for``/
    ``find_symbols``/``search_symbols_fts`` (ArangoDB, InMemory — SQLite
    answers from its native ``symbols`` table instead). Fields the
    rendered markdown does not carry precisely (``start_byte``,
    ``end_byte``, ``is_async``, ``decorators``, ``node_kind``, ``depth``)
    degrade to their model defaults rather than raising — this is the
    intentionally-lossy path; only SQLite's native table is full-fidelity.

    Args:
        page: A page dict as returned by ``get_page``/``list_pages`` for
            a ``category == "symbol"`` row (``node_id`` holds ``rel_path``,
            ``title`` holds ``qualname``, ``summary`` holds ``doc``).

    Returns:
        A reconstructed :class:`SymbolRecord`, or ``None`` when ``page``
        is not a well-formed ``sym:`` page (wrong category, or a body
        that does not match the expected section layout).
    """
    if page.get("category") != "symbol":
        return None
    concept_id = page.get("concept_id") or ""
    try:
        rel_path, qualname, _ordinal = parse_sym_id(concept_id)
    except ValueError:
        return None
    rel_path = page.get("node_id") or rel_path
    qualname = page.get("title") or qualname
    doc = page.get("summary") or ""

    body = page.get("body") or ""
    sections = body.split("\n\n")
    if len(sections) < 3:
        return None
    header = sections[1]
    signature = sections[2] if len(sections) > 2 else ""
    kind_value = "function"
    language = ""
    start_line = 1
    end_line = 1
    exported = False
    for part in header.split(" · "):
        part = part.strip()
        if part.startswith("**kind**"):
            kind_value = part.removeprefix("**kind**").strip()
        elif part.startswith("**language**"):
            language = part.removeprefix("**language**").strip()
        elif part.startswith("**file**"):
            location = part.removeprefix("**file**").strip()
            _path, _, line_range = location.rpartition(":L")
            start_str, _, end_str = line_range.partition("-")
            start_line = int(start_str) if start_str.isdigit() else 1
            end_line = int(end_str) if end_str.isdigit() else start_line
        elif part.startswith("**exported**"):
            exported = part.removeprefix("**exported**").strip() == "True"

    try:
        kind = SymbolKind(kind_value)
    except ValueError:
        kind = SymbolKind.FUNCTION

    name = qualname.rsplit(".", 1)[-1].rsplit("::", 1)[-1]
    parent = None
    if "." in qualname:
        parent = qualname.rsplit(".", 1)[0]
    elif "::" in qualname:
        parent = qualname.rsplit("::", 1)[0]

    return SymbolRecord(
        rel_path=rel_path,
        language=language,
        kind=kind,
        name=name,
        qualname=qualname,
        parent=parent,
        signature=signature,
        doc=doc,
        exported=exported,
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=0,
        content_hash=page.get("content_hash") or "",
    )


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
