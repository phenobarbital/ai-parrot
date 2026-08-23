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

import asyncio
import logging
import mimetypes
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import click
import pymupdf
import yaml
from pydantic import BaseModel, Field

from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS

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
        files = sorted(p for p in walker if p.is_file() and not any(part.startswith(".") for part in p.parts))
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
        f"SOURCE not found: {source!r} is neither an existing file/directory " "nor an http(s) URL."
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
        triage = {key: value for key, value in provenance.model_dump().items() if value is not None}
        if triage:
            payload["triage"] = triage

    if not payload:
        return ""

    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False)
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


# Fields on DocumentMetadata that a flat mapping (e.g. parsed frontmatter)
# can populate directly; everything else lands in `extra`.
_METADATA_FIELD_NAMES: frozenset[str] = frozenset(DocumentMetadata.model_fields) - {"extra"}

# Keys consumed out of the `document_meta` closed shape
# ({source_type, category, type, language, title} — abstract.py:864) that
# map onto a named DocumentMetadata field.
_DOCUMENT_META_NAMED_FIELDS: dict[str, str] = {
    "title": "title",
    "language": "language",
}

# Loader-metadata keys whose *loader-side* meaning differs from the
# DocumentMetadata field of the same name, so they must never be
# auto-mapped by the generic catch-all in _normalize_metadata(). E.g.
# MarkdownLoader emits a top-level "content_type" kwarg meaning the kind
# of chunk ("full_document" / "chapter" / "section" / "summary") — not a
# MIME type. `content_type` and `loader` on DocumentMetadata are always
# derived independently by DocumentAcquirer (mimetypes / loader class
# name), never copied verbatim from loader metadata.
_LOADER_METADATA_RESERVED_KEYS: frozenset[str] = frozenset({"content_type", "loader"})


def _metadata_from_mapping(mapping: dict[str, Any]) -> DocumentMetadata:
    """Build a :class:`DocumentMetadata` from a flat key/value mapping.

    Used for parsed YAML frontmatter: keys matching a named
    ``DocumentMetadata`` field populate it directly; every other key lands
    in ``extra`` — nothing is silently dropped.

    Args:
        mapping: A flat mapping, typically the parsed block returned by
            :func:`split_frontmatter`.

    Returns:
        A populated :class:`DocumentMetadata`.
    """
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in mapping.items():
        if key in _METADATA_FIELD_NAMES and value is not None:
            fields[key] = value
        else:
            extra[key] = value
    if extra:
        fields["extra"] = extra
    return DocumentMetadata(**fields)


def _normalize_metadata(doc_metadata: dict[str, Any]) -> DocumentMetadata:
    """Map a loader ``Document.metadata`` dict into :class:`DocumentMetadata`.

    ``doc_metadata`` follows the canonical FEAT-125 shape produced by
    ``AbstractLoader.create_metadata`` (abstract.py:864): top-level keys
    (``url``, ``source``, ``filename``, ``type``, ``source_type``,
    ``created_at``, ``category``, ``document_meta``, plus loader-specific
    extras) and a closed-shape ``document_meta`` sub-dict (``source_type``,
    ``category``, ``type``, ``language``, ``title``).

    Canonical keys map onto named ``DocumentMetadata`` fields where a
    field exists (``document_meta.title`` → ``title``,
    ``document_meta.language`` → ``language``, top-level ``created_at`` →
    ``created_at``, ``word_count`` → ``word_count``). Everything else —
    including the remainder of ``document_meta`` and any nested
    ``extracted_metadata`` block from ``MarkdownLoader`` — lands in
    ``extra``, nothing is silently dropped.

    Args:
        doc_metadata: The ``metadata`` dict off a loader-returned
            ``Document``.

    Returns:
        A populated :class:`DocumentMetadata`.
    """
    remaining = dict(doc_metadata)
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}

    document_meta = remaining.pop("document_meta", None)
    if isinstance(document_meta, dict):
        for key, value in document_meta.items():
            target = _DOCUMENT_META_NAMED_FIELDS.get(key)
            if target is not None and value:
                fields[target] = value
            elif value is not None:
                extra[f"document_meta.{key}"] = value

    extracted_metadata = remaining.pop("extracted_metadata", None)
    if isinstance(extracted_metadata, dict):
        for key, value in extracted_metadata.items():
            if key == "title" and "title" not in fields and value:
                fields["title"] = value
            elif key == "word_count" and value is not None:
                fields.setdefault("word_count", value)
            elif value is not None:
                extra[f"extracted_metadata.{key}"] = value

    created_at = remaining.pop("created_at", None)
    if created_at:
        fields["created_at"] = str(created_at)

    word_count = remaining.pop("word_count", None)
    if word_count is not None:
        fields.setdefault("word_count", word_count)

    author = remaining.pop("author", None)
    if author:
        fields["author"] = author

    modified_at = remaining.pop("modified_at", None)
    if modified_at:
        fields["modified_at"] = str(modified_at)

    for key, value in remaining.items():
        if key in _METADATA_FIELD_NAMES and key not in _LOADER_METADATA_RESERVED_KEYS and value is not None:
            fields.setdefault(key, value)
        elif value is not None:
            extra[key] = value

    if extra:
        fields["extra"] = extra
    return DocumentMetadata(**fields)


def _validate_extracted_text(text: str, path: Path) -> None:
    """Raise :class:`DocumentAcquisitionError` on unusable extracted text.

    Empty text and text carrying a NUL byte (the mojibake/binary-read-as-
    text tell) must never reach the triage LLM.

    Args:
        text: Extracted text to validate.
        path: Source path, used only for the error message.

    Raises:
        DocumentAcquisitionError: When ``text`` is empty/whitespace-only,
            or contains a ``\\x00`` byte.
    """
    if not text or not text.strip():
        raise DocumentAcquisitionError(f"{path}: extraction produced no text")
    if "\x00" in text:
        raise DocumentAcquisitionError(
            f"{path}: extracted text contains a NUL byte " "(likely a binary file misread as text)"
        )


def _resolve_url_suffix(content_type: str | None, url: str) -> str:
    """Resolve a filename suffix for a downloaded URL.

    Resolution order: the ``Content-Type`` response header (mapped via
    ``mimetypes.guess_extension``), then the URL path's own suffix, then
    ``""``.

    Args:
        content_type: The response's ``Content-Type`` header value, if
            any (may carry a ``; charset=...`` suffix).
        url: The original URL, used as a fallback source for the suffix.

    Returns:
        A lowercased suffix including the dot, or ``""`` when unresolved.
    """
    if content_type:
        mime = content_type.split(";", 1)[0].strip()
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed.lower()
    return Path(urlparse(url).path).suffix.lower()


class DocumentAcquirer:
    """Extracts markdown text + metadata from a :class:`DocumentRef`.

    Plain-text extensions (:data:`PLAIN_TEXT_EXTENSIONS`) are read directly
    off disk with no optional dependency. Everything else is dispatched
    through ``parrot_loaders.factory.get_loader_class``, imported lazily
    (inside :meth:`acquire`, never at module scope) so core ``ai-parrot``
    never hard-depends on the optional ``ai-parrot-loaders`` satellite.

    Attributes:
        fetch_timeout: Timeout, in seconds, for a URL fetch.
        max_bytes: Maximum number of bytes to download for a URL source.
        cache_dir: Optional directory for temporary URL downloads.
    """

    def __init__(
        self,
        *,
        fetch_timeout: float = 30.0,
        max_bytes: int = 100 * 1024 * 1024,
        cache_dir: Path | None = None,
    ) -> None:
        """Initialize the acquirer.

        Args:
            fetch_timeout: Timeout, in seconds, for a URL fetch.
            max_bytes: Maximum number of bytes to download for a URL
                source.
            cache_dir: Optional directory for temporary URL downloads.
        """
        self.fetch_timeout = fetch_timeout
        self.max_bytes = max_bytes
        self.cache_dir = cache_dir

    async def acquire(self, ref: DocumentRef) -> AcquiredDocument:
        """Extract text and metadata for a single resolved document.

        Args:
            ref: The document to acquire.

        Returns:
            The extracted :class:`AcquiredDocument`.

        Raises:
            DocumentAcquisitionError: When the document cannot be decoded
                or fetched. Callers SKIP the document rather than triage
                undecodable content.
        """
        if ref.is_url:
            return await self._acquire_url(ref)
        path = Path(ref.uri)
        if ref.suffix in PLAIN_TEXT_EXTENSIONS:
            return await self._acquire_plaintext(ref, path)
        return await self._acquire_via_loader(ref, path)

    async def _acquire_url(self, ref: DocumentRef) -> AcquiredDocument:
        """Fetch a remote document, then acquire it via the local branches.

        The URL is downloaded to a temp file and dispatched through the
        same plain-text / loader branches used for local documents — there
        is no separate extraction path for remote documents. The temp
        file is always removed, including on error.

        Args:
            ref: The document ref being acquired. ``ref.uri`` must be an
                ``http(s)://`` URL.

        Returns:
            The extracted :class:`AcquiredDocument`. ``metadata.source_url``
            is set to the original URL, and ``.ref`` is the original URL
            ref — never the temp path, which no longer exists once this
            returns.

        Raises:
            DocumentAcquisitionError: On an unsupported scheme, a
                non-2xx response, a size-cap violation, a fetch timeout,
                or an extraction failure on the downloaded content.
        """
        parsed = urlparse(ref.uri)
        if parsed.scheme not in ("http", "https"):
            raise DocumentAcquisitionError(f"Unsupported URL scheme {parsed.scheme!r}: {ref.uri}")
        tmp_path, suffix = await self._download(ref.uri)
        try:
            local = DocumentRef(uri=str(tmp_path), is_url=False, suffix=suffix)
            acquired = await self.acquire(local)
            acquired.metadata.source_url = ref.uri
            acquired.ref = ref  # record the URL, not the temp path
            return acquired
        finally:
            tmp_path.unlink(missing_ok=True)

    async def _download(self, url: str) -> tuple[Path, str]:
        """Fetch *url* into a capped local temp file.

        Streams the response body in chunks — never buffers the whole
        response in memory — aborting once ``self.max_bytes`` is exceeded
        (measured on bytes actually read, not trusted from
        ``Content-Length``). The scheme is re-checked against the
        *final*, post-redirect URL.

        Args:
            url: The ``http(s)://`` URL to fetch.

        Returns:
            ``(path, suffix)`` of the downloaded temp file. ``suffix`` is
            resolved from the ``Content-Type`` response header when
            present, else the URL path's own suffix, else ``""``.

        Raises:
            DocumentAcquisitionError: On an unsupported scheme after
                redirect, a non-2xx status, a size-cap violation, or any
                network/timeout error. Any partially-written temp file is
                removed before raising.
        """
        timeout = aiohttp.ClientTimeout(total=self.fetch_timeout)
        tmp_path: Path | None = None
        success = False
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url) as resp,
            ):
                if not (200 <= resp.status < 300):
                    raise DocumentAcquisitionError(f"{url}: fetch failed with HTTP status {resp.status}")
                final_scheme = urlparse(str(resp.url)).scheme
                if final_scheme not in ("http", "https"):
                    raise DocumentAcquisitionError(
                        "Unsupported URL scheme after redirect " f"{final_scheme!r}: {resp.url}"
                    )

                suffix = _resolve_url_suffix(resp.headers.get("Content-Type"), url)
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=self.cache_dir) as tmp:
                    tmp_path = Path(tmp.name)
                    total = 0
                    async for chunk in resp.content.iter_chunked(65536):
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise DocumentAcquisitionError(f"{url}: response exceeded " f"max_bytes={self.max_bytes}")
                        await asyncio.to_thread(tmp.write, chunk)
            success = True
            return tmp_path, suffix
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise DocumentAcquisitionError(f"{url}: fetch failed: {exc}") from exc
        finally:
            if not success and tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    async def _acquire_plaintext(self, ref: DocumentRef, path: Path) -> AcquiredDocument:
        """Acquire a plain-text/markdown document with no loader backend.

        Args:
            ref: The document ref being acquired.
            path: Local filesystem path for ``ref``.

        Returns:
            The extracted :class:`AcquiredDocument`, with any leading YAML
            frontmatter parsed into ``metadata`` and stripped from ``text``.

        Raises:
            DocumentAcquisitionError: On decode failure or unusable text.
        """
        try:
            raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentAcquisitionError(f"{path}: could not decode as UTF-8 plain text: {exc}") from exc
        except OSError as exc:
            raise DocumentAcquisitionError(f"{path}: could not be read: {exc}") from exc

        frontmatter, body = split_frontmatter(raw)
        metadata = _metadata_from_mapping(frontmatter) if frontmatter else DocumentMetadata()

        guessed_type, _ = mimetypes.guess_type(str(path))
        metadata.content_type = metadata.content_type or guessed_type or "text/plain"
        metadata.loader = "plaintext"

        _validate_extracted_text(body, path)
        return AcquiredDocument(ref=ref, text=body, metadata=metadata)

    async def _acquire_via_loader(self, ref: DocumentRef, path: Path) -> AcquiredDocument:
        """Acquire a document through a lazily-imported ``parrot_loaders`` loader.

        Args:
            ref: The document ref being acquired.
            path: Local filesystem path for ``ref``.

        Returns:
            The extracted :class:`AcquiredDocument`.

        Raises:
            DocumentAcquisitionError: When ``ai-parrot-loaders`` is not
                installed, the loader fails, or extraction yields no
                usable text.
        """
        try:
            from parrot_loaders.factory import get_loader_class
        except ImportError as exc:
            logger.warning(
                "No loader for %s: ai-parrot-loaders is not installed " "(only %s are readable without it)",
                path,
                ", ".join(sorted(PLAIN_TEXT_EXTENSIONS)),
            )
            raise DocumentAcquisitionError(
                f"{path}: ai-parrot-loaders is not installed; cannot extract " f"{ref.suffix or 'this file type'}"
            ) from exc

        loader_cls = get_loader_class(ref.suffix)
        loader = loader_cls(str(path))
        try:
            docs = await loader._load(str(path))
        except Exception as exc:
            raise DocumentAcquisitionError(f"{path}: loader extraction failed: {exc}") from exc

        if not docs:
            raise DocumentAcquisitionError(f"{path}: loader extracted no content")

        text = docs[0].page_content
        _validate_extracted_text(text, path)

        metadata = _normalize_metadata(docs[0].metadata)
        guessed_type, _ = mimetypes.guess_type(str(path))
        metadata.content_type = metadata.content_type or guessed_type
        metadata.loader = loader.__class__.__name__

        if ref.suffix == ".pdf":
            try:
                pdf = pymupdf.open(str(path))
                try:
                    metadata.page_count = pdf.page_count
                finally:
                    pdf.close()
            except Exception as exc:  # noqa: BLE001 — page count is nice-to-have, never fatal
                logger.warning("Could not read page count for %s: %s", path, exc)

        return AcquiredDocument(ref=ref, text=text, metadata=metadata)
