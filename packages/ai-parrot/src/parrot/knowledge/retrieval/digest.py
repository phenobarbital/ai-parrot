"""Derived digest computation over served bytes (spec §3.5.1, OQ-7, TASK-2273).

L0 does not carry a per-node digest — ``UniversalNode`` has none, and the
only stored hash is the per-*file* ``sha1`` in the SQLite ``files`` table
(``SQLitePersistence.is_stale``). Rather than change L0 (out of scope,
spec §1.2), ``Evidence.digest`` is computed at request time over the bytes
actually served, so INV-2 closure holds by construction for the returned
unit rather than trusting an index field.

This module is a pure function: it takes bytes it is given and hashes them.
It performs **no I/O** — reading content at a pinned rev (``git cat-file``)
is TASK-2275's responsibility.
"""

from __future__ import annotations

import hashlib
import logging
from enum import StrEnum

from parrot.knowledge.graphindex.schema import UniversalNode

logger = logging.getLogger(__name__)


class DigestScope(StrEnum):
    """Granularity a derived digest was computed at (spec §3.5.1).

    Not every L0 node has a line span, so the granularity is declared
    rather than assumed — a coarser scope is a real (visible) weakening of
    invalidation precision, not a silent one.

    Attributes:
        SPAN: ``sha256`` of the node's exact source line range — the strong
            case. Applies to ``SYMBOL`` nodes with
            ``domain_tags["lineno"]``/``["end_lineno"]`` (classes,
            functions).
        FILE: The file's own ``sha1`` (from the ``files`` table). Fallback
            for nodes with no line span but a backing file — ``RATIONALE``
            nodes (no lineno, RQ-4) and module nodes.
        SUMMARY: ``sha256`` of ``title + summary``. For synthetic nodes with
            no source file at all (``CONCEPT``, ``WIKI_PAGE``).
    """

    SPAN = "span"
    FILE = "file"
    SUMMARY = "summary"


def _read_span_bytes(source_bytes: bytes, lineno: int, end_lineno: int) -> bytes:
    """Slice a 1-indexed, inclusive line range out of already-loaded bytes.

    Mirrors ``SQLiteGraphReader._read_span``'s indexing convention exactly
    (``lines[lineno - 1 : end]``) so a `DigestScope.SPAN` digest covers
    precisely the bytes the retriever will later serve as
    ``ContextUnit.text`` — a mismatch here would silently break INV-2 while
    every test still passed.

    Args:
        source_bytes: The full file content, already read by the caller.
        lineno: 1-based start line (inclusive).
        end_lineno: 1-based end line (inclusive).

    Returns:
        The raw byte slice for that line range.
    """
    lines = source_bytes.splitlines(keepends=True)
    return b"".join(lines[lineno - 1 : end_lineno])


def derive_digest(
    node: UniversalNode,
    *,
    source_bytes: bytes | None,
    file_sha1: str | None,
) -> tuple[str, DigestScope]:
    """Compute ``(digest, DigestScope)`` for `node` over the bytes served.

    Pure function — performs no file or network I/O. The caller supplies
    whatever bytes/hash are available; this function only decides which
    granularity applies and hashes accordingly.

    Args:
        node: The L0 node evidence is being produced for.
        source_bytes: Full content of ``node.source_uri``, if the caller has
            it loaded — required for `DigestScope.SPAN`.
        file_sha1: The file's per-file ``sha1`` from the ``files`` table, if
            available — used for `DigestScope.FILE`.

    Returns:
        A ``(digest, scope)`` tuple. ``digest`` is a hex digest string;
        ``scope`` records the granularity it was computed at.
    """
    domain_tags = node.domain_tags or {}
    lineno = domain_tags.get("lineno")
    end_lineno = domain_tags.get("end_lineno")

    if lineno is not None and end_lineno is not None and source_bytes is not None:
        span_bytes = _read_span_bytes(source_bytes, int(lineno), int(end_lineno))
        digest = hashlib.sha256(span_bytes).hexdigest()
        return digest, DigestScope.SPAN

    if file_sha1 is not None:
        return file_sha1, DigestScope.FILE

    summary_text = f"{node.title}\n{node.summary or ''}"
    digest = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()
    return digest, DigestScope.SUMMARY
