"""ADR citations, evidence refs and freshness checks (FEAT-578 Module 3).

Citation extraction is Python-only and deliberately narrow: comment tokens
from :mod:`tokenize` and docstrings from :mod:`ast`. An executable string
literal is data, not rationale, so ``x = "see ADR-42"`` is never a citation
(spec §2).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import logging
import tokenize
import warnings
from dataclasses import dataclass
from pathlib import Path

from parrot.knowledge.wiki.decisions.models import (
    ADR_PARSE_FAILED,
    ADR_PATH_OUTSIDE_ROOT,
    ADR_SOURCE_UNAVAILABLE,
    DecisionDiagnostic,
    DecisionError,
    EvidenceRef,
)
from parrot.knowledge.wiki.decisions.parser import normalize_adr_alias
from parrot.knowledge.wiki.symbols import sym_concept_id

logger = logging.getLogger(__name__)

#: Freshness of one stored evidence span against the current source.
#: ``unverified`` means "no local root to check against" and is NEVER
#: upgraded to ``current`` (spec §2).
FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
FRESHNESS_MISSING = "missing"
FRESHNESS_UNVERIFIED = "unverified"

_SCOPED_NODE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_DOCSTRING_NODE_TYPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class Citation:
    """One resolved ``ADR-<n>`` reference in a Python source file."""

    alias: str  # canonical "ADR-42"
    rel_path: str
    line: int  # 1-based line the reference text sits on
    page_id: str  # sym:<rel>#<qualname>, or file:<rel> for module scope
    qualname: str | None  # None == file scope
    start_line: int  # owning span, 1-based inclusive
    end_line: int
    kind: str  # "comment" | "document" (docstring)


def sha1_of_span(text: str) -> str:
    """SHA-1 of the exact bytes an evidence span was read from."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324


def _symbol_ranges(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Every def/class as ``(qualname, start_line, end_line)``, 1-based inclusive."""
    ranges: list[tuple[str, int, int]] = []

    def _walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPED_NODE_TYPES):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                start_line = child.lineno
                end_line = child.end_lineno if child.end_lineno is not None else child.lineno
                ranges.append((qualname, start_line, end_line))
                _walk(child, qualname)
            else:
                _walk(child, prefix)

    _walk(tree, "")
    return ranges


def _owner_for_line(ranges: list[tuple[str, int, int]], line: int) -> tuple[str, int, int] | None:
    """Innermost symbol span containing ``line``, or ``None`` for file scope."""
    containing = [r for r in ranges if r[1] <= line <= r[2]]
    if not containing:
        return None
    return min(containing, key=lambda r: r[2] - r[1])


def extract_python_citations(rel_path: str, source: str) -> tuple[list[Citation], list[DecisionDiagnostic]]:
    """Find ADR references in comments and docstrings of one Python file.

    Module-level comments attach to the file and are reported as file scope
    (``page_id='file:<rel>'``, ``qualname=None``) — spec §2.

    Returns:
        ``(citations, diagnostics)``. A file that cannot be tokenized or
        parsed yields an ``ADR_PARSE_FAILED`` diagnostic and no citations,
        never an exception: one bad file must not abort a whole sync.
    """
    try:
        with warnings.catch_warnings():
            # Scanned files are third-party to the wiki: their own
            # SyntaxWarnings (e.g. an invalid escape sequence) are the
            # author's problem, not a build diagnostic, and without a
            # filename they surface as an unattributable ``<unknown>:NN``.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source, filename=rel_path or "<unknown>")
    except SyntaxError as exc:
        return [], [DecisionDiagnostic(code=ADR_PARSE_FAILED, message=f"Python syntax error: {exc}", path=rel_path)]

    ranges = _symbol_ranges(tree)
    citations: list[Citation] = []

    def _make_citation(alias: str, line: int, kind: str) -> Citation:
        owner = _owner_for_line(ranges, line)
        if owner is None:
            return Citation(
                alias=alias,
                rel_path=rel_path,
                line=line,
                page_id=f"file:{rel_path}",
                qualname=None,
                start_line=1,
                end_line=len(source.splitlines()) or 1,
                kind=kind,
            )
        qualname, start_line, end_line = owner
        return Citation(
            alias=alias,
            rel_path=rel_path,
            line=line,
            page_id=sym_concept_id(rel_path, qualname),
            qualname=qualname,
            start_line=start_line,
            end_line=end_line,
            kind=kind,
        )

    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            alias = normalize_adr_alias(token.string)
            if alias is None:
                continue
            citations.append(_make_citation(alias, token.start[0], "comment"))
    except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
        return [], [DecisionDiagnostic(code=ADR_PARSE_FAILED, message=f"tokenize error: {exc}", path=rel_path)]

    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_NODE_TYPES):
            continue
        docstring = ast.get_docstring(node)
        if not docstring:
            continue
        alias = normalize_adr_alias(docstring)
        if alias is None:
            continue
        if isinstance(node, ast.Module):
            line = 1
            citations.append(
                Citation(
                    alias=alias,
                    rel_path=rel_path,
                    line=line,
                    page_id=f"file:{rel_path}",
                    qualname=None,
                    start_line=1,
                    end_line=len(source.splitlines()) or 1,
                    kind="document",
                )
            )
            continue
        # node is FunctionDef / AsyncFunctionDef / ClassDef.
        docstring_node = node.body[0] if node.body else None
        line = docstring_node.lineno if docstring_node is not None else node.lineno
        citations.append(_make_citation(alias, line, "document"))

    return citations, []


def build_evidence(rel_path: str, source: str, page_id: str, start_line: int, end_line: int, kind: str) -> EvidenceRef:
    """Construct one ``EvidenceRef`` over a 1-based inclusive line span."""
    lines = source.splitlines()
    excerpt = "\n".join(lines[start_line - 1 : end_line])
    return EvidenceRef(
        page_id=page_id,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        source_sha1=sha1_of_span(excerpt),
        excerpt=excerpt,
        kind=kind,
    )


def _resolve_confined(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` under ``root``, refusing anything that escapes it.

    Raises:
        DecisionError: ``ADR_PATH_OUTSIDE_ROOT``.
    """
    resolved_root = root.resolve()
    candidate = (resolved_root / rel_path).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise DecisionError(ADR_PATH_OUTSIDE_ROOT, f"path escapes root: {rel_path!r}")
    return candidate


def _read_span_sync(path: Path, start_line: int, end_line: int) -> str | None:
    """Read one 1-based inclusive span, or ``None`` when the file is gone."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[start_line - 1 : end_line])


async def verify_freshness(root: Path | None, evidence: EvidenceRef) -> tuple[str, DecisionDiagnostic | None]:
    """Check one evidence span against the current bytes on disk.

    Args:
        root: Local project root, or ``None`` for a store-only/remote
            namespace. ``None`` yields ``unverified`` — spec §2: "If no
            project root is available, report unverified, never current."

    Returns:
        ``(freshness, diagnostic_or_None)``. A changed hash is ``stale``, an
        absent file is ``missing``; neither rewrites the stored record —
        reads never mutate review status (spec §2).
    """
    if root is None:
        return FRESHNESS_UNVERIFIED, None

    path = _resolve_confined(root, evidence.rel_path)
    text = await asyncio.to_thread(_read_span_sync, path, evidence.start_line, evidence.end_line)
    if text is None:
        return FRESHNESS_MISSING, DecisionDiagnostic(
            code=ADR_SOURCE_UNAVAILABLE,
            message=f"source file missing: {evidence.rel_path!r}",
            path=evidence.rel_path,
        )

    current_sha1 = sha1_of_span(text)
    if current_sha1 != evidence.source_sha1:
        return FRESHNESS_STALE, DecisionDiagnostic(
            code=ADR_SOURCE_UNAVAILABLE,
            message=f"evidence hash mismatch for {evidence.rel_path!r}",
            path=evidence.rel_path,
        )
    return FRESHNESS_CURRENT, None
