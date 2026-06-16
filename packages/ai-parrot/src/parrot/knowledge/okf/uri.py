"""Knowledge URI scheme — unified cross-index addressing (FEAT-239).

Provides a shared ``knowledge://`` URI scheme for referencing nodes across
PageIndex and GraphIndex without using ArangoDB-specific keys or PageIndex
tree paths directly.

URI format:
    knowledge://<index_type>/<identifier>

Examples:
    knowledge://graphindex/sym-builder-abc
    knowledge://pageindex/my-tree/concept-id

Legacy ``pageindex://`` URIs are also parsed for backward compatibility.
No migration of existing documents is performed in this FEAT.

Design notes:
- Pure functions, no I/O, no external dependencies.
- ``parse_uri()`` is the inverse of ``build_uri()`` for knowledge:// URIs.
- Legacy pageindex:// URIs keep the full ``tree/node`` as identifier —
  callers are responsible for further parsing.
"""


_KNOWLEDGE_SCHEME = "knowledge"
_LEGACY_PAGEINDEX_SCHEME = "pageindex"
_KNOWN_SCHEMES = {_KNOWLEDGE_SCHEME, _LEGACY_PAGEINDEX_SCHEME}


def build_uri(index_type: str, identifier: str) -> str:
    """Build a ``knowledge://`` URI for cross-index addressing.

    Args:
        index_type: Index namespace, e.g. ``"graphindex"`` or ``"pageindex"``.
        identifier: Node identifier within the index.  May contain slashes.

    Returns:
        URI string of the form ``knowledge://<index_type>/<identifier>``.

    Raises:
        ValueError: If ``index_type`` or ``identifier`` is empty.

    Examples:
        >>> build_uri("graphindex", "node-123")
        'knowledge://graphindex/node-123'
        >>> build_uri("pageindex", "tree/concept-id")
        'knowledge://pageindex/tree/concept-id'
    """
    if not index_type:
        raise ValueError("index_type must be non-empty")
    if not identifier:
        raise ValueError("identifier must be non-empty")
    return f"knowledge://{index_type}/{identifier}"


def parse_uri(uri: str) -> tuple[str, str]:
    """Parse a ``knowledge://`` or legacy ``pageindex://`` URI.

    Returns a ``(index_type, identifier)`` tuple:
    - For ``knowledge://`` URIs: ``index_type`` is the first path segment;
      ``identifier`` is everything after the first ``/``.
    - For ``pageindex://`` URIs: ``index_type = "pageindex"``;
      ``identifier`` is the entire path (``tree/node``).

    Args:
        uri: URI string to parse.

    Returns:
        Tuple of ``(index_type, identifier)``.

    Raises:
        ValueError: If the URI has no scheme, a malformed path, or an
            unrecognised scheme.

    Examples:
        >>> parse_uri("knowledge://graphindex/node-123")
        ('graphindex', 'node-123')
        >>> parse_uri("pageindex://my-tree/my-node")
        ('pageindex', 'my-tree/my-node')
    """
    if "://" not in uri:
        raise ValueError(f"Invalid URI (no scheme separator '://'): {uri!r}")

    scheme, rest = uri.split("://", 1)

    if scheme == _KNOWLEDGE_SCHEME:
        # knowledge://graphindex/node-123  →  ("graphindex", "node-123")
        # knowledge://pageindex/tree/concept  →  ("pageindex", "tree/concept")
        idx_type, _, identifier = rest.partition("/")
        if not idx_type:
            raise ValueError(f"Malformed knowledge URI (empty index_type): {uri!r}")
        if not identifier:
            raise ValueError(f"Malformed knowledge URI (empty identifier): {uri!r}")
        return (idx_type, identifier)

    if scheme == _LEGACY_PAGEINDEX_SCHEME:
        # pageindex://tree/node  →  ("pageindex", "tree/node")
        return (_LEGACY_PAGEINDEX_SCHEME, rest)

    raise ValueError(
        f"Unrecognised URI scheme: {scheme!r}. "
        f"Expected one of: {sorted(_KNOWN_SCHEMES)}"
    )


__all__ = [
    "build_uri",
    "parse_uri",
]
