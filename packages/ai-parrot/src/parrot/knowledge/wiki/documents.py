"""Document acquisition foundations for `wikitoolkit ingest` (FEAT-451).

This module widens ``wikitoolkit ingest`` from "a directory of plain-text
files" into "a directory, a single document, or a remote URL", acquiring
content through the loader layer (``parrot_loaders``) rather than a naive
``read_text()``. It carries no dependency on the optional
``ai-parrot-loaders`` satellite at import time — that dependency is only
reached lazily, from :class:`DocumentAcquirer` (added in a later task).

This module currently implements Module 1 of the FEAT-451 spec: the shared
Pydantic models plus :func:`resolve_sources`, which turns a CLI ``SOURCE``
argument into a list of :class:`DocumentRef`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click
import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger("parrot.knowledge.wiki.documents")

# Explicit, fixed order — this tuple IS the determinism guarantee for
# render_frontmatter(). Never iterate model_dump() insertion order and
# never sort_keys=True over the whole document.
_FRONTMATTER_FIELD_ORDER: tuple[str, ...] = (
    "title",
    "author",
    "created_at",
    "modified_at",
    "page_count",
    "word_count",
    "language",
    "content_type",
    "source_url",
    "loader",
)

# THE REGEX PRECEDENT — mirrors
# parrot_loaders.markdown.MarkdownLoader._extract_metadata_from_markdown
# (markdown.py:364-372). Tolerant of CRLF via the \r? group.
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


class DocumentRef(BaseModel):
    """One resolved ingestion source: a local file or a remote URL.

    Attributes:
        uri: Absolute filesystem path, or an http(s) URL.
        is_url: True when ``uri`` is a remote URL.
        suffix: Lowercased extension including the dot, or "" when unknown.
    """

    uri: str
    is_url: bool = False
    suffix: str = ""


class DocumentMetadata(BaseModel):
    """Normalized, loader-agnostic metadata about a source document.

    Every field is optional: a plain ``.txt`` yields almost none, a PDF
    yields most. Unknown loader-specific keys land in ``extra`` and are
    rendered under an ``extra:`` frontmatter block, never lost.

    Attributes:
        title: Document title, when known.
        author: Document author, when known.
        created_at: ISO-8601 creation timestamp, when parseable.
        modified_at: ISO-8601 modification timestamp, when parseable.
        page_count: Number of pages, when applicable (e.g. PDF).
        word_count: Word count, when computable.
        language: Detected or declared document language.
        content_type: MIME type, e.g. ``"application/pdf"``.
        source_url: Originating URL, set only for URL sources.
        loader: Name of the loader used to extract this document, e.g.
            ``"MarkdownLoader"``.
        extra: Any additional loader-specific metadata that does not map
            onto the fields above.
    """

    title: str | None = None
    author: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    page_count: int | None = None
    word_count: int | None = None
    language: str | None = None
    content_type: str | None = None
    source_url: str | None = None
    loader: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AcquiredDocument(BaseModel):
    """Text + metadata produced by the acquisition layer.

    Attributes:
        ref: The :class:`DocumentRef` this document was acquired from.
        text: Extracted markdown/plain text. Any leading YAML frontmatter
            has already been STRIPPED — whatever it carried is already
            folded into ``metadata``.
        metadata: Normalized :class:`DocumentMetadata` for this document.
    """

    ref: DocumentRef
    text: str
    metadata: DocumentMetadata


class TriageProvenance(BaseModel):
    """FEAT-402 decision trail, rendered into the page frontmatter.

    Built from the ``ManifestDocEntry`` (review.py:135) already handed to
    ``WikiIngestOrchestrator.ingest()`` as ``triage=``, plus the
    ``charter_version`` argument that call already receives. Introduces no
    new plumbing — it only surfaces what ``ingest()`` already holds.

    Attributes:
        composite_score: Triage router's composite score for this source.
        decision: One of ``"admit"``, ``"archive"``, ``"discard"``.
        decision_source: One of ``"heuristic"``, ``"model"``, ``"human"``,
            ``"auto"``.
        charter_version: Version of the ingestion charter used for this run.
    """

    composite_score: float | None = None
    decision: str | None = None
    decision_source: str | None = None
    charter_version: str | None = None


class DocumentAcquisitionError(Exception):
    """Raised when a document cannot be decoded or fetched.

    Callers SKIP the document (warn + record) rather than triaging
    undecodable content — never let mojibake reach the LLM.
    """


def resolve_sources(source: str, *, recursive: bool = True) -> list[DocumentRef]:
    """Resolve a CLI ``SOURCE`` argument into concrete document refs.

    Accepts a directory (recursive walk — same rules as the existing
    ``_discover_documents``: dotfiles and dot-directories skipped), a
    single file path, or an http(s) URL.

    Args:
        source: A directory path, a file path, or an ``http(s)://`` URL.
        recursive: When ``source`` is a directory, whether to walk it
            recursively (``rglob``) or only its immediate children
            (``glob``). Ignored for files and URLs.

    Returns:
        A list of :class:`DocumentRef`. For a directory this is sorted by
        path, matching the legacy ``_discover_documents`` ordering. For a
        file or URL this is a single-element list.

    Raises:
        click.ClickException: When ``source`` is neither an existing
            local path nor an http(s) URL.
    """
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        suffix = Path(parsed.path).suffix.lower()
        return [DocumentRef(uri=source, is_url=True, suffix=suffix)]

    path = Path(source)
    if path.is_dir():
        walker = path.rglob("*") if recursive else path.glob("*")
        files = sorted(
            p
            for p in walker
            if p.is_file() and not any(part.startswith(".") for part in p.parts)
        )
        return [
            DocumentRef(
                uri=str(p.resolve()),
                is_url=False,
                suffix=p.suffix.lower(),
            )
            for p in files
        ]

    if path.is_file():
        resolved = path.resolve()
        return [
            DocumentRef(
                uri=str(resolved),
                is_url=False,
                suffix=resolved.suffix.lower(),
            )
        ]

    raise click.ClickException(
        f"SOURCE not found: {source!r} is neither an existing file/directory "
        "nor an http(s) URL."
    )


def render_frontmatter(
    metadata: DocumentMetadata,
    provenance: TriageProvenance | None = None,
) -> str:
    """Render deterministic YAML frontmatter for a wiki page body.

    Fixed key order, sorted collections, ``None`` fields omitted, and a
    trailing ``---\\n`` — same determinism contract as
    ``parrot.knowledge.okf.frontmatter.project_frontmatter``: same input
    always produces byte-identical output. Returns ``""`` when every field
    is ``None`` (never emits an empty ``---\\n---\\n`` block).

    Descriptive document fields come first; ``provenance`` (when given and
    non-empty) is rendered under a single nested ``triage:`` key so the
    descriptive and audit halves can never collide on a key name.

    Args:
        metadata: Descriptive document metadata to render.
        provenance: Optional FEAT-402 triage decision trail to render
            under a nested ``triage:`` key.

    Returns:
        A YAML frontmatter block (``---\\n...\\n---\\n\\n``), or ``""`` when
        ``metadata`` and ``provenance`` are both fully empty.
    """
    payload: dict[str, Any] = {}
    for field in _FRONTMATTER_FIELD_ORDER:
        value = getattr(metadata, field)
        if value is not None:
            payload[field] = value
    if metadata.extra:
        payload["extra"] = {key: metadata.extra[key] for key in sorted(metadata.extra)}
    if provenance is not None:
        triage = {
            key: value
            for key, value in provenance.model_dump().items()
            if value is not None
        }
        if triage:
            payload["triage"] = triage

    if not payload:
        return ""

    body = yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{body}---\n\n"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split leading YAML frontmatter off a text document.

    Returns ``(parsed_mapping, body_without_frontmatter)``, or ``({},
    text)`` unchanged when there is no leading ``---`` block, when the
    block never terminates, or when it does not parse as a YAML mapping —
    malformed frontmatter is never a hard error, it is simply left inline.

    Args:
        text: Raw document text, possibly carrying leading YAML
            frontmatter.

    Returns:
        A ``(mapping, body)`` tuple. ``mapping`` is ``{}`` and ``body`` is
        ``text`` unchanged whenever the leading block cannot be parsed as
        a YAML mapping.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text

    if not isinstance(parsed, dict):
        return {}, text

    return parsed, text[match.end() :]
