"""Byte-parity ``## API outline`` projection from structural symbols.

:func:`render_outline` turns the symbols the ast-grep seam extracted
(:mod:`parrot.knowledge.wiki.languages.astgrep`) back into the exact
``outline`` lines each language's tree-sitter walker already emits, so
switching a scanner onto the seam changes *nothing* about the rendered
page — only ``symbols``/``refs`` gain new, additive data.

The walkers are the oracle: every string here is copied verbatim from
the corresponding emit site (see the module docstring of each renderer
function for its source), never "improved" or normalised. Symbols the
walkers never rendered (JS/TS class methods, PHP namespaces, anything
past the depth a walker shows) are silently skipped.

Convention (this feature only — no existing code depends on it):
:attr:`~parrot.knowledge.wiki.symbols.SymbolRecord.signature` holds the
raw parameter list **without** surrounding parentheses, mirroring every
walker's own ``params = <node text>.strip("()")`` step; renderers that
need parentheses add them back explicitly.
"""

from __future__ import annotations

from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord

#: Process-wide kill switch for the ast-grep structural backend, bound to
#: ``WikiProjectConfig.structural_backend`` by the scan entry point.
#: ``LanguageScanner.outline(source, rel_path)`` is a frozen two-argument
#: signature (TASK-2010) with no room for a config parameter, so scanners
#: read this module-level flag instead — the same pattern
#: ``languages/__init__.py`` uses for ``set_scan_root``/``get_scan_root``.
_structural_enabled: bool = True


def set_structural_enabled(enabled: bool) -> None:
    """Enable or disable the ast-grep structural seam for every scanner.

    Args:
        enabled: New value, normally ``WikiProjectConfig.structural_backend``.
    """
    global _structural_enabled
    _structural_enabled = enabled


def structural_enabled() -> bool:
    """Return whether scanners should try the ast-grep seam first.

    Returns:
        ``True`` by default; ``False`` after :func:`set_structural_enabled`
        was called with ``False`` (the config kill switch).
    """
    return _structural_enabled


def render_outline(symbols: list[SymbolRecord], language: str) -> list[str]:
    """Project ``symbols`` into today's ``## API outline`` lines.

    Args:
        symbols: Symbols extracted for one file, in any order.
        language: Scanner name (``"php"``, ``"rust"``, ``"javascript"``,
            ``"typescript"``, ``"perl"``). Unknown languages render no
            lines.

    Returns:
        Rendered outline lines, in source order (ascending
        ``start_byte``), byte-identical to the corresponding tree-sitter
        walker's own output.
    """
    ordered = sorted(symbols, key=lambda s: s.start_byte)
    renderer = _RENDERERS.get(language)
    if renderer is None:
        return []
    return renderer(ordered)


def _render_php(symbols: list[SymbolRecord]) -> list[str]:
    """Mirrors ``php.py`` lines 291/299/301."""
    lines: list[str] = []
    for sym in symbols:
        if sym.kind in (SymbolKind.CLASS, SymbolKind.INTERFACE, SymbolKind.TRAIT, SymbolKind.ENUM):
            lines.append(f"{sym.kind.value} {sym.name}: {sym.doc}".rstrip(": "))
        elif sym.kind == SymbolKind.METHOD:
            lines.append(f"    def {sym.name}({sym.signature}): {sym.doc}".rstrip(": "))
        elif sym.kind == SymbolKind.FUNCTION:
            lines.append(f"function {sym.name}({sym.signature}): {sym.doc}".rstrip(": "))
    return lines


def _render_rust(symbols: list[SymbolRecord]) -> list[str]:
    """Mirrors ``rust.py`` lines 293/295/300/304/308."""
    lines: list[str] = []
    for sym in symbols:
        if sym.kind in (SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.TRAIT):
            if sym.exported:
                lines.append(f"pub {sym.kind.value} {sym.name}: {sym.doc}".rstrip(": "))
        elif sym.kind == SymbolKind.MOD:
            if sym.exported:
                lines.append(f"pub mod {sym.name}")
        elif sym.kind == SymbolKind.IMPL:
            lines.append(f"impl {sym.name}:")
        elif sym.kind == SymbolKind.FUNCTION:
            sig = f"pub fn {sym.name}({sym.signature})"
            if sym.parent is not None:
                lines.append(f"    {sig}: {sym.doc}".rstrip(": "))
            elif sym.exported:
                lines.append(f"{sig}: {sym.doc}".rstrip(": "))
    return lines


#: JS/TS kinds the walker renders regardless of nesting depth (methods are
#: extracted as symbols but never rendered — javascript.py:612-616).
_JS_RENDERED_KINDS = frozenset(
    {SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.INTERFACE, SymbolKind.TYPE, SymbolKind.CONST}
)


def _render_javascript(symbols: list[SymbolRecord]) -> list[str]:
    """Mirrors ``javascript.py`` lines 632/642."""
    lines: list[str] = []
    for sym in symbols:
        if sym.kind not in _JS_RENDERED_KINDS:
            continue
        prefix = "export " if sym.exported else ""
        keyword = "const" if sym.kind == SymbolKind.CONST else sym.kind.value
        lines.append(f"{prefix}{keyword} {sym.name}: {sym.doc}".rstrip(": "))
    return lines


def _render_perl(symbols: list[SymbolRecord]) -> list[str]:
    """Mirrors ``perl.py`` lines 380/389/396/406/412/416/421."""
    lines: list[str] = []
    for sym in symbols:
        if sym.kind == SymbolKind.PACKAGE:
            lines.append(f"package {sym.name}")
        elif sym.kind == SymbolKind.CLASS:
            lines.append(f"class {sym.name}: {sym.doc}".rstrip(": "))
        elif sym.kind == SymbolKind.ROLE:
            lines.append(f"role {sym.name}: {sym.doc}".rstrip(": "))
        elif sym.kind == SymbolKind.FUNCTION:
            sig = f"sub {sym.name}({sym.signature})"
            line = f"{sig}: {sym.doc}".rstrip(": ")
            lines.append(f"    {line}" if sym.parent is not None else line)
        elif sym.kind == SymbolKind.METHOD:
            sig = f"method {sym.name}({sym.signature})"
            lines.append(f"    {sig}: {sym.doc}".rstrip(": "))
        elif sym.kind == SymbolKind.FIELD:
            lines.append(f"    field {sym.name}")
        elif sym.kind == SymbolKind.ATTRIBUTE:
            line = f"    has {sym.name}"
            if sym.signature:
                line = f"{line}: {sym.signature}"
            lines.append(line)
    return lines


_RENDERERS = {
    "php": _render_php,
    "rust": _render_rust,
    "javascript": _render_javascript,
    "typescript": _render_javascript,
    "tsx": _render_javascript,
    "perl": _render_perl,
}
