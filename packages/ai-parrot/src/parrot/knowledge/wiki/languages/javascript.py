"""JavaScript/TypeScript plugin for the wiki repo scanner.

A single scanner claims every JS/TS suffix (``.js``/``.jsx``/``.mjs``/
``.ts``/``.tsx``, FEAT-394) plus ``.svelte`` (FEAT-396): an API outline
(exported and non-exported classes, functions, consts, interfaces, type
aliases, with their JSDoc first line) via tree-sitter when the optional
``ai-parrot[wiki-languages]`` extra is installed, or a bounded,
line-anchored regex heuristic otherwise. Only **relative** import
specifiers (``./``, ``../``) are resolved — bare package names
(``react``, ``lodash``) are dropped at extraction time, never even
reaching :meth:`resolve_import`. Relative specifiers resolve via
extension guessing (``.ts``/``.tsx``/``.js``/``.jsx``/``.mjs``, then
``/index.*``); ``tsconfig.json`` path aliases are explicitly out of scope
for v1 (per spec).

Svelte components are handled by extraction, not by a separate scanner:
:func:`_extract_script_blocks` pulls the ``<script>`` bodies out before
parsing (the markup is not valid JS/TS and would break the tree), and the
grammar is chosen from the block's declared ``lang`` rather than the file
suffix. Only the ``<script>`` block is analysed — markup semantics
(component usage, ``{#if}``/``{#each}``, slots) are out of scope.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 240

# ---------------------------------------------------------------------------
# Heuristic patterns — line-anchored, bounded, no nested quantifiers (no
# catastrophic backtracking).
# ---------------------------------------------------------------------------

_RE_DOCBLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)

_RE_EXPORT_CLASS = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE
)
_RE_EXPORT_FUNCTION = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)
_RE_EXPORT_CONST = re.compile(
    r"^\s*export\s+(?:default\s+)?const\s+(\w+)", re.MULTILINE
)
_RE_EXPORT_INTERFACE = re.compile(
    r"^\s*export\s+(?:default\s+)?interface\s+(\w+)", re.MULTILINE
)
_RE_EXPORT_TYPE = re.compile(
    r"^\s*export\s+(?:default\s+)?type\s+(\w+)\s*=", re.MULTILINE
)
_RE_CLASS = re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
_RE_FUNCTION = re.compile(
    r"^\s*(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE
)

_RE_IMPORT_FROM = re.compile(
    # DOTALL so a multi-line `import {\n  a,\n  b,\n} from './x'` (common
    # Prettier/ESLint output) still matches — the lazy `.*?` before the
    # required `from` literal keeps this bounded, not catastrophic.
    r"""(?:import|export)\s+.*?\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE | re.DOTALL,
)
_RE_IMPORT_SIDE_EFFECT = re.compile(r"""import\s+['"]([^'"]+)['"]""", re.MULTILINE)
_RE_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)

#: Single-file-component suffix whose ``<script>`` block is JS/TS.
_SVELTE_SUFFIX = ".svelte"

#: A ``<script …>`` open tag's attribute text, then its body up to the
#: closing tag. Bounded like the patterns above: ``[^>]*`` cannot cross the
#: tag boundary and the lazy body is anchored by the required ``</script>``
#: literal, so there is no nested quantifier to backtrack on.
_RE_SVELTE_SCRIPT = re.compile(
    r"<script([^>]*)>(.*?)</script\s*>", re.DOTALL | re.IGNORECASE
)

#: The ``lang`` attribute within a ``<script>`` open tag, either quoting
#: style. The leading ``(?:^|\s)`` keeps it from matching a lookalike
#: attribute such as ``data-lang=``.
_RE_SCRIPT_LANG = re.compile(
    r"""(?:^|\s)lang\s*=\s*['"]([^'"]*)['"]""", re.IGNORECASE
)

#: ``lang`` values that select the TypeScript grammar.
_TYPESCRIPT_LANGS: frozenset[str] = frozenset({"ts", "typescript"})

#: The body of a ``kit.alias`` object literal in ``svelte.config.js``.
#: Scraped, never evaluated — the file is JavaScript. Bounded: the lazy
#: body is anchored by the required closing brace.
_RE_SVELTE_ALIAS_BLOCK = re.compile(r"\balias\s*:\s*\{(.*?)\}", re.DOTALL)

#: One ``key: 'value'`` entry inside that block, quoted or bare key.
_RE_ALIAS_ENTRY = re.compile(
    r"""['"]?([$@\w][$\w./*-]*)['"]?\s*:\s*['"]([^'"]+)['"]"""
)

#: Rendering label + start-of-line pattern for each exported construct
#: that has no distinct "params" group.
_EXPORT_SIMPLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("export const", _RE_EXPORT_CONST),
    ("export interface", _RE_EXPORT_INTERFACE),
    ("export type", _RE_EXPORT_TYPE),
)

_EXTENSION_CANDIDATES: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_INDEX_CANDIDATES: tuple[str, ...] = (
    "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
)


def _docblock_first_line(doc_body: str) -> str:
    """First non-empty line of a JSDoc block, ``*``-prefix stripped."""
    for raw in doc_body.splitlines():
        stripped = raw.strip().lstrip("*").strip()
        if stripped:
            return stripped[:_SUMMARY_MAX_CHARS]
    return ""


def _find_docblocks(source: str) -> list[tuple[int, int, str]]:
    """Every ``/** ... */`` block as ``(start, end, first_line)``, in order."""
    return [
        (m.start(), m.end(), _docblock_first_line(m.group(1)))
        for m in _RE_DOCBLOCK.finditer(source)
    ]


def _doc_for(docblocks: list[tuple[int, int, str]], decl_start: int) -> str:
    """JSDoc first line immediately (whitespace only) preceding ``decl_start``."""
    best = ""
    best_end = -1
    for _start, end, first_line in docblocks:
        if end <= decl_start and end > best_end:
            best_end = end
            best = first_line
    return best


def _extract_imports(source: str) -> list[str]:
    """Every raw import specifier, de-duplicated, in first-seen order.

    Non-relative specifiers used to be dropped here (FEAT-394). They now
    survive, because whether ``$lib/util`` is a repository alias or an
    external package is only decidable against the per-scan alias map,
    which does not exist at extraction time — this function sees one file
    and nothing else. Filtering therefore moved to
    :meth:`JavaScriptScanner.resolve_import`, which drops whatever it
    cannot resolve to a real file (FEAT-396).

    Args:
        source: Raw file content.

    Returns:
        Specifiers exactly as written, including bare package names.
    """
    specs: list[str] = []
    for pattern in (_RE_IMPORT_FROM, _RE_IMPORT_SIDE_EFFECT, _RE_REQUIRE):
        specs.extend(m.group(1) for m in pattern.finditer(source))
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in specs:
        if spec not in seen:
            seen.add(spec)
            ordered.append(spec)
    return ordered


def _extract_script_blocks(source: str, suffix: str) -> tuple[str, str | None]:
    """Split a single-file component into its script body and ``lang``.

    Only ``.svelte`` is treated as a component; every other suffix is
    returned unchanged so JS/TS behaviour is byte-identical to before this
    seam existed. Both the instance block and a ``<script module>`` /
    ``<script context="module">`` block are included, in document order,
    joined by a newline — the surrounding markup is dropped, since it is
    not valid JS/TS and would break the parse.

    A component with no ``<script>`` at all (markup only, or a
    self-closing ``<script />``) yields an empty body, which parses to an
    empty outline rather than raising.

    Args:
        source: Raw file content.
        suffix: The file's suffix, including the leading dot.

    Returns:
        ``(script_source, lang)``. ``lang`` is the declared language of
        the script blocks, lower-cased, or ``None`` when undeclared. When
        blocks disagree, a TypeScript declaration wins: the TS grammar
        also parses plain JS, so preferring it cannot lose symbols.
    """
    if suffix != _SVELTE_SUFFIX:
        return source, None

    bodies: list[str] = []
    langs: list[str] = []
    for match in _RE_SVELTE_SCRIPT.finditer(source):
        attributes, body = match.group(1), match.group(2)
        bodies.append(body)
        lang_match = _RE_SCRIPT_LANG.search(attributes)
        if lang_match is not None:
            declared = lang_match.group(1).strip().lower()
            if declared:
                langs.append(declared)

    lang: str | None = None
    for candidate in langs:
        if candidate in _TYPESCRIPT_LANGS:
            lang = candidate
            break
    else:
        lang = langs[0] if langs else None

    return "\n".join(bodies), lang


def _grammar_for(suffix: str, lang: str | None) -> str:
    """Pick the tree-sitter grammar name for one file.

    A ``.svelte`` suffix says nothing about the script block's language,
    so components are selected by their declared ``lang`` instead. Every
    other suffix keeps the original suffix-based rule.

    Args:
        suffix: The file's suffix, including the leading dot.
        lang: The ``lang`` returned by :func:`_extract_script_blocks`.

    Returns:
        ``"typescript"`` or ``"javascript"``.
    """
    if suffix == _SVELTE_SUFFIX:
        return "typescript" if lang in _TYPESCRIPT_LANGS else "javascript"
    return "typescript" if suffix in (".ts", ".tsx") else "javascript"


@dataclass(frozen=True)
class JsIndex:
    """Scanned file set plus the repository's import-alias prefix map.

    Replaces the bare ``frozenset[str]`` this scanner used to return. The
    alias map is a sorted tuple rather than a dict so longest-prefix
    matching is a plain ordered scan and the object stays hashable and
    immutable, exactly like the frozenset it supersedes.

    Attributes:
        files: Every scanned repository file, POSIX relative paths.
        aliases: ``(prefix, target)`` pairs such as
            ``("$lib/", "src/lib/")``, ordered longest prefix first. Both
            sides always end in ``/``, which is also what keeps Svelte 5
            runes (``$state``, ``$derived``) from ever matching.
    """

    files: frozenset[str]
    aliases: tuple[tuple[str, str], ...] = ()


def _as_prefix_pair(
    pattern: str, target: str, base_dir: str
) -> tuple[str, str] | None:
    """Normalize one ``paths``/``alias`` entry into a prefix pair.

    Handles both the wildcard form (``"$lib/*": "src/lib/*"``) and the
    bare form (``"$lib": "src/lib"``), producing a ``/``-terminated pair
    either way.

    Args:
        pattern: The alias as written (the map key).
        target: The repository-relative destination (the map value).
        base_dir: Directory the target is relative to, ``""`` for root.

    Returns:
        The ``(prefix, target)`` pair, or ``None`` when either side is
        unusable.
    """
    prefix = pattern[:-1] if pattern.endswith("/*") else pattern
    tail = target[:-1] if target.endswith("/*") else target
    prefix = prefix.rstrip("/")
    tail = tail.rstrip("/")
    if not prefix or not tail:
        return None
    joined = f"{base_dir}/{tail}" if base_dir else tail
    resolved = _normalize_posix(PurePosixPath(joined))
    if not resolved:
        return None
    return f"{prefix}/", f"{resolved}/"


def _aliases_from_tsconfig(data: Any, config_rel: str) -> list[tuple[str, str]]:
    """Prefix pairs from a tsconfig/jsconfig ``compilerOptions.paths`` map.

    ``paths`` entries are relative to ``baseUrl``, which is itself
    relative to the config file's own directory.

    Args:
        data: Parsed config document.
        config_rel: POSIX relative path of the config file.

    Returns:
        The prefix pairs found, possibly empty.
    """
    if not isinstance(data, dict):
        return []
    compiler = data.get("compilerOptions")
    if not isinstance(compiler, dict):
        return []
    paths = compiler.get("paths")
    if not isinstance(paths, dict) or not paths:
        return []
    base_url = compiler.get("baseUrl")
    base_url = base_url if isinstance(base_url, str) else "."
    config_dir = PurePosixPath(config_rel).parent
    base_dir = _normalize_posix(config_dir / base_url)

    pairs: list[tuple[str, str]] = []
    for pattern, targets in paths.items():
        if not isinstance(pattern, str):
            continue
        target = None
        if isinstance(targets, list) and targets:
            target = targets[0]
        elif isinstance(targets, str):
            target = targets
        if not isinstance(target, str):
            continue
        pair = _as_prefix_pair(pattern, target, base_dir)
        if pair is not None:
            pairs.append(pair)
    return pairs


def _aliases_from_svelte_config(text: str, config_rel: str) -> list[tuple[str, str]]:
    """Prefix pairs scraped from a ``svelte.config.js`` ``kit.alias`` block.

    The file is JavaScript, so it is **scraped, never evaluated**. A
    config that computes its aliases dynamically simply yields nothing
    here and falls through to the later discovery steps.

    Args:
        text: Raw file content.
        config_rel: POSIX relative path of the config file.

    Returns:
        The prefix pairs found, possibly empty.
    """
    block = _RE_SVELTE_ALIAS_BLOCK.search(text)
    if block is None:
        return []
    base_dir = _normalize_posix(PurePosixPath(config_rel).parent)
    pairs: list[tuple[str, str]] = []
    for match in _RE_ALIAS_ENTRY.finditer(block.group(1)):
        pair = _as_prefix_pair(match.group(1), match.group(2), base_dir)
        if pair is not None:
            pairs.append(pair)
    return pairs


def _discover_aliases(file_set: frozenset[str]) -> tuple[tuple[str, str], ...]:
    """Read the repository's import aliases once, for a whole scan.

    Discovery order, first declaration of a prefix winning:

    1. ``svelte.config.js`` — an explicit ``kit.alias`` block.
    2. ``tsconfig.json`` / ``jsconfig.json`` — ``compilerOptions.paths``.
    3. SvelteKit convention — ``$lib/`` maps to ``src/lib/`` whenever a
       ``svelte.config.js`` exists at the repository root.

    Step 3 is the common case, not a nicety: SvelteKit's own ``$lib``
    declaration lives in the **generated, gitignored**
    ``.svelte-kit/tsconfig.json``, and the committed ``tsconfig.json``
    merely extends it — so a fresh clone declares no alias anywhere.

    Args:
        file_set: Every scanned repository path. ``build_reference_index``
            receives all of them, not only this scanner's, so the config
            files are visible here even though ``.js``/``.json`` belong to
            other categories.

    Returns:
        ``(prefix, target)`` pairs ordered longest prefix first.
    """
    # Local import: the package __init__ imports this module during its
    # own initialization, so a module-level import of a sibling name from
    # it would be circular. By call time, package init has long finished.
    from parrot.knowledge.wiki.languages import get_scan_root

    scan_root = get_scan_root()

    def _read(rel: str) -> str | None:
        path = (scan_root / rel) if scan_root is not None else Path(rel)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not read %s: %s", rel, exc)
            return None

    pairs: list[tuple[str, str]] = []
    svelte_configs = [
        rel for rel in sorted(file_set)
        if PurePosixPath(rel).name == "svelte.config.js"
    ]

    for rel in svelte_configs:
        text = _read(rel)
        if text is not None:
            pairs.extend(_aliases_from_svelte_config(text, rel))

    for rel in sorted(file_set):
        if PurePosixPath(rel).name not in ("tsconfig.json", "jsconfig.json"):
            continue
        text = _read(rel)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError as exc:
            # Real tsconfig files legally contain comments and trailing
            # commas, which stdlib json rejects. Degrade to the next
            # source rather than failing the scan.
            logger.debug("Could not parse %s: %s", rel, exc)
            continue
        pairs.extend(_aliases_from_tsconfig(data, rel))

    for rel in svelte_configs:
        config_dir = _normalize_posix(PurePosixPath(rel).parent)
        target = f"{config_dir}/src/lib/" if config_dir else "src/lib/"
        pairs.append(("$lib/", target))

    deduped: dict[str, str] = {}
    for prefix, target in pairs:
        deduped.setdefault(prefix, target)
    return tuple(
        sorted(deduped.items(), key=lambda pair: len(pair[0]), reverse=True)
    )


def _normalize_posix(path: PurePosixPath) -> str:
    """Collapse ``.``/``..`` segments in a (possibly non-existent) path."""
    parts: list[str] = []
    for part in path.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part in (".", ""):
            continue
        else:
            parts.append(part)
    return "/".join(parts)


class JavaScriptScanner(LanguageScanner):
    """Deep extractor for JavaScript/TypeScript files."""

    name: ClassVar[str] = "javascript"
    #: ``.svelte`` rides along (FEAT-396): a component's ``<script>`` block
    #: is JS/TS, so it is extracted and parsed here rather than by a
    #: separate framework scanner. ``_SUFFIX_INDEX`` derives the routing.
    suffixes: ClassVar[frozenset[str]] = frozenset(
        {".js", ".jsx", ".mjs", ".ts", ".tsx", ".svelte"}
    )

    # -- outline ------------------------------------------------------------

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and raw imports from JS/TS source.

        Args:
            source: Raw JS/TS source text.
            rel_path: POSIX-style path relative to the repository root
                (unused by this scanner — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`. Any extraction
            failure degrades to an empty outline rather than raising.
        """
        try:
            # Imports come from the RAW source: the extractor already
            # works on Svelte markup, and reading them here keeps
            # non-component files byte-identical to the pre-seam
            # behaviour.
            imports = _extract_imports(source)
            suffix = PurePosixPath(rel_path).suffix
            script_source, lang = _extract_script_blocks(source, suffix)
            language = _grammar_for(suffix, lang)
            parser = treesitter.get_parser(language)
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, script_source)
            else:
                summary, lines = self._outline_heuristic(script_source)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("JS/TS outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

    def _outline_heuristic(self, source: str) -> tuple[str, list[str]]:
        """Bounded regex extraction — the fallback when tree-sitter is
        unavailable."""
        docblocks = _find_docblocks(source)
        entries: list[tuple[int, str]] = []

        for match in _RE_EXPORT_CLASS.finditer(source):
            doc = _doc_for(docblocks, match.start())
            entries.append(
                (match.start(), f"export class {match.group(1)}: {doc}".rstrip(": "))
            )
        for match in _RE_CLASS.finditer(source):
            doc = _doc_for(docblocks, match.start())
            entries.append(
                (match.start(), f"class {match.group(1)}: {doc}".rstrip(": "))
            )
        for match in _RE_EXPORT_FUNCTION.finditer(source):
            doc = _doc_for(docblocks, match.start())
            params = match.group(2).strip()
            entries.append((
                match.start(),
                f"export function {match.group(1)}({params}): {doc}".rstrip(": "),
            ))
        for match in _RE_FUNCTION.finditer(source):
            doc = _doc_for(docblocks, match.start())
            params = match.group(2).strip()
            entries.append((
                match.start(),
                f"function {match.group(1)}({params}): {doc}".rstrip(": "),
            ))
        for label, pattern in _EXPORT_SIMPLE_PATTERNS:
            for match in pattern.finditer(source):
                doc = _doc_for(docblocks, match.start())
                entries.append(
                    (match.start(), f"{label} {match.group(1)}: {doc}".rstrip(": "))
                )

        entries.sort(key=lambda e: e[0])
        lines = [line for _pos, line in entries]

        first_pos = min((pos for pos, _line in entries), default=len(source))
        summary = ""
        if docblocks and docblocks[0][0] < first_pos:
            summary = docblocks[0][2]
        return summary, lines

    def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]:
        """Best-effort tree-sitter outline using the JS/TS grammar's node
        types. Exercised only when the optional
        ``ai-parrot[wiki-languages]`` extra is installed; any structural
        mismatch degrades to an empty outline via the caller's
        ``except Exception`` guard rather than raising.
        """
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
        source_bytes = source.encode("utf-8")
        lines: list[str] = []

        def _text(node: Any) -> str:
            return source_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="replace"
            )

        def _name_of(node: Any) -> str:
            name_node = node.child_by_field_name("name")
            return _text(name_node) if name_node is not None else ""

        def _leading_doc(node: Any) -> str:
            prev = node.prev_sibling
            if prev is not None and prev.type == "comment":
                text = _text(prev)
                if text.startswith("/**"):
                    body = text[3:-2] if text.endswith("*/") else text[3:]
                    return _docblock_first_line(body)
            return ""

        exportable_types = {
            "class_declaration": "class",
            "function_declaration": "function",
            "interface_declaration": "interface",
            "type_alias_declaration": "type",
        }

        def _is_exported(node: Any) -> bool:
            parent = node.parent
            return parent is not None and parent.type == "export_statement"

        def _walk(node: Any) -> None:
            for child in node.children:
                kind = exportable_types.get(child.type)
                if kind is not None:
                    name = _name_of(child)
                    doc = _leading_doc(child) or _leading_doc(
                        child.parent if _is_exported(child) else child
                    )
                    prefix = "export " if _is_exported(child) else ""
                    lines.append(f"{prefix}{kind} {name}: {doc}".rstrip(": "))
                elif child.type == "lexical_declaration":
                    # `export const NAME = ...` / `const NAME = ...`
                    for decl in child.named_children:
                        name_node = decl.child_by_field_name("name")
                        if name_node is None:
                            continue
                        name = _text(name_node)
                        doc = _leading_doc(child)
                        prefix = "export " if _is_exported(child) else ""
                        lines.append(f"{prefix}const {name}: {doc}".rstrip(": "))
                _walk(child)

        _walk(root)

        summary = ""
        first_child = root.children[0] if root.children else None
        if first_child is not None and first_child.type == "comment":
            text = _text(first_child)
            if text.startswith("/**"):
                body = text[3:-2] if text.endswith("*/") else text[3:]
                summary = _docblock_first_line(body)
        return summary, lines

    # -- reference resolution -------------------------------------------------

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build the repo file set plus its import-alias map.

        Alias configuration is read here — **once per scan** — rather
        than per file: this method is called a single time per scanner
        per scan, over every scanned path.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            An opaque :class:`JsIndex`.
        """
        files = frozenset(PurePosixPath(p).as_posix() for p in rel_paths)
        return JsIndex(files=files, aliases=_discover_aliases(files))

    def _guess_target(self, base_str: str, file_set: frozenset[str]) -> str | None:
        """Match a extension-less repo path against the scanned files.

        Tries the path as written, then each known extension, then each
        ``index.*`` file inside it.

        Args:
            base_str: Normalized, repository-relative path without a
                guaranteed extension.
            file_set: Every scanned repository path.

        Returns:
            The matching path, or ``None``.
        """
        if not base_str:
            return None
        if base_str in file_set:
            return base_str
        for ext in _EXTENSION_CANDIDATES:
            candidate = base_str + ext
            if candidate in file_set:
                return candidate
        for idx in _INDEX_CANDIDATES:
            candidate = f"{base_str}/{idx}"
            if candidate in file_set:
                return candidate
        return None

    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> str | None:
        """Resolve one import specifier to a repository file.

        Relative specifiers (``./x``, ``../x``) resolve against the
        importing file's directory. Non-relative ones are matched against
        the repository's alias map, longest prefix first; anything left
        over — an npm package, or a SvelteKit virtual module such as
        ``$app/environment`` — has no file here and yields ``None``, so
        the edge is dropped rather than left dangling.

        Args:
            spec: A raw import specifier.
            from_file: POSIX-relative path of the importing file.
            index: The :class:`JsIndex` from :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved.
        """
        if isinstance(index, JsIndex):
            file_set, aliases = index.files, index.aliases
        else:  # tolerate the pre-FEAT-396 bare frozenset
            file_set, aliases = index, ()

        if spec.startswith("."):
            base = PurePosixPath(from_file).parent / spec
            return self._guess_target(_normalize_posix(base), file_set)

        for prefix, target in aliases:
            if spec.startswith(prefix):
                expanded = target + spec[len(prefix):]
                return self._guess_target(
                    _normalize_posix(PurePosixPath(expanded)), file_set
                )
        return None

    @property
    def mode(self) -> str:
        """``"tree-sitter"`` only when **both** selectable grammars load.

        This scanner picks between the TypeScript and JavaScript grammars
        per file, so reporting ``"tree-sitter"`` while either one is
        missing overstates what the outlines are worth: the files routed
        to the absent grammar silently took the regex path. Requiring both
        was the correction made in FEAT-396 — until then the check was an
        ``or``, and since the JavaScript grammar always loaded, TypeScript
        and Svelte files were reported as tree-sitter while being parsed
        by regex.
        """
        if (
            treesitter.get_parser("typescript") is not None
            and treesitter.get_parser("javascript") is not None
        ):
            return "tree-sitter"
        return "heuristic"
