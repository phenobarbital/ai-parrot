"""Perl plugin for the wiki repo scanner.

Deep extractor for ``.pl``/``.pm``/``.t`` files (FEAT-432): an API outline
(``package``/``class``/``role`` containers, ``sub``/``method`` with their
signature and doc, Moose/Moo ``has`` attributes, and Corinna ``field``
declarations) via tree-sitter when the optional
``ai-parrot[wiki-languages]`` extra is installed, or a bounded,
line-anchored regex heuristic otherwise. Import extraction
(``use``/``require``/``use parent``/``use base``) is regex-based in both
modes. Reference resolution follows Perl's standard convention:
``Module::Name`` resolves to ``lib/Module/Name.pm`` (or any other
``lib/``-rooted directory in the repo tree); ``require "./lib.pl"`` style
paths resolve relative to the importing file's directory.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar

from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 240

# ---------------------------------------------------------------------------
# Heuristic patterns — line-anchored, bounded, no nested quantifiers (no
# catastrophic backtracking).
# ---------------------------------------------------------------------------

_RE_PACKAGE = re.compile(r"^\s*package\s+(\w+(?:::\w+)*)\s*[;{]", re.MULTILINE)
_RE_CLASS = re.compile(r"^\s*class\s+(\w+(?:::\w+)*)\b", re.MULTILINE)
_RE_ROLE = re.compile(r"^\s*role\s+(\w+(?:::\w+)*)\b", re.MULTILINE)
_RE_SUB = re.compile(r"^\s*sub\s+(\w+)\s*(?:\(([^)]*)\))?\s*\{", re.MULTILINE)
_RE_METHOD = re.compile(r"^\s*method\s+(\w+)\s*(?:\(([^)]*)\))?\s*\{", re.MULTILINE)
_RE_FIELD = re.compile(r"^\s*field\s+([$@%]\w+)", re.MULTILINE)
_RE_HAS = re.compile(r"^\s*has\s+['\"]?(\w+)['\"]?\s*=>", re.MULTILINE)
_RE_ISA = re.compile(r"\bisa\s*=>\s*['\"]([\w:]+)['\"]")
_RE_MY_ARGS = re.compile(r"\bmy\s*\(([^)]*)\)\s*=\s*@_")

_RE_HEAD1_NAME = re.compile(r"^=head1[ \t]+NAME[ \t]*\n", re.MULTILINE)
_RE_HEAD1_DESCRIPTION = re.compile(r"^=head1[ \t]+DESCRIPTION[ \t]*\n", re.MULTILINE)
_RE_HEAD2 = re.compile(r"^=head2[ \t]+(\w+)[ \t]*\n", re.MULTILINE)
_RE_POD_COMMAND = re.compile(r"^=\w", re.MULTILINE)

_RE_USE_PARENT_BASE = re.compile(
    r"^\s*use\s+(?:parent|base)\s+(?:-\w+\s*,\s*)?"
    r"(?:qw\s*\(([^)]*)\)|['\"]([\w:]+)['\"])",
    re.MULTILINE,
)
_RE_USE_MODULE = re.compile(r"^\s*use\s+(\w+(?:::\w+)*)\b", re.MULTILINE)
_RE_REQUIRE_MODULE = re.compile(r"^\s*require\s+(\w+(?:::\w+)*)\s*;", re.MULTILINE)
_RE_REQUIRE_PATH = re.compile(r"^\s*require\s+['\"]([^'\"]+)['\"]\s*;", re.MULTILINE)

#: Directory name convention used to identify Perl library roots.
_LIB_DIR_NAME = "lib"


def _pod_block(source: str, heading_re: re.Pattern[str]) -> str:
    """First paragraph following the first match of ``heading_re``, or ``""``."""
    match = heading_re.search(source)
    if match is None:
        return ""
    start = match.end()
    next_command = _RE_POD_COMMAND.search(source, start)
    end = next_command.start() if next_command is not None else len(source)
    block = source[start:end].strip()
    if not block:
        return ""
    first_paragraph = block.split("\n\n", 1)[0].strip()
    return " ".join(first_paragraph.split())[:_SUMMARY_MAX_CHARS]


def _pod_summary(source: str) -> str:
    """POD summary: first ``=head1 NAME`` paragraph, else ``=head1 DESCRIPTION``."""
    summary = _pod_block(source, _RE_HEAD1_NAME)
    if summary:
        return summary
    return _pod_block(source, _RE_HEAD1_DESCRIPTION)


def _head2_docs(source: str) -> dict[str, str]:
    """Map of ``name -> first paragraph`` for every ``=head2 name`` block."""
    docs: dict[str, str] = {}
    for match in _RE_HEAD2.finditer(source):
        start = match.end()
        next_command = _RE_POD_COMMAND.search(source, start)
        end = next_command.start() if next_command is not None else len(source)
        block = source[start:end].strip()
        if not block:
            continue
        first_paragraph = block.split("\n\n", 1)[0].strip()
        if first_paragraph:
            docs[match.group(1)] = " ".join(first_paragraph.split())[:_SUMMARY_MAX_CHARS]
    return docs


def _preceding_comment(source: str, pos: int) -> str:
    """Text of a ``#`` comment on the line immediately preceding ``pos``."""
    line_start = source.rfind("\n", 0, pos) + 1
    prev_line_end = line_start - 1
    if prev_line_end < 0:
        return ""
    prev_line_start = source.rfind("\n", 0, prev_line_end) + 1
    prev_line = source[prev_line_start:prev_line_end].strip()
    if prev_line.startswith("#"):
        return prev_line.lstrip("#").strip()[:_SUMMARY_MAX_CHARS]
    return ""


def _doc_for(source: str, head2_docs: dict[str, str], name: str, pos: int) -> str:
    """Doc for a declaration: preceding ``#`` comment, else a matching ``=head2``."""
    doc = _preceding_comment(source, pos)
    if doc:
        return doc
    return head2_docs.get(name, "")


def _sub_params(source: str, match: re.Match[str]) -> str:
    """Signature params, or the ``my ($self, ...) = @_;`` unpack fallback."""
    signature = match.group(2)
    if signature is not None:
        return signature.strip()
    window = source[match.end():match.end() + 400]
    unpack = _RE_MY_ARGS.search(window)
    return unpack.group(1).strip() if unpack else ""


def _extract_perl_imports(source: str) -> list[str]:
    """Raw ``use``/``require``/``use parent``/``use base`` specifiers, in order."""
    imports: list[str] = []
    consumed_spans: list[tuple[int, int]] = []
    for match in _RE_USE_PARENT_BASE.finditer(source):
        qw_list, single = match.group(1), match.group(2)
        if qw_list:
            for name in qw_list.split():
                name = name.strip()
                if name:
                    imports.append(name)
        elif single:
            imports.append(single)
        consumed_spans.append((match.start(), match.end()))
    for match in _RE_USE_MODULE.finditer(source):
        if any(start <= match.start() < end for start, end in consumed_spans):
            continue
        imports.append(match.group(1))
    for match in _RE_REQUIRE_MODULE.finditer(source):
        imports.append(match.group(1))
    for match in _RE_REQUIRE_PATH.finditer(source):
        imports.append(f"require:{match.group(1)}")
    return imports


class PerlScanner(LanguageScanner):
    """Deep extractor for ``.pl``/``.pm``/``.t`` files."""

    name: ClassVar[str] = "perl"
    suffixes: ClassVar[frozenset[str]] = frozenset({".pl", ".pm", ".t"})

    # -- outline ------------------------------------------------------------

    def outline(self, source: str, rel_path: str) -> LanguageOutline:
        """Extract summary, API outline, and raw imports from Perl source.

        Args:
            source: Raw Perl source text.
            rel_path: POSIX-style path relative to the repository root
                (unused by this scanner — kept for interface parity).

        Returns:
            The extracted :class:`LanguageOutline`. Any extraction
            failure degrades to an empty outline rather than raising.
        """
        try:
            imports = _extract_perl_imports(source)
            parser = treesitter.get_parser("perl")
            if parser is not None:
                summary, lines = self._outline_treesitter(parser, source)
            else:
                summary, lines = self._outline_heuristic(source)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            logger.debug("Perl outline extraction failed on %s: %s", rel_path, exc)
            return LanguageOutline()
        return LanguageOutline(summary=summary, outline=lines, imports=imports)

    def _outline_heuristic(self, source: str) -> tuple[str, list[str]]:
        """Bounded regex extraction — the fallback when tree-sitter is
        unavailable."""
        head2_docs = _head2_docs(source)

        containers: list[tuple[int, str, str]] = []  # pos, label, name
        for match in _RE_PACKAGE.finditer(source):
            containers.append((match.start(), "package", match.group(1)))
        for match in _RE_CLASS.finditer(source):
            containers.append((match.start(), "class", match.group(1)))
        for match in _RE_ROLE.finditer(source):
            containers.append((match.start(), "role", match.group(1)))
        containers.sort(key=lambda c: c[0])

        entries: list[tuple[int, str]] = []
        for pos, label, cname in containers:
            doc = _doc_for(source, head2_docs, cname, pos)
            entries.append((pos, f"{label} {cname}: {doc}".rstrip(": ")))

        for match in _RE_SUB.finditer(source):
            pos, name = match.start(), match.group(1)
            params = _sub_params(source, match)
            doc = _doc_for(source, head2_docs, name, pos)
            owner = self._owner_before(containers, pos)
            sig = f"sub {name}({params})"
            line = f"{sig}: {doc}".rstrip(": ")
            entries.append((pos, f"    {line}" if owner is not None else line))

        for match in _RE_METHOD.finditer(source):
            pos, name = match.start(), match.group(1)
            params = _sub_params(source, match)
            doc = _doc_for(source, head2_docs, name, pos)
            sig = f"method {name}({params})"
            line = f"{sig}: {doc}".rstrip(": ")
            entries.append((pos, f"    {line}"))

        for match in _RE_FIELD.finditer(source):
            pos = match.start()
            entries.append((pos, f"    field {match.group(1)}"))

        for match in _RE_HAS.finditer(source):
            pos, attr_name = match.start(), match.group(1)
            window_end = source.find(";", match.end())
            window = source[match.end():window_end if window_end != -1 else len(source)]
            isa_match = _RE_ISA.search(window)
            line = f"    has {attr_name}"
            if isa_match:
                line = f"{line}: {isa_match.group(1)}"
            entries.append((pos, line))

        entries.sort(key=lambda e: e[0])
        lines = [line for _pos, line in entries]

        summary = _pod_summary(source)
        return summary, lines

    @staticmethod
    def _owner_before(
        containers: list[tuple[int, str, str]], pos: int
    ) -> str | None:
        """Name of the nearest ``package``/``class``/``role`` before ``pos``."""
        owner: str | None = None
        for cpos, _label, cname in containers:
            if cpos < pos:
                owner = cname
            else:
                break
        return owner

    def _outline_treesitter(self, parser: Any, source: str) -> tuple[str, list[str]]:
        """Tree-sitter outline extraction — implemented in TASK-2261.

        Falls through to the heuristic extractor for now; the outer
        ``except Exception`` guard in :meth:`outline` is not needed for
        this delegation since it cannot raise beyond what the heuristic
        itself already handles.
        """
        return self._outline_heuristic(source)

    # -- reference resolution -------------------------------------------------

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:
        """Build a ``(file_set, lib_dirs)`` pair over the repo file list.

        ``lib_dirs`` is the list of directories named ``lib`` that contain
        at least one ``.pm`` file, used as resolution roots for
        ``Module::Name`` specifiers.

        Args:
            rel_paths: POSIX-style relative paths of every scanned file.

        Returns:
            Opaque ``(frozenset[str], list[str])`` index.
        """
        file_set: set[str] = set()
        lib_dirs: set[str] = set()
        for rp in rel_paths:
            p = PurePosixPath(rp)
            if p.suffix not in (".pm", ".pl", ".t"):
                continue
            posix = p.as_posix()
            file_set.add(posix)
            if p.suffix == ".pm":
                for parent in p.parents:
                    if parent.name == _LIB_DIR_NAME:
                        lib_dirs.add(parent.as_posix())
        return (frozenset(file_set), sorted(lib_dirs))

    def resolve_import(
        self, spec: str, from_file: str, index: Any
    ) -> str | None:
        """Resolve a ``Module::Name`` or ``require:``-prefixed specifier.

        Args:
            spec: Raw import specifier from :meth:`outline` — either a
                ``Module::Name`` (from ``use``/``require``/``use
                parent``/``use base``) or a ``require:``-prefixed relative
                path (from ``require "./lib.pl";``).
            from_file: POSIX-relative path of the importing file.
            index: The ``(file_set, lib_dirs)`` pair from
                :meth:`build_reference_index`.

        Returns:
            The resolved rel path, or ``None`` when unresolved.
        """
        file_set, lib_dirs = index

        if spec.startswith("require:"):
            rel = spec[len("require:"):]
            base = PurePosixPath(from_file).parent
            candidate = self._normalize_posix(base / rel)
            return candidate if candidate in file_set else None

        module_path = spec.replace("::", "/") + ".pm"
        for lib_dir in lib_dirs:
            candidate = f"{lib_dir}/{module_path}"
            if candidate in file_set:
                return candidate
        if module_path in file_set:
            return module_path
        return None

    @staticmethod
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

    @property
    def mode(self) -> str:
        """``"heuristic"`` for now — tree-sitter check added in TASK-2261."""
        return "heuristic"
